import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))

STOCKS_OMX = ["VOLV-B.ST", "INVE-B.ST", "SEB-A.ST", "EVO.ST", "AZN.ST", "HM-B.ST", "ABB.ST", "ERIC-B.ST", "NDA-SE.ST", "ASSA-B.ST", "SAND.ST", "SWED-A.ST"]
STOCKS_NDX = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "COST", "NFLX"]

def run_test(stocks, start_years, rsi_entry, hold_days, atr_mult, be_trigger, use_m_ma50):
    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=start_years * 365)
    
    # Ladda index
    idx_ticker = "^OMX" if stocks[0].endswith(".ST") else "^NDX"
    idx = yf.Ticker(idx_ticker).history(period="6y")
    idx.index = idx.index.tz_localize(None).normalize()
    idx["MA50"] = idx.Close.rolling(50).mean()
    idx["MA200"] = idx.Close.rolling(200).mean()

    # Ladda aktier
    pool = {}
    for s in stocks:
        df = yf.Ticker(s).history(period="6y")
        if df.empty or len(df) < 500: continue
        df.index = df.index.tz_localize(None).normalize()
        df["MA200"] = df.Close.rolling(200).mean()
        df["EMA5"] = df.Close.ewm(span=5, adjust=False).mean()
        df["RSI"] = calc_rsi(df.Close)
        hl, hc, lc = df.High-df.Low, (df.High-df.Close.shift()).abs(), (df.Low-df.Close.shift()).abs()
        df["ATR"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(alpha=1/14, adjust=False).mean()
        pool[s] = df.dropna()

    cash = 1000000
    holdings = []
    trades = []
    current_date = start_dt

    while current_date <= end_dt:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1); continue
        
        # Marknadsfilter
        p_idx = idx[idx.index <= current_date].tail(1)
        if p_idx.empty: current_date += timedelta(days=1); continue
        m_bull = p_idx.Close.iloc[0] > p_idx.MA200.iloc[0]
        if use_m_ma50:
            m_bull = m_bull and (p_idx.Close.iloc[0] > p_idx.MA50.iloc[0])

        # Exits
        still_holding = []
        for h in holdings:
            df = pool[h["sym"]]
            day = df[df.index == current_date]
            if day.empty: still_holding.append(h); continue
            row = day.iloc[0]
            h["days"] += 1
            if (row.Close / h["entry"] - 1) > be_trigger and h["sl"] < h["entry"]: h["sl"] = h["entry"]
            
            exit_p, exit_r = None, None
            if row.Low <= h["sl"]: exit_p, exit_r = h["sl"], "SL"
            elif h["days"] >= hold_days and row.Close < row.EMA5: exit_p, exit_r = row.Close, "Time"
            
            if exit_p:
                cash += (h["qty"] * exit_p)
                trades.append(exit_p / h["entry"] - 1)
            else: still_holding.append(h)
        holdings = still_holding

        # Entry
        if m_bull and len(holdings) < 5:
            target_pos = (cash + sum(h['qty']*pool[h['sym']][pool[h['sym']].index <= current_date].Close.iloc[-1] for h in holdings)) * 0.20
            if cash >= target_pos:
                for sym, df in pool.items():
                    if any(h["sym"] == sym for h in holdings): continue
                    past = df[df.index <= current_date].tail(2)
                    if len(past) < 2: continue
                    r = past.iloc[-1]
                    if r.RSI < rsi_entry and r.RSI > past.iloc[-2].RSI and r.Close > r.MA200:
                        entry = r.Close
                        holdings.append({"sym": sym, "entry": entry, "sl": entry - (atr_mult * r.ATR), "qty": target_pos/entry, "days": 0})
                        cash -= target_pos
                        break
        current_date += timedelta(days=1)
    
    if not trades: return 0, 0
    return np.mean(trades)*100, (np.array(trades) > 0).mean()*100

print("Kör optimering på 5 år...")
best_res = -999
best_params = {}

for rsi in [35, 40, 45]:
    for hold in [10, 15, 20]:
        for atr in [3.0, 4.0]:
            for be in [0.03, 0.05]:
                for m50 in [True, False]:
                    ret, wr = run_test(STOCKS_OMX, 5, rsi, hold, atr, be, m50)
                    score = ret * wr
                    if score > best_res:
                        best_res = score
                        best_params = {"RSI": rsi, "Hold": hold, "ATR": atr, "BE": be, "M50": m50, "Ret": ret, "WR": wr}

print("\n--- OPTIMERAD STRATEGI FUNNEN ---")
print(best_params)
