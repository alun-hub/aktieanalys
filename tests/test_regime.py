import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
from src.core.regime import get_market_regime, evaluate_regime_from_indicators

class TestRegime(unittest.TestCase):

    def test_evaluate_regime_bull(self):
        # Index handlas över MA200 och MA50 > MA200
        res = evaluate_regime_from_indicators(close=2600.0, ma50=2550.0, ma200=2400.0)
        self.assertTrue(res["is_bull"])
        self.assertEqual(res["regime"], "bull")
        self.assertIn("Bull Market", res["label"])
        self.assertTrue(res["allow_buys"])

    def test_evaluate_regime_correction(self):
        # Index handlas över MA200 men under MA50 (korrektion)
        res = evaluate_regime_from_indicators(close=2450.0, ma50=2550.0, ma200=2400.0)
        self.assertTrue(res["is_bull"])
        self.assertEqual(res["regime"], "correction")
        self.assertTrue(res["allow_buys"])

    def test_evaluate_regime_bear(self):
        # Index handlas under MA200 (björnmarknad)
        res = evaluate_regime_from_indicators(close=2300.0, ma50=2350.0, ma200=2450.0)
        self.assertFalse(res["is_bull"])
        self.assertEqual(res["regime"], "bear")
        self.assertIn("Bear", res["label"])
        self.assertFalse(res["allow_buys"])

    @patch("src.core.regime.get_db")
    def test_get_market_regime_omx(self, mock_get_db):
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "close": 2600.0, "ma50": 2550.0, "ma200": 2400.0, "date": "2026-09-11"
        }
        res = get_market_regime(market="omx")
        self.assertIn("is_bull", res)
        self.assertIn("regime", res)
        self.assertIn("index_symbol", res)
        self.assertEqual(res["index_symbol"], "^OMX")
        self.assertTrue(res["is_bull"])

if __name__ == "__main__":
    unittest.main()
