import yfinance as yf
import pandas as pd
import sqlite3
import os
import json
import time
import fcntl
from datetime import datetime
from src.core.config import OMXS_50, NASDAQ_100, INDEX_TICKERS
from src.core.indicators import calculate_indicators
from src.core.settings import DB_PATH, DATA_DIR, HISTORY_PERIOD

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "schema.sql")
_LOCK_PATH = os.path.join(DATA_DIR, ".sync.lock")
_STATUS_PATH = os.path.join(DATA_DIR, "sync_status.json")

_DEFAULT_STATUS = {"running": False, "progress": 0, "total": 0,
                   "current": "", "last_synced": None, "error": None}


def _read_status():
    # Filbaserad status, inte en processlokal dict: appen kör flera
    # gunicorn-workers (separata processer) och en in-memory dict skulle visa
    # olika (och fel) status beroende på vilken worker som svarar på anropet.
    try:
        with open(_STATUS_PATH) as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_STATUS)


def _write_status(status):
    tmp = _STATUS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f)
    os.replace(tmp, _STATUS_PATH)


def get_sync_status():
    return _read_status()

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


_INIT_LOCK_PATH = os.path.join(DATA_DIR, ".init.lock")


def init_db():
    """Skapar alla tabeller från schema.sql (history + portfölj-tabeller).

    Körs vid varje processtart (app.py), inklusive en gång per gunicorn-worker.
    Låst (blockerande) så att flera processer som startar samtidigt inte kan
    krocka i migreringssteget (t.ex. döpa om samma legacy-tabell två gånger).
    """
    lock_file = open(_INIT_LOCK_PATH, "w")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    try:
        conn = get_db()
        _archive_legacy_holdings(conn)
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()

def update_stock_data(symbol):
    """Hämtar och sparar full historik för en enskild aktie (utdelningsjusterad)."""
    df = yf.download(symbol, period=HISTORY_PERIOD, interval="1d",
                     progress=False, auto_adjust=True)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Close" in df.columns:
        df = df.dropna(subset=["Close"]).copy()
    if df.empty:
        return None
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
    return df.index[-1].strftime('%Y-%m-%d')

def _last_business_day_before(day):
    """Senaste vardagen före `day` (söndag/lördag/måndag -> fredagen före)."""
    from datetime import timedelta
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def load_history_df(symbol, years=5, today=None):
    """Läser kurshistorik för `symbol` från databasen i yfinance-format, om den är färsk.

    Returnerar en DataFrame (DatetimeIndex, kolumnerna Open/High/Low/Close/Volume) för de
    senaste `years` åren, eller None om symbolen saknas, har för få rader eller sista
    kursen är äldre än föregående vardag (då får anroparen hämta live från Yahoo).
    Helgdagar gör att datan ibland räknas som gammal – det är medvetet konservativt.
    """
    from datetime import date as _date, timedelta
    today = today or _date.today()
    cutoff = (today - timedelta(days=int(365.25 * years))).strftime("%Y-%m-%d")
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM history "
            "WHERE symbol = ? AND date >= ? AND close IS NOT NULL ORDER BY date",
            (symbol, cutoff)).fetchall()
    finally:
        conn.close()
    if len(rows) < 30:
        return None
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df.index.name = "Date"
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    if df.index[-1].date() < _last_business_day_before(today):
        return None
    return df


