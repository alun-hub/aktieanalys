import pandas as pd
import numpy as np

def calc_rsi(s, n=14):
    """Beräknar RSI med Wilder's Smoothing."""
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))


def calc_atr(df, n=14):
    """Beräknar ATR med Wilder's Smoothing."""
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def calculate_indicators(df):
    """Huvudfunktion för att beräkna alla indikatorer för en DataFrame."""
    if df.empty: return df
    
    # Glidande medelvärden
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    # RSI (Wilder's)
    df['RSI'] = calc_rsi(df['Close'])
    
    # ATR (Wilder's)
    df['ATR'] = calc_atr(df)
    
    return df
