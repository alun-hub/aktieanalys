"""Grov men ärlig transaktionskostnadsmodell.

Poängen är inte exakt courtage till öret utan att backtestet inte längre låtsas
att handel är gratis. Antagandena är medvetet lite i överkant.
"""
from src.core.settings import FX_COST_PCT

# Ungefärlig Avanza-nivå: ~0,25 % med golv 1 kr (Mini), täcker de flesta
# privatpersoners orderstorlekar för swing-trading.
COMMISSION_RATE = 0.0025
COMMISSION_MIN = 1.0

# Halva köp-/säljspreaden. Large cap är likvitt; ändå inte noll.
SPREAD_BPS = {"nasdaq": 6, "omxs": 10, "crypto": 25}


def commission(order_value_sek):
    return max(order_value_sek * COMMISSION_RATE, COMMISSION_MIN)


def spread_cost(order_value, market):
    return order_value * SPREAD_BPS.get(market, 10) / 10_000.0


def fx_cost(order_value, market):
    """Avanza tar ut en valutaväxlingsavgift på USA-affärer."""
    return order_value * (FX_COST_PCT / 100.0) if market == "nasdaq" else 0.0


def transaction_cost(order_value, market):
    """Total kostnad för en sida (köp ELLER sälj) av en affär."""
    return commission(order_value) + spread_cost(order_value, market) + fx_cost(order_value, market)
