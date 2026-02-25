import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests as req
import yfinance as yf
from flask import Flask, jsonify, render_template, request

warnings.filterwarnings("ignore")

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))


# ── Indikatorer ───────────────────────────────────────────────────────────────

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = -d.clip(upper=0).rolling(n).mean()
    return 100 - 100 / (1 + g / l)


def calc_macd(s, fast=12, slow=26, sig=9):
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sl = m.ewm(span=sig, adjust=False).mean()
    return m, sl, m - sl


def calc_bb(close, n=20, num_std=2):
    ma  = close.rolling(n).mean()
    std = close.rolling(n).std()
    return ma + num_std * std, ma, ma - num_std * std


def calc_atr(df, n=14):
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(n).mean()


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


def calc_swing_score(df, sig, market_bull=True):
    score = 0
    details = {}

    # 1. Marknadsriktning (+2)
    if market_bull:
        score += 2; details["market"] = (2, "OMXS30 i upptrend")
    else:
        details["market"] = (0, "OMXS30 i nedtrend – handla varsamt")

    # 2. RSI i köpzon 32–52 (+2)
    rsi = sig["rsi"]
    if 32 <= rsi <= 52:
        score += 2; details["rsi"] = (2, f"RSI {rsi:.0f} – perfekt köpzon")
    elif rsi < 32:
        score += 1; details["rsi"] = (1, f"RSI {rsi:.0f} – extremt översåld, köp i etapper")
    else:
        details["rsi"] = (0, f"RSI {rsi:.0f} – utanför köpzon ({'>52' if rsi > 52 else '<32'})")

    # 3. Färsk MACD-korsning uppåt ≤5 dagar (+2)
    days = macd_days_since_cross(df)
    if days is not None and days <= 5:
        score += 2; details["macd"] = (2, f"Färsk MACD-korsning ({days}d sedan) – stark signal")
    elif sig["macd_bull"]:
        score += 1; details["macd"] = (1, f"MACD bullish men korsning {days or '?'}d sedan")
    else:
        details["macd"] = (0, "MACD bearish – momentum saknas")

    # 4. Kurs nära MA50 (±4%) eller nedre BB (±3%) (+2)
    kurs = float(df.Close.iloc[-1])
    ma50 = float(df.MA50.iloc[-1])
    bb_lower = float(df.BB_lower.iloc[-1])
    near_ma50 = abs(kurs - ma50) / ma50 < 0.04
    near_bb   = abs(kurs - bb_lower) / bb_lower < 0.03
    if near_ma50 or near_bb:
        where = "MA50" if near_ma50 else "nedre BB"
        score += 2; details["support"] = (2, f"Kurs vid {where}-stöd – bra ingång")
    else:
        pct = ((kurs - ma50) / ma50 * 100)
        details["support"] = (0, f"Kurs {pct:+.1f}% från MA50 – invänta dipp")

    # 5. Volym bekräftar (> 20-dagarssnitt) (+2)
    vol_now = float(df.Volume.iloc[-1])
    vol_avg = float(df.Volume.rolling(20).mean().iloc[-1])
    if vol_now > vol_avg:
        score += 2; details["volume"] = (2, f"Volym {vol_now/vol_avg:.1f}× snittet – köptryck bekräftat")
    else:
        details["volume"] = (0, f"Volym under snitt ({vol_now/vol_avg:.1f}×) – ingen bekräftelse")

    # Label
    if score >= 8:   label, css = "PRIME SETUP 🎯", "prime"
    elif score >= 6: label, css = "BRA SETUP", "good"
    elif score >= 4: label, css = "AVVAKTA", "wait"
    else:            label, css = "UNDVIK", "avoid"

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

# ── Stockholmsbörsen – OMXS30 + Large/Mid cap ────────────────────────────────
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

# Cache: {data: [...], ts: float}
_screener_cache: dict = {"data": None, "ts": 0.0}


