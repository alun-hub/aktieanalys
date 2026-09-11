import re
import time
import datetime
import pandas as pd
import yfinance as yf
from src.core.indicators import calc_rsi, calc_atr
from src.core.patterns import detect_patterns
from src.core.short_interest import fetch_short_interest
from src.core.signals import trend_score, trend_label
from src.core.config import OMXS_50, NASDAQ_100

CRYPTO_NAMES = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "XRP-USD": "XRP", "BNB-USD": "BNB", "ADA-USD": "Cardano",
    "DOGE-USD": "Dogecoin", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink",
    "DOT-USD": "Polkadot", "NEAR-USD": "NEAR Protocol", "SUI20947-USD": "Sui",
}


def search_symbols(query):
    """Söker efter tickers och bolagsnamn via OMX/Nasdaq-listor och Yahoo Finance."""
    query = query.strip()
    if not query:
        return []

    q_lower = query.lower()
    matches = []

    for sym, name in {**OMXS_50, **NASDAQ_100}.items():
        if q_lower in sym.lower() or q_lower in name.lower():
            matches.append({"symbol": sym, "name": name, "type": "Stock"})

    try:
        r = yf.Search(query, max_results=6).response
        for quote in r.get("quotes", []):
            sym = quote.get("symbol", "")
            name = quote.get("longname") or quote.get("shortname") or sym
            q_type = quote.get("quoteType", "EQUITY")
            if sym and not any(m["symbol"] == sym for m in matches):
                matches.append({"symbol": sym, "name": name, "type": q_type})
    except Exception:
        pass

    return matches[:10]


def resolve_symbol(query):
    """Mappar en söksträng (t.ex. 'investor', 'volvo', 'bitcoin') till rätt ticker."""
    q = query.strip()
    if not q:
        return None

    crypto_aliases = {
        "btc": "BTC-USD", "bitcoin": "BTC-USD",
        "eth": "ETH-USD", "ethereum": "ETH-USD",
        "sol": "SOL-USD", "solana": "SOL-USD",
        "xrp": "XRP-USD", "ripple": "XRP-USD",
        "bnb": "BNB-USD", "ada": "ADA-USD", "cardano": "ADA-USD",
        "doge": "DOGE-USD", "dogecoin": "DOGE-USD",
        "avax": "AVAX-USD", "avalanche": "AVAX-USD",
        "link": "LINK-USD", "chainlink": "LINK-USD",
        "dot": "DOT-USD", "polkadot": "DOT-USD",
        "near": "NEAR-USD", "sui": "SUI20947-USD",
    }
    q_lower = q.lower()
    if q_lower in crypto_aliases:
        return crypto_aliases[q_lower]

    q_upper = q.upper()
    if q_upper.endswith("-USD"):
        return q_upper

    all_tickers = {**OMXS_50, **NASDAQ_100}
    if q_upper in all_tickers:
        return q_upper
    if f"{q_upper}.ST" in all_tickers:
        return f"{q_upper}.ST"

    for sym, name in all_tickers.items():
        if q_lower == name.lower() or q_lower in name.lower() or name.lower() in q_lower:
            return sym

    results = search_symbols(q)
    if results and results[0].get("symbol"):
        return results[0]["symbol"]
    return q_upper


_market_overview_cache = {"data": None, "ts": 0.0}


def get_market_overview():
    """Snabb överblick för de viktigaste indexen och Bitcoin."""
    global _market_overview_cache
    now = time.time()
    if _market_overview_cache["data"] and (now - _market_overview_cache["ts"] < 300):
        return _market_overview_cache["data"]

    instruments = [("^OMX", "OMXS30"), ("^NDX", "Nasdaq 100"),
                   ("^GSPC", "S&P 500"), ("BTC-USD", "Bitcoin")]
    overview = []
    for sym, name in instruments:
        try:
            df = yf.download(sym, period="5d", interval="1d", progress=False, auto_adjust=True)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            c_today = float(df.iloc[-1]["Close"])
            c_prev = float(df.iloc[-2]["Close"])
            overview.append({"symbol": sym, "name": name, "price": round(c_today, 2),
                             "change_pct": round((c_today / c_prev - 1) * 100, 2)})
        except Exception:
            pass

    _market_overview_cache = {"data": overview, "ts": now}
    return overview


