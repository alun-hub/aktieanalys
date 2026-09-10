from flask import Blueprint, jsonify, request
import threading

from src.core.signals import run_market_screener
from src.core.backtest import run_backtest_local, optimize_omx
from src.core.data import sync_all_stocks, get_sync_status
from src.core.analysis import search_symbols, analyze_any_stock, get_market_overview
from src.core.crypto import get_crypto_screener
from src.core.insider import fetch_all_insider_buys
from src.core.congress import scan_congress_trades
from src.core.projection import project
from src.core import portfolio as pf

api_bp = Blueprint('api', __name__)


def _err(fn):
    try:
        return jsonify(fn())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/market_overview')
def market_overview_route():
    return _err(get_market_overview)


@api_bp.route('/screener')
def screener_route():
    market = request.args.get('market', 'all')
    try:
        results = run_market_screener(market=market)
        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 500


@api_bp.route('/search')
def search_route():
    return jsonify(search_symbols(request.args.get('q', '')))


@api_bp.route('/analyze')
def analyze_route():
    return jsonify(analyze_any_stock(request.args.get('symbol', '')))


@api_bp.route('/crypto')
def crypto_route():
    return _err(get_crypto_screener)


@api_bp.route('/insider')
def insider_route():
    days = int(request.args.get('days', 30))
    action = request.args.get('action', 'all')
    trades, err = fetch_all_insider_buys(days=days, action=action)
    return jsonify({"trades": trades, "error": err})


@api_bp.route('/congress')
def congress_route():
    months = int(request.args.get('months', 3))
    action = request.args.get('action', 'all')
    return jsonify(scan_congress_trades(months=months, txn_type=action))


@api_bp.route('/backtest', methods=['POST'])
def run_backtest():
    data = request.json or {}
    return jsonify(run_backtest_local(data.get('market', 'omxs'), int(data.get('years', 10))))


@api_bp.route('/optimize', methods=['POST'])
def run_optimize():
    data = request.json or {}
    return jsonify(optimize_omx(int(data.get('years', 8))))


@api_bp.route('/projection', methods=['POST'])
def projection_route():
    d = request.json or {}
    return jsonify(project(
        start_amount=d.get('start_amount', 0),
        monthly=d.get('monthly', 2000),
        years=d.get('years', 20),
        fee_pct=d.get('fee_pct', 0.4),
    ))


@api_bp.route('/portfolio', methods=['GET'])
def portfolio_list_route():
    return jsonify({"holdings": pf.list_holdings()})


@api_bp.route('/portfolio', methods=['POST'])
def portfolio_add_route():
    d = request.json or {}
    try:
        pf.add_holding(
            symbol=d['symbol'], qty=d['qty'], avg_price=d['avg_price'],
            name=d.get('name'), kind=d.get('kind', 'aktie'),
            fee_pct=d.get('fee_pct', 0), note=d.get('note', ''))
        return jsonify({"ok": True})
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"Ogiltig indata: {e}"}), 400


@api_bp.route('/portfolio/<symbol>', methods=['DELETE'])
def portfolio_delete_route(symbol):
    pf.remove_holding(symbol)
    return jsonify({"ok": True})


@api_bp.route('/portfolio/health')
def portfolio_health_route():
    return _err(pf.portfolio_health)


@api_bp.route('/update', methods=['POST'])
def update_data():
    threading.Thread(target=sync_all_stocks, daemon=True).start()
    return jsonify({"success": True, "message": "Synkronisering startad"})


@api_bp.route('/sync_status')
def sync_status_route():
    return jsonify(get_sync_status())
