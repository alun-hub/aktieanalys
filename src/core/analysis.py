import re
import time
import datetime
import pandas as pd
import yfinance as yf
from src.core.indicators import calc_rsi, calc_atr, calculate_indicators
from src.core.patterns import detect_patterns
from src.core.short_interest import fetch_short_interest
from src.core.signals import trend_score, trend_label
from src.core.config import OMXS_50, NASDAQ_100, POPULAR_ETFS, POPULAR_SWEDISH_FUNDS

CRYPTO_NAMES = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "XRP-USD": "XRP", "BNB-USD": "BNB", "ADA-USD": "Cardano",
    "DOGE-USD": "Dogecoin", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink",
    "DOT-USD": "Polkadot", "NEAR-USD": "NEAR Protocol", "SUI20947-USD": "Sui",
}


def _normalize_query(text):
    text = (text or "").strip().lower()
    text = text.replace("å", "a").replace("ä", "a").replace("ö", "o")
    text = text.replace("é", "e")
    return text


def search_symbols(query):
    """Söker efter tickers och bolagsnamn via fonder, ETF:er, aktier, krypto och Yahoo Finance."""
    query = query.strip()
    if not query:
        return []

    norm_q = _normalize_query(query)
    matches = []

    # 1. Populära svenska fonder (Länsförsäkringar, Avanza, Spiltan, AMF etc.)
    for key, item in POPULAR_SWEDISH_FUNDS.items():
        name = item["name"]
        norm_name = _normalize_query(name)
        aliases = [_normalize_query(a) for a in item.get("aliases", [])]
        if norm_q in norm_name or any(norm_q in a or a in norm_q for a in aliases):
            matches.append({
                "symbol": f"MANUAL:{key}",
                "name": name,
                "type": "Fond",
                "fee_pct": item.get("fee_pct", 0.0),
                "region": item.get("region", "Global")
            })

    # 2. Kurerade ETF:er (svenska & europeiska UCITS)
    for sym, item in POPULAR_ETFS.items():
        name = item["name"]
        norm_name = _normalize_query(name)
        norm_sym = _normalize_query(sym)
        if norm_q in norm_sym or norm_q in norm_name:
            matches.append({
                "symbol": sym,
                "name": name,
                "type": "ETF",
                "region": item.get("region", "Övrigt")
            })

    # 3. OMXS & Nasdaq aktier
    for sym, name in {**OMXS_50, **NASDAQ_100}.items():
        norm_name = _normalize_query(name)
        norm_sym = _normalize_query(sym)
        if norm_q in norm_sym or norm_q in norm_name:
            matches.append({"symbol": sym, "name": name, "type": "Stock"})

    # 4. Krypto
    for sym, name in CRYPTO_NAMES.items():
        norm_name = _normalize_query(name)
        norm_sym = _normalize_query(sym)
        if norm_q in norm_sym or norm_q in norm_name:
            matches.append({"symbol": sym, "name": name, "type": "Krypto"})

    # 5. Yahoo Finance sökning för globala ETF:er, utländska fonder och aktier
    try:
        r = yf.Search(query, max_results=15).response
        for quote in r.get("quotes", []):
            sym = quote.get("symbol", "")
            name = quote.get("longname") or quote.get("shortname") or sym
            q_type = quote.get("quoteType", "EQUITY")
            type_label = "ETF" if q_type == "ETF" else ("Fond" if q_type == "MUTUALFUND" else "Aktie")
            if sym and not any(m["symbol"] == sym for m in matches):
                matches.append({"symbol": sym, "name": name, "type": type_label})
    except Exception:
        pass

    return matches[:15]


