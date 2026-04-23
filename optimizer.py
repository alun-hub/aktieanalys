import yfinance as yf
import pandas as pd
import numpy as np

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))

STOCKS = ["VOLV-B.ST", "INVE-B.ST", "SEB-A.ST", "EVO.ST", "AZN.ST", "HM-B.ST", "ABB.ST", "ERIC-B.ST", "NDA-SE.ST", "ASSA-B.ST", "SAND.ST", "SWED-A.ST"]

# Ladda ner all data först
data_pool = {}
for sym in STOCKS:
    df = yf.Ticker(sym).history(period="3y")
    if not df.empty:
        df.index = df.index.normalize()
        df["MA50"] = df.Close.rolling(50).mean()
        df["MA200"] = df.Close.rolling(200).mean()
        df["RSI"] = calc_rsi(df.Close)
        hl = df.High - df.Low
        hc, lc = (df.High - df.Close.shift()).abs(), (df.Low - df.Close.shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
        data_pool[sym] = df.dropna()

results = []

# Vi testar rymden av möjligheter
for rsi_limit in [30, 35, 40]:
    for hold_days in [5, 10, 15, 20]:
        for atr_mult in [2.5, 3.5, 4.5]:
            
            total_pl = 0
            trades_count = 0
            wins = 0
            
            for sym, df in data_pool.items():
                in_trade = False
                entry_p = 0
                sl = 0
                days = 0
                
                for i in range(len(df)):
                    row = df.iloc[i]
                    
                    if not in_trade:
                        # Entry-villkor: RSI under gräns + Pris över MA200 (Trend)
                        if row.RSI < rsi_limit and row.Close > row.MA200:
                            in_trade = True
                            entry_p = row.Close
                            sl = entry_p - (atr_mult * row.ATR)
                            days = 0
                    else:
                        days += 1
                        # Exit-villkor: Stop loss eller Tid
                        if row.Low <= sl:
                            total_pl += (sl / entry_p - 1)
                            trades_count += 1
                            in_trade = False
                        elif days >= hold_days:
                            total_pl += (row.Close / entry_p - 1)
                            trades_count += 1
                            if row.Close > entry_p: wins += 1
                            in_trade = False
            
            if trades_count > 0:
                avg_ret = (total_pl / trades_count) * 100
                wr = (wins / trades_count) * 100
                results.append({
                    "RSI": rsi_limit, "Dagar": hold_days, "ATR": atr_mult,
                    "Affärer": trades_count, "Snitt %": avg_ret, "Win Rate %": wr,
                    "Score": avg_ret * trades_count # Enkel "Totalavkastning"-vikt
                })

report = pd.DataFrame(results)
print(report.sort_values("Score", ascending=False).head(10).to_string(index=False))
