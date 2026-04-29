import pandas as pd
from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100
from src.core.signals import (
    check_exit, OMX_ATR_MULT, NASDAQ_ATR_MULT, MA_ENTRY_MARGIN,
    VOLUME_SURGE, BREAKOUT_DAYS, RSI_OVERSOLD, OMX_MAX_DAYS
)
NASDAQ_MAX_DAYS = 20
POSITION_SIZE   = 0.20

# 10 professionellt utvalda konfigurationer att testa mot OMX
# (namn, breakout_dagar, vol_mult, atr_mult, max_dagar, rsi_exit, ma_kolumn)
# breakout_dagar=0 → RSI mean-reversion entry istället för breakout
OMXS_CONFIGS = [
    ("Nuläge (baseline)",    40,  1.6, 4.5, 27, 78, "ma50"),
    ("Kvartalsutbrott",      60,  1.5, 4.0, 20, 75, "ma200"),
    ("Halvårsutbrott",       90,  1.5, 4.5, 22, 75, "ma200"),
    ("52-veckors breakout", 252,  2.0, 4.5, 25, 75, "ma200"),
    ("Hög volymfilter",      20,  2.0, 4.0, 20, 73, "ma50"),
    ("Bred stopp",           20,  1.5, 5.0, 20, 75, "ma200"),
    ("40-dagars utbrott",    40,  1.5, 4.0, 20, 73, "ma200"),
    ("Pro momentum",         60,  1.8, 4.5, 25, 75, "ma200"),
    ("RSI mean reversion",    0,  1.0, 3.5, 15, 62, "ma200"),
    ("RSI + bred stopp",      0,  1.0, 4.5, 20, 65, "ma200"),
]


def _build_entry_sql(all_symbols, bd, vm, ma_col):
    """Bygger SQL för köpentry beroende på strategi-typ."""
    ph = ','.join(['?'] * len(all_symbols))
    if bd > 0:
        return f"""
            SELECT symbol, close, atr FROM history
            WHERE date = ? AND symbol IN ({ph})
              AND {ma_col} IS NOT NULL
              AND close > ({ma_col} * {MA_ENTRY_MARGIN})
              AND close > (SELECT MAX(high) FROM history h2
                           WHERE h2.symbol = history.symbol
                             AND h2.date < history.date
                           ORDER BY h2.date DESC LIMIT {bd})
              AND volume > (SELECT AVG(volume) FROM history h3
                            WHERE h3.symbol = history.symbol
                              AND h3.date < history.date
                            ORDER BY h3.date DESC LIMIT 20) * {vm}
            ORDER BY volume DESC LIMIT 1
        """
    # RSI mean reversion: köp vid RSI < 35 som börjar vända uppåt
    return f"""
        SELECT symbol, close, atr FROM history h1
        WHERE date = ? AND symbol IN ({ph})
          AND ma200 IS NOT NULL AND rsi IS NOT NULL
          AND rsi < 35
          AND rsi > (SELECT rsi FROM history h2
                     WHERE h2.symbol = h1.symbol AND h2.date < h1.date
                     ORDER BY h2.date DESC LIMIT 1)
          AND close > (ma200 * {MA_ENTRY_MARGIN})
        ORDER BY rsi ASC LIMIT 1
    """