# ─────────────────────────────────────────────────────────────────────────────
# Hjälpare
# ─────────────────────────────────────────────────────────────────────────────

def _num(v):
    try:
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _pct(v):
    n = _num(v)
    return round(n * 100, 1) if n is not None else None


def _display_name(symbol, is_crypto, ticker):
    if is_crypto:
        return CRYPTO_NAMES.get(symbol, symbol.replace("-USD", ""))
    for s, n in {**OMXS_50, **NASDAQ_100}.items():
        if s == symbol:
            return n
    try:
        info = ticker.info or {}
        return info.get("longName") or info.get("shortName") or symbol
    except Exception:
        return symbol


def _dividend_yield_pct(raw):
    # yfinance (>= 0.2.4x) returnerar direktavkastning redan i procent (t.ex. 2.4 = 2,4 %).
    n = _num(raw)
    if n is None or not (0 < n < 25):
        return None
    return round(n, 2)


def _valuation(closes, close, info, is_crypto):
    lo, hi = float(closes.min()), float(closes.max())
    pctile = round((close - lo) / (hi - lo), 2) if hi > lo else None
    span_txt = f"Priset ligger {int(pctile * 100)} % upp i sitt 5-årsspann." if pctile is not None else ""

    if is_crypto:
        return {"verdict": "spekulativt", "pe": None, "forward_pe": None, "ps": None,
                "dividend_yield": None, "price_pctile_5y": pctile,
                "text": (span_txt + " Krypto har inga vinster eller kassaflöden att "
                         "värdera mot – priset styrs helt av utbud och efterfrågan.").strip()}

    pe = _num(info.get("trailingPE"))
    fwd_pe = _num(info.get("forwardPE"))
    ps = _num(info.get("priceToSalesTrailing12Months"))
    dy = _dividend_yield_pct(info.get("dividendYield"))
    sector = (info.get("sector") or "")

    verdict, bits = "okänt", []
    if sector == "Financial Services" and pe and pe < 9:
        bits.append("OBS: investmentbolag och banker har ofta missvisande P/E – "
                    "titta hellre på substansvärde respektive P/B.")
    if pe and pe > 0:
        if pe < 12:
            verdict = "lågt värderat"
            bits.append(f"P/E {pe:.0f} är lågt – marknaden förväntar sig svag eller sjunkande vinst, eller så är aktien billig.")
        elif pe < 22:
            verdict = "rimligt värderat"
            bits.append(f"P/E {pe:.0f} ligger i ett normalt spann.")
        elif pe < 35:
            verdict = "högt värderat"
            bits.append(f"P/E {pe:.0f} är högt – marknaden prisar in god vinsttillväxt.")
        else:
            verdict = "mycket högt värderat"
            bits.append(f"P/E {pe:.0f} är mycket högt – all framtida tillväxt måste infrias för att motivera priset.")
    if dy:
        bits.append(f"Direktavkastning cirka {dy:g} %.")
    if span_txt:
        bits.append(span_txt)

    return {"verdict": verdict,
            "pe": round(pe, 1) if pe else None,
            "forward_pe": round(fwd_pe, 1) if fwd_pe else None,
            "ps": round(ps, 1) if ps else None,
            "dividend_yield": dy, "price_pctile_5y": pctile,
            "text": " ".join(bits) or "Nyckeltal saknas för det här bolaget hos datakällan."}


