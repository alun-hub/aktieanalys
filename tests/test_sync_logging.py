import io
import sqlite3
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.core import data


def _frame(n=60, end="2026-11-10"):
    idx = pd.bdate_range(end=end, periods=n)
    px = np.linspace(100, 110, n)
    return pd.DataFrame({"Open": px, "High": px + 1, "Low": px - 1, "Close": px,
                         "Volume": np.full(n, 1000)}, index=idx)


class _KeepOpen:
    """Delegerar till en delad in-memory-anslutning men ignorerar close()."""
    def __init__(self, conn):
        self._c = conn

    def __getattr__(self, name):
        return getattr(self._c, name)

    def close(self):
        pass


class TestUpdateStockData(unittest.TestCase):
    def test_empty_response_returns_none(self):
        with patch.object(data.yf, "download", return_value=pd.DataFrame()):
            self.assertIsNone(data.update_stock_data("ERIC-B.ST"))

    def test_returns_last_date_and_saves_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE history (symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, "
                     "volume INTEGER, ma50 REAL, ma200 REAL, rsi REAL, atr REAL, PRIMARY KEY (symbol, date))")
        with patch.object(data.yf, "download", return_value=_frame()), \
             patch.object(data, "get_db", return_value=_KeepOpen(conn)):
            last = data.update_stock_data("ERIC-B.ST")
        self.assertEqual(last, "2026-11-10")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 60)


class TestSyncSummary(unittest.TestCase):
    def _run(self, **kw):
        status = {}
        buf = io.StringIO()
        with redirect_stdout(buf):
            data._log_sync_summary(status, kw.get("total", 100), "2026-11-10",
                                   kw.get("empty", []), kw.get("failed", []), kw.get("stale", []))
        return status, buf.getvalue()

    def test_clean_sync_has_no_warning(self):
        status, out = self._run()
        self.assertIn("100/100 ok", out)
        self.assertNotIn("VARNING", out)
        self.assertEqual((status["empty"], status["failed"], status["stale"]), ([], [], []))

    def test_many_stale_se_symbols_warns_with_market_breakdown(self):
        stale = [f"S{i}.ST" for i in range(45)]
        status, out = self._run(stale=stale)
        self.assertIn("VARNING", out)
        self.assertIn("ST: 45", out)
        self.assertEqual(len(status["stale"]), 45)

    def test_few_stale_is_only_info(self):
        _, out = self._run(stale=["A.ST", "B.ST"])
        self.assertIn("Info", out)
        self.assertNotIn("VARNING", out)

    def test_empty_and_failed_reduce_ok_count(self):
        _, out = self._run(empty=["X.ST"], failed=["Y"])
        self.assertIn("98/100 ok", out)


if __name__ == "__main__":
    unittest.main()


class TestSyncSummaryEmptyWarning(unittest.TestCase):
    def test_many_empty_responses_warns(self):
        status, buf = {}, io.StringIO()
        with redirect_stdout(buf):
            data._log_sync_summary(status, 100, "2026-11-10", [f"S{i}.ST" for i in range(30)], [], [])
        self.assertIn("VARNING", buf.getvalue())
        self.assertIn("30 tomma", buf.getvalue())
