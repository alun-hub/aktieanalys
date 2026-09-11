# Implementation Plan: Beslutsstöd 360 & Aktiebacktest

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Omvandla backtest och signaler till ett aktivt beslutsstöd ("Beslutsstöd 360") med tre beprövade strategier, en scanner för dagens affärsmöjligheter med konkreta nivåer (Entry, Stop, Target, R:R), aktiespecifikt backtest i bolagsvyn samt flexibelt marknads- och aktiebacktest.

**Architecture:** Modulära strategimodeller (`dip`, `momentum`, `trend`) i `src/core/backtest.py` med unifierad exekverings- och nyckeltalslogik; en scanner i `src/core/signals.py` som läser SQLite-kursdata och kalkylerar dagens signaler med historisk edge och handelsnivåer; REST-endpoints i `src/api/routes.py`; samt responsiv vanilla JS/HTML-frontend i `templates/index.html`.

**Tech Stack:** Python 3, Flask, pandas, numpy, SQLite, vanilla JavaScript, HTML5/CSS3, unittest.

---

### Task 1: Modulära strategimodeller och signalgenerator

**Files:**
- Modify: `src/core/backtest.py:70-100`
- Test: `tests/test_strategies.py`

- [ ] **Step 1: Skriv det felande testet för strategisignaler**

Skapa `tests/test_strategies.py`:
```python
import unittest
import pandas as pd
import numpy as np
from src.core.backtest import prep_strategy_signals

class TestStrategies(unittest.TestCase):
    def setUp(self):
        n = 100
        dates = pd.date_range("2024-01-01", periods=n)
        # Skapa syntetisk data med uppåttrend
        prices = [100.0 + i * 0.5 for i in range(n)]
        self.df = pd.DataFrame({
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 2 for p in prices],
            "close": prices,
            "volume": [10000] * n,
            "ma50": [p - 5 for p in prices],
            "ma200": [p - 20 for p in prices],
            "rsi": [50] * n,
            "atr": [2.0] * n,
        }, index=dates)

    def test_dip_strategy_signals(self):
        # Sätt en dipp-dag: RSI låg, stängning över gårdagens lägsta
        self.df.loc[self.df.index[-1], "rsi"] = 30
        res = prep_strategy_signals(self.df, "dip")
        self.assertIn("entry_sig", res.columns)
        self.assertTrue(bool(res.iloc[-1]["entry_sig"]))

    def test_momentum_strategy_signals(self):
        # Sätt ett utbrott med hög volym
        self.df.loc[self.df.index[-1], "close"] = 300.0
        self.df.loc[self.df.index[-1], "high"] = 305.0
        self.df.loc[self.df.index[-1], "volume"] = 50000
        res = prep_strategy_signals(self.df, "momentum")
        self.assertIn("entry_sig", res.columns)
        self.assertTrue(bool(res.iloc[-1]["entry_sig"]))

    def test_trend_strategy_signals(self):
        res = prep_strategy_signals(self.df, "trend")
        self.assertIn("entry_sig", res.columns)
        # Med close > ma200 och ma50 > ma200 bör trend ge signal
        self.assertTrue(bool(res.iloc[-1]["entry_sig"]))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Kör testet och verifiera att det misslyckas**

Run: `python -m unittest tests/test_strategies.py`  
Expected: ImportError eller AttributeError: `prep_strategy_signals` finns inte.

- [ ] **Step 3: Implementera `prep_strategy_signals` i `src/core/backtest.py`**

Uppdatera signallogiken i `src/core/backtest.py`:
```python
STRATEGIES = {
    "dip": {
        "name": "Kvalitets-dipp i upptrend",
        "desc": "Köp starka bolag i upptrend vid tillfällig rekyl (RSI <= 38 eller test av MA50)",
        "default_rsi_exit": 65,
        "default_max_days": 20,
        "atr_stop_mult": 2.5,
    },
    "momentum": {
        "name": "Momentum & Utbrott",
        "desc": "Köp vid 20/50-dagars utbrott med volymökning och Close > MA50 > MA200",
        "default_rsi_exit": 78,
        "default_max_days": 25,
        "atr_stop_mult": 2.5,
    },
    "trend": {
        "name": "Långsiktig Trendföljare",
        "desc": "Position i stark trend över MA200 med Golden Cross",
        "default_rsi_exit": 85,
        "default_max_days": 252,
        "atr_stop_mult": 3.5,
    }
}

