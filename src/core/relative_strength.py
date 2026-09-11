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
            "badge": "neutral",
        }
        return res

    s_series = df_stock.set_index("date")["close"]
    i_series = df_index.set_index("date")["close"]

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
        "badge": badge,
    }

    _RS_CACHE[sym] = {"data": res, "ts": now_ts}
    return res
