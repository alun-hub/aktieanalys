import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE, "data")

OMXS_50 = {
    "ABB.ST": "ABB", "ALFA.ST": "Alfa Laval", "ALIV-SDB.ST": "Autoliv", "ASSA-B.ST": "Assa Abloy B",
    "ATCO-A.ST": "Atlas Copco A", "ATCO-B.ST": "Atlas Copco B", "BOL.ST": "Boliden", "ELUX-B.ST": "Electrolux B",
    "ERIC-B.ST": "Ericsson B", "ESSITY-B.ST": "Essity B", "EVO.ST": "Evolution", "GETI-B.ST": "Getinge B",
    "HM-B.ST": "H&M B", "HEXA-B.ST": "Hexagon B", "HUSQ-B.ST": "Husqvarna B", "INDU-C.ST": "Industrivärden C",
    "INVE-B.ST": "Investor B", "KINV-B.ST": "Kinnevik B", "NIBE-B.ST": "Nibe B", "NDA-SE.ST": "Nordea",
    "SAND.ST": "Sandvik", "SCA-B.ST": "SCA B", "SECU-B.ST": "Securitas B", "SEB-A.ST": "SEB A",
    "SKA-B.ST": "Skanska B", "SKF-B.ST": "SKF B", "SHB-A.ST": "Handelsbanken A", "SWED-A.ST": "Swedbank A",
    "TEL2-B.ST": "Tele2 B", "TELIA.ST": "Telia", "VOLV-B.ST": "Volvo B",
    "ADDT-B.ST": "Addtech B", "AXFO.ST": "Axfood", "BILL.ST": "Billerud", "EQT.ST": "EQT",
    "FABG.ST": "Fabege", "HPOL-B.ST": "Hexpol B", "INDT.ST": "Indutrade", "INTRUM.ST": "Intrum",
    "NOLA-B.ST": "Nolato B", "PEAB-B.ST": "Peab B", "SAAB-B.ST": "SAAB B", "SINCH.ST": "Sinch",
    "SSAB-A.ST": "SSAB A", "SWEC-B.ST": "Sweco B", "THULE.ST": "Thule Group", "TREL-B.ST": "Trelleborg B",
    "VOLCAR-B.ST": "Volvo Cars B", "BALD-B.ST": "Fastighets Balder B", "BETS-B.ST": "Betsson B",
    "CAST.ST": "Castellum", "EPI-A.ST": "Epiroc A", "GRNG.ST": "Gränges", "HUFV-A.ST": "Hufvudstaden A",
    "HMS.ST": "HMS Networks", "LATO-B.ST": "Latour B", "LIAB.ST": "Lindab International",
    "LUND-B.ST": "Lundbergföretagen B", "MIPS.ST": "MIPS", "OEM-B.ST": "OEM International B",
    "PLAZ-B.ST": "Platzer B", "SOBI.ST": "Swedish Orphan Biovitrum", "TROAX.ST": "Troax Group",
    "WIHL.ST": "Wihlborgs", "DIOS.ST": "Diös Fastigheter",
    "BUFAB.ST": "Bufab", "CLAS-B.ST": "Clas Ohlson B", "KNOW.ST": "Knowit B", "SYSR.ST": "Systemair"
}

NASDAQ_100 = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon", "META": "Meta Platforms",
    "GOOGL": "Alphabet A", "GOOG": "Alphabet C", "TSLA": "Tesla", "AVGO": "Broadcom", "COST": "Costco",
    "NFLX": "Netflix", "ASML": "ASML", "AMD": "Advanced Micro Devices", "AZN": "AstraZeneca",
    "ADBE": "Adobe", "QCOM": "Qualcomm", "CSCO": "Cisco", "INTC": "Intel", "INTU": "Intuit"
}
