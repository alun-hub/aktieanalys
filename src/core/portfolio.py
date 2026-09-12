"""Portfölj-hälsokoll.

Användaren lägger in de innehav hen äger (t.ex. hos Avanza). Vi räknar värde,
vinst/förlust och – viktigast – hur RISKEN ser ut: koncentration i enskilda
innehav, bransch- och landfördelning, avgifts- och utdelningsläge.

Detta är ingen handelssimulator. Inga köp/sälj-knappar rör den här tabellen.
"""
import json
import re
import time
import datetime
import yfinance as yf

from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100, POPULAR_ETFS
from src.core.signals import trend_score

_meta_cache = {}   # symbol -> (ts, {price, sector, country, currency, dividend_yield})
_META_TTL = 7200
_fx_cache = {}
_FX_TTL = 7200

CONCENTRATION_WARN = 20.0   # % av portföljen i ett enda innehav


def get_exchange_rate(currency):
    """Hämtar växelkurs till SEK (t.ex. USD -> SEK, EUR -> SEK)."""
    curr = (currency or "SEK").upper().strip()
    if curr in ("SEK", "KR", ""):
        return 1.0
    now = time.time()
    hit = _fx_cache.get(curr)
    if hit and now - hit[0] < _FX_TTL:
        return hit[1]

    fallbacks = {
        "USD": 9.70,
        "EUR": 10.80,
        "NOK": 0.95,
        "DKK": 1.45,
        "GBP": 12.80,
        "GBX": 0.128,
        "CAD": 7.10,
        "CHF": 11.20,
    }
    rate = fallbacks.get(curr, 1.0)
    try:
        lookup_curr = curr
        mult = 1.0
        if curr in ("GBX", "GBP"):
            lookup_curr = "GBP"
            if curr == "GBX":
                mult = 0.01
        t = yf.Ticker(f"{lookup_curr}SEK=X")
        fi = getattr(t, "fast_info", {}) or {}
        p = fi.get("last_price") or fi.get("lastPrice")
        if p and p > 0:
            rate = float(p) * mult
    except Exception:
        pass

    _fx_cache[curr] = (now, rate)
    return rate


def _known_name(symbol):
    if symbol in POPULAR_ETFS:
        return POPULAR_ETFS[symbol]["name"]
    return OMXS_50.get(symbol) or NASDAQ_100.get(symbol) or symbol


def add_holding(symbol=None, qty=None, avg_price=None, name=None, kind="aktie",
                fee_pct=0.0, note="", value=None, cost=None, is_manual=False, region=None):
    if not symbol:
        slug = re.sub(r'[^A-Z0-9]+', '-', (name or "MANUELLT").upper()).strip('-')
        symbol = f"MANUAL:{slug}"
    else:
        symbol = symbol.strip().upper()

    if is_manual and not symbol.startswith("MANUAL:"):
        symbol = f"MANUAL:{symbol}"

    if symbol.startswith("MANUAL:"):
        is_manual = True

    # Hantera Kronor-läge (värde och anskaffningskostnad direkt)
    if value is not None or cost is not None:
        val_f = float(value if value is not None else (float(qty) * float(avg_price) if qty and avg_price else 0))
        cost_f = float(cost if cost is not None else val_f)
        if qty is None or avg_price is None:
            qty = 1.0
            avg_price = cost_f
        reg = region or ("Global" if kind == "fond" else "Övrigt")
        meta_dict = {
            "is_manual": is_manual,
            "current_value": val_f,
            "cost": cost_f,
            "region": reg,
            "sector": f"Fond - {reg}" if kind == "fond" else "Övrigt",
            "custom_note": note if (note and not note.startswith("{")) else ""
        }
        note = json.dumps(meta_dict, ensure_ascii=False)
    elif is_manual:
        q = float(qty if qty is not None else 1.0)
        ap = float(avg_price if avg_price is not None else 0.0)
        c = q * ap
        reg = region or "Global"
        meta_dict = {
            "is_manual": True,
            "current_value": c,
            "cost": c,
            "region": reg,
            "sector": f"Fond - {reg}" if kind == "fond" else "Övrigt",
            "custom_note": note if (note and not note.startswith("{")) else ""
        }
        note = json.dumps(meta_dict, ensure_ascii=False)
        qty = q
        avg_price = ap

    conn = get_db()
    conn.execute(
        """INSERT INTO holdings (symbol, name, qty, avg_price, kind, fee_pct, added_date, note)
           VALUES (?, ?, ?, ?, ?, ?, date('now'), ?)
           ON CONFLICT(symbol) DO UPDATE SET
             qty=excluded.qty, avg_price=excluded.avg_price, name=excluded.name,
             kind=excluded.kind, fee_pct=excluded.fee_pct, note=excluded.note""",
        (symbol, name or _known_name(symbol), float(qty), float(avg_price),
         kind, float(fee_pct or 0), note or ""))
    conn.commit()
    conn.close()
    return symbol


