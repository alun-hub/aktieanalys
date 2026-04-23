import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/app/data/trading.db"
conn = sqlite3.connect(DB_PATH)

# Lägg till kolumnen om den saknas
try: conn.execute("ALTER TABLE history ADD COLUMN ma50 REAL")
except: pass

symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM history").fetchall()]
for s in symbols:
    print(f"Fixar {s}...")
    df = pd.read_sql_query("SELECT date, close FROM history WHERE symbol = ? ORDER BY date", conn, params=(s,))
    df["ma50"] = df.close.rolling(50).mean()
    for _, row in df.iterrows():
        if not pd.isna(row.ma50):
            conn.execute("UPDATE history SET ma50 = ? WHERE symbol = ? AND date = ?", (row.ma50, s, row.date))
conn.commit()
print("Databas fixad!")
