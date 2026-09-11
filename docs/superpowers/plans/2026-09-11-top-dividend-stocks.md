# Topp 10 Utdelningsaktier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skapa en ny flik i appen som listar och rankar de 10 bästa utdelningsaktierna baserat på en kvantitativ balans mellan hög direktavkastning och hållbar kvalitet ("bra köp").

**Architecture:** En ny modul `src/core/dividends.py` tillhandahåller beräkning av `dividend_score` och rankingfunktion med minnes- och filcache. En ny REST API-slutpunkt `/api/portal/top-dividends` exponerar listan med filtrering för `all`, `omx` och `nasdaq`. Slutligen uppdateras `templates/index.html` med fliken "Utdelning", responsiv design, marknadsfilter och direktlänkning till bolagsanalysen.

**Tech Stack:** Python 3.12, Flask, SQLite, Pandas, NumPy, Vanilla JavaScript / CSS.

---

### Task 1: Skapa `src/core/dividends.py` och enhetstester

**Files:**
- Create: `src/core/dividends.py`
- Test: `tests/test_dividends.py`

- [ ] **Step 1: Skriv det felande enhetstestet i `tests/test_dividends.py`**

```python
import unittest
from src.core.dividends import score_dividend_stock, get_top_dividend_stocks

class TestDividends(unittest.TestCase):

    def test_score_dividend_stock(self):
        # Bra utdelare: 5.5% direktavkastning, 50% payout ratio, P/E 12, trend_score 70
        res = score_dividend_stock(
            yield_pct=5.5,
            payout_ratio=50.0,
            pe=12.0,
            trend_score=70.0
        )
        self.assertTrue(80 <= res["dividend_score"] <= 100)
        self.assertIn("verdict", res)

        # Utdelningsfälla: 16% yield, 150% payout, negativ vinst (pe=None), trend_score 25
        res_trap = score_dividend_stock(
            yield_pct=16.0,
            payout_ratio=150.0,
            pe=None,
            trend_score=25.0
        )
        self.assertTrue(res_trap["dividend_score"] < 40)
        self.assertIn("fälla", res_trap["verdict"].lower())

    def test_get_top_dividend_stocks_structure(self):
        # Anropa med begränsad lista och force_refresh=False
        data = get_top_dividend_stocks(market="all", limit=5)
        self.assertIn("stocks", data)
        self.assertIn("updated_at", data)
        self.assertIsInstance(data["stocks"], list)
```

- [ ] **Step 2: Kör testet för att verifiera att det misslyckas**

Run: `python3 -m unittest tests/test_dividends.py`  
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.dividends'`

- [ ] **Step 3: Implementera `src/core/dividends.py`**

