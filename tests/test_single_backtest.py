import unittest
from unittest.mock import patch
import sqlite3
import pandas as pd
import numpy as np
from src.core.backtest import simulate_stock_trades, run_single_stock_backtest

class TestSingleStockBacktest(unittest.TestCase):
    def setUp(self):
        n = 300
        dates = [f"2023-{(i//30)+1:02d}-{(i%28)+1:02d}" for i in range(n)]
        dates = sorted(list(set(dates)))[:250]
        n = len(dates)
        prices = [100.0 + i * 0.2 for i in range(n)]
        self.df = pd.DataFrame({
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 2 for p in prices],
            "close": prices,
            "volume": [10000] * n,
            "ma50": [p - 2 for p in prices],
            "ma200": [p - 10 for p in prices],
            "rsi": [50] * n,
            "atr": [2.0] * n,
        }, index=dates)

    def test_simulate_stock_trades(self):
        self.df["entry_sig"] = False
        self.df.loc[self.df.index[10], "entry_sig"] = True
        self.df["entry_rank"] = 1.0

        trades, curve, stats = simulate_stock_trades(self.df, strategy="dip")
        self.assertIsInstance(trades, list)
        self.assertIsInstance(stats, dict)
        self.assertIn("win_rate", stats)
        self.assertIn("profit_factor", stats)
        self.assertIn("total_return", stats)
        self.assertIn("buy_and_hold_return", stats)
        self.assertIn("trades_count", stats)
        self.assertIn("avg_gain_pct", stats)
        self.assertIn("avg_loss_pct", stats)
        self.assertIn("avg_days_held", stats)

    def _one_trade_df(self):
        self.df["entry_sig"] = False
        self.df.loc[self.df.index[10], "entry_sig"] = True
        self.df["entry_rank"] = 1.0
        self.df.loc[self.df.index[20], "rsi"] = 80.0  # RSI-exit så att affären stängs
        return self.df

    def test_cost_model_is_applied_by_default(self):
        df = self._one_trade_df()
        free, _, _ = simulate_stock_trades(df, strategy="dip", fee_pct=0.0)
        modeled, _, _ = simulate_stock_trades(df, strategy="dip")             # courtage + spread
        us, _, _ = simulate_stock_trades(df, strategy="dip", market="nasdaq")  # + valutaväxling
        r = lambda t: [x for x in t if not x["open"]][0]["return_pct"]
        self.assertLess(r(modeled), r(free))
        self.assertLess(r(us), r(modeled))

    def test_entry_allowed_false_blocks_trade(self):
        df = self._one_trade_df()
        blocked = pd.Series(False, index=pd.to_datetime(["2000-01-01"]))  # ffill -> False över hela perioden
        # df-datumen i fixturen är skenbara strängar; använd riktiga datum för reindex
        df.index = pd.bdate_range("2023-01-02", periods=len(df)).strftime("%Y-%m-%d")
        trades, _, _ = simulate_stock_trades(df, strategy="dip", entry_allowed=blocked)
        self.assertEqual(trades, [])
        allowed = pd.Series(True, index=pd.to_datetime(["2000-01-01"]))
        trades, _, _ = simulate_stock_trades(df, strategy="dip", entry_allowed=allowed)
        self.assertGreaterEqual(len(trades), 1)

    def test_stop_loss_exit(self):
        self.df["entry_sig"] = False
        self.df.loc[self.df.index[10], "entry_sig"] = True
        # Drop price sharply on day 11 to trigger stop loss
        self.df.loc[self.df.index[11], "low"] = 50.0
        self.df.loc[self.df.index[11], "close"] = 50.0

        trades, curve, stats = simulate_stock_trades(self.df, strategy="dip")
        closed = [t for t in trades if not t["open"]]
        self.assertTrue(len(closed) >= 1)
        self.assertEqual(closed[0]["exit_reason"], "Stop loss")

    def test_rsi_exit(self):
        self.df["entry_sig"] = False
        self.df.loc[self.df.index[10], "entry_sig"] = True
        # Set high RSI on day 12
        self.df.loc[self.df.index[12], "rsi"] = 75.0

        trades, curve, stats = simulate_stock_trades(self.df, strategy="dip")
        closed = [t for t in trades if not t["open"]]
        self.assertTrue(len(closed) >= 1)
        self.assertIn("RSI-exit", closed[0]["exit_reason"])

    def test_target_exit(self):
        self.df["entry_sig"] = False
        self.df.loc[self.df.index[10], "entry_sig"] = True
        # Surge high price on day 12 without RSI triggering
        self.df.loc[self.df.index[12], "rsi"] = 50.0
        self.df.loc[self.df.index[12], "high"] = 200.0

        trades, curve, stats = simulate_stock_trades(self.df, strategy="dip")
        closed = [t for t in trades if not t["open"]]
        self.assertTrue(len(closed) >= 1)
        self.assertEqual(closed[0]["exit_reason"], "Målkurs nådd")

    def test_time_exit(self):
        self.df["entry_sig"] = False
        self.df.loc[self.df.index[10], "entry_sig"] = True
        # Flat prices, normal RSI -> should exit after default_max_days (20 days for dip)
        trades, curve, stats = simulate_stock_trades(self.df, strategy="dip")
        closed = [t for t in trades if not t["open"]]
        self.assertTrue(len(closed) >= 1)
        self.assertIn("Tids-exit", closed[0]["exit_reason"])

    def test_run_single_stock_backtest_missing_symbol(self):
        res = run_single_stock_backtest("NON_EXISTENT_SYMBOL_XYZ")
        self.assertIn("error", res)

    @patch("src.core.backtest.get_db")
    def test_run_single_stock_backtest_success(self, mock_get_db):
        conn = sqlite3.connect(":memory:")
        mock_get_db.return_value = conn
        conn.execute("""
            CREATE TABLE history (
                symbol TEXT, date TEXT, open REAL, high REAL, low REAL,
                close REAL, volume INTEGER, ma50 REAL, ma200 REAL, rsi REAL, atr REAL
            )
        """)
        for date, row in self.df.iterrows():
            conn.execute(
                "INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("TEST.ST", date, row["open"], row["high"], row["low"], row["close"],
                 row["volume"], row["ma50"], row["ma200"], row["rsi"], row["atr"])
            )
        conn.commit()

        res = run_single_stock_backtest("TEST.ST", strategy="dip", years=1)
        self.assertNotIn("error", res)
        self.assertEqual(res["symbol"], "TEST.ST")
        self.assertEqual(res["strategy"], "dip")
        self.assertIn("stats", res)
        self.assertIn("trades", res)
        self.assertIn("chart", res)

if __name__ == "__main__":
    unittest.main()
