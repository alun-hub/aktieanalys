import sqlite3
from src.core.data import get_db

def get_portfolio_summary():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    p = conn.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
    holdings = conn.execute("SELECT * FROM holdings").fetchall()
    
    total_holdings_value = 0
    for h in holdings:
        last = conn.execute("SELECT close FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 1", (h['symbol'],)).fetchone()
        price = last['close'] if last and last['close'] is not None else h['entry_price']
        total_holdings_value += (price * h['qty'])
        
    return {
        "cash": p['cash'],
        "initial": p['initial_capital'],
        "holdings_value": total_holdings_value,
        "total_value": p['cash'] + total_holdings_value,
        "comm_val": p['comm_val'],
        "comm_type": p['comm_type']
    }

def update_holdings_days():
    """Räknar upp antalet dagar varje innehav har ägts (anropas vid midnatt)."""
    conn = get_db()
    conn.execute("UPDATE holdings SET days_held = days_held + 1")
    conn.commit()

def execute_buy(symbol, price, qty):
    conn = get_db()
    p = conn.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
    cost = price * qty
    comm = p['comm_val'] if p['comm_type'] == 'fixed' else (cost * (p['comm_val']/100))
    total_cost = cost + comm
    
    if p['cash'] < total_cost:
        return False, f"Otillräckligt saldo."
        
    conn.execute("UPDATE portfolio SET cash = cash - ? WHERE id = 1", (total_cost,))
    conn.execute("INSERT INTO holdings (symbol, qty, entry_price, stop_loss, days_held) VALUES (?, ?, ?, ?, 0)", 
                 (symbol, qty, price, price * 0.90))
    conn.commit()
    return True, f"Köpt {qty} st {symbol}"

def execute_sell(symbol, price, reason):
    conn = get_db()
    h = conn.execute("SELECT * FROM holdings WHERE symbol = ?", (symbol,)).fetchone()
    if not h: return False, "Innehav hittades inte."
    
    p = conn.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
    val = price * h['qty']
    comm = p['comm_val'] if p['comm_type'] == 'fixed' else (val * (p['comm_val']/100))
    net_val = val - comm
    
    conn.execute("UPDATE portfolio SET cash = cash + ? WHERE id = 1", (net_val,))
    conn.execute("DELETE FROM holdings WHERE symbol = ?", (symbol,))
    conn.execute("INSERT INTO trades (symbol, entry_price, exit_price, qty, reason) VALUES (?, ?, ?, ?, ?)",
                 (symbol, h['entry_price'], price, h['qty'], reason))
    conn.commit()
    return True, f"Sålt {symbol}"

def update_portfolio_budget(cash, initial, comm_type='fixed', comm_val=0):
    conn = get_db()
    conn.execute("UPDATE portfolio SET cash = ?, initial_capital = ?, comm_type = ?, comm_val = ? WHERE id = 1", 
                 (cash, initial, comm_type, comm_val))
    conn.commit()