```python
import time
import datetime
import yfinance as yf
from src.core.config import OMXS_50, NASDAQ_100
from src.core.signals import trend_score
from src.core.data import get_db

_DIVIDEND_CACHE = {"all": None, "omx": None, "nasdaq": None, "ts": 0.0}
_CACHE_TTL = 3600  # 1 timme


def score_dividend_stock(yield_pct: float, payout_ratio: float = None, pe: float = None, trend_score_val: float = 50.0) -> dict:
    """Beräknar ett samlat utdelnings- och kvalitetsbetyg (0–100)."""
    if yield_pct is None or yield_pct <= 0:
        return {"dividend_score": 0.0, "verdict": "Ingen utdelning"}

    # 1. Direktavkastningspoäng (0–100)
    # 3.5 - 8.0 % är idealiskt
    if yield_pct < 1.5:
        y_score = yield_pct * 30.0
    elif yield_pct <= 3.5:
        y_score = 45.0 + (yield_pct - 1.5) * 20.0
    elif yield_pct <= 8.0:
        y_score = 85.0 + (yield_pct - 3.5) * 3.3
    elif yield_pct <= 12.0:
        y_score = 100.0 - (yield_pct - 8.0) * 5.0
    else:
        y_score = max(20.0, 80.0 - (yield_pct - 12.0) * 8.0)  # Utdelningsfällerisk

    # 2. Utdelningsandel (Payout ratio) (0–100)
    if payout_ratio is None:
        p_score = 50.0
    elif payout_ratio < 0:
        p_score = 10.0  # Negativ vinst
    elif payout_ratio <= 20.0:
        p_score = 65.0  # Mycket låg utdelningsandel
    elif payout_ratio <= 70.0:
        p_score = 100.0  # Hållbar och sund
    elif payout_ratio <= 85.0:
        p_score = 75.0
    elif payout_ratio <= 100.0:
        p_score = 40.0
    else:
        p_score = 10.0  # Utdelning överstiger vinst

    # 3. Värdering & P/E (0–100)
    if pe is None or pe <= 0:
        v_score = 25.0
    elif pe < 6.0:
        v_score = 70.0  # Kan vara cyklisk topp
    elif pe <= 18.0:
        v_score = 100.0  # Mycket attraktiv värdering
    elif pe <= 26.0:
        v_score = 65.0
    else:
        v_score = max(10.0, 65.0 - (pe - 26.0) * 3.0)

    # 4. Teknisk trend (0–100)
    t_score = max(0.0, min(100.0, float(trend_score_val or 50.0)))

    # Sammanvägning
    tot = (0.35 * y_score) + (0.25 * p_score) + (0.20 * v_score) + (0.20 * t_score)
    final_score = round(max(0.0, min(100.0, tot)), 1)

    # Omdöme i klarspråk
    if yield_pct > 12.0 and p_score < 40.0:
        verdict = "Varning för utdelningsfälla (ohållbar utdelningsandel)"
    elif final_score >= 80.0:
        verdict = "Stark kvalitetsutdelare med sund trend"
    elif final_score >= 65.0:
        verdict = "Stabil utdelningsaktie med god avkastning"
    elif final_score >= 50.0:
        verdict = "Måttlig kvalitet eller ansträngd värdering"
    else:
        verdict = "Hög risk eller svag trend"

    return {
        "dividend_score": final_score,
        "yield_score": round(y_score, 1),
        "payout_score": round(p_score, 1),
        "valuation_score": round(v_score, 1),
        "trend_score": round(t_score, 1),
        "verdict": verdict
    }


def get_top_dividend_stocks(market: str = "all", limit: int = 10, force_refresh: bool = False) -> dict:
    """Hämtar och rankar de bästa utdelningsaktierna för angiven marknad."""
    global _DIVIDEND_CACHE
    now = time.time()
    market = (market or "all").lower()

    if not force_refresh and _DIVIDEND_CACHE.get(market) and (now - _DIVIDEND_CACHE["ts"] < _CACHE_TTL):
        return _DIVIDEND_CACHE[market]

    db = get_db()
    tickers = {}
    if market in ("all", "omx", "omxs"):
        tickers.update({s: (n, "OMX") for s, n in OMXS_50.items()})
    if market in ("all", "nasdaq"):
        tickers.update({s: (n, "NASDAQ") for s, n in NASDAQ_100.items()})

    scored_stocks = []

    for sym, (name, mkt) in tickers.items():
        # Hämta senaste tekniska data från SQLite
        row = db.execute(
            "SELECT close, ma50, ma200, rsi, atr FROM history "
            "WHERE symbol = ? AND close IS NOT NULL ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
        if not row:
            continue

        close = float(row["close"])
        ma50 = float(row["ma50"]) if row["ma50"] is not None else None
        ma200 = float(row["ma200"]) if row["ma200"] is not None else None
        rsi = float(row["rsi"]) if row["rsi"] is not None else None

        tscore = trend_score(close, ma50, ma200, rsi)

        # Hämta fundamenta via yfinance
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            raw_yield = info.get("dividendYield")
            if not raw_yield:
                continue
            # yfinance returnerar procent eller decimal
            yield_pct = float(raw_yield)
            if yield_pct < 0.25:  # Om decimalform t.ex. 0.054 -> 5.4%
                yield_pct = yield_pct * 100.0

            raw_payout = info.get("payoutRatio")
            payout_pct = float(raw_payout) * 100.0 if raw_payout is not None else None
            pe = float(info.get("trailingPE")) if info.get("trailingPE") is not None else None

            score_data = score_dividend_stock(yield_pct, payout_pct, pe, tscore)
            curr = "$" if mkt == "NASDAQ" else "kr"

            scored_stocks.append({
                "symbol": sym,
                "name": name,
                "market": mkt,
                "currency": curr,
                "close": round(close, 2),
                "dividend_yield": round(yield_pct, 2),
                "payout_ratio": round(payout_pct, 1) if payout_pct is not None else None,
                "pe": round(pe, 1) if pe is not None else None,
                "trend_score": tscore,
                "dividend_score": score_data["dividend_score"],
                "verdict": score_data["verdict"]
            })
        except Exception:
            continue

    db.close()

    # Sortera på dividend_score fallande
    scored_stocks.sort(key=lambda x: x["dividend_score"], reverse=True)
    top_stocks = scored_stocks[:limit]

    # Tilldela rank
    for idx, s in enumerate(top_stocks, 1):
        s["rank"] = idx

    result = {
        "market": market,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stocks": top_stocks
    }

    _DIVIDEND_CACHE[market] = result
    _DIVIDEND_CACHE["ts"] = now
    return result
```

