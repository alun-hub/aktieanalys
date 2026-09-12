import unittest
from unittest.mock import patch, MagicMock
from src.core.allocation import compute_target_allocation, assess_concentration_risk


class TestAllocation(unittest.TestCase):

    @patch("src.core.allocation.get_db")
    @patch("src.core.allocation.get_market_regime")
    @patch("src.core.allocation.assess_concentration_risk")
    def test_all_regime_and_concentration_combinations_sum_to_100(
        self, mock_conc, mock_regime, mock_get_db
    ):
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn

        regimes = ["bull", "correction", "bear"]
        concentrations = ["normal", "elevated", "high"]

        for r in regimes:
            for c in concentrations:
                mock_regime.return_value = {"regime": r, "label": f"Regime {r}"}
                mock_conc.return_value = {"level": c, "spread_pct": 5.0, "detail": "test"}

                res = compute_target_allocation(market="all")
                alloc = res["allocation"]

                # Verifiera att alla 5 tillgångsklasser finns med
                for key in [
                    "broad_etf",
                    "equalweight_etf",
                    "dividend_stocks",
                    "growth_stocks",
                    "defensive",
                ]:
                    self.assertIn(key, alloc, f"Saknar {key} för {r} / {c}")
                    self.assertGreaterEqual(alloc[key], 0.0)

                # Verifiera att summan är exakt 100%
                total_pct = sum(alloc.values())
                self.assertAlmostEqual(
                    total_pct, 100.0, places=2, msg=f"Summan för {r}/{c} blev {total_pct}"
                )

                # Kontrollera specifika regler från planen
                if r == "bear":
                    self.assertEqual(alloc["growth_stocks"], 0.0)
                    self.assertEqual(alloc["defensive"], 65.0)
                elif r == "bull" and c == "high":
                    # Vid hög koncentrationsrisk ska likaviktat och utdelning öka
                    self.assertGreater(alloc["equalweight_etf"], 20.0)
                    self.assertGreater(alloc["dividend_stocks"], 25.0)
                    self.assertLess(alloc["growth_stocks"], 15.0)

    @patch("src.core.allocation.get_db")
    def test_assess_concentration_risk_fallback(self, mock_get_db):
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        # Inga rader i DB
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("src.core.allocation._CONCENTRATION_CACHE", {"data": None, "ts": 0.0}):
            with patch("src.core.allocation.yf.download") as mock_yf:
                mock_yf.side_effect = Exception("Network offline")
                res = assess_concentration_risk()
                self.assertIn("level", res)
                self.assertIn(res["level"], ["normal", "elevated", "high"])
                self.assertIn("spread_pct", res)


if __name__ == "__main__":
    unittest.main()