def prep_strategy_signals(g, strategy="dip", **custom_params):
    g = g.copy()
    c = g["close"]
    ma50 = g.get("ma50") if "ma50" in g.columns else c.rolling(50).mean()
    ma200 = g.get("ma200") if "ma200" in g.columns else c.rolling(200).mean()
    rsi = g.get("rsi") if "rsi" in g.columns else pd.Series(50, index=g.index)
    vol = g["volume"]
    prior_vol = vol.rolling(20).mean().shift(1)

    if strategy == "dip":
        # Upptrend + tillfällig rekyl + vändning
        in_uptrend = (ma200.notna()) & (c > ma200 * 0.99) & (ma200 >= ma200.shift(20) * 0.995)
        is_dipping = (rsi <= 40) | (g["low"] <= ma50 * 1.015)
        turnaround = (c > g["low"].shift(1)) | (c > g["open"])
        g["entry_sig"] = in_uptrend & is_dipping & turnaround
        g["entry_rank"] = 50.0 - rsi.fillna(50)  # Lägre RSI = starkare köpläge

    elif strategy == "momentum":
        # 20-dagars högsta + volym + trendhierarki
        prior_high_20 = g["high"].rolling(20).max().shift(1)
        breakout = (c > prior_high_20)
        vol_surge = (vol > prior_vol * 1.3)
        trend_ok = (ma50.notna()) & (ma200.notna()) & (c > ma50) & (ma50 > ma200 * 0.99)
        g["entry_sig"] = breakout & vol_surge & trend_ok
        g["entry_rank"] = (vol / prior_vol.replace(0, np.nan)).fillna(1.0)

    elif strategy == "trend":
        # Golden Cross eller etablerad stängning över stigande MA200
        golden_cross = (ma50 > ma200) & (c > ma200)
        g["entry_sig"] = golden_cross
        g["entry_rank"] = ((c / ma200.replace(0, np.nan)) - 1.0).fillna(0.0)

    else:
        # Fallback till tidigare standard
        g["entry_sig"] = False
        g["entry_rank"] = 0.0

    return g
```

- [ ] **Step 4: Kör testet och verifiera att det passerar**

Run: `python -m unittest tests/test_strategies.py`  
Expected: Ran 3 tests in ... OK.

- [ ] **Step 5: Commit förändringen**

Run:
```bash
git add src/core/backtest.py tests/test_strategies.py
git commit -m "Feat: modulära strategimodeller för dip, momentum och trend"
```

---

### Task 2: Aktiespecifikt Backtest & Nyckeltalsmotor

**Files:**
- Modify: `src/core/backtest.py`
- Test: `tests/test_single_backtest.py`

- [ ] **Step 1: Skriv felande test för `run_single_stock_backtest`**

Skapa `tests/test_single_backtest.py`:
```python
import unittest
import pandas as pd
import numpy as np
from src.core.backtest import simulate_stock_trades, run_single_stock_backtest