- [ ] **Step 4: Kör enhetstestet för att verifiera att det passerar**

Run: `python3 -m unittest tests/test_dividends.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/dividends.py tests/test_dividends.py
git commit -m "feat(dividends): lägg till motor för Topp 10 Utdelningsaktier"
```

---

### Task 2: Skapa API-slutpunkt `/api/portal/top-dividends`

**Files:**
- Modify: `src/api/routes.py`
- Test: `tests/test_api_endpoints.py`

- [ ] **Step 1: Lägg till test i `tests/test_api_endpoints.py`**

```python
    def test_top_dividends_endpoint(self):
        resp = self.client.get('/api/portal/top-dividends?market=all&limit=5')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('stocks', data)
        self.assertIn('updated_at', data)
```

- [ ] **Step 2: Kör testet för att verifiera att det misslyckas**

Run: `python3 -m unittest tests/test_api_endpoints.py`  
Expected: FAIL with status code 404

- [ ] **Step 3: Lägg till endpointen i `src/api/routes.py`**

```python
@portal_bp.route("/api/portal/top-dividends")
def get_top_dividends():
    market = request.args.get("market", "all")
    limit = int(request.args.get("limit", 10))
    refresh = request.args.get("refresh", "0") in ("1", "true")
    from src.core.dividends import get_top_dividend_stocks
    data = get_top_dividend_stocks(market=market, limit=limit, force_refresh=refresh)
    return jsonify(data)
```

- [ ] **Step 4: Kör testet för att verifiera att det passerar**

Run: `python3 -m unittest tests/test_api_endpoints.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes.py tests/test_api_endpoints.py
git commit -m "feat(api): lägg till /api/portal/top-dividends endpoint"
```

---

### Task 3: Bygg gränssnittet i `templates/index.html`

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Lägg till fliken i `TABS` och `TABLOADERS`**
  - Lägg till `["dividends", "Utdelning"]` i `TABS`-listan (efter `opportunities`).
  - Koppla `TABLOADERS["dividends"] = loadDividends`.

- [ ] **Step 2: Skapa sektionen `<section class="pane" id="pane-dividends">`**
  - Lägg till rubrik och introduktionstext.
  - Lägg till filterknappar för `Alla`, `Sverige (OMX)` och `USA (Nasdaq)`.
  - Skapa container `#div-container`.

- [ ] **Step 3: Skriv JavaScript-funktionen `loadDividends(market)`**
  - Hämta data från `/api/portal/top-dividends?market=...`.
  - Rendera kort/tabell med:
    - Rank 1–10.
    - Namn, symbol, pris.
    - Direktavkastning (accentfärg, stor text).
    - Utdelningspoäng (0–100) med progressbar.
    - P/E, utdelningsandel.
    - Trendstatus.
    - Knapp "Analysera" som anropar `goToAnalyze(symbol)`.

- [ ] **Step 4: Testa gränssnittet manuellt och verifiera att alla tester passerar**

Run: `python3 -m unittest discover tests`  
Expected: OK (alla tester passerar)

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): lägg till fliken Utdelning i frontend"
```

---

### Task 4: Förladda utdelningscachen vid nattsynk

**Files:**
- Modify: `src/core/data.py`

- [ ] **Step 1: Uppdatera `sync_all_stocks` i `src/core/data.py`**
  - Efter att alla aktier synkats, anropa `get_top_dividend_stocks(force_refresh=True)` så cachen alltid är uppdaterad och snabb för användaren.

- [ ] **Step 2: Kör hela testsviten**

Run: `python3 -m unittest discover tests`  
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/core/data.py
git commit -m "feat(sync): förladda utdelningscachen vid marknadssynk"
```

---

### Task 5: Push & Deploy till `gnarg`

- [ ] **Step 1: Pusha ändringar till GitHub**

```bash
git push origin main
```

- [ ] **Step 2: Kör deploy via SSH till `gnarg`**

```bash
ssh gnarg "cd /home/alun/aktieanalys && git pull origin main && ./deploy.sh"
```

- [ ] **Step 3: Verifiera på `gnarg` att podden startat och svarar på `/api/portal/top-dividends`**

```bash
ssh gnarg "curl -s -H 'Host: aktieanalys.192.168.1.176.nip.io' 'http://localhost/api/portal/top-dividends?limit=3' | head -c 150"
```
