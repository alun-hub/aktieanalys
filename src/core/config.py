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
    "^GSPC": "S&P 500",  # Global/US marknadsproxy för regim och koncentrationsanalys
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

    # Europeiska UCITS (handlas via Avanza/Nordnet på Euronext/Xetra/Stockholm - godkända för ISK)
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
    "XDEW.DE": {"name": "Xtrackers S&P 500 Equal Weight UCITS", "region": "USA", "sector": "ETF - Equal Weight"},
    "VHYL.AS": {"name": "Vanguard All-World High Dividend UCITS", "region": "Global", "sector": "ETF - Utdelning"},
    "FUSD.DE": {"name": "Fidelity US Quality Income UCITS", "region": "USA", "sector": "ETF - Utdelning"},
    "4GLD.DE": {"name": "Xetra-Gold", "region": "Råvaror", "sector": "ETF - Guld"},
    "DBZB.DE": {"name": "Xtrackers Global Aggregate Bond UCITS", "region": "Global", "sector": "ETF - Räntor"},

    # Amerikanska ETF:er
    "SPY": {"name": "SPDR S&P 500 ETF Trust", "region": "USA", "sector": "ETF - USA Index"},
    "QQQ": {"name": "Invesco QQQ Trust (Nasdaq 100)", "region": "USA", "sector": "ETF - USA Tech"},
    "VOO": {"name": "Vanguard S&P 500 ETF", "region": "USA", "sector": "ETF - USA Index"},
    "VTI": {"name": "Vanguard Total Stock Market ETF", "region": "USA", "sector": "ETF - USA Index"},
    "RSP": {"name": "Invesco S&P 500 Equal Weight ETF", "region": "USA", "sector": "ETF - Equal Weight"},
    "SCHD": {"name": "Schwab U.S. Dividend Equity ETF", "region": "USA", "sector": "ETF - Utdelning"},
    "VT": {"name": "Vanguard Total World Stock ETF", "region": "Global", "sector": "ETF - Global Index"},
    "ARKK": {"name": "ARK Innovation ETF", "region": "USA", "sector": "ETF - Innovation"},
    "GLD": {"name": "SPDR Gold Shares", "region": "Råvaror", "sector": "ETF - Guld"},
    "TLT": {"name": "iShares 20+ Year Treasury Bond ETF", "region": "USA", "sector": "ETF - Räntor"},
}

# Standardurval av UCITS-ETF:er för allokeringsmotorn (optimerat för svenskt ISK)
RECOMMENDED_UCITS_ETFS = {
    "broad_etf": [
        {"symbol": "VWCE.DE", "name": "Vanguard FTSE All-World UCITS (Acc)", "region": "Global", "fee_pct": 0.22},
        {"symbol": "IWDA.AS", "name": "iShares Core MSCI World UCITS", "region": "Global", "fee_pct": 0.20},
        {"symbol": "XACT-OMXS30.ST", "name": "Xact OMXS30 UCITS", "region": "Sverige", "fee_pct": 0.10},
    ],
    "equalweight_etf": [
        {"symbol": "XDEW.DE", "name": "Xtrackers S&P 500 Equal Weight UCITS", "region": "USA", "fee_pct": 0.20},
    ],
    "defensive": [
        {"symbol": "4GLD.DE", "name": "Xetra-Gold (Fysiskt guld)", "region": "Råvaror", "fee_pct": 0.0},
        {"symbol": "XACT-OBLIGATION.ST", "name": "Xact Obligation UCITS", "region": "Sverige", "fee_pct": 0.15},
        {"symbol": "DBZB.DE", "name": "Xtrackers Global Aggregate Bond UCITS", "region": "Global", "fee_pct": 0.10},
    ],
}

