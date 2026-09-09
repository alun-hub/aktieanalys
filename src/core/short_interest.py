import csv
import io
import time
import requests as req
import yfinance as yf

_short_cache = {}
_FI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def fetch_short_interest(symbol, company_name=None):
    """Hämtar blankningsnivåer för en aktie.
    För svenska aktier: FI:s blankningsregister.
    För amerikanska aktier: Yahoo Finance shortPercentOfFloat.
    """
    cached = _short_cache.get(symbol)
    if cached and (time.time() - cached["ts"] < 3600 * 6):
        return cached["result"]

    is_swedish = symbol.endswith(".ST")

    if not is_swedish:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            pct = info.get("shortPercentOfFloat")
            ratio = info.get("shortRatio")
            short_pct = round(pct * 100, 2) if pct is not None else None
            result = {
                "short_pct": short_pct,
                "short_ratio": round(ratio, 2) if ratio else None,
                "source": "Yahoo Finance",
                "risk": "Hög" if short_pct and short_pct > 10 else ("Medel" if short_pct and short_pct > 4 else "Låg")
            }
        except Exception as e:
            result = {"short_pct": None, "source": "Yahoo Finance", "risk": "Okänd"}
    else:
        search_name = company_name or symbol.replace(".ST", "").replace("-B", "").replace("-A", "")
        try:
            r = req.get(
                "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search",
                params={
                    "SearchFunctionType": "Blankning",
                    "Emittent": search_name,
                    "button": "export",
                    "language": "sv-SE",
                },
                headers=_FI_HEADERS,
                timeout=12
            )
            content = r.content.decode("utf-16-le", errors="ignore")
            reader = csv.DictReader(io.StringIO(content), delimiter=";")
            positions = []
            for row in reader:
                pct_str = row.get("Nettokortposition", row.get("Position", "0"))
                try:
                    pct_val = float(str(pct_str).replace(",", ".").replace("%", "").strip())
                    holder = row.get("Innehavare", row.get("Anmälningsskyldig", ""))
                    date = row.get("Positionsdatum", row.get("Publiceringsdatum", ""))[:10]
                    if pct_val > 0:
                        positions.append({"holder": holder, "pct": pct_val, "date": date})
                except Exception:
                    continue

            total = round(sum(p["pct"] for p in positions), 2) if positions else 0.0
            result = {
                "short_pct": total,
                "positions": positions[:5],
                "source": "Finansinspektionen",
                "risk": "Hög" if total > 5.0 else ("Medel" if total > 2.0 else "Låg")
            }
        except Exception:
            result = {"short_pct": 0.0, "positions": [], "source": "Finansinspektionen", "risk": "Låg"}

    _short_cache[symbol] = {"result": result, "ts": time.time()}
    return result
