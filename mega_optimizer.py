import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/app/data/trading.db"

def run_test(brk_days, atr_sl, vol_m, use_ma50, pos_size_pct):
    conn = sqlite3.connect(DB_PATH)
    omx_syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM history WHERE symbol LIKE '%.ST'").fetchall()]
    idx = pd.read_sql_query("SELECT date, close, ma200 FROM history WHERE symbol = '^OMX' ORDER BY date", conn)
    dates = idx['date'].tolist()
    start_idx = max(0, len(dates) - (5 * 252))
    
    cash = 100000
    holdings = []
    trades = []
    
    for date in dates[start_idx:]:
        still_holding = []
        portfolio_value = cash
        for h in holdings:
            row = conn.execute("SELECT low, high, close, ma50 FROM history WHERE symbol = ? AND date = ?", (h["sym"], date)).fetchone()
            if not row: 
                portfolio_value += (h["qty"] * h["last_p"]); still_holding.append(h); continue
            
            h["last_p"] = row[2]
            exit_p = None
            if row[0] <= h["sl"]: exit_p = h["sl"]
            elif use_ma50 and row[2] < row[3]: exit_p = row[2]
            
            if exit_p:
                cash += (h["qty"] * exit_p)
                trades.append(exit_p / h["entry"] - 1)
            else:
                portfolio_value += (h["qty"] * row[2])
                still_holding.append(h)
        holdings = still_holding

        if len(holdings) < (1 / pos_size_pct):
            idx_row = idx[idx['date'] == date].iloc[0]
            if idx_row['close'] > idx_row['ma200']:
                query = f"""
                    SELECT symbol, close, atr, volume,
                    (SELECT MAX(high) FROM history h2 WHERE h2.symbol = history.symbol AND h2.date < history.date ORDER BY h2.date DESC LIMIT {brk_days}) as last_h,
                    (SELECT AVG(volume) FROM history h3 WHERE h3.symbol = history.symbol AND h3.date < history.date ORDER BY h3.date DESC LIMIT 20) as avg_v
                    FROM history WHERE date = ? AND symbol LIKE '%.ST'
                """
                candidates = []
                for sym in omx_syms:
                    if any(h["sym"] == sym for h in holdings): continue
                    data = conn.execute(query, (date,)).fetchone()
                    if data and data[1] and data[4] and data[1] > data[4] and data[3] > (data[5] * vol_m):
                        candidates.append(data)
                
                if candidates:
                    best = candidates[0]
                    entry = best[1]
                    pos_size = portfolio_value * pos_size_pct
                    if cash >= pos_size:
                        holdings.append({"sym":best[0], "entry":entry, "sl":entry-(atr_sl*best[2]), "qty":pos_size/entry, "last_p":entry})
                        cash -= pos_size
    return ((portfolio_value / 100000) - 1) * 100

print("Startar Mega-Optimering...")
results = []
for brk in [5, 10, 20]:
    for sl in [2.5, 3.5, 4.5]:
        for vol in [1.1, 1.3]:
            for ma50 in [True, False]:
                ret = run_test(brk, sl, vol, ma50, 0.33)
                print(f"Brk:{brk} SL:{sl} Vol:{vol} MA50:{ma50} -> Ret:{ret:.2f}%")
                results.append({"brk":brk, "sl":sl, "vol":vol, "ma50":ma50, "ret":ret})

best = max(results, key=lambda x: x["ret"])
print("\n--- VINNARE ---")
print(best)
