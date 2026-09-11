import unittest
from app import app
from src.core.analysis import search_symbols, resolve_symbol
from src.core.portfolio import list_holdings, remove_holding, portfolio_health

class TestPortfolioFundsAndETFs(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        # Rensa eventuella testinnehav
        for h in list_holdings():
            if h["symbol"].startswith("MANUAL:TEST") or h["symbol"] in ("XACTHDIV.ST", "VWCE.DE"):
                remove_holding(h["symbol"])

    def tearDown(self):
        for h in list_holdings():
            if h["symbol"].startswith("MANUAL:TEST") or h["symbol"] in ("XACTHDIV.ST", "VWCE.DE"):
                remove_holding(h["symbol"])

    def test_popular_etf_search_and_resolve(self):
        matches = search_symbols("xact")
        symbols = [m["symbol"] for m in matches]
        self.assertIn("XACTHDIV.ST", symbols)
        xact_item = next(m for m in matches if m["symbol"] == "XACTHDIV.ST")
        self.assertEqual(xact_item["type"], "ETF")

        resolved_vwce = resolve_symbol("vwce")
        self.assertEqual(resolved_vwce, "VWCE.DE")

        resolved_xact = resolve_symbol("xact norden")
        self.assertEqual(resolved_xact, "XACTHDIV.ST")

    def test_add_manual_fund_in_kronor_mode(self):
        res = self.client.post("/api/portfolio", json={
            "name": "Test Global Index",
            "value": 50000.0,
            "cost": 40000.0,
            "is_manual": True,
            "kind": "fond",
            "region": "Global",
            "fee_pct": 0.22,
            "symbol": "MANUAL:TEST-GLOBAL-INDEX"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("symbol"), "MANUAL:TEST-GLOBAL-INDEX")

        health_res = self.client.get("/api/portfolio/health")
        self.assertEqual(health_res.status_code, 200)
        h = health_res.get_json()

        pos = next((p for p in h["positions"] if p["symbol"] == "MANUAL:TEST-GLOBAL-INDEX"), None)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["name"], "Test Global Index")
        self.assertEqual(pos["value"], 50000.0)
        self.assertEqual(pos["cost"], 40000.0)
        self.assertEqual(pos["pl"], 10000.0)
        self.assertEqual(pos["pl_pct"], 25.0)
        self.assertEqual(pos["region"], "Global")
        self.assertEqual(pos["fee_pct"], 0.22)
        self.assertIn("Global", h["by_region"])

    def test_etf_with_shares_and_gav(self):
        res = self.client.post("/api/portfolio", json={
            "symbol": "XACTHDIV.ST",
            "name": "Xact Norden Högutdelande",
            "qty": 100,
            "avg_price": 150.0,
            "kind": "fond",
            "fee_pct": 0.30
        })
        self.assertEqual(res.status_code, 200)
        health_res = self.client.get("/api/portfolio/health")
        h = health_res.get_json()
        pos = next((p for p in h["positions"] if p["symbol"] == "XACTHDIV.ST"), None)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["qty"], 100)
        self.assertEqual(pos["avg_price"], 150.0)
        self.assertEqual(pos["cost"], 15000.0)
        self.assertEqual(pos["region"], "Norden")

    def test_search_swedish_funds(self):
        # Sökning med å/ä/ö
        matches_se = search_symbols("länsförsäkringar")
        names_se = [m["name"] for m in matches_se]
        self.assertTrue(any("Länsförsäkringar Global Index" in n for n in names_se))

        # Sökning utan å/ä/ö (lansforsakringar)
        matches_norm = search_symbols("lansforsakringar")
        names_norm = [m["name"] for m in matches_norm]
        self.assertTrue(any("Länsförsäkringar Global Index" in n for n in names_norm))

        # Sökning på LF Global
        matches_lf = search_symbols("lf global")
        names_lf = [m["name"] for m in matches_lf]
        self.assertTrue(any("Länsförsäkringar Global Index" in n for n in names_lf))

        # Spiltan
        matches_sp = search_symbols("spiltan")
        names_sp = [m["name"] for m in matches_sp]
        self.assertTrue(any("Spiltan Aktiefond Investmentbolag" in n for n in names_sp))

if __name__ == "__main__":
    unittest.main()

