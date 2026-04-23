import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/app/data/trading.db"

def run_breakout_test(atr_mult, hold_days, vol_mult):
    conn = sqlite3.connect(DB_PATH)
    # Hämta symboler
    omx_syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM history WHERE symbol LIKE '%.ST'").fetchall()]
    
    # Hämta index för marknadsfilter
    idx = pd.read_sql_query("SELECT date, close, ma200 FROM history WHERE symbol = '^OMX' ORDER BY date", conn)
    dates = idx['date'].tolist()
    start_idx = max(0, len(dates) - (5 * 252))
    
    cash = 100000
    holdings = []
    trades = []
    
    for date in dates[start_idx:]:
        still_holding = []
        portfolio_value = cash
        
        # 1. Exits
        for h in holdings:
            row = conn.execute("SELECT low, high, close FROM history WHERE symbol = ? AND date = ?", (h["sym"], date)).fetchone()
            if not row: 
                portfolio_value += (h["qty"] * h["last_p"])
                still_holding.append(h); continue
            
            h["last_p"] = row[2]
            exit_p = None
            if row[0] <= h["sl"]: exit_p = h["sl"] # Stop Loss
            elif h["days"] >= hold_days: exit_p = row[2] # Time Exit
            
            if exit_p:
                cash += (h["qty"] * exit_p)
                trades.append(exit_p / h["entry"] - 1)
            else:
                h["days"] += 1
                portfolio_value += (h["qty"] * row[2])
                still_holding.append(h)
        holdings = still_holding

        # 2. Entries (Breakout Logic)
        if len(holdings) < 3:
            idx_row = idx[idx['date'] == date].iloc[0]
            if idx_row['close'] > idx_row['ma200']:
                # Hitta aktier som gör 20-dagars breakout med hög volym
                for sym in omx_syms:
                    if any(h["sym"] == sym for h in holdings): continue
                    
                    # Kolla breakout och volym
                    # (Vi simulerar 'High > last 20 days high' och 'Volume > avg')
                    data = conn.execute("""
                        SELECT close, high, volume, atr,
                        (SELECT MAX(high) FROM history h2 WHERE h2.symbol = history.symbol AND h2.date < history.date ORDER BY h2.date DESC LIMIT 20) as last_high,
                        (SELECT AVG(volume) FROM history h3 WHERE h3.symbol = history.symbol AND h3.date < history.date ORDER BY h3.date DESC LIMIT 20) as avg_vol
                        FROM history WHERE symbol = ? AND date = ?
                    """, (sym, date)).fetchone()
                    
                    if data and data[0] and data[4] and data[5]:
                        # BREAKOUT KRITERIER:
                        # 1. Pris över förra 20 dagars topp
                        # 2. Volym > vol_mult * snitt
                        if data[0] > data[4] and data[2] > (data[5] * vol_mult):
                            entry = data[0]
                            pos_size = portfolio_value * 0.33
                            if cash >= pos_size:
                                holdings.append({
                                    "sym": sym, "entry": entry, "qty": pos_size/entry, 
                                    "sl": entry - (atr_mult * data[3]), "days": 0, "last_p": entry
                                })
                                cash -= pos_size
                                break # Max en ny per dag

    if not trades: return 0, 0
    return ((portfolio_value / 100000) - 1) * 100, len(trades)

print("Kör Breakout Sniper optimering för Sverige (5 år)...")
for vol in [1.2, 1.5]:
    for atr in [2.5, 3.5]:
        for hold in [15, 25]:
            ret, count = run_breakout_test(atr, hold, vol)
            print(f"Vol:{vol} ATR:{atr} Hold:{hold} -> 5-års vinst:{ret:.2f}% ({count} affärer)")
