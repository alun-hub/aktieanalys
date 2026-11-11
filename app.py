from flask import Flask, render_template
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import threading

from src.api.routes import api_bp
from src.core.data import init_db, sync_all_stocks
from src.core.settings import RUN_SCHEDULER

app = Flask(__name__)
init_db()


def _nightly_sync():
    print("Nattsynk: hämtar marknadsdata…")
    sync_all_stocks()
    print("Nattsynk: klar.")


if RUN_SCHEDULER:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_nightly_sync, "cron", hour=23, minute=30)
    scheduler.add_job(_nightly_sync, "cron", hour=4, minute=0)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))

def _warm_caches():
    """Räknar de tunga cacharna i bakgrunden så första användaren inte väntar."""
    try:
        from src.core.signals import get_strategy_prior
        from src.core.relative_strength import get_universe_momentum
        get_universe_momentum()
        for strat in ("dip", "momentum", "trend"):
            get_strategy_prior(strat)
    except Exception as e:
        print(f"Cache-uppvärmning misslyckades: {e}", flush=True)


threading.Thread(target=_warm_caches, daemon=True).start()

app.register_blueprint(api_bp, url_prefix="/api/portal")
app.register_blueprint(api_bp, url_prefix="/api", name="api_direct")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=4000)
