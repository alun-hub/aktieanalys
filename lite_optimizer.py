import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))

STOCKS_OMX = ["VOLV-B.ST", "INVE-B.ST", "SEB-A.ST", "EVO.ST", "AZN.ST", "HM-B.ST", "ABB.ST", "NDA-SE.ST", "SAND.ST", "SWED-A.ST"]

# Ladda all data en gång för alla tester
idx = yf.Ticker("^OMX").history(period="6y")
idx.index = idx.index.tz_localize(None).normalize()
idx["MA50"], idx["MA200"] = idx.Close.rolling(50).mean(), idx.Close.rolling(200).mean()

pool = {}
for s in STOCKS_OMX:
    df = yf.Ticker(s).history(period="6y")
    if df.empty: continue
    df.index = df.index.tz_localize(None).normalize()
    df["MA200"] = df.Close.rolling(200).mean()
    df["EMA5"] = df.Close.ewm(span=5, adjust=False).mean()
    df["RSI"] = calc_rsi(df.Close)
    hl, hc, lc = df.High-df.Low, (df.High-df.Close.shift()).abs(), (df.Low-df.Close.shift()).abs()
    df["ATR"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(alpha=1/14, adjust=False).mean()
    pool[s] = df.dropna()

def run_test(start_years, rsi_entry, hold_days, atr_mult, be_trigger, use_m_ma50):
    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=start_years * 365)
    cash = 1000000
    holdings, trades, current_date = [], [], start_dt
    while current_date <= end_dt:
        if current_date.weekday() >= 5: current_date += timedelta(days=1); continue
        p_idx = idx[idx.index <= current_date].tail(1)
        if p_idx.empty: current_date += timedelta(days=1); continue
        m_bull = p_idx.Close.iloc[0] > p_idx.MA200.iloc[0]
        if use_m_ma50: m_bull = m_bull and (p_idx.Close.iloc[0] > p_idx.MA50.iloc[0])
        still_holding = []
        for h in holdings:
            day = pool[h["sym"]][pool[h["sym"]].index == current_date]
            if day.empty: still_holding.append(h); continue
            row = day.iloc[0]
            h["days"] += 1
            if (row.Close/h["entry"]-1) > be_trigger: h["sl"] = max(h["sl"], h["entry"])
            exit_p = None
            if row.Low <= h["sl"]: exit_p = h["sl"]
            elif h["days"] >= hold_days and row.Close < row.EMA5: exit_p = row.Close
            if exit_p: cash += (h["qty"] * exit_p); trades.append(exit_p/h["entry"]-1)
            else: still_holding.append(h)
        holdings = still_holding
        if m_bull and len(holdings) < 5:
            target_pos = (cash + sum(h['qty']*pool[h['sym']][pool[h['sym']].index <= current_date].Close.iloc[-1] for h in holdings)) * 0.20
            if cash >= target_pos:
                for sym, df in pool.items():
                    if any(h["sym"]==sym for h in holdings): continue
                    p = df[df.index <= current_date].tail(2)
                    if len(p) < 2: continue
                    r = p.iloc[-1]
                    if r.RSI < rsi_entry and r.RSI > p.iloc[-2].RSI and r.Close > r.MA200:
                        holdings.append({"sym":sym,"entry":r.Close,"sl":r.Close-(atr_mult*r.ATR),"qty":target_pos/r.Close,"days":0})
                        cash -= target_pos; break
        current_date += timedelta(days=1)
    return np.mean(trades)*len(trades) if trades else 0, len(trades)

print("Kör snabb-optimering...")
for rsi in [40, 45]:
    for hold in [15, 20]:
        for atr in [3.0, 4.0]:
            for m50 in [True, False]:
                total_ret, count = run_test(5, rsi, hold, atr, 0.05, m50)
                print(f"RSI:{rsi} Hold:{hold} ATR:{atr} M50:{m50} -> Affärer:{count} Total_Score:{total_ret:.2f}")
