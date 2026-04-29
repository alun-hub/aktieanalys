from flask import Blueprint, jsonify, request
import threading
import json
import os
from src.core.portfolio import get_portfolio_summary
from src.core.signals import generate_daily_orders
from src.core.backtest import run_backtest_local, optimize_omx
from src.core.data import get_db, sync_all_stocks

api_bp = Blueprint('api', __name__)

@api_bp.route('/portfolio/update', methods=['POST'])
def update_portfolio():
    try:
        data = request.json
        from src.core.portfolio import update_portfolio_budget
        update_portfolio_budget(
            float(data.get('cash', 100000)), 
            float(data.get('initial', 100000)),
            data.get('comm_type', 'fixed'),
            float(data.get('comm_val', 0))
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@api_bp.route('/thought')
def ai_thought():
    try:
        path = '/app/data/ai_thought.txt'
        if not os.path.exists(path):
            return jsonify({"thought": "Väntar på skanning..."})
        with open(path, 'r') as f:
            return jsonify({"thought": f.read()})
    except:
        return jsonify({"thought": "Kunde inte läsa analys."})

@api_bp.route('/portfolio')
def portfolio():
    return jsonify(get_portfolio_summary())

@api_bp.route('/orders')
def orders():
    summary = get_portfolio_summary()
    total_val = summary['total_value']
    orders_data = generate_daily_orders()
    
    # Läs in AI-poäng om de finns
    ai_scores = {}
    try:
        if os.path.exists('/app/data/ai_briefing.json'):
            with open('/app/data/ai_briefing.json', 'r') as f:
                ai_data = json.load(f)
                ai_scores = ai_data.get('scores', {})
    except: pass

    target_pos_val = total_val * 0.20
    for o in orders_data['buy']:
        o['suggested_amount'] = target_pos_val
        o['suggested_qty'] = int(target_pos_val / o['price'])
        o['ai_score'] = ai_scores.get(o['symbol'], 0) # Hämta poäng för denna symbol

    return jsonify(orders_data)

@api_bp.route('/execute', methods=['POST'])
def execute():
    try:
        data = request.json
        action = data.get('action')
        symbol = data.get('symbol')
        price_val = data.get('price')
        
        if price_val is None:
            return jsonify({"success": False, "message": "Inget pris angivet"}), 400
        
        price = float(price_val)
        if price <= 0:
            return jsonify({"success": False, "message": "Priset måste vara över 0"}), 400
        
        from src.core.portfolio import execute_buy, execute_sell
        if action == 'buy':
            # Försök hitta stop loss från dagens förslag
            sl = None
            try:
                orders_data = generate_daily_orders()
                for o in orders_data['buy']:
                    if o['symbol'] == symbol:
                        sl = o.get('sl')
                        break
            except: pass

            summary = get_portfolio_summary()
            target_val = summary['total_value'] * 0.20
            qty = int(target_val / price)
            if qty <= 0: qty = 1
            success, msg = execute_buy(symbol, price, qty, sl)
        else:
            success, msg = execute_sell(symbol, price, "Manuell")
        
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        print(f"ERROR in execute: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@api_bp.route('/holdings/edit', methods=['POST'])
def edit_holding():
    try:
        data = request.json
        symbol = data.get('symbol')
        entry = float(data.get('entry'))
        sl = float(data.get('sl'))
        qty = float(data.get('qty', 0))
        conn = get_db()
        if qty > 0:
            conn.execute("UPDATE holdings SET entry_price = ?, stop_loss = ?, qty = ? WHERE symbol = ?", (entry, sl, qty, symbol))
        else:
            conn.execute("UPDATE holdings SET entry_price = ?, stop_loss = ? WHERE symbol = ?", (entry, sl, symbol))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@api_bp.route('/holdings')
def holdings():
    conn = get_db()
    rows = conn.execute("SELECT * FROM holdings").fetchall()
    res = []
    for r in rows:
        last = conn.execute("SELECT close FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 1", (r['symbol'],)).fetchone()
        cur_price = last['close'] if last and last['close'] is not None else r['entry_price']
        
        # Defensiv vinstberäkning
        if r['entry_price'] and r['entry_price'] > 0:
            pl_pct = (cur_price / r['entry_price'] - 1) * 100
        else:
            pl_pct = 0
            
        res.append({
            "symbol": r['symbol'], 
            "qty": r['qty'],
            "entry": r['entry_price'], 
            "sl": r['stop_loss'],
            "current": cur_price, 
            "market_value": round(r['qty'] * cur_price, 2),
            "pl_pct": round(pl_pct, 2), 
            "days": r['days_held']
        })
    return jsonify(res)

@api_bp.route('/backtest', methods=['POST'])
def run_backtest():
    data = request.json
    return jsonify(run_backtest_local(data.get('market', 'omxs'), int(data.get('years', 5))))

@api_bp.route('/update', methods=['POST'])
def update_data():
    threading.Thread(target=sync_all_stocks, daemon=True).start()
    return jsonify({"success": True})

@api_bp.route('/optimize', methods=['POST'])
def run_optimize():
    data = request.json or {}
    years = int(data.get('years', 5))
    return jsonify(optimize_omx(years))
