# Byggplan: Blandad fond/ETF/aktie/utdelningsportfölj med regimstyrda köp- och säljförslag

> **Läsanvisning för den kodande modellen:** Detta dokument är skrivet för att vara
> självständigt läsbart utan tillgång till chatthistoriken som ledde fram till det.
> Alla filreferenser är verifierade mot kodbasen vid skrivtillfället (2026-09-12).
> Läs alltid det faktiska innehållet i refererade filer innan du ändrar dem — appen
> har utvecklats en del och vissa detaljer kan redan skilja sig.

## 1. Bakgrund och mål

Appen (`aktieanalys`, Flask + yfinance + SQLite) gör idag teknisk analys och
enaktie-backtest på svenska/amerikanska aktier. Målet med detta arbete är att bygga
om den till att ge **köpförslag på en blandning av breda ETF:er/fonder, enskilda
utdelningsaktier och tillväxt-/momentumaktier**, viktat efter marknadsregim och
koncentrationsrisk — samt att **flagga (aldrig auto-exekvera) sälj/trimma** när
marknaden vänder.

Bakgrund till varför blandningen behövs (inte bara "köp en global indexfond"):
Cap-viktade globala indexfonder (MSCI World / FTSE All-World) hade i
2025/2026 ca 70 % USA-vikt och de sju stora AI/tech-bolagen ("Magnificent 7")
utgjorde ~20–22 % av hela MSCI World (upp från 18 % 2023) och ~34 % av S&P 500.
En "diversifierad global fond" är alltså i praktiken en koncentrerad satsning på
ett fåtal AI-exponerade bolag. Om AI-drivna värderingar vänder ner slår det
oproportionerligt hårt på just den delen av en indexportfölj. Lösningen är inte
att tajma bort tech helt (ingen kan tillförlitligt tajma en bubbla), utan att:

1. Aktivt minska koncentrationsrisken (equal-weight, ex-US, utdelning som
   motvikt) istället för att blint lita på cap-viktning.
2. Använda regimfiltret som redan finns i appen (`src/core/regime.py`) för att
   dämpa/öka aktieandelen mot ETF/kassa, snarare än att försöka pricka toppen.
3. Ge **förslag**, aldrig automatisk exekvering av sälj — användaren beslutar.

**Explicit icke-mål:** Detta system ska INTE hävda att det kan slå ett globalt
index med säkerhet. Det ska vara transparent regelbaserat, backtestat ärligt,
och tydligt kommunicera osäkerhet i UI-texter.

## 2. Nulägesinventering — vad finns redan (återanvänd, bygg inte om)

Detta är en väsentligt mer mogen kodbas än ett minimalt scaffold. Läs dessa
filer innan du skriver ny kod — mycket av grundinfrastrukturen finns redan:

