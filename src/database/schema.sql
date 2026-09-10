-- Daglig, utdelningsjusterad kurshistorik för alla bevakade instrument.
CREATE TABLE IF NOT EXISTS history (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,
    open   REAL,
    high   REAL,
    low    REAL,
    close  REAL,
    volume INTEGER,
    ma50   REAL,
    ma200  REAL,
    rsi    REAL,
    atr    REAL,
    PRIMARY KEY (symbol, date)
);

-- Innehav som användaren äger (t.ex. hos Avanza) – underlag för portfölj-hälsokollen.
-- Detta är INTE ett simulerat handelskonto; ingen köp/sälj-logik rör den här tabellen.
CREATE TABLE IF NOT EXISTS holdings (
    symbol     TEXT PRIMARY KEY,
    name       TEXT,
    qty        REAL NOT NULL,
    avg_price  REAL NOT NULL,          -- genomsnittligt anskaffningsvärde (GAV) i noteringsvaluta
    kind       TEXT DEFAULT 'aktie',   -- 'aktie' | 'fond'
    fee_pct    REAL DEFAULT 0,         -- årlig förvaltningsavgift i procent (för fonder)
    added_date TEXT,
    note       TEXT
);