def remove_holding(symbol):
    conn = get_db()
    conn.execute("DELETE FROM holdings WHERE symbol = ?", (symbol.strip().upper(),))
    conn.commit()
    conn.close()


def list_holdings():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM holdings ORDER BY symbol")]
    conn.close()
    return rows


def _holding_recommendation(symbol, kind, m, row):
    """Genererar en kort rekommendation: Köp, Behåll eller Sälj med orsak och tidshorisont."""
    if kind == "fond" or symbol.startswith("MANUAL:"):
        return {"action": "Behåll", "badge": "hold", "horizon": "Lång sikt (3–5+ år)", "reason": "Långsiktigt fondsparande"}

    try:
        from src.core.analysis import analyze_any_stock
        an = analyze_any_stock(symbol)
        if an and not an.get("error") and an.get("recommendation"):
            rec = an["recommendation"]
            return {
                "action": rec.get("action", "Behåll"),
                "badge": rec.get("badge", "hold"),
                "horizon": rec.get("horizon", "1–3 månader"),
                "reason": rec.get("rationale") or "Teknisk analys",
                "strategy": rec.get("strategy"),
                "target_price": rec.get("target_price"),
                "stop_loss": rec.get("stop_loss"),
            }
    except Exception:
        pass

    close = m.get("price") or (row.get("close") if row else None)
    ma50 = m.get("ma50") or (row.get("ma50") if row else None)
    ma200 = m.get("ma200") or (row.get("ma200") if row else None)
    rsi = (row.get("rsi") if row else None)

    score = None
    if close and (ma50 or ma200):
        score = trend_score(close, ma50, ma200, rsi or 50.0)

    rec_key = (m.get("rec_key") or "").lower()

    if score is not None:
        if score >= 65:
            if rec_key in ("sell", "underperform"):
                return {"action": "Behåll", "badge": "hold", "horizon": "Bevaka MA50 (1–2 månader)", "reason": "Teknisk uppgång men svag analytikersyn"}
            return {"action": "Köp", "badge": "buy", "horizon": "Medellång sikt (2–6 månader)", "reason": "Stark teknisk upptrend"}
        elif score <= 38:
            if rec_key in ("strong_buy", "buy"):
                return {"action": "Behåll", "badge": "hold", "horizon": "1–3 månader (avvakta)", "reason": "Dipp under medelvärden men stark analytikerkonsensus"}
            return {"action": "Sälj", "badge": "sell", "horizon": "Kliv av omgående", "reason": "Nedåttrend under medelvärden"}
        else:
            if rec_key in ("strong_buy", "buy"):
                return {"action": "Köp", "badge": "buy", "horizon": "Lång sikt (6–12 månader)", "reason": "Konsolidering med positiv analytikerkonsensus"}
            return {"action": "Behåll", "badge": "hold", "horizon": "1–3 månader", "reason": "Konsolidering / neutral trend"}

    if rec_key in ("strong_buy", "buy"):
        return {"action": "Köp", "badge": "buy", "horizon": "Lång sikt (6–12 månader)", "reason": "Analytikerkonsensus: Köp"}
    elif rec_key in ("sell", "underperform"):
        return {"action": "Sälj", "badge": "sell", "horizon": "Kliv av omgående", "reason": "Analytikerkonsensus: Sälj"}

    return {"action": "Behåll", "badge": "hold", "horizon": "Lång sikt", "reason": "Stabil nivå / saknar stark säljsignal"}


