import sqlite3
import pandas as pd
from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100

# --- Konstanterna för strategin ---
OMX_ATR_MULT     = 4.5
NASDAQ_ATR_MULT  = 3.5
MA_MARGIN        = 0.993
MA_ENTRY_MARGIN  = 1.005
VOLUME_SURGE     = 1.6
RSI_OVERBOUGHT   = 78
RSI_OVERSOLD     = 45
BREAKOUT_DAYS    = 40
OMX_MAX_DAYS     = 27
BUY_LIMIT_MARGIN = 1.003

def check_exit(close, low, rsi, ma50, ma200, stop_loss, is_omx, max_days=None, days=0):
    """Returnerar (exit_pris, anledning) eller (None, None) om ingen exit."""
    if low is not None and stop_loss is not None and low <= stop_loss:
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

def run_market_screener(market="all"):
    """Kör komplett marknadsscreener och returnerar rekommendationer för alla bevakade aktier.
    market: 'all', 'omx', eller 'nasdaq'
    """
    db = get_db()
    db.row_factory = sqlite3.Row

    tickers_to_scan = {}
    if market in ("all", "omx"):
        tickers_to_scan.update({sym: (name, "OMX") for sym, name in OMXS_50.items()})
    if market in ("all", "nasdaq"):
        tickers_to_scan.update({sym: (name, "NASDAQ") for sym, name in NASDAQ_100.items()})

    results = []
    
    for sym, (name, mkt) in tickers_to_scan.items():
        rows = db.execute("""
            SELECT date, close, open, high, low, volume, ma50, ma200, rsi, atr
            FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 2
        """, (sym,)).fetchall()

        if not rows or len(rows) < 1 or rows[0]["close"] is None:
            continue

        r_now = rows[0]
        r_prev = rows[1] if len(rows) > 1 else rows[0]

        close = float(r_now["close"])
        prev_close = float(r_prev["close"]) if r_prev["close"] else close
        change_pct = round(((close / prev_close) - 1) * 100, 2) if prev_close else 0.0

        rsi = round(float(r_now["rsi"]), 1) if r_now["rsi"] is not None else None
        rsi_prev = round(float(r_prev["rsi"]), 1) if r_prev["rsi"] is not None else None
        ma50 = round(float(r_now["ma50"]), 2) if r_now["ma50"] is not None else None
        ma200 = round(float(r_now["ma200"]), 2) if r_now["ma200"] is not None else None
        atr = float(r_now["atr"]) if r_now["atr"] is not None else (close * 0.03)

        # ── Teknisk Poängsättning ──
        score = 50
        reasons = []

        # 1. Trend MA200 & MA50
        if ma200:
            if close > ma200:
                score += 20
                reasons.append("Över MA200 (bullish)")
            else:
                score -= 20
                reasons.append("Under MA200 (bearish)")

        if ma50:
            if close > ma50:
                score += 15
                reasons.append("Över MA50")
            else:
                score -= 15
                reasons.append("Under MA50")

            if ma200 and ma50 > ma200:
                score += 10
                reasons.append("Golden Cross")

        # 2. RSI Momentum
        if rsi:
            if rsi < 40 and rsi_prev and rsi > rsi_prev:
                score += 25
                reasons.append(f"RSI-vändning upp ({rsi})")
            elif rsi > 72:
                score -= 15
                reasons.append(f"Överköpt RSI ({rsi})")
            elif 45 <= rsi <= 65:
                score += 15
                reasons.append(f"Starkt momentum ({rsi})")

        score = max(5, min(95, score))

        # Rekommendations-nivå
        if score >= 70:
            rek = "KÖP (STARK)"
            rek_class = "prime"
        elif score >= 55:
            rek = "KÖP"
            rek_class = "bra"
        elif score <= 38:
            rek = "SÄLJ"
            rek_class = "undvik"
        else:
            rek = "BEVAKA"
            rek_class = "vanta"

        # Riskhantering / Avanza-recept
        sl = round(close - (3.0 * atr), 2)
        risk = max(0.1, close - sl)
        tp1 = round(close + (1.8 * risk), 2)
        tp2 = round(close + (3.2 * risk), 2)

        results.append({
            "symbol": sym,
            "name": name,
            "market": mkt,
            "close": close,
            "change_pct": change_pct,
            "rsi": rsi,
            "ma50": ma50,
            "ma200": ma200,
            "score": score,
            "rek": rek,
            "rek_class": rek_class,
            "reasons": reasons,
            "recipe": {
                "type": "Standard Köp",
                "buy_limit": round(close * BUY_LIMIT_MARGIN, 2),
                "stop_loss_trigger": sl,
                "stop_loss_limit": round(sl * 0.995, 2),
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "risk_reward": "1:1.8",
                "courtage_tip": "Mini vid order <15 000 kr, annars Small"
            }
        })

    # Sortera primärt på Score fallande
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def generate_daily_orders():
    """Bakåtkompatibilitet för äldre anrop."""
    results = run_market_screener(market="all")
    buys = [r for r in results if "KÖP" in r.get("rek", "")]
    sells = [r for r in results if "SÄLJ" in r.get("rek", "")]
    return {"buy": buys, "sell": sells, "all": results}
