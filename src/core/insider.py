import csv
import io
import re
import time
from datetime import datetime, timedelta
import requests as req
from src.core.config import OMXS_50

_FI_SEARCH = "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search"
_FI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

FI_EXCHANGE_FILTERS = {
    "nasdaq_stockholm": "NASDAQ STOCKHOLM",
    "first_north":      "FIRST NORTH",
    "spotlight":        "SPOTLIGHT",
    "ngm":              "NGM",
}

_insider_cache = {"data": None, "ts": 0, "days": 0}
_ticker_resolve_cache = {}

def _fetch_fi_chunk(date_from, date_to):
    """Hämtar transaktioner från Finansinspektionens export och avkodar utf-16-le."""
    try:
        r = req.get(_FI_SEARCH, params={
            "SearchFunctionType": "Insyn",
            "Publiceringsdatum.From": date_from,
            "Publiceringsdatum.To":   date_to,
            "button":   "export",
            "language": "sv-SE",
        }, headers=_FI_HEADERS, timeout=30)
        return r.content.decode("utf-16-le", errors="ignore")
    except Exception as e:
        print(f"Fel vid hämtning från FI: {e}")
        return ""

def _parse_num(s):
    if not s: return 0.0
    cleaned = str(s).replace("\xa0", "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def _resolve_ticker(fi_company, instrument=""):
    """Matchar ett bolagsnamn från FI mot kända tickers i OMXS_50 eller Yahoo Finance."""
    if not fi_company:
        return None, fi_company

    cache_key = fi_company.lower().strip()
    if cache_key in _ticker_resolve_cache:
        return _ticker_resolve_cache[cache_key]

    # 1. Direktmatchning mot våra kända svenska aktier
    for sym, name in OMXS_50.items():
        clean_name = re.sub(r"\s+(A|B|C|D|AB|publ\.?|\(publ\))$", "", name, flags=re.IGNORECASE).strip().lower()
        if clean_name in cache_key or cache_key in clean_name:
            _ticker_resolve_cache[cache_key] = (sym, name)
            return sym, name

    # 2. Om ingen direktmatchning, returnera bolagsnamnet direkt (ingen långsam nätverksloop)
    _ticker_resolve_cache[cache_key] = (None, fi_company)
    return None, fi_company

def fetch_all_insider_buys(days=30, force=False):
    """Hämtar alla insider-köp (förvärv) från Finansinspektionen de senaste N dagarna."""
    global _insider_cache
    now = time.time()
    
    if not force and _insider_cache["data"] and (now - _insider_cache["ts"] < 1800) and (_insider_cache["days"] >= days):
        return _insider_cache["data"], None

    today = datetime.now()
    intervals = []
    chunk_end = today
    remaining = days
    while remaining > 0:
        chunk_days = min(remaining, 30)
        chunk_start = chunk_end - timedelta(days=chunk_days)
        intervals.append((
            chunk_start.strftime("%Y-%m-%d"),
            chunk_end.strftime("%Y-%m-%d"),
        ))
        chunk_end = chunk_start
        remaining -= chunk_days

    all_lines = []
    header = None
    last_err = None

    for d_from, d_to in intervals:
        content = _fetch_fi_chunk(d_from, d_to)
        lines = content.splitlines()
        if not lines:
            continue
        if header is None:
            header = lines[0]
            all_lines.extend(lines)
        else:
            all_lines.extend(lines[1:])

    if not all_lines:
        return [], "Kunde inte hämta insynsdata från Finansinspektionen."

    trades = []
    reader = csv.DictReader(io.StringIO("\n".join(all_lines)), delimiter=";")
    for row in reader:
        try:
            karaktar = row.get("Karaktär", "")
            if "förvärv" not in karaktar.lower():
                continue

            plats = row.get("Handelsplats", "").upper()
            emittent = row.get("Emittent", "").strip()
            if not emittent:
                continue

            vol = _parse_num(row.get("Volym", "0"))
            pris = _parse_num(row.get("Pris", "0"))
            valuta = row.get("Valuta", "SEK")
            total_belopp = round(vol * pris, 2)

            ticker, display_name = _resolve_ticker(emittent, row.get("Instrumentnamn", ""))

            trades.append({
                "pub_date":    row.get("Publiceringsdatum", "")[:10],
                "date":        row.get("Transaktionsdatum", "")[:10],
                "company":     emittent,
                "ticker":      ticker,
                "display_name": display_name,
                "instrument":  row.get("Instrumentnamn", "").strip(),
                "insider":     row.get("Person i ledande ställning", "").strip(),
                "role":        row.get("Befattning", "").replace("\xa0", " ").strip(),
                "volume":      int(vol),
                "price":       round(pris, 2),
                "amount":      total_belopp,
                "currency":    valuta,
                "marketplace": plats
            })
        except Exception:
            continue

    trades.sort(key=lambda x: (x["pub_date"], x["amount"]), reverse=True)
    _insider_cache = {"data": trades, "ts": now, "days": days}
    return trades, None

def get_insider_buys_for_symbol(symbol, days=60):
    """Returnerar insynsköp för en specifik symbol under senaste N dagarna."""
    all_trades, _ = fetch_all_insider_buys(days=days)
    matches = [t for t in all_trades if t.get("ticker") == symbol]
    return matches
