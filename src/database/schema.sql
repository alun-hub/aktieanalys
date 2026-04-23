-- Historik för alla aktier
CREATE TABLE IF NOT EXISTS history (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    ma50 REAL,
    ma200 REAL,
    rsi REAL,
    atr REAL,
    PRIMARY KEY (symbol, date)
);

-- Portföljstatus
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash REAL NOT NULL DEFAULT 100000.0,
    initial_capital REAL NOT NULL DEFAULT 100000.0,
    comm_type TEXT DEFAULT 'fixed',
    comm_val REAL DEFAULT 0,
    last_updated TEXT
);

-- Nuvarande innehav
CREATE TABLE IF NOT EXISTS holdings (
    symbol TEXT PRIMARY KEY,
    entry_price REAL NOT NULL,
    entry_date TEXT NOT NULL,
    qty REAL NOT NULL,
    stop_loss REAL,
    days_held INTEGER DEFAULT 0,
    buy_fee REAL DEFAULT 0
);

-- Historik över alla stängda affärer
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    qty REAL NOT NULL,
    pl REAL NOT NULL,
    pl_pct REAL NOT NULL,
    reason TEXT
);

-- Initiera portfölj om den inte finns
INSERT OR IGNORE INTO portfolio (id, cash, initial_capital, last_updated) 
VALUES (1, 100000.0, 100000.0, datetime('now'));