class TestSingleStockBacktest(unittest.TestCase):
    def setUp(self):
        n = 300
        dates = [f"2023-{(i//30)+1:02d}-{(i%28)+1:02d}" for i in range(n)]
        dates = sorted(list(set(dates)))[:250]
        n = len(dates)
        prices = [100.0 + i * 0.2 for i in range(n)]
        self.df = pd.DataFrame({
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 2 for p in prices],
            "close": prices,
            "volume": [10000] * n,
            "ma50": [p - 2 for p in prices],
            "ma200": [p - 10 for p in prices],
            "rsi": [50] * n,
            "atr": [2.0] * n,
        }, index=dates)

    def test_simulate_stock_trades(self):
        # Injicera en köpsignal
        self.df.loc[self.df.index[10], "entry_sig"] = True
        self.df["entry_sig"] = self.df["entry_sig"].fillna(False)
        self.df["entry_rank"] = 1.0

        trades, curve, stats = simulate_stock_trades(self.df, strategy="dip")
        self.assertIsInstance(trades, list)
        self.assertIsInstance(stats, dict)
        self.assertIn("win_rate", stats)
        self.assertIn("profit_factor", stats)
        self.assertIn("total_return", stats)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Kör testet och verifiera att det misslyckas**

Run: `python -m unittest tests/test_single_backtest.py`  
Expected: FAIL - `simulate_stock_trades` saknas.

- [ ] **Step 3: Implementera `simulate_stock_trades` och `run_single_stock_backtest` i `src/core/backtest.py`**

