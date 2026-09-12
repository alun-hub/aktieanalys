"""Marknadsregim-modul för att bedöma det övergripande marknadsklimatet.

Undersöker om huvudindex (OMXS30 / Nasdaq 100) handlas i en bull market
eller bear market. I en bear market filtreras eller dämpas köpsignaler
eftersom majoriteten av enskilda köpsignaler misslyckas i fallande marknad.
"""
import datetime
import logging
import sqlite3
import yfinance as yf
from src.core.data import get_db
from src.core.config import INDEX_TICKERS

logger = logging.getLogger(__name__)

_REGIME_CACHE = {}
_REGIME_TTL = 1800  # 30 minuter


def evaluate_regime_from_indicators(close: float, ma50: float = None, ma200: float = None) -> dict:
    """Klassificerar marknadsregimen baserat på indexets relation till MA200 och MA50."""
    if close is None:
        return {
            "regime": "neutral",
            "is_bull": True,
            "allow_buys": True,
            "label": "Neutral / Okänd marknadsregim",
            "badge": "neutral",
            "description": "Ingen kursdata tillgänglig för index.",
        }

    if ma200 is None:
        return {
            "regime": "bull",
            "is_bull": True,
            "allow_buys": True,
            "label": "Marknadsklimat neutralt/positivt",
            "badge": "up",
            "description": "Saknar 200-dagars medelvärde för index.",
        }

    # Bear Market: Index stänger under MA200
    if close < ma200:
        return {
            "regime": "bear",
            "is_bull": False,
            "allow_buys": False,
            "label": "Bear Market (Försvarsläge – Undvik nya köp)",
            "badge": "down-strong",
            "description": f"Index handlas under 200-dagars medelvärde ({close:.1f} < {ma200:.1f}). Hög marknadsrisk.",
        }

    # Korrektion i upptrend: Över MA200 men under MA50
    if ma50 is not None and close < ma50:
        return {
            "regime": "correction",
            "is_bull": True,
            "allow_buys": True,
            "label": "Korrektion i upptrend (Selektiva dipp-köp tillåtna)",
            "badge": "warn",
            "description": f"Index rekylerar under MA50 ({close:.1f} < {ma50:.1f}) men håller långsiktigt stöd MA200 ({ma200:.1f}).",
        }

    # Bull Market: Över både MA200 och MA50
    ma50_txt = f"{ma50:.1f}" if ma50 else "–"
    return {
        "regime": "bull",
        "is_bull": True,
        "allow_buys": True,
        "label": "Bull Market (Gynnsamt marknadsklimat för köp)",
        "badge": "up-strong",
        "description": f"Index handlas i sund upptrend över MA200 ({ma200:.1f}) och MA50 ({ma50_txt}).",
    }


def get_market_regime(market: str = "all") -> dict:
    """Hämtar aktuell marknadsregim för angiven marknad (omx, nasdaq eller all)."""
    global _REGIME_CACHE
    market_key = (market or "all").lower()

    # Bestäm indexsymbol
    if market_key in ("nasdaq", "us", "usa"):
        index_sym = "^NDX"
        index_name = "Nasdaq 100"
    else:
        index_sym = "^OMX"
        index_name = "OMXS30"

    now_ts = datetime.datetime.now().timestamp()
    cached = _REGIME_CACHE.get(index_sym)
    if cached and (now_ts - cached["ts"] < _REGIME_TTL):
        return cached["data"]

    db = get_db()
    db.row_factory = sqlite3.Row
    row = None
    try:
        row = db.execute(
            "SELECT date, close, ma50, ma200 FROM history "
            "WHERE symbol = ? AND close IS NOT NULL ORDER BY date DESC LIMIT 1",
            (index_sym,),
        ).fetchone()
    except Exception as e:
        logger.debug(f"Kunde inte läsa index från databas: {e}")
    finally:
        db.close()

    close, ma50, ma200, date_str = None, None, None, ""
    if row:
        close = float(row["close"])
        ma50 = float(row["ma50"]) if row["ma50"] is not None else None
        ma200 = float(row["ma200"]) if row["ma200"] is not None else None
        date_str = str(row["date"])
    else:
        # Fallback till live-hämtning via yfinance
        try:
            t = yf.Ticker(index_sym)
            hist = t.history(period="1y")
            if not hist.empty:
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.get_level_values(0)
                if "Close" in hist.columns:
                    hist = hist.dropna(subset=["Close"])
            if not hist.empty and len(hist) >= 50:
                closes = hist["Close"]
                close = float(closes.iloc[-1])
                ma50 = float(closes.rolling(50).mean().iloc[-1])
                ma200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None
                date_str = hist.index[-1].strftime("%Y-%m-%d")
        except Exception as e:
            logger.debug(f"Kunde inte hämta {index_sym} från yfinance: {e}")

    regime_eval = evaluate_regime_from_indicators(close, ma50, ma200)

    result = {
        "market": market_key,
        "index_symbol": index_sym,
        "index_name": index_name,
        "close": round(close, 2) if close is not None else None,
        "ma50": round(ma50, 2) if ma50 is not None else None,
        "ma200": round(ma200, 2) if ma200 is not None else None,
        "date": date_str,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        **regime_eval,
    }

    _REGIME_CACHE[index_sym] = {"data": result, "ts": now_ts}
    return result