def resolve_symbol(query):
    """Mappar en söksträng (t.ex. 'investor', 'volvo', 'bitcoin', 'vwce', 'lf global') till rätt ticker."""
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
    norm_q = _normalize_query(q)

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
    if q_upper in POPULAR_ETFS:
        return q_upper
    if f"{q_upper}.ST" in POPULAR_ETFS:
        return f"{q_upper}.ST"

    # Exakta namnträffar går före delsträngsträffar, oavsett kategori, så att t.ex.
    # "handelsbanken" ger aktien SHB-A.ST och inte en fond som råkar innehålla ordet.
    for sym, name in all_tickers.items():
        if norm_q == _normalize_query(name):
            return sym
    for sym, item in POPULAR_ETFS.items():
        if norm_q == _normalize_query(item["name"]):
            return sym
    for key, item in POPULAR_SWEDISH_FUNDS.items():
        norm_name = _normalize_query(item["name"])
        aliases = [_normalize_query(a) for a in item.get("aliases", [])]
        if norm_q == norm_name or any(norm_q == a for a in aliases):
            return f"MANUAL:{key}"

    # Delsträngsträffar: aktier/ETF:er före fonder, eftersom bolagsnamn ofta är en
    # delsträng av ett fondnamn med samma varumärke (t.ex. "Handelsbanken Global Småbolag").
    for sym, name in all_tickers.items():
        norm_name = _normalize_query(name)
        if norm_q in norm_name or norm_name in norm_q:
            return sym
    for sym, item in POPULAR_ETFS.items():
        norm_name = _normalize_query(item["name"])
        if norm_q in norm_name or norm_name in norm_q:
            return sym
    for key, item in POPULAR_SWEDISH_FUNDS.items():
        norm_name = _normalize_query(item["name"])
        aliases = [_normalize_query(a) for a in item.get("aliases", [])]
        if norm_q in norm_name or any(norm_q in a for a in aliases):
            return f"MANUAL:{key}"

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
            if "Close" in df.columns:
                df = df.dropna(subset=["Close"])
            if len(df) < 2:
                continue
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
    pctile = None
    if not closes.empty:
        lo, hi = float(closes.min()), float(closes.max())
        if hi > lo and close is not None:
            val = _num((close - lo) / (hi - lo))
            if val is not None:
                pctile = round(val, 2)
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


def _tech_notes(close, ma50, ma200, rsi, curr, patterns, ema20=None, ma200_slope=None, macd_hist=None, bb=None):
    notes = []
    if ma200:
        slope_str = ""
        if ma200_slope is not None:
            slope_str = ", lutning uppåt (sund långsiktig bas)" if ma200_slope > 0 else ", lutning nedåt (förhöjd risk)"
        notes.append(f"{'Över' if close > ma200 else 'Under'} 200-dagars medelvärde ({ma200:g} {curr}{slope_str}) – "
                     f"{'långsiktigt positivt' if close > ma200 else 'långsiktig svaghet'}.")
    if ema20:
        notes.append(f"{'Över' if close > ema20 else 'Under'} kortsiktiga trendstödet EMA20 ({ema20:g} {curr}).")
    if ma50 and ma200:
        notes.append("Golden cross (MA50 över MA200)." if ma50 > ma200 else "Death cross (MA50 under MA200).")
    if macd_hist is not None:
        notes.append(f"MACD visar {'positivt' if macd_hist > 0 else 'negativt'} momentum ({macd_hist:+.2f}).")
    if bb:
        if bb.get("squeeze"):
            notes.append("Bollinger Squeeze: Volatiliteten är extremt komprimerad – förberedelse inför potentiellt kraftigt utbrott.")
        elif bb.get("upper") and close > bb["upper"]:
            notes.append(f"Handlas över övre Bollinger-bandet ({bb['upper']:g} {curr}) – starkt momentum men kortsiktigt överköpt mot volatiliteten.")
        elif bb.get("lower") and close < bb["lower"]:
            notes.append(f"Handlas under nedre Bollinger-bandet ({bb['lower']:g} {curr}) – kortsiktigt översåld mot volatiliteten.")
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


