"""Körtidsinställningar – läses från miljövariabler med rimliga defaultvärden.

Poängen: appen ska gå att köra med ett enkelt `python app.py` lokalt, utan
container och utan hårdkodade `/app/...`-sökvägar.
"""
import os

# Projektroten (…/aktieanalys)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# SQLite-fil. I containern sätts AKTIEANALYS_DB=/app/data/trading.db.
# DATA_DIR härleds ALLTID från DB_PATH (inte en egen miljövariabel) så att
# fillås m.m. garanterat hamnar i samma katalog som databasen faktiskt ligger i.
DB_PATH = os.getenv("AKTIEANALYS_DB", os.path.join(BASE_DIR, "data", "trading.db"))
DATA_DIR = os.path.dirname(DB_PATH) or "."

os.makedirs(DATA_DIR, exist_ok=True)

# Hur mycket historik som hämtas från Yahoo Finance vid synk.
# "max" krävs för att backtest över flera år ska vara ärligt.
HISTORY_PERIOD = os.getenv("AKTIEANALYS_HISTORY", "max")

# Starta den schemalagda nattsynken i den här processen?
# Sätts till "1" för en process; fillåset i data.sync_all_stocks skyddar ändå
# mot dubbelkörning om flera gunicorn-workers startar var sin schemaläggare.
RUN_SCHEDULER = os.getenv("RUN_SCHEDULER", "1") == "1"

# Antaganden som visas för användaren (sparprognos, kostnadsmodell)
FX_COST_PCT = 0.25          # Avanza valutaväxling, % per USD-affär
