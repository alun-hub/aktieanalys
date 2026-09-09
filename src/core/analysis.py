import re
import pandas as pd
import yfinance as yf
from src.core.indicators import calc_rsi, calc_atr
from src.core.patterns import detect_patterns
from src.core.short_interest import fetch_short_interest
from src.core.config import OMXS_50, NASDAQ_100

def search_symbols(query):
    """Söker efter tickers och bolagsnamn via OMX/Nasdaq-listor och Yahoo Finance."""
    query = query.strip()
    if not query:
        return []

    q_lower = query.lower()
    matches = []

    # 1. Sök i våra fördefinierade listor
    for sym, name in {**OMXS_50, **NASDAQ_100}.items():
        if q_lower in sym.lower() or q_lower in name.lower():
            matches.append({"symbol": sym, "name": name, "type": "Stock"})

    # 2. Yahoo Finance sökning för övriga aktier och fonder/krypto
    try:
        r = yf.Search(query, max_results=6).response
        for quote in r.get("quotes", []):
            sym = quote.get("symbol", "")
            name = quote.get("longname") or quote.get("shortname") or sym
            q_type = quote.get("quoteType", "EQUITY")
            if not any(m["symbol"] == sym for m in matches):
                matches.append({"symbol": sym, "name": name, "type": q_type})
    except Exception:
        pass

    return matches[:10]

def resolve_symbol(query):
    """Mappar en söksträng (t.ex. 'investor', 'volvo', 'saab', 'bitcoin') till rätt ticker."""
    q = query.strip()
    if not q:
        return None
    
    # Krypto-alias
    crypto_map = {
        "btc": "BTC-USD", "bitcoin": "BTC-USD",
        "eth": "ETH-USD", "ethereum": "ETH-USD",
        "sol": "SOL-USD", "solana": "SOL-USD",
        "xrp": "XRP-USD", "ripple": "XRP-USD"
    }
    if q.lower() in crypto_map:
        return crypto_map[q.lower()]

    all_tickers = {**OMXS_50, **NASDAQ_100}
    q_upper = q.upper()
    if q_upper in all_tickers:
        return q_upper

    if f"{q_upper}.ST" in all_tickers:
        return f"{q_upper}.ST"

    q_low = q.lower()
    for sym, name in all_tickers.items():
        if q_low == name.lower() or q_low in name.lower() or name.lower() in q_low:
            return sym

    # Fallback via search_symbols
    results = search_symbols(q)
    if results and results[0].get("symbol"):
        return results[0]["symbol"]

    return q_upper

_market_overview_cache = {"data": None, "ts": 0.0}

def get_market_overview():
    """Hämtar snabb överblick för de viktigaste indexen och Bitcoin."""
    import time
    global _market_overview_cache
    now = time.time()
    if _market_overview_cache["data"] and (now - _market_overview_cache["ts"] < 300):
        return _market_overview_cache["data"]

    instruments = [
        ("^OMX", "OMXS30"),
        ("^NDX", "Nasdaq 100"),
        ("^GSPC", "S&P 500"),
        ("BTC-USD", "Bitcoin")
    ]
    overview = []
    for sym, name in instruments:
        try:
            df = yf.download(sym, period="5d", interval="1d", progress=False)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            c_today = float(df.iloc[-1]["Close"])
            c_prev = float(df.iloc[-2]["Close"])
            chg = round(((c_today / c_prev) - 1) * 100, 2)
            overview.append({
                "symbol": sym,
                "name": name,
                "price": round(c_today, 2),
                "change_pct": chg
            })
        except Exception:
            pass

    _market_overview_cache = {"data": overview, "ts": now}
    return overview