Implementera:
```python
def simulate_stock_trades(df, strategy="dip", initial_capital=100_000.0, fee_pct=0.0015):
    """Kör en isolerad handelssimulering för en enskild aktie."""
    strat_cfg = STRATEGIES.get(strategy, STRATEGIES["dip"])
    rsi_exit = strat_cfg["default_rsi_exit"]
    max_days = strat_cfg["default_max_days"]
    atr_mult = strat_cfg["atr_stop_mult"]

    dates = list(df.index)
    trades = []
    cash = initial_capital
    position = None
    curve = []

    for i, date in enumerate(dates):
        r = df.loc[date]
        px_open = float(r["open"]) if not pd.isna(r["open"]) else float(r["close"])
        px_close = float(r["close"])
        atr = float(r["atr"]) if "atr" in r and not pd.isna(r["atr"]) else px_close * 0.02

        # 1. Hantera öppen position (check exit)
        if position:
            position["days"] += 1
            low = float(r["low"]) if not pd.isna(r["low"]) else px_close
            high = float(r["high"]) if not pd.isna(r["high"]) else px_close
            rsi_val = float(r["rsi"]) if "rsi" in r and not pd.isna(r["rsi"]) else 50.0

            exit_now = False
            exit_price = px_close
            exit_reason = ""

            # Stop loss
            if low <= position["stop_loss"]:
                exit_now = True
                exit_price = min(px_open, position["stop_loss"])
                exit_reason = "Stop loss"
            # Vinstmål / RSI-exit
            elif rsi_val >= rsi_exit:
                exit_now = True
                exit_price = px_close
                exit_reason = f"RSI-exit ({int(rsi_val)})"
            # Target exit
            elif high >= position["target"]:
                exit_now = True
                exit_price = position["target"]
                exit_reason = "Målkurs nådd"
            # Max holding period
            elif position["days"] >= max_days:
                exit_now = True
                exit_price = px_close
                exit_reason = f"Tids-exit ({max_days} d)"

            if exit_now:
                gross = position["qty"] * exit_price
                cost = gross * fee_pct
                net_val = gross - cost
                cash += net_val
                pnl = net_val - position["cost_basis"]
                ret_pct = (net_val / position["cost_basis"] - 1.0) * 100.0

                trades.append({
                    "entry_date": position["entry_date"],
                    "exit_date": date,
                    "entry_price": round(position["entry_price"], 2),
                    "exit_price": round(exit_price, 2),
                    "days_held": position["days"],
                    "return_pct": round(ret_pct, 2),
                    "profit": round(pnl, 2),
                    "exit_reason": exit_reason,
                    "open": False,
                })
                position = None

        # 2. Hantera ny köpsignal om vi saknar position
        if position is None and bool(r.get("entry_sig", False)):
            qty = int((cash * 0.95) // px_close)
            if qty > 0:
                cost_basis = qty * px_close * (1.0 + fee_pct)
                cash -= cost_basis
                stop_loss = px_close - atr_mult * atr
                # Target: 2.0x risk
                risk = px_close - stop_loss
                target = px_close + max(risk * 1.8, atr * 3.0)

                position = {
                    "entry_date": date,
                    "entry_price": px_close,
                    "qty": qty,
                    "cost_basis": cost_basis,
                    "stop_loss": stop_loss,
                    "target": target,
                    "days": 0,
                }

        # Värdera portfölj idag
        total_equity = cash + (position["qty"] * px_close if position else 0.0)
        curve.append({"date": date, "equity": round(total_equity, 1)})

    # Om position kvar vid slut
    if position:
        last_px = float(df.iloc[-1]["close"])
        gross = position["qty"] * last_px
        pnl = gross - position["cost_basis"]
        trades.append({
            "entry_date": position["entry_date"],
            "exit_date": dates[-1],
            "entry_price": round(position["entry_price"], 2),
            "exit_price": round(last_px, 2),
            "days_held": position["days"],
            "return_pct": round((gross / position["cost_basis"] - 1.0) * 100.0, 2),
            "profit": round(pnl, 2),
            "exit_reason": "Öppen position",
            "open": True,
        })

    # Beräkna statistik
    closed = [t for t in trades if not t["open"]]
    wins = [t for t in closed if t["profit"] > 0]
    losses = [t for t in closed if t["profit"] <= 0]
    win_rate = round(len(wins) / len(closed) * 100.0, 1) if closed else 0.0
    tot_win = sum(t["profit"] for t in wins)
    tot_loss = abs(sum(t["profit"] for t in losses))
    profit_factor = round(tot_win / tot_loss, 2) if tot_loss > 0 else (round(tot_win, 2) if tot_win > 0 else 1.0)

    # Buy & hold jämförelse för samma aktie
    first_px = float(df.iloc[0]["close"])
    last_px = float(df.iloc[-1]["close"])
    bh_return = round((last_px / first_px - 1.0) * 100.0, 2)
    strat_return = round((curve[-1]["equity"] / initial_capital - 1.0) * 100.0, 2)

    stats = {
        "trades_count": len(closed),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_return": strat_return,
        "buy_and_hold_return": bh_return,
        "avg_gain_pct": round(float(np.mean([t["return_pct"] for t in wins])), 2) if wins else 0.0,
        "avg_loss_pct": round(float(np.mean([t["return_pct"] for t in losses])), 2) if losses else 0.0,
        "avg_days_held": round(float(np.mean([t["days_held"] for t in closed])), 1) if closed else 0.0,
    }

    return trades, curve, stats

def run_single_stock_backtest(symbol, strategy="dip", years=5):
    """Hämtar data och kör enskilt aktiebacktest."""
    from src.core.data import get_db
    conn = get_db()
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume, ma50, ma200, rsi, atr "
        "FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date",
        conn, params=[symbol]
    )
    conn.close()

    if df.empty or len(df) < 50:
        return {"error": f"För lite historik för {symbol}."}

    df = df.set_index("date")
    cutoff = max(0, len(df) - int(years) * 252)
    df_sub = df.iloc[cutoff:].copy()

    df_signals = prep_strategy_signals(df_sub, strategy=strategy)
    trades, curve, stats = simulate_stock_trades(df_signals, strategy=strategy)

    # Nedskalad graf (max 50 punkter)
    step = max(1, len(curve) // 45)
    chart = [curve[i] for i in range(0, len(curve), step)]
    if chart and chart[-1]["date"] != curve[-1]["date"]:
        chart.append(curve[-1])

    return {
        "symbol": symbol,
        "strategy": strategy,
        "strategy_name": STRATEGIES.get(strategy, {}).get("name", strategy),
        "years": years,
        "stats": stats,
        "trades": trades[::-1],
        "chart": chart,
    }
```

- [ ] **Step 4: Kör testet och verifiera att det passerar**

Run: `python -m unittest tests/test_single_backtest.py`  
Expected: OK.

