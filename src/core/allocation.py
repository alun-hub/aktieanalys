"""Regelbaserad allokering mellan tillgångsklasser.

Detta är INTE en marknadstimingmodell som förutsäger avkastning – det är en
riskhanteringsregel som minskar exponering mot koncentrerad risk (Mag7/US-tech)
och drar ner aktieandel i identifierad björnmarknad. Ingen komponent här ska
tolkas som en prognos.
"""

import time
import datetime
import logging
import pandas as pd
import yfinance as yf

from src.core.data import get_db
from src.core.regime import get_market_regime

logger = logging.getLogger(__name__)

_CONCENTRATION_CACHE = {"data": None, "ts": 0.0}
_CONC_TTL = 3600  # 1 timme


def assess_concentration_risk() -> dict:
    """Grov proxy för koncentrationsrisk i cap-viktade index.

    Mäter skillnaden i 1-års avkastning (252 handelsdagar) mellan marknadsviktade
    S&P 500 (SPY) och likaviktade S&P 500 (RSP).
    När marknadsviktade index kraftigt drar ifrån det likaviktade indexet beror
    uppgången på ett fåtal megabolag (t.ex. Mag7) och koncentrationsrisken är hög.

    Returnerar:
        {"level": "normal"|"elevated"|"high", "spread_pct": float, "detail": str}
    """
    global _CONCENTRATION_CACHE
    now = time.time()
    if _CONCENTRATION_CACHE["data"] and (now - _CONCENTRATION_CACHE["ts"] < _CONC_TTL):
        return _CONCENTRATION_CACHE["data"]

    # 1. Försök beräkna från databasen om SPY/RSP finns
    db = get_db()
    try:
        spy_rows = db.execute(
            "SELECT date, close FROM history WHERE symbol = 'SPY' AND close IS NOT NULL ORDER BY date DESC LIMIT 252"
        ).fetchall()
        rsp_rows = db.execute(
            "SELECT date, close FROM history WHERE symbol = 'RSP' AND close IS NOT NULL ORDER BY date DESC LIMIT 252"
        ).fetchall()
        if len(spy_rows) >= 200 and len(rsp_rows) >= 200:
            spy_ret = (float(spy_rows[0]["close"]) / float(spy_rows[-1]["close"]) - 1.0) * 100.0
            rsp_ret = (float(rsp_rows[0]["close"]) / float(rsp_rows[-1]["close"]) - 1.0) * 100.0
            spread = round(spy_ret - rsp_ret, 1)
            level = "high" if spread >= 8.0 else ("elevated" if spread >= 3.0 else "normal")
            result = {
                "level": level,
                "spread_pct": spread,
                "detail": f"Cap-weight (SPY {spy_ret:+.1f}%) vs Equal-weight (RSP {rsp_ret:+.1f}%), spridning {spread:+.1f}%",
                "source": "database",
            }
            _CONCENTRATION_CACHE = {"data": result, "ts": now}
            return result
    except Exception as e:
        logger.debug(f"DB concentration calculation failed: {e}")
    finally:
        db.close()

    # 2. Live-hämtning via yfinance
    try:
        df = yf.download(["SPY", "RSP"], period="1y", interval="1d", progress=False)
        if not df.empty and "Close" in df.columns:
            closes = df["Close"].dropna()
            if "SPY" in closes.columns and "RSP" in closes.columns and len(closes) >= 50:
                spy_ret = (float(closes["SPY"].iloc[-1]) / float(closes["SPY"].iloc[0]) - 1.0) * 100.0
                rsp_ret = (float(closes["RSP"].iloc[-1]) / float(closes["RSP"].iloc[0]) - 1.0) * 100.0
                spread = round(spy_ret - rsp_ret, 1)
                level = "high" if spread >= 8.0 else ("elevated" if spread >= 3.0 else "normal")
                result = {
                    "level": level,
                    "spread_pct": spread,
                    "detail": f"Cap-weight (SPY {spy_ret:+.1f}%) vs Equal-weight (RSP {rsp_ret:+.1f}%), spridning {spread:+.1f}%",
                    "source": "live",
                }
                _CONCENTRATION_CACHE = {"data": result, "ts": now}
                return result
    except Exception as e:
        logger.debug(f"yfinance concentration calculation failed: {e}")

    # Fallback till säkert neutralt standardvärde
    fallback = {
        "level": "normal",
        "spread_pct": 0.0,
        "detail": "Neutral koncentrationsrisk (standardvärde)",
        "source": "fallback",
    }
    _CONCENTRATION_CACHE = {"data": fallback, "ts": now}
    return fallback


