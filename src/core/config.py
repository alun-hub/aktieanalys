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
    "TIETO.ST":     "TietoEVRY",
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
