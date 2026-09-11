# --- KONFIGURATION FÖR TRADING PORTAL ---

# OMXS Large Cap — aktiva aktier per 2025
# Borttagna: LUNE.ST (fusionerades med Aker BP 2022), SWMA.ST (avnoterades okt 2022),
#            CAST.ST (förvärvades av Balder/SBB 2022), HMB.ST (felaktig ticker → HM-B.ST)
OMXS_50 = {
    # Storbolag
    "ABB.ST":       "ABB",
    "ALFA.ST":      "Alfa Laval",
    "ALIV-SDB.ST":  "Autoliv SDB",
    "ASSA-B.ST":    "Assa Abloy B",
    "ATCO-A.ST":    "Atlas Copco A",
    "ATCO-B.ST":    "Atlas Copco B",
    "AZN.ST":       "AstraZeneca",
    "BOL.ST":       "Boliden",
    "ELUX-B.ST":    "Electrolux B",
    "EPIR.ST":      "Epiroc B",
    "ERIC-B.ST":    "Ericsson B",
    "ESSITY-B.ST":  "Essity B",
    "EVO.ST":       "Evolution",
    "GETI-B.ST":    "Getinge B",
    "HEXA-B.ST":    "Hexagon B",
    "HM-B.ST":      "H&M B",
    "HUSQ-B.ST":    "Husqvarna B",
    "INVE-B.ST":    "Investor B",
    "KINV-B.ST":    "Kinnevik B",
    "LATO-B.ST":    "Latour B",
    "NIBE-B.ST":    "NIBE B",
    "NDA-SE.ST":    "Nordea",
    "SAND.ST":      "Sandvik",
    "SCA-B.ST":     "SCA B",
    "SEB-A.ST":     "SEB A",
    "SHB-A.ST":     "Handelsbanken A",
    "SINCH.ST":     "Sinch",
    "SKA-B.ST":     "Skanska B",
    "SKF-B.ST":     "SKF B",
    "SSAB-A.ST":    "SSAB A",
    "SSAB-B.ST":    "SSAB B",
    "SWED-A.ST":    "Swedbank A",
    "TEL2-B.ST":    "Tele2 B",
    "TELIA.ST":     "Telia",
    "THULE.ST":     "Thule Group",
    "TREL-B.ST":    "Trelleborg B",
    "VOLV-B.ST":    "Volvo B",
    "VOLCAR-B.ST":  "Volvo Cars B",
    # Övrig Large Cap
    "BALD-B.ST":    "Balder B",
    "FABG.ST":      "Fabege",
    "HUFV-A.ST":    "Hufvudstaden A",
    "INDUT.ST":     "Indutrade",
    "LIAB.ST":      "Lifco B",
    "LUND-B.ST":    "Lundbergföretagen B",
    "PEAB-B.ST":    "Peab B",
    "SECU-B.ST":    "Securitas B",
    "TIETOS.ST":    "TietoEVRY",
}

# Nasdaq 100 — 50 mest likvida och marknadsviktade (per 2025)
NASDAQ_100 = {
    # Mega cap tech
    "AAPL":  "Apple",
    "MSFT":  "Microsoft",
    "NVDA":  "Nvidia",
    "AMZN":  "Amazon",
    "META":  "Meta",
    "GOOGL": "Alphabet A",
    "GOOG":  "Alphabet C",
    "TSLA":  "Tesla",
    "AVGO":  "Broadcom",
    # Halvledare
    "AMD":   "AMD",
    "QCOM":  "Qualcomm",
    "ASML":  "ASML Holding",
    "AMAT":  "Applied Materials",
    "MU":    "Micron Technology",
    "KLAC":  "KLA Corporation",
    "LRCX":  "Lam Research",
    "MRVL":  "Marvell Technology",
    "ADI":   "Analog Devices",
    "MCHP":  "Microchip Technology",
    "ON":    "ON Semiconductor",
    "SNPS":  "Synopsys",
    "CDNS":  "Cadence Design",
    # Mjukvara & Cloud
    "ADBE":  "Adobe",
    "INTU":  "Intuit",
    "CRWD":  "CrowdStrike",
    "PANW":  "Palo Alto Networks",
    "FTNT":  "Fortinet",
    "CSCO":  "Cisco",
    # Cybersäkerhet / SaaS
    "ABNB":  "Airbnb",
    "PYPL":  "PayPal",
    # Internet & Media
    "NFLX":  "Netflix",
    "MELI":  "MercadoLibre",
    # Hälsa & Biotech
    "ISRG":  "Intuitive Surgical",
    "REGN":  "Regeneron",
    "VRTX":  "Vertex Pharmaceuticals",
    "GILD":  "Gilead Sciences",
    "DXCM":  "Dexcom",
    "IDXX":  "IDEXX Laboratories",
    # Konsument
    "COST":  "Costco",
    "SBUX":  "Starbucks",
    "MNST":  "Monster Beverage",
    "MDLZ":  "Mondelez",
    "PEP":   "PepsiCo",
    # Industri & Övrig
    "ADP":   "ADP",
    "CTAS":  "Cintas",
    "PAYX":  "Paychex",
    "PCAR":  "PACCAR",
    "ODFL":  "Old Dominion Freight",
    "FAST":  "Fastenal",
    "ROST":  "Ross Stores",
}

