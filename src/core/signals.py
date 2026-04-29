import sqlite3
from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100

# --- Konstanterna för strategin ---
# Optimerade via walk-forward validation (IS 2019-2022, OOS 2023-2026)
# Vinnare: OOS 72.4% vinstprocent, +13.2% avkastning mot 61.7% / +4.6% för baseline
OMX_ATR_MULT    = 4.5   # ATR-multiplikator för OMX stop loss (ökat från 3.5 → ger mer andrum)
NASDAQ_ATR_MULT = 3.5   # ATR-multiplikator för Nasdaq stop loss (optimerat: 4.5→3.5)
MA_MARGIN       = 0.993  # Hur långt under MA innan trendbrott utlöses
MA_ENTRY_MARGIN = 1.005  # Close måste vara denna % över MA vid köp
VOLUME_SURGE    = 1.6    # Volym måste vara denna × snittvolym vid utbrott (ökat från 1.2)
RSI_OVERBOUGHT  = 78     # RSI-nivå för vinsthemtagning (ökat från 70 → låter vinnare löpa)
RSI_OVERSOLD    = 45     # RSI-nivå för Nasdaq-köp (optimerat: 40→45 = fler trades, samma win-rate)
BREAKOUT_DAYS   = 40     # Antal dagar för att beräkna högsta (ökat från 20)
OMX_MAX_DAYS    = 27     # Max dagar i OMX-position innan timeout-exit
BUY_LIMIT_MARGIN = 1.003 # Limitpris = close × denna faktor vid köp


def check_exit(close, low, rsi, ma50, ma200, stop_loss, is_omx, max_days=None, days=0):
    """Returnerar (exit_pris, anledning) eller (None, None) om ingen exit."""
    if low is not None and low <= stop_loss:
        return stop_loss, "Stop loss utlöst"
    if rsi is not None and rsi > RSI_OVERBOUGHT:
        return close, f"Vinsthemtagning (RSI > {RSI_OVERBOUGHT})"
    if is_omx and close is not None and ma50 is not None and close < ma50 * MA_MARGIN:
        return close, "Trendbrott GM50"
    if not is_omx and close is not None and ma200 is not None and close < ma200 * MA_MARGIN:
        return close, "Trendbrott GM200"
    md = max_days if max_days is not None else (OMX_MAX_DAYS if is_omx else None)
    if md is not None and days >= md:
        return close, f"Timeout ({md} dagar)"
    return None, None


def find_omx_buys(db, holdings):
    held = {h["symbol"] for h in holdings}
    candidates = []
    for sym in OMXS_50.keys():
        if sym in held:
            continue
        row = db.execute("""
            SELECT close, volume, atr, ma50,
            (SELECT MAX(high) FROM history h2
             WHERE h2.symbol = history.symbol AND h2.date < history.date
             ORDER BY h2.date DESC LIMIT ?) as last_h,
            (SELECT AVG(volume) FROM history h3
             WHERE h3.symbol = history.symbol AND h3.date < history.date
             ORDER BY h3.date DESC LIMIT ?) as avg_v
            FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 1
        """, (BREAKOUT_DAYS, BREAKOUT_DAYS, sym)).fetchone()

        if not (row and row["close"] and row["last_h"] and row["avg_v"] and row["ma50"]):
            continue
        if (row["close"] > row["last_h"]
                and row["volume"] > row["avg_v"] * VOLUME_SURGE
                and row["close"] > row["ma50"] * MA_ENTRY_MARGIN):
            sl = row["close"] - OMX_ATR_MULT * row["atr"] if row["atr"] else row["close"] * 0.95
            candidates.append({
                "symbol": sym, "reason": f"Utbrott ({BREAKOUT_DAYS} dgr högsta)", "price": row["close"],
                "sl": sl,
                "recipe": {"type": "Standard Köp", "operator": "Direkt",
                           "trigger": 0, "limit": row["close"] * BUY_LIMIT_MARGIN}
            })
    return candidates


def find_nasdaq_buys(db, holdings):
    held = {h["symbol"] for h in holdings}
    candidates = []
    for sym in NASDAQ_100.keys():
        if sym in held:
            continue
        rows = db.execute(
            "SELECT close, rsi, ma200, atr FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 2",
            (sym,)
        ).fetchall()
        if len(rows) < 2:
            continue
        r_now, r_prev = rows[0], rows[1]

        # Rising MA200: MA200 idag måste vara högre än för 20 dagar sedan
        ma_old = db.execute(
            "SELECT ma200 FROM history WHERE symbol = ? AND ma200 IS NOT NULL ORDER BY date DESC LIMIT 1 OFFSET 19",
            (sym,)
        ).fetchone()

        if (r_now["rsi"] and r_prev["rsi"]
                and r_now["rsi"] < RSI_OVERSOLD
                and r_now["rsi"] > r_prev["rsi"]
                and r_now["ma200"]
                and r_now["close"] > r_now["ma200"] * MA_ENTRY_MARGIN
                and ma_old and r_now["ma200"] > ma_old["ma200"]):
            sl = r_now["close"] - NASDAQ_ATR_MULT * r_now["atr"] if r_now["atr"] else r_now["close"] * 0.90
            candidates.append({
                "symbol": sym, "reason": "Momentum (RSI vändning, stigande MA200)", "price": r_now["close"],
                "sl": sl,
                "recipe": {"type": "Stop Loss (Köp)", "operator": ">=",
                           "trigger": r_now["close"], "limit": r_now["close"] * 1.01}
            })
    return candidates


def generate_daily_orders():
    db = get_db()
    db.row_factory = sqlite3.Row

    sell_orders = []
    holdings = db.execute("SELECT * FROM holdings").fetchall()

    for h in holdings:
        if h["days_held"] == 0:
            continue
        last = db.execute(
            "SELECT close, low, rsi, ma50, ma200 FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 1",
            (h["symbol"],)
        ).fetchone()
        if not last:
            continue

        is_omx = h["symbol"].endswith(".ST")
        exit_p, reason = check_exit(
            last["close"], last["low"], last["rsi"], last["ma50"], last["ma200"],
            h["stop_loss"], is_omx
        )
        if exit_p is not None:
            sell_orders.append({
                "symbol": h["symbol"], "action": "SÄLJ", "reason": reason,
                "price": exit_p,
                "recipe": {"type": "Standard Sälj", "operator": "Direkt",
                           "trigger": 0, "limit": exit_p}
            })

    buy_orders = []
    if len(holdings) < 5:
        buy_orders = find_omx_buys(db, holdings) + find_nasdaq_buys(db, holdings)

    return {"sell": sell_orders, "buy": buy_orders[:5]}
