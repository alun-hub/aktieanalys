"""Marknadsläge – teknisk trendbild för bevakade aktier.

Detta är INTE köp-/säljrekommendationer. Det säger bara om priset just nu ligger
i en uppåt- eller nedåttrend enligt glidande medelvärden och RSI. Insyns- och
kongressköp påverkar ingenting här – de visas som ren information i bolagsvyn.
"""
import sqlite3
from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100

ATR_STOP_MULT = 3.0   # samma multipel som bolagsvyns nivåkalkyl


def trend_score(close, ma50, ma200, rsi, ma200_slope=None, ema20=None, macd_hist=None):
    """0–100 där 50 = neutralt. Symmetriskt: death cross straffar lika mycket
    som golden cross belönar. Tar hänsyn till MA200-lutning, EMA20 och MACD-histogram."""
    s = 50.0

    # Långsiktig trend (MA200 & dess lutning)
    if ma200_slope is not None:
        if ma200:
            s += 14 if close > ma200 else -14
        s += 5 if ma200_slope > 0 else (-5 if ma200_slope < 0 else 0)
    else:
        if ma200:
            s += 18 if close > ma200 else -18

    # Kortsiktigt & medellångt momentum (MA50 & EMA20)
    if ema20 is not None:
        if ma50:
            s += 8 if close > ma50 else -8
        s += 5 if close > ema20 else -5
    else:
        if ma50:
            s += 12 if close > ma50 else -12

    # Golden / Death cross
    if ma50 and ma200:
        s += 7 if ma50 > ma200 else -7

    # MACD momentum-bekräftelse
    if macd_hist is not None:
        s += 4 if macd_hist > 0 else (-4 if macd_hist < 0 else 0)

    # RSI (Wilder's)
    if rsi is not None:
        s += (rsi - 50) * 0.25
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


