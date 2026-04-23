import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/app/data/trading.db"

def run_killer_test():
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
        
        # 1. Exits (Bara trendbrott)
        for h in holdings:
            row = conn.execute("SELECT low, close, ma50 FROM history WHERE symbol = ? AND date = ?", (h["sym"], date)).fetchone()
            if not row: 
                portfolio_value += (h["qty"] * h["last_p"]); still_holding.append(h); continue
            
            h["last_p"] = row[1]
            exit_p = None
            if row[0] <= h["sl"]: exit_p = h["sl"] # Hard Stop
            elif row[1] < row[2]: exit_p = row[1]  # Trendbrott (Pris < MA50)
            
            if exit_p:
                cash += (h["qty"] * exit_p)
                trades.append(exit_p / h["entry"] - 1)
            else:
                portfolio_value += (h["qty"] * row[1])
                still_holding.append(h)
        holdings = still_holding

        # 2. Entries (Bara 2 innehav, sök marknadens ledare)
        if len(holdings) < 2:
            idx_row = idx[idx['date'] == date].iloc[0]
            if idx_row['close'] > idx_row['ma200']:
                candidates = []
                for sym in omx_syms:
                    if any(h["sym"] == sym for h in holdings): continue
                    
                    data = conn.execute("""
                        SELECT close, atr, ma50, ma200,
                        (SELECT close/close_old - 1 FROM (SELECT close as close_old FROM history h2 WHERE h2.symbol = history.symbol AND h2.date < history.date ORDER BY h2.date DESC LIMIT 1 OFFSET 125)) as mom_6m
                        FROM history WHERE symbol = ? AND date = ?
                    """, (sym, date)).fetchone()
                    
                    if data and data[4] is not None:
                        # Kriterier: Stark upptrend + Ledar-momentum
                        if data[0] > data[2] > data[3] and data[4] > 0.10:
                            candidates.append({"sym": sym, "close": data[0], "atr": data[1], "mom": data[4]})
                
                if candidates:
                    # Välj den absolut starkaste
                    candidates.sort(key=lambda x: x["mom"], reverse=True)
                    best = candidates[0]
                    entry = best["close"]
                    pos_size = portfolio_value * 0.50
                    if cash >= pos_size:
                        holdings.append({
                            "sym": best["sym"], "entry": entry, "qty": pos_size/entry, 
                            "sl": entry - (5.0 * best["atr"]), "last_p": entry
                        })
                        cash -= pos_size
    
    return ((portfolio_value / 100000) - 1) * 100, len(trades)

ret, count = run_killer_test()
print(f"INVESTOR KILLER v12.0 -> 5-års vinst: {ret:.2f}% ({count} affärer)")
