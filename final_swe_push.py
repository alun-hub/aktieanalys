import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/app/data/trading.db"

def run_test(rsi_limit, hold_days, atr_mult, take_profit):
    conn = sqlite3.connect(DB_PATH)
    idx_df = pd.read_sql_query("SELECT date, close, ma200 FROM history WHERE symbol = '^OMX' ORDER BY date", conn)
    omx_syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM history WHERE symbol LIKE '%.ST'").fetchall()]
    
    trades, initial_capital = [], 100000
    cash, holdings = initial_capital, []
    dates = idx_df['date'].tolist()
    start_idx = max(0, len(dates) - (5 * 252)) # 5 ÅR!
    portfolio_value = initial_capital

    for date in dates[start_idx:]:
        still_holding = []
        portfolio_value = cash
        for h in holdings:
            row = conn.execute("SELECT low, high, close FROM history WHERE symbol = ? AND date = ?", (h["sym"], date)).fetchone()
            if not row: 
                portfolio_value += (h["qty"] * h["last_p"])
                still_holding.append(h); continue
            h["last_p"] = row[2]
            
            exit_p = None
            if row[0] <= h["sl"]: exit_p = h["sl"] # Stop Loss
            elif row[1] >= h["entry"] * (1 + take_profit): exit_p = h["entry"] * (1 + take_profit) # Take Profit!
            elif h["days"] >= hold_days: exit_p = row[2] # Time Exit
            
            if exit_p:
                cash += (h["qty"] * exit_p)
                trades.append(exit_p/h["entry"]-1)
            else:
                h["days"] += 1
                portfolio_value += (h["qty"] * row[2])
                still_holding.append(h)
        holdings = still_holding

        if len(holdings) < 3: # Max 3 aktier för fokus
            idx_row = idx_df[idx_df['date'] == date].iloc[0]
            if idx_row['close'] > idx_row['ma200']:
                # Vi letar efter RS > 0 (starkare än index senaste 3 månaderna)
                # För enkelhet i detta skript kör vi på RSI och MA-trend
                query = f"SELECT symbol, close, rsi, atr FROM history WHERE date = ? AND rsi < ? AND close > ma200 AND symbol LIKE '%.ST' ORDER BY rsi ASC LIMIT 1"
                best = conn.execute(query, [date, rsi_limit]).fetchone()
                if best and not any(h["sym"]==best[0] for h in holdings):
                    entry = best[1]
                    holdings.append({"sym":best[0], "entry":entry, "sl":entry-(atr_mult*best[3]), "qty":(portfolio_value*0.33)/entry, "days":0, "last_p":entry})
                    cash -= (portfolio_value*0.33)
    return ((portfolio_value/initial_capital)-1)*100, len(trades)

print("Kör 5-års optimering för Stockholm...")
for rsi in [45, 50]:
    for hold in [15, 20]:
        for tp in [0.08, 0.12, 0.20]:
            for atr in [2.0, 3.0]:
                ret, count = run_test(rsi, hold, atr, tp)
                print(f"RSI:{rsi} Hold:{hold} TP:{tp} ATR:{atr} -> 5-års vinst:{ret:.2f}%")
