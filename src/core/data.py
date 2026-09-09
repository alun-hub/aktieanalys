import yfinance as yf
import pandas as pd
import sqlite3
import os
from datetime import datetime
from src.core.config import OMXS_50, NASDAQ_100, INDEX_TICKERS
from src.core.indicators import calculate_indicators

_sync_status = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current": "",
    "last_synced": None,
    "error": None
}

def get_sync_status():
    return _sync_status

def get_db():
    conn = sqlite3.connect('/app/data/trading.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS history (
        symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER,
        ma50 REAL, ma200 REAL, rsi REAL, atr REAL, PRIMARY KEY (symbol, date))""")
    conn.commit()

def update_stock_data(symbol):
    """Hämtar och sparar data för en enskild aktie."""
    df = yf.download(symbol, period="2y", interval="1d", progress=False)
    if df.empty: return
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = calculate_indicators(df)
    conn = get_db()
    for date, row in df.iterrows():
        conn.execute("""INSERT OR REPLACE INTO history 
            (symbol, date, open, high, low, close, volume, ma50, ma200, rsi, atr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, date.strftime('%Y-%m-%d'), float(row['Open']), float(row['High']), 
             float(row['Low']), float(row['Close']), int(row['Volume']),
             float(row['MA50']) if not pd.isna(row['MA50']) else None,
             float(row['MA200']) if not pd.isna(row['MA200']) else None,
             float(row['RSI']) if not pd.isna(row['RSI']) else None,
             float(row['ATR']) if not pd.isna(row['ATR']) else None))
    conn.commit()

def sync_all_stocks():
    """Total synkronisering av marknaden med realtidsstatus."""
    global _sync_status
    if _sync_status["running"]:
        return

    all_tickers = {**OMXS_50, **NASDAQ_100, **INDEX_TICKERS}
    total = len(all_tickers)
    _sync_status = {
        "running": True,
        "progress": 0,
        "total": total,
        "current": "Startar…",
        "last_synced": _sync_status.get("last_synced"),
        "error": None
    }

    count = 0
    for symbol in all_tickers.keys():
        try:
            _sync_status["current"] = symbol
            update_stock_data(symbol)
            count += 1
            _sync_status["progress"] = count
        except Exception as e:
            print(f"Fel vid synk av {symbol}: {e}")

    _sync_status["running"] = False
    _sync_status["current"] = "Klar"
    _sync_status["last_synced"] = datetime.now().strftime("%Y-%m-%d %H:%M")
