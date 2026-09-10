"""Marknadsläge – teknisk trendbild för bevakade aktier.

Detta är INTE köp-/säljrekommendationer. Det säger bara om priset just nu ligger
i en uppåt- eller nedåttrend enligt glidande medelvärden och RSI. Insyns- och
kongressköp påverkar ingenting här – de visas som ren information i bolagsvyn.
"""
import sqlite3
from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100

ATR_STOP_MULT = 3.0   # samma multipel som bolagsvyns nivåkalkyl


def trend_score(close, ma50, ma200, rsi):
    """0–100 där 50 = neutralt. Symmetriskt: death cross straffar lika mycket
    som golden cross belönar. RSI vägs in kontinuerligt."""
    s = 50.0
    if ma200:
        s += 18 if close > ma200 else -18
    if ma50:
        s += 12 if close > ma50 else -12
    if ma50 and ma200:
        s += 8 if ma50 > ma200 else -8
    if rsi is not None:
        s += (rsi - 50) * 0.3
        if rsi > 75:
            s -= (rsi - 75) * 1.0          # överköpt = risk, inte styrka
        elif rsi < 25:
            s -= (25 - rsi) * 0.4          # kraftigt översålt = svaghet
    return max(2.0, min(98.0, round(s, 1)))


def trend_label(score):
    if score >= 68:
        return "Stark uppåttrend", "up-strong"
    if score >= 55:
        return "Svag uppåttrend", "up"
    if score > 45:
        return "Neutral / oklart", "neutral"
    if score > 32:
        return "Svag nedåttrend", "down"
    return "Stark nedåttrend", "down-strong"


def _reasons(close, ma50, ma200, rsi, curr):
    out = []
    if ma200:
        out.append(f"{'Över' if close > ma200 else 'Under'} 200-dagars medelvärde ({ma200:g} {curr})")
    if ma50 and ma200:
        out.append("Golden cross (MA50 > MA200)" if ma50 > ma200 else "Death cross (MA50 < MA200)")
    if rsi is not None:
        if rsi > 75:
            out.append(f"RSI {rsi:g} – överköpt")
        elif rsi < 30:
            out.append(f"RSI {rsi:g} – översålt")
        else:
            out.append(f"RSI {rsi:g}")
    return out


def run_market_screener(market="all"):
    db = get_db()
    db.row_factory = sqlite3.Row

    tickers = {}
    if market in ("all", "omx", "omxs"):
        tickers.update({s: (n, "OMX") for s, n in OMXS_50.items()})
    if market in ("all", "nasdaq"):
        tickers.update({s: (n, "NASDAQ") for s, n in NASDAQ_100.items()})

    results = []
    for sym, (name, mkt) in tickers.items():
        rows = db.execute(
            "SELECT date, close, open, ma50, ma200, rsi, atr FROM history "
            "WHERE symbol = ? ORDER BY date DESC LIMIT 2", (sym,)).fetchall()
        if not rows or rows[0]["close"] is None:
            continue
        now, prev = rows[0], (rows[1] if len(rows) > 1 else rows[0])
        close = float(now["close"])
        prev_close = float(prev["close"]) if prev["close"] else close
        curr = "$" if mkt == "NASDAQ" else "kr"

        rsi = round(float(now["rsi"]), 1) if now["rsi"] is not None else None
        ma50 = round(float(now["ma50"]), 2) if now["ma50"] is not None else None
        ma200 = round(float(now["ma200"]), 2) if now["ma200"] is not None else None
        atr = float(now["atr"]) if now["atr"] is not None else close * 0.03

        score = trend_score(close, ma50, ma200, rsi)
        label, tclass = trend_label(score)
        stop = round(close - ATR_STOP_MULT * atr, 2)

        results.append({
            "symbol": sym, "name": name, "market": mkt, "currency": curr,
            "close": round(close, 2),
            "change_pct": round((close / prev_close - 1) * 100, 2) if prev_close else 0.0,
            "rsi": rsi, "ma50": ma50, "ma200": ma200,
            "trend_score": score, "trend_label": label, "trend_class": tclass,
            "reasons": _reasons(close, ma50, ma200, rsi, curr),
            "levels": {
                "atr": round(atr, 2),
                "atr_pct": round(atr / close * 100, 1),
                "stop_suggestion": stop,
                "stop_pct": round((stop / close - 1) * 100, 1),
            },
        })

    db.close()
    results.sort(key=lambda x: x["trend_score"], reverse=True)
    return results
