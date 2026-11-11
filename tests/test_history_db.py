import datetime
import unittest
from unittest.mock import patch

import pandas as pd

from src.core import data
from src.core.data import _last_business_day_before, load_history_df


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_a, **_k):
        rows = self._rows

        class _R:
            def fetchall(self_inner):
                return rows
        return _R()

    def close(self):
        pass


def _rows(last, n=60):
    """n dagliga rader som slutar på `last` (datum som ISO-sträng)."""
    end = datetime.date.fromisoformat(last)
    out = []
    for i in range(n):
        d = end - datetime.timedelta(days=n - 1 - i)
        out.append({"date": d.isoformat(), "open": 10.0 + i, "high": 11.0 + i,
                    "low": 9.0 + i, "close": 10.5 + i, "volume": 1000 + i})
    return out


class TestLastBusinessDay(unittest.TestCase):
    def test_weekdays_and_weekend(self):
        self.assertEqual(_last_business_day_before(datetime.date(2026, 11, 11)), datetime.date(2026, 11, 10))  # ons -> tis
        self.assertEqual(_last_business_day_before(datetime.date(2026, 11, 9)), datetime.date(2026, 11, 6))    # mån -> fre
        self.assertEqual(_last_business_day_before(datetime.date(2026, 11, 8)), datetime.date(2026, 11, 6))    # sön -> fre
        self.assertEqual(_last_business_day_before(datetime.date(2026, 11, 7)), datetime.date(2026, 11, 6))    # lör -> fre


class TestLoadHistoryDf(unittest.TestCase):
    def _load(self, rows, today):
        with patch.object(data, "get_db", return_value=_FakeConn(rows)):
            return load_history_df("ERIC-B.ST", years=5, today=today)

    def test_fresh_data_returns_yfinance_style_frame(self):
        df = self._load(_rows("2026-11-10"), datetime.date(2026, 11, 11))
        self.assertIsNotNone(df)
        self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertIsInstance(df.index, pd.DatetimeIndex)
        self.assertEqual(df.index[-1].strftime("%Y-%m-%d"), "2026-11-10")

    def test_stale_data_returns_none(self):
        self.assertIsNone(self._load(_rows("2026-11-05"), datetime.date(2026, 11, 11)))

    def test_too_few_rows_returns_none(self):
        self.assertIsNone(self._load(_rows("2026-11-10", n=10), datetime.date(2026, 11, 11)))

    def test_friday_data_is_fresh_on_monday(self):
        self.assertIsNotNone(self._load(_rows("2026-11-06"), datetime.date(2026, 11, 9)))


if __name__ == "__main__":
    unittest.main()
