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

    @patch("src.core.regime.get_market_regime")
    @patch("src.core.portfolio.list_holdings")
    @patch("src.core.portfolio.get_db")
    def test_sell_alerts_ignore_funds_in_bear_market(self, mock_get_db, mock_list_holdings, mock_regime):
        from src.core.portfolio import generate_sell_alerts

        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        # Simulera en björnmarknad
        mock_regime.return_value = {"regime": "bear", "is_bull": False}

        # Två innehav: en global indexfond och en aktie
        mock_list_holdings.return_value = [
            {"symbol": "LF-GLOBAL", "name": "Länsförsäkringar Global", "kind": "fond", "avg_price": 100.0},
            {"symbol": "VOLV-B.ST", "name": "Volvo B", "kind": "aktie", "avg_price": 300.0},
        ]

        def execute_side_effect(query, params=None):
            m = MagicMock()
            if "history" in query.lower() and params and "VOLV-B.ST" in params:
                m.fetchone.return_value = {"close": 240.0, "open": 242.0, "ma50": 260.0, "ma200": 280.0, "atr": 6.0}
            elif "sell_alerts" in query.lower():
                m.fetchone.return_value = None
            else:
                m.fetchone.return_value = None
            return m

        mock_conn.execute.side_effect = execute_side_effect

        alerts = generate_sell_alerts()
        symbols_alerted = [a["symbol"] for a in alerts]

        # Fonden får ALDRIG flaggas för sälj vid bear market
        self.assertNotIn("LF-GLOBAL", symbols_alerted)
        # Aktien ska flaggas
        self.assertIn("VOLV-B.ST", symbols_alerted)
        volvo_alert = next(a for a in alerts if a["symbol"] == "VOLV-B.ST")
        self.assertEqual(volvo_alert["severity"], "exit")


if __name__ == "__main__":
    unittest.main()