def _fundamentals(info, is_crypto):
    if is_crypto or not info:
        return None
    summary = (info.get("longBusinessSummary") or "").strip()
    return {
        "summary": summary[:700] + ("…" if len(summary) > 700 else ""),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "market_cap": _num(info.get("marketCap")),
        "revenue_growth": _pct(info.get("revenueGrowth")),
        "earnings_growth": _pct(info.get("earningsGrowth")),
        "profit_margin": _pct(info.get("profitMargins")),
    }


def _tech_notes(close, ma50, ma200, rsi, curr, patterns):
    notes = []
    if ma200:
        notes.append(f"{'Över' if close > ma200 else 'Under'} 200-dagars medelvärde ({ma200:g} {curr}) – "
                     f"{'långsiktigt positivt' if close > ma200 else 'långsiktig svaghet'}.")
    if ma50 and ma200:
        notes.append("Golden cross (MA50 över MA200)." if ma50 > ma200 else "Death cross (MA50 under MA200).")
    if rsi is not None:
        if rsi > 75:
            notes.append(f"RSI {rsi:g} – överköpt, ökad risk för rekyl.")
        elif rsi < 30:
            notes.append(f"RSI {rsi:g} – översålt.")
        else:
            notes.append(f"RSI {rsi:g} – neutralt momentum.")
    if patterns:
        p = patterns[-1]
        notes.append(f"Senaste ljusmönster: {p['pattern']} – {p.get('desc', '')}")
    return notes


def _next_earnings(ticker):
    try:
        cal = ticker.calendar
        ed = None
        if isinstance(cal, dict):
            v = cal.get("Earnings Date")
            ed = v[0] if isinstance(v, (list, tuple)) and v else v
        if ed is None:
            return None
        d = ed.date() if hasattr(ed, "date") else ed
        days = (d - datetime.date.today()).days
        if days < 0:
            return None
        return {"date": str(d), "days_until": days, "soon": days <= 14}
    except Exception:
        return None


def calc_context(symbol, is_crypto, is_us):
    """Ren informationskontext – insyns- och kongresstransaktioner. Ingen poäng, ingen rekommendation."""
    ctx = {"insider": [], "congress": []}
    if is_crypto:
        return ctx
    if not is_us:
        try:
            from src.core.insider import get_insider_transactions_for_symbol
            ctx["insider"] = get_insider_transactions_for_symbol(symbol, days=120)
        except Exception:
            pass
    else:
        try:
            from src.core.congress import scan_congress_trades
            cg = scan_congress_trades(months=6)
            ctx["congress"] = [t for t in cg.get("trades", []) if t.get("ticker") == symbol][:12]
        except Exception:
            pass
    return ctx


def _summary(name, tlabel, valuation, is_crypto):
    parts = [f"{name} ligger just nu i en {tlabel.lower()}."]
    if valuation.get("verdict") not in (None, "okänt"):
        parts.append(f"Värderingen ser {valuation['verdict']} ut.")
    parts.append("Det här är information, inte en köp- eller säljrekommendation.")
    if is_crypto:
        parts.append("Krypto är en mycket volatil och spekulativ tillgångsklass.")
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Bolagsanalys
# ─────────────────────────────────────────────────────────────────────────────