def _meta(symbol):
    if symbol.startswith("MANUAL:"):
        return {"price": None, "sector": "Fond", "country": "Global",
                "currency": "SEK", "dividend_yield": None}

    hit = _meta_cache.get(symbol)
    if hit and time.time() - hit[0] < _META_TTL:
        return hit[1]

    meta = {"price": None, "sector": None, "country": None,
            "currency": None, "dividend_yield": None,
            "rec_key": None, "ma50": None, "ma200": None}

    if symbol in POPULAR_ETFS:
        meta["sector"] = POPULAR_ETFS[symbol].get("sector")
        meta["country"] = POPULAR_ETFS[symbol].get("region")

    conn = get_db()
    row = conn.execute(
        "SELECT close, ma50, ma200, rsi FROM history WHERE symbol = ? AND close IS NOT NULL "
        "ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row and row["close"] is not None:
        meta["price"] = float(row["close"])
        if row["ma50"] is not None:
            meta["ma50"] = float(row["ma50"])
        if row["ma200"] is not None:
            meta["ma200"] = float(row["ma200"])

    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        if not meta["sector"]:
            meta["sector"] = info.get("sector") or ("Krypto" if symbol.endswith("-USD") else None)
        if not meta["country"]:
            meta["country"] = info.get("country") or ("Sverige" if symbol.endswith(".ST") else None)
        meta["currency"] = info.get("currency")
        meta["rec_key"] = info.get("recommendationKey")
        if info.get("fiftyDayAverage"):
            meta["ma50"] = float(info.get("fiftyDayAverage"))
        if info.get("twoHundredDayAverage"):
            meta["ma200"] = float(info.get("twoHundredDayAverage"))
        dy = info.get("dividendYield")
        if dy and 0 < dy < 25:
            meta["dividend_yield"] = float(dy)
        fi = getattr(t, "fast_info", {}) or {}
        live_p = fi.get("last_price") or fi.get("lastPrice") or info.get("currentPrice") or info.get("regularMarketPrice")
        if live_p:
            meta["price"] = float(live_p)
    except Exception:
        pass

    if meta["country"] is None:
        meta["country"] = "Sverige" if symbol.endswith(".ST") else ("USA" if not symbol.endswith("-USD") else "—")
    if meta["currency"] is None:
        meta["currency"] = "SEK" if symbol.endswith(".ST") else ("USD" if not symbol.endswith("-USD") else "USD")

    _meta_cache[symbol] = (time.time(), meta)
    return meta


def _region(country):
    c = (country or "").strip().lower()
    if c in ("sverige", "sweden"):
        return "Sverige"
    if c in ("usa", "united states", "us"):
        return "USA"
    if c in ("global", "världen", "world"):
        return "Global"
    if c in ("norden", "nordics"):
        return "Norden"
    if c in ("europa", "europe"):
        return "Europa"
    if c in ("tillväxtmarknader", "emerging markets", "em"):
        return "Tillväxtmarknader"
    if c in ("räntor", "ränta", "bonds"):
        return "Räntor"
    if c in ("råvaror", "guld", "gold"):
        return "Råvaror"
    if c in ("asien", "asia"):
        return "Asien"
    return "Övrigt" if c else "Okänd"


def portfolio_health():
    holdings = list_holdings()
    if not holdings:
        return {"empty": True, "positions": [], "warnings": [], "total_value": 0}

    # Förladda metadata parallellt för alla icke-manuella innehav för att eliminera sekventiell Yahoo-latens
    non_manual = [
        h["symbol"] for h in holdings
        if not (h["symbol"].startswith("MANUAL:") or (h.get("note") and '"is_manual": true' in h["note"]))
    ]
    uncached = [
        s for s in non_manual
        if s not in _meta_cache or (time.time() - _meta_cache[s][0] >= _META_TTL)
    ]
    if uncached:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(uncached))) as executor:
            list(executor.map(_meta, uncached))

    positions, total_value, total_cost = [], 0.0, 0.0
    for h in holdings:
        is_manual = False
        note_data = {}
        if h["note"]:
            try:
                note_data = json.loads(h["note"])
                if isinstance(note_data, dict) and note_data.get("is_manual"):
                    is_manual = True
            except Exception:
                pass

        if h["symbol"].startswith("MANUAL:") or is_manual:
            curr = "SEK"
            fx_rate = 1.0
            value = float(note_data.get("current_value", h["qty"] * h["avg_price"]))
            cost = float(note_data.get("cost", h["qty"] * h["avg_price"]))
            raw_value = value
            raw_cost = cost
            price = round(value / h["qty"], 2) if h["qty"] else round(value, 2)
            region = _region(note_data.get("region") or "Global")
            sector = note_data.get("sector") or ("Fond - " + region if h["kind"] == "fond" else "Övrigt")
            price_stale = False
            div_yield = None
            rec = {"action": "Behåll", "badge": "hold", "reason": "Långsiktigt fondsparande"}
        else:
            m = _meta(h["symbol"])
            curr = (m.get("currency") or ("SEK" if h["symbol"].endswith(".ST") else "USD")).upper()
            fx_rate = get_exchange_rate(curr)

            raw_price = m["price"] or h["avg_price"]
            raw_cost = h["avg_price"] * h["qty"]
            raw_value = raw_price * h["qty"]

            price = raw_price
            value = raw_value * fx_rate
            cost = raw_cost * fx_rate

            sector = m["sector"] or "Okänd"
            region = _region(m["country"])
            price_stale = m["price"] is None
            div_yield = m["dividend_yield"]

            conn = get_db()
            hist_row = conn.execute(
                "SELECT close, ma50, ma200, rsi FROM history WHERE symbol = ? AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT 1", (h["symbol"],)).fetchone()
            conn.close()
            rec = _holding_recommendation(h["symbol"], h["kind"], m, dict(hist_row) if hist_row else None)

        total_value += value
        total_cost += cost
        positions.append({
            "symbol": h["symbol"], "name": h["name"] or h["symbol"],
            "kind": h["kind"], "qty": h["qty"], "avg_price": round(h["avg_price"], 2),
            "price": round(price, 2),
            "currency": curr,
            "fx_rate": round(fx_rate, 4),
            "value": round(value, 2), "cost": round(cost, 2),
            "raw_value": round(raw_value, 2), "raw_cost": round(raw_cost, 2),
            "pl": round(value - cost, 2),
            "pl_pct": round((value / cost - 1) * 100, 1) if cost else 0.0,
            "fee_pct": h["fee_pct"] or 0.0,
            "sector": sector, "region": region,
            "dividend_yield": div_yield,
            "price_stale": price_stale,
            "is_manual": is_manual or h["symbol"].startswith("MANUAL:"),
            "recommendation": rec,
        })

    for p in positions:
        p["weight"] = round(p["value"] / total_value * 100, 1) if total_value else 0.0

    def _agg(key):
        out = {}
        for p in positions:
            out[p[key]] = round(out.get(p[key], 0) + p["weight"], 1)
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    weighted_fee = sum(p["weight"] / 100 * (p["fee_pct"] or 0) for p in positions)
    weighted_yield = sum(p["weight"] / 100 * (p["dividend_yield"] or 0) for p in positions)

    warnings = []
    big = [p for p in positions if p["weight"] >= CONCENTRATION_WARN]
    for p in big:
        warnings.append(f"{p['name']} är {p['weight']:g} % av portföljen – en enskild aktie som väger så tungt är en klumprisk.")
    sectors = _agg("sector")
    if sectors and next(iter(sectors.values())) >= 45:
        top = next(iter(sectors.items()))
        warnings.append(f"{top[1]:g} % ligger i branschen {top[0]}. En bransch som backar drar då ner hela portföljen.")
    regions = _agg("region")
    if len(positions) < 5:
        warnings.append(f"Bara {len(positions)} innehav. Med så få aktier svänger portföljen mycket på enskilda bolag – en bred indexfond ger mer stabil spridning.")
    if weighted_fee >= 1.0:
        warnings.append(f"Vägd förvaltningsavgift ~{weighted_fee:.2f} %/år. Över en lång sparhorisont äter det en stor del av avkastningen.")

    return {
        "empty": False,
        "total_value": round(total_value),
        "total_cost": round(total_cost),
        "pl": round(total_value - total_cost),
        "pl_pct": round((total_value / total_cost - 1) * 100, 1) if total_cost else 0.0,
        "n_positions": len(positions),
        "largest_weight": max((p["weight"] for p in positions), default=0),
        "weighted_fee_pct": round(weighted_fee, 2),
        "weighted_dividend_yield": round(weighted_yield, 2),
        "by_sector": sectors,
        "by_region": regions,
        "positions": sorted(positions, key=lambda p: -p["value"]),
        "warnings": warnings,
    }


