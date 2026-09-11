import unittest
from app import app
from src.core.portfolio import list_holdings, remove_holding

class TestPortfolioSearch(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        remove_holding("INVE-B.ST")

    def tearDown(self):
        remove_holding("INVE-B.ST")

    def test_add_holding_by_name(self):
        # Skicka 'investor' istället för 'INVE-B.ST'
        res = self.client.post("/api/portfolio", json={
            "symbol": "investor",
            "qty": 10,
            "avg_price": 250.0,
            "kind": "aktie"
        })
        self.assertEqual(res.status_code, 200)
        holdings = list_holdings()
        syms = [h["symbol"] for h in holdings]
        self.assertIn("INVE-B.ST", syms)

if __name__ == "__main__":
    unittest.main()