def generate_recommendation(symbol, close, ma50, ma200, rsi, atr, tscore, valuation, info, edge_summary, is_crypto):
    """Skapar en konkret och modig köp/sälj/behåll-rekommendation med tidshorisont baserad på teknisk analys och värdering."""
    rec_key = (info.get("recommendationKey") or "").lower() if info else ""
    target_analyst = info.get("targetMedianPrice") or info.get("targetMeanPrice") if info else None
    atr_val = atr if (atr and atr > 0) else close * 0.03

    # 1. Kontrollera aktiva signaler från strategimodellerna (dip, momentum, trend)
    if edge_summary:
        if edge_summary.get("dip", {}).get("active_signal"):
            target = round(close + 3.2 * atr_val, 2)
            stop = round(close - 2.2 * atr_val, 2)
            return {
                "action": "Köp",
                "badge": "buy",
                "horizon": "Kort sikt (2–4 veckor)",
                "target_price": target,
                "stop_loss": stop,
                "strategy": "Kvalitets-dipp",
                "rationale": "Aktiv köpsignal i dipp-strategin. Aktien rekylerar i en sund upptrend och visar tydliga tecken på vändning med god historisk träffsäkerhet.",
            }
        if edge_summary.get("momentum", {}).get("active_signal"):
            target = round(close + 4.5 * atr_val, 2)
            stop = round(close - 2.5 * atr_val, 2)
            return {
                "action": "Köp",
                "badge": "buy",
                "horizon": "Kort/Medellång sikt (3–6 veckor)",
                "target_price": target,
                "stop_loss": stop,
                "strategy": "Momentum & Utbrott",
                "rationale": "Aktivt momentumutbrott med ökad volym och positiv trendhierarki (Close > MA50 > MA200).",
            }
        if edge_summary.get("trend", {}).get("active_signal"):
            target = round(close + 6.0 * atr_val, 2)
            stop = round(close - 3.0 * atr_val, 2)
            return {
                "action": "Köp",
                "badge": "buy",
                "horizon": "Lång sikt (6–12 månader)",
                "target_price": target,
                "stop_loss": stop,
                "strategy": "Långsiktig Trendföljare",
                "rationale": "Stark långsiktig trendföljarsignal med etablerat Golden Cross över 200-dagars medelvärde.",
            }

    # 2. Krypto
    if is_crypto:
        if tscore >= 60:
            return {
                "action": "Köp",
                "badge": "buy",
                "horizon": "Kortsiktig swing (1–4 veckor)",
                "target_price": round(close + 3.0 * atr_val, 2),
                "stop_loss": round(close - 2.5 * atr_val, 2),
                "strategy": "Krypto Momentum",
                "rationale": "Positivt momentum och stigande trend över glidande medelvärden.",
            }
        elif tscore <= 40:
            return {
                "action": "Sälj",
                "badge": "sell",
                "horizon": "Kliv av omgående",
                "target_price": round(close - 3.0 * atr_val, 2),
                "stop_loss": round(close + 2.0 * atr_val, 2),
                "strategy": "Teknisk Riskminimering",
                "rationale": "Svagt momentum och fallande trend under medelvärden i högvolatil tillgång.",
            }
        else:
            return {
                "action": "Behåll",
                "badge": "hold",
                "horizon": "Avvakta (1–2 veckor)",
                "target_price": round(close + 2.0 * atr_val, 2),
                "stop_loss": round(close - 2.0 * atr_val, 2),
                "strategy": "Neutral konsolidering",
                "rationale": "Konsoliderar i sidledes kanal utan tydlig trendriktning.",
            }

    # 3. Aktier – teknisk trend + värdering och analytikerstöd
    v_verdict = (valuation.get("verdict") or "").lower() if valuation else ""

    if tscore >= 65:
        if rec_key in ("sell", "underperform") or (rsi and rsi > 75):
            return {
                "action": "Behåll",
                "badge": "hold",
                "horizon": "Bevaka MA50 (1–2 månader)",
                "target_price": round(target_analyst, 2) if target_analyst else round(close + 2.0 * atr_val, 2),
                "stop_loss": round(close - 2.0 * atr_val, 2),
                "strategy": "Vinstsäkring / Konsolidering",
                "rationale": "Stark upptrend men kortsiktigt överköpt eller svag analytikersyn. Behåll med uppflyttad stop-loss men avvakta nya köp.",
            }
        target = round(target_analyst, 2) if (target_analyst and target_analyst > close) else round(close + 4.0 * atr_val, 2)
        stop = round(close - 2.5 * atr_val, 2)
        return {
            "action": "Köp",
            "badge": "buy",
            "horizon": "Medellång sikt (2–6 månader)",
            "target_price": target,
            "stop_loss": stop,
            "strategy": "Teknisk upptrend",
            "rationale": "Stark teknisk upptrend ovanför MA50 och MA200 med bekräftat positivt momentum.",
        }

    if tscore >= 45:
        if rec_key in ("strong_buy", "buy") or v_verdict in ("lågt", "rimligt"):
            target = round(target_analyst, 2) if (target_analyst and target_analyst > close) else round(close + 4.0 * atr_val, 2)
            stop = round(close - 2.5 * atr_val, 2)
            return {
                "action": "Köp",
                "badge": "buy",
                "horizon": "Lång sikt (6–12 månader)",
                "target_price": target,
                "stop_loss": stop,
                "strategy": "Ackumulera / Basbygge",
                "rationale": "Stabil konsolidering med attraktiv värdering och starkt analytikerstöd. Bra ingångsläge för en långsiktig position.",
            }
        else:
            return {
                "action": "Behåll",
                "badge": "hold",
                "horizon": "Avvakta utbrott (1–3 månader)",
                "target_price": round(close + 2.5 * atr_val, 2),
                "stop_loss": round(close - 2.5 * atr_val, 2),
                "strategy": "Konsolidering",
                "rationale": "Neutral trend i intervallhandel. Behåll befintligt innehav med stop-loss under MA200 men avvakta med nya köp.",
            }

    # tscore < 45
    if rec_key in ("strong_buy", "buy") and v_verdict in ("lågt", "rimligt"):
        return {
            "action": "Behåll",
            "badge": "hold",
            "horizon": "1–3 månader (Invänta bottenkänning)",
            "target_price": round(target_analyst, 2) if target_analyst else round(close + 3.0 * atr_val, 2),
            "stop_loss": round(close - 3.0 * atr_val, 2),
            "strategy": "Kvalitetsbolag i motvind",
            "rationale": "Kortsiktig rekyl under medelvärden men stark fundamental bas och positiv analytikerkonsensus motiverar att behålla positionen.",
        }

    return {
        "action": "Sälj",
        "badge": "sell",
        "horizon": "Kliv av omgående / Avvakta",
        "target_price": round(close - 3.0 * atr_val, 2),
        "stop_loss": round(close + 2.0 * atr_val, 2),
        "strategy": "Teknisk nedåttrend",
        "rationale": "Svag teknisk trend under MA50 och MA200 med fallande kurser. Sälj eller minska positionen för att skydda kapitalet.",
    }