def analyze_stock(symbol, period="3mo"):
    fetch = FETCH_PERIOD.get(period, "1y")
    days  = DISPLAY_DAYS.get(period, 95)

    tk = yf.Ticker(symbol)
    df = tk.history(period=fetch)[["Open", "High", "Low", "Close", "Volume"]].copy()
    if df.empty or len(df) < 55:
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
    swing = calc_swing_score(df, sig)

    golden = (df.MA50 > df.MA200) & (df.MA50.shift(1) <= df.MA200.shift(1))
    death  = (df.MA50 < df.MA200) & (df.MA50.shift(1) >= df.MA200.shift(1))

    cutoff  = df.index[-1] - pd.Timedelta(days=days)
    disp    = df[df.index >= cutoff].copy()
    patterns = detect_patterns(disp)

    try:
        info = tk.info
        name = info.get("longName") or info.get("shortName") or symbol
    except Exception:
        name = symbol

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
        tk  = yf.Ticker(symbol)
        df  = tk.history(period="1y")[["Open", "High", "Low", "Close", "Volume"]].copy()
        if df.empty or len(df) < 55:
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
        swing = calc_swing_score(df, sig)

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


def run_screener():
    """Kör screener parallellt för alla OMXS_50-aktier."""
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(screener_analyze, sym, name): sym
                   for sym, name in OMXS_50.items()}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    # Sortera: starkast signal först, sedan swing_score, sedan strength
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
    tk = yf.Ticker(symbol)
    df = tk.history(period=FETCH.get(period, "2y"))[["Open", "High", "Low", "Close", "Volume"]].copy()
    if df.empty or len(df) < 250:
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


# ── Persistens ────────────────────────────────────────────────────────────────

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
    force = request.args.get("force", "0") == "1"
    cached = _screener_cache["data"]
    age    = time.time() - _screener_cache["ts"]

    if cached and not force:
        return jsonify({"data": cached, "cached": True,
                        "age_min": round(age / 60, 1),
                        "ts": _screener_cache["ts"]})

    data = run_screener()
    _screener_cache["data"] = data
    _screener_cache["ts"]   = time.time()
    return jsonify({"data": data, "cached": False,
                    "age_min": 0, "ts": _screener_cache["ts"]})


@app.route("/api/backtest", methods=["POST"])
def backtest_route():
    data      = request.json or {}
    period    = data.get("period", "2y")
    min_score = int(data.get("min_score", 6))
    max_days  = int(data.get("max_days", 30))
    symbols   = data.get("symbols") or list(OMXS_50.keys())

    def run_one(sym):
        trades = run_backtest_symbol(sym, period, min_score, max_days)
        return {"symbol": sym, "name": OMXS_50.get(sym, sym),
                "trades": trades, "stats": compute_backtest_stats(trades)}

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(run_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda x: -(x["stats"]["total"] if x["stats"] else 0))
    all_trades = [t for r in results for t in r["trades"]]
    return jsonify({"results": results, "overall": compute_backtest_stats(all_trades)})


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
    result   = []
    tot_inv  = tot_cur = 0.0

    for h in holdings:
        sym = h["symbol"]
        try:
            price = float(yf.Ticker(sym).fast_info["last_price"])
        except Exception:
            price = h["buy_price"]

        inv    = h["shares"] * h["buy_price"]
        cur    = h["shares"] * price
        pl     = cur - inv
        pl_pct = pl / inv * 100 if inv else 0
        tot_inv += inv
        tot_cur += cur

        try:
            df = yf.Ticker(sym).history(period="1y")[["Open", "High", "Low", "Close", "Volume"]].copy()
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
            rek, rek_klass = "–", ""

        result.append({**h,
            "current_price": round(price, 2),
            "current_value": round(cur, 2),
            "invested":      round(inv, 2),
            "pl":            round(pl, 2),
            "pl_pct":        round(pl_pct, 2),
            "rek":           rek,
            "rek_klass":     rek_klass,
        })

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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
