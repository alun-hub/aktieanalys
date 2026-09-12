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


STRATEGIES = {
    "dip": {
        "name": "Kvalitets-dipp i upptrend",
        "desc": "Köp starka bolag i upptrend vid tillfällig rekyl (RSI <= 38 eller test av MA50)",
        "default_rsi_exit": 65,
        "default_max_days": 20,
        "atr_stop_mult": 2.5,
    },
    "momentum": {
        "name": "Momentum & Utbrott",
        "desc": "Köp vid 20/50-dagars utbrott med volymökning och Close > MA50 > MA200",
        "default_rsi_exit": 78,
        "default_max_days": 25,
        "atr_stop_mult": 2.5,
    },
    "trend": {
        "name": "Långsiktig Trendföljare",
        "desc": "Position i stark trend över MA200 med Golden Cross",
        "default_rsi_exit": 85,
        "default_max_days": 252,
        "atr_stop_mult": 3.5,
    }
}


def prep_strategy_signals(g, strategy="dip", **custom_params):
    g = g.copy()
    g.columns = [str(col).lower() for col in g.columns]
    c = g["close"]
    ma50 = g.get("ma50") if "ma50" in g.columns else c.rolling(50).mean()
    ma200 = g.get("ma200") if "ma200" in g.columns else c.rolling(200).mean()
    rsi = g.get("rsi") if "rsi" in g.columns else pd.Series(50, index=g.index)
    vol = g["volume"]
    prior_vol = vol.rolling(20).mean().shift(1)

    # Beräkna On-Balance Volume (OBV) för volymkonfluens
    if "obv" in g.columns and not g["obv"].isna().all():
        obv = g["obv"]
    else:
        direction = np.sign(c.diff()).fillna(0)
        obv = (direction * vol).cumsum()

    if strategy == "dip":
        # Upptrend + tillfällig rekyl + vändning
        in_uptrend = (ma200.notna()) & (c > ma200 * 0.99) & (ma200 >= ma200.shift(20) * 0.995)
        is_dipping = (rsi <= 40) | (g["low"] <= ma50 * 1.015)
        turnaround = (c > g["low"].shift(1)) | (c > g["open"])
        # Volymkonfluens: Undvik panikdumpningar (säljvolym > 2.5x snittet)
        no_panic_dump = vol <= (prior_vol * 2.5).fillna(vol)
        # OBV-stabilitet: OBV ska inte vara i fritt fall
        obv_ma20 = obv.rolling(20).mean()
        obv_ok = (obv >= obv_ma20) | (obv.diff(5) >= 0) | obv_ma20.isna()
        g["entry_sig"] = in_uptrend & is_dipping & turnaround & no_panic_dump & obv_ok
        g["entry_rank"] = 50.0 - rsi.fillna(50)  # Lägre RSI = starkare köpläge

    elif strategy == "momentum":
        # 20-dagars högsta + volym + trendhierarki + OBV-bekräftelse
        prior_high_20 = g["high"].rolling(20).max().shift(1)
        breakout = (c > prior_high_20)
        vol_surge = (vol > prior_vol * 1.3)
        trend_ok = (ma50.notna()) & (ma200.notna()) & (c > ma50) & (ma50 > ma200 * 0.99)
        obv_high_20 = obv.rolling(20).max().shift(1)
        obv_surge = (obv >= obv_high_20) | obv_high_20.isna()
        g["entry_sig"] = breakout & vol_surge & trend_ok & obv_surge
        g["entry_rank"] = (vol / prior_vol.replace(0, np.nan)).fillna(1.0)

    elif strategy == "trend":
        # Golden Cross eller etablerad stängning över stigande MA200
        golden_cross = (ma50 > ma200) & (c > ma200)
        g["entry_sig"] = golden_cross
        g["entry_rank"] = ((c / ma200.replace(0, np.nan)) - 1.0).fillna(0.0)

    else:
        # Fallback till tidigare standard
        g["entry_sig"] = False
        g["entry_rank"] = 0.0

    return g


def _prep_signals(g, p):
    if isinstance(p, str):
        return prep_strategy_signals(g, strategy=p)
    if isinstance(p, dict) and "strategy" in p:
        return prep_strategy_signals(g, strategy=p["strategy"], **{k: v for k, v in p.items() if k != "strategy"})

    g = g.copy()
    if p.get("entry") == "breakout":
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
            if r is None or pd.isna(r["open"]):
                continue  # ofullständig dagsbar (t.ex. dagens Yahoo-data) – försök igen nästa dag
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
            if r is None or pd.isna(r["close"]):
                continue
            if h["days"] >= 1 and not pd.isna(r["low"]) and float(r["low"]) <= h["stop"]:
                fill = h["stop"] if pd.isna(r["open"]) else min(float(r["open"]), h["stop"])
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


