import csv
import io
import json
import os
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests as req
import yfinance as yf
from flask import Flask, jsonify, render_template, request
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
except ImportError:
    _vader = None
try:
    from pytrends.request import TrendReq
    _pytrends = TrendReq(hl="sv-SE", tz=60)
except ImportError:
    _pytrends = None

warnings.filterwarnings("ignore")

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))


# ── Indikatorer ───────────────────────────────────────────────────────────────

def calc_rsi(s, n=14):
    """Beräknar RSI med Wilder's Smoothing (standard)."""
    d = s.diff()
    # Wilder's smoothing motsvarar en EMA med alpha = 1/n
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    
    # Hantera division med noll (om inga förluster skett på n dagar)
    rsi = 100 - 100 / (1 + g / l.replace(0, 1e-9))
    return rsi


def calc_macd(s, fast=12, slow=26, sig=9):
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sl = m.ewm(span=sig, adjust=False).mean()
    return m, sl, m - sl


def calc_bb(close, n=20, num_std=2):
    ma  = close.rolling(n).mean()
    std = close.rolling(n).std()
    return ma + num_std * std, ma, ma - num_std * std


def calc_atr(df, n=14):
    """Beräknar ATR med Wilder's Smoothing."""
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def calc_obv(df):
    """Beräknar On-Balance Volume (OBV)."""
    obv = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
    return obv


def get_index_ticker(symbol):
    """Returnerar rätt index-ticker baserat på aktiens suffix."""
    if symbol.upper().endswith(".ST") or symbol.upper().endswith("ST"):
        return "^OMX"
    if "." not in symbol or symbol.upper().endswith(".US"):
        return "^NDX"
    return "^OMX"


_market_cache = {}

def fetch_market_data(symbol):
    """Hämtar index-data för trend- och RS-analys."""
    idx_ticker = get_index_ticker(symbol)
    now = time.time()
    
    if idx_ticker in _market_cache and now - _market_cache[idx_ticker]["ts"] < 3600:
        return _market_cache[idx_ticker]

    try:
        idf = yf.Ticker(idx_ticker).history(period="1y")
        if idf.empty:
            return None
        ma200 = idf.Close.rolling(200).mean().iloc[-1]
        last  = idf.Close.iloc[-1]
        bull  = last > ma200
        
        # För Relativ Styrka (RS): hämta förändring senaste 90 dagarna
        if len(idf) > 65:
            idx_return = (idf.Close.iloc[-1] / idf.Close.iloc[-65] - 1) * 100
        else:
            idx_return = 0
            
        data = {"bull": bull, "idx_return": idx_return, "ts": now, "ticker": idx_ticker}
        _market_cache[idx_ticker] = data
        return data
    except Exception:
        return None