- [ ] **Step 5: Commit förändringen**

Run:
```bash
git add src/core/backtest.py tests/test_single_backtest.py
git commit -m "Feat: aktiespecifik simulering och nyckeltalsberäkning"
```

---

### Task 3: Dagens Möjligheter Scanner & Nivåberäkning

**Files:**
- Modify: `src/core/signals.py`
- Test: `tests/test_opportunities.py`

- [ ] **Step 1: Skriv test för scanner och nivåberäkning**

Skapa `tests/test_opportunities.py`:
```python
import unittest
from src.core.signals import calculate_trade_levels

class TestTradeLevels(unittest.TestCase):
    def test_calculate_trade_levels(self):
        close = 100.0
        atr = 3.0
        levels = calculate_trade_levels(close, atr, strategy="dip")
        self.assertIn("entry_price", levels)
        self.assertIn("stop_loss", levels)
        self.assertIn("target_price", levels)
        self.assertIn("risk_pct", levels)
        self.assertIn("reward_pct", levels)
        self.assertIn("risk_reward_ratio", levels)
        self.assertTrue(levels["stop_loss"] < close)
        self.assertTrue(levels["target_price"] > close)
        self.assertTrue(levels["risk_reward_ratio"] > 1.0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Kör testet och verifiera att det misslyckas**

Run: `python -m unittest tests/test_opportunities.py`  
Expected: FAIL - `calculate_trade_levels` saknas.

- [ ] **Step 3: Implementera nivåberäkning och `scan_opportunities` i `src/core/signals.py`**

Lägg till i `src/core/signals.py`:
```python
def calculate_trade_levels(close, atr, strategy="dip"):
    """Beräknar konkreta handelsnivåer (Entry, Stop Loss, Target, R:R)."""
    atr = max(atr, close * 0.015)
    if strategy == "dip":
        stop_dist = 2.2 * atr
        target_dist = 3.5 * atr
    elif strategy == "momentum":
        stop_dist = 2.5 * atr
        target_dist = 5.0 * atr
    else:  # trend
        stop_dist = 3.0 * atr
        target_dist = 6.5 * atr

    stop_loss = round(close - stop_dist, 2)
    target_price = round(close + target_dist, 2)
    risk_pct = round((close - stop_loss) / close * 100.0, 1)
    reward_pct = round((target_price - close) / close * 100.0, 1)
    rr = round(reward_pct / risk_pct, 1) if risk_pct > 0 else 1.0

    return {
        "entry_price": round(close, 2),
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "risk_reward_ratio": rr,
        "rr_label": f"1 : {rr:g}",
    }