def _run_omx_config(conn, all_symbols, dates, start_idx, bd, vm, am, md, rsi_out, ma_col):
    """Kör ett enskilt backtest för given OMX-konfiguration."""
    entry_sql = _build_entry_sql(all_symbols, bd, vm, ma_col)
    trades, cash, holdings, cap = [], 100_000, [], 100_000

    for date in dates[start_idx:]:
        still, port_v = [], cash

        for h in holdings:
            row = conn.execute(
                "SELECT low, close, rsi, ma50, ma200 FROM history WHERE symbol = ? AND date = ?",
                (h["sym"], date)
            ).fetchone()
            if not row:
                port_v += h["qty"] * h["last_p"]
                still.append(h)
                continue

            h["last_p"] = row["close"]
            exit_p = None

            if h["days"] > 0:
                if row["low"] is not None and row["low"] <= h["sl"]:
                    exit_p = h["sl"]
                elif row["rsi"] is not None and row["rsi"] > rsi_out:
                    exit_p = row["close"]
                elif row["close"] is not None and row["ma50"] is not None \
                        and row["close"] < row["ma50"] * 0.993:
                    exit_p = row["close"]
                elif h["days"] >= md:
                    exit_p = row["close"]

            if exit_p is not None:
                cash += h["qty"] * exit_p
                trades.append(exit_p / h["entry"] - 1)
            else:
                h["days"] += 1
                port_v += h["qty"] * row["close"]
                still.append(h)

        holdings = still
        if len(holdings) >= 5:
            continue

        # Marknadsfilter: index över MA50 (snabbare signal än MA200)
        idx = conn.execute(
            "SELECT close, ma50 FROM history WHERE symbol = '^OMX' AND date = ?", (date,)
        ).fetchone()
        if not (idx and idx["close"] and idx["ma50"] and idx["close"] > idx["ma50"]):
            continue

        best = conn.execute(entry_sql, [date] + all_symbols).fetchone()
        if best and not any(h["sym"] == best["symbol"] for h in holdings):
            sl = best["close"] - am * best["atr"] if best["atr"] else best["close"] * 0.92
            p = port_v * POSITION_SIZE
            holdings.append({
                "sym": best["symbol"], "entry": best["close"], "sl": sl,
                "qty": p / best["close"], "days": 0, "last_p": best["close"]
            })
            cash -= p

    wins = len([t for t in trades if t > 0])
    total_return = round((port_v / cap - 1) * 100, 2)
    win_rate = round(wins / len(trades) * 100, 2) if trades else 0
    # Kombinationsmått: win_rate × sign(return) för smart ranking
    score = win_rate * (1 if total_return >= 0 else -1)
    return {"trades": len(trades), "return": total_return, "win_rate": win_rate, "score": score}


def optimize_omx(years=5):
    """Testar alla konfigurationer mot historisk data och returnerar rankad lista."""
    conn = get_db()
    all_symbols = list(OMXS_50.keys())
    dates_df = pd.read_sql_query(
        "SELECT DISTINCT date FROM history WHERE symbol = '^OMX' ORDER BY date",
        conn
    )
    if dates_df.empty:
        return {"error": "Ingen historik för ^OMX."}

    dates = dates_df["date"].tolist()
    start_idx = max(0, len(dates) - (years * 252))
    results = []

    for cfg in OMXS_CONFIGS:
        name, bd, vm, am, md, rsi_out, ma_col = cfg
        try:
            r = _run_omx_config(conn, all_symbols, dates, start_idx, bd, vm, am, md, rsi_out, ma_col)
            r.update({
                "name": name, "breakout_d": bd, "vol_mult": vm,
                "atr_mult": am, "max_days": md, "rsi_exit": rsi_out
            })
            results.append(r)
        except Exception as e:
            results.append({"name": name, "error": str(e), "score": -999})

    results.sort(key=lambda r: r.get("score", -999), reverse=True)
    return results


def _find_omx_entry(conn, date, all_symbols):
    placeholders = ','.join(['?'] * len(all_symbols))
    return conn.execute(f"""
        SELECT symbol, close, atr FROM history
        WHERE date = ?
          AND symbol IN ({placeholders})
          AND ma50 IS NOT NULL
          AND close > (SELECT MAX(high) FROM history h2
                       WHERE h2.symbol = history.symbol
                         AND h2.date < history.date
                       ORDER BY h2.date DESC LIMIT {BREAKOUT_DAYS})
          AND volume > (SELECT AVG(volume) FROM history h3
                        WHERE h3.symbol = history.symbol
                          AND h3.date < history.date
                        ORDER BY h3.date DESC LIMIT {BREAKOUT_DAYS}) * {VOLUME_SURGE}
          AND close > (ma50 * {MA_ENTRY_MARGIN})
        LIMIT 1
    """, [date] + all_symbols).fetchone()


