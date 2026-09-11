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

    def test_trend_strategy_signals(self):
        res = prep_strategy_signals(self.df, "trend")
        self.assertIn("entry_sig", res.columns)
        self.assertTrue(bool(res.iloc[-1]["entry_sig"]))

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