| Funktion | Fil | Status |
|---|---|---|
| ETF-universum (30+ st, taggade region+sektor) | `src/core/config.py:126-158` (`POPULAR_ETFS`) | **Finns redan.** Innehåller bl.a. `VT` (global total world), `VWCE.DE`/`IWDA.AS` (MSCI World), `EMIM.AS` (EM), `SCHD` (US utdelning), `GLD`/`4GLD.DE` (guld), `TLT` (räntor), `XACT-BEAR-2.ST` (hedge). **Saknas:** ett equal-weight S&P 500-alternativ (t.ex. `RSP`) — lägg till. |
| Svenska fonder (för portföljmatchning) | `src/core/config.py` (`POPULAR_SWEDISH_FUNDS`) | Finns, med `fee_pct` och `aliases`. |
| Index för regimbedömning | `src/core/config.py:121-124` (`INDEX_TICKERS`) | `^OMX`, `^NDX`. Saknar en global-indexproxy (t.ex. `^GSPC` eller `URTH`/`VT`) — behövs om vi vill regimbedöma "globalt läge" separat från OMX/Nasdaq. |
| Marknadsregim (bull/bear/correction) | `src/core/regime.py` — `get_market_regime(market)` (rad 76) | Finns, cachead 30 min, baserat på index vs MA50/MA200. Returnerar `{regime, is_bull, allow_buys, label, badge, description}`. |
| Utdelningsscoring | `src/core/dividends.py` — `score_dividend_stock(yield_pct, payout_ratio, pe, trend_score_val)` (rad 12) och `get_top_dividend_stocks(market, limit, force_refresh)` (rad 156) | Finns och är API-exponerad (`GET /api/top-dividends`). **Begränsning:** verifiera var `payout_ratio`/`pe` faktiskt hämtas ifrån — yfinance `.info`-fält är notoriskt opålitliga (saknas ofta för icke-amerikanska bolag). Läs igenom hela filen innan du bygger vidare; TTL-cache finns redan (`_DIVIDEND_CACHE`, 1h). |
| Relativ styrka (Mansfield RS) | `src/core/relative_strength.py` — `calculate_mansfield_rs`, `get_stock_relative_strength(sym, market)` | Finns, mäter aktie vs index. |
| Momentum/dip/trend-signaler + edge-filter | `src/core/signals.py` — `scan_opportunities(market, strategy_filter)` (rad 186) | Finns. Kräver ≥5 historiska trades med win-rate ≥50 % och profit factor ≥1.3 innan en signal visas (kvalitetsspärr). Kombinerar redan RS-data. |
| Enaktie-backtest med ärlig kostnadsmodell | `src/core/backtest.py` (767 rader) | Finns: nästa-dags-öppning-fills, courtage/spread/FX (`src/core/costs.py`), walk-forward-optimerare (`OMXS_CONFIGS`), `simulate_stock_trades` för isolerad edge-mätning. **Saknar:** portföljnivå-simulering över flera tillgångsslag samtidigt (se Fas 4). |
| Portfölj (verkliga innehav) | `src/core/portfolio.py` — `add_holding(..., kind="aktie"|"fond", fee_pct, region)`, `list_holdings()`, `portfolio_health()` | Finns. `kind='fond'` och `fee_pct` hanteras redan för ägda innehav — men detta är en hälsokoll för det du ÄGER, inte ett rekommendationssystem för vad du BORDE äga. |
| DB-schema | `src/database/schema.sql` | `history` (pris+indikatorer per symbol/dag), `holdings` (ägda positioner). **Saknar** en tabell för målallokering/rekommendationshistorik (se §3). |
| API-endpoints | `src/api/routes.py` | `/api/top-dividends`, `/api/opportunities` (redan kombinerar `scan_opportunities` + `get_market_regime`), `/api/screener`, `/api/backtest`, `/api/portfolio*`. Nya endpoints läggs till på samma Blueprint (`api_bp`). |

**Konsekvens:** Fas "bygg ETF-universum" är i stort sett redan klar. Arbetet
handlar mest om att **koppla ihop** befintliga byggstenar (regim + utdelning +
momentum + ETF-lista) till en gemensam allokeringsmotor, plus att lägga till
fundamentaldata-robusthet och portföljnivå-backtest.

## 3. Datamodellsändringar

Lägg till i `src/database/schema.sql` (kör mot befintlig `history`/`holdings` —
skriv en enkel migration i `src/core/data.py` som gör `CREATE TABLE IF NOT
EXISTS`, following samma mönster som `_archive_legacy_holdings`):

```sql
-- Målallokering per tillgångsklass, en rad per beräkningstillfälle (historik för uppföljning).
CREATE TABLE IF NOT EXISTS allocation_targets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at   TEXT NOT NULL,
    regime        TEXT NOT NULL,            -- 'bull' | 'correction' | 'bear'
    concentration_flag TEXT NOT NULL,       -- 'normal' | 'elevated' | 'high' (se §4.2)
    pct_broad_etf     REAL NOT NULL,
    pct_equalweight_etf REAL NOT NULL,
    pct_dividend_stocks REAL NOT NULL,
    pct_growth_stocks   REAL NOT NULL,
    pct_defensive       REAL NOT NULL,      -- räntor/guld
    note          TEXT
);

-- Sälj/trim-flaggor genererade av regimskiftet, kvitteras manuellt av användaren.
CREATE TABLE IF NOT EXISTS sell_alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    reason        TEXT NOT NULL,            -- t.ex. 'regime_bear', 'atr_stop', 'trend_break'
    severity      TEXT NOT NULL,            -- 'trim' | 'exit'
    acknowledged  INTEGER DEFAULT 0,        -- 0/1, sätts av användaren i UI
    acknowledged_at TEXT
);
```

Ingen ny extern datakälla behövs för pris/indikatorer — allt går via befintlig
`history`-tabell och `yfinance` samma sätt som idag.

## 4. Modul-för-modul-spec (byggordning)

### Fas 0 — Komplettera tillgångsuniversum (litet, gör detta först)

Fil: `src/core/config.py`

- Lägg till minst ett equal-weight-alternativ, t.ex.:
  ```python
  "RSP": {"name": "Invesco S&P 500 Equal Weight ETF", "region": "USA", "sector": "ETF - USA Equal Weight"},
  "XDEW.DE": {"name": "Xtrackers S&P 500 Equal Weight UCITS", "region": "USA", "sector": "ETF - USA Equal Weight"},
  ```
