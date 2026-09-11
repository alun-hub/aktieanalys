# Genomförandeplan: Träffsäkrare prognoser och maximerad vinst

**Datum:** 2026-09-11 22:59  
**Specifikation:** `docs/superpowers/specs/2026-09-11-high-accuracy-forecasting-design.md`

---

## Översikt över Tasks

- **Task 1: Marknadsregim-modul (`src/core/regime.py`)**
  - Identifierar om marknaden (OMXS30 / Nasdaq-100) befinner sig i Bull Market, Korrektion eller Bear Market baserat på MA200 och MA50.
  - Enhetstester i `tests/test_regime.py`.

- **Task 2: Relativ Styrka (`src/core/relative_strength.py`)**
  - Beräknar Mansfield Relative Strength (MRS) för en aktie relativt dess benchmark-index.
  - Enhetstester i `tests/test_relative_strength.py`.

- **Task 3: OBV-volymkonfluens i strategimotorn (`src/core/backtest.py`)**
  - Uppdaterar `prep_strategy_signals` så att "Dipp" kräver positiv/neutral OBV-ackumulering under rekyl och "Momentum" kräver volymspik + nytt OBV-högsta.
  - Enhetstester i `tests/test_backtest.py`.

- **Task 4: Kvalitetsspärr, Marknadsregim & Dynamiska Nivåer i `src/core/signals.py`**
  - Uppdaterar `calculate_trade_levels` med Mål 1 (TP1, 50% delvinst + Breakeven-regel) och Mål 2 (TP2 + Trailing Chandelier Stop).
  - Uppdaterar `scan_opportunities` med kvalitetsspärr (win-rate ≥ 55%, profit factor ≥ 1.4, trades ≥ 5, MRS ≥ 0 och marknadsregim).
  - Enhetstester i `tests/test_signals.py` och `tests/test_api_endpoints.py`.

- **Task 5: Frontend UI-stöd i `templates/index.html`**
  - Visar marknadsregim-status i toppen av `Möjligheter`.
  - Visar Ledaraktie RS-badge, TP1 (delvinst 50%) och TP2 (fullt mål).

- **Task 6: Fullständig verifiering, Git Push och Deploy till `gnarg`**
  - Kör hela testsviten (`python3 -m unittest discover tests`).
  - Git push till GitHub och deploy via SSH till `gnarg`.
  - Live-verifiering med curl mot Ingress.

---

## Detaljerade Task-specifikationer

### Task 1: Marknadsregim-modul (`src/core/regime.py`)
- **Filer:**
  - Skapa: `src/core/regime.py`
  - Test: `tests/test_regime.py`
- **Steg:**
  1. Skriv felande test i `tests/test_regime.py`:
     - Testa `get_market_regime("omx")` och `get_market_regime("nasdaq")` med mockade indexrader.
     - Verifiera klassificering som `bull` när close > ma200 och ma50 > ma200 * 0.98.
     - Verifiera klassificering som `bear` när close < ma200.
  2. Implementera `src/core/regime.py`:
     - Hämtar senaste rader för `^OMX` och `^NDX` från `history` i SQLite.
     - Returnerar status, index_close, ma50, ma200, is_bull, regime_label och text.
  3. Kör `python3 -m unittest tests/test_regime.py` och verifiera att testerna passerar.
  4. Committa: `feat(regime): lägg till marknadsregim-modul för OMX och Nasdaq`.

### Task 2: Relativ Styrka (`src/core/relative_strength.py`)
- **Filer:**
  - Skapa: `src/core/relative_strength.py`
  - Test: `tests/test_relative_strength.py`
- **Steg:**
  1. Skriv felande test i `tests/test_relative_strength.py`:
     - Skapa syntetiska DataFrame-serier för aktie och index.
     - Verifiera att `calculate_mansfield_rs(stock_series, index_series, period=50)` beräknar korrekt MRS och identifierar om aktien är outperformer ($MRS > 0$).
  2. Implementera `src/core/relative_strength.py`:
     - Funktioner `calculate_mansfield_rs(stock_df, index_df)` och `get_stock_relative_strength(symbol, market)`.
  3. Kör `python3 -m unittest tests/test_relative_strength.py`.
  4. Committa: `feat(rs): lägg till Mansfield Relative Strength analys`.

### Task 3: OBV-volymkonfluens i strategimotorn (`src/core/backtest.py`)
- **Filer:**
  - Ändra: `src/core/backtest.py`
  - Test: `tests/test_backtest.py`
- **Steg:**
  1. Uppdatera `prep_strategy_signals` i `src/core/backtest.py`:
     - Beräkna OBV (On-Balance Volume) om kolumnen saknas.
     - I dipp-strategin: kontrollera att OBV inte kraschar (20-dagars OBV lutning $\ge -0.05$).
     - I momentum-strategin: bekräfta utbrott med volymspik $\ge 1.35 \times$ och nytt 20d högsta i OBV.
  2. Kör `python3 -m unittest tests/test_backtest.py`.
  3. Committa: `feat(strategy): lägg till OBV volymkonfluens för dipp och momentum`.

### Task 4: Kvalitetsspärr, Marknadsregim & Dynamiska Nivåer (`src/core/signals.py`)
- **Filer:**
  - Ändra: `src/core/signals.py`
  - Test: `tests/test_signals.py`, `tests/test_api_endpoints.py`
- **Steg:**
  1. Uppdatera `calculate_trade_levels`:
     - Lägg till `tp1` (mål 1 vid $2.2 \times ATR$, sälj 50% och flytta stop till breakeven).
     - Lägg till `tp2` (mål 2 vid $4.5 \times ATR$, glidande trailing stop).
     - Lägg till `trailing_rule`.
  2. Uppdatera `scan_opportunities`:
     - Hämta marknadsregim via `get_market_regime`.
     - Beräkna relativ styrka MRS via `get_stock_relative_strength`.
     - Applicera kvalitetsfilter: `win_rate >= 55.0`, `profit_factor >= 1.40`, `trades_count >= 5`.
     - Inkludera marknadsregim-information och RS i resultatet.
  3. Kör tester och verifiera.
  4. Committa: `feat(signals): kvalitetsspärr, marknadsregim och 50% TP trailing stop`.

### Task 5: Frontend UI-stöd i `templates/index.html`
- **Filer:**
  - Ändra: `templates/index.html`
- **Steg:**
  1. I `pane-opportunities`:
     - Rendera en elegant marknadsregim-banner: `🟢 Marknadsläge: Bull Market (OMXS30 / Nasdaq i upptrend)` eller `🟠 Försvarsläge: Marknadskorrigering`.
  2. I varje möjlighetskort:
     - Rendera RS-badge (t.ex. `Ledaraktie +3.5%`).
     - Uppdatera nivårutan med:
       - **Entry**: kurs
       - **Stop-loss**: initial stop
       - **Delmål 1 (50%)**: kurs + $2.2 \times ATR$ (breakeven flytt)
       - **Slutmål 2 (50%)**: kurs + $4.5 \times ATR$ (trailing stop)
  3. Verifiera i webbläsare/tester.
  4. Committa: `feat(ui): visa marknadsregim och dynamiska TP1/TP2 i möjligheter`.

### Task 6: Deploy & Live-verifiering
- **Filer:** N/A
- **Steg:**
  1. Kör `python3 -m unittest discover tests`.
  2. Kör `git push origin main`.
  3. Kör `ssh gnarg "cd /home/alun/aktieanalys && git pull origin main && ./deploy.sh"`.
  4. Verifiera pods med `kubectl get pods`.
  5. Verifiera curl mot `/api/portal/opportunities`.