def detect_patterns(df):
    """Identifierar vanliga candlestick-mönster på de senaste dagarna."""
    patterns = []
    closes = df["Close"].values
    opens  = df["Open"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    dates  = [d.strftime("%Y-%m-%d") for d in df.index]

    for i in range(1, len(df)):
        c, o, h, l   = closes[i], opens[i], highs[i], lows[i]
        pc, po        = closes[i-1], opens[i-1]
        body          = abs(c - o)
        rng           = h - l
        if rng < 0.001:
            continue
        lower_wick = min(c, o) - l
        upper_wick = h - max(c, o)

        if body / rng < 0.08:
            patterns.append({"date": dates[i], "pattern": "Doji",
                             "bullish": None,
                             "desc": "Oavgjort – köpare och säljare är lika starka. Vänta på bekräftelse nästa dag."})

        elif lower_wick > 2 * body and upper_wick < body and c >= o:
            patterns.append({"date": dates[i], "pattern": "Hammer",
                             "bullish": True,
                             "desc": "Bullish – köparna tog tillbaka kontrollen under dagen. Potentiell vändning uppåt."})

        elif upper_wick > 2 * body and lower_wick < body and c <= o:
            patterns.append({"date": dates[i], "pattern": "Shooting Star",
                             "bullish": False,
                             "desc": "Bearish – säljarna tryckte ned priset från toppen. Risk för vändning nedåt."})

        elif (c > o and pc < po              # dagens grön, gårdagens röd
              and c > po and o < pc):        # dagens kropp slukar gårdagens
            patterns.append({"date": dates[i], "pattern": "Bullish Engulfing",
                             "bullish": True,
                             "desc": "Stark köpsignal – det gröna ljuset slukar helt det röda. Köptrycket tog över."})

        elif (c < o and pc > po              # dagens röd, gårdagens grön
              and c < po and o > pc):
            patterns.append({"date": dates[i], "pattern": "Bearish Engulfing",
                             "bullish": False,
                             "desc": "Stark säljsignal – det röda ljuset slukar helt det gröna. Säljarna tog över."})

        # Morning Star (3-ljus): röd → liten → grön stor
        if i >= 2:
            c2, o2 = closes[i-2], opens[i-2]
            mid_body = abs(pc - po)
            if (c2 < o2                         # dag 1 röd
                    and mid_body / rng < 0.3    # dag 2 liten (star)
                    and c > o                   # dag 3 grön
                    and c > (c2 + o2) / 2):     # stänger över mitten av dag 1
                patterns.append({"date": dates[i], "pattern": "Morning Star",
                                 "bullish": True,
                                 "desc": "Stark bullish vändning (3-ljus) – köparna tog kontroll efter en nedgång."})

    return patterns[-6:] if len(patterns) > 6 else patterns


def calc_sltp(df, kurs):
    """Beräknar stop-loss och kursmål baserat på ATR och MA50."""
    atr  = float(df["ATR"].iloc[-1])
    ma50 = float(df["MA50"].iloc[-1])

    sl_atr   = kurs - 1.5 * atr          # ATR-baserad
    sl_ma50  = ma50 - 0.5 * atr          # strax under MA50
    sl_swing = float(df["Low"].iloc[-10:].min()) * 0.995  # senaste botten
    sl       = max(sl_atr, sl_ma50, sl_swing)
    sl       = min(sl, kurs * 0.95)      # max 5% förlust

    risk     = kurs - sl
    risk_pct = risk / kurs * 100

    trailing_sl = kurs - 1.5 * atr      # trailing: rör sig uppåt med aktien

    return {
        "stop_loss":          round(sl, 2),
        "stop_loss_pct":      round(risk_pct, 1),
        "trailing_stop":      round(trailing_sl, 2),
        "trailing_atr":       round(atr, 2),
        "take_profit_2":      round(kurs + 2 * risk, 2),
        "take_profit_2_pct":  round(risk_pct * 2, 1),
        "take_profit_3":      round(kurs + 3 * risk, 2),
        "take_profit_3_pct":  round(risk_pct * 3, 1),
        "atr":                round(atr, 2),
        "atr_pct":            round(atr / kurs * 100, 1),
        "bb_upper":           round(float(df["BB_upper"].iloc[-1]), 2),
        "bb_lower":           round(float(df["BB_lower"].iloc[-1]), 2),
        "ma50":               round(ma50, 2),
    }


def macd_days_since_cross(df):
    """Returnerar antal dagar sedan senaste bullish MACD-korsning, eller None."""
    cross_up = (df.MACD > df.MACD_sig) & (df.MACD.shift(1) <= df.MACD_sig.shift(1))
    if not cross_up.any():
        return None
    last_cross = df.index[cross_up].max()
    return (df.index[-1] - last_cross).days


def calc_swing_score(df, sig, market_data=None):
    score = 0
    details = {}
    market_bull = market_data["bull"] if market_data else True
    idx_ret     = market_data["idx_return"] if market_data else 0
    idx_ticker  = market_data["ticker"] if market_data else "Index"

    # 1. Marknadsriktning (+2)
    if market_bull:
        score += 2; details["market"] = (2, f"Marknadsläge: {idx_ticker} i bull-trend (Pris > MA200).")
    else:
        details["market"] = (0, f"Marknadsläge: {idx_ticker} i bear-trend – var försiktig.")

    # 2. Relativ Styrka (RS) (+2) - Jämför aktien mot index senaste 3 månaderna
    if len(df) > 65:
        stock_ret = (df.Close.iloc[-1] / df.Close.iloc[-65] - 1) * 100
        rs = stock_ret - idx_ret
        if rs > 5:
            score += 2; details["rs"] = (2, f"Relativ Styrka: Stark (+{rs:.1f}% mot index) – aktien leder marknaden.")
        elif rs > -5:
            score += 1; details["rs"] = (1, f"Relativ Styrka: Neutral ({rs:+.1f}% mot index).")
        else:
            details["rs"] = (0, f"Relativ Styrka: Svag ({rs:.1f}% mot index) – aktien släpar efter.")
    else:
        details["rs"] = (0, "Relativ Styrka: Otillräcklig historik för analys.")

    # 3. On-Balance Volume (OBV) (+2)
    obv = calc_obv(df)
    obv_ma = obv.rolling(20).mean()
    if obv.iloc[-1] > obv_ma.iloc[-1]:
        score += 2; details["obv"] = (2, "Volymflöde (OBV): Positivt – stora pengar ackumulerar aktien.")
    else:
        details["obv"] = (0, "Volymflöde (OBV): Negativt – bristande volymbekräftelse.")

    # 4. RSI i köpzon 32–52 (+2)
    rsi = sig["rsi"]
    if 32 <= rsi <= 52:
        score += 2; details["rsi"] = (2, f"RSI {rsi:.0f}: Optimal köpzon – låg risk för överköpt rekyl.")
    elif rsi < 32:
        score += 1; details["rsi"] = (1, f"RSI {rsi:.0f}: Översålt – potential för vändning men hög risk.")
    else:
        details["rsi"] = (0, f"RSI {rsi:.0f}: Neutral eller överköpt – invänta bättre läge.")

    # 5. Färsk MACD-korsning uppåt ≤5 dagar (+2)
    days = macd_days_since_cross(df)
    if days is not None and days <= 5:
        score += 2; details["macd"] = (2, f"MACD: Färsk bullish korsning ({days}d sedan) – positivt momentum.")
    elif sig["macd_bull"]:
        score += 1; details["macd"] = (1, f"MACD: Bullish trend, men korsningen skedde för {days or '?'}d sedan.")
    else:
        details["macd"] = (0, "MACD: Bearish – inget positivt trendskifte än.")

    # 6. Kurs nära MA50 (±4%) eller nedre BB (±3%) (+2)
    kurs = float(df.Close.iloc[-1])
    ma50 = float(df.MA50.iloc[-1])
    bb_lower = float(df.BB_lower.iloc[-1])
    near_ma50 = abs(kurs - ma50) / ma50 < 0.04
    near_bb   = abs(kurs - bb_lower) / bb_lower < 0.03
    if near_ma50 or near_bb:
        where = "MA50" if near_ma50 else "nedre Bollingerband"
        score += 2; details["support"] = (2, f"Stöd: Kursen testar {where} – god risk/reward för entry.")
    else:
        details["support"] = (0, "Stöd: Kursen hänger 'i luften' – risk för dipp till MA50.")

    # Label (Max score: 12)
    if score >= 10:  label, css = "ELITE SETUP 🚀", "prime"
    elif score >= 8: label, css = "BRA SETUP ✅", "good"
    elif score >= 5: label, css = "AVVAKTA ⏳", "wait"
    else:            label, css = "UNDVIK ❌", "avoid"

    return {"score": score, "label": label, "css": css, "details": details}


def gen_signal(df):
    m50, m200 = df.MA50, df.MA200

    if m50.iloc[-5] <= m200.iloc[-5] and m50.iloc[-1] > m200.iloc[-1]:
        ma_t, ma_b = "Golden Cross (ny!)", True
    elif m50.iloc[-1] > m200.iloc[-1]:
        ma_t, ma_b = "Golden Cross (aktiv)", True
    elif m50.iloc[-5] >= m200.iloc[-5] and m50.iloc[-1] < m200.iloc[-1]:
        ma_t, ma_b = "Death Cross (ny!)", False
    else:
        ma_t, ma_b = "Death Cross (aktiv)", False

    r = float(df.RSI.iloc[-1])
    if r < 35:   rsi_t, rsi_b = f"Översåld ({r:.0f})", True
    elif r > 70: rsi_t, rsi_b = f"Överköpt ({r:.0f})", False
    else:        rsi_t, rsi_b = f"Neutral ({r:.0f})", True

    mn, sn = df.MACD.iloc[-1], df.MACD_sig.iloc[-1]
    mp, sp = df.MACD.iloc[-2], df.MACD_sig.iloc[-2]
    if mp <= sp and mn > sn:   macd_t, macd_b = "Bullish korsning (ny!)", True
    elif mp >= sp and mn < sn: macd_t, macd_b = "Bearish korsning (ny!)", False
    elif mn > sn:              macd_t, macd_b = "Bullish", True
    else:                      macd_t, macd_b = "Bearish", False

    pos = sum([ma_b, rsi_b, macd_b])
    rek_map = {3: ("Köp", "kop"), 2: ("Köp / Håll", "kop-hall"),
               1: ("Håll / Sälj", "hall-salj"), 0: ("Sälj", "salj")}
    rek, klass = rek_map[pos]

    return dict(ma_text=ma_t, ma_bull=ma_b, rsi_text=rsi_t, rsi_bull=rsi_b, rsi=r,
                macd_text=macd_t, macd_bull=macd_b, rek=rek, rek_klass=klass, positiva=pos)


FETCH_PERIOD = {"3mo": "1y", "6mo": "2y", "1y": "2y"}
DISPLAY_DAYS = {"3mo": 95,  "6mo": 185,  "1y": 370}

# ── Börsnoteringlistor ────────────────────────────────────────────────────────

# Nasdaq Stockholm – OMXS30 + Large/Mid cap
OMXS_50 = {
    # OMXS30
    "ABB.ST":        "ABB",
    "ALFA.ST":       "Alfa Laval",
    "ALIV-SDB.ST":   "Autoliv",
    "ASSA-B.ST":     "Assa Abloy B",
    "ATCO-A.ST":     "Atlas Copco A",
    "ATCO-B.ST":     "Atlas Copco B",
    "BOL.ST":        "Boliden",
    "ELUX-B.ST":     "Electrolux B",
    "ERIC-B.ST":     "Ericsson B",
    "ESSITY-B.ST":   "Essity B",
    "EVO.ST":        "Evolution",
    "GETI-B.ST":     "Getinge B",
    "HM-B.ST":       "H&M B",
    "HEXA-B.ST":     "Hexagon B",
    "HUSQ-B.ST":     "Husqvarna B",
    "INDU-C.ST":     "Industrivärden C",
    "INVE-B.ST":     "Investor B",
    "KINV-B.ST":     "Kinnevik B",
    "NIBE-B.ST":     "Nibe B",
    "NDA-SE.ST":     "Nordea",
    "SAND.ST":       "Sandvik",
    "SCA-B.ST":      "SCA B",
    "SECU-B.ST":     "Securitas B",
    "SEB-A.ST":      "SEB A",
    "SKA-B.ST":      "Skanska B",
    "SKF-B.ST":      "SKF B",
    "SHB-A.ST":      "Handelsbanken A",
    "SWED-A.ST":     "Swedbank A",
    "TEL2-B.ST":     "Tele2 B",
    "TELIA.ST":      "Telia",
    "VOLV-B.ST":     "Volvo B",
    # Midcap / övriga large cap (original)
    "ADDT-B.ST":     "Addtech B",
    "AXFO.ST":       "Axfood",
    "BILL.ST":       "Billerud",
    "EQT.ST":        "EQT",
    "FABG.ST":       "Fabege",
    "HPOL-B.ST":     "Hexpol B",
    "INDT.ST":       "Indutrade",
    "INTRUM.ST":     "Intrum",
    "NOLA-B.ST":     "Nolato B",
    "PEAB-B.ST":     "Peab B",
    "SAAB-B.ST":     "SAAB B",
    "SINCH.ST":      "Sinch",
    "SSAB-A.ST":     "SSAB A",
    "SWEC-B.ST":     "Sweco B",
    "THULE.ST":      "Thule Group",
    "TREL-B.ST":     "Trelleborg B",
    "VOLCAR-B.ST":   "Volvo Cars B",
    # Utökad midcap
    "BALD-B.ST":     "Fastighets Balder B",
    "BETS-B.ST":     "Betsson B",
    "CAST.ST":       "Castellum",
    "EPI-A.ST":      "Epiroc A",
    "GRNG.ST":       "Gränges",
    "HUFV-A.ST":     "Hufvudstaden A",
    "HMS.ST":        "HMS Networks",
    "LATO-B.ST":     "Latour B",
    "LIAB.ST":       "Lindab International",
    "LUND-B.ST":     "Lundbergföretagen B",
    "MIPS.ST":       "MIPS",
    "OEM-B.ST":      "OEM International B",
    "PLAZ-B.ST":     "Platzer B",
    "SOBI.ST":       "Swedish Orphan Biovitrum",
    "TROAX.ST":      "Troax Group",
    "VITEC-B.ST":    "Vitec Software B",
    "WIHL.ST":       "Wihlborgs",
    "DIOS.ST":       "Diös Fastigheter",
    "BUFAB.ST":      "Bufab",
    "CLAS-B.ST":     "Clas Ohlson B",
    "KNOW.ST":       "Knowit B",
    "SYSR.ST":       "Systemair",
}

# Nasdaq First North Growth Market – mest handlade bolag
FIRST_NORTH = {
    "EMBRAC-B.ST":   "Embracer Group B",
    "NОРДН.ST":      "Nordnet",
    "BOOZT.ST":      "Boozt",
    "STORY-B.ST":    "Storytel B",
    "CDON.ST":       "CDON",
    "COOR.ST":       "Coor Service Management",
    "EGTX.ST":       "EG7",
    "FNOX.ST":       "Fortnox",
    "HANZA.ST":      "Hanza",
    "INT.ST":        "Invisio",
    "IRRAS.ST":      "Irras",
    "KAR.ST":        "Karnov Group",
    "KCAP.ST":       "K-Capita",
    "KFAST-B.ST":    "K-Fastigheter B",
    "MIDW-B.ST":     "Midway Holding B",
    "MOMENT.ST":     "Moment Group",
    "NCAB.ST":       "NCAB Group",
    "NENT-B.ST":     "NENT Group B",
    "NIBE-B.ST":     "Nibe Industrier B",
    "NILORN.ST":     "Nilörngruppen B",
    "OXE.ST":        "OXE Marine",
    "PNDX-B.ST":     "Paradox Interactive B",
    "PLUN.ST":       "Plun",
    "PRFO.ST":       "Performance B",
    "RATO-B.ST":     "Ratos B",
    "SFAB.ST":       "Scandinavian Financial Advisors B",
    "SG.ST":         "Scandic Hotels",
    "STIL.ST":       "Stillfront Group",
    "TOBII.ST":      "Tobii",
    "VIMIAN.ST":     "Vimian Group",
    "XANO-B.ST":     "XANO Industri B",
    "ZIGN.ST":       "Zignify Global Product Sourcing",
}

# Nasdaq 100 – USA:s 100 största teknikbolag
NASDAQ_100 = {
    "AAPL":   "Apple",
    "MSFT":   "Microsoft",
    "NVDA":   "NVIDIA",
    "AMZN":   "Amazon",
    "META":   "Meta Platforms",
    "GOOGL":  "Alphabet A",
    "GOOG":   "Alphabet C",
    "TSLA":   "Tesla",
    "AVGO":   "Broadcom",
    "COST":   "Costco",
    "NFLX":   "Netflix",
    "ASML":   "ASML",
    "AMD":    "Advanced Micro Devices",
    "AZN":    "AstraZeneca",
    "ADBE":   "Adobe",
    "QCOM":   "Qualcomm",
    "CSCO":   "Cisco",
    "INTC":   "Intel",
    "INTU":   "Intuit",
    "TXN":    "Texas Instruments",
    "AMGN":   "Amgen",
    "AMAT":   "Applied Materials",
    "BKNG":   "Booking Holdings",
    "ISRG":   "Intuitive Surgical",
    "HON":    "Honeywell",
    "VRTX":   "Vertex Pharmaceuticals",
    "SBUX":   "Starbucks",
    "PANW":   "Palo Alto Networks",
    "GILD":   "Gilead Sciences",
    "ADI":    "Analog Devices",
    "LRCX":   "Lam Research",
    "MU":     "Micron Technology",
    "KLAC":   "KLA Corporation",
    "MDLZ":   "Mondelez",
    "REGN":   "Regeneron",
    "MRVL":   "Marvell Technology",
    "SNPS":   "Synopsys",
    "CDNS":   "Cadence Design",
    "PYPL":   "PayPal",
    "MAR":    "Marriott",
    "ORLY":   "O'Reilly Automotive",
    "CTAS":   "Cintas",
    "MELI":   "MercadoLibre",
    "NXPI":   "NXP Semiconductors",
    "WDAY":   "Workday",
    "DXCM":   "Dexcom",
    "CEG":    "Constellation Energy",
    "CRWD":   "CrowdStrike",
    "IDXX":   "Idexx Laboratories",
    "AEP":    "American Electric Power",
    "KDP":    "Keurig Dr Pepper",
    "MNST":   "Monster Beverage",
    "PCAR":   "Paccar",
    "FTNT":   "Fortinet",
    "ROST":   "Ross Stores",
    "FAST":   "Fastenal",
    "ODFL":   "Old Dominion Freight",
    "ON":     "ON Semiconductor",
    "GEHC":   "GE HealthCare",
    "FANG":   "Diamondback Energy",
    "EA":     "Electronic Arts",
    "CTSH":   "Cognizant",
    "ZS":     "Zscaler",
    "BIIB":   "Biogen",
    "WBD":    "Warner Bros Discovery",
    "TEAM":   "Atlassian",
    "VRSK":   "Verisk Analytics",
    "XEL":    "Xcel Energy",
    "DDOG":   "Datadog",
    "TTD":    "The Trade Desk",
    "ANSS":   "Ansys",
    "ILMN":   "Illumina",
    "GFS":    "GlobalFoundries",
    "APP":    "AppLovin",
    "PLTR":   "Palantir",
    "ARM":    "ARM Holdings",
    "SMCI":   "Super Micro Computer",
}

# Alla listor samlade
# ── ETF:er ───────────────────────────────────────────────────────────────────

ETFS = {
    # Svenska börs-ETF:er (Nasdaq Stockholm, handlas i SEK)
    "XACT.ST":        "XACT OMXS30 (Sverige)",
    "XACTBULL.ST":    "XACT Bull (Sverige 1.5x)",
    "XACTBEAR.ST":    "XACT Bear (Sverige -1.5x)",
    "XACTOBLIG.ST":   "XACT Obligation (ränta)",
    "SXR8.ST":        "iShares Core S&P 500 (USD)",
    "EUNL.ST":        "iShares Core MSCI World (global)",
    "IS3N.ST":        "iShares Core MSCI EM (tillväxtmarknader)",
    "DXET.ST":        "Xtrackers MSCI Europe (Europa)",
    "FLOT.ST":        "Franklin STOXX Europe 600",
    "TNOW.ST":        "iShares Automation & Robotics",
    "IQQH.ST":        "iShares Global Clean Energy",
    "BTCE.ST":        "ETC Bitcoin (BTC)",
    "ETHE.ST":        "ETC Ethereum (ETH)",
    "4GLD.ST":        "WisdomTree Physical Gold (guld)",
    "VZLD.ST":        "WisdomTree Physical Silver (silver)",
    # Populära US-listade ETF:er (handlas i USD)
    "SPY":    "SPDR S&P 500 ETF",
    "QQQ":    "Invesco Nasdaq 100 ETF",
    "VTI":    "Vanguard Total Stock Market ETF",
    "VOO":    "Vanguard S&P 500 ETF",
    "VEA":    "Vanguard FTSE Developed Markets ETF",
    "VWO":    "Vanguard FTSE Emerging Markets ETF",
    "GLD":    "SPDR Gold Shares",
    "TLT":    "iShares 20+ Year Treasury Bond ETF",
    "XLK":    "Technology Select Sector SPDR",
    "XLF":    "Financial Select Sector SPDR",
    "XLE":    "Energy Select Sector SPDR",
    "ARKK":   "ARK Innovation ETF",
    "SOXX":   "iShares Semiconductor ETF",
    "MCHI":   "iShares MSCI China ETF",
}

# ── Kryptovalutor (CoinGecko) ─────────────────────────────────────────────────

CRYPTO = {
    "BTC-USD":   "Bitcoin",
    "ETH-USD":   "Ethereum",
    "SOL-USD":   "Solana",
    "XRP-USD":   "XRP",
    "BNB-USD":   "BNB",
    "ADA-USD":   "Cardano",
    "DOGE-USD":  "Dogecoin",
    "AVAX-USD":  "Avalanche",
    "DOT-USD":   "Polkadot",
    "LINK-USD":  "Chainlink",
    "MATIC-USD": "Polygon",
    "UNI-USD":   "Uniswap",
    "LTC-USD":   "Litecoin",
    "ATOM-USD":  "Cosmos",
    "FIL-USD":   "Filecoin",
}

_COINGECKO_IDS = {
    "BTC-USD":   "bitcoin",
    "ETH-USD":   "ethereum",
    "SOL-USD":   "solana",
    "XRP-USD":   "ripple",
    "BNB-USD":   "binancecoin",
    "ADA-USD":   "cardano",
    "DOGE-USD":  "dogecoin",
    "AVAX-USD":  "avalanche-2",
    "DOT-USD":   "polkadot",
    "LINK-USD":  "chainlink",
    "MATIC-USD": "matic-network",
    "UNI-USD":   "uniswap",
    "LTC-USD":   "litecoin",
    "ATOM-USD":  "cosmos",
    "FIL-USD":   "filecoin",
}

_CG_BASE    = "https://api.coingecko.com/api/v3"
_cg_cache: dict = {}        # symbol → {df, ts}
_cg_price_cache: dict = {}  # symbol → {data, ts}
_cg_global_cache: dict = {"data": None, "ts": 0.0}
_crypto_screener_cache: dict = {"data": None, "ts": 0.0}


def fetch_crypto_df(symbol):
    """Hämtar daglig kurshistorik (365 dagar) + OHLC (90 dagar) från CoinGecko.
    market_chart → 365 dagliga stängningar + volym
    ohlc         → OHLC för senaste 90 dagar
    Slår ihop till DataFrame med Open, High, Low, Close, Volume.
    Cache 15 min.
    """
    cached = _cg_cache.get(symbol)
    if cached and time.time() - cached["ts"] < 900:  # 15 min cache
        return cached["df"]

    cg_id = _COINGECKO_IDS.get(symbol)
    if not cg_id:
        return None
    try:
        # 1. market_chart – 365 dagliga stängningar + volym
        r1 = req.get(
            f"{_CG_BASE}/coins/{cg_id}/market_chart",
            params={"vs_currency": "usd", "days": "365", "interval": "daily"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        mc = r1.json()
        if not mc or "prices" not in mc:
            return None
        prices = mc["prices"]        # [[ts_ms, close], ...]
        volumes = mc.get("total_volumes", [])

        mc_rows = {}
        for i, (ts, close) in enumerate(prices):
            date = pd.Timestamp(ts, unit="ms").normalize()
            vol = volumes[i][1] if i < len(volumes) else 0
            mc_rows[date] = {"Close": close, "Volume": vol}

        # 2. ohlc – OHLC för senaste 90 dagar
        r2 = req.get(
            f"{_CG_BASE}/coins/{cg_id}/ohlc",
            params={"vs_currency": "usd", "days": "90"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        ohlc_data = r2.json()
        ohlc_rows = {}
        if ohlc_data and not isinstance(ohlc_data, dict):
            for row in ohlc_data:
                ts, o, h, l, c = row
                date = pd.Timestamp(ts, unit="ms").normalize()
                ohlc_rows[date] = {"Open": o, "High": h, "Low": l, "Close": c}

        # 3. Slå ihop: börja med mc_rows, berika med OHLC
        all_dates = sorted(mc_rows.keys())
        records = []
        for date in all_dates:
            mc = mc_rows[date]
            ohlc = ohlc_rows.get(date)
            if ohlc:
                records.append({
                    "Date": date,
                    "Open": ohlc["Open"], "High": ohlc["High"],
                    "Low": ohlc["Low"],   "Close": ohlc["Close"],
                    "Volume": mc["Volume"],
                })
            else:
                c = mc["Close"]
                records.append({
                    "Date": date,
                    "Open": c, "High": c, "Low": c, "Close": c,
                    "Volume": mc["Volume"],
                })

        df = pd.DataFrame(records).set_index("Date").sort_index()
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        _cg_cache[symbol] = {"df": df, "ts": time.time()}
        return df
    except Exception:
        return None


def fetch_crypto_price(symbol):
    """Hämtar live-pris + 24h-förändring + market cap + volym från CoinGecko.
    Returnerar dict: {"price": float, "change_24h": float, "market_cap": float, "volume_24h": float}
    Cache 60 sek.
    """
    cached = _cg_price_cache.get(symbol)
    if cached and time.time() - cached["ts"] < 60:
        return cached["data"]
    cg_id = _COINGECKO_IDS.get(symbol)
    if not cg_id:
        return None
    try:
        r = req.get(
            f"{_CG_BASE}/simple/price",
            params={
                "ids": cg_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        d = r.json().get(cg_id, {})
        if not d:
            return None
        data = {
            "price":      float(d.get("usd", 0)),
            "change_24h": float(d.get("usd_24h_change", 0) or 0),
            "market_cap": float(d.get("usd_market_cap", 0) or 0),
            "volume_24h": float(d.get("usd_24h_vol", 0) or 0),
        }
        _cg_price_cache[symbol] = {"data": data, "ts": time.time()}
        return data
    except Exception:
        return None


def fetch_crypto_global():
    """Hämtar global kryptomarknadsdata från CoinGecko.
    Returnerar: {"btc_dominance": float, "total_market_cap_usd": float, "market_cap_change_24h": float}
    Cache 5 min.
    """
    if _cg_global_cache["data"] and time.time() - _cg_global_cache["ts"] < 300:
        return _cg_global_cache["data"]
    try:
        r = req.get(
            f"{_CG_BASE}/global",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        d = r.json().get("data", {})
        result = {
            "btc_dominance":       float(d.get("market_cap_percentage", {}).get("btc", 0)),
            "total_market_cap_usd": float(d.get("total_market_cap", {}).get("usd", 0)),
            "market_cap_change_24h": float(d.get("market_cap_change_percentage_24h_usd", 0) or 0),
        }
        _cg_global_cache["data"] = result
        _cg_global_cache["ts"]   = time.time()
        return result
    except Exception:
        return {"btc_dominance": 0, "total_market_cap_usd": 0, "market_cap_change_24h": 0}


def gen_crypto_signal(df):
    """Genererar signal för krypto. Använder MA50-riktning om MA200 saknas."""
    has_ma200 = ("MA200" in df.columns) and pd.notna(df.MA200.iloc[-1])

    if has_ma200:
        m50, m200 = df.MA50, df.MA200
        if m50.iloc[-5] <= m200.iloc[-5] and m50.iloc[-1] > m200.iloc[-1]:
            ma_t, ma_b = "Golden Cross (ny!)", True
        elif m50.iloc[-1] > m200.iloc[-1]:
            ma_t, ma_b = "Golden Cross (aktiv)", True
        elif m50.iloc[-5] >= m200.iloc[-5] and m50.iloc[-1] < m200.iloc[-1]:
            ma_t, ma_b = "Death Cross (ny!)", False
        else:
            ma_t, ma_b = "Death Cross (aktiv)", False
    else:
        # MA50-riktning: jämför senaste med 5 dagar sedan
        try:
            ma50_rising = float(df.MA50.iloc[-1]) > float(df.MA50.iloc[-5])
        except Exception:
            ma50_rising = True
        if ma50_rising:
            ma_t, ma_b = "MA50 stigande", True
        else:
            ma_t, ma_b = "MA50 fallande", False

    r = float(df.RSI.iloc[-1])
    if r < 35:   rsi_t, rsi_b = f"Översåld ({r:.0f})", True
    elif r > 70: rsi_t, rsi_b = f"Överköpt ({r:.0f})", False
    else:        rsi_t, rsi_b = f"Neutral ({r:.0f})", True

    mn, sn = df.MACD.iloc[-1], df.MACD_sig.iloc[-1]
    mp, sp = df.MACD.iloc[-2], df.MACD_sig.iloc[-2]
    if mp <= sp and mn > sn:   macd_t, macd_b = "Bullish korsning (ny!)", True
    elif mp >= sp and mn < sn: macd_t, macd_b = "Bearish korsning (ny!)", False
    elif mn > sn:              macd_t, macd_b = "Bullish", True
    else:                      macd_t, macd_b = "Bearish", False

    pos = sum([ma_b, rsi_b, macd_b])
    rek_map = {3: ("Köp", "kop"), 2: ("Köp / Håll", "kop-hall"),
               1: ("Håll / Sälj", "hall-salj"), 0: ("Sälj", "salj")}
    rek, klass = rek_map[pos]

    return dict(ma_text=ma_t, ma_bull=ma_b, rsi_text=rsi_t, rsi_bull=rsi_b, rsi=r,
                macd_text=macd_t, macd_bull=macd_b, rek=rek, rek_klass=klass, positiva=pos)


def analyze_crypto(symbol, period="3mo"):
    """Analyserar en kryptovaluta. Liknar analyze_stock men använder CoinGecko-data."""
    fetch = FETCH_PERIOD.get(period, "1y")
    days  = DISPLAY_DAYS.get(period, 95)

    df = fetch_crypto_df(symbol)
    if df is None or df.empty or len(df) < 30:
        return None

    df["MA50"]     = df.Close.rolling(50).mean()
    df["MA200"]    = df.Close.rolling(200).mean()
    df["RSI"]      = calc_rsi(df.Close)
    df["MACD"], df["MACD_sig"], df["MACD_hist"] = calc_macd(df.Close)
    df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
    df["ATR"]      = calc_atr(df)
    # Droppa bara rader där kärnindikatorer saknas – MA200 kan vara NaN
    df.dropna(subset=["MA50", "RSI", "MACD", "BB_upper", "ATR"], inplace=True)
    if len(df) < 5:
        return None

    has_ma200 = pd.notna(df.MA200.iloc[-1])
    sig  = gen_crypto_signal(df)

    # market_bull: för BTC använd sin egen MA50-riktning; för andra använd BTC:s trend
    if symbol == "BTC-USD":
        try:
            market_bull = float(df.MA50.iloc[-1]) > float(df.MA50.iloc[-5])
        except Exception:
            market_bull = True
    else:
        try:
            btc_df = fetch_crypto_df("BTC-USD")
            if btc_df is not None and len(btc_df) >= 10:
                btc_df["MA50"] = btc_df.Close.rolling(50).mean()
                btc_df.dropna(inplace=True)
                market_bull = float(btc_df.MA50.iloc[-1]) > float(btc_df.MA50.iloc[-5])
            else:
                market_bull = True
        except Exception:
            market_bull = True

    kurs  = float(df.Close.iloc[-1])
    sltp  = calc_sltp(df, kurs)
    # För krypto använder vi BTC-trend som market_bull
    swing = calc_swing_score(df, sig, {"bull": market_bull, "idx_return": 0, "ticker": "BTC-USD"})

    golden = (df.MA50 > df.MA200) & (df.MA50.shift(1) <= df.MA200.shift(1))
    death  = (df.MA50 < df.MA200) & (df.MA50.shift(1) >= df.MA200.shift(1))

    cutoff  = df.index[-1] - pd.Timedelta(days=days)
    disp    = df[df.index >= cutoff].copy()
    patterns = detect_patterns(disp)

    name = CRYPTO.get(symbol, symbol)

    # Live-pris
    live = fetch_crypto_price(symbol)
    market_info = {}
    if live:
        market_info = {
            "price":      live["price"],
            "change_24h": live["change_24h"],
            "market_cap": live["market_cap"],
            "volume_24h": live["volume_24h"],
        }

    def clean(s):
        return [None if pd.isna(v) else round(float(v), 4) for v in s]

    return {
        "symbol":      symbol,
        "name":        name,
        "kurs":        round(kurs, 4),
        "currency":    "USD",
        "has_ma200":   has_ma200,
        "market_info": market_info,
        "signal":      sig,
        "sltp":        sltp,
        "swing":       swing,
        "patterns":    patterns,
        "chart": {
            "dates":     [d.strftime("%Y-%m-%d") for d in disp.index],
            "open":      clean(disp.Open),
            "high":      clean(disp.High),
            "low":       clean(disp.Low),
            "close":     clean(disp.Close),
            "volume":    [int(v) for v in disp.Volume],
            "ma50":      clean(disp.MA50),
            "ma200":     clean(disp.MA200),
            "bb_upper":  clean(disp.BB_upper),
            "bb_mid":    clean(disp.BB_mid),
            "bb_lower":  clean(disp.BB_lower),
            "rsi":       clean(disp.RSI),
            "macd":      [round(float(v), 6) for v in disp.MACD],
            "macd_sig":  [round(float(v), 6) for v in disp.MACD_sig],
            "macd_hist": [round(float(v), 6) for v in disp.MACD_hist],
            "golden_x":  [d.strftime("%Y-%m-%d") for d in disp.index[golden[disp.index]]],
            "golden_y":  clean(disp.Close[golden[disp.index]]),
            "death_x":   [d.strftime("%Y-%m-%d") for d in disp.index[death[disp.index]]],
            "death_y":   clean(disp.Close[death[disp.index]]),
        },
    }


def crypto_screener_analyze(symbol, name):
    """Lätt crypto-analys för screener. Liknar screener_analyze men använder CoinGecko."""
    try:
        df = fetch_crypto_df(symbol)
        if df is None or df.empty or len(df) < 30:
            return None

        df["MA50"]     = df.Close.rolling(50).mean()
        df["MA200"]    = df.Close.rolling(200).mean()
        df["RSI"]      = calc_rsi(df.Close)
        df["MACD"], df["MACD_sig"], df["MACD_hist"] = calc_macd(df.Close)
        df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
        df["ATR"]      = calc_atr(df)
        df.dropna(subset=["MA50", "RSI", "MACD", "BB_upper", "ATR"], inplace=True)
        if len(df) < 5:
            return None

        sig  = gen_crypto_signal(df)
        kurs = float(df.Close.iloc[-1])
        sltp = calc_sltp(df, kurs)

        # market_bull via BTC MA50
        if symbol == "BTC-USD":
            try:
                market_bull = float(df.MA50.iloc[-1]) > float(df.MA50.iloc[-5])
            except Exception:
                market_bull = True
        else:
            market_bull = True  # BTC-data kan vara stale i screener – använda True som default

        swing = calc_swing_score(df, sig, {"bull": market_bull, "idx_return": 0, "ticker": "BTC-USD"})

        recent = df.iloc[-10:]
        pats   = detect_patterns(recent)
        latest = pats[-1]["pattern"] if pats else "–"
        latest_bull = pats[-1]["bullish"] if pats else None

        strength = sig["positiva"] * 3
        if "ny!" in sig["ma_text"]:   strength += 1
        if "ny!" in sig["macd_text"]: strength += 1

        return {
            "symbol":       symbol,
            "name":         name,
            "kurs":         round(kurs, 4),
            "currency":     "USD",
            "rsi":          round(sig["rsi"], 1),
            "atr":          sltp["atr"],
            "atr_pct":      sltp["atr_pct"],
            "stop_loss":    sltp["stop_loss"],
            "sl_pct":       sltp["stop_loss_pct"],
            "tp1":          sltp["take_profit_2"],
            "tp1_pct":      sltp["take_profit_2_pct"],
            "ma_text":      sig["ma_text"],
            "macd_text":    sig["macd_text"],
            "rek":          sig["rek"],
            "rek_klass":    sig["rek_klass"],
            "positiva":     sig["positiva"],
            "strength":     strength,
            "pattern":      latest,
            "pattern_bull": latest_bull,
            "bb_pos":       round((kurs - sltp["bb_lower"]) /
                                  max(sltp["bb_upper"] - sltp["bb_lower"], 0.01) * 100),
            "swing_score":  swing["score"],
            "swing_label":  swing["label"],
            "swing_css":    swing["css"],
        }
    except Exception:
        return None


def get_ohlcv_df(symbol, period="1y"):
    """Hämtar OHLCV-data via yfinance. Crypto hanteras separat via fetch_crypto_df."""
    return yf.Ticker(symbol).history(period=period)[["Open", "High", "Low", "Close", "Volume"]].copy()


STOCK_LISTS = {
    "omxs":       ("Nasdaq Stockholm", OMXS_50),
    "firstnorth": ("First North", FIRST_NORTH),
    "nasdaq100":  ("Nasdaq 100 (USA)", NASDAQ_100),
    "etf":        ("ETF:er", ETFS),
    "crypto":     ("Krypto", CRYPTO),
}

# Sammanslagna för enkel uppslagning
ALL_STOCKS = {**OMXS_50, **FIRST_NORTH, **NASDAQ_100, **ETFS, **CRYPTO}

# Cache: {data: [...], ts: float}
_screener_cache: dict = {"data": None, "ts": 0.0}


def analyze_stock(symbol, period="3mo"):
    fetch = FETCH_PERIOD.get(period, "1y")
    days  = DISPLAY_DAYS.get(period, 95)

    is_crypto = symbol in _COINGECKO_IDS
    df = get_ohlcv_df(symbol, fetch)
    if df is None or df.empty or len(df) < 55:
        return None

    df["MA50"]     = df.Close.rolling(50).mean()
    df["MA200"]    = df.Close.rolling(200).mean()
    df["RSI"]      = calc_rsi(df.Close)
    df["MACD"], df["MACD_sig"], df["MACD_hist"] = calc_macd(df.Close)
    df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
    df["ATR"]      = calc_atr(df)
    df.dropna(inplace=True)
    if len(df) < 5:
        return None

    sig  = gen_signal(df)
    kurs = float(df.Close.iloc[-1])
    sltp = calc_sltp(df, kurs)
    market_data = fetch_market_data(symbol)
    swing = calc_swing_score(df, sig, market_data)

    golden = (df.MA50 > df.MA200) & (df.MA50.shift(1) <= df.MA200.shift(1))
    death  = (df.MA50 < df.MA200) & (df.MA50.shift(1) >= df.MA200.shift(1))

    cutoff  = df.index[-1] - pd.Timedelta(days=days)
    disp    = df[df.index >= cutoff].copy()
    patterns = detect_patterns(disp)

    if is_crypto:
        name = CRYPTO.get(symbol, symbol)
    else:
        try:
            info = yf.Ticker(symbol).info
            name = info.get("longName") or info.get("shortName") or symbol
        except Exception:
            name = ALL_STOCKS.get(symbol, symbol)

    def clean(s):
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    return {
        "symbol":   symbol,
        "name":     name,
        "kurs":     round(kurs, 2),
        "signal":   sig,
        "sltp":     sltp,
        "swing":    swing,
        "patterns": patterns,
        "chart": {
            "dates":     [d.strftime("%Y-%m-%d") for d in disp.index],
            "open":      clean(disp.Open),
            "high":      clean(disp.High),
            "low":       clean(disp.Low),
            "close":     clean(disp.Close),
            "volume":    [int(v) for v in disp.Volume],
            "ma50":      clean(disp.MA50),
            "ma200":     clean(disp.MA200),
            "bb_upper":  clean(disp.BB_upper),
            "bb_mid":    clean(disp.BB_mid),
            "bb_lower":  clean(disp.BB_lower),
            "rsi":       clean(disp.RSI),
            "macd":      [round(float(v), 4) for v in disp.MACD],
            "macd_sig":  [round(float(v), 4) for v in disp.MACD_sig],
            "macd_hist": [round(float(v), 4) for v in disp.MACD_hist],
            "golden_x":  [d.strftime("%Y-%m-%d") for d in disp.index[golden[disp.index]]],
            "golden_y":  clean(disp.Close[golden[disp.index]]),
            "death_x":   [d.strftime("%Y-%m-%d") for d in disp.index[death[disp.index]]],
            "death_y":   clean(disp.Close[death[disp.index]]),
        },
    }


# ── Screener ─────────────────────────────────────────────────────────────────

def screener_analyze(symbol, name):
    """Lätt version av analyze_stock för screener – hoppar över info-anrop."""
    try:
        df = get_ohlcv_df(symbol, "1y")
        if df is None or df.empty or len(df) < 55:
            return None

        df["MA50"]     = df.Close.rolling(50).mean()
        df["MA200"]    = df.Close.rolling(200).mean()
        df["RSI"]      = calc_rsi(df.Close)
        df["MACD"], df["MACD_sig"], df["MACD_hist"] = calc_macd(df.Close)
        df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
        df["ATR"]      = calc_atr(df)
        df.dropna(inplace=True)
        if len(df) < 5:
            return None

        sig  = gen_signal(df)
        kurs = float(df.Close.iloc[-1])
        sltp = calc_sltp(df, kurs)
        market_data = fetch_market_data(symbol)
        swing = calc_swing_score(df, sig, market_data)

        # Senaste candlestick-mönster (bara sista 10 dagarna)
        recent = df.iloc[-10:]
        pats   = detect_patterns(recent)
        latest = pats[-1]["pattern"] if pats else "–"
        latest_bull = pats[-1]["bullish"] if pats else None

        # Signalstyrka för sortering (0–9)
        strength = sig["positiva"] * 3
        if "ny!" in sig["ma_text"]:   strength += 1
        if "ny!" in sig["macd_text"]: strength += 1

        return {
            "symbol":       symbol,
            "name":         name,
            "kurs":         round(kurs, 2),
            "rsi":          round(sig["rsi"], 1),
            "atr":          sltp["atr"],
            "atr_pct":      sltp["atr_pct"],
            "stop_loss":    sltp["stop_loss"],
            "sl_pct":       sltp["stop_loss_pct"],
            "tp1":          sltp["take_profit_2"],
            "tp1_pct":      sltp["take_profit_2_pct"],
            "ma_text":      sig["ma_text"],
            "macd_text":    sig["macd_text"],
            "rek":          sig["rek"],
            "rek_klass":    sig["rek_klass"],
            "positiva":     sig["positiva"],
            "strength":     strength,
            "pattern":      latest,
            "pattern_bull": latest_bull,
            "bb_pos":       round((kurs - sltp["bb_lower"]) /
                                  max(sltp["bb_upper"] - sltp["bb_lower"], 0.01) * 100),
            "swing_score":  swing["score"],
            "swing_label":  swing["label"],
            "swing_css":    swing["css"],
        }
    except Exception:
        return None


def run_screener(symbols=None):
    """Kör screener parallellt för givna aktier (standard: OMXS_50)."""
    if symbols is None:
        symbols = OMXS_50
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(screener_analyze, sym, name): sym
                   for sym, name in symbols.items()}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    rek_order = {"kop": 0, "kop-hall": 1, "hall-salj": 2, "salj": 3}
    results.sort(key=lambda x: (rek_order.get(x["rek_klass"], 9), -x.get("swing_score", 0), -x["strength"]))
    return results


# ── Backtesting ───────────────────────────────────────────────────────────────

def compute_backtest_stats(trades):
    """Beräknar aggregerad statistik från en lista av trades."""
    if not trades:
        return None
    wins   = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    avg_win  = sum(t["pl_pct"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss = sum(t["pl_pct"] for t in losses) / len(losses) if losses else 0
    return {
        "total":         len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(trades) * 100, 1),
        "avg_return":    round(sum(t["pl_pct"] for t in trades) / len(trades), 2),
        "avg_win":       round(avg_win, 2),
        "avg_loss":      round(avg_loss, 2),
        "profit_factor": round(abs(avg_win / avg_loss) if avg_loss else 0, 2),
        "avg_days":      round(sum(t["days_held"] for t in trades) / len(trades), 1),
    }


def run_backtest_symbol(symbol, period="2y", min_score=6, max_days=30):
    """Backtesta swing-signaler för ett symbol på historisk data (inga lookahead-problem)."""
    FETCH = {"1y": "1y", "2y": "2y", "3y": "5y"}
    df = get_ohlcv_df(symbol, FETCH.get(period, "2y"))
    if df is None or df.empty or len(df) < 100:
        return []

    # Beräkna alla indikatorer en gång med rolling windows (= noll lookahead)
    df["MA50"]     = df.Close.rolling(50).mean()
    df["MA200"]    = df.Close.rolling(200).mean()
    df["RSI"]      = calc_rsi(df.Close)
    df["MACD"], df["MACD_sig"], df["MACD_hist"] = calc_macd(df.Close)
    df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
    df["ATR"]      = calc_atr(df)
    df.dropna(inplace=True)
    if len(df) < 40:
        return []

    trades      = []
    in_trade    = False
    entry_price = trade_sl = trade_tp = entry_date = None
    entry_idx   = 0
    # Starta efter 35 rader så volym-rullande snitt (20d) och MACD-historik är stabila
    start_i = 35

    for i in range(start_i, len(df) - 1):
        row = df.iloc[i]

        if in_trade:
            days_held = i - entry_idx
            exit_price = exit_reason = None

            if float(row["Low"]) <= trade_sl:
                exit_price  = trade_sl
                exit_reason = "Stop-loss"
            elif float(row["High"]) >= trade_tp:
                exit_price  = trade_tp
                exit_reason = "Take-profit"
            elif days_held >= max_days:
                exit_price  = float(row["Close"])
                exit_reason = f"Timeout ({days_held}d)"

            if exit_price is not None:
                pl_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_date":  entry_date,
                    "exit_date":   df.index[i].strftime("%Y-%m-%d"),
                    "entry_price": round(entry_price, 2),
                    "exit_price":  round(exit_price, 2),
                    "sl":          round(trade_sl, 2),
                    "tp":          round(trade_tp, 2),
                    "pl_pct":      round(pl_pct, 2),
                    "days_held":   days_held,
                    "exit_reason": exit_reason,
                    "win":         pl_pct > 0,
                })
                in_trade = False

        if not in_trade:
            # Slice med precomputed indikatorer – inga re-beräkningar, konstant tid
            sub = df.iloc[max(0, i - 34):i + 1]  # 35 rader räcker för alla indikatorer
            try:
                sig         = gen_signal(sub)
                kurs        = float(row["Close"])
                sltp        = calc_sltp(sub, kurs)
                market_bull = bool(float(row["MA50"]) > float(row["MA200"]))
                swing       = calc_swing_score(sub, sig, market_bull)
            except Exception:
                continue

            if swing["score"] >= min_score:
                next_open   = float(df.iloc[i + 1]["Open"])
                entry_price = next_open
                entry_date  = df.index[i].strftime("%Y-%m-%d")
                entry_idx   = i + 1

                risk = entry_price - sltp["stop_loss"]
                if risk <= 0:
                    continue
                trade_sl = sltp["stop_loss"]
                trade_tp = entry_price + 2 * risk  # 2:1 R/R
                in_trade = True

    return trades


# ── Finansinspektionen – insynsregister ───────────────────────────────────────

_FI_AUTOCOMPLETE = "https://marknadssok.fi.se/Publiceringsklient/sv-SE/AutoComplete/H%C3%A4mtaAutoCompleteListaFull"
_FI_SEARCH       = "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search"
_FI_HEADERS      = {"User-Agent": "Mozilla/5.0"}
_insider_cache: dict = {}  # name:days → {result, ts}
_fi_name_cache: dict = {}  # clean query → resolved fi_name


def _fi_autocomplete(query):
    """Slår upp rätt bolagsnamn via autocomplete och väljer kandidaten med flest trades."""
    if query in _fi_name_cache:
        return _fi_name_cache[query]

    try:
        r = req.get(_FI_AUTOCOMPLETE,
                    params={"sokfunktion": "Insyn", "sokterm": query, "falt": "Utgivare"},
                    headers=_FI_HEADERS, timeout=5)
        candidates = r.json()[:5]
    except Exception:
        return query
    if not candidates:
        return query
    if len(candidates) == 1:
        _fi_name_cache[query] = candidates[0]
        return candidates[0]

    # Testa varje kandidat mot de senaste 365 dagarna och välj den med flest rader
    date_from = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")
    best_name, best_count = candidates[0], -1
    for candidate in candidates:
        try:
            time.sleep(0.3)  # undvik rate-limiting från FI
            resp = req.get(_FI_SEARCH, params={
                "SearchFunctionType": "Insyn",
                "Utgivare":           candidate,
                "Transaktionsdatum.From": date_from,
                "Transaktionsdatum.To":   date_to,
                "button": "export", "language": "sv-SE",
            }, headers=_FI_HEADERS, timeout=8)
            count = resp.content.decode("utf-16-le").count("\n") - 1
            if count > best_count:
                best_count, best_name = count, candidate
        except Exception:
            continue
    _fi_name_cache[query] = best_name
    return best_name


def fetch_insider_trades(name, days=90):
    """Hämtar insynstransaktioner från FI för ett bolag (senaste N dagar)."""
    cache_key = f"{name}:{days}"
    cached = _insider_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < 3600:  # 1h cache
        return cached["result"]

    # Rensa aktieklass-suffix och hitta FI-namn via autocomplete
    clean = re.sub(r"\s+(A|B|C|AB|publ\.?|\(publ\))$", "", name, flags=re.IGNORECASE).strip()
    fi_name = _fi_autocomplete(clean)

    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")

    try:
        r = req.get(_FI_SEARCH, params={
            "SearchFunctionType": "Insyn",
            "Utgivare":           fi_name,
            "Transaktionsdatum.From": date_from,
            "Transaktionsdatum.To":   date_to,
            "button":   "export",
            "language": "sv-SE",
        }, headers=_FI_HEADERS, timeout=10)
        content = r.content.decode("utf-16-le")
    except Exception as e:
        return {"trades": [], "summary": None, "fi_name": fi_name, "error": str(e)}

    def parse_num(s):
        s = str(s).replace("\xa0", "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
        try: return float(s)
        except ValueError: return 0.0

    trades = []
    reader = csv.DictReader(io.StringIO(content), delimiter=";")
    for row in reader:
        try:
            karaktar = row.get("Karaktär", "")
            is_buy   = "förvärv" in karaktar.lower()
            is_sell  = "avyttring" in karaktar.lower()
            vol      = parse_num(row.get("Volym", "0"))
            pris     = parse_num(row.get("Pris", "0"))
            valuta   = row.get("Valuta", "SEK")
            value    = vol * pris
            # Grov valutakonvertering till SEK
            if valuta == "USD": value *= 10.5
            elif valuta == "EUR": value *= 11.0
            trades.append({
                "date":       row.get("Transaktionsdatum", "")[:10],
                "pub_date":   row.get("Publiceringsdatum", "")[:10],
                "name":       row.get("Person i ledande ställning", ""),
                "role":       row.get("Befattning", "").replace("\xa0", " ").strip(),
                "type":       karaktar,
                "is_buy":     is_buy,
                "is_sell":    is_sell,
                "volume":     round(vol),
                "price":      round(pris, 2),
                "currency":   valuta,
                "value_sek":  round(value),
            })
        except Exception:
            continue

    buys  = [t for t in trades if t["is_buy"]]
    sells = [t for t in trades if t["is_sell"]]
    net   = sum(t["value_sek"] for t in buys) - sum(t["value_sek"] for t in sells)

    def fmt(v):
        av = abs(v)
        if av >= 1_000_000: return f"{v/1_000_000:+.1f} MSEK"
        if av >= 1_000:     return f"{v/1_000:+.0f} kSEK"
        return f"{v:+.0f} SEK"

    summary = {
        "buy_count":     len(buys),
        "sell_count":    len(sells),
        "total":         len(trades),
        "unique_buyers": len({t["name"] for t in buys}),
        "net_value":     round(net),
        "net_fmt":       fmt(net) if trades else "–",
        "signal":        "bullish" if net > 0 and buys else ("bearish" if net < 0 and sells else "neutral"),
    }

    result = {"trades": trades, "summary": summary, "fi_name": fi_name}
    _insider_cache[cache_key] = {"result": result, "ts": time.time()}
    return result


# ── Portfolio Strategy Backtest ───────────────────────────────────────────────

# ── Indikatorer ───────────────────────────────────────────────────────────────

def calc_rsi(s, n=14):
    """Beräknar RSI med Wilder's Smoothing (standard)."""
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    rsi = 100 - 100 / (1 + g / l.replace(0, 1e-9))
    return rsi

def calc_macd(s, fast=12, slow=26, sig=9):
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sl = m.ewm(span=sig, adjust=False).mean()
    return m, sl, m - sl

def calc_bb(close, n=20, num_std=2):
    ma  = close.rolling(n).mean()
    std = close.rolling(n).std()
    return ma + num_std * std, ma, ma - num_std * std

def calc_atr(df, n=14):
    """Beräknar ATR med Wilder's Smoothing."""
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def calc_obv(df):
    """Beräknar On-Balance Volume (OBV)."""
    obv = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
    return obv

# ... resten av dina befintliga hjälpfunktioner (gen_signal, calc_sltp, fetch_market_data etc) ...

# ── Portfolio Strategy Backtest ───────────────────────────────────────────────

def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size_val=10, config=None):
    conf = config or {}
    comm_val = float(conf.get("comm_val", 0))
    pos_size_pct = 0.20 # 20% per aktie (max 5 st) för optimal balans

    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=years * 365)
    
    idx_ticker = "^OMX" if conf.get("market") == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=400), end=end_dt)
    if not idx_df.empty:
        if idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
        idx_df.index = idx_df.index.normalize()

    all_data = {}
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=400), end=end_dt)
            if not df.empty and len(df) > 150:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df.index = df.index.normalize()
                df["MA200"] = df.Close.rolling(200).mean()
                df["EMA5"] = df.Close.ewm(span=5, adjust=False).mean()
                df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
                all_data[sym] = df
        except: continue

    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []

    while current_date <= end_dt:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1); continue
        
        # 1. Hantera exits
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            day_data = df[df.index <= current_date].tail(1)
            if day_data.empty: still_holding.append(h); continue
            row = day_data.iloc[0]
            h["days_held"] += 1
            
            # BREAKEVEN GUARD: Vid 5% vinst, flytta SL till entry
            if (row.Close / h["entry_price"] - 1) > 0.05 and h["sl"] < h["entry_price"]:
                h["sl"] = h["entry_price"]

            exit_p, exit_r = None, None
            
            # EXIT 1: Stop-loss
            if row.Low <= h["sl"]: 
                exit_p, exit_r = h["sl"], "Stop-Loss/Breakeven"
            
            # EXIT 2: Trend Harvesting (Efter 10 dagar, sälj om vi bryter EMA5)
            elif h["days_held"] >= 10:
                if row.Close < row.EMA5:
                    exit_p, exit_r = row.Close, f"Harvest Exit ({h['days_held']}d)"
            
            if exit_p:
                cash += (h["qty"] * exit_p) - comm_val
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": current_date.strftime("%Y-%m-%d"), "pl": round((exit_p - h["entry_price"]) * h["qty"] - (2*comm_val), 2), "pl_pct": round(((exit_p/h["entry_price"])-1)*100, 2), "reason": exit_r})
            else: still_holding.append(h)
        holdings = still_holding

        # 2. Köp ny (Kvalitets-sniping)
        cur_v = cash + sum(h["qty"] * float(all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].Close.iloc[-1]) for h in holdings if not all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].empty)
        target_pos = cur_v * pos_size_pct
        
        if cash >= target_pos + comm_val:
            best_sym = None
            for sym, df in all_data.items():
                if any(h["symbol"] == sym for h in holdings): continue
                past = df[df.index <= current_date].tail(2)
                if len(past) < 2: continue
                try:
                    r_now = past.iloc[-1]
                    r_prev = past.iloc[-2]
                    # SNIPER ENTRY: RSI < 40 OCH RSI har vänt uppåt (Momentum-skifte)
                    if r_now.RSI < 40 and r_now.RSI > r_prev.RSI and r_now.Close > r_now.MA200:
                        best_sym = sym; break 
                except: continue
            
            if best_sym:
                row = all_data[best_sym][all_data[best_sym].index <= current_date].tail(1).iloc[0]
                entry = float(row.Close)
                # Sätt en vid SL (3.5x ATR)
                holdings.append({"symbol": best_sym, "entry_price": entry, "sl": entry - (3.5 * row.ATR), "qty": target_pos / entry, "entry_date": current_date, "days_held": 0, "buy_fee": comm_val, "hwm": entry})
                cash -= (target_pos + comm_val)

        if current_date.weekday() == 0: history.append({"date": current_date.strftime("%Y-%m-%d"), "value": round(cur_v, 2)})
        current_date += timedelta(days=1)

    for h in holdings:
        last_p = float(all_data[h["symbol"]].Close.iloc[-1])
        trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": end_dt.strftime("%Y-%m-%d"), "pl": round((last_p - h["entry_price"]) * h["qty"] - (2*comm_val), 2), "pl_pct": round(((last_p/h["entry_price"])-1)*100, 2), "reason": "Testslut"})
        cash += (h["qty"] * last_p) - comm_val
    return {"final_value": round(cash, 2), "total_return_pct": round((cash/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}


@app.route("/api/backtest/strategy", methods=["POST"])
def strategy_backtest_route():
    data = request.json or {}
    years = int(data.get("years", 1))
    pos_size = float(data.get("pos_size", 20000))
    capital = float(data.get("capital", 100000))
    market = data.get("market", "omxs")
    
    config = {
        "min_score": data.get("min_score", 7),
        "exit_type": data.get("exit_type", "sltp"),
        "sl_pct": data.get("sl_pct", 5),
        "tp_pct": data.get("tp_pct", 10),
        "comm_type": data.get("comm_type", "fixed"),
        "comm_val": data.get("comm_val", 0)
    }
    
    symbols = OMXS_50 if market == "omxs" else NASDAQ_100
    result = run_strategy_backtest(symbols, years, capital, pos_size, config)
    return jsonify(result)


def load_json(fname, default):
    path = os.path.join(BASE, fname)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(fname, data):
    path = os.path.join(BASE, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/market")
def market_route():
    tk = yf.Ticker("^OMX")
    df = tk.history(period="1y")[["Close"]].copy()
    df["MA50"]  = df.Close.rolling(50).mean()
    df["MA200"] = df.Close.rolling(200).mean()
    df.dropna(inplace=True)
    if df.empty:
        return jsonify({"error": "Ingen data"}), 500
    latest = df.iloc[-1]
    bull = bool(latest.MA50 > latest.MA200)
    cross = (df.MA50 > df.MA200) != (df.MA50.shift(1) > df.MA200.shift(1))
    cross_date = df.index[cross].max() if cross.any() else None
    return jsonify({
        "kurs": round(float(latest.Close), 2),
        "ma50": round(float(latest.MA50), 2),
        "ma200": round(float(latest.MA200), 2),
        "bull": bull,
        "trend": "Golden Cross (aktiv)" if bull else "Death Cross (aktiv)",
        "cross_date": cross_date.strftime("%Y-%m-%d") if cross_date is not None else None,
    })


@app.route("/api/search")
def search_route():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    # Sök lokalt i ALL_STOCKS först (träffar på namn och ticker)
    ql = q.lower()
    local = []
    for sym, name in ALL_STOCKS.items():
        if ql in name.lower() or ql in sym.lower():
            if sym in CRYPTO:
                exch = "Krypto"
            elif sym in ETFS:
                exch = "ETF"
            elif sym in FIRST_NORTH:
                exch = "First North"
            elif sym in NASDAQ_100:
                exch = "Nasdaq 100"
            else:
                exch = "Nasdaq Stockholm"
            local.append({"symbol": sym, "name": name, "exchange": exch})
        if len(local) >= 10:
            break

    if local:
        return jsonify(local)

    # Fallback: Yahoo Finance API för aktier utanför listorna
    try:
        r = req.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": 10, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        quotes = r.json().get("quotes", [])
        return jsonify([
            {"symbol": qt.get("symbol"), "name": qt.get("longname") or qt.get("shortname", ""),
             "exchange": qt.get("exchDisp", "")}
            for qt in quotes if qt.get("quoteType") in ("EQUITY", "ETF")
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze", methods=["POST"])
def analyze_route():
    data = request.json
    results = [r for s in data.get("symbols", [])
               if (r := analyze_stock(s, data.get("period", "3mo")))]
    return jsonify(results)


@app.route("/api/compare", methods=["POST"])
def compare_route():
    data   = request.json
    period = data.get("period", "3mo")
    result = []
    for sym in data.get("symbols", []):
        df = yf.Ticker(sym).history(period=period)[["Close"]]
        if df.empty:
            continue
        try:
            info = yf.Ticker(sym).info
            name = info.get("longName") or info.get("shortName") or sym
        except Exception:
            name = sym
        base = float(df.Close.iloc[0])
        ret  = (float(df.Close.iloc[-1]) / base - 1) * 100
        result.append({
            "symbol": sym, "name": name,
            "values": (df.Close / base * 100).round(2).tolist(),
            "dates":  [d.strftime("%Y-%m-%d") for d in df.index],
            "return": f"{ret:+.1f}%",
            "return_val": round(ret, 2),
        })
    return jsonify(result)


@app.route("/api/screener")
def screener_route():
    force   = request.args.get("force", "0") == "1"
    markets = request.args.getlist("markets") or ["omxs"]

    # Bygg symbollista från valda marknader
    symbols = {}
    for m in markets:
        if m in STOCK_LISTS:
            symbols.update(STOCK_LISTS[m][1])
    if not symbols:
        symbols = OMXS_50

    # Cachning bara för standard-valet (omxs ensamt)
    use_cache = markets == ["omxs"]
    if use_cache:
        cached = _screener_cache["data"]
        age    = time.time() - _screener_cache["ts"]
        if cached and not force:
            return jsonify({"data": cached, "cached": True,
                            "age_min": round(age / 60, 1),
                            "ts": _screener_cache["ts"]})

    data = run_screener(symbols)

    if use_cache:
        _screener_cache["data"] = data
        _screener_cache["ts"]   = time.time()

    return jsonify({"data": data, "cached": False,
                    "age_min": 0, "ts": time.time()})


# ── Krypto-endpoints ──────────────────────────────────────────────────────────

@app.route("/api/crypto/analyze", methods=["POST"])
def crypto_analyze_route():
    """Kör analyze_crypto() parallellt för lista av symbols."""
    data    = request.json or {}
    symbols = data.get("symbols", [])
    period  = data.get("period", "3mo")
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(analyze_crypto, sym, period): sym for sym in symbols}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)
    return jsonify(results)


@app.route("/api/crypto/screener")
def crypto_screener_route():
    """Kör crypto_screener_analyze() för alla CRYPTO-coins. Cache 10 min."""
    force = request.args.get("force", "0") == "1"
    cached_data = _crypto_screener_cache["data"]
    age         = time.time() - _crypto_screener_cache["ts"]
    if cached_data and not force and age < 600:  # 10 min cache
        return jsonify({
            "data":   cached_data,
            "cached": True,
            "global": fetch_crypto_global(),
        })

    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(crypto_screener_analyze, sym, name): sym
                   for sym, name in CRYPTO.items()}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    rek_order = {"kop": 0, "kop-hall": 1, "hall-salj": 2, "salj": 3}
    results.sort(key=lambda x: (rek_order.get(x["rek_klass"], 9),
                                -x.get("swing_score", 0), -x["strength"]))

    _crypto_screener_cache["data"] = results
    _crypto_screener_cache["ts"]   = time.time()
    return jsonify({
        "data":   results,
        "cached": False,
        "global": fetch_crypto_global(),
    })


@app.route("/api/crypto/prices")
def crypto_prices_route():
    """Batch-hämtning av live-priser för alla crypto-coins i ett CoinGecko-anrop."""
    ids     = list(_COINGECKO_IDS.values())
    id_map  = {v: k for k, v in _COINGECKO_IDS.items()}  # cg_id → symbol
    try:
        r = req.get(
            f"{_CG_BASE}/simple/price",
            params={
                "ids":               ",".join(ids),
                "vs_currencies":     "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol":  "true",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        raw = r.json()
        result = {}
        for cg_id, d in raw.items():
            sym = id_map.get(cg_id)
            if sym:
                result[sym] = {
                    "price":      float(d.get("usd", 0)),
                    "change_24h": float(d.get("usd_24h_change", 0) or 0),
                    "market_cap": float(d.get("usd_market_cap", 0) or 0),
                    "volume_24h": float(d.get("usd_24h_vol", 0) or 0),
                }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/crypto/global")
def crypto_global_route():
    """Returnerar global kryptomarknadsdata."""
    return jsonify(fetch_crypto_global())


@app.route("/api/backtest", methods=["POST"])
def backtest_route():
    data      = request.json or {}
    period    = data.get("period", "2y")
    min_score = int(data.get("min_score", 6))
    max_days  = int(data.get("max_days", 30))
    markets   = data.get("markets") or ["omxs"]

    # Bygg symbollista från valda marknader
    sym_map: dict = {}
    for m in markets:
        if m in STOCK_LISTS:
            sym_map.update(STOCK_LISTS[m][1])
    if not sym_map:
        sym_map = OMXS_50

    symbols = data.get("symbols") or list(sym_map.keys())

    def run_one(sym):
        trades = run_backtest_symbol(sym, period, min_score, max_days)
        return {"symbol": sym, "name": sym_map.get(sym, ALL_STOCKS.get(sym, sym)),
                "trades": trades, "stats": compute_backtest_stats(trades)}

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(run_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda x: -(x["stats"]["total"] if x["stats"] else 0))
    all_trades = [t for r in results for t in r["trades"]]
    return jsonify({"results": results, "overall": compute_backtest_stats(all_trades)})


def backtest_insider_signal(symbol, name, lookback_days=730):
    """Simulerar köp på publiceringsdatum för varje insider-köp de senaste N dagarna."""
    fi_data    = fetch_insider_trades(name, days=lookback_days)
    buy_trades = [t for t in fi_data.get("trades", []) if t["is_buy"] and t.get("pub_date")]
    if not buy_trades:
        return {"trades": [], "stats": None, "fi_name": fi_data.get("fi_name", "")}

    # Hämta historisk prisdata (behöver 5 år för att täcka +90 dagar efter äldsta trade)
    tk = yf.Ticker(symbol)
    df = tk.history(period="5y")[["Close"]].copy()
    if df.empty:
        return {"trades": [], "stats": None, "fi_name": fi_data.get("fi_name", "")}

    # Normalisera index: ta bort tidszoner för enkel jämförelse
    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
    df.index = df.index.normalize()

    def price_at_offset(date_str, offset_trading_days):
        """Stängningskurs offset handelsdagar från date_str (nästa handelsdag om ej börsdag)."""
        try:
            target = pd.Timestamp(date_str).normalize()
            pos = df.index.searchsorted(target)          # närmaste index >= target
            target_pos = pos + offset_trading_days
            if target_pos >= len(df):
                return None
            return round(float(df.iloc[target_pos]["Close"]), 2)
        except Exception:
            return None

    results = []
    for t in buy_trades:
        entry = price_at_offset(t["pub_date"], 0)
        if entry is None:
            continue
        r30 = price_at_offset(t["pub_date"], 30)
        r60 = price_at_offset(t["pub_date"], 60)
        r90 = price_at_offset(t["pub_date"], 90)

        def pct(p):
            return round((p - entry) / entry * 100, 2) if p else None

        results.append({
            "pub_date":    t["pub_date"],
            "trade_date":  t["date"],
            "insider":     t["name"],
            "role":        t["role"],
            "volume":      t["volume"],
            "fi_price":    t["price"],
            "currency":    t["currency"],
            "entry_price": entry,
            "r30":         pct(r30),
            "r60":         pct(r60),
            "r90":         pct(r90),
        })

    def horizon_stats(key):
        vals = [t[key] for t in results if t[key] is not None]
        if not vals:
            return None
        wins = [v for v in vals if v > 0]
        return {
            "n":        len(vals),
            "win_rate": round(len(wins) / len(vals) * 100, 1),
            "avg":      round(sum(vals) / len(vals), 2),
            "best":     round(max(vals), 2),
            "worst":    round(min(vals), 2),
        }

    return {
        "trades":  results,
        "fi_name": fi_data.get("fi_name", ""),
        "stats": {
            "total": len(results),
            "h30":   horizon_stats("r30"),
            "h60":   horizon_stats("r60"),
            "h90":   horizon_stats("r90"),
        },
    }


@app.route("/api/insider", methods=["POST"])
def insider_route():
    data = request.json or {}
    name = data.get("name", "")
    days = int(data.get("days", 90))
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(fetch_insider_trades(name, days))


@app.route("/api/insider/backtest", methods=["POST"])
def insider_backtest_route():
    data   = request.json or {}
    symbol = data.get("symbol", "")
    name   = data.get("name", "")
    days   = int(data.get("days", 730))
    if not symbol or not name:
        return jsonify({"error": "symbol and name required"}), 400
    return jsonify(backtest_insider_signal(symbol, name, days))


def _fetch_fi_chunk(date_from, date_to):
    """Hämtar ett datumintervall från FI och returnerar råtext (utf-16-le decoded)."""
    r = req.get(_FI_SEARCH, params={
        "SearchFunctionType": "Insyn",
        "Publiceringsdatum.From": date_from,
        "Publiceringsdatum.To":   date_to,
        "button":   "export",
        "language": "sv-SE",
    }, headers=_FI_HEADERS, timeout=60)
    return r.content.decode("utf-16-le")


FI_EXCHANGE_FILTERS = {
    "nasdaq_stockholm": "NASDAQ STOCKHOLM",
    "first_north":      "FIRST NORTH",
    "spotlight":        "SPOTLIGHT",
    "ngm":              "NGM",
}


def fetch_all_insider_buys(days, exchanges=None):
    """Hämtar ALLA insider-köp för valda handelsplatser de senaste N dagarna.
    Delar upp i månadsvis anrop för att kringgå FI:s exportgräns (~500 rader/anrop).
    exchanges: lista av nycklar från FI_EXCHANGE_FILTERS, None = alla svenska.
    """
    now = datetime.now()
    # Bygg lista av månadsintervall bakåt i tiden
    intervals = []
    chunk_end = now
    remaining = days
    while remaining > 0:
        chunk_days = min(remaining, 30)
        chunk_start = chunk_end - timedelta(days=chunk_days)
        intervals.append((
            chunk_start.strftime("%Y-%m-%d"),
            chunk_end.strftime("%Y-%m-%d"),
        ))
        chunk_end = chunk_start
        remaining -= chunk_days

    all_content_parts = []
    header_line = None
    last_err = None
    for date_from, date_to in intervals:
        try:
            content = _fetch_fi_chunk(date_from, date_to)
            lines = content.splitlines()
            if not lines:
                continue
            if header_line is None:
                header_line = lines[0]
                all_content_parts.extend(lines)
            else:
                # Hoppa över header-raden i efterföljande chunk
                all_content_parts.extend(lines[1:])
        except Exception as e:
            last_err = str(e)
            continue

    if not all_content_parts:
        return [], last_err or "Inga data från FI"

    combined = "\n".join(all_content_parts)

    def parse_num(s):
        s = str(s).replace("\xa0","").replace("\u00a0","").replace(" ","").replace(",",".")
        try: return float(s)
        except ValueError: return 0.0

    trades = []
    reader = csv.DictReader(io.StringIO(combined), delimiter=";")
    for row in reader:
        try:
            karaktar = row.get("Karaktär", "")
            if "förvärv" not in karaktar.lower():
                continue
            # Filtrera på handelsplats
            plats = row.get("Handelsplats", "").upper()
            if exchanges:
                allowed = [FI_EXCHANGE_FILTERS[e] for e in exchanges if e in FI_EXCHANGE_FILTERS]
                if not any(a in plats for a in allowed):
                    continue
            elif not plats:
                continue
            pub_date = row.get("Publiceringsdatum", "")[:10]
            if not pub_date:
                continue
            emittent   = row.get("Emittent", "").strip()
            instrument = row.get("Instrumentnamn", "").strip()
            if not emittent:
                continue
            vol   = parse_num(row.get("Volym", "0"))
            pris  = parse_num(row.get("Pris", "0"))
            valuta = row.get("Valuta", "SEK")
            trades.append({
                "pub_date":    pub_date,
                "date":        row.get("Transaktionsdatum", "")[:10],
                "fi_company":  emittent,
                "instrument":  instrument,
                "insider":     row.get("Person i ledande ställning", ""),
                "role":        row.get("Befattning", "").replace("\xa0", " ").strip(),
                "volume":      round(vol),
                "price":       round(pris, 2),
                "currency":    valuta,
            })
        except Exception:
            continue
    return trades, None


# Cache: fi_company → (symbol, display_name) eller None
_ticker_resolve_cache: dict = {}

_YF_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
_YF_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _resolve_ticker(fi_company, instrument=""):
    """Slår upp Yahoo Finance-ticker för ett FI-bolagsnamn.
    Kontrollerar först OMXS_50-listan, sedan Yahoo Finance-sökning.
    Returnerar (symbol, display_name) eller None. Resultat cachas permanent.
    """
    if not fi_company:
        return None

    cache_key = fi_company.lower()
    if cache_key in _ticker_resolve_cache:
        return _ticker_resolve_cache[cache_key]

    # 1. Försök matcha mot OMXS_50 via namnlikhet
    fi_lower = fi_company.lower()
    best_sym, best_name, best_len = None, None, 0
    for sym, name in OMXS_50.items():
        clean = re.sub(r"\s+(A|B|C|D|AB|publ\.?|\(publ\))$", "", name, flags=re.IGNORECASE).strip().lower()
        for key in (name.lower(), clean):
            if len(key) < 4:
                continue
            if re.search(r'(?<![a-zåäö])' + re.escape(key) + r'(?![a-zåäö])', fi_lower):
                if len(key) > best_len:
                    best_sym, best_name, best_len = sym, name, len(key)

    if best_sym:
        result = (best_sym, best_name)
        _ticker_resolve_cache[cache_key] = result
        return result

    # 2. Fallback: Yahoo Finance-sökning – prova bolagsnamn, sedan instrumentnamn
    for query in filter(None, [fi_company, instrument]):
        try:
            r = req.get(_YF_SEARCH,
                        params={"q": query, "quotesCount": 8, "newsCount": 0},
                        headers=_YF_HEADERS, timeout=5)
            quotes = r.json().get("quotes", [])
            # Välj första .ST-aktie
            for qt in quotes:
                sym = qt.get("symbol", "")
                if sym.endswith(".ST") and qt.get("quoteType") == "EQUITY":
                    name = qt.get("longname") or qt.get("shortname") or fi_company
                    result = (sym, name)
                    _ticker_resolve_cache[cache_key] = result
                    return result
        except Exception:
            continue

    _ticker_resolve_cache[cache_key] = None
    return None


@app.route("/api/markets")
def markets_route():
    """Returnerar tillgängliga börsnoteringlistor."""
    return jsonify([
        {"id": k, "label": v[0], "count": len(v[1])}
        for k, v in STOCK_LISTS.items()
    ])


# ── Nyhetssentiment (VADER NLP) ───────────────────────────────────────────────

_news_cache: dict = {}  # symbol → {result, ts}

def fetch_news_sentiment(symbol):
    """Hämtar senaste nyheter via yfinance och beräknar sentiment med VADER."""
    cached = _news_cache.get(symbol)
    if cached and time.time() - cached["ts"] < 1800:  # 30 min cache
        return cached["result"]

    try:
        tk    = yf.Ticker(symbol)
        news  = tk.news or []
    except Exception:
        news = []

    articles = []
    for item in news[:15]:
        c = item.get("content", item)
        title   = c.get("title") or item.get("title", "")
        summary = c.get("summary") or c.get("description", "")
        pub     = c.get("pubDate") or item.get("providerPublishTime", "")
        source  = (c.get("provider") or {}).get("displayName") or item.get("publisher", "")

        text = f"{title}. {summary}".strip(". ")
        if not text:
            continue

        if _vader:
            sc = _vader.polarity_scores(text)
            compound = round(sc["compound"], 3)
        else:
            compound = 0.0

        articles.append({
            "title":    title,
            "source":   source,
            "pub_date": str(pub)[:10] if pub else "",
            "sentiment": compound,
            "label":    "positiv" if compound >= 0.05 else ("negativ" if compound <= -0.05 else "neutral"),
        })

    if not articles:
        result = {"articles": [], "avg_sentiment": None, "signal": "ingen data"}
    else:
        avg = round(sum(a["sentiment"] for a in articles) / len(articles), 3)
        result = {
            "articles":     articles,
            "avg_sentiment": avg,
            "signal": "positiv" if avg >= 0.05 else ("negativ" if avg <= -0.05 else "neutral"),
        }

    _news_cache[symbol] = {"result": result, "ts": time.time()}
    return result


# ── Google Trends ─────────────────────────────────────────────────────────────

_trends_cache: dict = {}  # query → {result, ts}

def fetch_google_trends(company_name, symbol):
    """Hämtar Google Trends-data för ett bolag (sökvolymtrend senaste 90 dagarna)."""
    cache_key = symbol
    cached = _trends_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < 3600 * 6:  # 6h cache
        return cached["result"]

    if not _pytrends:
        return {"error": "pytrends ej installerat", "trend": None}

    # Rensa namn för sökning
    clean = re.sub(r"\s+(A|B|C|AB|publ\.?|\(publ\)|Ltd\.?|Inc\.?|Corp\.?)$",
                   "", company_name, flags=re.IGNORECASE).strip()
    # Inga .ST-suffix i Google-sökning
    clean = re.sub(r"\.(ST|US|L|DE)$", "", clean).strip()

    try:
        _pytrends.build_payload([clean], timeframe="today 3-m", geo="SE")
        df = _pytrends.interest_over_time()
        if df.empty or clean not in df.columns:
            result = {"query": clean, "trend": None, "signal": "ingen data", "values": []}
        else:
            vals = df[clean].tolist()
            dates = [d.strftime("%Y-%m-%d") for d in df.index]
            # Jämför senaste 2 veckor mot 4 veckor dessförinnan
            recent = vals[-2:] if len(vals) >= 2 else vals
            older  = vals[-6:-2] if len(vals) >= 6 else vals[:max(1, len(vals)-2)]
            avg_recent = sum(recent) / len(recent) if recent else 0
            avg_older  = sum(older)  / len(older)  if older  else 0
            change = round((avg_recent - avg_older) / max(avg_older, 1) * 100, 1)
            result = {
                "query":   clean,
                "values":  list(zip(dates, vals)),
                "change_pct": change,
                "signal": "stigande" if change > 15 else ("fallande" if change < -15 else "stabilt"),
                "current": round(avg_recent, 1),
            }
    except Exception as e:
        result = {"query": clean, "trend": None, "signal": "fel", "error": str(e), "values": []}

    _trends_cache[cache_key] = {"result": result, "ts": time.time()}
    return result


# ── Blankning (short interest) ────────────────────────────────────────────────

_short_cache: dict = {}  # symbol → {result, ts}

def fetch_short_interest(symbol, company_name):
    """Hämtar blankning/short interest.
    För US-aktier: yfinance info (shortPercentOfFloat).
    För svenska aktier: FI:s blankningsregister (aggregerade nettopositioner).
    """
    cached = _short_cache.get(symbol)
    if cached and time.time() - cached["ts"] < 3600 * 4:  # 4h cache
        return cached["result"]

    is_swedish = symbol.endswith(".ST")

    if not is_swedish:
        # US/internationell – yfinance har short data
        try:
            info = yf.Ticker(symbol).info
            pct  = info.get("shortPercentOfFloat")
            ratio = info.get("shortRatio")
            result = {
                "short_pct":   round(pct * 100, 2) if pct else None,
                "short_ratio": round(ratio, 2) if ratio else None,
                "source":      "Yahoo Finance",
                "signal": ("hög" if pct and pct > 0.10 else
                           ("medel" if pct and pct > 0.05 else "låg")) if pct else "okänd",
            }
        except Exception as e:
            result = {"short_pct": None, "source": "Yahoo Finance", "signal": "fel", "error": str(e)}
    else:
        # Svenska aktier – FI:s blankningsregister
        try:
            r = req.get(
                "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search",
                params={
                    "SearchFunctionType": "Blankning",
                    "Emittent": company_name,
                    "button": "export", "language": "sv-SE",
                },
                headers=_FI_HEADERS, timeout=15,
            )
            content = r.content.decode("utf-16-le")
            reader  = csv.DictReader(io.StringIO(content), delimiter=";")
            rows    = list(reader)

            positions = []
            for row in rows:
                pct_str = row.get("Nettokorposition", row.get("Position", "0"))
                try:
                    pct_val = float(str(pct_str).replace(",", ".").replace("%", "").strip())
                    holder  = row.get("Innehavare", row.get("Anmälningsskyldig", ""))
                    date    = row.get("Positionsdatum", row.get("Publiceringsdatum", ""))[:10]
                    if pct_val > 0:
                        positions.append({"holder": holder, "pct": pct_val, "date": date})
                except Exception:
                    continue

            total = round(sum(p["pct"] for p in positions), 2) if positions else None
            result = {
                "short_pct":  total,
                "positions":  positions[:5],
                "source":     "Finansinspektionen",
                "signal": ("hög" if total and total > 5 else
                           ("medel" if total and total > 2 else "låg")) if total else "okänd",
            }
        except Exception as e:
            result = {"short_pct": None, "source": "FI", "signal": "fel", "error": str(e)}

    _short_cache[symbol] = {"result": result, "ts": time.time()}
    return result


@app.route("/api/signals/extra", methods=["POST"])
def extra_signals_route():
    """Hämtar nyhetssentiment, Google Trends och blankning för en aktie."""
    data   = request.json or {}
    symbol = data.get("symbol", "")
    name   = data.get("name", symbol)
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    # Kör alla tre parallellt
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_news   = ex.submit(fetch_news_sentiment, symbol)
        f_trends = ex.submit(fetch_google_trends, name, symbol)
        f_short  = ex.submit(fetch_short_interest, symbol, name)
        news   = f_news.result()
        trends = f_trends.result()
        short  = f_short.result()

    return jsonify({"news": news, "trends": trends, "short": short})


# ── Politiker-handel (US Congress / STOCK Act) ────────────────────────────────

_QUIVER_URL   = "https://api.quiverquant.com/beta/live/congresstrading"
_congress_cache: dict = {"data": None, "ts": 0.0}


def fetch_congress_trades_raw():
    """Hämtar senaste ~1000 kongresstransaktioner från Quiver Quant (gratis, ingen nyckel)."""
    if _congress_cache["data"] and time.time() - _congress_cache["ts"] < 3600 * 4:
        return _congress_cache["data"]
    try:
        r = req.get(_QUIVER_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        data = r.json()
        _congress_cache["data"] = data
        _congress_cache["ts"]   = time.time()
        return data
    except Exception as e:
        return []


@app.route("/api/congress/scan", methods=["POST"])
def congress_scan_route():
    """Hämtar politiker-köp och räknar avkastning till idag.
    Matchar US-tickers mot kursdata och visar per politiker + per aktie.
    """
    data   = request.json or {}
    months = int(data.get("months", 3))
    txn_type = data.get("type", "purchase")   # purchase | sale | all
    chamber  = data.get("chamber", "all")     # all | Senate | Representatives
    party    = data.get("party", "all")       # all | R | D

    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    today  = pd.Timestamp.now().normalize()

    raw = fetch_congress_trades_raw()
    if not raw:
        return jsonify({"error": "Kunde inte hämta data från Quiver Quant", "trades": []}), 500

    # Filtrera
    filtered = []
    for t in raw:
        if t.get("TickerType") not in ("Stock", "ST", None):
            continue
        if t.get("TransactionDate", "") < cutoff:
            continue
        txn = (t.get("Transaction") or "").lower()
        if txn_type != "all" and txn_type.lower() not in txn:
            continue
        if chamber != "all" and t.get("House", "") != chamber:
            continue
        if party != "all" and t.get("Party", "") != party:
            continue
        ticker = (t.get("Ticker") or "").strip().upper()
        if not ticker or ticker in ("--", "N/A", ""):
            continue
        filtered.append(t)

    # Hämta unika tickers och dagens priser parallellt
    unique_tickers = list({t["Ticker"].upper() for t in filtered})

    def get_price_series(ticker):
        try:
            df = yf.Ticker(ticker).history(period="1y")[["Close"]].copy()
            if df.empty:
                return ticker, None
            df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
            df.index = df.index.normalize()
            return ticker, df
        except Exception:
            return ticker, None

    price_data: dict = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for ticker, df in ex.map(lambda t: get_price_series(t), unique_tickers):
            price_data[ticker] = df

    results = []
    for t in filtered:
        ticker = t["Ticker"].upper()
        df     = price_data.get(ticker)
        if df is None:
            continue
        try:
            txn_date = pd.Timestamp(t["TransactionDate"]).normalize()
            pos      = df.index.searchsorted(txn_date)
            if pos >= len(df):
                continue
            entry_price = round(float(df.iloc[pos]["Close"]), 2)
            today_price = round(float(df.iloc[-1]["Close"]), 2)
            ret_pct     = round((today_price - entry_price) / entry_price * 100, 2)
            held_days   = (today - txn_date).days

            results.append({
                "ticker":       ticker,
                "politician":   t.get("Representative", ""),
                "party":        t.get("Party", ""),
                "chamber":      t.get("House", ""),
                "txn_date":     t.get("TransactionDate", "")[:10],
                "report_date":  t.get("ReportDate", "")[:10],
                "transaction":  t.get("Transaction", ""),
                "amount_range": t.get("Range", ""),
                "entry_price":  entry_price,
                "today_price":  today_price,
                "return_pct":   ret_pct,
                "held_days":    held_days,
                "excess_return": round(t.get("ExcessReturn") or 0, 2),
                "spy_change":   round(t.get("SPYChange") or 0, 2),
            })
        except Exception:
            continue

    results.sort(key=lambda x: (x["return_pct"] is None, -(x["return_pct"] or 0)))

    rets  = [r["return_pct"] for r in results if r["return_pct"] is not None]
    wins  = [v for v in rets if v > 0]
    buys  = [r for r in results if "purchase" in r["transaction"].lower()]
    buy_rets = [r["return_pct"] for r in buys if r["return_pct"] is not None]

    # Topp-politiker (flest köp)
    pol_counts: dict = {}
    for r in results:
        p = r["politician"]
        pol_counts[p] = pol_counts.get(p, 0) + 1
    top_politicians = sorted(pol_counts.items(), key=lambda x: -x[1])[:10]

    # Topp-aktier (flest handlade av politiker)
    ticker_counts: dict = {}
    for r in buys:
        ticker_counts[r["ticker"]] = ticker_counts.get(r["ticker"], 0) + 1
    top_tickers = sorted(ticker_counts.items(), key=lambda x: -x[1])[:10]

    stats = {
        "total":          len(results),
        "purchases":      len(buys),
        "win_rate":       round(len([v for v in buy_rets if v > 0]) / len(buy_rets) * 100, 1) if buy_rets else None,
        "avg_return":     round(sum(buy_rets) / len(buy_rets), 2) if buy_rets else None,
        "best":           round(max(buy_rets), 2) if buy_rets else None,
        "worst":          round(min(buy_rets), 2) if buy_rets else None,
        "top_politicians": top_politicians,
        "top_tickers":    top_tickers,
    }

    return jsonify({"trades": results, "stats": stats, "months": months})


@app.route("/api/insider/scan", methods=["POST"])
def insider_scan_route():
    """Hämtar insider-köp för valda handelsplatser under en period och räknar avkastning till idag."""
    data      = request.json or {}
    months    = int(data.get("months", 6))
    exchanges = data.get("exchanges") or ["nasdaq_stockholm"]
    days      = months * 30

    today = pd.Timestamp.now().normalize()

    buy_trades, fetch_err = fetch_all_insider_buys(days, exchanges)
    if fetch_err and not buy_trades:
        return jsonify({"error": fetch_err, "trades": [], "stats": {"total": 0}}), 500

    # Lös upp unika bolag parallellt (Yahoo Finance-sökning för okända)
    unique_companies = {t["fi_company"]: t.get("instrument", "") for t in buy_trades}

    def resolve_one(fi_co, instr):
        return fi_co, _resolve_ticker(fi_co, instr)

    resolved: dict = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(resolve_one, co, instr): co for co, instr in unique_companies.items()}
        for fut in as_completed(futs):
            fi_co, hit = fut.result()
            resolved[fi_co] = hit

    matched: dict = {}  # symbol → {name, trades}
    unmatched = set()
    for t in buy_trades:
        hit = resolved.get(t["fi_company"])
        if hit is None:
            unmatched.add(t["fi_company"])
            continue
        sym, name = hit
        matched.setdefault(sym, {"name": name, "trades": []})["trades"].append(t)

    # Hämta kurser parallellt för matchade bolag
    results = []

    def price_rows(sym, entry_data):
        try:
            tk = yf.Ticker(sym)
            df = tk.history(period="2y")[["Close"]].copy()
            if df.empty:
                return []
            df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
            df.index = df.index.normalize()
            today_price = round(float(df.iloc[-1]["Close"]), 2)
            rows = []
            for t in entry_data["trades"]:
                try:
                    pub_ts = pd.Timestamp(t["pub_date"]).normalize()
                    pos    = df.index.searchsorted(pub_ts)
                    if pos >= len(df):
                        continue
                    entry = round(float(df.iloc[pos]["Close"]), 2)
                    ret   = round((today_price - entry) / entry * 100, 2) if entry else None
                    held_days = (today - pub_ts).days
                    rows.append({
                        "symbol":      sym,
                        "name":        entry_data["name"],
                        "fi_company":  t["fi_company"],
                        "pub_date":    t["pub_date"],
                        "insider":     t["insider"],
                        "role":        t["role"],
                        "volume":      t["volume"],
                        "fi_price":    t["price"],
                        "entry_price": entry,
                        "today_price": today_price,
                        "return_pct":  ret,
                        "held_days":   held_days,
                    })
                except Exception:
                    continue
            return rows
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(price_rows, sym, edata): sym for sym, edata in matched.items()}
        for fut in as_completed(futures):
            results.extend(fut.result())

    results.sort(key=lambda x: (x["return_pct"] is None, -(x["return_pct"] or 0)))

    rets = [r["return_pct"] for r in results if r["return_pct"] is not None]
    wins = [v for v in rets if v > 0]
    stats = {
        "total":      len(results),
        "companies":  len(matched),
        "win_rate":   round(len(wins) / len(rets) * 100, 1) if rets else None,
        "avg":        round(sum(rets) / len(rets), 2) if rets else None,
        "best":       round(max(rets), 2) if rets else None,
        "worst":      round(min(rets), 2) if rets else None,
        "unmatched":  len(unmatched),
        "fi_error":   fetch_err,
    }

    return jsonify({"trades": results, "stats": stats, "months": months})


@app.route("/api/watchlist", methods=["GET", "POST"])
def watchlist_route():
    if request.method == "POST":
        save_json("watchlist.json", request.json)
        return jsonify({"ok": True})
    return jsonify(load_json("watchlist.json", []))


@app.route("/api/portfolio", methods=["GET", "POST"])
def portfolio_route():
    if request.method == "POST":
        save_json("portfolio.json", request.json)
        return jsonify({"ok": True})
    return jsonify(load_json("portfolio.json", []))


@app.route("/api/portfolio/value")
def portfolio_value():
    holdings = load_json("portfolio.json", [])

    def fetch_holding(h):
        sym = h["symbol"]
        tk  = yf.Ticker(sym)

        # 1. Hämta live-pris
        price = h["buy_price"]
        if sym in _COINGECKO_IDS:
            try:
                p = fetch_crypto_price(sym)
                if p:
                    price = round(p, 2)
            except Exception:
                pass
        else:
            try:
                price = round(float(tk.fast_info["last_price"]), 2)
            except Exception:
                pass

        # 2. Hämta historik för teknisk analys
        rek, rek_klass = "–", ""
        try:
            df = get_ohlcv_df(sym, "1y")
            if not df.empty:
                # Använd stängningskurs om fast_info saknas
                if price == h["buy_price"]:
                    price = round(float(df["Close"].iloc[-1]), 2)
                df["MA50"]  = df.Close.rolling(50).mean()
                df["MA200"] = df.Close.rolling(200).mean()
                df["RSI"]   = calc_rsi(df.Close)
                df["MACD"], df["MACD_sig"], df["MACD_hist"] = calc_macd(df.Close)
                df["ATR"]   = calc_atr(df)
                df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
                df.dropna(inplace=True)
                sig = gen_signal(df)
                rek, rek_klass = sig["rek"], sig["rek_klass"]
        except Exception:
            pass

        inv    = h["shares"] * h["buy_price"]
        cur    = h["shares"] * price
        pl     = cur - inv
        pl_pct = pl / inv * 100 if inv else 0

        return {**h,
            "current_price": round(price, 2),
            "current_value": round(cur, 2),
            "invested":      round(inv, 2),
            "pl":            round(pl, 2),
            "pl_pct":        round(pl_pct, 2),
            "rek":           rek,
            "rek_klass":     rek_klass,
        }

    result = []
    with ThreadPoolExecutor(max_workers=min(len(holdings), 8)) as ex:
        futures = {ex.submit(fetch_holding, h): h for h in holdings}
        # Bevara ordningen från portföljlistan
        order = {h["symbol"]: i for i, h in enumerate(holdings)}
        for fut in as_completed(futures):
            try:
                result.append(fut.result())
            except Exception:
                pass
    result.sort(key=lambda x: order.get(x["symbol"], 999))

    tot_pl = tot_cur - tot_inv
    return jsonify({
        "holdings": result,
        "summary": {
            "total_invested": round(tot_inv, 2),
            "total_current":  round(tot_cur, 2),
            "total_pl":       round(tot_pl, 2),
            "total_pl_pct":   round(tot_pl / tot_inv * 100 if tot_inv else 0, 2),
        },
    })


# ── Portföljanalys ────────────────────────────────────────────────────────────

def _build_reasons(tech_score, insider_signal, buy_count, news_signal, trends_signal,
                   short_signal, pl_pct):
    """Bygger en lista med 3–5 svenska förklaringspunkter för rekommendationen."""
    reasons = []

    # Teknisk analys
    if tech_score >= 80:
        reasons.append("Starka tekniska signaler – MA, RSI och MACD pekar uppåt.")
    elif tech_score >= 55:
        reasons.append("Blandade tekniska signaler – viss positiv trend men ej bekräftad.")
    else:
        reasons.append("Svaga tekniska signaler – majoriteten av indikatorerna är negativa.")

    # Insiderhandel
    if insider_signal == "bullish" and buy_count >= 2:
        reasons.append(f"Insiders köper aktivt – {buy_count} köp senaste 90 dagarna.")
    elif insider_signal == "bullish":
        reasons.append("Insiderköp registrerade hos FI senaste 90 dagarna.")
    elif insider_signal == "bearish":
        reasons.append("Insiders säljer – netto-utflöde senaste 90 dagarna.")
    else:
        reasons.append("Ingen tydlig insidersignal senaste 90 dagarna.")

    # Nyhetssentiment
    if news_signal == "positiv":
        reasons.append("Positiv nyhetssentiment – senaste nyheterna är övervägande optimistiska.")
    elif news_signal == "negativ":
        reasons.append("Negativ nyhetssentiment – senaste nyheterna är övervägande pessimistiska.")

    # Google Trends
    if trends_signal == "stigande":
        reasons.append("Ökat sökintresse i Google – ökad marknadsmässig uppmärksamhet.")
    elif trends_signal == "fallande":
        reasons.append("Minskande sökintresse i Google – lägre uppmärksamhet från marknaden.")

    # Blankning
    if short_signal == "hög":
        reasons.append("Hög blankningsandel – marknaden satsar mot aktien, ökad risk.")
    elif short_signal == "medel":
        reasons.append("Måttlig blankningsandel – viss negativ exponering på marknaden.")

    # P/L-kontext
    if pl_pct is not None:
        if pl_pct >= 20:
            reasons.append(f"Du har {pl_pct:+.1f}% vinst – överväg att ta hem en del vinst.")
        elif pl_pct <= -15:
            reasons.append(f"Du har {pl_pct:+.1f}% förlust – utvärdera om caset fortfarande håller.")

    return reasons[:5]


def score_portfolio_holding(symbol, name, buy_price, current_price):
    """Beräknar ett komposit-score 0–100 och ger rekommendation för ett innehav."""
    pl_pct = round((current_price - buy_price) / buy_price * 100, 2) if buy_price else 0

    # 1. Teknisk analys (35 %)
    tech_score = 0
    tech_label = "okänd"
    try:
        tk = yf.Ticker(symbol)
        df = tk.history(period="1y")[["Open", "High", "Low", "Close", "Volume"]].copy()
        df["MA50"]  = df.Close.rolling(50).mean()
        df["MA200"] = df.Close.rolling(200).mean()
        df["RSI"]   = calc_rsi(df.Close)
        df["MACD"], df["MACD_sig"], df["MACD_hist"] = calc_macd(df.Close)
        df["ATR"]   = calc_atr(df)
        df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
        df.dropna(inplace=True)
        if len(df) >= 5:
            sig   = gen_signal(df)
            swing = calc_swing_score(df, sig)
            pos   = sig["positiva"]       # 0–3
            sw    = swing["score"]        # 0–10
            # MA + RSI + MACD ger 0–3 → mappar till 0–50; swing ger 0–10 → 0–50
            tech_score = round(pos / 3 * 50 + sw / 10 * 50)
            tech_label = sig["rek"]
    except Exception:
        pass

    # 2. Insiderhandel (25 %)
    insider_score  = 50   # neutral om ingen data
    insider_signal = "neutral"
    buy_count      = 0
    try:
        ins = fetch_insider_trades(name, days=90)
        sm  = ins.get("summary") or {}
        insider_signal = sm.get("signal", "neutral")
        buy_count      = sm.get("buy_count", 0)
        sell_count     = sm.get("sell_count", 0)
        net_value      = sm.get("net_value", 0)
        
        if insider_signal == "bullish":
            # Poäng baseras på värde: 50k (60p), 500k (75p), 5M (90p)
            if net_value > 5_000_000:   insider_score = 95
            elif net_value > 1_000_000: insider_score = 85
            elif net_value > 500_000:   insider_score = 75
            elif net_value > 100_000:   insider_score = 65
            else:                       insider_score = 60
        elif insider_signal == "bearish":
            if net_value < -5_000_000:  insider_score = 5
            elif net_value < -1_000_000:insider_score = 15
            elif net_value < -500_000:  insider_score = 25
            else:                       insider_score = 35
        else:
            insider_score = 50
    except Exception:
        pass

    # 3. Nyhetssentiment (20 %)
    news_score  = 50
    news_signal = "neutral"
    try:
        nd = fetch_news_sentiment(symbol)
        news_signal = nd.get("signal", "neutral")
        avg = nd.get("avg_sentiment")
        if avg is not None:
            # avg är -1 till +1 → mappar till 0–100
            news_score = round((avg + 1) / 2 * 100)
    except Exception:
        pass

    # 4. Blankning (10 %)
    short_score  = 60   # neutral/okänd = lite positivt
    short_signal = "okänd"
    try:
        sd = fetch_short_interest(symbol, name)
        short_signal = sd.get("signal", "okänd")
        if short_signal == "låg":
            short_score = 80
        elif short_signal == "medel":
            short_score = 45
        elif short_signal == "hög":
            short_score = 15
        else:
            short_score = 60
    except Exception:
        pass

    # 5. Google Trends (10 %)
    trends_score  = 50
    trends_signal = "stabilt"
    try:
        td = fetch_google_trends(name, symbol)
        trends_signal = td.get("signal", "stabilt")
        if trends_signal == "stigande":
            trends_score = 75
        elif trends_signal == "fallande":
            trends_score = 30
        else:
            trends_score = 50
    except Exception:
        pass

    # Komposit
    composite = round(
        tech_score    * 0.35 +
        insider_score * 0.25 +
        news_score    * 0.20 +
        short_score   * 0.10 +
        trends_score  * 0.10
    )

    if composite >= 70:
        rek, rek_css = "ÖKA", "oka"
    elif composite >= 50:
        rek, rek_css = "BEHÅLL", "behall"
    elif composite >= 35:
        rek, rek_css = "VAKTA", "vakta"
    else:
        rek, rek_css = "SÄLJ", "salj"

    reasons = _build_reasons(tech_score, insider_signal, buy_count, news_signal,
                             trends_signal, short_signal, pl_pct)

    return {
        "symbol":        symbol,
        "name":          name,
        "pl_pct":        pl_pct,
        "score":         composite,
        "rek":           rek,
        "rek_css":       rek_css,
        "tech_label":    tech_label,
        "tech_score":    tech_score,
        "insider_score": insider_score,
        "news_score":    news_score,
        "short_score":   short_score,
        "trends_score":  trends_score,
        "reasons":       reasons,
    }


@app.route("/api/portfolio/analyze", methods=["POST"])
def portfolio_analyze_route():
    """Analyserar alla innehav i portföljen och returnerar rekommendationer."""
    body     = request.json or {}
    holdings = body.get("holdings", [])
    if not holdings:
        return jsonify({"error": "inga innehav"}), 400

    results = []
    with ThreadPoolExecutor(max_workers=min(len(holdings), 5)) as ex:
        futures = {
            ex.submit(
                score_portfolio_holding,
                h["symbol"], h.get("name", h["symbol"]),
                float(h["buy_price"]), float(h["current_price"])
            ): h["symbol"]
            for h in holdings
            if h.get("symbol") and h.get("buy_price") and h.get("current_price")
        }
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception:
                pass

    results.sort(key=lambda x: x["score"])
    return jsonify({"analysis": results})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
