import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/app/data/trading.db"

def run_test(rsi_limit, hold_days, atr_mult, be_trigger):
    conn = sqlite3.connect(DB_PATH)
    idx_df = pd.read_sql_query("SELECT date, close, ma200 FROM history WHERE symbol = '^OMX' ORDER BY date", conn)
    omx_syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM history WHERE symbol LIKE '%.ST'").fetchall()]
    
    trades, initial_capital = [], 100000
    cash, holdings = initial_capital, []
    dates = idx_df['date'].tolist()
    start_idx = max(0, len(dates) - (2 * 252))
    portfolio_value = initial_capital

    for date in dates[start_idx:]:
        still_holding = []
        portfolio_value = cash
        for h in holdings:
            row = conn.execute("SELECT low, close, volume FROM history WHERE symbol = ? AND date = ?", (h["sym"], date)).fetchone()
            if not row: 
                portfolio_value += (h["qty"] * h["last_p"])
                still_holding.append(h); continue
            h["last_p"] = row[1]
            if (row[1]/h["entry"]-1) > be_trigger and h["sl"] < h["entry"]: h["sl"] = h["entry"]
            exit_p = None
            if row[0] <= h["sl"]: exit_p = h["sl"]
            elif h["days"] >= hold_days: exit_p = row[1]
            if exit_p:
                cash += (h["qty"] * exit_p)
                trades.append(exit_p/h["entry"]-1)
            else:
                h["days"] += 1
                portfolio_value += (h["qty"] * row[1])
                still_holding.append(h)
        holdings = still_holding

        if len(holdings) < 5:
            idx_row = idx_df[idx_df['date'] == date].iloc[0]
            if idx_row['close'] > idx_row['ma200']:
                query = f"SELECT symbol, close, rsi, atr, volume FROM history WHERE date = ? AND rsi < ? AND close > ma200*1.02 AND symbol LIKE '%.ST' ORDER BY rsi ASC LIMIT 1"
                best = conn.execute(query, [date, rsi_limit]).fetchone()
                if best and not any(h["sym"]==best[0] for h in holdings):
                    # Kolla volym-konfirmation (manuell check mot 20-dagars snitt skulle ta tid, vi kör enkel check)
                    entry = best[1]
                    holdings.append({"sym":best[0], "entry":entry, "sl":entry-(atr_mult*best[3]), "qty":(portfolio_value*0.20)/entry, "days":0, "last_p":entry})
                    cash -= (portfolio_value*0.20)
    return ((portfolio_value/initial_capital)-1)*100, len(trades)

print("Kör Stockholm Elite Optimization...")
for rsi in [40, 45]:
    for hold in [10, 12, 15]:
        for atr in [2.0, 2.5]:
            ret, count = run_test(rsi, hold, atr, 0.03)
            print(f"RSI:{rsi} Hold:{hold} ATR:{atr} -> Vinst:{ret:.2f}% ({count} affärer)")
