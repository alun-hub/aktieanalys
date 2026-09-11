# Designspecifikation: Träffsäkrare prognoser och maximerad vinst

**Datum:** 2026-09-11 22:58  
**Status:** Utkast för godkännande  
**Syfte:** Höja modellens träffsäkerhet (win-rate) och vinstfaktor genom att eliminera falska signaler, filtrera bort marknadsbreda björnmarknader, välja marknadsledare (relativ styrka) och låta vinnare löpa med dynamisk stop/delvinst.

---

## 1. Bakgrund & Problemformulering

Nuvarande signalmodell genererar affärsmöjligheter och köprekommendationer baserat på enskilda aktiers isolerade tekniska indikatorer (RSI, MA-nivåer och 20-dagars utbrott). Detta medför tre systematiska svagheter:
1. **Marknadsrisk ignoreras:** En aktie kan få köpsignal trots att hela börsen (OMXS30/Nasdaq) är i en aggressiv nedtrend. I fallande marknader misslyckas uppemot 70–80 % av alla köpsignaler.
2. **Underpresterare rekommenderas:** Svaga bolag som dippar djupare än index handlas ofta ner ytterligare ("fallande knivar").
3. **För tidig vinsthemtagning & fasta exits:** Fasta vinstmål klipper av stora vinnare för tidigt, vilket sänker portföljens totala vinstfaktor.
4. **Saknar volymkonfluens:** Dippar och utbrott kontrollerar inte om institutionellt kapital (Smart Money) faktiskt ackumulerar aktien.

---

## 2. Arkitektur & Nya Komponenter

```
┌─────────────────────────────────────────────────────────────┐
│                       Marknadsregim                         │
│   OMXS30 / Nasdaq-100 över MA200 & stigande 50d-lutning     │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Endast köp vid Bull-regim)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  Relativ Styrka (Mansfield RS)               │
│   Aktie vs Benchmark-index (Endast ledaraktier med MRS > 0) │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Volym- & Priskonfluens                      │
│   Teknisk setup + Positiv OBV-ackumulering / Volymspik      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  Strikt Statistisk Edge-spärr               │
│   Minst 55-60% historisk win-rate & vinstfaktor ≥ 1.4       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               Dynamiska Nivåer (Risk/Reward)                │
│   50% delvinst vid TP1 + Breakeven + Glidande Chandelier     │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Detaljerad funktionsbeskrivning

### 3.1 Marknadsregim-filter (`src/core/regime.py`)
- **Indata:** Prishistorik för `^OMX` (Sverige) och `^NDX` (USA) från SQLite-databasen `history`.
- **Regler:**
  - `Bull Market`: $Index > MA200$ och $MA50 > MA200 \times 0.98$. Köpsignaler är fullt aktiva.
  - `Korrektion / Osäkerhet`: $Index > MA200$, men $MA50 < MA200$ eller $Index < MA50$. Varning flaggas, endast dipp i superstarka bolag tillåts.
  - `Bear Market`: $Index < MA200$. Nya köpsignaler i `Möjligheter` blockeras eller markeras med "Hög marknadsrisk - avvakta".
- **API/Gränssnitt:** `get_market_regime(market="all") -> dict`

### 3.2 Relativ Styrka mot Index (`src/core/relative_strength.py`)
- **Mansfield Relative Strength (MRS):**
  $$RS(t) = \frac{Price_{Aktie}(t)}{Price_{Index}(t)}$$
  $$MRS(t) = \left(\frac{RS(t)}{SMA_{50}(RS)(t)} - 1\right) \times 100$$
- **Tolkning:**
  - $MRS > +2.0$: **Stark ledaraktie** (outperformer). Prioriteras högst i `Möjligheter`.
  - $-2.0 \le MRS \le +2.0$: Följer index.
  - $MRS < -2.0$: **Underperformer**. Sorteras bort från köplägen.

### 3.3 OBV Volymackumulering (`src/core/analysis.py` / `src/core/backtest.py`)
- För strategin **Dipp**:
  - $OBV_{20d}$ ska ha stigande eller neutral lutning medan priset dippar (visar att säljtrycket sker på låg volym och att köpare ackumulerar).
- För strategin **Momentum**:
  - Volym på utbrottsdagen $\ge 1.4 \times$ 20-dagars medelvolym samt att OBV sätter nytt 20-dagars högsta.

### 3.4 Strikt kvalitetsgräns för "Dagens Möjligheter" (`src/core/signals.py`)
- Aktier kvalificerar sig till listan i `Möjligheter` endast om:
  1. Historisk win-rate i backtest $\ge 55\ \%$ (rekommenderat $\ge 60\ \%$ för dipp).
  2. Profit factor $\ge 1.40$.
  3. Minst 5 avslutade historiska affärer under 5-årsperioden.
  4. Relativ styrka $MRS \ge 0$.
  5. Marknadsregimen för respektive marknad är inte i Bear Market.

### 3.5 Dynamiska Handelsnivåer (50 % TP + Trailing Stop)
- I `calculate_trade_levels`:
  - **Stop-loss initial:** $Close - 2.2 \times ATR$.
  - **Mål 1 (TP1 - 50 % av positionen):** $Close + 2.2 \times ATR$.
    - *Regel:* När TP1 nås flyttas stop-loss upp till *Breakeven* (ingångskurs). Affären blir 100 % riskfri.
  - **Mål 2 (TP2 / Slutmål - 50 %):** $Close + 4.5 \times ATR$.
  - **Glidande Chandelier Stop:** För återstående halva flyttas stop-loss upp längs $HighestHigh_{10} - 2.2 \times ATR$.

---

## 4. Användargränssnitt (UI-ändringar)

1. **Marknadsläges-indikator i header för Möjligheter:**
   - Visar tydlig status: `🟢 Marknadsläge: Bull Market (OMXS30 > MA200)` eller `🔴 Varning: Björnmarknad råder`.
2. **Kortvy för Affärsmöjligheter:**
   - Ny badge: `Ledaraktie (RS +4.8%)`.
   - Konfluens-checklista: `✓ Prisreaktion ✓ Volymackumulering (OBV) ✓ Marknadsstöd`.
   - Handelsnivåer visar både TP1 (Delmål 50% + Breakeven) och TP2 (Fullt mål / Trailing stop).

---

## 5. Teststrategi & Verifiering

- **Enhetstester:**
  - `tests/test_regime.py`: Verifiera korrekt regimklassificering (Bull, Correction, Bear) mot syntetiska och historiska indexkurser.
  - `tests/test_relative_strength.py`: Verifiera Mansfield RS beräkning och att ledaraktier identifieras korrekt.
  - `tests/test_signals_confluence.py`: Verifiera att OBV- och regimfilter effektivt sållar bort svaga signaler och att handelsnivåerna med TP1/TP2 beräknas korrekt.
  - Kör hela testsviten (`python3 -m unittest discover tests`).
- **Live-verifiering:**
  - Bygg och driftsätt på `gnarg` via SSH.
  - Verifiera att fliken `Möjligheter` visar kvalitetsfiltrerade lägen och marknadsregim.