# Index för marknadsanalys
INDEX_TICKERS = {
    "^OMX": "OMXS30",
    "^NDX": "Nasdaq 100",
}

# Populära ETF:er (svenska, nordiska och europeiska UCITS samt US core)
POPULAR_ETFS = {
    # Svenska & Nordiska (XACT m.fl.)
    "XACTHDIV.ST": {"name": "Xact Norden Högutdelande", "region": "Norden", "sector": "ETF - Utdelning"},
    "XACT-OMXS30.ST": {"name": "Xact OMXS30", "region": "Sverige", "sector": "ETF - Sverige"},
    "XACT-SVERIGE.ST": {"name": "Xact Sverige", "region": "Sverige", "sector": "ETF - Sverige"},
    "XACT-SMABOLAG.ST": {"name": "Xact Småbolag", "region": "Sverige", "sector": "ETF - Småbolag"},
    "XACT-SVENSKA-SMABOLAG.ST": {"name": "Xact Svenska Småbolag", "region": "Sverige", "sector": "ETF - Småbolag"},
    "XACT-OBLIGATION.ST": {"name": "Xact Obligation", "region": "Sverige", "sector": "ETF - Räntor"},
    "XACT-BEAR-2.ST": {"name": "Xact Bear 2", "region": "Sverige", "sector": "ETF - Bear/Hedge"},
    "XACT-BULL-2.ST": {"name": "Xact Bull 2", "region": "Sverige", "sector": "ETF - Bull/Hävstång"},

    # Europeiska UCITS (handlas via Avanza/Nordnet på Euronext/Xetra)
    "CSPX.AS": {"name": "iShares Core S&P 500 UCITS (Acc)", "region": "USA", "sector": "ETF - USA Index"},
    "SXR8.DE": {"name": "iShares Core S&P 500 UCITS (DE)", "region": "USA", "sector": "ETF - USA Index"},
    "IWDA.AS": {"name": "iShares Core MSCI World UCITS", "region": "Global", "sector": "ETF - Global Index"},
    "EUNL.DE": {"name": "iShares Core MSCI World UCITS (DE)", "region": "Global", "sector": "ETF - Global Index"},
    "VWCE.DE": {"name": "Vanguard FTSE All-World UCITS (Acc)", "region": "Global", "sector": "ETF - Global Index"},
    "VWRL.AS": {"name": "Vanguard FTSE All-World UCITS (Dist)", "region": "Global", "sector": "ETF - Global Index"},
    "VUSA.AS": {"name": "Vanguard S&P 500 UCITS", "region": "USA", "sector": "ETF - USA Index"},
    "VUAA.DE": {"name": "Vanguard S&P 500 UCITS (Acc)", "region": "USA", "sector": "ETF - USA Index"},
    "EQAC.DE": {"name": "Invesco EQQQ Nasdaq-100 UCITS", "region": "USA", "sector": "ETF - USA Tech"},
    "EQQQ.L": {"name": "Invesco EQQQ Nasdaq-100 UCITS (L)", "region": "USA", "sector": "ETF - USA Tech"},
    "EMIM.AS": {"name": "iShares Core MSCI EM IMI UCITS", "region": "Tillväxtmarknader", "sector": "ETF - Tillväxtmarknader"},
    "IS3N.DE": {"name": "iShares Core MSCI EM IMI UCITS (DE)", "region": "Tillväxtmarknader", "sector": "ETF - Tillväxtmarknader"},
    "XD9U.DE": {"name": "Xtrackers S&P 500 UCITS", "region": "USA", "sector": "ETF - USA Index"},
    "4GLD.DE": {"name": "Xetra-Gold", "region": "Råvaror", "sector": "ETF - Guld"},

    # Amerikanska ETF:er
    "SPY": {"name": "SPDR S&P 500 ETF Trust", "region": "USA", "sector": "ETF - USA Index"},
    "QQQ": {"name": "Invesco QQQ Trust (Nasdaq 100)", "region": "USA", "sector": "ETF - USA Tech"},
    "VOO": {"name": "Vanguard S&P 500 ETF", "region": "USA", "sector": "ETF - USA Index"},
    "VTI": {"name": "Vanguard Total Stock Market ETF", "region": "USA", "sector": "ETF - USA Index"},
    "SCHD": {"name": "Schwab U.S. Dividend Equity ETF", "region": "USA", "sector": "ETF - Utdelning"},
    "VT": {"name": "Vanguard Total World Stock ETF", "region": "Global", "sector": "ETF - Global Index"},
    "ARKK": {"name": "ARK Innovation ETF", "region": "USA", "sector": "ETF - Innovation"},
    "GLD": {"name": "SPDR Gold Shares", "region": "Råvaror", "sector": "ETF - Guld"},
    "TLT": {"name": "iShares 20+ Year Treasury Bond ETF", "region": "USA", "sector": "ETF - Räntor"},
}

