import time
import datetime
import yfinance as yf
from src.core.config import OMXS_50, NASDAQ_100
from src.core.signals import trend_score
from src.core.data import get_db

_DIVIDEND_CACHE = {}
_CACHE_TTL = 3600  # 1 timme


def score_dividend_stock(
    yield_pct: float,
    payout_ratio: float = None,
    pe: float = None,
    trend_score_val: float = 50.0,
) -> dict:
    """Beräknar ett samlat utdelnings- och kvalitetsbetyg (0–100)."""
    if yield_pct is None or yield_pct <= 0:
        return {
            "dividend_score": 0.0,
            "yield_score": 0.0,
            "payout_score": 0.0,
            "valuation_score": 0.0,
            "trend_score": 0.0,
            "verdict": "Ingen utdelning",
        }

    # 1. Direktavkastningspoäng (0–100)
    # 3.5 - 8.0 % är idealiskt
    if yield_pct < 1.5:
        y_score = yield_pct * 30.0
    elif yield_pct <= 3.5:
        y_score = 45.0 + (yield_pct - 1.5) * 20.0
    elif yield_pct <= 8.0:
        y_score = 85.0 + (yield_pct - 3.5) * 3.3
    elif yield_pct <= 12.0:
        y_score = 100.0 - (yield_pct - 8.0) * 5.0
    else:
        y_score = max(20.0, 80.0 - (yield_pct - 12.0) * 8.0)  # Utdelningsfällerisk

    # 2. Utdelningsandel (Payout ratio) (0–100)
    if payout_ratio is None:
        p_score = 50.0
    elif payout_ratio < 0:
        p_score = 10.0  # Negativ vinst
    elif payout_ratio <= 20.0:
        p_score = 65.0  # Mycket låg utdelningsandel
    elif payout_ratio <= 70.0:
        p_score = 100.0  # Hållbar och sund
    elif payout_ratio <= 85.0:
        p_score = 75.0
    elif payout_ratio <= 100.0:
        p_score = 40.0
    else:
        p_score = 10.0  # Utdelning överstiger vinst

    # 3. Värdering & P/E (0–100)
    if pe is None or pe <= 0:
        v_score = 25.0
    elif pe < 6.0:
        v_score = 70.0  # Kan vara cyklisk topp
    elif pe <= 18.0:
        v_score = 100.0  # Mycket attraktiv värdering
    elif pe <= 26.0:
        v_score = 65.0
    else:
        v_score = max(10.0, 65.0 - (pe - 26.0) * 3.0)

    # 4. Teknisk trend (0–100)
    t_score = max(0.0, min(100.0, float(trend_score_val if trend_score_val is not None else 50.0)))

    # Sammanvägning (Yield: 35%, Payout: 25%, PE: 20%, Trend: 20%)
    tot = (0.35 * y_score) + (0.25 * p_score) + (0.20 * v_score) + (0.20 * t_score)
    final_score = round(max(0.0, min(100.0, tot)), 1)

    # Omdöme i klarspråk
    if yield_pct > 12.0 and p_score < 40.0:
        verdict = "Varning för utdelningsfälla (ohållbar utdelningsandel)"
    elif final_score >= 80.0:
        verdict = "Stark kvalitetsutdelare med sund trend"
    elif final_score >= 65.0:
        verdict = "Stabil utdelningsaktie med god avkastning"
    elif final_score >= 50.0:
        verdict = "Måttlig kvalitet eller ansträngd värdering"
    else:
        verdict = "Hög risk eller svag trend"

    return {
        "dividend_score": final_score,
        "yield_score": round(y_score, 1),
        "payout_score": round(p_score, 1),
        "valuation_score": round(v_score, 1),
        "trend_score": round(t_score, 1),
        "verdict": verdict,
    }


def get_top_dividend_stocks(
    market: str = "all", limit: int = 10, force_refresh: bool = False
) -> dict:
    """Hämtar och rankar de bästa utdelningsaktierna för angiven marknad."""
    global _DIVIDEND_CACHE
    now = time.time()
    market = (market or "all").lower()

    cached = _DIVIDEND_CACHE.get(market)
    if not force_refresh and cached and (now - cached["ts"] < _CACHE_TTL):
        return cached["data"]

    db = get_db()
    tickers = {}
    if market in ("all", "omx", "omxs"):
        tickers.update({s: (n, "OMX") for s, n in OMXS_50.items()})
    if market in ("all", "nasdaq"):
        tickers.update({s: (n, "NASDAQ") for s, n in NASDAQ_100.items()})

    scored_stocks = []

    try:
        for sym, (name, mkt) in tickers.items():
            # Hämta senaste tekniska data från SQLite
            row = db.execute(
                "SELECT close, ma50, ma200, rsi, atr FROM history "
                "WHERE symbol = ? AND close IS NOT NULL ORDER BY date DESC LIMIT 1",
                (sym,),
            ).fetchone()
            if not row:
                continue

            close = float(row["close"])
            ma50 = float(row["ma50"]) if row["ma50"] is not None else None
            ma200 = float(row["ma200"]) if row["ma200"] is not None else None
            rsi = float(row["rsi"]) if row["rsi"] is not None else None

            tscore = trend_score(close, ma50, ma200, rsi)

            # Hämta fundamenta via yfinance
            try:
                t = yf.Ticker(sym)
                info = t.info or {}
                raw_yield = info.get("dividendYield")
                if not raw_yield:
                    continue

                # yfinance returnerar procent (t.ex. 5.4) eller decimal (0.054)
                yield_pct = float(raw_yield)
                if yield_pct < 0.25:
                    yield_pct = yield_pct * 100.0

                raw_payout = info.get("payoutRatio")
                if raw_payout is not None:
                    payout_pct = float(raw_payout)
                    if payout_pct <= 2.0:
                        payout_pct = payout_pct * 100.0
                else:
                    payout_pct = None

                raw_pe = info.get("trailingPE")
                pe = float(raw_pe) if raw_pe is not None and raw_pe == raw_pe else None

                score_data = score_dividend_stock(yield_pct, payout_pct, pe, tscore)
                curr = "$" if mkt == "NASDAQ" else "kr"

                scored_stocks.append(
                    {
                        "symbol": sym,
                        "name": name,
                        "market": mkt,
                        "currency": curr,
                        "close": round(close, 2),
                        "dividend_yield": round(yield_pct, 2),
                        "payout_ratio": round(payout_pct, 1) if payout_pct is not None else None,
                        "pe": round(pe, 1) if pe is not None else None,
                        "trend_score": tscore,
                        "dividend_score": score_data["dividend_score"],
                        "yield_score": score_data["yield_score"],
                        "payout_score": score_data["payout_score"],
                        "valuation_score": score_data["valuation_score"],
                        "verdict": score_data["verdict"],
                    }
                )
            except Exception:
                continue
    finally:
        db.close()

    # Sortera på dividend_score fallande
    scored_stocks.sort(key=lambda x: x["dividend_score"], reverse=True)
    top_stocks = scored_stocks[:limit]

    # Tilldela rank
    for idx, s in enumerate(top_stocks, 1):
        s["rank"] = idx

    result = {
        "market": market,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stocks": top_stocks,
    }

    _DIVIDEND_CACHE[market] = {"data": result, "ts": now}
    return result
