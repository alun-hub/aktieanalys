import pandas as pd

def detect_patterns(df):
    """Identifierar vanliga candlestick-mönster på de senaste dagarna.
    df måste innehålla kolumnerna Open, High, Low, Close.
    """
    if df is None or len(df) < 3:
        return []

    patterns = []
    closes = df["Close"].values
    opens  = df["Open"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    
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

        # Doji: Liten kropp relativt hela rangen
        if body / rng < 0.08:
            patterns.append({
                "date": dates[i],
                "pattern": "Doji",
                "bullish": None,
                "desc": "Oavgjort – köpare och säljare är lika starka. Avvakta bekräftelse."
            })

        # Hammer: Lång nedre svans, liten kropp upptill, grön eller nära grön
        elif lower_wick > 2 * body and upper_wick < body and c >= o:
            patterns.append({
                "date": dates[i],
                "pattern": "Hammer",
                "bullish": True,
                "desc": "Bullish – köparna tryckte tillbaka priset från botten. Stark vändningssignal."
            })

        # Shooting Star: Lång övre svans, liten kropp nertill
        elif upper_wick > 2 * body and lower_wick < body and c <= o:
            patterns.append({
                "date": dates[i],
                "pattern": "Shooting Star",
                "bullish": False,
                "desc": "Bearish – säljarna pressade ned priset från dagshögsta. Risk för nedgång."
            })

        # Bullish Engulfing: Dagens gröna kropp slukar helt gårdagens röda
        elif c > o and pc < po and c > po and o < pc:
            patterns.append({
                "date": dates[i],
                "pattern": "Bullish Engulfing",
                "bullish": True,
                "desc": "Stark köpsignal – dagens köpare slukade hela gårdagens säljtapp."
            })

        # Bearish Engulfing: Dagens röda kropp slukar helt gårdagens gröna
        elif c < o and pc > po and c < po and o > pc:
            patterns.append({
                "date": dates[i],
                "pattern": "Bearish Engulfing",
                "bullish": False,
                "desc": "Stark säljsignal – säljarna tog total kontroll över gårdagens uppgång."
            })

        # Morning Star (3 ljus): Röd stor -> Liten star -> Grön stor som stänger över halva dag 1
        if i >= 2:
            c2, o2 = float(closes[i-2]), float(opens[i-2])
            mid_body = abs(pc - po)
            if (c2 < o2 and mid_body / rng < 0.35 and c > o and c > (c2 + o2) / 2):
                patterns.append({
                    "date": dates[i],
                    "pattern": "Morning Star",
                    "bullish": True,
                    "desc": "Stark bullish vändning (3-ljus) – köparna återtog kontrollen efter en svacka."
                })

    return patterns[-6:] if len(patterns) > 6 else patterns
