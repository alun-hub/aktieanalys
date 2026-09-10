"""Ärligt backtest.

Skillnader mot den gamla motorn (som systematiskt överskattade strategin):

* Köp fylls på NÄSTA handelsdags öppningskurs efter signalen – aldrig på samma
  slutkurs som gav signalen.
* Stop loss fylls på ``min(dagens öppning, stoppnivå)`` så gap-nedgångar kostar.
* Övriga exits (RSI, trendbrott, timeout) fylls på nästa dags öppning.
* Courtage, spread och valutaväxling dras av på varje affär (src/core/costs.py).
* Historiken hämtas med ``period="max"`` – begärt antal år valideras mot vad som
  faktiskt finns.
* Jämförelse: "köp allt och behåll" på exakt samma utdelningsjusterade data, samt
  indexets prisutveckling (utan utdelning – tydligt märkt).
* Nyckeltal: CAGR, årlig volatilitet, max drawdown, CAGR/|MaxDD|, andel tid i
  marknaden, affärer/år, snittinnehav. Träffprocent räknas bara på STÄNGDA affärer.
* Optimeraren kör walk-forward: parametrarna bedöms på data de inte tränats på.
"""
import numpy as np
import pandas as pd

from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100
from src.core.costs import transaction_cost

TRADING_DAYS = 252
POSITION_SIZE = 0.20
MAX_HOLDINGS = 5
MIN_CASH_FRACTION = 0.10
INITIAL_CAPITAL = 100_000.0
ENTRY_MARGIN = 1.005
TREND_BREAK_MARGIN = 0.993

# marknad -> standardparametrar
DEFAULT_PARAMS = {
    "omxs": dict(entry="breakout", breakout_days=40, vol_mult=1.6, atr_mult=4.5,
                 max_days=27, rsi_exit=78, trend_ma="ma50"),
    "nasdaq": dict(entry="pullback", rsi_entry=45, atr_mult=3.5,
                   max_days=20, rsi_exit=78, trend_ma="ma200"),
    "crypto": dict(entry="pullback", rsi_entry=44, atr_mult=2.5,
                   max_days=25, rsi_exit=78, trend_ma="ma50"),
}

# walk-forward-konfigurationer för OMX-optimeraren
OMXS_CONFIGS = [
    ("Nuläge (baseline)",   dict(breakout_days=40, vol_mult=1.6, atr_mult=4.5, max_days=27, rsi_exit=78, trend_ma="ma50")),
    ("Kvartalsutbrott",     dict(breakout_days=60, vol_mult=1.5, atr_mult=4.0, max_days=20, rsi_exit=75, trend_ma="ma200")),
    ("Halvårsutbrott",      dict(breakout_days=90, vol_mult=1.5, atr_mult=4.5, max_days=22, rsi_exit=75, trend_ma="ma200")),
    ("52-veckors breakout", dict(breakout_days=252, vol_mult=2.0, atr_mult=4.5, max_days=25, rsi_exit=75, trend_ma="ma200")),
    ("Hög volymfilter",     dict(breakout_days=20, vol_mult=2.0, atr_mult=4.0, max_days=20, rsi_exit=73, trend_ma="ma50")),
    ("Bred stopp",          dict(breakout_days=20, vol_mult=1.5, atr_mult=5.0, max_days=20, rsi_exit=75, trend_ma="ma200")),
    ("40-dagars / GM200",   dict(breakout_days=40, vol_mult=1.5, atr_mult=4.0, max_days=20, rsi_exit=73, trend_ma="ma200")),
    ("Pro momentum",        dict(breakout_days=60, vol_mult=1.8, atr_mult=4.5, max_days=25, rsi_exit=75, trend_ma="ma200")),
    ("Snäv timeout",        dict(breakout_days=40, vol_mult=1.6, atr_mult=4.5, max_days=12, rsi_exit=70, trend_ma="ma50")),
    ("Trög timeout",        dict(breakout_days=40, vol_mult=1.6, atr_mult=4.5, max_days=45, rsi_exit=82, trend_ma="ma200")),
]

# ─────────────────────────────────────────────────────────────────────────────
# Datainläsning
# ─────────────────────────────────────────────────────────────────────────────

