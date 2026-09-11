# Designspecifikation: Beslutsstöd 360 & Aktiebacktest

**Datum:** 2026-09-11  
**Status:** Godkänd av användare

---

## 1. Bakgrund & Problemformulering

Nuvarande backtest-motor och signalmodell i Aktieanalys simulerar en portfölj med en stel swing-strategi (utbrott eller RSI-pullback) över hela OMXS30/Nasdaq100 samtidigt med max 5 samtidiga innehav. Huvudsyftet var pedagogiskt ("index sparande slår timing"), vilket innebär att användaren inte får något praktiskt beslutsstöd när hen vill köpa eller sälja specifika aktier.

### Mål
Förvandla verktyget till ett aktivt beslutsstöd ("Beslutsstöd 360") som:
1. Identifierar konkreta affärsmöjligheter **idag** baserat på beprövade strategier (Kvalitets-dipp, Momentum-utbrott, Långsiktig trendföljare).
2. Ger aktiespecifik historisk edge (träffsäkerhet, vinstfaktor, snittavkastning) direkt i bolagsanalysen.
3. Tillhandahåller ett interaktivt backtest för både enskilda aktier och hela marknadsportföljer med valbara strategier.
4. Levererar en konkret handelsplan för varje signal: föreslagen ingångskurs, stop-loss, målkurs och Risk/Reward-kvot.

---

## 2. Strategimodeller