def analyze_any_stock(symbol):
    """Komplett djupanalys av valfri aktie med teknisk status, insynshandel och Avanza-nivåer."""
    resolved = resolve_symbol(symbol)
    if resolved:
        symbol = resolved
    symbol = symbol.strip().upper()
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y")
        if df.empty or len(df) < 30:
            return {"error": f"Kunde inte hämta kursdata för {symbol}. Prova att ange fullständig ticker (t.ex. INVE-B.ST eller AAPL)."}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
        df.index = df.index.normalize()

        # Beräkna indikatorer
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        df["RSI"] = calc_rsi(df["Close"])
        df["ATR"] = calc_atr(df)

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = round(float(last["Close"]), 2)
        change_pct = round(((close / float(prev["Close"])) - 1) * 100, 2)
        rsi = round(float(last["RSI"]), 1) if not pd.isna(last["RSI"]) else None
        rsi_prev = round(float(prev["RSI"]), 1) if not pd.isna(prev["RSI"]) else None
        ma50 = round(float(last["MA50"]), 2) if not pd.isna(last["MA50"]) else None
        ma200 = round(float(last["MA200"]), 2) if not pd.isna(last["MA200"]) else None
        atr = float(last["ATR"]) if not pd.isna(last["ATR"]) else close * 0.03

        # Bolagsnamn
        company_name = symbol
        for s, n in {**OMXS_50, **NASDAQ_100}.items():
            if s == symbol:
                company_name = n
                break
        if company_name == symbol:
            try:
                info = ticker.info
                company_name = info.get("longName") or info.get("shortName") or symbol
            except Exception:
                pass

        # Candlestick-mönster senaste 20 dagarna
        patterns = detect_patterns(df.tail(20))

        # Blankningsdata
        short_data = fetch_short_interest(symbol, company_name)

        # ── Teknisk Poängsättning ──
        score = 50
        bull_factors = []
        bear_factors = []

        # 1. Långsiktig Trend (MA200)
        if ma200:
            if close > ma200:
                score += 20
                bull_factors.append(f"Kursen ligger över 200-dagars medelvärde ({ma200} kr) – långsiktigt positiv trend.")
            else:
                score -= 20
                bear_factors.append(f"Kursen handlas under 200-dagars medelvärde ({ma200} kr) – långsiktig svaghet.")

        # 2. Medellång trend (MA50) & Golden Cross
        if ma50:
            if close > ma50:
                score += 15
                bull_factors.append(f"Kursen är över 50-dagars medelvärde ({ma50} kr).")
            else:
                score -= 15
                bear_factors.append(f"Kursen har brutit ned under 50-dagars medelvärde ({ma50} kr).")

            if ma200 and ma50 > ma200:
                score += 10
                bull_factors.append("Golden Cross (MA50 över MA200) indikerar etablerad bull-trend.")

        # 3. Momentum & RSI
        if rsi:
            if rsi < 40 and rsi_prev and rsi > rsi_prev:
                score += 25
                bull_factors.append(f"RSI har vänt upp från översålt läge ({rsi}) – god risk/reward för studs.")
            elif rsi > 72:
                score -= 15
                bear_factors.append(f"RSI är överköpt ({rsi}) – ökad risk för kortsiktig vinsthemtagning.")
            elif 45 <= rsi <= 65:
                score += 15
                bull_factors.append(f"RSI ({rsi}) befinner sig i hälsosam uppåtgående expansionszon.")

        # 4. Blankningsrisk
        if short_data.get("risk") == "Hög":
            score -= 15
            bear_factors.append(f"Hög blankning ({short_data.get('short_pct')}%) – institutioner spekulerar i nedgång.")
        elif short_data.get("short_pct", 0) < 1.0:
            bull_factors.append("Minimal blankning – lågt institutionellt säljtryck.")

        # 5. Candlestick-mönster
        if patterns:
            last_p = patterns[-1]
            if last_p.get("bullish") is True:
                score += 10
                bull_factors.append(f"Candlestick-mönster: {last_p['pattern']} ({last_p['desc']})")
            elif last_p.get("bullish") is False:
                score -= 10
                bear_factors.append(f"Candlestick-mönster: {last_p['pattern']} ({last_p['desc']})")

        score = max(5, min(95, score))

        # Beslutskategori
        if score >= 70:
            decision = "KÖPVÄRD (STARK SETUP)"
            decision_color = "var(--grn)"
        elif score >= 50:
            decision = "BEVAKA (NEUTRAL)"
            decision_color = "var(--am)"
        else:
            decision = "UNDVIK / AVVAKTA"
            decision_color = "var(--red)"

        # ── Avanza Expert Orderguide & Riskhantering ──
        # Stop loss sätts utanför normalt brus (3.0 x ATR)
        stop_loss = round(close - (3.0 * atr), 2)
        risk_per_share = round(close - stop_loss, 2)
        take_profit_1 = round(close + (1.8 * risk_per_share), 2) # 50% vinsthemtagning
        take_profit_2 = round(close + (3.2 * risk_per_share), 2) # Låta vinnaren löpa

        avanza_recipe = {
            "symbol": symbol,
            "name": company_name,
            "buy_limit": round(close * 1.003, 2),
            "stop_loss_trigger": stop_loss,
            "stop_loss_limit": round(stop_loss * 0.995, 2),
            "take_profit_1": take_profit_1,
            "take_profit_2": take_profit_2,
            "risk_reward_ratio": "1 : 1.8",
            "courtage_tip": "Välj Avanza Mini om ordern är under 15 000 kr, annars Avanza Small för lägst avgift."
        }

        return {
            "symbol": symbol,
            "name": company_name,
            "close": close,
            "change_pct": change_pct,
            "rsi": rsi,
            "ma50": ma50,
            "ma200": ma200,
            "score": score,
            "decision": decision,
            "decision_color": decision_color,
            "bull_factors": bull_factors,
            "bear_factors": bear_factors,
            "patterns": patterns,
            "short_data": short_data,
            "avanza_recipe": avanza_recipe
        }
    except Exception as e:
        return {"error": f"Fel vid analys av {symbol}: {str(e)}"}
