import os
import json
import sqlite3
import google.generativeai as genai
from src.core.data import get_db
from src.core.strategy import generate_daily_orders

def generate_ai_briefing():
    """Genererar en strukturerad analys med poängsättning per aktie."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return "Ingen API-nyckel."

    conn = get_db()
    conn.row_factory = sqlite3.Row
    raw_orders = generate_daily_orders()
    portfolio = conn.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
    
    index_data = {}
    for idx in ["^OMX", "^NDX"]:
        r = conn.execute("SELECT close, (close / (SELECT close FROM history h2 WHERE h2.symbol = h.symbol AND h2.date < h.date ORDER BY h2.date DESC LIMIT 1 OFFSET 10) - 1) * 100 as perf_10d FROM history h WHERE symbol = ? ORDER BY date DESC LIMIT 1", (idx,)).fetchone()
        if r: index_data[idx] = {"perf_10d": round(r["perf_10d"], 2)}

    enriched_buys = []
    for o in raw_orders['buy']:
        symbol = o['symbol']
        tech = conn.execute("SELECT rsi, ma50, volume, (SELECT AVG(volume) FROM history h2 WHERE h2.symbol = h.symbol AND h2.date < h.date ORDER BY h2.date DESC LIMIT 20) as avg_vol FROM history h WHERE symbol = ? ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
        history = conn.execute("SELECT close FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 20", (symbol,)).fetchall()
        price_series = [round(h["close"], 2) for h in reversed(history)]
        if tech:
            enriched_buys.append({
                "symbol": symbol, "rsi": round(tech["rsi"], 1) if tech["rsi"] else 0,
                "volym_styrka": round(tech["volume"] / tech["avg_vol"], 2) if tech["avg_vol"] else 0,
                "price_series_20d": price_series, "reason": o["reason"]
            })

    prompt = f"""
    Du är en senior förvaltare. Analysera köpkandidaterna och ge varje aktie en 'Confidence Score' mellan 1 och 100.
    100 = Perfekt mönster, låg risk, hög potential.
    1 = Svagt mönster, överköpt eller hög marknadsrisk.

    MARKNAD (10d): OMXS30: {index_data.get('^OMX', {}).get('perf_10d')}% | Nasdaq: {index_data.get('^NDX', {}).get('perf_10d')}%

    KANDIDATER:
    {json.dumps(enriched_buys, indent=2)}

    SVARAFORMAT (JSON):
    {{
      "thought": "Din korta sammanfattning här (max 3 meningar).",
      "scores": {{ "SYMBOL": poäng_heltal }}
    }}
    Svara ENDAST med JSON-objektet.
    """

    try:
        genai.configure(api_key=api_key)
        # Fixat: Använder det fullständiga namnet för preview-modellen
        model = genai.GenerativeModel('models/gemini-3.1-pro-preview')
        response = model.generate_content(prompt)
        # Städa bort eventuella markdown-taggar om AI:n skickar sådana
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_json)
        
        with open("/app/data/ai_briefing.json", "w") as f:
            json.dump(data, f)
        
        thought = data.get("thought", "Analys klar.")
    except Exception as e:
        thought = f"Analys klar (AI Score fail: {e})"
        with open("/app/data/ai_briefing.json", "w") as f:
            json.dump({"thought": thought, "scores": {}}, f)

    # Behåll bakåtkompatibilitet för ai_thought.txt
    with open("/app/data/ai_thought.txt", "w") as f:
        f.write(thought)
    
    return thought
