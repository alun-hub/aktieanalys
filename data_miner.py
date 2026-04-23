import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── Indikatorer (Exakt kopia från din app.py) ──────────────────
def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))

def calc_macd(s):
    m = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    sl = m.ewm(span=9, adjust=False).mean()
    return m, sl

def calc_bb(close, n=20):
    ma, std = close.rolling(n).mean(), close.rolling(n).std()
    return ma + 2*std, ma, ma - 2*std

def calc_atr(df, n=14):
    hl = df.High - df.Low
    hc, lc = (df.High - df.Close.shift()).abs(), (df.Low - df.Close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def calc_swing_score(df, idx=None):
    if idx is None: idx = -1
    row = df.iloc[idx]
    score = 0
    
    # Trend (+2)
    if row.MA50 > row.MA200: score += 2
    # RSI (+2)
    if 32 <= row.RSI <= 52: score += 2
    elif row.RSI < 32: score += 1
    # MACD (+2)
    if row.MACD > row.MACD_sig: score += 2
    # Stöd (+2)
    near_ma50 = abs(row.Close - row.MA50) / row.MA50 < 0.04
    near_bb = abs(row.Close - row.BB_low) / row.BB_low < 0.03
    if near_ma50 or near_bb: score += 2
    # Volym (+2)
    vol_avg = df.Volume.rolling(20).mean().iloc[idx]
    if row.Volume > vol_avg: score += 2
    # Relativ Styrka (Neutral 0 för denna analys)
    
    return score

# ── Analys-motor ───────────────────────────────────────────────
STOCKS = ["VOLV-B.ST", "INVE-B.ST", "SEB-A.ST", "EVO.ST", "AZN.ST", "HM-B.ST", "ABB.ST", "ERIC-B.ST", "NDA-SE.ST", "ASSA-B.ST"]
print(f"Analyserar {len(STOCKS)} aktier över 2 år...")

results = []

for sym in STOCKS:
    df = yf.Ticker(sym).history(period="3y")
    if df.empty: continue
    df.index = df.index.normalize()
    df["MA50"], df["MA200"] = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
    df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
    df["MACD"], df["MACD_sig"] = calc_macd(df.Close)
    df["BB_up"], df["BB_mid"], df["BB_low"] = calc_bb(df.Close)
    
    df = df.dropna()
    # Vi testar varje dag utom de sista 20 (behövs för facit)
    for i in range(len(df) - 20):
        score = calc_swing_score(df, i)
        price_now = df.Close.iloc[i]
        
        # Facit: Hur gick det sen?
        ret_5d = (df.Close.iloc[i+5] / price_now - 1) * 100
        ret_10d = (df.Close.iloc[i+10] / price_now - 1) * 100
        ret_20d = (df.Close.iloc[i+20] / price_now - 1) * 100
        
        results.append({"score": score, "5d": ret_5d, "10d": ret_10d, "20d": ret_20d})

# ── Sammanställning ────────────────────────────────────────────
report = pd.DataFrame(results)
summary = report.groupby("score").agg({
    "5d": ["count", "mean", lambda x: (x > 0).mean() * 100],
    "10d": ["mean", lambda x: (x > 0).mean() * 100],
    "20d": ["mean"]
})

summary.columns = ["Antal fall", "Snitt 5d (%)", "Win Rate 5d (%)", "Snitt 10d (%)", "Win Rate 10d (%)", "Snitt 20d (%)"]
print("\n--- STATISTISK ANALYS AV SWING SCORE ---")
print(summary.round(2).to_string())
