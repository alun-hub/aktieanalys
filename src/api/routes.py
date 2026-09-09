from flask import Blueprint, jsonify, request
import threading
import json
import os
from src.core.signals import run_market_screener
from src.core.backtest import run_backtest_local, optimize_omx
from src.core.data import sync_all_stocks, get_sync_status
from src.core.analysis import search_symbols, analyze_any_stock, get_market_overview
from src.core.insider import fetch_all_insider_buys
from src.core.congress import scan_congress_trades
from src.core.crypto import get_crypto_screener

api_bp = Blueprint('api', __name__)

@api_bp.route('/thought')
def ai_thought():
    try:
        path = '/app/data/ai_thought.txt'
        if not os.path.exists(path):
            return jsonify({"thought": "Väntar på marknadsskanning…"})
        with open(path, 'r') as f:
            return jsonify({"thought": f.read()})
    except:
        return jsonify({"thought": "Kunde inte läsa AI-analys."})

@api_bp.route('/market_overview')
def market_overview_route():
    try:
        return jsonify(get_market_overview())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/screener')
def screener_route():
    market = request.args.get('market', 'all')
    try:
        results = run_market_screener(market=market)
        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 500

@api_bp.route('/orders')
def orders_fallback():
    """Bakåtkompatibilitet för skanningsknappar."""
    market = request.args.get('market', 'all')
    results = run_market_screener(market=market)
    buys = [r for r in results if "KÖP" in r["rek"]]
    sells = [r for r in results if "SÄLJ" in r["rek"]]
    return jsonify({"buy": buys, "sell": sells, "all": results})

@api_bp.route('/search')
def search_route():
    q = request.args.get('q', '')
    return jsonify(search_symbols(q))

@api_bp.route('/analyze')
def analyze_route():
    symbol = request.args.get('symbol', '')
    return jsonify(analyze_any_stock(symbol))

@api_bp.route('/insider')
def insider_route():
    days = int(request.args.get('days', 30))
    trades, err = fetch_all_insider_buys(days=days)
    return jsonify({"trades": trades, "error": err})

@api_bp.route('/congress')
def congress_route():
    months = int(request.args.get('months', 3))
    return jsonify(scan_congress_trades(months=months))

@api_bp.route('/crypto')
def crypto_route():
    return jsonify(get_crypto_screener())

@api_bp.route('/backtest', methods=['POST'])
def run_backtest():
    data = request.json or {}
    return jsonify(run_backtest_local(data.get('market', 'omxs'), int(data.get('years', 5))))

@api_bp.route('/optimize', methods=['POST'])
def run_optimize():
    data = request.json or {}
    years = int(data.get('years', 5))
    return jsonify(optimize_omx(years))

@api_bp.route('/update', methods=['POST'])
def update_data():
    threading.Thread(target=sync_all_stocks, daemon=True).start()
    return jsonify({"success": True, "message": "Synkronisering startad"})

@api_bp.route('/sync_status')
def sync_status_route():
    return jsonify(get_sync_status())
