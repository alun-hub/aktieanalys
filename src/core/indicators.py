import pandas as pd
import numpy as np


def calc_rsi(s, n=14):
    """Beräknar RSI med Wilder's Smoothing.
    
    Hanterar noll-volatilitet och stillastående serier stabilt (returnerar 50 vid noll-förändring)
    utan numerisk singularitet eller felaktigt översålda värden vid kursstopp.
    """
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    total = g + l
    # Om både g och l är 0 (kursen rör sig inte) ska RSI vara neutralt 50
    rsi = np.where(total == 0, 50.0, 100.0 * (g / np.where(total == 0, 1.0, total)))
    return pd.Series(rsi, index=s.index)


def calc_atr(df, n=14):
    """Beräknar ATR med Wilder's Smoothing.
    
    Stöder kolumnnamn oberoende av skiftläge (High/high, Low/low, Close/close).
    """
    cols = {str(c).lower(): c for c in df.columns}
    high = df[cols["high"]]
    low = df[cols["low"]]
    close = df[cols["close"]]

    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def calc_ema(s, span=20):
    """Beräknar Exponential Moving Average (EMA)."""
    return s.ewm(span=span, adjust=False).mean()


def calc_macd(s, fast=12, slow=26, signal=9):
    """Beräknar MACD-linje, signallinje och MACD-histogram.
    
    MACD = EMA(12) - EMA(26)
    Signal = EMA(9) av MACD
    Histogram = MACD - Signal
    """
    fast_ema = s.ewm(span=fast, adjust=False).mean()
    slow_ema = s.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def calc_bollinger_bands(s, n=20, k=2):
    """Beräknar Bollinger Bands, Bandwidth (Squeeze) och %B.
    
    Upper = Middle + k * Std
    Lower = Middle - k * Std
    Bandwidth = (Upper - Lower) / Middle
    %B = (Close - Lower) / (Upper - Lower)
    """
    mid = s.rolling(n).mean()
    std = s.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    pct_b = (s - lower) / (upper - lower).replace(0, np.nan)
    return upper, mid, lower, bandwidth, pct_b


def calc_obv(close, volume):
    """Beräknar On-Balance Volume (OBV)."""
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    return obv


def calculate_indicators(df):
    """Huvudfunktion för att beräkna alla tekniska indikatorer för en DataFrame."""
    if df.empty:
        return df

    cols = {str(c).lower(): c for c in df.columns}
    close = df[cols["close"]]

    # Glidande medelvärden
    df['EMA20'] = calc_ema(close, 20)
    df['MA50'] = close.rolling(window=50).mean()
    df['MA200'] = close.rolling(window=200).mean()

    # RSI (Wilder's)
    df['RSI'] = calc_rsi(close)

    # ATR (Wilder's)
    df['ATR'] = calc_atr(df)

    # MACD (12, 26, 9)
    macd, sig, hist = calc_macd(close)
    df['MACD'] = macd
    df['MACD_Signal'] = sig
    df['MACD_Hist'] = hist

    # Bollinger Bands (20, 2)
    bb_u, bb_m, bb_l, bb_bw, bb_pctb = calc_bollinger_bands(close)
    df['BB_Upper'] = bb_u
    df['BB_Middle'] = bb_m
    df['BB_Lower'] = bb_l
    df['BB_Bandwidth'] = bb_bw
    df['BB_PctB'] = bb_pctb

    # OBV om volym finns
    if "volume" in cols:
        vol = df[cols["volume"]]
        df['OBV'] = calc_obv(close, vol)
        df['OBV_EMA20'] = df['OBV'].ewm(span=20, adjust=False).mean()

    return df
