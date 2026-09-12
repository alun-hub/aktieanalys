from flask import Blueprint, jsonify, request
import threading

from src.core.signals import run_market_screener, scan_opportunities, build_recommendations
from src.core.backtest import run_backtest_local, optimize_omx, run_single_stock_backtest, run_portfolio_backtest
from src.core.data import sync_all_stocks, get_sync_status
from src.core.analysis import search_symbols, analyze_any_stock, get_market_overview, resolve_symbol
from src.core.crypto import get_crypto_screener
from src.core.insider import fetch_all_insider_buys
from src.core.congress import scan_congress_trades
from src.core.projection import project
from src.core import portfolio as pf
from src.core.dividends import get_top_dividend_stocks
from src.core.regime import get_market_regime

api_bp = Blueprint('api', __name__)


def _err(fn):
    try:
        return jsonify(fn())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/top-dividends')
@api_bp.route('/top_dividends')
def top_dividends_route():
    market = request.args.get('market', 'all')
    try:
        limit = int(request.args.get('limit', 10))
    except (ValueError, TypeError):
        limit = 10
    refresh = request.args.get('refresh', 'false').lower() in ('true', '1')
    try:
        data = get_top_dividend_stocks(market=market, limit=limit, force_refresh=refresh)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e), "stocks": [], "updated_at": ""}), 500


@api_bp.route('/opportunities')
def opportunities_route():
    market = request.args.get('market', 'all')
    strategy = request.args.get('strategy', 'all')
    refresh = request.args.get('refresh', '0') in ('1', 'true', 'True')
    opps = scan_opportunities(market=market, strategy_filter=strategy, force_refresh=refresh)
    regime = get_market_regime(market=market)
    return jsonify({"opportunities": opps, "total": len(opps), "regime": regime})


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
    market = data.get('market', 'omxs')
    years = int(data.get('years', 10))
    strategy = data.get('strategy', 'dip')
    return jsonify(run_backtest_local(market=market, years=years, strategy=strategy))


@api_bp.route('/backtest/stock', methods=['POST'])
def backtest_stock_route():
    data = request.json or {}
    sym = data.get('symbol', '').strip().upper()
    strat = data.get('strategy', 'dip')
    years = int(data.get('years', 5))
    return jsonify(run_single_stock_backtest(sym, strategy=strat, years=years))


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
        is_manual = bool(d.get('is_manual', False))
        name = (d.get('name') or '').strip()
        raw_sym = str(d.get('symbol') or '').strip()
        value = d.get('value')
        cost = d.get('cost')
        region = d.get('region')

        if not raw_sym and not name:
            return jsonify({"error": "Varken symbol eller namn angivet"}), 400

        # Manuellt innehav eller saknar ticker
        if is_manual or raw_sym.startswith('MANUAL:') or (not raw_sym and name):
            used_sym = pf.add_holding(
                symbol=raw_sym or None,
                qty=d.get('qty'),
                avg_price=d.get('avg_price'),
                name=name or raw_sym,
                kind=d.get('kind', 'fond'),
                fee_pct=d.get('fee_pct', 0),
                note=d.get('note', ''),
                value=value,
                cost=cost,
                is_manual=True,
                region=region
            )
            return jsonify({"ok": True, "symbol": used_sym})

        resolved = resolve_symbol(raw_sym) or raw_sym.upper()
        if value is not None or cost is not None:
            used_sym = pf.add_holding(
                symbol=resolved,
                qty=d.get('qty'),
                avg_price=d.get('avg_price'),
                name=name or pf._known_name(resolved),
                kind=d.get('kind', 'aktie'),
                fee_pct=d.get('fee_pct', 0),
                note=d.get('note', ''),
                value=value,
                cost=cost,
                is_manual=False,
                region=region
            )
        else:
            used_sym = pf.add_holding(
                symbol=resolved,
                qty=d['qty'],
                avg_price=d['avg_price'],
                name=name or pf._known_name(resolved),
                kind=d.get('kind', 'aktie'),
                fee_pct=d.get('fee_pct', 0),
                note=d.get('note', ''),
                region=region
            )
        return jsonify({"ok": True, "symbol": used_sym})
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


@api_bp.route('/recommendations')
def recommendations_route():
    market = request.args.get('market', 'all')
    refresh = request.args.get('refresh', '0') in ('1', 'true', 'True')
    try:
        data = build_recommendations(market=market, force_refresh=refresh)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/portfolio-backtest')
def portfolio_backtest_route():
    years = request.args.get('years', 10, type=int)
    try:
        data = run_portfolio_backtest(years=years)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/sell-alerts')
def sell_alerts_route():
    include_ack = request.args.get('include_acknowledged', '0') in ('1', 'true', 'True')
    try:
        alerts = pf.list_sell_alerts(include_acknowledged=include_ack)
        return jsonify({"alerts": alerts, "total": len(alerts)})
    except Exception as e:
        return jsonify({"error": str(e), "alerts": []}), 500


@api_bp.route('/sell-alerts/<int:alert_id>/acknowledge', methods=['POST'])
def sell_alert_ack_route(alert_id):
    try:
        ok = pf.acknowledge_sell_alert(alert_id)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500

