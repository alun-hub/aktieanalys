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
    """Kör ett enskilt backtest för given OMX-konfiguration med korrekt portföljberäkning."""
    entry_sql = _build_entry_sql(all_symbols, bd, vm, ma_col)
    trades, cash, holdings, cap = [], 100_000.0, [], 100_000.0

    for date in dates[start_idx:]:
        still = []

        for h in holdings:
            row = conn.execute(
                "SELECT low, close, rsi, ma50, ma200 FROM history WHERE symbol = ? AND date = ?",
                (h["sym"], date)
            ).fetchone()
            if not row or row["close"] is None:
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
                still.append(h)

        holdings = still
        port_v = cash + sum(h["qty"] * h["last_p"] for h in holdings)

        if len(holdings) >= 5 or cash < port_v * 0.10:
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
            p = min(cash, port_v * POSITION_SIZE)
            holdings.append({
                "sym": best["symbol"], "entry": best["close"], "sl": sl,
                "qty": p / best["close"], "days": 0, "last_p": best["close"]
            })
            cash -= p

    final_val = cash + sum(h["qty"] * h["last_p"] for h in holdings)
    wins = len([t for t in trades if t > 0])
    total_return = round((final_val / cap - 1) * 100, 2)
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


def run_crypto_backtest(years=3):
    """Kör deterministiskt backtest på ledande kryptopar mot Bitcoin som benchmark."""
    from src.core.crypto import get_crypto_df, CRYPTO_LIST
    symbols = ["BTC-USD", "ETH-USD", "SOL-USD"]
    dfs = {}
    p_str = f"{max(1, min(5, years))}y"
    for s in symbols:
        df = get_crypto_df(s, period=p_str)
        if df is not None and not df.empty and len(df) > 30:
            dfs[s] = df

    if not dfs or "BTC-USD" not in dfs:
        return {"error": "Kunde inte hämta tillräcklig historisk data för kryptobacktest."}

    # Hitta gemensamma datum
    all_dates = sorted(list(set.intersection(*[set(df.index.strftime('%Y-%m-%d')) for df in dfs.values()])))
    if len(all_dates) < 30:
        return {"error": "För få gemensamma handelsdagar för vald period."}

    initial_cap = 100_000.0
    cash = initial_cap
    holdings = []
    trades = []
    equity_curve = [initial_cap]

    for d in all_dates:
        still = []
        for h in holdings:
            df = dfs.get(h["sym"])
            try:
                row = df.loc[d]
                c = float(row["Close"])
                low = float(row["Low"])
                rsi = float(row["RSI"]) if not pd.isna(row["RSI"]) else 50
                h["last_p"] = c
            except KeyError:
                still.append(h)
                continue

            exit_p, reason = None, ""
            if h["days"] > 0:
                if low <= h["sl"]:
                    exit_p = h["sl"]
                    reason = "Stop loss utlöst"
                elif rsi > 78:
                    exit_p = c
                    reason = "Vinsthemtagning (RSI > 78)"
                elif h["days"] >= 25:
                    exit_p = c
                    reason = "Timeout (25 dagar)"

            if exit_p is not None:
                proceeds = h["qty"] * exit_p
                cash += proceeds
                ret = (exit_p / h["entry"] - 1) * 100
                trades.append({
                    "symbol": h["sym"],
                    "name": CRYPTO_LIST.get(h["sym"], h["sym"]),
                    "entry_date": h["entry_date"],
                    "entry_price": round(h["entry"], 2),
                    "exit_date": d,
                    "exit_price": round(exit_p, 2),
                    "return_pct": round(ret, 2),
                    "profit": round(proceeds - (h["qty"] * h["entry"]), 2),
                    "days_held": h["days"],
                    "exit_reason": reason
                })
            else:
                h["days"] += 1
                still.append(h)

        holdings = still
        port_v = cash + sum(h["qty"] * h["last_p"] for h in holdings)
        equity_curve.append(port_v)

        # Marknadsregim: Bitcoin över MA50
        try:
            btc_row = dfs["BTC-USD"].loc[d]
            if pd.isna(btc_row.get("MA50")) or float(btc_row["Close"]) < float(btc_row["MA50"]):
                continue
        except KeyError:
            continue

        if len(holdings) < 3 and cash >= port_v * 0.25:
            for s in symbols:
                if any(h["sym"] == s for h in holdings):
                    continue
                s_df = dfs[s]
                try:
                    s_row = s_df.loc[d]
                    c_p = float(s_row["Close"])
                    rsi_v = float(s_row["RSI"]) if not pd.isna(s_row["RSI"]) else 50
                    ma50_v = float(s_row["MA50"]) if not pd.isna(s_row["MA50"]) else 0
                    atr_v = float(s_row["ATR"]) if not pd.isna(s_row["ATR"]) else c_p * 0.05
                    if c_p > ma50_v and rsi_v < 44:
                        p_size = min(cash, port_v * 0.30)
                        sl = round(c_p - 2.5 * atr_v, 2)
                        holdings.append({
                            "sym": s,
                            "name": CRYPTO_LIST.get(s, s),
                            "entry_date": d,
                            "entry": c_p,
                            "sl": sl,
                            "qty": p_size / c_p,
                            "days": 0,
                            "last_p": c_p
                        })
                        cash -= p_size
                        break
                except KeyError:
                    continue

    # Avsluta öppna positioner
    for h in holdings:
        proceeds = h["qty"] * h["last_p"]
        ret = (h["last_p"] / h["entry"] - 1) * 100
        trades.append({
            "symbol": h["sym"],
            "name": CRYPTO_LIST.get(h["sym"], h["sym"]),
            "entry_date": h["entry_date"],
            "entry_price": round(h["entry"], 2),
            "exit_date": all_dates[-1],
            "exit_price": round(h["last_p"], 2),
            "return_pct": round(ret, 2),
            "profit": round(proceeds - (h["qty"] * h["entry"]), 2),
            "days_held": h["days"],
            "exit_reason": "Öppen position vid slut"
        })

    final_cap = cash + sum(h["qty"] * h["last_p"] for h in holdings)
    total_return = round((final_cap / initial_cap - 1) * 100, 2)

    btc_first = float(dfs["BTC-USD"].loc[all_dates[0]]["Close"])
    btc_last = float(dfs["BTC-USD"].loc[all_dates[-1]]["Close"])
    btc_return = round((btc_last / btc_first - 1) * 100, 2)
    alpha = round(total_return - btc_return, 2)

    win_count = len([t for t in trades if t["return_pct"] > 0])
    win_rate = round(win_count / len(trades) * 100, 1) if trades else 0

    gross_profit = sum(t["profit"] for t in trades if t["profit"] > 0)
    gross_loss = abs(sum(t["profit"] for t in trades if t["profit"] < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)

    peak = initial_cap
    max_dd = 0.0
    for v in equity_curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd: max_dd = dd

    # Generera visualisering av kurva (ca 35 punkter)
    n_pts = 35
    step = max(1, len(all_dates) // n_pts)
    chart_points = []
    for i in range(0, len(all_dates), step):
        d_cur = all_dates[i]
        strat_v = equity_curve[min(i, len(equity_curve) - 1)]
        b_val = float(dfs["BTC-USD"].loc[d_cur]["Close"])
        idx_v = initial_cap * (b_val / btc_first)
        chart_points.append({
            "date": d_cur,
            "strategy": round(strat_v, 0),
            "index": round(idx_v, 0)
        })
    if chart_points and chart_points[-1]["date"] != all_dates[-1]:
        chart_points.append({
            "date": all_dates[-1],
            "strategy": round(final_cap, 0),
            "index": round(initial_cap * (1 + btc_return / 100.0), 0)
        })

    return {
        "trades": len(trades),
        "return": total_return,
        "win_rate": win_rate,
        "index_name": "Bitcoin",
        "index_return": btc_return,
        "alpha": alpha,
        "max_drawdown": round(max_dd, 2),
        "profit_factor": profit_factor,
        "equity_chart": chart_points,
        "trade_list": trades[::-1]
    }


def run_backtest_local(market="omxs", years=5):
    """Kör deterministisk backtest med full affärslogg, benchmark och max drawdown."""
    if market == "crypto":
        return run_crypto_backtest(years=years)

    conn = get_db()
    is_omx = (market == "omxs")
    idx_ticker = "^OMX" if is_omx else "^NDX"
    symbols_dict = OMXS_50 if is_omx else NASDAQ_100
    all_symbols = list(symbols_dict.keys())
    max_days = OMX_MAX_DAYS if is_omx else NASDAQ_MAX_DAYS
    atr_mult = OMX_ATR_MULT if is_omx else NASDAQ_ATR_MULT

    dates_df = pd.read_sql_query(
        "SELECT DISTINCT date FROM history WHERE symbol = ? ORDER BY date",
        conn, params=(idx_ticker,)
    )
    if dates_df.empty:
        return {"error": f"Ingen historik för index {idx_ticker}."}

    dates = dates_df['date'].tolist()
    start_idx = max(0, len(dates) - (years * 252))
    initial_cap = 100_000.0
    cash = initial_cap
    holdings = []
    trades = []
    equity_curve = [initial_cap]

    for date in dates[start_idx:]:
        still_holding = []

        for h in holdings:
            row = conn.execute(
                "SELECT low, close, rsi, ma50, ma200 FROM history WHERE symbol = ? AND date = ?",
                (h["sym"], date)
            ).fetchone()
            if not row or row["close"] is None:
                still_holding.append(h)
                continue

            h["last_p"] = row["close"]
            exit_p, reason = None, ""
            if h["days"] > 0:
                exit_p, reason = check_exit(
                    row["close"], row["low"], row["rsi"],
                    row["ma50"], row["ma200"],
                    h["sl"], is_omx, max_days, h["days"]
                )

            if exit_p is not None:
                proceeds = h["qty"] * exit_p
                cash += proceeds
                ret = (exit_p / h["entry"] - 1) * 100
                trades.append({
                    "symbol": h["sym"],
                    "name": h.get("name", h["sym"]),
                    "entry_date": h["entry_date"],
                    "entry_price": round(h["entry"], 2),
                    "exit_date": date,
                    "exit_price": round(exit_p, 2),
                    "return_pct": round(ret, 2),
                    "profit": round(proceeds - (h["qty"] * h["entry"]), 2),
                    "days_held": h["days"],
                    "exit_reason": reason or "Avslut"
                })
            else:
                h["days"] += 1
                still_holding.append(h)

        holdings = still_holding
        port_v = cash + sum(h["qty"] * h["last_p"] for h in holdings)
        equity_curve.append(port_v)

        if len(holdings) >= 5 or cash < port_v * 0.10:
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
            p_size = min(cash, port_v * POSITION_SIZE)
            sym = best["symbol"]
            holdings.append({
                "sym": sym,
                "name": symbols_dict.get(sym, sym),
                "entry_date": date,
                "entry": best["close"],
                "sl": sl,
                "qty": p_size / best["close"],
                "days": 0,
                "last_p": best["close"]
            })
            cash -= p_size

    # Avsluta öppna positioner
    for h in holdings:
        proceeds = h["qty"] * h["last_p"]
        ret = (h["last_p"] / h["entry"] - 1) * 100
        trades.append({
            "symbol": h["sym"],
            "name": h.get("name", h["sym"]),
            "entry_date": h["entry_date"],
            "entry_price": round(h["entry"], 2),
            "exit_date": dates[-1],
            "exit_price": round(h["last_p"], 2),
            "return_pct": round(ret, 2),
            "profit": round(proceeds - (h["qty"] * h["entry"]), 2),
            "days_held": h["days"],
            "exit_reason": "Öppen position vid slut"
        })

    final_cap = cash + sum(h["qty"] * h["last_p"] for h in holdings)
    total_return = round((final_cap / initial_cap - 1) * 100, 2)

    # Benchmark avkastning
    idx_df = pd.read_sql_query(
        "SELECT close FROM history WHERE symbol = ? AND date IN (?, ?) ORDER BY date",
        conn, params=(idx_ticker, dates[start_idx], dates[-1])
    )
    index_return = 0.0
    if len(idx_df) >= 2 and idx_df.iloc[0]["close"]:
        index_return = round((float(idx_df.iloc[-1]["close"]) / float(idx_df.iloc[0]["close"]) - 1) * 100, 2)
    alpha = round(total_return - index_return, 2)

    win_count = len([t for t in trades if t["return_pct"] > 0])
    win_rate = round(win_count / len(trades) * 100, 1) if trades else 0

    gross_profit = sum(t["profit"] for t in trades if t["profit"] > 0)
    gross_loss = abs(sum(t["profit"] for t in trades if t["profit"] < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)

    peak = initial_cap
    max_dd = 0.0
    for v in equity_curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd: max_dd = dd

    # Generera visualisering av kurva (ca 35 punkter)
    n_pts = 35
    step = max(1, len(dates[start_idx:]) // n_pts)
    chart_points = []
    idx_first_row = conn.execute("SELECT close FROM history WHERE symbol = ? AND date = ?", (idx_ticker, dates[start_idx])).fetchone()
    idx_first_close = float(idx_first_row["close"]) if (idx_first_row and idx_first_row["close"]) else None

    for i in range(0, len(dates[start_idx:]), step):
        d_cur = dates[start_idx + i]
        strat_v = equity_curve[min(i, len(equity_curve) - 1)]
        idx_v = initial_cap
        if idx_first_close:
            r = conn.execute("SELECT close FROM history WHERE symbol = ? AND date = ?", (idx_ticker, d_cur)).fetchone()
            if r and r["close"]:
                idx_v = initial_cap * (float(r["close"]) / idx_first_close)
        chart_points.append({
            "date": d_cur,
            "strategy": round(strat_v, 0),
            "index": round(idx_v, 0)
        })
    if chart_points and chart_points[-1]["date"] != dates[-1]:
        chart_points.append({
            "date": dates[-1],
            "strategy": round(final_cap, 0),
            "index": round(initial_cap * (1 + index_return / 100.0), 0)
        })

    return {
        "trades": len(trades),
        "return": total_return,
        "win_rate": win_rate,
        "index_name": "OMXS30" if is_omx else "Nasdaq 100",
        "index_return": index_return,
        "alpha": alpha,
        "max_drawdown": round(max_dd, 2),
        "profit_factor": profit_factor,
        "equity_chart": chart_points,
        "trade_list": trades[::-1][:100]
    }