def scan_opportunities(market="all", strategy_filter="all"):
    """Skannar alla bolag för dagens datum efter köpmöjligheter."""
    from src.core.backtest import prep_strategy_signals, simulate_stock_trades, STRATEGIES
    import pandas as pd
    from src.core.config import OMXS_50, NASDAQ_100

    db = get_db()
    tickers = {}
    if market in ("all", "omx", "omxs"):
        tickers.update({s: (n, "OMX") for s, n in OMXS_50.items()})
    if market in ("all", "nasdaq"):
        tickers.update({s: (n, "NASDAQ") for s, n in NASDAQ_100.items()})

    strategies_to_check = ["dip", "momentum", "trend"]
    if strategy_filter in strategies_to_check:
        strategies_to_check = [strategy_filter]

    opportunities = []

    for sym, (name, mkt) in tickers.items():
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume, ma50, ma200, rsi, atr "
            "FROM history WHERE symbol = ? AND close IS NOT NULL ORDER BY date",
            db, params=[sym]
        )
        if df.empty or len(df) < 100:
            continue

        df = df.set_index("date")
        curr = "$" if mkt == "NASDAQ" else "kr"

        for strat in strategies_to_check:
            df_sig = prep_strategy_signals(df, strategy=strat)
            last_row = df_sig.iloc[-1]

            if bool(last_row.get("entry_sig", False)):
                close = float(last_row["close"])
                atr = float(last_row["atr"]) if not pd.isna(last_row["atr"]) else close * 0.02
                levels = calculate_trade_levels(close, atr, strategy=strat)

                # Beräkna historisk edge på 5 års historik
                sub_df = df_sig.tail(252 * 5)
                _, _, stats = simulate_stock_trades(sub_df, strategy=strat)

                # Motivering i klarspråk
                if strat == "dip":
                    reason = f"Översåld dipp (RSI {last_row.get('rsi', 0):.0f}) i långsiktig upptrend över MA200."
                elif strat == "momentum":
                    reason = "Utbrott mot nytt fleraveckorshögsta med förhöjd handelsvolym."
                else:
                    reason = "Stark upptrend bekräftad av Golden Cross och stängning över MA200."

                opportunities.append({
                    "symbol": sym,
                    "name": name,
                    "market": mkt,
                    "currency": curr,
                    "close": close,
                    "strategy": strat,
                    "strategy_name": STRATEGIES[strat]["name"],
                    "reason": reason,
                    "levels": levels,
                    "edge": {
                        "win_rate": stats["win_rate"],
                        "trades_count": stats["trades_count"],
                        "profit_factor": stats["profit_factor"],
                        "avg_gain_pct": stats["avg_gain_pct"],
                    },
                    "score": round(stats["win_rate"] * stats["profit_factor"], 1),
                })

    db.close()
    # Sortera på starkast statistisk edge
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return opportunities
```

- [ ] **Step 4: Kör testet och verifiera att det passerar**

Run: `python -m unittest tests/test_opportunities.py`  
Expected: OK.

- [ ] **Step 5: Commit förändringen**

Run:
```bash
git add src/core/signals.py tests/test_opportunities.py
git commit -m "Feat: scanner för dagens köpmöjligheter och handelsnivåer"
```

---

### Task 4: API-endpoints och integration med bolagsanalys

**Files:**
- Modify: `src/api/routes.py`
- Modify: `src/core/analysis.py`
- Test: `tests/test_api_endpoints.py`

- [ ] **Step 1: Skriv test för nya API-endpoints**

Skapa `tests/test_api_endpoints.py`:
```python
import unittest
from app import app

class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_opportunities_route(self):
        res = self.client.get("/api/opportunities")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("opportunities", data)

    def test_backtest_stock_route(self):
        res = self.client.post("/api/backtest/stock", json={"symbol": "INVE-B.ST", "strategy": "dip", "years": 3})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue("error" in data or "stats" in data)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Kör testet och verifiera att det misslyckas**

Run: `python -m unittest tests/test_api_endpoints.py`  
Expected: 404 för `/api/opportunities` eller saknade endpoints.

- [ ] **Step 3: Lägg till endpoints i `src/api/routes.py` och utöka `src/core/analysis.py`**

I `src/api/routes.py`:
```python
from src.core.signals import run_market_screener, scan_opportunities
from src.core.backtest import run_backtest_local, optimize_omx, run_single_stock_backtest

@api_bp.route('/opportunities')
def opportunities_route():
    market = request.args.get('market', 'all')
    strategy = request.args.get('strategy', 'all')
    opps = scan_opportunities(market=market, strategy_filter=strategy)
    return jsonify({"opportunities": opps, "total": len(opps)})

@api_bp.route('/backtest/stock', methods=['POST'])
def backtest_stock_route():
    data = request.json or {}
    sym = data.get('symbol', '').strip().upper()
    strat = data.get('strategy', 'dip')
    years = int(data.get('years', 5))
    return jsonify(run_single_stock_backtest(sym, strategy=strat, years=years))
```