- Lägg till en global indexproxy i `INDEX_TICKERS` för regimbedömning på
  global nivå (separat från OMX/Nasdaq), t.ex. `"URTH": "MSCI World"` eller
  `"^GSPC": "S&P 500"`. Motivera valet i kommentar — `URTH` är en ETF (har
  utdelning/likviditet), `^GSPC` är ett rent indexvärde. Rekommendation:
  använd `^GSPC` för regimbedömning (matchar mönstret för `^OMX`/`^NDX`) men
  `VT`/`IWDA.AS` för faktisk exponeringsdata.
- **Öppet beslut (kräver användarens input, gissa inte):** exakt vilka
  ETF:er som ska ingå i standardallokeringen (svenska/europeiska UCITS vs
  amerikanska tickers) beror på användarens depåtyp (ISK/AF, mäklare). Fråga
  användaren om detta INNAN kodning av Fas 2, annars bygg med `POPULAR_ETFS`
  som redan finns och låt urvalet vara konfigurerbart.

### Fas 1 — Robust fundamentaldata för utdelningsaktier

Fil: `src/core/dividends.py`

1. Läs igenom befintlig `score_dividend_stock` (rad 12) och
   `get_top_dividend_stocks` (rad 156) helt — förstå exakt varifrån
   `yield_pct`/`payout_ratio`/`pe` idag hämtas.
2. Om de hämtas direkt från `yf.Ticker(sym).info` (troligt, då detta är
   standardmönstret): lägg till explicit felhantering — `.info` kan sakna
   nycklar helt (returnerar `None`) eller kasta exception för mindre likvida
   tickers. Nuvarande `score_dividend_stock` hanterar redan `payout_ratio is
   None` → `p_score = 50.0` (neutral gissning), vilket är rimligt — behåll det
   mönstret, förbättra inte i onödan.
3. Lägg till en enkel "utdelningskontinuitet"-signal om den saknas: antal år
   i följd med bibehållen/höjd utdelning, via `yf.Ticker(sym).dividends`
   (tidsserie finns redan tillgänglig via yfinance, ingen ny datakälla). Detta
   är den starkaste enskilda kvalitetsindikatorn för "utdelningsaristokrat"-
   typ av bolag och saknas idag i scoringen.
4. **Testa robusthet**, inte bara happy path: skriv/utöka
   `tests/test_dividends.py` med fall där `.info` returnerar tomt dict eller
   kastar — scoringen får aldrig krascha hela `get_top_dividend_stocks`-loopen
   för en trasig ticker (kolla om `ThreadPoolExecutor`-anropet redan har
   try/except per symbol; om inte, lägg till).

### Fas 2 — Allokeringsmotor (ny modul)

Ny fil: `src/core/allocation.py`

```python
"""Regelbaserad allokering mellan tillgångsklasser.

Detta är INTE en marknadstimingmodell som förutsäger avkastning — det är en
riskhanteringsregel som minskar exponering mot koncentrerad risk (Mag7/US-tech)
och drar ner aktieandel i identifierad björnmarknad. Ingen komponent här ska
tolkas som en prognos.
"""

def assess_concentration_risk() -> dict:
    """Grov proxy för koncentrationsrisk i cap-viktade index.

    Enklaste robusta implementation: hämta prisutveckling senaste 252 dagarna
    för ett urval Mag7-tickers (finns redan i NASDAQ_100 i config.py) kontra
    ett equal-weight-liknande snitt av samma urval. Stor positiv divergens
    (cap-tunga bolag +X% mer än snittet) => 'high'. Detta undviker att behöva
    skrapa faktiska indexvikter (ingen bra fri datakälla för det) och bygger
    enbart på data som redan finns i `history`-tabellen.

    Returnerar t.ex.:
    {"level": "normal"|"elevated"|"high", "spread_pct": float, "detail": str}
    """

def compute_target_allocation(market: str = "all") -> dict:
    """Kombinerar get_market_regime() + assess_concentration_risk() till en
    målfördelning i procent mellan:
      - broad_etf (t.ex. VT/IWDA.AS — bred, cap-viktad global)
      - equalweight_etf (t.ex. RSP/XDEW.DE)
      - dividend_stocks (från get_top_dividend_stocks)
      - growth_stocks (från scan_opportunities)
      - defensive (GLD/TLT/räntefond)

    Startpunkt för regeltabell (JUSTERA EJ utan att fråga användaren — dessa
    procentsatser är en avvägning mellan risk och edge som bara användaren
    kan besluta om):

        regime=bull,  concentration=normal   -> 40/15/20/20/5
        regime=bull,  concentration=elevated -> 30/20/25/15/10
        regime=bull,  concentration=high     -> 20/25/30/10/15
        regime=correction (any concentration) -> 25/20/25/10/20
        regime=bear   (any concentration)     -> 10/10/15/0/65

    Skriv resultatet till `allocation_targets`-tabellen (§3) för historik/
    uppföljning, med `computed_at` = nu.
    """
```

