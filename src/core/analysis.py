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
    
    # Krypto-alias & direkta par
    crypto_aliases = {
        "btc": "BTC-USD", "bitcoin": "BTC-USD", "btc-usd": "BTC-USD",
        "eth": "ETH-USD", "ethereum": "ETH-USD", "eth-usd": "ETH-USD",
        "sol": "SOL-USD", "solana": "SOL-USD", "sol-usd": "SOL-USD",
        "xrp": "XRP-USD", "ripple": "XRP-USD", "xrp-usd": "XRP-USD",
        "bnb": "BNB-USD", "bnb-usd": "BNB-USD",
        "ada": "ADA-USD", "cardano": "ADA-USD", "ada-usd": "ADA-USD",
        "doge": "DOGE-USD", "dogecoin": "DOGE-USD", "doge-usd": "DOGE-USD",
        "avax": "AVAX-USD", "avalanche": "AVAX-USD", "avax-usd": "AVAX-USD",
        "link": "LINK-USD", "chainlink": "LINK-USD", "link-usd": "LINK-USD",
        "dot": "DOT-USD", "polkadot": "DOT-USD", "dot-usd": "DOT-USD",
        "near": "NEAR-USD", "near-usd": "NEAR-USD",
        "sui": "SUI-USD", "sui-usd": "SUI-USD"
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
    """Komplett djupanalys av valfri aktie eller krypto med teknisk status och Avanza-nivåer."""
    resolved = resolve_symbol(symbol)
    if resolved:
        symbol = resolved
    symbol = symbol.strip().upper()
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y")
        if df.empty or len(df) < 30:
            return {"error": f"Kunde inte hämta kursdata för {symbol}. Prova att ange fullständig ticker (t.ex. INVE-B.ST, AAPL eller BTC-USD)."}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
        df.index = df.index.normalize()

        is_crypto = symbol.endswith("-USD")
        is_us = (symbol in NASDAQ_100) or (not symbol.endswith(".ST") and not is_crypto)
        curr = "$" if (is_crypto or is_us) else "kr"

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
        atr = float(last["ATR"]) if not pd.isna(last["ATR"]) else close * (0.05 if is_crypto else 0.03)

        # Bolags- eller tillgångsnamn
        company_name = symbol
        for s, n in {**OMXS_50, **NASDAQ_100}.items():
            if s == symbol:
                company_name = n
                break
        if is_crypto:
            crypto_names = {
                "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
                "XRP-USD": "XRP", "BNB-USD": "BNB", "ADA-USD": "Cardano",
                "DOGE-USD": "Dogecoin", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink",
                "DOT-USD": "Polkadot", "NEAR-USD": "NEAR Protocol", "SUI-USD": "Sui"
            }
            company_name = crypto_names.get(symbol, symbol.replace("-USD", ""))
        elif company_name == symbol:
            try:
                info = ticker.info
                company_name = info.get("longName") or info.get("shortName") or symbol
            except Exception:
                pass

        # Candlestick-mönster senaste 20 dagarna
        patterns = detect_patterns(df.tail(20))

        # Blankningsdata (endast aktier)
        short_data = {}
        if not is_crypto:
            try:
                short_data = fetch_short_interest(symbol, company_name)
            except Exception:
                short_data = {}

        # ── Teknisk Poängsättning ──
        score = 50
        bull_factors = []
        bear_factors = []

        # 1. Långsiktig Trend (MA200)
        if ma200:
            if close > ma200:
                score += 20
                bull_factors.append(f"Kursen ligger över 200-dagars medelvärde ({ma200} {curr}) – långsiktigt positiv trend.")
            else:
                score -= 20
                bear_factors.append(f"Kursen handlas under 200-dagars medelvärde ({ma200} {curr}) – långsiktig svaghet.")

        # 2. Medellång trend (MA50) & Golden Cross
        if ma50:
            if close > ma50:
                score += 15
                bull_factors.append(f"Kursen är över 50-dagars medelvärde ({ma50} {curr}).")
            else:
                score -= 15
                bear_factors.append(f"Kursen har brutit ned under 50-dagars medelvärde ({ma50} {curr}).")

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

        # 4. Blankningsrisk / Marknadsstruktur
        if is_crypto:
            bull_factors.append("24/7 global marknadslikviditet och decentraliserad orderbok.")
        elif short_data and isinstance(short_data, dict):
            short_pct = short_data.get("short_pct")
            if short_data.get("risk") == "Hög":
                score -= 15
                bear_factors.append(f"Hög blankning ({short_pct}%) – institutioner spekulerar i nedgång.")
            elif short_pct is not None and short_pct < 1.0:
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
        take_profit_1 = round(close + (1.8 * risk_per_share), 2)
        take_profit_2 = round(close + (3.2 * risk_per_share), 2)

        if is_crypto:
            clean_sym = symbol.replace("-USD", "")
            courtage_tip = f"Kryptotillgång: Handla via Avanza ISK med certifikat (t.ex. {clean_sym} ZERO utan avgift eller Virtune) för schablonbeskattning."
            avanza_query = clean_sym
        elif is_us:
            courtage_tip = "USA-aktie: Handla med Avanza Mini/Small och tänk på valutaväxling (0.25%)."
            avanza_query = company_name or symbol
        else:
            courtage_tip = "Svensk aktie: Välj Avanza Mini om ordern är under 15 000 kr, annars Avanza Small."
            avanza_query = company_name or symbol

        avanza_recipe = {
            "symbol": symbol,
            "name": company_name,
            "currency": curr,
            "buy_limit": round(close * 1.003, 2),
            "stop_loss_trigger": stop_loss,
            "stop_loss_limit": round(stop_loss * 0.995, 2),
            "take_profit_1": take_profit_1,
            "take_profit_2": take_profit_2,
            "risk_reward_ratio": "1 : 1.8",
            "courtage_tip": courtage_tip,
            "avanza_query": avanza_query
        }

        confluence = calc_confluence(symbol, score, short_data, is_crypto, is_us, ticker)

        return {
            "symbol": symbol,
            "name": company_name,
            "currency": curr,
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
            "confluence": confluence,
            "earnings": confluence.get("earnings"),
            "avanza_recipe": avanza_recipe
        }
    except Exception as e:
        return {"error": f"Fel vid analys av {symbol}: {str(e)}"}


def calc_confluence(symbol, tech_score, short_data, is_crypto, is_us, ticker_obj):
    """Beräknar ett samlat konfluens-score (0-100) som väger samman teknik, insyn, kongress och rapportkalender."""
    confluence_factors = []
    # Baspoäng från teknisk setup (max 45p)
    conf_score = int(tech_score * 0.45)
    insider_buys = []
    congress_buys = []
    earnings_info = None

    # 1. Insynskonfluens (Sverige - Finansinspektionen)
    if not is_crypto and not is_us:
        try:
            from src.core.insider import get_insider_buys_for_symbol
            insider_buys = get_insider_buys_for_symbol(symbol, days=60)
            if insider_buys:
                tot_sek = sum(t.get("amount", 0) for t in insider_buys)
                latest = insider_buys[0]
                conf_score += 25
                confluence_factors.append({
                    "type": "insider",
                    "title": "Insynsköp bekräftar",
                    "desc": f"Insynspersoner har köpt aktier för {tot_sek:,.0f} kr senaste 60 dagarna ({latest.get('insider', '')}, {latest.get('role', '')}).",
                    "positive": True
                })
        except Exception:
            pass

    # 2. Kongresskonfluens (USA - Senate & House)
    if is_us and not is_crypto:
        try:
            from src.core.congress import scan_congress_trades
            cg = scan_congress_trades(months=3, txn_type="buy")
            congress_buys = [t for t in cg.get("trades", []) if t.get("ticker") == symbol]
            if congress_buys:
                conf_score += 20
                names = ", ".join(list(set(t["politician"] for t in congress_buys[:3])))
                confluence_factors.append({
                    "type": "congress",
                    "title": "Kongressköp (USA)",
                    "desc": f"Amerikanska politiker ({names}) har rapporterat köp i bolaget.",
                    "positive": True
                })
        except Exception:
            pass

    # 3. Blankningssituation
    if not is_crypto and short_data and isinstance(short_data, dict):
        short_pct = short_data.get("short_pct")
        if short_pct is not None:
            if short_pct < 1.0:
                conf_score += 15
                confluence_factors.append({
                    "type": "short",
                    "title": "Minimal blankning",
                    "desc": f"Endast {short_pct}% blankat. Institutionellt säljtryck saknas.",
                    "positive": True
                })
            elif short_pct > 5.0 and tech_score >= 60:
                conf_score += 15
                confluence_factors.append({
                    "type": "short_squeeze",
                    "title": "Short Squeeze Potential",
                    "desc": f"Hög blankning ({short_pct}%) kombinerat med utbrott ökar chansen för squeeze.",
                    "positive": True
                })

    # 4. Krypto marknadsstruktur
    if is_crypto:
        conf_score += 20
        confluence_factors.append({
            "type": "crypto",
            "title": "Hög likviditet & ETF-flöden",
            "desc": "Global handel med växande institutionellt kapital.",
            "positive": True
        })

    # 5. Rapportkalender (Earnings Guard)
    if not is_crypto and ticker_obj:
        try:
            cal = ticker_obj.calendar
            if cal and "Earnings Date" in cal:
                ed_list = cal.get("Earnings Date")
                if ed_list and len(ed_list) > 0:
                    import datetime
                    next_ed = ed_list[0]
                    if isinstance(next_ed, (datetime.date, datetime.datetime)):
                        d_val = next_ed.date() if isinstance(next_ed, datetime.datetime) else next_ed
                        days_until = (d_val - datetime.date.today()).days
                        if 0 <= days_until <= 14:
                            conf_score -= 25  # Riskavdrag: Ta aldrig ny position precis före rapport!
                            earnings_info = {
                                "date": str(d_val),
                                "days_until": days_until,
                                "warning": True,
                                "message": f"Kvartalsrapport om {days_until} dagar ({d_val}). Risk för gap nedåt vid rapportmiss!"
                            }
                            confluence_factors.append({
                                "type": "earnings_warning",
                                "title": "⚠️ Rapportvarning",
                                "desc": f"Kvartalsrapport om {days_until} dagar ({d_val}). Ökad risk – avråder från aggressivt utbrottsköp före rapporten.",
                                "positive": False
                            })
                        elif days_until > 14:
                            earnings_info = {
                                "date": str(d_val),
                                "days_until": days_until,
                                "warning": False,
                                "message": f"Nästa rapport: {d_val} ({days_until} dagar kvar)."
                            }
        except Exception:
            pass

    conf_score = max(5, min(99, conf_score))
    if conf_score >= 80:
        conf_label = "SUPER-KONFLUENS"
        conf_badge = "badge-grn"
    elif conf_score >= 65:
        conf_label = "STARK KONFLUENS"
        conf_badge = "badge-grn"
    elif conf_score >= 45:
        conf_label = "MÅTTLIG KONFLUENS"
        conf_badge = "badge-am"
    else:
        conf_label = "LÅG KONFLUENS"
        conf_badge = "badge-red"

    return {
        "score": conf_score,
        "label": conf_label,
        "badge": conf_badge,
        "factors": confluence_factors,
        "earnings": earnings_info,
        "insider_count": len(insider_buys),
        "congress_count": len(congress_buys)
    }
