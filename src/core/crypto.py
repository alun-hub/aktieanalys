import time
import pandas as pd
import yfinance as yf
from src.core.indicators import calc_rsi, calc_atr, calculate_indicators
from src.core.patterns import detect_patterns

CRYPTO_LIST = {
    "BTC-USD":   "Bitcoin",
    "ETH-USD":   "Ethereum",
    "SOL-USD":   "Solana",
    "XRP-USD":   "XRP",
    "BNB-USD":   "BNB",
    "ADA-USD":   "Cardano",
    "DOGE-USD":  "Dogecoin",
    "AVAX-USD":  "Avalanche",
    "LINK-USD":  "Chainlink",
    "DOT-USD":   "Polkadot",
    "NEAR-USD":  "NEAR Protocol",
    "SUI20947-USD": "Sui"
}

_crypto_cache = {"screener": None, "ts": 0.0}

def get_crypto_df(symbol, period="1y"):
    """Hämtar OHLCV för ett kryptopar."""
    try:
        df = yf.download(symbol, period=period, interval="1d", progress=False)
        if df.empty or len(df) < 30:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
        df.index = df.index.normalize()

        df = calculate_indicators(df)
        return df
    except Exception as e:
        print(f"Fel vid hämtning av krypto {symbol}: {e}")
        return None

def analyze_crypto_symbol(symbol):
    """Teknisk trend + volatilitet för ett kryptopar. Ingen köp-/säljsignal."""
    from src.core.signals import trend_score, trend_label

    df = get_crypto_df(symbol, period="1y")
    if df is None or df.empty:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = round(float(last["Close"]), 2)
    rsi = round(float(last["RSI"]), 1) if not pd.isna(last["RSI"]) else None
    ma50 = round(float(last["MA50"]), 2) if not pd.isna(last["MA50"]) else None
    ma200 = round(float(last["MA200"]), 2) if not pd.isna(last["MA200"]) else None
    ema20 = round(float(last["EMA20"]), 2) if ("EMA20" in last and not pd.isna(last["EMA20"])) else None
    atr = float(last["ATR"]) if not pd.isna(last["ATR"]) else close * 0.05

    macd = round(float(last["MACD"]), 2) if ("MACD" in last and not pd.isna(last["MACD"])) else None
    macd_sig = round(float(last["MACD_Signal"]), 2) if ("MACD_Signal" in last and not pd.isna(last["MACD_Signal"])) else None
    macd_hist = round(float(last["MACD_Hist"]), 2) if ("MACD_Hist" in last and not pd.isna(last["MACD_Hist"])) else None

    bb_squeeze = False
    if "BB_Bandwidth" in df.columns and len(df) >= 40:
        tail_bw = df["BB_Bandwidth"].dropna().tail(126)
        if len(tail_bw) >= 20 and not pd.isna(last["BB_Bandwidth"]):
            bb_squeeze = bool(last["BB_Bandwidth"] <= tail_bw.quantile(0.20))

    ma200_slope = None
    if len(df) >= 20 and not pd.isna(df["MA200"].iloc[-20]) and ma200 is not None:
        ma200_slope = ma200 - float(df["MA200"].iloc[-20])

    daily = df["Close"].pct_change().dropna().tail(90)
    vol_pct = round(float(daily.std() * (365 ** 0.5) * 100), 0) if len(daily) > 5 else None

    tscore = trend_score(close, ma50, ma200, rsi, ma200_slope=ma200_slope, ema20=ema20, macd_hist=macd_hist)
    tlabel, tclass = trend_label(tscore)

    reasons = []
    if ma200:
        slope_str = " (stigande)" if (ma200_slope and ma200_slope > 0) else (" (fallande)" if (ma200_slope and ma200_slope < 0) else "")
        reasons.append(f"{'Över' if close > ma200 else 'Under'} MA200{slope_str}")
    if ema20:
        reasons.append(f"{'Över' if close > ema20 else 'Under'} kortsiktigt stöd EMA20")
    if ma50:
        reasons.append(f"{'Över' if close > ma50 else 'Under'} MA50")
    if macd_hist is not None:
        reasons.append(f"MACD {'positivt' if macd_hist > 0 else 'negativt'} momentum")
    if bb_squeeze:
        reasons.append("Bollinger Squeeze (volatilitet komprimerad)")
    if rsi is not None:
        reasons.append(f"RSI {rsi:g}" + (" (överköpt)" if rsi > 75 else " (översålt)" if rsi < 30 else ""))
    if vol_pct:
        reasons.append(f"Årlig volatilitet ~{vol_pct:g} %")

    return {
        "symbol": symbol,
        "name": CRYPTO_LIST.get(symbol, symbol),
        "price": close,
        "change_24h": round((close / float(prev["Close"]) - 1) * 100, 2),
        "rsi": rsi, "ma50": ma50, "ma200": ma200, "ema20": ema20,
        "macd": {"macd": macd, "signal": macd_sig, "hist": macd_hist},
        "bollinger_squeeze": bb_squeeze,
        "trend_score": tscore, "trend": tlabel, "trend_class": tclass,
        "volatility_pct": vol_pct,
        "stop_suggestion": round(close - 2.5 * atr, 2),
        "reasons": reasons,
        "patterns": detect_patterns(df.tail(30)),
    }

def get_crypto_screener(force=False):
    """Hämtar och cachar trendöversikt för alla kryptovalutor."""
    global _crypto_cache
    now = time.time()
    if not force and _crypto_cache["screener"] and (now - _crypto_cache["ts"] < 600):
        return _crypto_cache["screener"]

    results = []
    for symbol in CRYPTO_LIST.keys():
        data = analyze_crypto_symbol(symbol)
        if data:
            results.append(data)

    results.sort(key=lambda x: x["trend_score"], reverse=True)
    _crypto_cache = {"screener": results, "ts": now}
    return results
