import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
from app import app
from src.core.analysis import analyze_any_stock


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_opportunities_route(self):
        res = self.client.get("/api/opportunities")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("opportunities", data)
        self.assertIn("total", data)

    def test_opportunities_route_with_params(self):
        res = self.client.get("/api/opportunities?market=omxs&strategy=dip")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("opportunities", data)
        self.assertIn("total", data)

    def test_backtest_stock_route(self):
        res = self.client.post("/api/backtest/stock", json={"symbol": "INVE-B.ST", "strategy": "dip", "years": 3})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue("error" in data or "stats" in data)

    def test_backtest_route_with_strategy(self):
        res = self.client.post("/api/backtest", json={"market": "omxs", "strategy": "dip", "years": 1})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue("error" in data or "stats" in data or "trades" in data)

    @patch("yfinance.Ticker")
    @patch("src.core.analysis.fetch_short_interest", return_value={})
    @patch("src.core.analysis.calc_context", return_value={"insider": [], "congress": []})
    def test_analyze_stock_edge_summary(self, mock_ctx, mock_short, mock_ticker):
        n = 120
        dates = pd.date_range("2023-01-01", periods=n)
        df = pd.DataFrame({
            "Open": [100.0 + i for i in range(n)],
            "High": [102.0 + i for i in range(n)],
            "Low": [98.0 + i for i in range(n)],
            "Close": [100.0 + i for i in range(n)],
            "Volume": [10000] * n,
        }, index=dates)

        mock_instance = MagicMock()
        mock_ticker.return_value = mock_instance
        mock_instance.history.return_value = df
        mock_instance.info = {"sector": "Technology"}
        mock_instance.calendar = None

        res = analyze_any_stock("TEST.ST")
        self.assertIn("edge_summary", res)
        self.assertIn("dip", res["edge_summary"])
        self.assertIn("momentum", res["edge_summary"])
        self.assertIn("trend", res["edge_summary"])
        self.assertIn("win_rate", res["edge_summary"]["dip"])
        self.assertIn("profit_factor", res["edge_summary"]["dip"])
        self.assertIn("trades_count", res["edge_summary"]["dip"])
        self.assertIn("total_return", res["edge_summary"]["dip"])
        self.assertIn("active_signal", res["edge_summary"]["dip"])

        # Kontrollera modig rekommendation och avsaknad av feg disclaimer
        self.assertIn("recommendation", res)
        rec = res["recommendation"]
        self.assertIn(rec["action"], ("Köp", "Behåll", "Sälj"))
        self.assertIn("horizon", rec)
        self.assertIn("rationale", rec)
        self.assertNotIn("Det här är information, inte en köp- eller säljrekommendation", res.get("summary", ""))
        self.assertTrue(res.get("summary", "").startswith("Rekommendation:"))


if __name__ == "__main__":
    unittest.main()
