import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from src.core.relative_strength import calculate_mansfield_rs, get_stock_relative_strength

class TestRelativeStrength(unittest.TestCase):

    def test_calculate_mansfield_rs_outperforming(self):
        # Skapa 100 dagars data där aktien stiger snabbare än index
        dates = pd.date_range("2025-01-01", periods=100)
        # Index stiger 10% över 100 dagar
        index_s = pd.Series(np.linspace(100, 110, 100), index=dates)
        # Aktien stiger 40% över 100 dagar
        stock_s = pd.Series(np.linspace(100, 140, 100), index=dates)

        mrs_series = calculate_mansfield_rs(stock_s, index_s, period=50)
        self.assertEqual(len(mrs_series), 100)
        # Senaste värdet ska vara klart positivt (outperformer)
        last_mrs = float(mrs_series.iloc[-1])
        self.assertGreater(last_mrs, 0.0)

    def test_calculate_mansfield_rs_underperforming(self):
        dates = pd.date_range("2025-01-01", periods=100)
        index_s = pd.Series(np.linspace(100, 130, 100), index=dates)
        stock_s = pd.Series(np.linspace(100, 90, 100), index=dates)

        mrs_series = calculate_mansfield_rs(stock_s, index_s, period=50)
        last_mrs = float(mrs_series.iloc[-1])
        self.assertLess(last_mrs, 0.0)

    @patch("src.core.relative_strength.get_db")
    def test_get_stock_relative_strength(self, mock_get_db):
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn

        dates = pd.date_range("2025-01-01", periods=100).strftime("%Y-%m-%d")
        df_stock = pd.DataFrame({"date": dates, "close": np.linspace(100, 150, 100)})
        df_index = pd.DataFrame({"date": dates, "close": np.linspace(2000, 2100, 100)})

        def mock_read_sql(query, conn, params=None):
            if params and params[0] == "VOLV-B.ST":
                return df_stock
            return df_index

        with patch("pandas.read_sql_query", side_effect=mock_read_sql):
            res = get_stock_relative_strength("VOLV-B.ST", market="omx")
            self.assertIn("mrs", res)
            self.assertTrue(res["is_outperformer"])
            self.assertIn("Ledaraktie", res["rs_label"])

if __name__ == "__main__":
    unittest.main()
