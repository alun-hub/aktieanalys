from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100
import pandas as pd
import numpy as np

def generate_daily_orders():
    conn = get_db()
    conn.row_factory = sqlite3.Row if hasattr(sqlite3, 'Row') else None # Säkerställ row_factory
    
    # Workaround för sqlite3.Row utanför context
    db = get_db()
    db.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
    
    sell_orders = []
    holdings = db.execute("SELECT * FROM holdings").fetchall()
    
    for h in holdings:
        if h["days_held"] == 0: continue

        last = db.execute("SELECT close, low, high, rsi, ma50, ma200 FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 1", (h["symbol"],)).fetchone()
        if not last: continue
        
        is_omx = h["symbol"].endswith(".ST")
        
        # DEFENSIVA KONTROLLER FÖR SÄLJ-VILLKOR
        close = last.get("close")
        low = last.get("low")
        rsi = last.get("rsi")
        ma50 = last.get("ma50")
        
        if low is not None and low <= h["stop_loss"]:
            sell_orders.append({
                "symbol": h["symbol"], "action": "SÄLJ", "reason": "Stop loss utlöst",
                "details": f"Kursen har fallit under din säkerhetsnivå {h['stop_loss']:.2f}.", "price": h["stop_loss"],
                "recipe": {"type": "Stop Loss (Sälj)", "operator": "Lägre än eller lika med (<=)", "trigger": h["stop_loss"], "limit": h["stop_loss"] * 0.995, "validity": "1 vecka"}
            })
        elif rsi is not None and rsi > 70:
            sell_orders.append({
                "symbol": h["symbol"], "action": "SÄLJ", "reason": "Vinsthemtagning",
                "details": f"Aktien är överköpt (RSI:{rsi:.1f}). Dags att låsa in vinst.", "price": close,
                "recipe": {"type": "Glidande Stop Loss", "operator": "Procentuell avvikelse", "trigger": "2.5 %", "limit": "Marknad", "validity": "1 vecka"}
            })
        elif is_omx and close is not None and ma50 is not None and close < (ma50 * 0.995):
            sell_orders.append({
                "symbol": h["symbol"], "action": "SÄLJ", "reason": "Trendbrott GM50",
                "details": f"Kursen {close:.2f} har etablerat sig under GM50.", "price": close,
                "recipe": {"type": "Standard Sälj", "operator": "Direkt", "trigger": 0, "limit": close, "validity": "I dag"}
            })

    buy_orders = []
    if len(holdings) < 5:
        # SVERIGE (Utbrott)
        for sym in OMXS_50.keys():
            if any(h["symbol"] == sym for h in holdings): continue
            row = db.execute("""
                SELECT close, volume, atr, rsi, ma50,
                (SELECT MAX(high) FROM history h2 WHERE h2.symbol = history.symbol AND h2.date < history.date ORDER BY h2.date DESC LIMIT 20) as last_h,
                (SELECT AVG(volume) FROM history h3 WHERE h3.symbol = history.symbol AND h3.date < history.date ORDER BY h3.date DESC LIMIT 20) as avg_v
                FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 1
            """, (sym,)).fetchone()
            
            if row and row["close"] and row["last_h"] and row["volume"] and row["avg_v"]:
                if row["close"] > row["last_h"] and row["volume"] > row["avg_v"] * 1.2 and row["ma50"] and row["close"] > (row["ma50"] * 1.005):
                    buy_orders.append({
                        "symbol": sym, "reason": "Utbrott (20 dgr högsta)", "price": row["close"], "sl": row["close"] - (3.5 * row["atr"]) if row["atr"] else row["close"]*0.95,
                        "details": f"Aktien har brutit upp över motståndet {row['last_h']:.2f}.", "market": "Sverige",
                        "recipe": {"type": "Standard Köp (Limit)", "operator": "Direkt", "trigger": 0, "limit": row["close"] * 1.003, "validity": "I dag"}
                    })

        # USA (Momentum)
        for sym in NASDAQ_100.keys():
            if any(h["symbol"] == sym for h in holdings): continue
            rows = db.execute("SELECT close, rsi, ma200, atr FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 2", (sym,)).fetchall()
            if len(rows) < 2: continue
            r_now, r_prev = rows[0], rows[1]
            if r_now["rsi"] and r_prev["rsi"] and r_now["rsi"] < 40 and r_now["rsi"] > r_prev["rsi"] and r_now["close"] and r_now["ma200"] and r_now["close"] > (r_now["ma200"] * 1.005):
                buy_orders.append({
                    "symbol": sym, "reason": "Momentum (RSI vändning)", "price": r_now["close"], "sl": r_now["close"] - (4.5 * r_now["atr"]) if r_now["atr"] else r_now["close"]*0.90,
                    "details": "RSI har vänt upp från en dipp.", "market": "USA",
                    "recipe": {"type": "Stop Loss (Köp)", "operator": "Högre än eller lika med (>=)", "trigger": r_now["close"], "limit": r_now["close"] * 1.01, "validity": "1 vecka"}
                })

    return {"sell": sell_orders, "buy": buy_orders[:5]}