def _summary(name, tlabel, valuation, rec, is_crypto):
    action_str = f"Rekommendation: {rec['action'].upper()} ({rec['horizon'].lower()})."
    desc = f"{name} ligger i en {tlabel.lower()}"
    if valuation.get("verdict") not in (None, "okänt"):
        desc += f" och värderingen ser {valuation['verdict']} ut."
    else:
        desc += "."
    parts = [action_str, desc, rec["rationale"]]
    if is_crypto:
        parts.append("Krypto är en mycket volatil tillgångsklass.")
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Bolagsanalys
# ─────────────────────────────────────────────────────────────────────────────

_analysis_cache = {}
_ANALYSIS_TTL = 900  # 15 minuter cache


def analyze_any_stock(symbol):
    """Bolags-/tillgångsanalys: vad det är och hur det är värderat först, teknisk trend som kontext."""
    resolved = resolve_symbol(symbol)
    symbol = (resolved or symbol).strip().upper()
    now = time.time()
    hit = _analysis_cache.get(symbol)
    if hit and (now - hit[0] < _ANALYSIS_TTL):
        return hit[1]
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5y", auto_adjust=True)
        if df.empty:
            return {"error": f"Kunde inte hämta kursdata för {symbol}. "
                             "Prova fullständig ticker (t.ex. INVE-B.ST, AAPL eller BTC-USD)."}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if "Close" in df.columns:
            df = df.dropna(subset=["Close"]).copy()
        if df.empty or len(df) < 30:
            return {"error": f"Kunde inte hämta kursdata för {symbol}. "
                             "Prova fullständig ticker (t.ex. INVE-B.ST, AAPL eller BTC-USD)."}

        df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
        df.index = df.index.normalize()

        is_crypto = symbol.endswith("-USD")
        is_us = (symbol in NASDAQ_100) or (not symbol.endswith(".ST") and not is_crypto)
        curr = "$" if (is_crypto or is_us) else "kr"

        df = calculate_indicators(df)

        last, prev = df.iloc[-1], df.iloc[-2]
        close = round(float(last["Close"]), 2)
        prev_close = float(prev["Close"]) if ("Close" in prev and not pd.isna(prev["Close"])) else close
        change_pct = round((close / prev_close - 1) * 100, 2) if prev_close and prev_close > 0 else 0.0
        rsi = round(float(last["RSI"]), 1) if not pd.isna(last["RSI"]) else None
        ma50 = round(float(last["MA50"]), 2) if not pd.isna(last["MA50"]) else None
        ma200 = round(float(last["MA200"]), 2) if not pd.isna(last["MA200"]) else None
        ema20 = round(float(last["EMA20"]), 2) if ("EMA20" in last and not pd.isna(last["EMA20"])) else None
        atr = float(last["ATR"]) if not pd.isna(last["ATR"]) else close * (0.05 if is_crypto else 0.03)

        macd = round(float(last["MACD"]), 2) if ("MACD" in last and not pd.isna(last["MACD"])) else None
        macd_sig = round(float(last["MACD_Signal"]), 2) if ("MACD_Signal" in last and not pd.isna(last["MACD_Signal"])) else None
        macd_hist = round(float(last["MACD_Hist"]), 2) if ("MACD_Hist" in last and not pd.isna(last["MACD_Hist"])) else None

        bb_u = round(float(last["BB_Upper"]), 2) if ("BB_Upper" in last and not pd.isna(last["BB_Upper"])) else None
        bb_m = round(float(last["BB_Middle"]), 2) if ("BB_Middle" in last and not pd.isna(last["BB_Middle"])) else None
        bb_l = round(float(last["BB_Lower"]), 2) if ("BB_Lower" in last and not pd.isna(last["BB_Lower"])) else None
        bb_bw = round(float(last["BB_Bandwidth"]) * 100, 1) if ("BB_Bandwidth" in last and not pd.isna(last["BB_Bandwidth"])) else None

        bb_squeeze = False
        if "BB_Bandwidth" in df.columns and len(df) >= 40:
            tail_bw = df["BB_Bandwidth"].dropna().tail(126)
            if len(tail_bw) >= 20 and not pd.isna(last["BB_Bandwidth"]):
                bb_squeeze = bool(last["BB_Bandwidth"] <= tail_bw.quantile(0.20))

        bb_dict = {
            "upper": bb_u, "middle": bb_m, "lower": bb_l,
            "bandwidth_pct": bb_bw, "squeeze": bb_squeeze
        }

        ma200_slope = None
        if len(df) >= 20 and not pd.isna(df["MA200"].iloc[-20]) and ma200 is not None:
            ma200_slope = ma200 - float(df["MA200"].iloc[-20])

        name = _display_name(symbol, is_crypto, ticker)
        info = {}
        if not is_crypto:
            try:
                info = ticker.info or {}
            except Exception:
                info = {}

        # Teknisk kontext
        tscore = trend_score(close, ma50, ma200, rsi, ma200_slope=ma200_slope, ema20=ema20, macd_hist=macd_hist)
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

        rec = generate_recommendation(
            symbol=symbol, close=close, ma50=ma50, ma200=ma200, rsi=rsi,
            atr=atr, tscore=tscore, valuation=valuation, info=info,
            edge_summary=edge_summary, is_crypto=is_crypto
        )

        result = {
            "symbol": symbol, "name": name, "currency": curr,
            "asset_type": "krypto" if is_crypto else "aktie",
            "close": close, "change_pct": change_pct,
            "recommendation": rec,
            "summary": _summary(name, tlabel, valuation, rec, is_crypto),
            "valuation": valuation,
            "fundamentals": _fundamentals(info, is_crypto),
            "technical": {
                "trend_score": tscore, "trend_label": tlabel, "trend_class": tclass,
                "rsi": rsi, "ma50": ma50, "ma200": ma200, "ema20": ema20,
                "vs_ma200_pct": vs_ma200,
                "ma200_slope": round(ma200_slope, 2) if ma200_slope is not None else None,
                "macd": {
                    "macd": macd, "signal": macd_sig, "hist": macd_hist,
                    "status": "bullish" if (macd_hist and macd_hist > 0) else "bearish"
                },
                "bollinger": bb_dict,
                "notes": _tech_notes(close, ma50, ma200, rsi, curr, patterns,
                                     ema20=ema20, ma200_slope=ma200_slope,
                                     macd_hist=macd_hist, bb=bb_dict),
                "patterns": patterns,
            },
            "risk": risk,
            "context": calc_context(symbol, is_crypto, is_us),
            "levels": levels,
            "edge_summary": edge_summary,
        }
        _analysis_cache[symbol] = (now, result)
        return result
    except Exception as e:
        return {"error": f"Fel vid analys av {symbol}: {e}"}


def _safe(fn, *args):
    try:
        return fn(*args) or {}
    except Exception:
        return {}
