"""Sparprognos – vad regelbundet sparande i en billig, bred indexfond kan bli.

Alla belopp räknas i DAGENS köpkraft (real avkastning efter inflation), så
slutsumman inte blåses upp av inflation. Fondavgiften dras av.
"""

# Långsiktig real avkastning (efter inflation) för en bred aktieindexfond.
# ~5 % är ett vanligt historiskt medel för globala aktier; 3 % och 7 % som spann.
SCENARIOS = {"försiktigt": 3.0, "normalt": 5.0, "optimistiskt": 7.0}


def _grow(start, monthly, months, annual_pct):
    m = (1 + annual_pct / 100) ** (1 / 12) - 1
    bal = float(start)
    yearly = [{"year": 0, "value": round(bal)}]
    for i in range(1, months + 1):
        bal = bal * (1 + m) + monthly
        if i % 12 == 0:
            yearly.append({"year": i // 12, "value": round(bal)})
    return bal, yearly


def project(start_amount=0, monthly=2000, years=20, fee_pct=0.4):
    start_amount = max(0.0, float(start_amount))
    monthly = max(0.0, float(monthly))
    years = max(1, min(60, int(years)))
    fee_pct = max(0.0, min(3.0, float(fee_pct)))
    months = years * 12

    scenarios = {}
    for label, gross in SCENARIOS.items():
        net = gross - fee_pct
        final, series = _grow(start_amount, monthly, months, net)
        scenarios[label] = {"real_return_pct": gross, "net_return_pct": round(net, 2),
                            "final": round(final), "series": series}

    contributed = round(start_amount + monthly * months)
    mid = scenarios["normalt"]["final"]

    return {
        "input": {"start_amount": round(start_amount), "monthly": round(monthly),
                  "years": years, "fee_pct": fee_pct},
        "total_contributed": contributed,
        "scenarios": scenarios,
        "growth_vs_contributed": mid - contributed,
        "fee_comparison": _fee_comparison(start_amount, monthly, months),
        "assumptions": [
            "Beloppen är i dagens köpkraft – real avkastning efter inflation, inte nominell.",
            "Fondavgiften är avdragen. Courtage/växlingsavgifter för fondköp är oftast noll.",
            f"'Normalt' = {SCENARIOS['normalt']:g} %/år real, ungefär globala aktiers historiska snitt.",
            "Verkligt utfall varierar kraftigt. Börsen kan falla 40–50 % och ta flera år att återhämta.",
            "Detta är en illustration, inte ett löfte om avkastning.",
        ],
    }


def _fee_comparison(start_amount, monthly, months):
    """Vad avgiften kostar: billig indexfond (0,2 %) mot dyr fond (1,4 %), 5 % brutto."""
    cheap, _ = _grow(start_amount, monthly, months, 5.0 - 0.2)
    pricey, _ = _grow(start_amount, monthly, months, 5.0 - 1.4)
    return {
        "cheap_fee_pct": 0.2, "cheap_final": round(cheap),
        "pricey_fee_pct": 1.4, "pricey_final": round(pricey),
        "difference": round(cheap - pricey),
        "text": "Samma sparande och samma bruttoavkastning (5 %/år). Enda skillnaden är "
                "fondavgiften. Skillnaden hamnar hos fondbolaget istället för hos dig.",
    }
