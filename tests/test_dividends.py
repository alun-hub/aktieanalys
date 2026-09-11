import unittest
from unittest.mock import patch, MagicMock
from src.core.dividends import score_dividend_stock, get_top_dividend_stocks

class TestDividends(unittest.TestCase):

    def test_score_dividend_stock(self):
        # Bra utdelare: 5.5% direktavkastning, 50% payout ratio, P/E 12, trend_score 70
        res = score_dividend_stock(
            yield_pct=5.5,
            payout_ratio=50.0,
            pe=12.0,
            trend_score_val=70.0
        )
        self.assertTrue(80 <= res["dividend_score"] <= 100)
        self.assertIn("verdict", res)

        # Utdelningsfälla: 16% yield, 150% payout, negativ vinst (pe=None), trend_score 25
        res_trap = score_dividend_stock(
            yield_pct=16.0,
            payout_ratio=150.0,
            pe=None,
            trend_score_val=25.0
        )
        self.assertTrue(res_trap["dividend_score"] < 40)
        self.assertIn("fälla", res_trap["verdict"].lower())

    @patch("src.core.dividends.get_db")
    @patch("src.core.dividends.yf.Ticker")
    def test_get_top_dividend_stocks_structure(self, mock_ticker, mock_get_db):
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "close": 100.0, "ma50": 95.0, "ma200": 90.0, "rsi": 50.0, "atr": 2.0
        }
        mock_t = MagicMock()
        mock_t.info = {"dividendYield": 0.05, "payoutRatio": 0.5, "trailingPE": 15.0}
        mock_ticker.return_value = mock_t

        data = get_top_dividend_stocks(market="omx", limit=5, force_refresh=True)
        self.assertIn("stocks", data)
        self.assertIn("updated_at", data)
        self.assertIsInstance(data["stocks"], list)
        self.assertTrue(len(data["stocks"]) <= 5)

    def test_score_zero_or_none_yield(self):
        res_zero = score_dividend_stock(yield_pct=0)
        self.assertEqual(res_zero["dividend_score"], 0.0)
        self.assertEqual(res_zero["verdict"], "Ingen utdelning")

        res_none = score_dividend_stock(yield_pct=None)
        self.assertEqual(res_none["dividend_score"], 0.0)
        self.assertEqual(res_none["verdict"], "Ingen utdelning")

    def test_payout_ratio_high_trap(self):
        # 250% payout ratio ska ge låg payout_score (10.0)
        res = score_dividend_stock(yield_pct=9.0, payout_ratio=250.0, pe=15.0, trend_score_val=50.0)
        self.assertEqual(res["payout_score"], 10.0)
        self.assertIn("fälla", res["verdict"].lower())

    @patch("src.core.dividends.get_db")
    @patch("src.core.dividends.yf.Ticker")
    def test_get_top_dividend_stocks_ranking(self, mock_ticker, mock_get_db):
        # Skapa mock DB med 2 aktier
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn

        def mock_fetchone(query, params):
            sym = params[0]
            if sym == "VOLV-B.ST":
                return {"close": 250.0, "ma50": 240.0, "ma200": 220.0, "rsi": 55.0, "atr": 5.0}
            elif sym == "TELIA.ST":
                return {"close": 30.0, "ma50": 29.0, "ma200": 32.0, "rsi": 45.0, "atr": 0.8}
            return None

        mock_conn.execute.return_value.fetchone = MagicMock(side_effect=lambda: None)
        # Mock execute returning object with fetchone
        def execute_side_effect(query, params=None):
            m = MagicMock()
            if params and len(params) > 0:
                sym = params[0]
                if sym == "VOLV-B.ST":
                    m.fetchone.return_value = {"close": 250.0, "ma50": 240.0, "ma200": 220.0, "rsi": 55.0, "atr": 5.0}
                elif sym == "TELIA.ST":
                    m.fetchone.return_value = {"close": 30.0, "ma50": 29.0, "ma200": 32.0, "rsi": 45.0, "atr": 0.8}
                else:
                    m.fetchone.return_value = None
            else:
                m.fetchone.return_value = None
            return m

        mock_conn.execute.side_effect = execute_side_effect

        def ticker_side_effect(sym):
            m = MagicMock()
            if sym == "VOLV-B.ST":
                m.info = {"dividendYield": 0.06, "payoutRatio": 0.50, "trailingPE": 11.0}
            elif sym == "TELIA.ST":
                m.info = {"dividendYield": 0.07, "payoutRatio": 0.95, "trailingPE": 22.0}
            else:
                m.info = {}
            return m

        mock_ticker.side_effect = ticker_side_effect

        data = get_top_dividend_stocks(market="omx", limit=5, force_refresh=True)
        self.assertIn("stocks", data)
        self.assertGreaterEqual(len(data["stocks"]), 2)
        stocks = data["stocks"]
        # Kontrollera att de är sorterade fallande på dividend_score
        self.assertGreaterEqual(stocks[0]["dividend_score"], stocks[1]["dividend_score"])
        self.assertEqual(stocks[0]["rank"], 1)
        self.assertEqual(stocks[1]["rank"], 2)

    @patch("src.core.dividends.get_db")
    @patch("src.core.dividends.yf.Ticker")
    def test_cache_dynamic_limit(self, mock_ticker, mock_get_db):
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "close": 100.0, "ma50": 95.0, "ma200": 90.0, "rsi": 50.0, "atr": 2.0
        }
        mock_t = MagicMock()
        mock_t.info = {"dividendYield": 0.05, "payoutRatio": 0.5, "trailingPE": 15.0}
        mock_ticker.return_value = mock_t

        # First call with limit=1
        data1 = get_top_dividend_stocks(market="omx", limit=1, force_refresh=True)
        self.assertEqual(len(data1["stocks"]), 1)

        # Second call with limit=3 (from cache)
        data2 = get_top_dividend_stocks(market="omx", limit=3, force_refresh=False)
        self.assertGreater(len(data2["stocks"]), 1)