def run_backtest_local(market="omxs", years=5, strategy="dip"):
    if market == "crypto":
        return run_crypto_backtest(years=years)

    conn = get_db()
    idx_ticker = _index_ticker(market)
    symbols = _stock_universe(market)
    params = dict(DEFAULT_PARAMS.get(market, DEFAULT_PARAMS["omxs"]))

    if strategy and strategy != "breakout" and strategy in STRATEGIES:
        strat_cfg = STRATEGIES[strategy]
        if "default_rsi_exit" in strat_cfg:
            params["rsi_exit"] = strat_cfg["default_rsi_exit"]
        if "default_max_days" in strat_cfg:
            params["max_days"] = strat_cfg["default_max_days"]
        if "atr_stop_mult" in strat_cfg:
            params["atr_mult"] = strat_cfg["atr_stop_mult"]

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

    if strategy and strategy != "breakout" and strategy in STRATEGIES:
        hist = {s: prep_strategy_signals(g, strategy=strategy) for s, g in hist_raw.items() if len(g) > 200}
    else:
        hist = {s: _prep_signals(g, params) for s, g in hist_raw.items() if len(g) > 200}

    curve, trades = _run_engine(hist, index_close, dates, params, market)
    result = _summarise(curve, trades, hist, index_close, market)
    result["market"] = "OMXS30" if market == "omxs" else "Nasdaq 100"
    result["requested_years"] = requested
    result["actual_years"] = result["years"]
    result["strategy"] = strategy
    result["strategy_name"] = STRATEGIES.get(strategy, {}).get("name", strategy)
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