def _load_history(conn, symbols):
    ph = ",".join("?" * len(symbols))
    df = pd.read_sql_query(
        f"SELECT symbol,date,open,high,low,close,volume,ma50,ma200,rsi,atr "
        f"FROM history WHERE symbol IN ({ph}) ORDER BY date",
        conn, params=list(symbols))
    out = {}
    for sym, g in df.groupby("symbol", sort=False):
        out[sym] = g.drop(columns="symbol").set_index("date")
    return out


def _prep_signals(g, p):
    g = g.copy()
    if p["entry"] == "breakout":
        n = int(p["breakout_days"])
        prior_high = g["high"].rolling(n).max().shift(1)
        prior_vol = g["volume"].rolling(20).mean().shift(1)
        g["entry_sig"] = (
            g["ma50"].notna() & prior_high.notna() & prior_vol.notna()
            & (g["close"] > prior_high)
            & (g["volume"] > prior_vol * p["vol_mult"])
            & (g["close"] > g["ma50"] * ENTRY_MARGIN)
        )
        g["entry_rank"] = g["volume"] / prior_vol            # högre = starkare
    else:  # pullback / mean reversion i uppåttrend
        g["entry_sig"] = (
            g["ma200"].notna()
            & (g["rsi"] < p["rsi_entry"])
            & (g["rsi"] > g["rsi"].shift(1))
            & (g["close"] > g["ma200"] * ENTRY_MARGIN)
            & (g["ma200"] > g["ma200"].shift(20))
        )
        g["entry_rank"] = -g["rsi"]                          # lägre RSI = bättre
    return g


# ─────────────────────────────────────────────────────────────────────────────
# Kärnmotor
# ─────────────────────────────────────────────────────────────────────────────