**Viktigt designval:** `assess_concentration_risk` ska bygga på data som
redan finns i `history`-tabellen (inga nya externa API-anrop för indexvikter
— sådan data finns inte gratis och tillförlitligt via yfinance). Om
implementationen visar sig ge orimliga/instabila resultat i test, dokumentera
det tydligt istället för att tvinga fram en siffra — hellre `"level":
"unknown"` än en falsk precision.

### Fas 3 — Enhetlig rekommendationsmotor

Fil: `src/core/signals.py` (utöka, återanvänd `scan_opportunities` internt)

```python
def build_recommendations(market: str = "all") -> dict:
    """Slår ihop allocation.compute_target_allocation() med konkreta
    köpkandidater per tillgångsklass till en enda lista, taggad med `type`:
    'broad_etf' | 'equalweight_etf' | 'dividend_stock' | 'growth_stock' | 'defensive'.

    Broad/equalweight/defensive: hämtas direkt från POPULAR_ETFS (statisk lista,
    ingen scoring behövs — det är indexprodukter, "köp enligt målvikt").
    dividend_stock: från dividends.get_top_dividend_stocks(market, limit=...).
    growth_stock: från signals.scan_opportunities(market, ...) — VIKTA NER
    antalet förslag proportionellt när concentration_flag == 'high' (detta är
    mekanismen som faktiskt svarar på användarens ursprungsfråga: mindre
    exponering mot momentum-drivna US-tech-namn när koncentrationsrisken är hög).

    Returnerar: {"allocation": {...}, "recommendations": [...], "regime": {...},
                 "generated_at": iso_timestamp}
    """
```

Ny endpoint i `src/api/routes.py` (samma mönster som `opportunities_route`,
rad 42-48):

```python
@api_bp.route('/recommendations')
def recommendations_route():
    market = request.args.get('market', 'all')
    return jsonify(build_recommendations(market=market))
```

### Fas 4 — Portföljnivå-backtest (validera INNAN ni litar på Fas 2/3)

Fil: `src/core/backtest.py` (ny funktion, återanvänd `_run_engine`-mönstret
rad 187 där det går)

```python
def run_portfolio_backtest(years: int = 10) -> dict:
    """Simulerar hela allokeringsstrategin (Fas 2-regler applicerade historiskt,
    dag för dag, INGEN lookahead — regimen och koncentrationsflaggan för dag N
    får bara använda data t.o.m. dag N) mot:
      a) 100% köp-och-behåll i en bred global ETF (t.ex. VT eller VWCE.DE)
      b) 100% köp-och-behåll i S&P 500 (cap-viktad, för att visa Mag7-effekten)

    Kostnadsmodell: återanvänd src/core/costs.py rakt av — rebalansering
    mellan tillgångsklasser kostar courtage/spread precis som en aktieaffär.

    Nyckeltal: samma som befintlig run_backtest_local (CAGR, maxDD,
    CAGR/|MaxDD|), PLUS årlig standardavvikelse jämfört mot (a) och (b) för
    att visa om lägre koncentrationsrisk faktiskt gav lägre eller högre
    riskjusterad avkastning historiskt.
    """
```

**Detta är den viktigaste fasen att inte hoppa över.** Utan denna vet varken
appen eller användaren om allokeringsreglerna i Fas 2 faktiskt hjälper eller
bara känns tryggare. Publicera resultatet tydligt i UI innan
rekommendationerna (Fas 3) presenteras som något användaren bör agera på.

**Känd begränsning som MÅSTE kommuniceras i UI-text, inte döljas:**
Backtestet lider fortsatt av survivorship bias för `growth_stocks`-delen
(se `src/core/config.py` — `OMXS_50`/`NASDAQ_100` är dagens bolagslistor,
avnoterade/uppköpta bolag saknas i historiken). ETF-delen (broad/equalweight/
defensive) har INTE detta problem eftersom index-ETF:er redan internt
hanterar bolagsbyten. Skriv detta explicit i disclaimer-texten som visas vid
`/recommendations`.

### Fas 5 — Säljvarningar (endast förslag, ingen auto-exekvering)

Fil: `src/core/regime.py` (utöka) + `src/core/portfolio.py` (koppla in)

