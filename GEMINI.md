# 📜 GEMINI TRADING PORTAL - MANDATORY RULES

Denna fil innehåller de absoluta kraven för Trading Portalen. Inga ändringar får göras som bryter mot eller raderar dessa komponenter utan uttrycklig instruktion.

## 1. GRÄNSSNITT (UI) - KRITISKA KOMPONENTER
Följande delar i `templates/index.html` får ALDRIG tas bort:

- **Flikar:** Dashboard (Översikt), Backtest (Simulering), README (Dokumentation).
- **Statistik-rad (5 kort):** 
    1. CASH (Klickbar för inställningar).
    2. INNEHAV (Marknadsvärde totalt).
    3. TOTALT (Cash + Innehav).
    4. START (Ursprungligt kapital).
    5. V/F TOTALT (Total vinst/förlust i SEK och %).
- **Köp-lista:** Måste visa `suggested_amount` (SEK) och `suggested_qty` (antal) för varje kandidat.
- **Portfölj-tabell:** Måste innehålla kolumnerna: `Papper`, `Antal`, `Inköp`, `Värde`, `Stop loss`, `V/F %` och `Åtgärder (Edit/Sälj)`.
- **Order-modal (Avanza Expert):** Måste visa två steg:
    - **STEG 1:** Köp-detaljer (Typ, Antal, Trigger, Limit).
    - **STEG 2:** Stop Loss-detaljer (Röd box för omedelbart skydd hos Avanza).

## 2. EKONOMISK LOGIK & RISK
- **Position Sizing:** Varje ny affär ska vara exakt 20% av det totala portföljvärdet.
- **Harmony Buffer:** Alla trendlinje-brott (GM50/GM200) ska ha en marginal på 0.5% för att undvika brus.
- **Newbie Protection:** Inga säljsignaler får genereras på aktier som köptes samma dag (`days_held == 0`).
- **USA Momentum:** Köp triggas endast vid RSI < 40 och en bekräftad vändning uppåt.
- **Sverige Breakout:** Köp triggas vid 20-dagars högsta + Volym-bekräftelse (>1.2x snitt).

## 3. TEKNISK STANDARD
- **Surgical Edits:** Använd `replace` för ändringar i HTML/JS. Skriv aldrig över hela `index.html` om det inte är absolut nödvändigt.
- **Defensive JS:** Använd alltid `fmt()` eller null-checks vid formatering av siffror (`.toFixed`, `Math.round`) för att inte krascha skriptet.
- **AI Brain:** `src/core/ai_bridge.py` måste skicka 20 dagars prishistorik till Gemini för mönsterigenkänning.
- **Global Scope:** Alla JS-funktioner i HTML ska vara fästa vid `window` (t.ex. `window.runBacktest`) för att garantera tillgänglighet.

## 4. ÄNDRINGSPROTOKOLL
Innan varje ny version deployas SKA Gemini kontrollera:
1. Finns Backtest-fliken kvar?
2. Fungerar Köp/Sälj-knapparna?
3. Är alla kolumner i portföljen synliga?
4. Är courtage-inställningarna kvar?
