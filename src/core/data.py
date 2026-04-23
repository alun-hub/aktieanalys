import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from src.core.indicators import calc_rsi, calc_atr
from src.core.config import OMXS_50, NASDAQ_100

DB_PATH = "/app/data/trading.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    with open("src/database/schema.sql", "r") as f:
        conn.executescript(f.read())
    
    # MIGRATION: Lägg till saknade kolumner
    try:
        conn.execute("ALTER TABLE portfolio ADD COLUMN comm_type TEXT DEFAULT 'fixed'")
        conn.execute("ALTER TABLE portfolio ADD COLUMN comm_val REAL DEFAULT 0")
        conn.execute("ALTER TABLE history ADD COLUMN ma50 REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass

def update_stock_data(symbol, days=365*5):
    """Hämtar och sparar historisk data för en symbol."""
    try:
        df = yf.Ticker(symbol).history(period=f"{days}d")
        if df.empty: return False
        df.index = df.index.tz_localize(None).normalize()
        # Beräkna indikatorer innan vi sparar
        df["MA50"] = df.Close.rolling(50).mean()
        df["MA200"] = df.Close.rolling(200).mean()
        df["RSI"] = calc_rsi(df.Close)
        df["ATR"] = calc_atr(df)

        conn = get_db()
        for date, row in df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO history (symbol, date, open, high, low, close, volume, ma50, ma200, rsi, atr)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, date.strftime("%Y-%m-%d"), row.Open, row.High, row.Low, row.Close, row.Volume, 
                  row.MA50 if not pd.isna(row.MA50) else None,
                  row.MA200 if not pd.isna(row.MA200) else None, 
                  row.RSI if not pd.isna(row.RSI) else None, 
                  row.ATR if not pd.isna(row.ATR) else None))

        conn.commit()
        return True
    except Exception as e:
        print(f"Fel vid uppdatering av {symbol}: {e}")
        return False

def sync_all_stocks():
    all_symbols = list(OMXS_50.keys()) + list(NASDAQ_100.keys()) + ["^OMX", "^NDX"]
    print(f"Börjar synka {len(all_symbols)} instrument...")
    count = 0
    for sym in all_symbols:
        if update_stock_data(sym):
            count += 1
            print(f"Synkad: {sym} ({count}/{len(all_symbols)})")
    print(f"SYNCHRONIZATION COMPLETE. Totalt {count} instrument.")
    return count

def get_local_history(symbol, limit=300):
    conn = get_db()
    query = f"SELECT * FROM history WHERE symbol = ? ORDER BY date DESC LIMIT {limit}"
    df = pd.read_sql_query(query, conn, params=(symbol,))
    return df.sort_values("date")