def _run_engine(hist, index_close, dates, params, market):
    """hist: {sym: DataFrame med entry_sig/entry_rank}, index_close: Series (för regim).

    Returnerar (equity_curve, trades) där equity_curve = list[(date, value, n_holdings)].
    """
    trend_ma = params["trend_ma"]
    atr_mult = params["atr_mult"]
    max_days = int(params["max_days"])
    rsi_exit = params["rsi_exit"]

    index_ma200 = index_close.rolling(200).mean()

    cash = INITIAL_CAPITAL
    holdings = {}          # sym -> dict(qty, entry_px, entry_date, stop, days, last_price)
    pending_entry = []     # symboler att köpa på nästa öppning
    pending_exit = {}      # sym -> anledning, sälj på nästa öppning
    trades = []
    curve = []

    def row(sym, date):
        g = hist.get(sym)
        if g is None or date not in g.index:
            return None
        return g.loc[date]

    def close_position(sym, fill_px, date, reason):
        nonlocal cash
        h = holdings.pop(sym)
        gross = h["qty"] * fill_px
        exit_cost = transaction_cost(gross, market)
        cash += gross - exit_cost
        cost_basis = h["qty"] * h["entry_px"] + h["entry_cost"]
        net_proceeds = gross - exit_cost
        trades.append({
            "symbol": sym,
            "entry_date": h["entry_date"],
            "exit_date": date,
            "entry_price": round(h["entry_px"], 2),
            "exit_price": round(fill_px, 2),
            "days_held": h["days"],
            "return_pct": round((net_proceeds / cost_basis - 1) * 100, 2),
            "profit": round(net_proceeds - cost_basis, 2),
            "exit_reason": reason,
            "open": False,
        })

    for date in dates:
        # 1. fyll väntande säljordrar på dagens öppning
        for sym in list(pending_exit):
            r = row(sym, date)
            if r is None:
                continue
            close_position(sym, float(r["open"]), date, pending_exit.pop(sym))

        # 2. fyll väntande köpordrar på dagens öppning
        for sym in pending_entry:
            if len(holdings) >= MAX_HOLDINGS or sym in holdings:
                continue
            r = row(sym, date)
            if r is None or pd.isna(r["open"]) or pd.isna(r["atr"]):
                continue
            px = float(r["open"])
            equity = cash + sum(h["qty"] * h["last_price"] for h in holdings.values())
            budget = min(cash, equity * POSITION_SIZE)
            qty = int(budget // px)
            if qty < 1:
                continue
            gross = qty * px
            entry_cost = transaction_cost(gross, market)
            if gross + entry_cost > cash:
                continue
            cash -= gross + entry_cost
            holdings[sym] = {
                "qty": qty, "entry_px": px, "entry_date": date,
                "entry_cost": entry_cost, "stop": px - atr_mult * float(r["atr"]),
                "days": 0, "last_price": px,
            }
        pending_entry = []

        # 3. intradag: stop loss + markera dagens värde + bestäm nästa exit
        for sym in list(holdings):
            h = holdings[sym]
            r = row(sym, date)
            if r is None:
                continue
            if h["days"] >= 1 and not pd.isna(r["low"]) and float(r["low"]) <= h["stop"]:
                fill = min(float(r["open"]), h["stop"])
                close_position(sym, fill, date, "Stop loss")
                continue
            h["last_price"] = float(r["close"])
            h["days"] += 1
            if h["days"] < 1:
                continue
            rsi = None if pd.isna(r["rsi"]) else float(r["rsi"])
            ma = None if pd.isna(r[trend_ma]) else float(r[trend_ma])
            if rsi is not None and rsi > rsi_exit:
                pending_exit[sym] = f"Vinsthemtagning (RSI>{int(rsi_exit)})"
            elif ma is not None and float(r["close"]) < ma * TREND_BREAK_MARGIN:
                pending_exit[sym] = "Trendbrott"
            elif h["days"] >= max_days:
                pending_exit[sym] = f"Timeout ({max_days} d)"

        # 4. markera equity
        equity = cash + sum(h["qty"] * h["last_price"] for h in holdings.values())
        curve.append((date, equity, len(holdings)))

        # 5. ny köpsignal? (marknadsregim + max en ny position per dag)
        regime_ok = date in index_ma200.index and not pd.isna(index_ma200.loc[date]) \
            and index_close.loc[date] > index_ma200.loc[date]
        slots_left = MAX_HOLDINGS - len(holdings) - len(pending_entry)
        if regime_ok and slots_left > 0 and cash > equity * MIN_CASH_FRACTION:
            best_sym, best_rank = None, -np.inf
            for sym, g in hist.items():
                if sym in holdings or sym in pending_entry or date not in g.index:
                    continue
                r = g.loc[date]
                if bool(r["entry_sig"]) and not pd.isna(r["entry_rank"]) and r["entry_rank"] > best_rank:
                    best_sym, best_rank = sym, float(r["entry_rank"])
            if best_sym:
                pending_entry.append(best_sym)

    # stäng kvarvarande positioner till sista markerade pris (redovisas som öppna)
    last_date = dates[-1]
    for sym, h in holdings.items():
        cost_basis = h["qty"] * h["entry_px"] + h["entry_cost"]
        value = h["qty"] * h["last_price"]
        trades.append({
            "symbol": sym, "entry_date": h["entry_date"], "exit_date": last_date,
            "entry_price": round(h["entry_px"], 2), "exit_price": round(h["last_price"], 2),
            "days_held": h["days"],
            "return_pct": round((value / cost_basis - 1) * 100, 2),
            "profit": round(value - cost_basis, 2),
            "exit_reason": "Öppen position", "open": True,
        })

    return curve, trades


# ─────────────────────────────────────────────────────────────────────────────
# Nyckeltal och jämförelser
# ─────────────────────────────────────────────────────────────────────────────

def _years_between(d0, d1):
    return max((pd.to_datetime(d1) - pd.to_datetime(d0)).days / 365.25, 0.1)


def _curve_stats(dates, values):
    values = np.asarray(values, dtype=float)
    years = _years_between(dates[0], dates[-1])
    total = float(values[-1] / values[0] - 1)
    cagr = float((values[-1] / values[0]) ** (1 / years) - 1)
    daily = np.diff(values) / values[:-1]
    vol = float(np.std(daily) * np.sqrt(TRADING_DAYS)) if len(daily) > 1 else 0.0
    peak = np.maximum.accumulate(values)
    max_dd = float((values / peak - 1).min())
    return {
        "total_return": round(total * 100, 2),
        "cagr": round(cagr * 100, 2),
        "volatility": round(vol * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "calmar": round(cagr / abs(max_dd), 2) if max_dd < 0 else None,
    }


def _buy_and_hold_all(hist, dates, market):
    """Köp lika stor peng i varje symbol med data på startdagen, behåll till slut."""
    start = dates[0]
    date_idx = pd.Index(dates)
    series = {}
    for s, g in hist.items():
        if start not in g.index or pd.isna(g.loc[start, "open"]):
            continue
        closes = g["close"].reindex(date_idx).ffill()
        if closes.isna().any():
            continue
        series[s] = closes
    if not series:
        return None, None
    per = INITIAL_CAPITAL / len(series)
    px = pd.DataFrame(series)
    qty = np.array([(per - transaction_cost(per, market)) / float(hist[s].loc[start, "open"])
                    for s in px.columns])
    curve = list(map(float, px.values @ qty))
    return curve, _curve_stats(dates, curve)


def _sample_chart(dates, strat_vals, bench_vals, n=45):
    step = max(1, len(dates) // n)
    pts = []
    for i in range(0, len(dates), step):
        pts.append({"date": dates[i],
                    "strategy": round(strat_vals[i], 0),
                    "benchmark": round(bench_vals[i], 0)})
    if pts and pts[-1]["date"] != dates[-1]:
        pts.append({"date": dates[-1],
                    "strategy": round(strat_vals[-1], 0),
                    "benchmark": round(bench_vals[-1], 0)})
    return pts


def _summarise(curve, trades, hist, index_close, market):
    dates = [c[0] for c in curve]
    strat_vals = [c[1] for c in curve]
    years = _years_between(dates[0], dates[-1])

    stats = _curve_stats(dates, strat_vals)
    closed = [t for t in trades if not t["open"]]
    open_tr = [t for t in trades if t["open"]]
    wins = [t for t in closed if t["return_pct"] > 0]
    invested_days = sum(1 for c in curve if c[2] > 0)

    bh_curve, bh_stats = _buy_and_hold_all(hist, dates, market)

    idx = index_close.reindex(pd.Index(dates)).ffill()
    idx0 = idx.dropna().iloc[0] if idx.notna().any() else None
    index_return = round((idx.iloc[-1] / idx0 - 1) * 100, 2) if idx0 else None

    bench_vals = bh_curve if bh_curve else strat_vals
    return {
        "period_start": dates[0],
        "period_end": dates[-1],
        "years": round(years, 1),
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": round(strat_vals[-1], 0),
        **stats,
        "pct_time_invested": round(invested_days / len(curve) * 100, 1),
        "trades_closed": len(closed),
        "trades_open": len(open_tr),
        "trades_per_year": round(len(closed) / years, 1),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "avg_hold_days": round(float(np.mean([t["days_held"] for t in closed])), 1) if closed else 0.0,
        "buy_hold_all": bh_stats,
        "index_price_return": index_return,
        "equity_chart": _sample_chart(dates, strat_vals, bench_vals),
        "trade_list": trades[::-1][:100],
        "notes": [
            "Köp fylls på nästa dags öppningskurs. Courtage, spread och valutaväxling avdragna.",
            "Universum = dagens indexbolag (survivorship bias – avnoterade bolag saknas, vilket smickrar resultatet).",
            "\"Köp allt och behåll\" = lika stor peng i varje bolag på startdagen, en engångscourtage, behållt till slutet.",
            "Index-raden är prisindex utan utdelning och underskattar en verklig indexfond med ca 3–4 %/år.",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Publika ingångar
# ─────────────────────────────────────────────────────────────────────────────

def _stock_universe(market):
    return list((OMXS_50 if market == "omxs" else NASDAQ_100).keys())


def _index_ticker(market):
    return "^OMX" if market == "omxs" else "^NDX"


def run_backtest_local(market="omxs", years=5):
    if market == "crypto":
        return run_crypto_backtest(years=years)

    conn = get_db()
    idx_ticker = _index_ticker(market)
    symbols = _stock_universe(market)
    params = DEFAULT_PARAMS[market]

    hist_raw = _load_history(conn, symbols + [idx_ticker])
    conn.close()
    if idx_ticker not in hist_raw:
        return {"error": f"Ingen historik för index {idx_ticker}. Kör en synk först."}

    index_close = hist_raw.pop(idx_ticker)["close"]
    all_dates = list(index_close.index)
    if len(all_dates) < 260:
        return {"error": "För lite historik. Kör en full synk först."}

    requested = max(1, int(years))
    start_idx = max(0, len(all_dates) - requested * TRADING_DAYS)
    dates = all_dates[start_idx:]

    hist = {s: _prep_signals(g, params) for s, g in hist_raw.items() if len(g) > 200}
    curve, trades = _run_engine(hist, index_close, dates, params, market)
    result = _summarise(curve, trades, hist, index_close, market)
    result["market"] = "OMXS30" if market == "omxs" else "Nasdaq 100"
    result["requested_years"] = requested
    result["actual_years"] = result["years"]
    if result["years"] < requested - 0.5:
        result["notes"].insert(0, f"Begärde {requested} år men bara {result['years']} år data finns – kör på det som finns.")
    return result


def run_crypto_backtest(years=3):
    from src.core.crypto import get_crypto_df, CRYPTO_LIST
    symbols = ["BTC-USD", "ETH-USD", "SOL-USD"]
    period = f"{max(1, min(10, int(years)))}y"
    hist_raw = {}
    for s in symbols:
        df = get_crypto_df(s, period=period)
        if df is None or df.empty or len(df) < 60:
            continue
        g = df.rename(columns=str.lower)
        g.index = g.index.strftime("%Y-%m-%d")
        hist_raw[s] = g

    if "BTC-USD" not in hist_raw:
        return {"error": "Kunde inte hämta tillräcklig kryptohistorik."}

    params = DEFAULT_PARAMS["crypto"]
    index_close = hist_raw["BTC-USD"]["close"]
    dates = list(index_close.index)
    hist = {s: _prep_signals(g, params) for s, g in hist_raw.items()}
    curve, trades = _run_engine(hist, index_close, dates, params, "crypto")
    result = _summarise(curve, trades, hist, index_close, "crypto")
    result["market"] = "Krypto (BTC/ETH/SOL)"
    result["requested_years"] = int(years)
    result["actual_years"] = result["years"]
    result["notes"].append("Krypto är extremt volatilt; 3 mynt som fortfarande finns kvar är kraftig survivorship bias.")
    return result


def optimize_omx(years=8):
    """Walk-forward: parametrarna bedöms på data de inte 'tränats' på.

    Vi delar historiken i en tränings- och en testperiod och redovisar båda.
    En konfiguration som ser bra ut i träning men dåligt i test är överanpassad.
    """
    conn = get_db()
    symbols = _stock_universe("omxs")
    hist_raw = _load_history(conn, symbols + ["^OMX"])
    conn.close()
    if "^OMX" not in hist_raw:
        return {"error": "Ingen historik för ^OMX."}

    index_close = hist_raw.pop("^OMX")["close"]
    all_dates = list(index_close.index)
    start_idx = max(0, len(all_dates) - max(4, int(years)) * TRADING_DAYS)
    dates = all_dates[start_idx:]
    if len(dates) < 500:
        return {"error": "För lite historik för walk-forward. Kör en full synk först."}

    split = int(len(dates) * 0.6)
    train_dates, test_dates = dates[:split], dates[split:]

    results = []
    for name, cfg in OMXS_CONFIGS:
        p = dict(DEFAULT_PARAMS["omxs"]); p.update(cfg)
        hist = {s: _prep_signals(g, p) for s, g in hist_raw.items() if len(g) > 200}
        row = {"name": name, "atr_mult": p["atr_mult"], "max_days": p["max_days"],
               "breakout_days": p["breakout_days"], "trend_ma": p["trend_ma"]}
        for label, dd in (("train", train_dates), ("test", test_dates)):
            curve, trades = _run_engine(hist, index_close, dd, p, "omxs")
            st = _curve_stats([c[0] for c in curve], [c[1] for c in curve])
            closed = [t for t in trades if not t["open"]]
            wins = [t for t in closed if t["return_pct"] > 0]
            row[f"{label}_cagr"] = st["cagr"]
            row[f"{label}_maxdd"] = st["max_drawdown"]
            row[f"{label}_winrate"] = round(len(wins) / len(closed) * 100, 1) if closed else 0.0
            row[f"{label}_trades"] = len(closed)
        results.append(row)

    results.sort(key=lambda r: r["test_cagr"], reverse=True)
    return {
        "train_period": [train_dates[0], train_dates[-1]],
        "test_period": [test_dates[0], test_dates[-1]],
        "results": results,
        "note": "Rankad på CAGR i testperioden (out-of-sample). Stor skillnad mellan "
                "train och test = överanpassning. Detta är inte en prognos.",
    }
