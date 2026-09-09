import os
import json
import sqlite3
from google import genai
from google.genai import types
from src.core.data import get_db
from src.core.signals import generate_daily_orders

def generate_ai_briefing():
    """Genererar analys med stabil JSON-hantering för Gemini 3.1."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return "Ingen API-nyckel."

    conn = get_db()
    conn.row_factory = sqlite3.Row
    raw_orders = generate_daily_orders()
    
    # 1. Hämta Marknadskontext (10 dagar)
    index_data = {}
    for idx in ["^OMX", "^NDX"]:
        try:
            r = conn.execute("SELECT close, (close / (SELECT close FROM history h2 WHERE h2.symbol = h.symbol AND h2.date < h.date ORDER BY h2.date DESC LIMIT 1 OFFSET 10) - 1) * 100 as perf_10d FROM history h WHERE symbol = ? ORDER BY date DESC LIMIT 1", (idx,)).fetchone()
            if r: index_data[idx] = {"perf_10d": round(r["perf_10d"], 2)}
        except: pass

    # 2. Berika Kandidater
    enriched_buys = []
    for o in raw_orders.get('buy', []):
        symbol = o['symbol']
        try:
            tech = conn.execute("SELECT rsi, ma50, volume, (SELECT AVG(volume) FROM history h2 WHERE h2.symbol = h.symbol AND h2.date < h.date ORDER BY h2.date DESC LIMIT 20) as avg_vol FROM history h WHERE symbol = ? ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
            history = conn.execute("SELECT close FROM history WHERE symbol = ? ORDER BY date DESC LIMIT 20", (symbol,)).fetchall()
            price_series = [round(h["close"], 2) for h in reversed(history)]
            if tech:
                enriched_buys.append({
                    "symbol": symbol, "rsi": round(tech["rsi"], 1) if tech["rsi"] else 0,
                    "volym_styrka": round(tech["volume"] / tech["avg_vol"], 2) if tech["avg_vol"] else 0,
                    "price_series_20d": price_series, "reason": o["reason"]
                })
        except: pass

    prompt = f"""
    Analysera köpkandidaterna och svara med JSON.
    POÄNG (1-100): 100=Bäst, 1=Sämst.

    MARKNAD (10d): OMXS30: {index_data.get('^OMX', {}).get('perf_10d')}% | Nasdaq: {index_data.get('^NDX', {}).get('perf_10d')}%
    KANDIDATER: {json.dumps(enriched_buys)}

    FORMAT (Svara ENDAST med detta JSON-objekt):
    {{
      "thought": "Kort analys här.",
      "scores": {{ "SYMBOL": poäng }}
    }}
    """

    try:
        client = genai.Client(api_key=api_key)
        
        # Använd Gemini 3.1 Pro Preview med tydligt text-baserat anrop
        response = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json'
            )
        )
        
        # Robust extrahering av text
        text_content = ""
        if hasattr(response, 'text'):
            text_content = response.text
        elif response.candidates:
            text_content = response.candidates[0].content.parts[0].text
            
        data = json.loads(text_content)
        
        with open("/app/data/ai_briefing.json", "w") as f:
            json.dump(data, f)
        
        thought = data.get("thought", "Analys klar.")
    except Exception as e:
        thought = f"Analys misslyckades (Error: {e})"
        try:
            with open("/app/data/ai_briefing.json", "w") as f:
                json.dump({"thought": thought, "scores": {}}, f)
        except: pass

    with open("/app/data/ai_thought.txt", "w") as f:
        f.write(thought)
    
    return thought
