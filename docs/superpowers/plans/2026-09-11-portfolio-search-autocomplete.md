# Implementation Plan: Bolagssökning & Autocomplete i Portföljvyn

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Göra det möjligt att söka fram aktier med bolagsnamn istället för ticker i "Min portfölj" med live-autocomplete och automatiskt ticker-uppslag.

**Architecture:** Använd befintlig `resolve_symbol` i `src/core/analysis.py` vid anrop till `POST /api/portfolio`; bygg en responsiv dropdown i `templates/index.html` kopplad till `GET /api/portal/search` med kursförslag.

**Tech Stack:** Python 3, Flask, SQLite, vanilla JavaScript, HTML5/CSS3, unittest.

---

### Task 1: Backend - Symboluppslag i Portfolio API

**Files:**
- Modify: `src/api/routes.py`
- Test: `tests/test_portfolio_search.py`

- [ ] **Step 1: Skriv test i `tests/test_portfolio_search.py`**

```python
import unittest
from app import app
from src.core.portfolio import list_holdings, remove_holding

class TestPortfolioSearch(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        remove_holding("INVE-B.ST")

    def tearDown(self):
        remove_holding("INVE-B.ST")

    def test_add_holding_by_name(self):
        # Skicka 'investor' istället för 'INVE-B.ST'
        res = self.client.post("/api/portfolio", json={
            "symbol": "investor",
            "qty": 10,
            "avg_price": 250.0,
            "kind": "aktie"
        })
        self.assertEqual(res.status_code, 200)
        holdings = list_holdings()
        syms = [h["symbol"] for h in holdings]
        self.assertIn("INVE-B.ST", syms)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Kör testet och verifiera att det misslyckas**

Run: `python3 -m unittest tests/test_portfolio_search.py`  
Expected: FAIL (sparas som "INVESTOR" istället för "INVE-B.ST").

- [ ] **Step 3: Implementera i `src/api/routes.py`**

I `portfolio_add_route()`:
```python
from src.core.analysis import resolve_symbol

@api_bp.route('/portfolio', methods=['POST'])
def portfolio_add_route():
    d = request.json or {}
    try:
        raw_sym = d['symbol'].strip()
        resolved = resolve_symbol(raw_sym) or raw_sym.upper()
        pf.add_holding(
            symbol=resolved, qty=d['qty'], avg_price=d['avg_price'],
            name=d.get('name'), kind=d.get('kind', 'aktie'),
            fee_pct=d.get('fee_pct', 0), note=d.get('note', ''))
        return jsonify({"ok": True, "symbol": resolved})
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"Ogiltig indata: {e}"}), 400
```

- [ ] **Step 4: Kör testet och verifiera att det passerar**

Run: `python3 -m unittest tests/test_portfolio_search.py`  
Expected: OK.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/api/routes.py tests/test_portfolio_search.py
git commit -m "Feat: automatisk uppslagning av bolagsnamn vid portföljtillägg"
```

---

### Task 2: Frontend - HTML & Autocomplete Dropdown

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Uppdatera HTML för sökfält och dropdown**

I `#pane-portfolio`:
Byt ut ticker-fältet mot:
```html
<div class="field" style="position:relative; flex:2;">
  <label>Sök bolag eller ticker</label>
  <input id="pf-sym" placeholder="t.ex. Investor, Volvo, Apple…" autocomplete="off">
  <input type="hidden" id="pf-symbol-val">
  <div id="pf-search-dropdown" class="dropdown hidden" style="position:absolute; top:100%; left:0; right:0; z-index:50; background:var(--bg-card); border:1px solid var(--border); border-radius:6px; max-height:220px; overflow-y:auto; box-shadow:0 4px 12px rgba(0,0,0,0.4); margin-top:2px;"></div>
</div>
```

- [ ] **Step 2: Implementera söklogik och val i JavaScript**

I `templates/index.html`:
- Lyssna på `input` på `#pf-sym`.
- Kör debounce mot `/api/portal/search?q=...`.
- Renderar sökresultat med bolagsnamn och symbol.
- Vid klick på träff:
  - Fyll `#pf-sym` med bolagsnamn.
  - Sätt `#pf-symbol-val` till symbolen.
  - Hämta dagsaktuell kurs från `/api/portal/analyze?symbol=` och fyll i `#pf-gav` som förslag om `#pf-gav` är tomt.
  - Dölj dropdownen.
- I `addHolding()`: Skicka `symbol: $("#pf-symbol-val").value || $("#pf-sym").value.trim()`.

- [ ] **Step 3: Validera JavaScript syntax och commit**

Run:
```bash
node -e "const fs = require('fs'); const html = fs.readFileSync('templates/index.html', 'utf8'); const script = html.substring(html.indexOf('<script>') + 8, html.indexOf('</script>')); new Function(script); console.log('JavaScript syntax OK!');"
git add templates/index.html
git commit -m "Feat: autocomplete-sökning och kursförslag i portföljvyn"
```

---

### Task 3: Verifiering och Slutkontroll

- [ ] **Step 1: Kör alla unittester**

Run: `python3 -m unittest discover tests`

- [ ] **Step 2: Commit och deploy-redo**
