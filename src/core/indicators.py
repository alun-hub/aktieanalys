import pandas as pd
import numpy as np

def calc_rsi(s, n=14):
    """Beräknar RSI med Wilder's Smoothing."""
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))

def calc_macd(s, fast=12, slow=26, sig=9):
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sl = m.ewm(span=sig, adjust=False).mean()
    return m, sl, m - sl

def calc_bb(close, n=20, num_std=2):
    ma = close.rolling(n).mean()
    std = close.rolling(n).std()
    return ma + num_std * std, ma, ma - num_std * std

def calc_atr(df, n=14):
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()
