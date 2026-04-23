from flask import Flask, render_template
from src.api.routes import api_bp
from src.core.data import init_db, sync_all_stocks, update_stock_data, get_db
from src.core.ai_bridge import generate_ai_briefing
from src.core.portfolio import update_holdings_days
from apscheduler.schedulers.background import BackgroundScheduler
import os

app = Flask(__name__)

if not os.path.exists('data'):
    os.makedirs('data')

with app.app_context():
    init_db()

# --- AUTOMATISKA JOBB ---

def sync_portfolio_holdings():
    """Hämtar färska kurser för aktier vi faktiskt äger (var 15:e minut)."""
    print("SMART SYNC: Uppdaterar kurser för portföljinnehav...")
    conn = get_db()
    holdings = conn.execute("SELECT symbol FROM holdings").fetchall()
    for h in holdings:
        try:
            update_stock_data(h['symbol'])
            print(f"  - {h['symbol']} uppdaterad.")
        except Exception as e:
            print(f"  - Fel vid uppdatering av {h['symbol']}: {e}")

def nightly_sync_full():
    """Total genomgång av alla marknader (natt och tidig morgon)."""
    print("AUTONOMOUS JOB: Startar fullständig marknadssynk...")
    sync_all_stocks()
    print("AUTONOMOUS JOB: Marknadssynk klar.")

def morning_ai_job():
    """Genererar dagens rapport baserat på färsk marknadsdata."""
    print("AUTONOMOUS JOB: Startar morgonens AI-analys...")
    generate_ai_briefing()
    print("AUTONOMOUS JOB: AI-analys klar.")

def maintenance_job():
    """Dagligt underhåll (öka dagar ägda)."""
    print("MAINTENANCE: Ökar days_held för alla innehav.")
    update_holdings_days()

# --- SCHEMALÄGGARE ---
scheduler = BackgroundScheduler()

# 1. Full synk vid stängning och innan öppning
scheduler.add_job(nightly_sync_full, 'cron', hour=23, minute=30)
scheduler.add_job(nightly_sync_full, 'cron', hour=4, minute=0)

# 2. AI Analys kl 05:00
scheduler.add_job(morning_ai_job, 'cron', hour=5, minute=0)

# 3. Smart Sync för innehav (var 15:e minut under börsdagen)
scheduler.add_job(sync_portfolio_holdings, 'interval', minutes=15)

# 4. Underhåll vid midnatt
scheduler.add_job(maintenance_job, 'cron', hour=0, minute=5)

scheduler.start()

# --- ROUTES ---
app.register_blueprint(api_bp, url_prefix='/api/portal')

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # Stäng av debug-mode vid körning med scheduler för att undvika dubbla jobb
    app.run(debug=False, host='0.0.0.0', port=4000)
