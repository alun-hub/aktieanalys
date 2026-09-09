from flask import Flask, render_template
from src.api.routes import api_bp
from src.core.data import init_db, sync_all_stocks
from src.core.ai_bridge import generate_ai_briefing
from apscheduler.schedulers.background import BackgroundScheduler
import os

app = Flask(__name__)

if not os.path.exists('data'):
    os.makedirs('data')

with app.app_context():
    init_db()

# --- AUTOMATISKA BAKGRUNDSJOBB ---

def nightly_sync_full():
    """Total genomgång av alla marknader (natt och tidig morgon)."""
    print("AUTONOMOUS JOB: Startar fullständig marknadssynk...")
    sync_all_stocks()
    print("AUTONOMOUS JOB: Marknadssynk klar.")

def morning_ai_job():
    """Genererar dagens rapport baserat på färsk marknadsdata."""
    print("AUTONOMOUS JOB: Startar morgonens AI-analys...")
    try:
        generate_ai_briefing()
        print("AUTONOMOUS JOB: AI-analys klar.")
    except Exception as e:
        print(f"AUTONOMOUS JOB: AI-analys misslyckades: {e}")

# --- SCHEMALÄGGARE ---
scheduler = BackgroundScheduler()

# 1. Full synk vid stängning och innan öppning
scheduler.add_job(nightly_sync_full, 'cron', hour=23, minute=30)
scheduler.add_job(nightly_sync_full, 'cron', hour=4, minute=0)

# 2. AI Analys kl 05:00
scheduler.add_job(morning_ai_job, 'cron', hour=5, minute=0)

scheduler.start()

# --- ROUTES ---
app.register_blueprint(api_bp, url_prefix='/api/portal')

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=4000)
