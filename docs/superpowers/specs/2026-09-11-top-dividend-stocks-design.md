# Designspecifikation: Topp 10 Utdelningsaktier

**Datum:** 2026-09-11  
**Status:** Godkänd design  
**Syfte:** Erbjuda en ny flik i appen som rankar de 10 bästa utdelningsaktierna genom att maximera direktavkastning och samtidigt filtrera för god fundamental kvalitet, rimlig värdering och sund teknisk trend (undvika "utdelningsfällor").

---

## 1. Mål & Användarupplevelse

Användaren vill snabbt kunna identifiera de bästa utdelningsaktierna att köpa just nu. Att enbart sortera på högst direktavkastning (yield) leder ofta till s.k. utdelningsfällor (bolag i kris vars kurser kollapsat eller vars utdelning riskerar att sänkas/stoppas).

Systemet ska därför:
1. Skanna bevakade svenska (OMXS Large Cap) och amerikanska aktier (Nasdaq 100).
2. Tillämpa en kvantitativ poängmodell som väger samman direktavkastning, utdelningsandel, värdering och teknisk trend.
3. Presentera en "Topp 10"-lista med valbara marknadsfilter (`Alla`, `Sverige`, `USA`).
4. Erbjuda snabb-navigering till bolagsanalysen för respektive aktie.
5. Ladda blixtsnabbt tack vare bakgrundscaching.

---

## 2. Arkitektur & Komponenter

### 2.1 Ny modul: `src/core/dividends.py`
En isolerad modul med två huvudsakliga ansvarsområden:
1. `score_dividend_stock(...)`: Beräknar ett samlat utdelningsbetyg (0–100) för ett enskilt instrument.
2. `get_top_dividend_stocks(market="all", limit=10, force_refresh=False)`: Hämtar och cachar rankingen per marknad (`omx`, `nasdaq`, `all`).

### 2.2 Beräkningsmodell: Dividend Quality & Value Score (0–100)
Modellen bygger på fyra viktade komponenter:

1. **Direktavkastning (Vikt: 35 %)**
   * 0 %: 0 poäng
   * 1–3 %: 40–70 poäng (godkänd, men måttlig)
   * 3.5–8.0 %: 85–100 poäng (optimal nivå för hållbar hög direktavkastning)
   * 8.0–12.0 %: 70–85 poäng (mycket hög, kräver god utdelningsandel)
   * \> 12.0 %: Avdrag för förhöjd risk för utdelningssänkning/fälla såvida inte vinst och kassaflöde stödjer det fullt ut.

2. **Utdelningsandel / Payout Ratio (Vikt: 25 %)**
   * 30–70 % av vinsten: 100 poäng (idealiskt – bolaget återinvesterar samtidigt som aktieägarna belönas).
   * 70–85 %: 75 poäng (acceptabelt).
   * 85–100 %: 45 poäng (snäv marginal vid sämre konjunktur).
   * \> 100 % eller negativ: 10 poäng (delar ut mer än vad bolaget tjänar – ohållbart).

3. **Värdering & Lönsamhet / P/E (Vikt: 20 %)**
   * P/E 8–18: 90–100 poäng (attraktiv och rimlig värdering).
   * P/E 18–25: 65 poäng.
   * P/E > 30 eller negativ vinst: 20 poäng.

4. **Teknisk Trend & Skydd mot kursfall (Vikt: 20 %)**
   * Använder appens befintliga `trend_score` (MA200, MA200-lutning, EMA20, MACD).
   * Poäng: `(trend_score / 100) * 100`.
   * Motivering: En direktavkastning på 6 % ger ingen vinst om aktien faller 20 % per år. Vi vill äga utdelare som rör sig sidledes eller uppåt.

### 2.3 API Endpoint: `GET /api/portal/top-dividends`
* **Query-parametrar:**
  * `market`: `all` (standard), `omx`, `nasdaq`
  * `limit`: int (standard 10)
  * `refresh`: bool (valfri tvingad omräkning)
* **Svarsstruktur:**
  ```json
  {
    "market": "all",
    "updated_at": "2026-09-11 22:30",
    "stocks": [
      {
        "rank": 1,
        "symbol": "VOLV-B.ST",
        "name": "Volvo B",
        "market": "OMX",
        "currency": "kr",
        "price": 344.20,
        "dividend_yield": 5.4,
        "dividend_score": 88.5,
        "payout_ratio": 58.2,
        "pe": 11.2,
        "trend_score": 64.0,
        "trend_label": "Svag uppåttrend",
        "trend_class": "up",
        "verdict": "Hög utdelning & stabil kvalitet"
      }
    ]
  }
  ```

### 2.4 Cachingstrategi
* Att fråga Yahoo Finance om nyckeltal för ~100 bolag tar 10–20 sekunder om det görs oskyddat.
* Därför sparas resultatet i en in-memory och disk-cache med en TTL på 3600 sekunder (1 timme).
* Cachen förladdas även under den nattliga `sync_all_stocks()` i [`src/core/data.py`](file:///home/alun/aktieanalys/src/core/data.py).

---

## 3. Användargränssnitt (`templates/index.html`)

1. **Navigeringsflik:**
   * Lägg till `["dividends", "Utdelning"]` i `TABS`-listan (placeras logiskt bredvid "Möjligheter" och "Analysera bolag").
2. **Flikinnehåll (`#pane-dividends`):**
   * Header: "Topp 10 Utdelningsaktier" med ingress som förklarar modellen (bästa kombinationen av hög yield, sund utdelningsandel och god trend).
   * Marknadsfilterknappar: `Alla` (aktiv), `Sverige (OMX)`, `USA (Nasdaq)`.
   * Resultatkort/tabell:
     * Rank med medalj/siffra (1–10).
     * Bolagsnamn, ticker och aktuell kurs.
     * Direktavkastning markerad i accentfärg.
     * Total Utdelningspoäng (0–100) med grafisk statusbar.
     * P/E och utdelningsandel i procent.
     * Teknisk trendbadge.
     * Snabbknapp "Analysera" som öppnar bolagsanalysen med ett klick.

---

## 4. Testning & Verifiering

1. **Enhetstester (`tests/test_dividends.py`):**
   * Testa poängmotorns beräkning för optimala värden, orimligt höga utdelningar (>15 %) och negativa utdelningsandelar.
   * Testa marknadsfiltrering (`all`, `omx`, `nasdaq`).
   * Testa cachingmekanismen.
2. **API-tester:**
   * Verifiera att `/api/portal/top-dividends` returnerar statuskod 200 och exakt 10 resultat sorterade fallande på `dividend_score`.
