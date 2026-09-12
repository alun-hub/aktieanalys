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

    @patch("src.api.routes.get_top_dividend_stocks")
    def test_top_dividends_route(self, mock_get_top):
        mock_get_top.return_value = {
            "market": "all",
            "updated_at": "2026-09-11 22:30",
            "stocks": [
                {
                    "rank": 1,
                    "symbol": "VOLV-B.ST",
                    "name": "Volvo B",
                    "market": "OMX",
                    "dividend_score": 85.0,
                    "dividend_yield": 5.5,
                }
            ],
        }
        res = self.client.get("/api/portal/top-dividends")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("stocks", data)
        self.assertIn("updated_at", data)
        self.assertEqual(data["market"], "all")
        self.assertEqual(len(data["stocks"]), 1)
        mock_get_top.assert_called_with(market="all", limit=10, force_refresh=False)

    @patch("src.api.routes.get_top_dividend_stocks")
    def test_top_dividends_route_with_params(self, mock_get_top):
        mock_get_top.return_value = {
            "market": "omx",
            "updated_at": "2026-09-11 22:30",
            "stocks": [],
        }
        res = self.client.get("/api/portal/top-dividends?market=omx&limit=5&refresh=true")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["market"], "omx")
        mock_get_top.assert_called_with(market="omx", limit=5, force_refresh=True)

    @patch("src.api.routes.build_recommendations")
    def test_recommendations_route(self, mock_build):
        mock_build.return_value = {
            "allocation": {"broad_etf": 40.0, "equalweight_etf": 15.0, "dividend_stocks": 20.0, "growth_stocks": 20.0, "defensive": 5.0},
            "recommendations": [{"type": "broad_etf", "symbol": "VWCE.DE", "name": "Vanguard FTSE All-World"}],
            "regime": {"regime": "bull"},
            "concentration": {"level": "normal"},
            "generated_at": "2026-09-12 11:00",
        }
        res = self.client.get("/api/portal/recommendations?market=all")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("allocation", data)
        self.assertIn("recommendations", data)
        self.assertEqual(data["allocation"]["broad_etf"], 40.0)

    @patch("src.api.routes.run_portfolio_backtest")
    def test_portfolio_backtest_route(self, mock_bt):
        mock_bt.return_value = {
            "years": 10,
            "strategy": {"cagr": 15.0, "max_drawdown": -12.0},
            "benchmark_global": {"cagr": 10.0, "max_drawdown": -20.0},
            "benchmark_sp500": {"cagr": 14.0, "max_drawdown": -22.0},
            "equity_curve": [{"date": "2026-09-12", "strategy": 100000}],
        }
        res = self.client.get("/api/portal/portfolio-backtest?years=10")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("strategy", data)
        self.assertEqual(data["strategy"]["cagr"], 15.0)

    @patch("src.core.portfolio.list_sell_alerts")
    @patch("src.core.portfolio.acknowledge_sell_alert")
    def test_sell_alerts_routes(self, mock_ack, mock_list):
        mock_list.return_value = [
            {"id": 1, "symbol": "TEST", "severity": "exit", "reason": "atr_stop", "acknowledged": 0}
        ]
        mock_ack.return_value = True

        res_list = self.client.get("/api/portal/sell-alerts")
        self.assertEqual(res_list.status_code, 200)
        data = res_list.get_json()
        self.assertEqual(len(data["alerts"]), 1)
        self.assertEqual(data["alerts"][0]["symbol"], "TEST")

        res_ack = self.client.post("/api/portal/sell-alerts/1/acknowledge")
        self.assertEqual(res_ack.status_code, 200)
        data_ack = res_ack.get_json()
        self.assertTrue(data_ack["ok"])
        mock_ack.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()