Tre beprövade och komplementära strategier implementeras i [`src/core/backtest.py`](file:///home/alun/aktieanalys/src/core/backtest.py) och [`src/core/signals.py`](file:///home/alun/aktieanalys/src/core/signals.py):

### Strategi 1: Kvalitets-dipp i uppåttrend (Mean Reversion)
* **Syfte:** Köpa stabila bolag i långsiktig upptrend när de tillfälligt rekylerar nedåt.
* **Köp-villkor:**
  - Långsiktig trend: `Close > MA200` och `MA200 >= MA200[20 dgr sedan] * 0.998`.
  - Rekyl: `RSI(14) <= 38` eller `Low <= MA50 * 1.01` och `Close > Low`.
  - Vändningstecken: Dagens stängning är högre än gårdagens lägsta (`Close > Low[1]`) eller grön dagsstapel (`Close > Open`).
* **Sälj-villkor:**
  - Vinstmål / exit: `RSI(14) >= 65` eller kurs når `Entry + 2.0 * ATR` eller `holding_days >= 20`.
  - Stop-loss: `Entry - 2.5 * ATR`.

### Strategi 2: Momentum & Utbrott (Swing-trading)
* **Syfte:** Fånga aktier med stark acceleration och stigande volym.
* **Köp-villkor:**
  - Utbrott: `Close > max(High[20])` eller `max(High[50])` för gårdagens staplar.
  - Volymbekräftelse: `Volume > 1.35 * SMA(Volume, 20)`.
  - Trendhierarki: `Close > MA50 > MA200`.
* **Sälj-villkor:**
  - Trailing stop: Kurs stänger under `MA20` eller faller under `Högsta kurs sedan köp - 3.0 * ATR`.
  - Vinsthemtagning: `RSI(14) >= 78` eller `holding_days >= 25`.
  - Initial stop-loss: `Entry - 2.5 * ATR`.

### Strategi 3: Långsiktig Trendföljare (Positionsinvestering)
* **Syfte:** Hålla vinnare i stora strukturella uppgångar och undvika björnmarknader.
* **Köp-villkor:**
  - Trendsignal: `MA50 > MA200` (Golden Cross) eller `Close > MA200` efter att ha legat under, med bekräftad uppåtlutning.
* **Sälj-villkor:**
  - Trendbrott: `Close < MA200 * 0.98` (2 % buffert) eller Death Cross (`MA50 < MA200`).

---

## 3. Arkitektur & Komponenter

```mermaid
flowchart TD
    DB[(SQLite: history)] --> StratEngine[Strategimotor: src/core/backtest.py]
    StratEngine --> OppScanner[Scanner för Dagens Möjligheter: src/core/signals.py]
    StratEngine --> SingleBacktest[Aktiespecifikt Backtest: src/core/backtest.py]
    StratEngine --> PortfolioBacktest[Portföljbacktest: src/core/backtest.py]

    OppScanner --> API_Opp[/api/opportunities]
    SingleBacktest --> API_SingleBt[/api/backtest/stock]
    PortfolioBacktest --> API_PortBt[/api/backtest]

    API_Opp --> View_Opp[Flik: Affärsmöjligheter]
    API_SingleBt --> View_Analyze[Flik: Analysera bolag]
    API_SingleBt --> View_Bt[Flik: Backtest]
    API_PortBt --> View_Bt
```

### 3.1 Backend: [`src/core/backtest.py`](file:///home/alun/aktieanalys/src/core/backtest.py)
* **`run_single_stock_backtest(symbol, strategy='dip', years=5)`:**
  - Kör vald strategi isolerat på en aktie.
  - Returnerar:
    - Nyckeltal: `trades_count`, `win_rate`, `profit_factor`, `cagr`, `total_return`, `max_drawdown`, `avg_gain_pct`, `avg_loss_pct`, `avg_days_held`.
    - Jämförelse: `buy_and_hold_return` för samma aktie.
    - `trades`: Lista över alla genomförda affärer med entry-datum, exit-datum, priser, avkastning och orsak.
    - `equity_curve`: Utveckling för strategin vs buy & hold.
* **`run_portfolio_backtest(market='omxs', strategy='dip', years=5)`:**
  - Utökar den befintliga portföljsimuleringen med valbar strategi (`dip`, `momentum`, `trend`).

### 3.2 Backend: [`src/core/signals.py`](file:///home/alun/aktieanalys/src/core/signals.py)
* **`scan_opportunities(market='all')`:**
  - Går igenom alla aktier i databasen för OMXS och Nasdaq.
  - Undersöker om dagens dagsstapel uppfyller köpvillkor för Strategi 1, 2 eller 3.
  - För varje kandidat beräknas:
    - `symbol`, `name`, `market`, `currency`, `close`
    - `strategy`: identifierad strategi (`dip`, `momentum`, `trend`)
    - `signal_reason`: beskrivande text om varför signalen triggats
    - `edge`: historisk statistik för just den aktien under de senaste 5 åren (win rate %, antal trades, profit factor)
    - `levels`:
      - `entry_price`: Rekommenderad ingångsnivå
      - `stop_loss`: Kurs och procentrisk (`-X.X %`)
      - `target_price`: Målkurs och procentpotential (`+Y.Y %`)
      - `risk_reward`: Beräknad R:R (t.ex. `1 : 2.2`)

### 3.3 API Endpoints: [`src/api/routes.py`](file:///home/alun/aktieanalys/src/api/routes.py)
1. **`GET /api/opportunities?market=all&strategy=all`**  
   Returnerar dagens köpkandidater rankade efter edge och risk/reward.
2. **`POST /api/backtest/stock`**  
   Body: `{ symbol: "INVE-B.ST", strategy: "dip", years: 5 }`  
   Returnerar komplett aktiebacktest.
3. **`POST /api/backtest`**  
   Body: `{ market: "omxs", strategy: "dip", years: 5 }`  
   Utökad med fältet `strategy`.

### 3.4 Frontend: [`templates/index.html`](file:///home/alun/aktieanalys/templates/index.html)
1. **Ny flik "Affärsmöjligheter" i toppmenyn:**
   - Filterfält: Marknad (Alla, Stockholm, USA), Strategi (Alla, Kvalitets-dipp, Momentum, Långsiktig trend).
   - Informationsrika kort för varje köpkandidat med tydliga badges, nivåer (Entry, Stop, Target, R:R) och historisk träffsäkerhet.
   - Snabblänk till att fördjupa sig i aktien eller se dess affärslogg.
2. **Förbättring av "Analysera bolag":**
   - Ny sektion: "Statistisk Edge & Dagens Signalläge".
   - Visar aktiv signal om sådan finns idag.
   - Visar en tabell/sammanställning av aktiens historiska prestanda på de 3 strategierna.
   - Knapp för att köra aktiebacktest direkt i vyn.
3. **Uppdaterad "Backtest"-flik:**
   - Väljare mellan "Hela marknaden" och "Enskild aktie".
   - Dropdown för strategival.
   - Graf som jämför strategin med att hålla aktien/indexet.
   - Interaktiv affärslista.

---

## 4. Felhantering & Edge Cases

* **Otillräcklig historik:** Om en aktie har mindre än 200 handelsdagar flaggas detta och strategier som kräver MA200 ger ingen signal.
* **Hög volatilitet / Extrem stop-loss:** Om beräknad stop-loss blir orimligt djup (> 15 %) justeras eller flaggas signalen som hög risk.
* **Risk/Reward-kontroll:** Signaler där potentiell vinst är lägre än risken (R:R < 1:1) sorteras bort eller varnas för.
* **Inga dagliga signaler:** Om marknaden är stendöd eller i allmän nedgång visas ett tydligt meddelande: *"Inga aktier uppfyller kriterierna idag. Tålamod är en dygd i aktiemarknaden."*

---

## 5. Verifiering & Testning

1. **Enhetstester och dataintegritet:**
   - Verifiera att signalberäkning inte har framåtblickande fel (lookahead bias) – köp triggas på dagens stängning och exekveras till morgondagens öppning eller stängningskurs.
   - Verifiera korrekta formler för Win Rate, Profit Factor, ATR och Drawdown.
2. **Backtesting-tester:**
   - Körning mot kända bolag (Investor B, Volvo B, Apple, Microsoft) med verifiering av affärslistor.
3. **API-tester:**
   - Validera endpoints via curl/HTTP-anrop (`/api/opportunities`, `/api/backtest/stock`, `/api/backtest`).
4. **UI-validering:**
   - Verifiera rendering i webbläsaren för alla tre vyer (Affärsmöjligheter, Analysera bolag, Backtest).
