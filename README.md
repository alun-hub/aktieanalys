# Aktieanalys for n00b's

Webbapp för teknisk analys av svenska aktier, optimerad för swing trading (2–4 trades/månad). Byggd med Flask och yfinance, körs i Podman/Docker.

![Python](https://img.shields.io/badge/python-3.12-blue) ![Flask](https://img.shields.io/badge/flask-3.1-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Funktioner

### Marknadspuls
Visar OMXS30:s långsiktiga trend (Golden Cross / Death Cross) direkt under headern. Grönt = upptrend, rött = nedtrend. Påverkar Swing-Score för alla aktier.

### Aktieanalys
Analysera en eller flera aktier med:
- **MA50 / MA200** – Golden Cross (köp) eller Death Cross (sälj)
- **RSI 14** – översåld / neutral / överköpt
- **MACD 12/26/9** – momentum och riktning
- **Bollinger Bands** – prisposition relativt normalvariation
- **Candlestick-mönster** – Hammer, Shooting Star, Doji, Engulfing, Morning Star
- **Stop-loss & kursmål** – ATR-baserade nivåer med 1:2 och 1:3 R/R
- **Positionsstorlekskalkylator** – räknar max antal aktier baserat på portföljstorlek och risktolerans (1–2%)

### Swing-Score (0–10)
Bedömer om *timing för entry* är rätt just nu, baserat på 5 kriterier:

| Kriterium | Poäng |
|-----------|-------|
| OMXS30 i upptrend | 2 |
| RSI i köpzon (32–52) | 2 |
| Färsk MACD-korsning (≤5 dagar) | 2 |
| Kurs vid MA50 eller nedre Bollinger Band (±4%) | 2 |
| Volym över 20-dagarssnitt | 2 |

- **8–10**: PRIME SETUP – sällsynt, agera
- **6–7**: BRA SETUP – godkänd entry
- **4–5**: AVVAKTA – för tidig, invänta dipp
- **0–3**: UNDVIK – dålig timing

### Top 3 köprekommendationer
Screener-fliken visar automatiskt de tre aktier som bäst uppfyller swing trade-kriterierna. Krav för att kvalificera:
- Golden Cross (långsiktig upptrend)
- Swing-Score ≥ 6 (BRA SETUP eller bättre)
- Minst 2 av 3 klassiska indikatorer positiva

Om inga aktier kvalificerar visas ett meddelande – hellre ingen handel än dålig handel.

### Screener
Analyserar 72 svenska Large/Mid Cap-aktier parallellt. Filter:
- Prime Setup (Swing-Score ≥ 8)
- Köp / Köp–Håll / Håll–Sälj / Sälj

### Förklara-läge
Klicka på **❓ Förklara** i headern för att aktivera förklaringsläge. Klicka sedan på valfri indikator, tabell eller term för att få en nybörjarvänlig förklaring i en panel längst ned på skärmen.

### Portfölj & Bevakningslista
Spara egna innehav och bevakade aktier. Data lagras lokalt i JSON-filer.

---

## Kom igång

### Krav
- Podman (eller Docker)

### Starta med Podman

```bash
# Bygg image
podman build -t aktieanalys .

# Starta container med persistent data
podman run -d \
  --name aktieanalys \
  -p 5000:5000 \
  -v aktieanalys-data:/app/data \
  aktieanalys

# Öppna i webbläsaren
open http://localhost:5000
```

### Starta lokalt (utan container)

```bash
pip install -r requirements.txt
python app.py
```

### Stoppa / uppdatera

```bash
# Stoppa
podman stop aktieanalys

# Uppdatera efter kodändring
podman stop aktieanalys && podman rm aktieanalys
podman build -t aktieanalys . && podman run -d --name aktieanalys -p 5000:5000 -v aktieanalys-data:/app/data aktieanalys
```

---

## Teknisk stack

| Komponent | Teknologi |
|-----------|-----------|
| Backend | Python 3.12, Flask 3.1 |
| Data | yfinance (Yahoo Finance) |
| Analys | pandas, beräkningar i Python |
| Frontend | Vanilla JS, HTML/CSS (ingen framework) |
| Container | Podman / Docker, gunicorn (2 workers, 120s timeout) |
| Persistens | JSON-filer via named volume |

---

## Datakällor

Kurser och historik hämtas från **Yahoo Finance** via `yfinance`. Datan är fördröjd och kan saknas för avnoterade eller sällan handlade aktier. Appen är avsedd för analys och lärande – **inte** som finansiell rådgivning.

> ⚠️ Sätt alltid stop-loss. Ej finansiell rådgivning.
