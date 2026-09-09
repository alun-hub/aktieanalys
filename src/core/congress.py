import time
from datetime import datetime, timedelta
import requests as req

_KADOA_URL = "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data/trades.json"
_congress_cache = {"data": None, "ts": 0.0}

def fetch_congress_trades_raw():
    """Hämtar kongresstransaktioner från open-source datadump."""
    global _congress_cache
    now = time.time()
    if _congress_cache["data"] and (now - _congress_cache["ts"] < 3600 * 6):
        return _congress_cache["data"]
    try:
        r = req.get(_KADOA_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            _congress_cache["data"] = data
            _congress_cache["ts"] = now
            return data
    except Exception as e:
        print(f"Fel vid hämtning av kongressdata: {e}")
    return _congress_cache["data"] or []

def scan_congress_trades(months=3, txn_type="all", chamber="all", party="all"):
    """Skannar politiker-köp och sälj och returnerar sammanställning och avkastning."""
    raw = fetch_congress_trades_raw()
    if not raw:
        return {"trades": [], "stats": {}, "error": "Kunde inte hämta kongressdata"}

    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    filtered = []
    for t in raw:
        t_date = t.get("transaction_date") or t.get("filing_date", "")
        if t_date < cutoff:
            continue
        
        ttype = (t.get("transaction_type") or "Purchase").strip()
        ttype_low = ttype.lower()
        if "purchase" in ttype_low or "buy" in ttype_low:
            action = "KÖP"
            action_badge = "badge-grn"
        elif "sale" in ttype_low or "sell" in ttype_low:
            action = "SÄLJ"
            action_badge = "badge-red"
        else:
            action = "ÖVRIGT"
            action_badge = "badge-am"

        if txn_type == "buy" and action != "KÖP":
            continue
        if txn_type == "sell" and action != "SÄLJ":
            continue

        c_chamber = (t.get("chamber") or "").lower()
        if chamber != "all" and chamber.lower() not in c_chamber:
            continue

        c_party = (t.get("party") or "").upper()
        if party != "all" and c_party != party.upper():
            continue

        ticker = (t.get("ticker") or "").strip().upper()
        if not ticker or ticker in ("--", "N/A", "NONE"):
            continue

        ret = t.get("ret_since")
        ret_val = round(float(ret), 2) if ret is not None else None

        filtered.append({
            "ticker":        ticker,
            "politician":    t.get("filer_name") or t.get("filer_id", "Okänd"),
            "party":         c_party or "—",
            "chamber":       (t.get("chamber") or "Congress").capitalize(),
            "txn_date":      t.get("transaction_date", "")[:10],
            "report_date":   t.get("filing_date", "")[:10],
            "action":        action,
            "action_badge":  action_badge,
            "transaction":   ttype,
            "amount_range":  t.get("amount_range_label", ""),
            "entry_price":   None,
            "today_price":   None,
            "return_pct":    ret_val,
            "held_days":     t.get("days_to_file")
        })

    # Sortera på datum i första hand
    filtered.sort(key=lambda x: x["txn_date"], reverse=True)

    rets = [r["return_pct"] for r in filtered if r["return_pct"] is not None]
    wins = [v for v in rets if v > 0]

    pol_counts = {}
    for r in filtered:
        p = r["politician"]
        pol_counts[p] = pol_counts.get(p, 0) + 1
    top_politicians = sorted(pol_counts.items(), key=lambda x: -x[1])[:8]

    ticker_counts = {}
    for r in filtered:
        ticker_counts[r["ticker"]] = ticker_counts.get(r["ticker"], 0) + 1
    top_tickers = sorted(ticker_counts.items(), key=lambda x: -x[1])[:8]

    buy_count = sum(1 for r in filtered if r["action"] == "KÖP")
    sell_count = sum(1 for r in filtered if r["action"] == "SÄLJ")

    stats = {
        "total":           len(filtered),
        "buys":            buy_count,
        "sells":           sell_count,
        "win_rate":        round(len(wins) / len(rets) * 100, 1) if rets else 0,
        "avg_return":      round(sum(rets) / len(rets), 2) if rets else 0,
        "best":            round(max(rets), 2) if rets else 0,
        "worst":           round(min(rets), 2) if rets else 0,
        "top_politicians": top_politicians,
        "top_tickers":     top_tickers,
    }

    return {"trades": filtered[:100], "stats": stats, "months": months}
