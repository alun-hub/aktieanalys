import yfinance as yf
import pandas as pd
import sqlite3
import os
import fcntl
from datetime import datetime
from src.core.config import OMXS_50, NASDAQ_100, INDEX_TICKERS
from src.core.indicators import calculate_indicators
from src.core.settings import DB_PATH, DATA_DIR, HISTORY_PERIOD

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "schema.sql")
_LOCK_PATH = os.path.join(DATA_DIR, ".sync.lock")

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
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def _archive_legacy_holdings(conn):
    """Den borttagna handelssimulatorn hade en 'holdings'-tabell med andra
    kolumner (entry_price/stop_loss/...) än dagens portfölj-hälsokoll
    (avg_price/kind/...). 'CREATE TABLE IF NOT EXISTS' skulle annars tyst
    lämna den gamla tabellen orörd och krascha portfölj-funktionerna.
    Arkivera den gamla tabellen under nytt namn i stället för att skriva
    över eller tappa datan."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(holdings)")}
    if cols and "avg_price" not in cols:
        conn.execute("ALTER TABLE holdings RENAME TO holdings_legacy_tradesim")
        conn.commit()
        print("OBS: äldre 'holdings'-tabell (handelssimulator) hittades och "
              "arkiverades som 'holdings_legacy_tradesim' – ej borttagen.")


def init_db():
    """Skapar alla tabeller från schema.sql (history + portfölj-tabeller)."""
    conn = get_db()
    _archive_legacy_holdings(conn)
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

def update_stock_data(symbol):
    """Hämtar och sparar full historik för en enskild aktie (utdelningsjusterad)."""
    df = yf.download(symbol, period=HISTORY_PERIOD, interval="1d",
                     progress=False, auto_adjust=True)
    if df.empty:
        return
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = calculate_indicators(df)
    conn = get_db()
    rows = [
        (symbol, date.strftime('%Y-%m-%d'),
         float(row['Open']), float(row['High']), float(row['Low']), float(row['Close']),
         int(row['Volume']) if not pd.isna(row['Volume']) else 0,
         float(row['MA50']) if not pd.isna(row['MA50']) else None,
         float(row['MA200']) if not pd.isna(row['MA200']) else None,
         float(row['RSI']) if not pd.isna(row['RSI']) else None,
         float(row['ATR']) if not pd.isna(row['ATR']) else None)
        for date, row in df.iterrows()
        if not pd.isna(row['Close'])
    ]
    conn.executemany("""INSERT OR REPLACE INTO history
        (symbol, date, open, high, low, close, volume, ma50, ma200, rsi, atr)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    conn.close()

def sync_all_stocks():
    """Total synkronisering av marknaden med realtidsstatus.

    Skyddad av ett fillås så att flera processer (gunicorn-workers) inte kan
    köra synken samtidigt.
    """
    global _sync_status
    if _sync_status["running"]:
        return

    lock_file = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Synk pågår redan i en annan process – hoppar över.")
        lock_file.close()
        return

    try:
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
    finally:
        _sync_status["running"] = False
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