import sqlite3 # Import behövs inuti filen
def run_backtest_local(market="omxs", years=5):
    conn = get_db(); is_omx = (market == "omxs"); idx_ticker = "^OMX" if is_omx else "^NDX"
    all_symbols = list(OMXS_50.keys()) if is_omx else list(NASDAQ_100.keys())
    dates_df = pd.read_sql_query("SELECT DISTINCT date FROM history WHERE symbol = ? ORDER BY date", conn, params=(idx_ticker,))
    if dates_df.empty: return {"error": "Ingen historik."}
    dates = dates_df['date'].tolist(); start_idx = max(0, len(dates)-(years*252))
    trades, cash, holdings, initial_cap = [], 100000, [], 100000
    for date in dates[start_idx:]:
        still_holding, port_v = [], cash
        for h in holdings:
            row = conn.execute("SELECT low, high, close, rsi, ma50, ma200 FROM history WHERE symbol = ? AND date = ?", (h["sym"], date)).fetchone()
            if not row: port_v += (h["qty"] * h["last_p"]); still_holding.append(h); continue
            h["last_p"] = row[2]; exit_p = None
            if h["days"] > 0: 
                if row[0] is not None and row[0] <= h["sl"]: exit_p = h["sl"]
                elif row[3] is not None and row[3] > 70: exit_p = row[2]
                elif is_omx and row[2] is not None and row[4] is not None and row[2] < (row[4] * 0.995): exit_p = row[2]
                elif not is_omx and row[2] is not None and row[5] is not None and row[2] < (row[5] * 0.995): exit_p = row[2]
                elif h["days"] >= (12 if is_omx else 20): exit_p = row[2]
            
            if exit_p: cash += (h["qty"] * exit_p); trades.append(exit_p / h["entry"] - 1)
            else: h["days"] += 1; port_v += (h["qty"] * row[2]); still_holding.append(h)
        holdings = still_holding
        if len(holdings) < 5:
            idx_row = conn.execute("SELECT close, ma200 FROM history WHERE symbol = ? AND date = ?", (idx_ticker, date)).fetchone()
            if idx_row and idx_row[0] is not None and idx_row[1] is not None and idx_row[0] > idx_row[1]:
                if is_omx:
                    query = "SELECT symbol, close, atr, rsi FROM history WHERE date = ? AND symbol IN ({}) AND ma50 IS NOT NULL AND close > (SELECT MAX(high) FROM history h2 WHERE h2.symbol = history.symbol AND h2.date < history.date ORDER BY h2.date DESC LIMIT 20) AND volume > (SELECT AVG(volume) FROM history h3 WHERE h3.symbol = history.symbol AND h3.date < history.date ORDER BY h3.date DESC LIMIT 20) * 1.2 AND close > (ma50 * 1.005) LIMIT 1".format(','.join(['?']*len(all_symbols)))
                    best = conn.execute(query, [date] + all_symbols).fetchone()
                    if best and not any(h["sym"]==best[0] for h in holdings):
                        p_size = port_v * 0.20
                        holdings.append({"sym":best[0], "entry":best[1], "sl":best[1]-(3.5*best[2]) if best[2] else best[1]*0.95, "qty":p_size/best[1], "days":0, "last_p":best[1]})
                        cash -= p_size
                else:
                    query = "SELECT symbol, close, atr, rsi FROM history h1 WHERE date = ? AND ma200 IS NOT NULL AND rsi < 40 AND rsi > (SELECT rsi FROM history h2 WHERE h2.symbol = h1.symbol AND h2.date < h1.date ORDER BY h2.date DESC LIMIT 1) AND close > (ma200 * 1.005) AND symbol IN ({}) LIMIT 1".format(','.join(['?']*len(all_symbols)))
                    best = conn.execute(query, [date] + all_symbols).fetchone()
                    if best and not any(h["sym"]==best[0] for h in holdings):
                        p_size = port_v * 0.20
                        holdings.append({"sym":best[0], "entry":best[1], "sl":best[1]-(4.5*best[2]) if best[2] else best[1]*0.90, "qty":p_size/best[1], "days":0, "last_p":best[1]})
                        cash -= p_size
    return {"trades": len(trades), "return": round(((port_v/initial_cap)-1)*100, 2), "win_rate": round((len([t for t in trades if t > 0])/len(trades)*100) if trades else 0, 2)}
