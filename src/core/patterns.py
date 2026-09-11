import pandas as pd


def detect_patterns(df):
    """Identifierar vanliga candlestick-mönster på de senaste dagarna med modern trendkontext.
    
    df måste innehålla kolumnerna Open, High, Low, Close (oberoende av skiftläge).
    """
    if df is None or len(df) < 3:
        return []

    cols = {str(c).lower(): c for c in df.columns}
    if not all(k in cols for k in ("open", "high", "low", "close")):
        return []

    patterns = []
    closes = df[cols["close"]].values
    opens  = df[cols["open"]].values
    highs  = df[cols["high"]].values
    lows   = df[cols["low"]].values

    # Hantera datum-index
    if isinstance(df.index, pd.DatetimeIndex):
        dates = [d.strftime("%Y-%m-%d") for d in df.index]
    else:
        dates = [str(d)[:10] for d in df.index]

    for i in range(1, len(df)):
        c, o, h, l = float(closes[i]), float(opens[i]), float(highs[i]), float(lows[i])
        pc, po     = float(closes[i-1]), float(opens[i-1])
        body       = abs(c - o)
        rng        = h - l
        if rng < 0.0001:
            continue

        lower_wick = min(c, o) - l
        upper_wick = h - max(c, o)

        # Trendkontext före det aktuella ljuset (kort till medellång trend)
        lookback = min(5, i)
        prior_change = closes[i-1] - closes[i-lookback]
        in_downtrend = prior_change < 0
        in_uptrend = prior_change > 0

        # 1. Hammer & Hanging Man (Lång nedre svans, liten kropp upptill)
        if lower_wick > 2 * body and upper_wick < max(body, rng * 0.15):
            if in_downtrend or (pc <= po and c >= o):
                patterns.append({
                    "date": dates[i],
                    "pattern": "Hammer",
                    "bullish": True,
                    "desc": "Bullish – köparna tryckte tillbaka priset från botten efter en nedgång. Stark vändningssignal."
                })
            else:
                patterns.append({
                    "date": dates[i],
                    "pattern": "Hanging Man",
                    "bullish": False,
                    "desc": "Bearish varning – uppträdde efter uppgång, det djupa testet nedåt signalerar växande säljtryck."
                })

        # 2. Shooting Star & Inverted Hammer (Lång övre svans, liten kropp nertill)
        elif upper_wick > 2 * body and lower_wick < max(body, rng * 0.15):
            if in_uptrend or (pc >= po and c <= o):
                patterns.append({
                    "date": dates[i],
                    "pattern": "Shooting Star",
                    "bullish": False,
                    "desc": "Bearish – säljarna pressade ned priset från dagshögsta i en uppgångsfas. Risk för rekyl."
                })
            else:
                patterns.append({
                    "date": dates[i],
                    "pattern": "Inverted Hammer",
                    "bullish": True,
                    "desc": "Bullish – köparna testade högre nivåer efter en nedgång, vilket signalerar gryende köpintresse."
                })

        # 3. Doji: Mycket liten kropp relativt hela dagsintervallet (utan extrem asymmetrisk svans)
        elif body / rng < 0.08:
            patterns.append({
                "date": dates[i],
                "pattern": "Doji",
                "bullish": None,
                "desc": "Oavgjort – köpare och säljare är lika starka. Avvakta bekräftelse."
            })

        # 4. Bullish Engulfing: Dagens gröna kropp slukar helt gårdagens röda
        elif c > o and pc < po and c >= po and o <= pc and body >= abs(pc - po):
            patterns.append({
                "date": dates[i],
                "pattern": "Bullish Engulfing",
                "bullish": True,
                "desc": "Stark köpsignal – dagens köpare slukade hela gårdagens säljtapp."
            })

        # 5. Bearish Engulfing: Dagens röda kropp slukar helt gårdagens gröna
        elif c < o and pc > po and c <= po and o >= pc and body >= abs(pc - po):
            patterns.append({
                "date": dates[i],
                "pattern": "Bearish Engulfing",
                "bullish": False,
                "desc": "Stark säljsignal – säljarna tog total kontroll över gårdagens uppgång."
            })

        # 6. Morning Star & Evening Star (3 ljus)
        if i >= 2:
            c2, o2 = float(closes[i-2]), float(opens[i-2])
            ph, pl = float(highs[i-1]), float(lows[i-1])
            star_body = abs(pc - po)
            star_rng = max(ph - pl, 0.0001)

            # Morning Star: Stor röd dag 1 -> Liten star dag 2 -> Stor grön dag 3 över halva dag 1
            if (c2 < o2 and (star_body / star_rng < 0.40) and c > o and c > (c2 + o2) / 2):
                patterns.append({
                    "date": dates[i],
                    "pattern": "Morning Star",
                    "bullish": True,
                    "desc": "Stark bullish vändning (3-ljus) – köparna återtog kontrollen efter en svacka."
                })
            # Evening Star: Stor grön dag 1 -> Liten star dag 2 -> Stor röd dag 3 under halva dag 1
            elif (c2 > o2 and (star_body / star_rng < 0.40) and c < o and c < (c2 + o2) / 2):
                patterns.append({
                    "date": dates[i],
                    "pattern": "Evening Star",
                    "bullish": False,
                    "desc": "Stark bearish vändning (3-ljus) – säljarna tog över initiativet i toppen av trenden."
                })

    return patterns[-6:] if len(patterns) > 6 else patterns
