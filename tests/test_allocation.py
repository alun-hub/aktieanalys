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

    @patch("src.core.allocation.compute_target_allocation")
    @patch("src.core.dividends.get_top_dividend_stocks")
    @patch("src.core.signals.scan_opportunities")
    def test_build_recommendations_category_types(
        self, mock_scan, mock_div, mock_alloc
    ):
        from src.core.signals import build_recommendations

        mock_alloc.return_value = {
            "allocation": {
                "broad_etf": 40.0,
                "equalweight_etf": 15.0,
                "dividend_stocks": 20.0,
                "growth_stocks": 20.0,
                "defensive": 5.0,
            },
            "regime": {"regime": "bull", "label": "Bull"},
            "concentration": {"level": "normal", "spread_pct": 2.0},
        }
        mock_div.return_value = {
            "stocks": [{
                "symbol": "SHB-A.ST",
                "name": "Handelsbanken A",
                "market": "omx",
                "currency": "SEK",
                "close": 120.0,
                "dividend_yield": 5.5,
                "payout_ratio": 50.0,
                "pe": 10.0,
                "streak_years": 10,
                "dividend_score": 85.0,
                "verdict": "Stark utdelare",
            }]
        }
        mock_scan.return_value = [{
            "symbol": "SEB-A.ST",
            "name": "SEB A",
            "market": "omx",
            "currency": "SEK",
            "close": 140.0,
            "strategy": "trend",
            "strategy_name": "Långsiktig Trendföljare",
            "score": 90.0,
            "edge": {"win_rate": 65.0, "trades_count": 8, "profit_factor": 2.0, "avg_gain_pct": 5.0},
            "reason": "Upptrend",
        }]

        res = build_recommendations(market="all")
        types = {r["type"] for r in res["recommendations"]}
        alloc_keys = set(res["allocation"].keys())

        # Alla typer i rekommendationerna ska matcha allokeringsnycklarna exakt
        self.assertTrue(types.issubset(alloc_keys), f"{types} inte delmängd av {alloc_keys}")
        self.assertIn("dividend_stocks", types)
        self.assertIn("growth_stocks", types)
        self.assertIn("broad_etf", types)
        self.assertIn("equalweight_etf", types)
        self.assertIn("defensive", types)


if __name__ == "__main__":
    unittest.main()