I `src/core/analysis.py`:
Lägg till ett anrop för historisk edge i `analyze_any_stock`:
```python
# Beräkna historisk edge för de 3 strategierna i bolagsvyn
edge_summary = {}
if not is_crypto:
    from src.core.backtest import prep_strategy_signals, simulate_stock_trades
    for s_key in ("dip", "momentum", "trend"):
        df_sig = prep_strategy_signals(df, strategy=s_key)
        _, _, s_stats = simulate_stock_trades(df_sig, strategy=s_key)
        edge_summary[s_key] = {
            "win_rate": s_stats["win_rate"],
            "profit_factor": s_stats["profit_factor"],
            "trades_count": s_stats["trades_count"],
            "active_signal": bool(df_sig.iloc[-1].get("entry_sig", False)),
        }
```
Inkludera `edge_summary` i returobjektet från `analyze_any_stock`.

- [ ] **Step 4: Kör testet och verifiera att det passerar**

Run: `python -m unittest tests/test_api_endpoints.py`  
Expected: 200 OK på båda rutter.

- [ ] **Step 5: Commit förändringen**

Run:
```bash
git add src/api/routes.py src/core/analysis.py tests/test_api_endpoints.py
git commit -m "Feat: API-endpoints för opportunities och aktiespecifikt backtest"
```

---

### Task 5: Frontend - Flik "Affärsmöjligheter"

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Lägg till fliken i navigeringen i `templates/index.html`**

Lägg till "Möjligheter" som framträdande flik:
```html
["opportunities", "Möjligheter"],
```

- [ ] **Step 2: Skapa sektionen `#pane-opportunities` i `templates/index.html`**

Lägg till HTML med filter (Marknad, Strategi) och kort/tabell-container för dagens lägen:
```html
<section class="pane" id="pane-opportunities">
  <div class="card">
    <h2>Dagens Affärsmöjligheter</h2>
    <p class="muted">Aktier som ger bekräftad köpsignal idag baserat på statistiskt beprövade strategier. Varje läge redovisar historisk träffsäkerhet samt konkreta nivåer för ingång, stop-loss och vinstmål.</p>
    <div class="row">
      <div class="field"><label>Marknad</label>
        <select id="opp-market" onchange="loadOpportunities()">
          <option value="all">Alla marknader</option>
          <option value="omxs">Stockholm (OMXS)</option>
          <option value="nasdaq">USA (Nasdaq)</option>
        </select>
      </div>
      <div class="field"><label>Strategi</label>
        <select id="opp-strategy" onchange="loadOpportunities()">
          <option value="all">Alla strategier</option>
          <option value="dip">Kvalitets-dipp</option>
          <option value="momentum">Momentum & Utbrott</option>
          <option value="trend">Långsiktig Trend</option>
        </select>
      </div>
      <div class="field" style="align-self:end;">
        <button class="btn btn-primary" onclick="loadOpportunities()">Uppdatera lägen</button>
      </div>
    </div>
  </div>
  <div id="opp-container" class="grid cols-2" style="margin-top:1rem;"></div>
</section>
```

- [ ] **Step 3: Implementera JavaScript-funktion `loadOpportunities()`**