```python
def generate_sell_alerts() -> list[dict]:
    """Går igenom pf.list_holdings() (befintlig funktion, portfolio.py rad 141)
    och flaggar per innehav:

    - severity='exit': symbol har kind='aktie' (INTE 'fond' — bred indexfond
      ska normalt behållas genom en cykel, det är hela poängen med den) OCH
      regime.get_market_regime() == 'bear' för dess marknad OCH innehavet
      klassas som growth/momentum (inte utdelningsaktie — se dividends.py-
      scoring för att skilja dem åt).
    - severity='trim': regime == 'correction' för momentumpositioner.
    - reason='atr_stop': återanvänd befintlig ATR_STOP_MULT-logik från
      signals.py rad 11/128 per position.

    Skriver till `sell_alerts`-tabellen (§3) MED acknowledged=0. Skriver ALDRIG
    till holdings-tabellen och utför ALDRIG en faktisk försäljning — appen har
    ingen mäklarintegration och ska inte låtsas ha det.
    """
```

Ny endpoint: `GET /api/sell-alerts` (lista, med `acknowledged`-filter) och
`POST /api/sell-alerts/<id>/acknowledge` (användaren kvitterar — matchar
mönstret i `portfolio_delete_route`, routes.py rad 198).

**Bekräftat med användaren:** enbart förslag, ingen automatisk exekvering.
Bygg INTE en auto-sälj-väg ens bakom en flagga i denna fas.

### Fas 6 — UI-integration

Fil: `templates/index.html` (vanilla JS + Plotly, inget React — följ
befintlig stil för `/opportunities`-vyn som förlaga)

- Ny flik "Rekommendationer": visar `allocation`-donut/stapeldiagram (Plotly,
  redan ett beroende) + lista grupperad per `type`.
- Ny sektion i portföljvyn: "Säljvarningar" med kvittensknapp per rad, kopplad
  mot `/api/sell-alerts`.
- Disclaimer-text (obligatorisk, placera väl synligt ovanför
  rekommendationslistan): kort och ärlig, i stil med existerande
  `signals.py`-dokumentation ("Detta är INTE köp-/säljrekommendationer...").

## 5. Testplan

Följ befintlig konvention (en fil per modul i `tests/`):

- `tests/test_allocation.py` (ny): testa `compute_target_allocation` för alla
  9 kombinationer av regime × concentration, verifiera att procentsatserna
  alltid summerar till 100.
- `tests/test_dividends.py` (utöka): trasig/saknad `.info`-data kraschar inte.
- `tests/test_regime.py` (utöka): `generate_sell_alerts` genererar inga
  'exit'-flaggor för `kind='fond'`-innehav ens i bear-regim.
- Ny portföljbacktest-test: verifiera no-lookahead genom att kontrollera att
  regimen för dag N beräknas enbart från `history`-rader med `date <= N`
  (samma no-lookahead-princip som redan hävdas i `backtest.py`-docstringen
  rad 1-17 — testa att det verkligen stämmer för den nya portföljmotorn).

## 6. Öppna beslut — fråga användaren innan implementation, gissa inte

1. Exakt ETF-urval per tillgångsklass i standardallokeringen (svensk/europeisk
   UCITS vs amerikansk ticker) — beror på kontotyp (ISK/AF/depå hos vilken
   mäklare).
2. Procentsatserna i allokeringstabellen (§4, Fas 2) är ett förslag, inte ett
   beslut — användarens risktolerans avgör hur aggressivt man ska tilta bort
   från cap-viktning.
3. Tröskelvärden för `assess_concentration_risk` (vad räknas som "elevated"
   vs "high" spread) behöver kalibreras mot historisk data innan de låses,
   inte gissas fram.
4. Om `sell_alerts` ska skickas som notis (e-post/push) eller bara visas i
   UI vid nästa besök — inget notissystem finns i appen idag, avgör om det
   är värt att bygga ett innan detta görs.

## 7. Sammanfattning av byggordning

1. Fas 0 (config-tillägg, litet)
2. Fas 1 (utdelningsdata-robusthet)
3. Fas 4 FÖRE Fas 2/3 i praktiken rekommenderas — bygg en enkel version av
   allokeringsreglerna och backtesta dem innan de exponeras som
   rekommendationer i UI, annars riskerar ni att lansera en känsla av edge
   utan att ha verifierat den.
4. Fas 2 (allokeringsmotor, efter backtest-validering)
5. Fas 3 (rekommendationsmotor + endpoint)
6. Fas 5 (säljvarningar)
7. Fas 6 (UI)