def _log_sync_summary(status, total, expected, empty, failed, stale):
    """Loggar och sparar i statusen hur synken gick, så tysta luckor syns.

    `stale` = symboler vars senaste kurs är äldre än föregående vardag (helgdagar ger
    enstaka sådana, men många på en gång – t.ex. alla .ST – tyder på ett Yahoo-problem).
    """
    status["empty"], status["failed"], status["stale"] = empty, failed, stale
    ok = total - len(empty) - len(failed)
    print(f"Synk: {ok}/{total} ok, {len(empty)} tomma svar, {len(failed)} fel, "
          f"{len(stale)} med kurs äldre än {expected}.", flush=True)
    if len(empty) + len(failed) > max(3, total // 5):
        print(f"Synk VARNING: många symboler fick inget svar ({len(empty)} tomma, {len(failed)} fel) – "
              f"troligen ett Yahoo-problem. Exempel: {', '.join((empty + failed)[:8])}", flush=True)
    if stale:
        groups = {}
        for sym in stale:
            key = sym.rsplit(".", 1)[-1] if "." in sym else "övriga"
            groups[key] = groups.get(key, 0) + 1
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(groups.items()))
        level = "VARNING" if len(stale) > max(3, total // 5) else "Info"
        print(f"Synk {level}: inaktuella symboler per marknad – {detail}. "
              f"Exempel: {', '.join(stale[:8])}", flush=True)


def sync_all_stocks():
    """Total synkronisering av marknaden med realtidsstatus.

    Skyddad av ett fillås så att flera processer (gunicorn-workers) inte kan
    köra synken samtidigt. Statusen skrivs till en delad fil, inte en
    processlokal dict, så alla workers ser samma (korrekta) förlopp.
    """
    # Fillåset är den enda auktoritativa kontrollen: det släpps av OS när
    # processen dör, så en kraschad synk (running=True kvar i statusfilen)
    # blockerar inte framtida synkar.
    lock_file = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Synk pågår redan i en annan process – hoppar över.")
        lock_file.close()
        return

    try:
        all_tickers = {**OMXS_50, **NASDAQ_100, **INDEX_TICKERS}
        status = {
            "running": True, "progress": 0, "total": len(all_tickers),
            "current": "Startar…", "last_synced": _read_status().get("last_synced"),
            "error": None,
        }
        _write_status(status)

        count = 0
        empty, failed, stale = [], [], []
        expected = _last_business_day_before(datetime.now().date()).strftime("%Y-%m-%d")
        for symbol in all_tickers.keys():
            try:
                status["current"] = symbol
                last_date = update_stock_data(symbol)
                if last_date is None:
                    # Yahoo ibland tomt svar utan fel – försök en gång till innan vi ger upp
                    print(f"Synk: tomt svar för {symbol}, försöker igen…", flush=True)
                    time.sleep(2)
                    last_date = update_stock_data(symbol)
                if last_date is None:
                    empty.append(symbol)
                    print(f"Synk: tomt svar för {symbol} även efter nytt försök – kursdata ej uppdaterad.", flush=True)
                elif last_date < expected:
                    stale.append(symbol)
                count += 1
                status["progress"] = count
            except Exception as e:
                failed.append(symbol)
                print(f"Fel vid synk av {symbol}: {e}", flush=True)
            _write_status(status)

        _log_sync_summary(status, len(all_tickers), expected, empty, failed, stale)

        try:
            from src.core.dividends import get_top_dividend_stocks
            status["current"] = "Förladdar utdelningscachen…"
            _write_status(status)
            get_top_dividend_stocks(market="all", force_refresh=True)
            get_top_dividend_stocks(market="omx", force_refresh=True)
            get_top_dividend_stocks(market="nasdaq", force_refresh=True)
        except Exception as e:
            print(f"Kunde inte förladda utdelningscachen: {e}")

        try:
            from src.core.signals import clear_signals_cache, scan_opportunities, build_recommendations
            clear_signals_cache()
            status["current"] = "Förladdar möjligheter och rekommendationer…"
            _write_status(status)
            scan_opportunities(market="all", force_refresh=True)
            build_recommendations(market="all", force_refresh=True)
        except Exception as e:
            print(f"Kunde inte förladda signalkakorna: {e}")

        status["running"] = False
        status["current"] = "Klar"
        status["last_synced"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _write_status(status)
    finally:
        status = _read_status()
        status["running"] = False
        _write_status(status)
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