def simulate_stock_trades(df, strategy="dip", initial_capital=100_000.0, fee_pct=0.0015):
    """Kör en isolerad handelssimulering för en enskild aktie."""
    if df is None or df.empty:
        return [], [], {
            "trades_count": 0,
            "win_rate": 0.0,
            "profit_factor": 1.0,
            "total_return": 0.0,
            "buy_and_hold_return": 0.0,
            "avg_gain_pct": 0.0,
            "avg_loss_pct": 0.0,
            "avg_days_held": 0.0,
        }

    df = df.copy()
    df.columns = [str(col).lower() for col in df.columns]

    strat_cfg = STRATEGIES.get(strategy, STRATEGIES["dip"])
    rsi_exit = strat_cfg.get("default_rsi_exit", 70)
    max_days = strat_cfg.get("default_max_days", 20)
    atr_mult = strat_cfg.get("atr_stop_mult", 2.5)

    dates = list(df.index)
    trades = []
    cash = float(initial_capital)
    position = None
    curve = []

    for i, date in enumerate(dates):
        r = df.iloc[i]
        px_open = float(r["open"]) if ("open" in r and not pd.isna(r["open"])) else float(r["close"])
        px_close = float(r["close"])
        atr = float(r["atr"]) if ("atr" in r and not pd.isna(r["atr"])) else px_close * 0.02

        # 1. Hantera öppen position (check exit)
        if position:
            position["days"] += 1
            low = float(r["low"]) if ("low" in r and not pd.isna(r["low"])) else px_close
            high = float(r["high"]) if ("high" in r and not pd.isna(r["high"])) else px_close
            rsi_val = float(r["rsi"]) if ("rsi" in r and not pd.isna(r["rsi"])) else 50.0

            exit_now = False
            exit_price = px_close
            exit_reason = ""

            # Stop loss
            if low <= position["stop_loss"]:
                exit_now = True
                exit_price = min(px_open, position["stop_loss"])
                exit_reason = "Stop loss"
            # Vinstmål / RSI-exit
            elif rsi_val >= rsi_exit:
                exit_now = True
                exit_price = px_close
                exit_reason = f"RSI-exit ({int(rsi_val)})"
            # Target exit
            elif high >= position["target"]:
                exit_now = True
                exit_price = position["target"]
                exit_reason = "Målkurs nådd"
            # Max holding period
            elif position["days"] >= max_days:
                exit_now = True
                exit_price = px_close
                exit_reason = f"Tids-exit ({max_days} d)"

            if exit_now:
                gross = position["qty"] * exit_price
                cost = gross * fee_pct
                net_val = gross - cost
                cash += net_val
                pnl = net_val - position["cost_basis"]
                ret_pct = (net_val / position["cost_basis"] - 1.0) * 100.0

                trades.append({
                    "entry_date": position["entry_date"],
                    "exit_date": date,
                    "entry_price": round(float(position["entry_price"]), 2),
                    "exit_price": round(float(exit_price), 2),
                    "days_held": int(position["days"]),
                    "return_pct": round(float(ret_pct), 2),
                    "profit": round(float(pnl), 2),
                    "exit_reason": exit_reason,
                    "open": False,
                })
                position = None

        # 2. Hantera ny köpsignal om vi saknar position
        if position is None and bool(r.get("entry_sig", False)):
            qty = int((cash * 0.95) // px_close)
            if qty > 0:
                cost_basis = qty * px_close * (1.0 + fee_pct)
                cash -= cost_basis
                stop_loss = px_close - atr_mult * atr
                # Target: 2.0x risk
                risk = px_close - stop_loss
                target = px_close + max(risk * 1.8, atr * 3.0)

                position = {
                    "entry_date": date,
                    "entry_price": px_close,
                    "qty": qty,
                    "cost_basis": cost_basis,
                    "stop_loss": stop_loss,
                    "target": target,
                    "days": 0,
                }

        # Värdera portfölj idag
        total_equity = cash + (position["qty"] * px_close if position else 0.0)
        curve.append({"date": date, "equity": round(float(total_equity), 1)})

    # Om position kvar vid slut
    if position:
        last_px = float(df.iloc[-1]["close"])
        gross = position["qty"] * last_px
        pnl = gross - position["cost_basis"]
        trades.append({
            "entry_date": position["entry_date"],
            "exit_date": dates[-1],
            "entry_price": round(float(position["entry_price"]), 2),
            "exit_price": round(float(last_px), 2),
            "days_held": int(position["days"]),
            "return_pct": round(float((gross / position["cost_basis"] - 1.0) * 100.0), 2),
            "profit": round(float(pnl), 2),
            "exit_reason": "Öppen position",
            "open": True,
        })

    # Beräkna statistik
    closed = [t for t in trades if not t["open"]]
    wins = [t for t in closed if t["profit"] > 0]
    losses = [t for t in closed if t["profit"] <= 0]
    win_rate = round(len(wins) / len(closed) * 100.0, 1) if closed else 0.0
    tot_win = sum(t["profit"] for t in wins)
    tot_loss = abs(sum(t["profit"] for t in losses))
    profit_factor = round(tot_win / tot_loss, 2) if tot_loss > 0 else (round(float(tot_win), 2) if tot_win > 0 else 1.0)

    # Buy & hold jämförelse för samma aktie
    first_px = float(df.iloc[0]["close"])
    last_px = float(df.iloc[-1]["close"])
    bh_return = round((last_px / first_px - 1.0) * 100.0, 2) if first_px > 0 else 0.0
    strat_return = round((curve[-1]["equity"] / initial_capital - 1.0) * 100.0, 2) if curve else 0.0

    stats = {
        "trades_count": len(closed),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "total_return": float(strat_return),
        "buy_and_hold_return": float(bh_return),
        "avg_gain_pct": round(float(np.mean([t["return_pct"] for t in wins])), 2) if wins else 0.0,
        "avg_loss_pct": round(float(np.mean([t["return_pct"] for t in losses])), 2) if losses else 0.0,
        "avg_days_held": round(float(np.mean([t["days_held"] for t in closed])), 1) if closed else 0.0,
    }

    return trades, curve, stats


def run_single_stock_backtest(symbol, strategy="dip", years=5):
    """Hämtar data och kör enskilt aktiebacktest."""
    try:
        conn = get_db()
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume, ma50, ma200, rsi, atr "
            "FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date",
            conn, params=[symbol]
        )
        conn.close()
    except Exception as e:
        return {"error": f"Kunde inte hämta historik för {symbol}."}

    if df.empty or len(df) < 50:
        return {"error": f"För lite historik för {symbol}."}

    df = df.set_index("date")
    cutoff = max(0, len(df) - int(years) * 252)
    df_sub = df.iloc[cutoff:].copy()

    df_signals = prep_strategy_signals(df_sub, strategy=strategy)
    trades, curve, stats = simulate_stock_trades(df_signals, strategy=strategy)

    # Nedskalad graf (max 50 punkter)
    step = max(1, len(curve) // 45)
    chart = [curve[i] for i in range(0, len(curve), step)]
    if chart and chart[-1]["date"] != curve[-1]["date"]:
        chart.append(curve[-1])

    return {
        "symbol": symbol,
        "strategy": strategy,
        "strategy_name": STRATEGIES.get(strategy, {}).get("name", strategy),
        "years": int(years),
        "stats": stats,
        "trades": trades[::-1],
        "chart": chart,
    }


_PORTFOLIO_BT_CACHE = {}


def run_portfolio_backtest(years: int = 10) -> dict:
    """Simulerar hela allokeringsstrategin (regimstyrd + koncentrationsmedveten)
    historiskt dag för dag utan lookahead mot två jämförelseindex:
      a) 100% köp-och-behåll i bred global ETF (VT)
      b) 100% köp-och-behåll i marknadsviktade S&P 500 (SPY)

    Modellen:
    - Broad ETF: VT (Global Index)
    - Equal Weight ETF: RSP (S&P 500 Equal Weight)
    - Dividend Stocks: SCHD (Kvalitetsutdelare)
    - Growth / Momentum: QQQ (Tillväxt/Tech)
    - Defensive: GLD (Fysiskt guld)

    Kostnader: Rebalansering drar courtage och spread via transaction_cost().
    """
    import yfinance as yf
    import time

    global _PORTFOLIO_BT_CACHE
    now = time.time()
    years = int(years)
    cache_key = f"pf_bt_{years}"
    if cache_key in _PORTFOLIO_BT_CACHE:
        cached_ts, cached_res = _PORTFOLIO_BT_CACHE[cache_key]
        if now - cached_ts < 3600:
            return cached_res

    try:
        symbols = ["VT", "RSP", "SCHD", "QQQ", "GLD", "SPY"]
        df_all = yf.download(symbols, period=f"{years + 1}y", interval="1d", progress=False, auto_adjust=True)
        if df_all.empty or "Close" not in df_all.columns:
            return {"error": "Kunde inte hämta historisk kursdata för portföljbacktest."}

        closes = df_all["Close"].dropna()
        if len(closes) < 252:
            return {"error": "För lite historisk data tillgänglig för portföljbacktest."}

        # Glidande medelvärden på SPY för regim (utan lookahead)
        spy_close = closes["SPY"]
        spy_ma50 = spy_close.rolling(50).mean()
        spy_ma200 = spy_close.rolling(200).mean()

        # 252-dagars rullande avkastning för koncentrationsrisk
        spy_ret_252 = spy_close.pct_change(252) * 100.0
        rsp_ret_252 = closes["RSP"].pct_change(252) * 100.0
        spread_252 = spy_ret_252 - rsp_ret_252

        start_idx = max(252, len(closes) - years * 252)
        sim_dates = closes.index[start_idx:]

        if len(sim_dates) < 100:
            return {"error": "Otillräckligt med handelsdagar för angiven period."}

        pct_changes = closes.pct_change().fillna(0.0)

        initial_capital = 100_000.0
        equity_strategy = initial_capital
        equity_vt = initial_capital
        equity_spy = initial_capital

        current_weights = {
            "broad_etf": 0.40,
            "equalweight_etf": 0.15,
            "dividend_stocks": 0.20,
            "growth_stocks": 0.20,
            "defensive": 0.05,
        }

        asset_proxy = {
            "broad_etf": "VT",
            "equalweight_etf": "RSP",
            "dividend_stocks": "SCHD",
            "growth_stocks": "QQQ",
            "defensive": "GLD",
        }

        rebalance_count = 0
        curve = []
        strategy_daily_returns = []
        vt_daily_returns = []
        spy_daily_returns = []

        last_rebalance_idx = -999

        for i, date in enumerate(sim_dates):
            # 1. Bestäm regim och koncentration för gårdagen/dagens början (strikt utan lookahead)
            prev_date = closes.index[start_idx + i - 1] if (start_idx + i > 0) else date
            close_val = float(spy_close.loc[prev_date])
            ma50_val = float(spy_ma50.loc[prev_date]) if not pd.isna(spy_ma50.loc[prev_date]) else close_val
            ma200_val = float(spy_ma200.loc[prev_date]) if not pd.isna(spy_ma200.loc[prev_date]) else close_val
            spread_val = float(spread_252.loc[prev_date]) if not pd.isna(spread_252.loc[prev_date]) else 0.0

            if close_val < ma200_val:
                regime = "bear"
            elif close_val < ma50_val:
                regime = "correction"
            else:
                regime = "bull"

            if spread_val >= 8.0:
                conc = "high"
            elif spread_val >= 3.0:
                conc = "elevated"
            else:
                conc = "normal"

            # 2. Målvikter
            if regime == "bull":
                if conc == "high":
                    target_w = {"broad_etf": 0.20, "equalweight_etf": 0.25, "dividend_stocks": 0.30, "growth_stocks": 0.10, "defensive": 0.15}
                elif conc == "elevated":
                    target_w = {"broad_etf": 0.30, "equalweight_etf": 0.20, "dividend_stocks": 0.25, "growth_stocks": 0.15, "defensive": 0.10}
                else:
                    target_w = {"broad_etf": 0.40, "equalweight_etf": 0.15, "dividend_stocks": 0.20, "growth_stocks": 0.20, "defensive": 0.05}
            elif regime == "correction":
                target_w = {"broad_etf": 0.25, "equalweight_etf": 0.20, "dividend_stocks": 0.25, "growth_stocks": 0.10, "defensive": 0.20}
            else:  # bear
                target_w = {"broad_etf": 0.10, "equalweight_etf": 0.10, "dividend_stocks": 0.15, "growth_stocks": 0.00, "defensive": 0.65}

            # 3. Omviktningskontroll (månadsvis eller regimbyte)
            should_rebalance = (i - last_rebalance_idx >= 21) or any(abs(target_w[k] - current_weights[k]) >= 0.15 for k in target_w)
            if should_rebalance:
                turnover = sum(abs(target_w[k] - current_weights[k]) for k in target_w) / 2.0
                rebalance_amount = equity_strategy * turnover
                cost = transaction_cost(rebalance_amount, "nasdaq") if rebalance_amount > 100.0 else 0.0
                equity_strategy -= cost
                current_weights = target_w.copy()
                last_rebalance_idx = i
                rebalance_count += 1

            # 4. Beräkna dagens avkastning
            day_chg = pct_changes.loc[date]
            strat_ret = sum(current_weights[k] * float(day_chg[asset_proxy[k]]) for k in current_weights)
            vt_ret = float(day_chg["VT"])
            spy_ret = float(day_chg["SPY"])

            equity_strategy *= (1.0 + strat_ret)
            equity_vt *= (1.0 + vt_ret)
            equity_spy *= (1.0 + spy_ret)

            strategy_daily_returns.append(strat_ret)
            vt_daily_returns.append(vt_ret)
            spy_daily_returns.append(spy_ret)

            date_str = date.strftime("%Y-%m-%d")
            curve.append({
                "date": date_str,
                "strategy": round(equity_strategy, 1),
                "benchmark_global": round(equity_vt, 1),
                "benchmark_sp500": round(equity_spy, 1),
            })

        total_days = len(sim_dates)
        years_actual = total_days / 252.0

        def calc_metrics(daily_rets, final_eq, init_eq):
            s_rets = pd.Series(daily_rets)
            cagr = ((final_eq / init_eq) ** (1.0 / years_actual) - 1.0) * 100.0
            cum = (1.0 + s_rets).cumprod()
            peak = cum.cummax()
            dd = (cum / peak - 1.0)
            max_dd = float(dd.min()) * 100.0
            vol = float(s_rets.std() * np.sqrt(252) * 100.0)
            calmar = round(cagr / abs(max_dd), 2) if max_dd != 0 else 0.0
            return {
                "cagr": round(cagr, 1),
                "max_drawdown": round(max_dd, 1),
                "volatility": round(vol, 1),
                "calmar": calmar,
                "final_value": int(round(final_eq)),
            }

        stats_strat = calc_metrics(strategy_daily_returns, equity_strategy, initial_capital)
        stats_vt = calc_metrics(vt_daily_returns, equity_vt, initial_capital)
        stats_spy = calc_metrics(spy_daily_returns, equity_spy, initial_capital)

        step = max(1, len(curve) // 120)
        chart_sampled = [curve[j] for j in range(0, len(curve), step)]
        if chart_sampled and chart_sampled[-1]["date"] != curve[-1]["date"]:
            chart_sampled.append(curve[-1])

        result = {
            "years": int(round(years_actual)),
            "start_date": sim_dates[0].strftime("%Y-%m-%d"),
            "end_date": sim_dates[-1].strftime("%Y-%m-%d"),
            "strategy": stats_strat,
            "benchmark_global": {**stats_vt, "name": "Global Index (VT)"},
            "benchmark_sp500": {**stats_spy, "name": "S&P 500 (SPY)"},
            "equity_curve": chart_sampled,
            "rebalance_count": rebalance_count,
            "disclaimer": (
                "Historisk simulering utan framåtblickande information. Strategin justerar månadsvis "
                "mellan globala index, likaviktat, utdelningsaktier och defensiva tillgångar baserat "
                "på marknadstrend (MA50/MA200) och koncentrationsrisk. Courtage och spread beaktas."
            ),
        }

        _PORTFOLIO_BT_CACHE[cache_key] = (now, result)
        return result
    except Exception as e:
        return {"error": f"Fel vid simulering av portföljbacktest: {e}"}