# Populära svenska fonder (för snabb sökning och auto-ifyllning i portföljen)
POPULAR_SWEDISH_FUNDS = {
    # Länsförsäkringar
    "LF-GLOBAL": {
        "name": "Länsförsäkringar Global Index",
        "fee_pct": 0.20,
        "region": "Global",
        "aliases": ["lf global", "lansforsakringar global", "länsförsäkringar global index", "lansforsakringar global index"]
    },
    "LF-TILLVAXT": {
        "name": "Länsförsäkringar Tillväxtmarknad Index",
        "fee_pct": 0.40,
        "region": "Tillväxtmarknader",
        "aliases": ["lf tillvaxt", "lansforsakringar tillvaxt", "länsförsäkringar tillväxtmarknad index"]
    },
    "LF-SVERIGE": {
        "name": "Länsförsäkringar Sverige Index",
        "fee_pct": 0.20,
        "region": "Sverige",
        "aliases": ["lf sverige", "lansforsakringar sverige", "länsförsäkringar sverige index"]
    },
    "LF-USA": {
        "name": "Länsförsäkringar USA Index",
        "fee_pct": 0.20,
        "region": "USA",
        "aliases": ["lf usa", "lansforsakringar usa", "länsförsäkringar usa index"]
    },
    "LF-EUROPA": {
        "name": "Länsförsäkringar Europa Index",
        "fee_pct": 0.20,
        "region": "Europa",
        "aliases": ["lf europa", "lansforsakringar europa", "länsförsäkringar europa index"]
    },
    "LF-SMABOLAG": {
        "name": "Länsförsäkringar Småbolag Sverige",
        "fee_pct": 1.40,
        "region": "Sverige",
        "aliases": ["lf smabolag", "lansforsakringar smabolag"]
    },
    "LF-FASTIGHET": {
        "name": "Länsförsäkringar Fastighetsfond",
        "fee_pct": 1.40,
        "region": "Sverige",
        "aliases": ["lf fastighet", "lansforsakringar fastighet"]
    },

    # Avanza Fonder
    "AVANZA-ZERO": {
        "name": "Avanza Zero",
        "fee_pct": 0.00,
        "region": "Sverige",
        "aliases": ["zero", "avanza zero"]
    },
    "AVANZA-GLOBAL": {
        "name": "Avanza Global",
        "fee_pct": 0.09,
        "region": "Global",
        "aliases": ["avanza global"]
    },
    "AVANZA-USA": {
        "name": "Avanza USA",
        "fee_pct": 0.17,
        "region": "USA",
        "aliases": ["avanza usa"]
    },
    "AVANZA-EUROPA": {
        "name": "Avanza Europa",
        "fee_pct": 0.17,
        "region": "Europa",
        "aliases": ["avanza europa"]
    },
    "AVANZA-EM": {
        "name": "Avanza Emerging Markets",
        "fee_pct": 0.29,
        "region": "Tillväxtmarknader",
        "aliases": ["avanza emerging", "avanza em", "avanza tillvaxt"]
    },
    "AVANZA-AUTO-6": {
        "name": "Avanza Auto 6",
        "fee_pct": 0.36,
        "region": "Global",
        "aliases": ["avanza auto", "auto 6"]
    },

    # Spiltan
    "SPILTAN-INVESTMENT": {
        "name": "Spiltan Aktiefond Investmentbolag",
        "fee_pct": 0.20,
        "region": "Sverige",
        "aliases": ["spiltan", "spiltan investment", "spiltan aktiefond"]
    },
    "SPILTAN-GLOBAL-INVEST": {
        "name": "Spiltan Globalfond Investmentbolag",
        "fee_pct": 0.50,
        "region": "Global",
        "aliases": ["spiltan global", "spiltan globalfond"]
    },
    "SPILTAN-RANTE": {
        "name": "Spiltan Räntefond Sverige",
        "fee_pct": 0.10,
        "region": "Räntor",
        "aliases": ["spiltan ranta", "spiltan rantefond"]
    },
    "SPILTAN-ENKEL": {
        "name": "Spiltan Enkel",
        "fee_pct": 0.20,
        "region": "Global",
        "aliases": ["spiltan enkel"]
    },

    # AMF
    "AMF-GLOBAL": {
        "name": "AMF Aktiefond Global",
        "fee_pct": 0.40,
        "region": "Global",
        "aliases": ["amf global", "amf aktiefond global"]
    },
    "AMF-SVERIGE": {
        "name": "AMF Aktiefond Sverige",
        "fee_pct": 0.40,
        "region": "Sverige",
        "aliases": ["amf sverige", "amf aktiefond sverige"]
    },
    "AMF-USA": {
        "name": "AMF Aktiefond Nordamerika",
        "fee_pct": 0.40,
        "region": "USA",
        "aliases": ["amf usa", "amf nordamerika"]
    },
    "AMF-EUROPA": {
        "name": "AMF Aktiefond Europa",
        "fee_pct": 0.40,
        "region": "Europa",
        "aliases": ["amf europa"]
    },
    "AMF-SMABOLAG": {
        "name": "AMF Aktiefond Småbolag",
        "fee_pct": 0.40,
        "region": "Sverige",
        "aliases": ["amf smabolag"]
    },
    "AMF-RANTEFOND-MIX": {
        "name": "AMF Räntefond Mix",
        "fee_pct": 0.10,
        "region": "Räntor",
        "aliases": ["amf ranta", "amf rantefond", "amf mix"]
    },

    # Swedbank Robur
    "SWEDBANK-ACCESS-GLOBAL": {
        "name": "Swedbank Robur Access Global",
        "fee_pct": 0.20,
        "region": "Global",
        "aliases": ["robur access global", "swedbank global"]
    },
    "SWEDBANK-ACCESS-SVERIGE": {
        "name": "Swedbank Robur Access Sverige",
        "fee_pct": 0.20,
        "region": "Sverige",
        "aliases": ["robur access sverige", "swedbank sverige"]
    },
    "SWEDBANK-ACCESS-USA": {
        "name": "Swedbank Robur Access USA",
        "fee_pct": 0.20,
        "region": "USA",
        "aliases": ["robur access usa", "swedbank usa"]
    },
    "SWEDBANK-TECHNOLOGY": {
        "name": "Swedbank Robur Technology",
        "fee_pct": 1.25,
        "region": "USA",
        "aliases": ["robur technology", "swedbank tech"]
    },
    "SWEDBANK-NY-TEKNIK": {
        "name": "Swedbank Robur Ny Teknik",
        "fee_pct": 1.25,
        "region": "Norden",
        "aliases": ["robur ny teknik", "swedbank ny teknik"]
    },

    # Handelsbanken
    "SHB-GLOBAL-SMA": {
        "name": "Handelsbanken Global Småbolag",
        "fee_pct": 0.60,
        "region": "Global",
        "aliases": ["shb global smabolag", "handelsbanken global sma"]
    },
    "SHB-GL-INDEX-CRIT": {
        "name": "Handelsbanken Gl Index Crit",
        "fee_pct": 0.40,
        "region": "Global",
        "aliases": ["handelsbanken global index", "shb global index"]
    },
    "SHB-SVERIGE-INDEX": {
        "name": "Handelsbanken Sverige Index Crit",
        "fee_pct": 0.40,
        "region": "Sverige",
        "aliases": ["handelsbanken sverige index", "shb sverige index"]
    },
    "SHB-USA-INDEX": {
        "name": "Handelsbanken USA Index Crit",
        "fee_pct": 0.40,
        "region": "USA",
        "aliases": ["handelsbanken usa index", "shb usa index"]
    },

    # Storebrand
    "STOREBRAND-GLOBAL-ALL": {
        "name": "Storebrand Global All Countries",
        "fee_pct": 0.30,
        "region": "Global",
        "aliases": ["storebrand global", "spp global"]
    },
    "STOREBRAND-USA": {
        "name": "Storebrand USA",
        "fee_pct": 0.20,
        "region": "USA",
        "aliases": ["storebrand usa", "spp usa"]
    },
    "STOREBRAND-SVERIGE": {
        "name": "Storebrand Sverige",
        "fee_pct": 0.20,
        "region": "Sverige",
        "aliases": ["storebrand sverige", "spp sverige"]
    },
    "STOREBRAND-EM": {
        "name": "Storebrand Tillväxtmarknader",
        "fee_pct": 0.40,
        "region": "Tillväxtmarknader",
        "aliases": ["storebrand tillvaxt", "storebrand emerging"]
    },

    # PLUS Fonder
    "PLUS-ALLABOLAG": {
        "name": "PLUS Allabolag Sverige Index",
        "fee_pct": 0.20,
        "region": "Sverige",
        "aliases": ["plus allabolag", "plus sverige"]
    },
    "PLUS-SMABOLAG": {
        "name": "PLUS Småbolag Sverige Index",
        "fee_pct": 0.40,
        "region": "Sverige",
        "aliases": ["plus smabolag"]
    },
    "PLUS-MIKROBOLAG": {
        "name": "PLUS Mikrobolag Sverige Index",
        "fee_pct": 0.40,
        "region": "Sverige",
        "aliases": ["plus mikrobolag"]
    },

    # DNB & Övriga
    "DNB-GLOBAL-INDEKS": {
        "name": "DNB Global Indeks",
        "fee_pct": 0.20,
        "region": "Global",
        "aliases": ["dnb global", "dnb global indeks"]
    },
    "DNB-TEKNOLOGI": {
        "name": "DNB Teknologi",
        "fee_pct": 1.20,
        "region": "Global",
        "aliases": ["dnb teknologi", "dnb tech"]
    },
    "TIN-NY-TEKNIK": {
        "name": "TIN Ny Teknik",
        "fee_pct": 1.50,
        "region": "Norden",
        "aliases": ["tin ny teknik", "tin fonder"]
    },
}


