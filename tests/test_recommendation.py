import unittest

from src.core.analysis import generate_recommendation

BASE = dict(symbol="TEST.ST", close=100.0, ma50=98.0, ma200=95.0, rsi=55.0, atr=2.0, tscore=50.0,
            valuation={"verdict": "högt värderat"}, info={}, edge_summary={}, is_crypto=False)


def rec(**kw):
    args = {**BASE, **kw}
    return generate_recommendation(**args)


def edge(active=True, exp=1.5, qualifies=True, n=12):
    return {"active_signal": active, "qualifies": qualifies, "expectancy_pct": exp,
            "trades_count": n, "confidence": "medel"}


class TestStockRecommendation(unittest.TestCase):
    def test_strong_momentum_buys(self):
        r = rec(mom_pct=85.0, regime={"regime": "bull"})
        self.assertEqual(r["action"], "Köp")
        self.assertEqual(r["strategy"], "Relativ momentum")

    def test_moderately_strong_momentum_only_holds(self):
        # Percentil 70 är över snittet men inte i den femtedel där effekten syns
        self.assertEqual(rec(mom_pct=70.0, regime={"regime": "bull"})["action"], "Behåll")

    def test_strong_momentum_in_bear_market_holds(self):
        r = rec(mom_pct=85.0, regime={"regime": "bear"})
        self.assertEqual(r["action"], "Behåll")

    def test_strong_momentum_but_overbought_holds(self):
        self.assertEqual(rec(mom_pct=85.0, rsi=80.0, regime={"regime": "bull"})["action"], "Behåll")

    def test_trend_score_alone_no_longer_drives_buy(self):
        # Hög trendpoäng men svag momentum -> inget köp
        r = rec(tscore=90.0, mom_pct=30.0, regime={"regime": "bull"})
        self.assertNotEqual(r["action"], "Köp")

    def test_weakest_below_ma200_sells(self):
        r = rec(mom_pct=10.0, close=90.0, ma200=100.0, ma50=95.0, regime={"regime": "bull"})
        self.assertEqual(r["action"], "Sälj")

    def test_weak_but_oversold_holds(self):
        r = rec(mom_pct=10.0, close=90.0, ma200=100.0, ma50=95.0, rsi=25.0, regime={"regime": "bull"})
        self.assertEqual(r["action"], "Behåll")

    def test_weak_above_ma200_holds(self):
        self.assertEqual(rec(mom_pct=10.0, regime={"regime": "bull"})["action"], "Behåll")

    def test_unknown_momentum_defaults_to_hold(self):
        r = rec(mom_pct=None, regime={"regime": "bull"})
        self.assertEqual(r["action"], "Behåll")

    def test_cheap_and_positive_analysts_buys_in_neutral_zone(self):
        r = rec(mom_pct=50.0, valuation={"verdict": "lågt värderat"}, info={"recommendationKey": "buy"},
                regime={"regime": "bull"})
        self.assertEqual(r["action"], "Köp")

    def test_cheap_alone_is_not_enough(self):
        r = rec(mom_pct=50.0, valuation={"verdict": "lågt värderat"}, regime={"regime": "bull"})
        self.assertEqual(r["action"], "Behåll")


class TestSignalSelection(unittest.TestCase):
    def test_best_expectancy_signal_wins(self):
        es = {"dip": edge(exp=0.8), "momentum": edge(exp=2.4), "trend": edge(active=False, exp=9.0)}
        r = rec(edge_summary=es, mom_pct=50.0, regime={"regime": "bull"})
        self.assertEqual(r["strategy"], "Momentum & Utbrott")
        self.assertIn("+2.4", r["rationale"])

    def test_non_qualifying_signal_gives_no_buy(self):
        es = {"dip": edge(exp=-1.0, qualifies=False)}
        r = rec(edge_summary=es, mom_pct=50.0, regime={"regime": "bull"})
        self.assertNotEqual(r["strategy"], "Kvalitets-dipp")
        self.assertNotEqual(r["action"], "Köp")


if __name__ == "__main__":
    unittest.main()