def analyze_any_stock(symbol):
    """Bolags-/tillgångsanalys: vad det är och hur det är värderat först, teknisk trend som kontext."""
    resolved = resolve_symbol(symbol)
    symbol = (resolved or symbol).strip().upper()
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5y", auto_adjust=True)
        if df.empty or len(df) < 30:
            return {"error": f"Kunde inte hämta kursdata för {symbol}. "
                             "Prova fullständig ticker (t.ex. INVE-B.ST, AAPL eller BTC-USD)."}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
        df.index = df.index.normalize()

        is_crypto = symbol.endswith("-USD")
        is_us = (symbol in NASDAQ_100) or (not symbol.endswith(".ST") and not is_crypto)
        curr = "$" if (is_crypto or is_us) else "kr"

        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        df["RSI"] = calc_rsi(df["Close"])
        df["ATR"] = calc_atr(df)

        last, prev = df.iloc[-1], df.iloc[-2]
        close = round(float(last["Close"]), 2)
        change_pct = round((close / float(prev["Close"]) - 1) * 100, 2)
        rsi = round(float(last["RSI"]), 1) if not pd.isna(last["RSI"]) else None
        ma50 = round(float(last["MA50"]), 2) if not pd.isna(last["MA50"]) else None
        ma200 = round(float(last["MA200"]), 2) if not pd.isna(last["MA200"]) else None
        atr = float(last["ATR"]) if not pd.isna(last["ATR"]) else close * (0.05 if is_crypto else 0.03)

        name = _display_name(symbol, is_crypto, ticker)
        info = {}
        if not is_crypto:
            try:
                info = ticker.info or {}
            except Exception:
                info = {}

        # Teknisk kontext
        tscore = trend_score(close, ma50, ma200, rsi)
        tlabel, tclass = trend_label(tscore)
        patterns = detect_patterns(df.tail(20))
        vs_ma200 = round((close / ma200 - 1) * 100, 1) if ma200 else None

        # Värdering
        valuation = _valuation(df["Close"].dropna(), close, info, is_crypto)

        # Risk
        closes_1y = df["Close"].tail(252)
        daily = df["Close"].pct_change().dropna().tail(252)
        risk = {
            "week52_high": round(float(closes_1y.max()), 2),
            "week52_low": round(float(closes_1y.min()), 2),
            "volatility_pct": round(float(daily.std() * (252 ** 0.5) * 100), 1) if len(daily) > 5 else None,
            "beta": _num(info.get("beta")),
            "earnings": _next_earnings(ticker) if not is_crypto else None,
            "short": {} if is_crypto else _safe(fetch_short_interest, symbol, name),
        }

        # Nivåkalkyl (för den som ändå vill sätta stop-loss)
        stop = round(close - 3.0 * atr, 2)
        levels = {
            "atr": round(atr, 2), "atr_pct": round(atr / close * 100, 1),
            "stop_suggestion": stop, "stop_pct": round((stop / close - 1) * 100, 1),
            "avanza_query": name or symbol,
        }

        # Historisk edge för strategierna
        edge_summary = {}
        if not is_crypto and len(df) >= 100:
            from src.core.backtest import prep_strategy_signals, simulate_stock_trades
            for s_key in ("dip", "momentum", "trend"):
                df_sig = prep_strategy_signals(df, strategy=s_key)
                _, _, s_stats = simulate_stock_trades(df_sig, strategy=s_key)
                edge_summary[s_key] = {
                    "win_rate": s_stats["win_rate"],
                    "profit_factor": s_stats["profit_factor"],
                    "trades_count": s_stats["trades_count"],
                    "total_return": s_stats["total_return"],
                    "active_signal": bool(df_sig.iloc[-1].get("entry_sig", False)),
                }

        return {
            "symbol": symbol, "name": name, "currency": curr,
            "asset_type": "krypto" if is_crypto else "aktie",
            "close": close, "change_pct": change_pct,
            "summary": _summary(name, tlabel, valuation, is_crypto),
            "valuation": valuation,
            "fundamentals": _fundamentals(info, is_crypto),
            "technical": {
                "trend_score": tscore, "trend_label": tlabel, "trend_class": tclass,
                "rsi": rsi, "ma50": ma50, "ma200": ma200, "vs_ma200_pct": vs_ma200,
                "notes": _tech_notes(close, ma50, ma200, rsi, curr, patterns),
                "patterns": patterns,
            },
            "risk": risk,
            "context": calc_context(symbol, is_crypto, is_us),
            "levels": levels,
            "edge_summary": edge_summary,
        }
    except Exception as e:
        return {"error": f"Fel vid analys av {symbol}: {e}"}


def _safe(fn, *args):
    try:
        return fn(*args) or {}
    except Exception:
        return {}
