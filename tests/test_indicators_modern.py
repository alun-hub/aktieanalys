import unittest
import pandas as pd
import numpy as np

from src.core.indicators import (
    calc_rsi, calc_atr, calc_ema, calc_macd,
    calc_bollinger_bands, calc_obv, calculate_indicators
)
from src.core.patterns import detect_patterns
from src.core.signals import trend_score


class TestModernIndicators(unittest.TestCase):

    def test_rsi_normal_and_flat(self):
        # 1. Normal stigande/fallande serie
        prices = pd.Series([100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112, 114, 115, 117])
        rsi = calc_rsi(prices, n=14)
        self.assertEqual(len(rsi), len(prices))
        self.assertTrue(50 < rsi.iloc[-1] <= 100)

        # 2. Helt stillastående serie (noll volatilitet) -> ska ge 50.0 neutralt, inte 0
        flat_prices = pd.Series([100.0] * 20)
        flat_rsi = calc_rsi(flat_prices, n=14)
        self.assertEqual(flat_rsi.iloc[-1], 50.0)

        # 3. Enbart uppgångar -> ska närma sig 100
        rising = pd.Series(list(range(100, 130)))
        rising_rsi = calc_rsi(rising, n=14)
        self.assertAlmostEqual(rising_rsi.iloc[-1], 100.0, places=2)

        # 4. Enbart nedgångar -> ska närma sig 0
        falling = pd.Series(list(range(130, 100, -1)))
        falling_rsi = calc_rsi(falling, n=14)
        self.assertAlmostEqual(falling_rsi.iloc[-1], 0.0, places=2)

    def test_atr_case_insensitive(self):
        # Med stora bokstäver
        df_upper = pd.DataFrame({
            "High": [105, 106, 107, 108],
            "Low": [100, 101, 102, 103],
            "Close": [104, 105, 106, 107]
        })
        atr_u = calc_atr(df_upper, n=3)
        self.assertTrue(atr_u.iloc[-1] > 0)

        # Med små bokstäver
        df_lower = pd.DataFrame({
            "high": [105, 106, 107, 108],
            "low": [100, 101, 102, 103],
            "close": [104, 105, 106, 107]
        })
        atr_l = calc_atr(df_lower, n=3)
        self.assertAlmostEqual(atr_u.iloc[-1], atr_l.iloc[-1], places=5)

    def test_macd(self):
        prices = pd.Series(np.linspace(100, 150, 40))
        macd, signal, hist = calc_macd(prices, fast=12, slow=26, signal=9)
        self.assertEqual(len(macd), 40)
        self.assertEqual(len(signal), 40)
        self.assertEqual(len(hist), 40)
        # Kontrollera att hist = macd - signal
        np.testing.assert_allclose(hist.values, (macd - signal).values)
        # I en ren upptrend bör MACD vara positiv
        self.assertTrue(macd.iloc[-1] > 0)

    def test_bollinger_bands(self):
        prices = pd.Series([100 + np.sin(i) * 5 for i in range(50)])
        upper, middle, lower, bw, pct_b = calc_bollinger_bands(prices, n=20, k=2)
        
        # Upper ska alltid vara större än Lower där vi har tillräckligt med data
        valid_idx = 25
        self.assertTrue(upper.iloc[valid_idx] > middle.iloc[valid_idx] > lower.iloc[valid_idx])
        self.assertTrue(bw.iloc[valid_idx] > 0)

    def test_obv(self):
        closes = pd.Series([100, 102, 101, 105])
        volumes = pd.Series([1000, 1500, 800, 2000])
        obv = calc_obv(closes, volumes)
        # dag 0: 0
        # dag 1 (upp): +1500
        # dag 2 (ner): 1500 - 800 = 700
        # dag 3 (upp): 700 + 2000 = 2700
        self.assertEqual(list(obv), [0, 1500, 700, 2700])

    def test_calculate_indicators_all(self):
        dates = pd.date_range("2026-01-01", periods=60)
        df = pd.DataFrame({
            "Open": np.linspace(100, 120, 60),
            "High": np.linspace(101, 122, 60),
            "Low": np.linspace(99, 119, 60),
            "Close": np.linspace(100, 121, 60),
            "Volume": [10000] * 60
        }, index=dates)

        res = calculate_indicators(df)
        expected_cols = ["EMA20", "MA50", "RSI", "ATR", "MACD", "MACD_Signal", "MACD_Hist", "BB_Upper", "BB_Lower", "BB_Bandwidth", "OBV"]
        for col in expected_cols:
            self.assertIn(col, res.columns)

    def test_candlestick_patterns_context(self):
        dates = pd.date_range("2026-01-01", periods=6)
        
        # 1. Hammer efter nedgång
        df_hammer = pd.DataFrame({
            "Open":  [110, 108, 106, 104, 102, 100],
            "High":  [111, 109, 107, 105, 103, 100.5],
            "Low":   [109, 107, 105, 103, 101, 95.0],   # Lång svans nertill på sista
            "Close": [109, 107, 105, 103, 101, 100.2],
        }, index=dates)
        patterns = detect_patterns(df_hammer)
        pattern_names = [p["pattern"] for p in patterns]
        self.assertIn("Hammer", pattern_names)

        # 2. Hanging Man efter uppgång (samma form som hammer men i toppen)
        df_hanging = pd.DataFrame({
            "Open":  [95, 97, 99, 101, 103, 105],
            "High":  [96, 98, 100, 102, 104, 105.5],
            "Low":   [94, 96, 98, 100, 102, 100.0],    # Lång svans nertill i toppen
            "Close": [96, 98, 100, 102, 104, 105.2],
        }, index=dates)
        patterns_h = detect_patterns(df_hanging)
        pattern_names_h = [p["pattern"] for p in patterns_h]
        self.assertIn("Hanging Man", pattern_names_h)

    def test_trend_score_with_slope(self):
        # Stark upptrend med positiv MA200-lutning och MACD
        s1 = trend_score(close=120, ma50=115, ma200=110, rsi=60, ma200_slope=1.5, ema20=118, macd_hist=0.5)
        # Samma priser men fallande MA200-lutning och negativ MACD
        s2 = trend_score(close=120, ma50=115, ma200=110, rsi=60, ma200_slope=-1.5, ema20=118, macd_hist=-0.5)
        self.assertTrue(s1 > s2)


if __name__ == "__main__":
    unittest.main()
