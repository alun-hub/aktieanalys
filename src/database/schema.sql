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

-- Målallokering per tillgångsklass, en rad per beräkningstillfälle (historik för uppföljning).
CREATE TABLE IF NOT EXISTS allocation_targets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at         TEXT NOT NULL,
    regime              TEXT NOT NULL,            -- 'bull' | 'correction' | 'bear'
    concentration_flag  TEXT NOT NULL,            -- 'normal' | 'elevated' | 'high'
    pct_broad_etf       REAL NOT NULL,
    pct_equalweight_etf REAL NOT NULL,
    pct_dividend_stocks REAL NOT NULL,
    pct_growth_stocks   REAL NOT NULL,
    pct_defensive       REAL NOT NULL,            -- räntor/guld
    note                TEXT
);

-- Sälj/trim-flaggor genererade av regimskiftet eller stop-loss, kvitteras manuellt av användaren.
CREATE TABLE IF NOT EXISTS sell_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    reason          TEXT NOT NULL,                -- t.ex. 'regime_bear', 'atr_stop', 'trend_break'
    severity        TEXT NOT NULL,                -- 'trim' | 'exit'
    acknowledged    INTEGER DEFAULT 0,            -- 0/1, sätts av användaren i UI
    acknowledged_at TEXT
);
