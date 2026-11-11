"""Relativ Styrka (Mansfield Relative Strength - MRS).

Mäter hur en aktie utvecklas i förhållande till sitt jämförelseindex
(OMXS30 för svenska aktier, Nasdaq 100 för amerikanska).

Ett positivt MRS-värde (> 0) visar att aktien är en 'outperformer'
(ledaraktie) som stiger snabbare eller faller mindre än marknaden.
Ett negativt MRS-värde (< 0) visar en underpresterande aktie.
"""
import logging
import pandas as pd
import numpy as np
from src.core.data import get_db
from src.core.config import NASDAQ_100

logger = logging.getLogger(__name__)

_RS_CACHE = {}
_RS_TTL = 1800  # 30 minuter

_MOM_CACHE = {"ts": 0.0, "vals": None, "by_sym": {}}
_MOM_TTL = 3600
MOM_LOOKBACK = 252   # ~12 månader
MOM_SKIP = 21        # hoppar över senaste månaden (kortsiktig reversion)


def momentum_12_1(closes) -> float:
    """12–1-månaders momentum i procent: kursen för en månad sedan mot kursen för tolv månader sedan.
    None om historiken är för kort."""
    c = pd.Series(closes).dropna()
    if len(c) < MOM_LOOKBACK + 1:
        return None
    base = float(c.iloc[-(MOM_LOOKBACK + 1)])
    if base <= 0:
        return None
    return (float(c.iloc[-(MOM_SKIP + 1)]) / base - 1.0) * 100.0


def get_universe_momentum():
    """Sorterad numpy-vektor med 12–1-momentum för alla bolag i universumet (cachad)."""
    from src.core.config import OMXS_50
    now_ts = pd.Timestamp.now().timestamp()
    if _MOM_CACHE["vals"] is not None and now_ts - _MOM_CACHE["ts"] < _MOM_TTL:
        return _MOM_CACHE["vals"]
    db = get_db()
    vals = []
    by_sym = {}
    try:
        for sym in list({**OMXS_50, **NASDAQ_100}):
            rows = db.execute(
                "SELECT close FROM history WHERE symbol = ? AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT ?", (sym, MOM_LOOKBACK + 5)).fetchall()
            closes = [r[0] for r in reversed(rows)]
            m = momentum_12_1(closes)
            if m is not None:
                vals.append(m)
                by_sym[sym] = {"mom": m, "close": float(closes[-1])}
    finally:
        db.close()
    arr = np.sort(np.array(vals, dtype=float))
    _MOM_CACHE.update({"ts": now_ts, "vals": arr, "by_sym": by_sym})
    return arr


def get_top_momentum(market="all", limit=5, min_pct=80.0):
    """Bolag i universumet med högst 12–1-momentum (percentil >= min_pct), starkast först."""
    from src.core.config import OMXS_50
    arr = get_universe_momentum()
    out = []
    for sym, v in _MOM_CACHE["by_sym"].items():
        is_us = sym in NASDAQ_100
        if market in ("omx", "omxs") and is_us:
            continue
        if market == "nasdaq" and not is_us:
            continue
        pct = momentum_percentile(v["mom"])
        if pct < min_pct:
            continue
        out.append({"symbol": sym, "name": (NASDAQ_100 if is_us else OMXS_50)[sym],
                    "market": "NASDAQ" if is_us else "OMX", "currency": "$" if is_us else "kr",
                    "close": v["close"], "mom_12_1": round(v["mom"], 1), "mom_pct": pct})
    out.sort(key=lambda x: x["mom_12_1"], reverse=True)
    return out[:limit]


def momentum_percentile(mom_value) -> float:
    """Var ett momentumvärde ligger i universumet, 0–100 (50 om jämförelsedata saknas)."""
    if mom_value is None:
        return 50.0
    arr = get_universe_momentum()
    if len(arr) < 20:
        return 50.0
    return round(float(np.searchsorted(arr, mom_value, side="right")) / len(arr) * 100.0, 1)


def calculate_mansfield_rs(
    stock_prices: pd.Series, index_prices: pd.Series, period: int = 50
) -> pd.Series:
    """Beräknar Mansfield Relative Strength (MRS) som en tidsserie."""
    # Synka datumindex
    aligned = pd.concat([stock_prices, index_prices], axis=1, join="inner").dropna()
    if aligned.empty or len(aligned) < period:
        return pd.Series(dtype=float)

    s_price = aligned.iloc[:, 0].astype(float)
    i_price = aligned.iloc[:, 1].astype(float)

    # Undvik division med 0
    i_price = i_price.replace(0, np.nan)
    rs_ratio = s_price / i_price

    sma_rs = rs_ratio.rolling(period).mean()
    mrs = ((rs_ratio / sma_rs) - 1.0) * 100.0

    return mrs


def get_stock_relative_strength(symbol: str, market: str = "all") -> dict:
    """Hämtar och beräknar Mansfield Relative Strength för en aktie mot dess marknadsindex."""
    global _RS_CACHE
    sym = symbol.strip().upper()

    now_ts = pd.Timestamp.now().timestamp()
    cached = _RS_CACHE.get(sym)
    if cached and (now_ts - cached["ts"] < _RS_TTL):
        return cached["data"]

    # Välj index
    is_us = (sym in NASDAQ_100) or (market and market.lower() in ("nasdaq", "us", "usa"))
    index_sym = "^NDX" if is_us else "^OMX"

    db = get_db()
    try:
        df_stock = pd.read_sql_query(
            "SELECT date, close FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date",
            db, params=[sym]
        )
        df_index = pd.read_sql_query(
            "SELECT date, close FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date",
            db, params=[index_sym]
        )
    finally:
        db.close()

    if df_stock.empty or df_index.empty:
        res = {
            "symbol": sym,
            "index_symbol": index_sym,
            "mrs": 0.0,
            "is_outperformer": False,
            "rs_label": "Neutral / Okänd relativ styrka",
            "mom_12_1": None,
            "mom_pct": 50.0,
            "badge": "neutral",
        }
        return res

    s_series = df_stock.set_index("date")["close"]
    i_series = df_index.set_index("date")["close"]

    mom_val = momentum_12_1(s_series)
    mom_pct = momentum_percentile(mom_val)
    mrs_series = calculate_mansfield_rs(s_series, i_series, period=50)

    if mrs_series.empty or pd.isna(mrs_series.iloc[-1]):
        mrs_val = 0.0
    else:
        mrs_val = round(float(mrs_series.iloc[-1]), 1)

    is_outperformer = mrs_val > 0.0

    if mrs_val >= 3.0:
        rs_label = f"Stark Ledaraktie (+{mrs_val}% mot index)"
        badge = "up-strong"
    elif mrs_val > 0.0:
        rs_label = f"Ledaraktie (+{mrs_val}% mot index)"
        badge = "up"
    elif mrs_val >= -3.0:
        rs_label = f"Följer index ({mrs_val}%)"
        badge = "neutral"
    else:
        rs_label = f"Underperformer ({mrs_val}% mot index)"
        badge = "down"

    res = {
        "symbol": sym,
        "index_symbol": index_sym,
        "mrs": mrs_val,
        "is_outperformer": is_outperformer,
        "rs_label": rs_label,
        "mom_12_1": round(mom_val, 1) if mom_val is not None else None,
        "mom_pct": mom_pct,
        "badge": badge,
    }

    _RS_CACHE[sym] = {"data": res, "ts": now_ts}
    return res