Bygg rendering med badges, handelsnivåer och snabblänkar:
```javascript
async function loadOpportunities() {
  const container = $("#opp-container");
  container.innerHTML = '<p class="muted">Skannar marknaden efter köplägen…</p>';
  const mkt = $("#opp-market").value;
  const strat = $("#opp-strategy").value;
  const d = await getJSON(`/api/portal/opportunities?market=${mkt}&strategy=${strat}`);
  const list = d.opportunities || [];
  if (!list.length) {
    container.innerHTML = '<div class="card" style="grid-column:1/-1;"><p class="muted">Inga aktier uppfyller kriterierna just idag. Tålamod och disciplin är nyckeln till bra investeringar.</p></div>';
    return;
  }
  container.innerHTML = list.map(op => `
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
          <h3>${esc(op.name)} <small class="muted">${esc(op.symbol)}</small></h3>
          <span class="pill ${op.strategy === 'dip' ? 'up' : (op.strategy === 'momentum' ? 'info' : 'neutral')}">${esc(op.strategy_name)}</span>
        </div>
        <div style="text-align:right;">
          <div style="font-size:1.3rem; font-weight:bold;">${op.close} ${esc(op.currency)}</div>
          <small class="muted">${esc(op.market)}</small>
        </div>
      </div>
      <p style="margin:0.6rem 0; font-size:0.95rem;">${esc(op.reason)}</p>
      
      <div class="callout info" style="margin:0.6rem 0; padding:0.6rem;">
        <b>Historisk edge (5 år):</b> ${op.edge.win_rate} % vinstaffärer (${op.edge.trades_count} st), vinstfaktor ${op.edge.profit_factor}
      </div>

      <div class="grid cols-3" style="margin-top:0.6rem; background:var(--bg-subtle, #1a202c); padding:0.6rem; border-radius:6px;">
        <div><small class="muted">Entry</small><br><b>${op.levels.entry_price}</b></div>
        <div><small class="muted">Stop-loss</small><br><b class="neg">${op.levels.stop_loss}</b> <small>(${op.levels.risk_pct}%)</small></div>
        <div><small class="muted">Målkurs</small><br><b class="up">${op.levels.target_price}</b> <small>(+${op.levels.reward_pct}%)</small></div>
      </div>
      <div style="margin-top:0.4rem; font-size:0.85rem; color:var(--text-dim);">Risk/Reward-kvot: <b>${op.levels.rr_label}</b></div>

      <div style="display:flex; gap:0.5rem; margin-top:0.8rem;">
        <button class="btn btn-primary" onclick="showTab('analyze'); analyze('${esc(op.symbol)}')">Analysera bolag</button>
        <button class="btn" onclick="openStockBacktest('${esc(op.symbol)}', '${esc(op.strategy)}')">Visa historiska affärer</button>
      </div>
    </div>
  `).join("");
}
```

- [ ] **Step 4: Commit förändringen**

Run:
```bash
git add templates/index.html
git commit -m "Feat: ny vy för Dagens Affärsmöjligheter med handelsplan och edge"
```

---

### Task 6: Frontend - Aktiebacktest & Förbättrad Bolagsvy

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Lägg till kort för "Statistisk Edge" i bolagsvyn**

I bolagsanalysens renderingsfunktion i `templates/index.html`:
Lägg till visning av aktiv signal och historisk edge per strategi, samt en knapp för att köra direkt aktiebacktest.

- [ ] **Step 2: Uppgradera Backtest-vyn med lägesväljare (Hela marknaden vs Enskild aktie)**

Uppdatera `#pane-backtest` så att användaren kan växla mellan marknadssimulering och enskild aktie, välja strategi (`dip`, `momentum`, `trend`), och se equity-graf och affärslogg.

- [ ] **Step 3: Implementera JavaScript-funktion `openStockBacktest(symbol, strategy)`**

Skapa funktion som växlar till Backtest-fliken, sätter parametrarna för aktien och kör simuleringen automatiskt.

- [ ] **Step 4: Commit förändringen**

Run:
```bash
git add templates/index.html
git commit -m "Feat: aktiebacktest i bolagsanalys och förbättrad backtest-flik"
```

---

### Task 7: Slutverifiering & E2E-validering

**Files:**
- Test: Samtliga testfiler i `tests/`
- Run: Lokal Flask-server och HTTP-anrop

- [ ] **Step 1: Kör hela testsviten**

Run: `python -m unittest discover -s tests`  
Expected: Alla tester passerar utan fel.

- [ ] **Step 2: Verifiera API-anrop lokalt**

Testa via python/curl:
- `GET /api/opportunities?market=all`
- `POST /api/backtest/stock` med `{ "symbol": "INVE-B.ST", "strategy": "dip", "years": 5 }`

- [ ] **Step 3: Commit och förbered för användaröverlämning**

Run:
```bash
git status
```
Verifiera att arbetskatalogen är ren och allt fungerar.
