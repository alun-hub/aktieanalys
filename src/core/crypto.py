import time
import pandas as pd
import yfinance as yf
from src.core.indicators import calc_rsi, calc_atr
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
    "SUI-USD":   "Sui"
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

        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        df["RSI"] = calc_rsi(df["Close"])
        df["ATR"] = calc_atr(df)
        return df
    except Exception as e:
        print(f"Fel vid hämtning av krypto {symbol}: {e}")
        return None

def analyze_crypto_symbol(symbol):
    """Utför full analys på ett kryptopar och sätter betyg och nivåer."""
    df = get_crypto_df(symbol, period="1y")
    if df is None or df.empty:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = round(float(last["Close"]), 2)
    rsi = round(float(last["RSI"]), 1) if not pd.isna(last["RSI"]) else None
    rsi_prev = round(float(prev["RSI"]), 1) if not pd.isna(prev["RSI"]) else None
    ma50 = round(float(last["MA50"]), 2) if not pd.isna(last["MA50"]) else None
    ma200 = round(float(last["MA200"]), 2) if not pd.isna(last["MA200"]) else None
    atr = float(last["ATR"]) if not pd.isna(last["ATR"]) else close * 0.05

    # Mönsteridentifiering på senaste 30 dagarna
    patterns = detect_patterns(df.tail(30))

    # Signal & Poäng
    score = 50
    reasons = []

    # Trendbedömning
    if ma50 and close > ma50:
        score += 15
        reasons.append("Över MA50 (kortsiktig trend upp)")
    elif ma50 and close < ma50:
        score -= 15
        reasons.append("Under MA50 (kortsiktig svaghet)")

    if ma200 and close > ma200:
        score += 15
        reasons.append("Över MA200 (långsiktig bull-marknad)")
    elif ma200 and close < ma200:
        score -= 15
        reasons.append("Under MA200 (långsiktig bear-marknad)")

    # RSI Vändning / Momentum
    if rsi:
        if rsi < 35 and rsi_prev and rsi > rsi_prev:
            score += 20
            reasons.append(f"RSI vändning upp från översålt läge ({rsi})")
        elif rsi > 70:
            score -= 15
            reasons.append(f"RSI överköpt ({rsi}), risk för rekyl")
        elif 45 <= rsi <= 60:
            score += 5
            reasons.append(f"RSI i sunt momentum ({rsi})")

    # Mönsterbekräftelse
    if patterns:
        last_pattern = patterns[-1]
        if last_pattern["bullish"] is True:
            score += 15
            reasons.append(f"Mönster: {last_pattern['pattern']} (Bullish)")
        elif last_pattern["bullish"] is False:
            score -= 15
            reasons.append(f"Mönster: {last_pattern['pattern']} (Bearish)")

    # Gränser
    score = max(5, min(95, score))

    if score >= 75:
        signal = "STARK KÖP"
        signal_class = "prime"
    elif score >= 60:
        signal = "KÖP"
        signal_class = "bra"
    elif score <= 35:
        signal = "SÄLJ"
        signal_class = "undvik"
    else:
        signal = "NEUTRAL"
        signal_class = "vanta"

    # Riskhantering: Stop loss och Take profit
    sl = round(close - (2.5 * atr), 2)
    tp1 = round(close + (2.5 * atr * 1.5), 2) # 1.5x R:R
    tp2 = round(close + (2.5 * atr * 2.5), 2) # 2.5x R:R

    return {
        "symbol": symbol,
        "name": CRYPTO_LIST.get(symbol, symbol),
        "price": close,
        "change_24h": round(((close / float(prev["Close"])) - 1) * 100, 2),
        "rsi": rsi,
        "ma50": ma50,
        "ma200": ma200,
        "score": score,
        "signal": signal,
        "signal_class": signal_class,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons,
        "patterns": patterns
    }

def get_crypto_screener(force=False):
    """Hämtar och cachar screener för alla kryptovalutor."""
    global _crypto_cache
    now = time.time()
    if not force and _crypto_cache["screener"] and (now - _crypto_cache["ts"] < 600):
        return _crypto_cache["screener"]

    results = []
    for symbol in CRYPTO_LIST.keys():
        data = analyze_crypto_symbol(symbol)
        if data:
            results.append(data)

    results.sort(key=lambda x: x["score"], reverse=True)
    _crypto_cache = {"screener": results, "ts": now}
    return results
