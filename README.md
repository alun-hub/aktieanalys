# Aktieanalys

Ett personligt webbverktyg som hjälper en privatinvesterare att fatta bra, begripliga
beslut. Fokus ligger på det som faktiskt bygger förmögenhet över tid – regelbundet
sparande i billiga indexfonder, diversifiering och en lång horisont – med teknisk
analys som *kontext*, inte som köp-/säljsignaler.

Byggd med Flask + yfinance + pandas. Ren vanilla-JS-frontend, ingen framework.

## Vyer

| Vy | Vad den gör |
|----|-------------|
| **Din plan** | Sparprognos: vad regelbundet månadssparande i en indexfond kan bli, i dagens penningvärde, med fondavgiften avdragen. Visar också vad en dyr fond kostar jämfört med en billig. |
| **Min portfölj** | Lägg in dina innehav och få en hälsokoll: värde, vinst/förlust och framför allt **riskbilden** – koncentration per innehav, bransch- och landfördelning, vägd avgift. Ingen handel sker här. |
| **Analysera bolag** | Leder med *vad bolaget gör* och *hur det är värderat* (P/E, direktavkastning, pris i sitt 5-årsspann i klarspråk). Teknisk trend visas som kontext. Ingen "köpvärd"-dom. |
| **Marknadsläge** | Teknisk trend (glidande medelvärden + RSI) för bevakade aktier. Uttryckligen *inte* köp-/säljråd. |
| **Backtest** | Simulerar en regelstyrd swing-strategi *ärligt*: köp fylls på nästa dags öppningskurs, courtage/spread/valutaväxling dras av, jämförs alltid med "köp allt och behåll". Plus walk-forward som visar om strategin är överanpassad. |
| **Insyn / Kongress** | Insynshandel (Finansinspektionen) och amerikansk kongresshandel – som ren information, utan signalvärde. |
| **Krypto** | Trend och årlig volatilitet för de största kryptovalutorna. Ingen köpsignal. |
| **Ordlista** | Förklaringar av alla facktermer. Termer i texten går också att hovra över. |

## Kör lokalt

```bash
pip install -r requirements.txt
python app.py          # http://localhost:4000
```

Databasen (`data/trading.db`) skapas automatiskt. Klicka **Uppdatera kursdata** i
appen (eller vänta på nattsynken) för att fylla den – screener och backtest är tomma
tills dess. Full historik hämtas (`period="max"`), så första synken tar några minuter.

Miljövariabler (se `src/core/settings.py`): `AKTIEANALYS_DB` (sökväg till SQLite-filen;
katalogen den ligger i skapas automatiskt), `AKTIEANALYS_HISTORY`, `RUN_SCHEDULER`.

## Container / k3s

```bash
podman build -t localhost/aktieanalys:latest -f Containerfile .
podman run -d --name aktieanalys -p 4000:4000 -v aktieanalys-data:/app/data localhost/aktieanalys:latest
```

k3s: `./deploy.sh` bygger image:n, strömmar den via ssh till k3s-värden, applicerar `aktieanalys.yaml`
och en genererad ingress samt väntar på utrullningen. Kopiera `deploy.env.example` till `deploy.env`
och ange `DEPLOY_HOST` (ssh-värd, eller `local`) och `INGRESS_HOSTS`. Extra CA-certifikat (t.ex. vid
SSL-inspektion) läggs som `*.crt` i `certs/` före bygget. Appen läser `GEMINI_API_KEY` från en
Kubernetes-secret `gemini-api`, och `vol.yaml` skapar datavolymen.

## Datakällor & förbehåll

Kurser från Yahoo Finance via `yfinance` – fördröjda, och universumet är *dagens*
indexbolag (avnoterade bolag saknas, vilket smickrar historiska backtest –
"survivorship bias"). Insynsdata från Finansinspektionen, kongressdata från en öppen
datadump. **Inget i appen är finansiell rådgivning.**