def _reasons(close, ma50, ma200, rsi, curr, ma200_slope=None, ema20=None, macd_hist=None, bb_squeeze=False):
    out = []
    if ma200:
        slope_txt = ""
        if ma200_slope is not None:
            slope_txt = " (stigande)" if ma200_slope > 0 else " (fallande)"
        out.append(f"{'Över' if close > ma200 else 'Under'} 200-dagars medelvärde{slope_txt} ({ma200:g} {curr})")
    if ema20:
        out.append(f"{'Över' if close > ema20 else 'Under'} kortsiktigt stöd EMA20 ({ema20:g} {curr})")
    if ma50 and ma200:
        out.append("Golden cross (MA50 > MA200)" if ma50 > ma200 else "Death cross (MA50 < MA200)")
    if macd_hist is not None:
        out.append(f"MACD {'positivt' if macd_hist > 0 else 'negativt'} momentum ({macd_hist:+.2f})")
    if bb_squeeze:
        out.append("Bollinger Squeeze (volatilitet komprimerad inför utbrott)")
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
        # close IS NOT NULL: en enstaka dag kan sakna kurs (t.ex. en
        # ofullständig bar från en synk mitt under handelsdagen hos Yahoo).
        rows = db.execute(
            "SELECT date, close, open, ma50, ma200, rsi, atr FROM history "
            "WHERE symbol = ? AND close IS NOT NULL ORDER BY date DESC LIMIT 25", (sym,)).fetchall()
        if not rows:
            continue
        now, prev = rows[0], (rows[1] if len(rows) > 1 else rows[0])
        close = float(now["close"])
        prev_close = float(prev["close"]) if prev["close"] else close
        curr = "$" if mkt == "NASDAQ" else "kr"

        rsi = round(float(now["rsi"]), 1) if now["rsi"] is not None else None
        ma50 = round(float(now["ma50"]), 2) if now["ma50"] is not None else None
        ma200 = round(float(now["ma200"]), 2) if now["ma200"] is not None else None
        atr = float(now["atr"]) if now["atr"] is not None else close * 0.03

        ma200_slope = None
        if len(rows) >= 20 and now["ma200"] is not None and rows[19]["ma200"] is not None:
            ma200_slope = float(now["ma200"]) - float(rows[19]["ma200"])

        score = trend_score(close, ma50, ma200, rsi, ma200_slope=ma200_slope)
        label, tclass = trend_label(score)
        stop = round(close - ATR_STOP_MULT * atr, 2)

        results.append({
            "symbol": sym, "name": name, "market": mkt, "currency": curr,
            "close": round(close, 2),
            "change_pct": round((close / prev_close - 1) * 100, 2) if prev_close else 0.0,
            "rsi": rsi, "ma50": ma50, "ma200": ma200,
            "trend_score": score, "trend_label": label, "trend_class": tclass,
            "reasons": _reasons(close, ma50, ma200, rsi, curr, ma200_slope=ma200_slope),
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


def calculate_trade_levels(close: float, atr: float, strategy: str = "dip") -> dict:
    """Beräknar konkreta handelsnivåer baserat på vald strategi, ATR och dynamisk 50% TP1/TP2."""
    if strategy == "dip":
        stop_dist = 2.2 * atr
        tp1_dist = 2.2 * atr
        target_dist = 3.5 * atr
    elif strategy == "momentum":
        stop_dist = 2.5 * atr
        tp1_dist = 2.5 * atr
        target_dist = 5.0 * atr
    else:  # trend
        stop_dist = 3.0 * atr
        tp1_dist = 3.0 * atr
        target_dist = 6.5 * atr

    stop_loss = round(close - stop_dist, 2)
    tp1 = round(close + tp1_dist, 2)
    target_price = round(close + target_dist, 2)
    risk_pct = round((close - stop_loss) / close * 100.0, 1)
    reward_pct = round((target_price - close) / close * 100.0, 1)
    rr = round(reward_pct / risk_pct, 1) if risk_pct > 0 else 1.0

    return {
        "entry_price": round(close, 2),
        "stop_loss": stop_loss,
        "target_price": target_price,
        "tp1": tp1,
        "tp2": target_price,
        "trailing_desc": "Vid Delmål 1 säkras 50% vinst och stop-loss flyttas till breakeven (ingångskurs). Resterande 50% rids med glidande trailing stop mot Mål 2.",
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "risk_reward_ratio": rr,
        "rr_label": f"1 : {rr:g}",
    }


EDGE_CREDIBILITY_K = 15   # antal egna affärer som ger aktiens egen statistik 50 % vikt
MIN_PRIOR_TRADES = 30     # minsta antal affärer i universumet för att lita på snittet
MIN_OWN_TRADES_NO_PRIOR = 10
SCORE_W_MRS = 0.05        # vikt för Mansfield RS i rangordningen
SCORE_W_MOM = 0.03        # vikt för momentum-percentil (12–1 mån) i rangordningen

_PRIOR_CACHE = {}
_PRIOR_TTL = 6 * 3600


def _cost_market(mkt):
    return "nasdaq" if str(mkt).upper() in ("NASDAQ", "US", "USA") else "omxs"


def _regime_market(mkt):
    return "nasdaq" if _cost_market(mkt) == "nasdaq" else "omx"


def _closed_returns(trades):
    return [float(t["return_pct"]) for t in trades if not t.get("open")]


def entry_allowed_now(mkt, strategy, date):
    """Tillåter marknadsregimen nya köp enligt `strategy` på `date`? (True om data saknas)"""
    import pandas as pd
    from src.core.regime import regime_entry_mask
    mask = regime_entry_mask(_regime_market(mkt), strategy)
    if mask is None or len(mask) == 0:
        return True
    mask = mask[~mask.index.duplicated(keep="last")].sort_index()
    val = mask.reindex([pd.Timestamp(str(date)[:10])], method="ffill")
    return bool(val.iloc[0]) if not val.isna().all() else True


def get_strategy_prior(strategy, force_refresh=False):
    """Poolad statistik för en strategi över hela universumet (5 år, med kostnader och
    regimfilter). Används som utgångspunkt som enskilda aktiers få affärer krymps mot –
    annars blir 5–10 affärer per aktie mest slump."""
    import time
    import pandas as pd
    from src.core.backtest import prep_strategy_signals, simulate_stock_trades
    from src.core.regime import regime_entry_mask
    now = time.time()
    hit = _PRIOR_CACHE.get(strategy)
    if hit and not force_refresh and now - hit[0] < _PRIOR_TTL:
        return hit[1]

    db = get_db()
    rets = []
    try:
        for sym, name in {**OMXS_50, **NASDAQ_100}.items():
            mkt = "NASDAQ" if sym in NASDAQ_100 else "OMX"
            df = pd.read_sql_query(
                "SELECT date, open, high, low, close, volume, ma50, ma200, rsi, atr "
                "FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date",
                db, params=[sym])
            if len(df) < 300:
                continue
            df = df.set_index("date")
            sig = prep_strategy_signals(df, strategy=strategy).tail(252 * 5)
            mask = regime_entry_mask(_regime_market(mkt), strategy)
            trades, _, _ = simulate_stock_trades(sig, strategy=strategy, market=_cost_market(mkt),
                                                 entry_allowed=mask)
            rets.extend(_closed_returns(trades))
    finally:
        db.close()

    prior = None
    if rets:
        wins = [r for r in rets if r > 0]
        prior = {"n": len(rets), "mean_ret": sum(rets) / len(rets),
                 "win_rate": len(wins) / len(rets) * 100.0}
    _PRIOR_CACHE[strategy] = (now, prior)
    return prior


def blend_edge(trades, stats, prior):
    """Krymper en akties egen affärsstatistik mot universumssnittet.

    expectancy_pct = förväntad nettoavkastning per affär (efter kostnader). `qualifies`
    kräver att den är > 0 *och* att strategin i snitt är lönsam över hela universumet – bygger
    på poolad statistik, inte på aktiens egna fåtal affärer.
    """
    rets = _closed_returns(trades)
    n = len(rets)
    own_mean = sum(rets) / n if n else 0.0
    own_win = (sum(1 for r in rets if r > 0) / n * 100.0) if n else 0.0
    if prior and prior["n"] >= MIN_PRIOR_TRADES:
        w = n / (n + EDGE_CREDIBILITY_K)
        exp = w * own_mean + (1 - w) * prior["mean_ret"]
        win = w * own_win + (1 - w) * prior["win_rate"]
        # Kräver att strategin fungerar i universumet som helhet. Annars är en aktie med några
        # lyckade affärer bara en av 98 som av slump ser bra ut (multipla jämförelser).
        qualifies = exp > 0 and prior["mean_ret"] > 0
        prior_n, prior_exp = prior["n"], round(prior["mean_ret"], 2)
    else:
        w = 1.0 if n else 0.0
        exp, win = own_mean, own_win
        qualifies = n >= MIN_OWN_TRADES_NO_PRIOR and exp > 0
        prior_n, prior_exp = 0, None
    confidence = "hög" if n >= 20 else ("medel" if n >= 8 else "låg")
    return {
        "win_rate": round(win, 1),
        "trades_count": n,
        "profit_factor": stats.get("profit_factor"),
        "avg_gain_pct": stats.get("avg_gain_pct"),
        "total_return": stats.get("total_return"),
        "expectancy_pct": round(exp, 2),
        "own_expectancy_pct": round(own_mean, 2),
        "credibility": round(w, 2),
        "confidence": confidence,
        "prior_trades": prior_n,
        "prior_expectancy_pct": prior_exp,
        "qualifies": bool(qualifies),
    }


def compute_edge(df_sig, strategy, mkt):
    """Historisk edge för `strategy` på en akties signaldata (5 år, kostnader + regimfilter)."""
    from src.core.backtest import simulate_stock_trades
    from src.core.regime import regime_entry_mask
    mask = regime_entry_mask(_regime_market(mkt), strategy)
    trades, _, stats = simulate_stock_trades(df_sig.tail(252 * 5), strategy=strategy,
                                             market=_cost_market(mkt), entry_allowed=mask)
    return blend_edge(trades, stats, get_strategy_prior(strategy))


_OPPORTUNITIES_CACHE = {}
_OPPORTUNITIES_TTL = 3600

_RECOMMENDATIONS_CACHE = {}
_RECOMMENDATIONS_TTL = 3600


def clear_signals_cache():
    """Tömmer cachen för affärsmöjligheter och rekommendationer vid datanyuppdatering."""
    global _OPPORTUNITIES_CACHE, _RECOMMENDATIONS_CACHE
    _OPPORTUNITIES_CACHE.clear()
    _RECOMMENDATIONS_CACHE.clear()
    _PRIOR_CACHE.clear()


def scan_opportunities(market="all", strategy_filter="all", force_refresh: bool = False):
    """Skannar alla bolag för dagens datum efter köpmöjligheter med kvalitetsspärr och relativ styrka."""
    import time
    global _OPPORTUNITIES_CACHE
    now = time.time()
    cache_key = (market, strategy_filter)
    if not force_refresh and cache_key in _OPPORTUNITIES_CACHE:
        ts, cached_data = _OPPORTUNITIES_CACHE[cache_key]
        if now - ts < _OPPORTUNITIES_TTL:
            return [dict(x) for x in cached_data]

    from src.core.backtest import prep_strategy_signals, STRATEGIES
    from src.core.relative_strength import get_stock_relative_strength
    import pandas as pd

    db = get_db()
    tickers = {}
    if market in ("all", "omx", "omxs"):
        tickers.update({s: (n, "OMX") for s, n in OMXS_50.items()})
    if market in ("all", "nasdaq"):
        tickers.update({s: (n, "NASDAQ") for s, n in NASDAQ_100.items()})

    strategies_to_check = ["dip", "momentum", "trend"]
    if strategy_filter in strategies_to_check:
        strategies_to_check = [strategy_filter]

    opportunities = []

    for sym, (name, mkt) in tickers.items():
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume, ma50, ma200, rsi, atr "
            "FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date",
            db, params=[sym]
        )
        if df.empty or len(df) < 100:
            continue

        df = df.set_index("date")
        curr = "$" if mkt == "NASDAQ" else "kr"

        # Beräkna Relativ Styrka först när signal faktiskt genereras (sparar ~80% exekveringstid)
        rs = None

        for strat in strategies_to_check:
            df_sig = prep_strategy_signals(df, strategy=strat)
            last_row = df_sig.iloc[-1]

            if bool(last_row.get("entry_sig", False)):
                # Marknadsregimen: inga nya köp i bear (och bara dipp-köp i korrektion)
                if not entry_allowed_now(mkt, strat, df_sig.index[-1]):
                    continue
                close = float(last_row["close"])
                atr = float(last_row["atr"]) if not pd.isna(last_row["atr"]) else close * 0.02
                levels = calculate_trade_levels(close, atr, strategy=strat)

                # Historisk edge: 5 år, med kostnader och regimfilter, krympt mot
                # universumssnittet. Kräver positiv förväntad nettoavkastning per affär.
                stats = compute_edge(df_sig, strat, mkt)
                if not stats["qualifies"]:
                    continue

                # Beräkna RS endast för kandidater som kvalificerat sig
                if rs is None:
                    rs = get_stock_relative_strength(sym, market=mkt)

                # Motivering i klarspråk
                if strat == "dip":
                    reason = f"Översåld dipp (RSI {last_row.get('rsi', 0):.0f}) i långsiktig upptrend över MA200."
                elif strat == "momentum":
                    reason = "Utbrott mot nytt fleraveckorshögsta med förhöjd handelsvolym och OBV-bekräftelse."
                else:
                    reason = "Ny långsiktig trend: Golden Cross (MA50 över MA200) och kurs över MA200 har precis inträffat."

                # Rangordning: förväntad nettoavkastning per affär (%), plus relativ styrka och
                # 12–1-månaders momentum (vikter överst i filen).
                score_val = round(
                    stats["expectancy_pct"]
                    + SCORE_W_MRS * float(rs.get("mrs") or 0)
                    + SCORE_W_MOM * (float(rs.get("mom_pct", 50.0)) - 50.0), 2)

                opportunities.append({
                    "symbol": sym,
                    "name": name,
                    "market": mkt,
                    "currency": curr,
                    "close": close,
                    "strategy": strat,
                    "strategy_name": STRATEGIES[strat]["name"],
                    "reason": reason,
                    "levels": levels,
                    "relative_strength": rs,
                    "edge": {k: v for k, v in stats.items() if k != "qualifies"},
                    "score": score_val,
                })

    db.close()
    # Sortera på starkast statistisk edge
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    _OPPORTUNITIES_CACHE[cache_key] = (now, opportunities)
    return opportunities


def build_recommendations(market="all", force_refresh: bool = False) -> dict:
    """Slår ihop målvikt från compute_target_allocation med konkreta
    investeringskandidater per tillgångsklass:
      - 'broad_etf': Breda UCITS-index-ETF:er (t.ex. VWCE.DE, IWDA.AS)
      - 'equalweight_etf': Likaviktade UCITS-ETF:er (t.ex. XDEW.DE)
      - 'dividend_stocks': Högrankade utdelningsaktier från get_top_dividend_stocks
      - 'growth_stocks': Momentum/tillväxtaktier med statistisk edge från scan_opportunities
      - 'defensive': Kapitalbevarande UCITS-ETF:er (fysiskt guld, räntor)
    """
    import datetime
    import time
    global _RECOMMENDATIONS_CACHE
    now = time.time()
    cache_key = market
    if not force_refresh and cache_key in _RECOMMENDATIONS_CACHE:
        ts, cached_data = _RECOMMENDATIONS_CACHE[cache_key]
        if now - ts < _RECOMMENDATIONS_TTL:
            return dict(cached_data)

    from src.core.allocation import compute_target_allocation
    from src.core.dividends import get_top_dividend_stocks
    from src.core.config import RECOMMENDED_UCITS_ETFS

    target_data = compute_target_allocation(market=market)
    alloc = target_data["allocation"]
    regime_data = target_data["regime"]
    conc_data = target_data["concentration"]
    conc_level = conc_data.get("level", "normal")

    recommendations = []

    # 1. Breda UCITS ETF:er
    if alloc.get("broad_etf", 0) > 0:
        for etf in RECOMMENDED_UCITS_ETFS.get("broad_etf", []):
            recommendations.append({
                "type": "broad_etf",
                "type_label": "Bred Global Index-ETF",
                "target_pct": alloc["broad_etf"],
                "symbol": etf["symbol"],
                "name": etf["name"],
                "region": etf["region"],
                "fee_pct": etf["fee_pct"],
                "badge": "UCITS / ISK",
                "reason": "Bred marknadsviktad basallokering med låg förvaltningsavgift.",
            })

    # 2. Likaviktade UCITS ETF:er
    if alloc.get("equalweight_etf", 0) > 0:
        for etf in RECOMMENDED_UCITS_ETFS.get("equalweight_etf", []):
            recommendations.append({
                "type": "equalweight_etf",
                "type_label": "Likaviktad ETF",
                "target_pct": alloc["equalweight_etf"],
                "symbol": etf["symbol"],
                "name": etf["name"],
                "region": etf["region"],
                "fee_pct": etf["fee_pct"],
                "badge": "UCITS / ISK",
                "reason": "Minskar koncentrationsrisk mot tech-jättar (Mag7) genom jämn bolagsviktning.",
            })

    # 3. Utdelningsaktier
    if alloc.get("dividend_stocks", 0) > 0:
        div_limit = 5 if conc_level == "high" else 3
        div_res = get_top_dividend_stocks(market=market, limit=div_limit)
        for s in div_res.get("stocks", []):
            recommendations.append({
                "type": "dividend_stocks",
                "type_label": "Utdelningsaktie",
                "target_pct": alloc["dividend_stocks"],
                "symbol": s["symbol"],
                "name": s["name"],
                "market": s["market"],
                "currency": s["currency"],
                "close": s["close"],
                "yield_pct": s["dividend_yield"],
                "payout_ratio": s["payout_ratio"],
                "pe": s["pe"],
                "streak_years": s.get("streak_years"),
                "score": s["dividend_score"],
                "badge": f"{s['dividend_yield']}% direktavk.",
                "reason": s["verdict"],
            })

    # 4. Tillväxt / Momentum
    if alloc.get("growth_stocks", 0) > 0:
        # Kandidater: bolagen med starkast relativ momentum (12–1 mån) i universumet – den enda
        # indikator som i våra tester hängt ihop med överavkastning. Tekniska köpsignaler
        # (scan_opportunities) läggs till när de klarar den statistiska spärren.
        from src.core.relative_strength import get_top_momentum
        growth_limit = 2 if conc_level == "high" else (4 if conc_level == "elevated" else 5)
        seen = set()
        for op in scan_opportunities(market=market)[:growth_limit]:
            seen.add(op["symbol"])
            recommendations.append({
                "type": "growth_stocks",
                "type_label": "Tillväxt / Momentum",
                "target_pct": alloc["growth_stocks"],
                "symbol": op["symbol"],
                "name": op["name"],
                "market": op["market"],
                "currency": op["currency"],
                "close": op["close"],
                "strategy": op["strategy_name"],
                "score": op["score"],
                "badge": f"Förväntat {op['edge']['expectancy_pct']:+.1f}% / affär",
                "reason": op["reason"],
            })
        for m in get_top_momentum(market=market, limit=growth_limit):
            if m["symbol"] in seen or len(seen) >= growth_limit:
                continue
            seen.add(m["symbol"])
            recommendations.append({
                "type": "growth_stocks",
                "type_label": "Tillväxt / Momentum",
                "target_pct": alloc["growth_stocks"],
                "symbol": m["symbol"],
                "name": m["name"],
                "market": m["market"],
                "currency": m["currency"],
                "close": m["close"],
                "strategy": "Relativ momentum",
                "score": m["mom_pct"],
                "badge": f"Momentum {m['mom_pct']:.0f}:e percentilen",
                "reason": f"Bland de starkaste bolagen i universumet på 12–1 månaders momentum ({m['mom_12_1']:+.0f} %). "
                          "Effekten är liten och ingen garanti.",
            })

    # 5. Defensivt (Guld & Räntor)
    if alloc.get("defensive", 0) > 0:
        for etf in RECOMMENDED_UCITS_ETFS.get("defensive", []):
            recommendations.append({
                "type": "defensive",
                "type_label": "Defensivt (Guld/Räntor)",
                "target_pct": alloc["defensive"],
                "symbol": etf["symbol"],
                "name": etf["name"],
                "region": etf["region"],
                "fee_pct": etf["fee_pct"],
                "badge": "UCITS / ISK",
                "reason": "Dämpar portföljvolatilitet och bevarar kapital i oroligt marknadsklimat.",
            })

    res = {
        "allocation": alloc,
        "recommendations": recommendations,
        "regime": regime_data,
        "concentration": conc_data,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "disclaimer": (
            "Detta är regelbaserade modellförslag baserade på marknadsregim och koncentrationsrisk, "
            "inte personlig rådgivning eller garanterade prognoser. ETF-urvalet består av europeiska "
            "UCITS-fonder anpassade för svenskt ISK."
        ),
    }
    _RECOMMENDATIONS_CACHE[cache_key] = (now, res)
    return res


