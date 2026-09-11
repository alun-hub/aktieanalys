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
    """Beräknar konkreta handelsnivåer baserat på vald strategi och ATR."""
    if strategy == "dip":
        stop_dist = 2.2 * atr
        target_dist = 3.5 * atr
    elif strategy == "momentum":
        stop_dist = 2.5 * atr
        target_dist = 5.0 * atr
    else:  # trend
        stop_dist = 3.0 * atr
        target_dist = 6.5 * atr

    stop_loss = round(close - stop_dist, 2)
    target_price = round(close + target_dist, 2)
    risk_pct = round((close - stop_loss) / close * 100.0, 1)
    reward_pct = round((target_price - close) / close * 100.0, 1)
    rr = round(reward_pct / risk_pct, 1) if risk_pct > 0 else 1.0

    return {
        "entry_price": round(close, 2),
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "risk_reward_ratio": rr,
        "rr_label": f"1 : {rr:g}",
    }


def scan_opportunities(market="all", strategy_filter="all"):
    """Skannar alla bolag för dagens datum efter köpmöjligheter."""
    from src.core.backtest import prep_strategy_signals, simulate_stock_trades, STRATEGIES
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

        for strat in strategies_to_check:
            df_sig = prep_strategy_signals(df, strategy=strat)
            last_row = df_sig.iloc[-1]

            if bool(last_row.get("entry_sig", False)):
                close = float(last_row["close"])
                atr = float(last_row["atr"]) if not pd.isna(last_row["atr"]) else close * 0.02
                levels = calculate_trade_levels(close, atr, strategy=strat)

                # Beräkna historisk edge på 5 års historik
                sub_df = df_sig.tail(252 * 5)
                _, _, stats = simulate_stock_trades(sub_df, strategy=strat)

                # Motivering i klarspråk
                if strat == "dip":
                    reason = f"Översåld dipp (RSI {last_row.get('rsi', 0):.0f}) i långsiktig upptrend över MA200."
                elif strat == "momentum":
                    reason = "Utbrott mot nytt fleraveckorshögsta med förhöjd handelsvolym."
                else:
                    reason = "Stark upptrend bekräftad av Golden Cross och stängning över MA200."

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
                    "edge": {
                        "win_rate": stats["win_rate"],
                        "trades_count": stats["trades_count"],
                        "profit_factor": stats["profit_factor"],
                        "avg_gain_pct": stats["avg_gain_pct"],
                    },
                    "score": round(stats["win_rate"] * stats["profit_factor"], 1),
                })

    db.close()
    # Sortera på starkast statistisk edge
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return opportunities

