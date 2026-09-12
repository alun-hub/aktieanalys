import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from src.core.analysis import _valuation, analyze_any_stock


class TestAnalysisRobustness(unittest.TestCase):

    def test_valuation_handles_nan_and_edge_cases(self):
        # Tom serie
        res = _valuation(pd.Series(dtype=float), 100.0, {}, False)
        self.assertIsNone(res["price_pctile_5y"])
        self.assertIn("saknas", res["text"])

        # lo == hi
        res = _valuation(pd.Series([100.0, 100.0]), 100.0, {}, False)
        self.assertIsNone(res["price_pctile_5y"])

        # close is NaN
        res = _valuation(pd.Series([50.0, 150.0]), float("nan"), {}, False)
        self.assertIsNone(res["price_pctile_5y"])

        # close is None
        res = _valuation(pd.Series([50.0, 150.0]), None, {}, False)
        self.assertIsNone(res["price_pctile_5y"])

        # Normalt fall
        res = _valuation(pd.Series([50.0, 150.0]), 100.0, {"trailingPE": 15.0}, False)
        self.assertEqual(res["price_pctile_5y"], 0.5)
        self.assertIn("50 %", res["text"])

    @patch("src.core.analysis.yf.Ticker")
    def test_analyze_any_stock_with_trailing_nan_row(self, mock_ticker_cls):
        # Simulera en 50-dagars tidsserie där sista raden är NaN (som yfinance ibland gör)
        dates = pd.date_range("2026-01-01", periods=50, freq="D")
        closes = [100.0 + i for i in range(49)] + [np.nan]
        highs = [102.0 + i for i in range(49)] + [np.nan]
        lows = [98.0 + i for i in range(49)] + [np.nan]
        opens = [99.0 + i for i in range(49)] + [np.nan]
        volumes = [1000] * 49 + [0]

        df = pd.DataFrame({
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes
        }, index=dates)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_ticker.info = {"trailingPE": 12.0, "dividendYield": 0.05}
        mock_ticker_cls.return_value = mock_ticker

        res = analyze_any_stock("MOCK_NAN_TEST")
        self.assertNotIn("error", res)
        # Sista giltiga priset ska vara 100.0 + 48 = 148.0
        self.assertEqual(res["close"], 148.0)
        self.assertIsNotNone(res["valuation"]["price_pctile_5y"])
        self.assertIn("% upp i sitt 5-årsspann", res["valuation"]["text"])


if __name__ == "__main__":
    unittest.main()
