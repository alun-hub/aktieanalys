"""Portfölj-hälsokoll.

Användaren lägger in de innehav hen äger (t.ex. hos Avanza). Vi räknar värde,
vinst/förlust och – viktigast – hur RISKEN ser ut: koncentration i enskilda
innehav, bransch- och landfördelning, avgifts- och utdelningsläge.

Detta är ingen handelssimulator. Inga köp/sälj-knappar rör den här tabellen.
"""
import time
import yfinance as yf

from src.core.data import get_db
from src.core.config import OMXS_50, NASDAQ_100

_meta_cache = {}   # symbol -> (ts, {price, sector, country, currency, dividend_yield})
_META_TTL = 3600

CONCENTRATION_WARN = 20.0   # % av portföljen i ett enda innehav


def _known_name(symbol):
    return OMXS_50.get(symbol) or NASDAQ_100.get(symbol) or symbol


def add_holding(symbol, qty, avg_price, name=None, kind="aktie", fee_pct=0.0, note=""):
    symbol = symbol.strip().upper()
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


def _meta(symbol):
    hit = _meta_cache.get(symbol)
    if hit and time.time() - hit[0] < _META_TTL:
        return hit[1]

    meta = {"price": None, "sector": None, "country": None,
            "currency": None, "dividend_yield": None}

    conn = get_db()
    row = conn.execute(
        "SELECT close FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row and row["close"] is not None:
        meta["price"] = float(row["close"])

    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        meta["sector"] = info.get("sector") or ("Krypto" if symbol.endswith("-USD") else None)
        meta["country"] = info.get("country") or ("Sverige" if symbol.endswith(".ST") else None)
        meta["currency"] = info.get("currency")
        dy = info.get("dividendYield")
        if dy and 0 < dy < 25:
            meta["dividend_yield"] = float(dy)
        if meta["price"] is None:
            fi = getattr(t, "fast_info", {}) or {}
            meta["price"] = fi.get("last_price") or fi.get("lastPrice")
    except Exception:
        pass

    if meta["country"] is None:
        meta["country"] = "Sverige" if symbol.endswith(".ST") else ("USA" if not symbol.endswith("-USD") else "—")

    _meta_cache[symbol] = (time.time(), meta)
    return meta


def _region(country):
    c = (country or "").strip().lower()
    if c in ("sverige", "sweden"):
        return "Sverige"
    if c in ("usa", "united states", "us"):
        return "USA"
    return "Övrigt" if c else "Okänd"


def portfolio_health():
    holdings = list_holdings()
    if not holdings:
        return {"empty": True, "positions": [], "warnings": [], "total_value": 0}

    positions, total_value, total_cost = [], 0.0, 0.0
    for h in holdings:
        m = _meta(h["symbol"])
        price = m["price"] or h["avg_price"]
        value = price * h["qty"]
        cost = h["avg_price"] * h["qty"]
        total_value += value
        total_cost += cost
        positions.append({
            "symbol": h["symbol"], "name": h["name"] or h["symbol"],
            "kind": h["kind"], "qty": h["qty"], "avg_price": round(h["avg_price"], 2),
            "price": round(price, 2), "value": value, "cost": cost,
            "pl": value - cost, "pl_pct": round((value / cost - 1) * 100, 1) if cost else 0.0,
            "fee_pct": h["fee_pct"] or 0.0,
            "sector": m["sector"] or "Okänd", "region": _region(m["country"]),
            "dividend_yield": m["dividend_yield"],
            "price_stale": m["price"] is None,
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
