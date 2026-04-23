import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/app/data/trading.db"

def run_backtest(market_symbols, idx_ticker, years, rsi_entry, hold_days, atr_mult, be_trigger, use_ma50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    idx_df = pd.read_sql_query("SELECT date, close, ma200 FROM history WHERE symbol = ? ORDER BY date", conn, params=(idx_ticker,))
    if idx_df.empty: return -999, 0

    dates = idx_df['date'].tolist()
    start_idx = max(0, len(dates) - (years * 252))
    
    trades = []
    capital = 100000
    portfolio_value = capital
    cash = capital
    holdings = [] # {sym, entry, sl, qty, days, last_p}

    for date in dates[start_idx:]:
        still_holding = []
        portfolio_value = cash
        
        # 1. Exits
        for h in holdings:
            row = conn.execute("SELECT low, close, ma50 FROM history WHERE symbol = ? AND date = ?", (h["sym"], date)).fetchone()
            if not row: 
                portfolio_value += (h["qty"] * h["last_p"])
                still_holding.append(h); continue
            
            h["last_p"] = row["close"]
            # Breakeven
            if (row["close"] / h["entry"] - 1) > be_trigger and h["sl"] < h["entry"]: h["sl"] = h["entry"]

            exit_p = None
            if row["low"] <= h["sl"]: exit_p = h["sl"]
            elif h["days"] >= hold_days: exit_p = row["close"]
            elif use_ma50 and row["close"] < row["ma50"]: exit_p = row["close"]
            
            if exit_p:
                cash += (h["qty"] * exit_p)
                trades.append(exit_p / h["entry"] - 1)
            else:
                h["days"] += 1
                portfolio_value += (h["qty"] * row["close"])
                still_holding.append(h)
        holdings = still_holding
        
        # 2. Entries
        if len(holdings) < 5:
            idx_row = idx_df[idx_df['date'] == date].iloc[0]
            if idx_row['close'] > idx_row['ma200']:
                placeholders = ','.join(['?'] * len(market_symbols))
                query = f"SELECT symbol, close, rsi, atr FROM history WHERE date = ? AND rsi < ? AND close > ma200 AND symbol IN ({placeholders}) ORDER BY rsi ASC LIMIT 1"
                best = conn.execute(query, [date, rsi_entry] + market_symbols).fetchone()
                
                if best and not any(h["sym"] == best["symbol"] for h in holdings):
                    pos_size = portfolio_value * 0.20
                    if cash >= pos_size:
                        entry = best["close"]
                        holdings.append({"sym": best["symbol"], "entry": entry, "sl": entry - (atr_mult * best["atr"]), "qty": pos_size/entry, "days": 0, "last_p": entry})
                        cash -= pos_size
    
    total_ret = ((portfolio_value / capital) - 1) * 100
    return total_ret, len(trades)

# Hämta symboler från DB
conn = sqlite3.connect(DB_PATH)
all_syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM history").fetchall()]
omx_syms = [s for s in all_syms if s.endswith(".ST")]
ndx_syms = [s for s in all_syms if not s.endswith(".ST") and not s.startswith("^")]

print("--- TUNING STOCKHOLM (OMX) ---")
best_omx = {"ret": -999}
for rsi in [40, 45, 50]:
    for hold in [10, 15, 20]:
        for atr in [3.0, 4.0]:
            for be in [0.02, 0.04, 99]:
                ret, count = run_backtest(omx_syms, "^OMX", 2, rsi, hold, atr, be, False)
                if ret > best_omx["ret"]:
                    best_omx = {"ret": ret, "count": count, "rsi": rsi, "hold": hold, "atr": atr, "be": be}

print(best_omx)

print("\n--- TUNING USA (NASDAQ) ---")
best_ndx = {"ret": -999}
for rsi in [40, 45, 50]:
    for hold in [15, 20, 25]:
        for atr in [3.5, 4.5]:
            ret, count = run_backtest(ndx_syms, "^NDX", 2, rsi, hold, atr, 99, False)
            if ret > best_ndx["ret"]:
                best_ndx = {"ret": ret, "count": count, "rsi": rsi, "hold": hold, "atr": atr}

print(best_ndx)
