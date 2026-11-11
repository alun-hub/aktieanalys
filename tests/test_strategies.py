import unittest
import pandas as pd
import numpy as np
from src.core.backtest import prep_strategy_signals

class TestStrategies(unittest.TestCase):
    def setUp(self):
        n = 100
        dates = pd.date_range("2024-01-01", periods=n)
        prices = [100.0 + i * 0.5 for i in range(n)]
        self.df = pd.DataFrame({
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 2 for p in prices],
            "close": prices,
            "volume": [10000] * n,
            "ma50": [p - 5 for p in prices],
            "ma200": [p - 20 for p in prices],
            "rsi": [50] * n,
            "atr": [2.0] * n,
        }, index=dates)

    def test_dip_strategy_signals(self):
        self.df.loc[self.df.index[-1], "rsi"] = 30
        res = prep_strategy_signals(self.df, "dip")
        self.assertIn("entry_sig", res.columns)
        self.assertTrue(bool(res.iloc[-1]["entry_sig"]))

    def test_momentum_strategy_signals(self):
        self.df.loc[self.df.index[-1], "close"] = 300.0
        self.df.loc[self.df.index[-1], "high"] = 305.0
        self.df.loc[self.df.index[-1], "volume"] = 50000
        res = prep_strategy_signals(self.df, "momentum")
        self.assertIn("entry_sig", res.columns)
        self.assertTrue(bool(res.iloc[-1]["entry_sig"]))

    def test_trend_signal_is_event_not_state(self):
        # En trend som pågått hela perioden är inget färskt köptillfälle
        res = prep_strategy_signals(self.df, "trend")
        self.assertIn("entry_sig", res.columns)
        self.assertFalse(bool(res.iloc[-1]["entry_sig"]))

    def test_trend_signal_fires_after_recent_golden_cross(self):
        df = self.df.copy()
        n = len(df)
        # MA50 under MA200 fram till 5 dagar före slutet, sedan golden cross
        df["ma50"] = df["ma200"] - 5.0
        df.iloc[n - 5:, df.columns.get_loc("ma50")] = df["ma200"].iloc[n - 5:] + 5.0
        res = prep_strategy_signals(df, "trend")
        self.assertTrue(bool(res.iloc[-1]["entry_sig"]))
        # ...men inte långt efteråt (trenden är då inte längre "ny")
        df2 = self.df.copy()
        df2["ma50"] = df2["ma200"] - 5.0
        df2.iloc[n - 40:, df2.columns.get_loc("ma50")] = df2["ma200"].iloc[n - 40:] + 5.0
        self.assertFalse(bool(prep_strategy_signals(df2, "trend").iloc[-1]["entry_sig"]))

    def test_dip_panic_dump_filtered(self):
        # Om volymen på dippen är extrem (panikförsäljning, 5x snittet), ska signalen filtreras bort
        self.df.loc[self.df.index[-1], "rsi"] = 30
        self.df.loc[self.df.index[-1], "volume"] = 60000  # 6x mot 10000
        self.df.loc[self.df.index[-1], "close"] = 120.0
        self.df.loc[self.df.index[-1], "open"] = 135.0   # kraftigt röd stapel
        res = prep_strategy_signals(self.df, "dip")
        self.assertFalse(bool(res.iloc[-1]["entry_sig"]))


if __name__ == "__main__":
    unittest.main()