def compute_target_allocation(market: str = "all") -> dict:
    """Kombinerar get_market_regime() + assess_concentration_risk() till en
    målfördelning i procent mellan:
      - broad_etf (t.ex. VWCE.DE / IWDA.AS — bred, marknadsviktad global index-ETF)
      - equalweight_etf (t.ex. XDEW.DE / RSP — likaviktad motvikt mot tech-koncentration)
      - dividend_stocks (stabila kvalitetsutdelare med kassaflöden)
      - growth_stocks (momentum- och tillväxtaktier med verifierad edge)
      - defensive (guld och ränte-ETF:er för kapitalbevarande)

    Regeltabell:
        regime=bull,  concentration=normal   -> 40/15/20/20/5
        regime=bull,  concentration=elevated -> 30/20/25/15/10
        regime=bull,  concentration=high     -> 20/25/30/10/15
        regime=correction (any concentration)-> 25/20/25/10/20
        regime=bear   (any concentration)    -> 10/10/15/0/65

    Sparar beräkningen i `allocation_targets` i databasen för historik och uppföljning.
    """
    regime_data = get_market_regime(market)
    conc_data = assess_concentration_risk()

    regime = regime_data.get("regime", "bull")
    if regime not in ("bull", "correction", "bear"):
        regime = "bull"

    conc_level = conc_data.get("level", "normal")
    if conc_level not in ("normal", "elevated", "high"):
        conc_level = "normal"

    if regime == "bull":
        if conc_level == "high":
            alloc = {
                "broad_etf": 20.0,
                "equalweight_etf": 25.0,
                "dividend_stocks": 30.0,
                "growth_stocks": 10.0,
                "defensive": 15.0,
            }
        elif conc_level == "elevated":
            alloc = {
                "broad_etf": 30.0,
                "equalweight_etf": 20.0,
                "dividend_stocks": 25.0,
                "growth_stocks": 15.0,
                "defensive": 10.0,
            }
        else:  # normal
            alloc = {
                "broad_etf": 40.0,
                "equalweight_etf": 15.0,
                "dividend_stocks": 20.0,
                "growth_stocks": 20.0,
                "defensive": 5.0,
            }
    elif regime == "correction":
        alloc = {
            "broad_etf": 25.0,
            "equalweight_etf": 20.0,
            "dividend_stocks": 25.0,
            "growth_stocks": 10.0,
            "defensive": 20.0,
        }
    else:  # bear
        alloc = {
            "broad_etf": 10.0,
            "equalweight_etf": 10.0,
            "dividend_stocks": 15.0,
            "growth_stocks": 0.0,
            "defensive": 65.0,
        }

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Spara historik i databasen
    db = get_db()
    try:
        db.execute(
            """INSERT INTO allocation_targets
            (computed_at, regime, concentration_flag, pct_broad_etf, pct_equalweight_etf,
             pct_dividend_stocks, pct_growth_stocks, pct_defensive, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_str,
                regime,
                conc_level,
                alloc["broad_etf"],
                alloc["equalweight_etf"],
                alloc["dividend_stocks"],
                alloc["growth_stocks"],
                alloc["defensive"],
                f"Marknad: {market}, Spridning: {conc_data.get('spread_pct', 0.0)}%",
            ),
        )
        db.commit()
    except Exception as e:
        logger.debug(f"Kunde inte spara målallokering till DB: {e}")
    finally:
        db.close()

    return {
        "market": market,
        "regime": regime_data,
        "concentration": conc_data,
        "allocation": alloc,
        "computed_at": now_str,
    }
