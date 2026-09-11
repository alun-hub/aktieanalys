# Designspecifikation: Bolagssökning & Autocomplete i Portföljvyn

**Datum:** 2026-09-11  
**Status:** Godkänd av användare

---

## 1. Bakgrund & Problemformulering
I nuvarande version av "Min portfölj" måste användaren mata in exakt ticker-symbol (t.ex. `INVE-B.ST` eller `AAPL`). Det är opraktiskt för privatinvesterare som tänker i bolagsnamn (t.ex. "Investor", "Volvo", "Handelsbanken", "Apple").

### Mål
1. Göra det möjligt att söka fram bolag med fritext i portföljformuläret.
2. Visa en snabb autocomplete-rullgardinslista med bolagsnamn och ticker under sökfältet.
3. Vid val av bolag: automatiskt fylla i ticker, bolagsnamn samt föreslå dagsaktuell kurs i fältet för snittpris (GAV).
4. Om användaren skriver ett bolagsnamn och direkt trycker "Lägg till / uppdatera" ska backend automatiskt mappa namnet till rätt ticker via `resolve_symbol`.

---

## 2. Arkitektur & Komponenter

### 2.1 Backend: [`src/api/routes.py`](file:///home/alun/aktieanalys/src/api/routes.py) & [`src/core/portfolio.py`](file:///home/alun/aktieanalys/src/core/portfolio.py)
* I `portfolio_add_route()` i `src/api/routes.py`:
  - Använd `resolve_symbol(symbol)` från `src.core.analysis` för att mappa eventuella bolagsnamn (t.ex. "investor" -> `INVE-B.ST`, "volvo" -> `VOLV-B.ST`) om inte symbolen redan är en exakt ticker.
  - Om bolagsnamn saknas: hämta ett snyggt visningsnamn automatiskt från `_known_name` eller Yahoo.

### 2.2 Frontend: [`templates/index.html`](file:///home/alun/aktieanalys/templates/index.html)
* **HTML:**
  - Gör om ticker-fältet till ett sökfält med positionering för en svävande resultatlista:
    `<div class="field" style="position:relative;">`
    `<label>Bolag / Ticker</label>`
    `<input id="pf-sym" placeholder="Sök bolag (t.ex. Investor, Apple)…" autocomplete="off">`
    `<input type="hidden" id="pf-symbol-val">`
    `<div id="pf-search-dropdown" class="dropdown-menu hidden"></div>`
* **CSS:**
  - Enkel ren styling för dropdown-menyn: absolut positionerad under fältet med bakgrundsfärg, skugga, z-index och hover-effekter.
* **JavaScript:**
  - Eventlistener på `input` i `#pf-sym` med debounce (200ms).
  - Anropar `/api/portal/search?q=...` och renderar listan över träffar.
  - Vid klick på träff:
    - Sätt texten i `#pf-sym` till bolagsnamnet.
    - Spara tickern i `#pf-symbol-val`.
    - Hämta dagsaktuell kurs och sätt som förslag i `#pf-gav` om fältet är tomt.
    - Dölj dropdownen.
  - Stäng dropdownen vid klick utanför eller Escape.
  - I `addHolding()`: Använd det valda ticker-värdet (eller fall back till texten i `#pf-sym`).

---

## 3. Verifiering & Testning
1. Enhetstest för `portfolio_add_route` med fritext-namn (t.ex. `{"symbol": "investor", "qty": 10, "avg_price": 250}`).
2. JS-syntaxvalidering.
3. Testkörning och verifiering.
