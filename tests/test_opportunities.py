import unittest
from unittest.mock import patch
import sqlite3
import pandas as pd
from src.core.signals import calculate_trade_levels, scan_opportunities

class TestTradeLevels(unittest.TestCase):
    def test_calculate_trade_levels_dip(self):
        close = 100.0
        atr = 3.0
        levels = calculate_trade_levels(close, atr, strategy="dip")
        self.assertIn("entry_price", levels)
        self.assertIn("stop_loss", levels)
        self.assertIn("target_price", levels)
        self.assertIn("risk_pct", levels)
        self.assertIn("reward_pct", levels)
        self.assertIn("risk_reward_ratio", levels)
        self.assertIn("rr_label", levels)
        self.assertEqual(levels["entry_price"], 100.0)
        self.assertEqual(levels["stop_loss"], 100.0 - 2.2 * 3.0)  # 93.4
        self.assertEqual(levels["target_price"], 100.0 + 3.5 * 3.0)  # 110.5
        self.assertTrue(levels["stop_loss"] < close)
        self.assertTrue(levels["target_price"] > close)
        self.assertTrue(levels["risk_reward_ratio"] > 1.0)
        self.assertEqual(levels["rr_label"], f"1 : {levels['risk_reward_ratio']:g}")

    def test_calculate_trade_levels_momentum(self):
        close = 200.0
        atr = 5.0
        levels = calculate_trade_levels(close, atr, strategy="momentum")
        self.assertEqual(levels["stop_loss"], round(200.0 - 2.5 * 5.0, 2))
        self.assertEqual(levels["target_price"], round(200.0 + 5.0 * 5.0, 2))
        self.assertTrue(levels["risk_reward_ratio"] > 1.0)

    def test_calculate_trade_levels_trend(self):
        close = 50.0
        atr = 1.0
        levels = calculate_trade_levels(close, atr, strategy="trend")
        self.assertEqual(levels["stop_loss"], round(50.0 - 3.0 * 1.0, 2))
        self.assertEqual(levels["target_price"], round(50.0 + 6.5 * 1.0, 2))
        self.assertTrue(levels["risk_reward_ratio"] > 1.0)


class TestScanOpportunities(unittest.TestCase):
    def setUp(self):
        n = 150
        dates = [f"2023-{(i // 25) + 1:02d}-{(i % 25) + 1:02d}" for i in range(n)]
        prices = [100.0 + i * 0.5 for i in range(n)]
        self.df_history = pd.DataFrame({
            "symbol": ["ABB.ST"] * n,
            "date": dates,
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 2 for p in prices],
            "close": prices,
            "volume": [10000] * n,
            "ma50": [p - 5 for p in prices],
            "ma200": [p - 20 for p in prices],
            "rsi": [50.0] * n,
            "atr": [2.0] * n,
        })
        # Set last row RSI <= 30 to trigger dip entry_sig (close > ma200 and rsi <= 30)
        self.df_history.loc[self.df_history.index[-1], "rsi"] = 28.0

    @patch("src.core.signals.get_db")
    @patch("src.core.signals.OMXS_50", {"ABB.ST": "ABB"})
    @patch("src.core.signals.NASDAQ_100", {})
    def test_scan_opportunities_detects_dip(self, mock_get_db):
        conn = sqlite3.connect(":memory:")
        mock_get_db.return_value = conn
        self.df_history.to_sql("history", conn, index=False)

        opps = scan_opportunities(market="omxs", strategy_filter="dip")
        self.assertEqual(len(opps), 1)
        opp = opps[0]
        self.assertEqual(opp["symbol"], "ABB.ST")
        self.assertEqual(opp["name"], "ABB")
        self.assertEqual(opp["market"], "OMX")
        self.assertEqual(opp["currency"], "kr")
        self.assertEqual(opp["strategy"], "dip")
        self.assertEqual(opp["strategy_name"], "Kvalitets-dipp i upptrend")
        self.assertIn("Översåld dipp", opp["reason"])
        self.assertIn("levels", opp)
        self.assertIn("edge", opp)
        self.assertIn("score", opp)
        self.assertIn("win_rate", opp["edge"])
        self.assertIn("profit_factor", opp["edge"])

    @patch("src.core.signals.get_db")
    @patch("src.core.signals.OMXS_50", {"ABB.ST": "ABB"})
    @patch("src.core.signals.NASDAQ_100", {})
    def test_scan_opportunities_strategy_filter_excludes(self, mock_get_db):
        conn = sqlite3.connect(":memory:")
        mock_get_db.return_value = conn
        self.df_history.to_sql("history", conn, index=False)

        # Filtering by momentum when only dip triggers should return 0
        opps = scan_opportunities(market="omxs", strategy_filter="momentum")
        self.assertEqual(len(opps), 0)

    @patch("src.core.signals.get_db")
    @patch("src.core.signals.OMXS_50", {"ABB.ST": "ABB"})
    @patch("src.core.signals.NASDAQ_100", {})
    def test_scan_opportunities_too_few_rows_skipped(self, mock_get_db):
        conn = sqlite3.connect(":memory:")
        mock_get_db.return_value = conn
        # Only 50 rows (< 100 required)
        self.df_history.head(50).to_sql("history", conn, index=False)

        opps = scan_opportunities(market="omxs")
        self.assertEqual(len(opps), 0)


if __name__ == "__main__":
    unittest.main()