def _find_nasdaq_entry(conn, date, all_symbols):
    placeholders = ','.join(['?'] * len(all_symbols))
    return conn.execute(f"""
        SELECT symbol, close, atr FROM history h1
        WHERE date = ?
          AND symbol IN ({placeholders})
          AND ma200 IS NOT NULL
          AND rsi IS NOT NULL
          AND rsi < {RSI_OVERSOLD}
          AND rsi > (SELECT rsi FROM history h2
                     WHERE h2.symbol = h1.symbol AND h2.date < h1.date
                     ORDER BY h2.date DESC LIMIT 1)
          AND close > (ma200 * {MA_ENTRY_MARGIN})
          AND ma200 > (SELECT ma200 FROM history h3
                       WHERE h3.symbol = h1.symbol AND h3.date < h1.date
                         AND h3.ma200 IS NOT NULL
                       ORDER BY h3.date DESC LIMIT 1 OFFSET 19)
        ORDER BY rsi ASC LIMIT 1
    """, [date] + all_symbols).fetchone()


def run_backtest_local(market="omxs", years=5):
    conn = get_db()
    is_omx = (market == "omxs")
    idx_ticker = "^OMX" if is_omx else "^NDX"
    all_symbols = list(OMXS_50.keys()) if is_omx else list(NASDAQ_100.keys())
    max_days = OMX_MAX_DAYS if is_omx else NASDAQ_MAX_DAYS
    atr_mult = OMX_ATR_MULT if is_omx else NASDAQ_ATR_MULT

    dates_df = pd.read_sql_query(
        "SELECT DISTINCT date FROM history WHERE symbol = ? ORDER BY date",
        conn, params=(idx_ticker,)
    )
    if dates_df.empty:
        return {"error": "Ingen historik."}

    dates = dates_df['date'].tolist()
    start_idx = max(0, len(dates) - (years * 252))
    trades, cash, holdings, initial_cap = [], 100000, [], 100000

    for date in dates[start_idx:]:
        still_holding = []
        port_v = cash

        for h in holdings:
            row = conn.execute(
                "SELECT low, close, rsi, ma50, ma200 FROM history WHERE symbol = ? AND date = ?",
                (h["sym"], date)
            ).fetchone()
            if not row:
                port_v += h["qty"] * h["last_p"]
                still_holding.append(h)
                continue

            h["last_p"] = row["close"]
            if h["days"] > 0:
                exit_p, _ = check_exit(
                    row["close"], row["low"], row["rsi"],
                    row["ma50"], row["ma200"],
                    h["sl"], is_omx, max_days, h["days"]
                )
            else:
                exit_p = None

            if exit_p is not None:
                cash += h["qty"] * exit_p
                trades.append(exit_p / h["entry"] - 1)
            else:
                h["days"] += 1
                port_v += h["qty"] * row["close"]
                still_holding.append(h)

        holdings = still_holding
        if len(holdings) >= 5:
            continue

        idx_row = conn.execute(
            "SELECT close, ma200 FROM history WHERE symbol = ? AND date = ?",
            (idx_ticker, date)
        ).fetchone()
        if not (idx_row and idx_row["close"] and idx_row["ma200"]
                and idx_row["close"] > idx_row["ma200"]):
            continue

        best = _find_omx_entry(conn, date, all_symbols) if is_omx else _find_nasdaq_entry(conn, date, all_symbols)
        if best and not any(h["sym"] == best["symbol"] for h in holdings):
            sl = best["close"] - atr_mult * best["atr"] if best["atr"] else best["close"] * 0.95
            p_size = port_v * POSITION_SIZE
            holdings.append({
                "sym": best["symbol"], "entry": best["close"], "sl": sl,
                "qty": p_size / best["close"], "days": 0, "last_p": best["close"]
            })
            cash -= p_size

    win_count = len([t for t in trades if t > 0])
    win_rate = round(win_count / len(trades) * 100, 2) if trades else 0
    return {
        "trades": len(trades),
        "return": round((port_v / initial_cap - 1) * 100, 2),
        "win_rate": win_rate
    }