def generate_sell_alerts() -> list[dict]:
    """Går igenom alla innehav i portföljen och flaggar sälj- och trimförslag:
    - Endast för enskilda aktier (kind == 'aktie'), ALDRIG för fonder/ETF:er (kind == 'fond').
    - severity='exit': Bear market i aktiens marknad ELLER pris under ATR-stop.
    - severity='trim': Korrektion i marknaden för momentum-aktier, eller brott under MA50.
    - reason: 'regime_bear', 'atr_stop', eller 'trend_break'.

    Sparar nya varningar i `sell_alerts`-tabellen om de inte redan är aktiva.
    Exekverar ALDRIG faktiska sälj och rör ALDRIG holdings-tabellen.
    """
    from src.core.regime import get_market_regime

    holdings = list_holdings()
    if not holdings:
        return []

    conn = get_db()
    created_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    alerts = []

    regime_omx = get_market_regime("omx")
    regime_ndx = get_market_regime("nasdaq")

    try:
        for h in holdings:
            sym = h["symbol"].upper()
            kind = h.get("kind", "aktie")
            # Fonder och manuella poster säljs aldrig pga regimskifte
            if kind == "fond" or sym.startswith("MANUAL:"):
                continue

            is_us = not sym.endswith(".ST") and not sym.endswith("-USD")
            market_regime = regime_ndx if is_us else regime_omx
            regime = market_regime.get("regime", "bull")

            row = conn.execute(
                "SELECT close, open, ma50, ma200, atr FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date DESC LIMIT 1",
                (sym,),
            ).fetchone()

            if not row:
                continue

            close = float(row["close"])
            ma50 = float(row["ma50"]) if row["ma50"] is not None else None
            ma200 = float(row["ma200"]) if row["ma200"] is not None else None
            atr = float(row["atr"]) if row["atr"] is not None else close * 0.03
            avg_price = float(h.get("avg_price") or close)

            stop_level = avg_price - (atr * 2.5)

            new_alert = None

            # 1. Stop loss triggad?
            if close < stop_level and avg_price > 0:
                new_alert = {
                    "symbol": sym,
                    "name": h.get("name") or sym,
                    "reason": "atr_stop",
                    "severity": "exit",
                    "reason_text": f"Kursen ({close:.1f}) har brutit under stop-loss ({stop_level:.1f}). Begränsa nedsidan.",
                }
            # 2. Bear market för hela marknaden?
            elif regime == "bear":
                if ma200 and close < ma200:
                    new_alert = {
                        "symbol": sym,
                        "name": h.get("name") or sym,
                        "reason": "regime_bear",
                        "severity": "exit",
                        "reason_text": f"Index handlas i Bear Market och {sym} har brutit under MA200 ({close:.1f} < {ma200:.1f}).",
                    }
                else:
                    new_alert = {
                        "symbol": sym,
                        "name": h.get("name") or sym,
                        "reason": "regime_bear",
                        "severity": "trim",
                        "reason_text": f"Marknaden är i Bear Market. Överväg att trimma positionen och säkra likviditet.",
                    }
            # 3. Korrektion i marknaden + svaghet i aktien
            elif regime == "correction" and ma50 and close < ma50:
                new_alert = {
                    "symbol": sym,
                    "name": h.get("name") or sym,
                    "reason": "trend_break",
                    "severity": "trim",
                    "reason_text": f"Marknadskorrektion: Kursen har brutit under 50-dagars medelvärde ({close:.1f} < {ma50:.1f}).",
                }

            if new_alert:
                existing = conn.execute(
                    "SELECT id FROM sell_alerts WHERE symbol = ? AND acknowledged = 0",
                    (sym,),
                ).fetchone()
                if not existing:
                    cursor = conn.execute(
                        """INSERT INTO sell_alerts (symbol, created_at, reason, severity, acknowledged)
                        VALUES (?, ?, ?, ?, 0)""",
                        (sym, created_now, new_alert["reason"], new_alert["severity"]),
                    )
                    conn.commit()
                    alert_id = cursor.lastrowid
                else:
                    try:
                        alert_id = existing["id"]
                    except (KeyError, TypeError, IndexError):
                        alert_id = None

                alerts.append({
                    "id": alert_id,
                    "symbol": sym,
                    "name": new_alert["name"],
                    "reason": new_alert["reason"],
                    "severity": new_alert["severity"],
                    "reason_text": new_alert["reason_text"],
                    "close": round(close, 2),
                    "avg_price": round(avg_price, 2),
                    "created_at": created_now,
                })
    finally:
        conn.close()

    return alerts


def list_sell_alerts(include_acknowledged: bool = False) -> list[dict]:
    """Hämtar alla genererade säljvarningar från databasen."""
    generate_sell_alerts()
    conn = get_db()
    if include_acknowledged:
        query = "SELECT * FROM sell_alerts ORDER BY id DESC"
        rows = conn.execute(query).fetchall()
    else:
        query = "SELECT * FROM sell_alerts WHERE acknowledged = 0 ORDER BY id DESC"
        rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def acknowledge_sell_alert(alert_id: int) -> bool:
    """Markerar en säljvarning som kvitterad av användaren."""
    conn = get_db()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor = conn.execute(
        "UPDATE sell_alerts SET acknowledged = 1, acknowledged_at = ? WHERE id = ?",
        (now_str, int(alert_id)),
    )
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

