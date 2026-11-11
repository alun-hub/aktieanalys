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
| **Rekommendationer** | Regelbaserad målallokering mellan tillgångsklasser (bred index-ETF, likaviktad ETF, utdelningsaktier, tillväxtaktier, defensivt) utifrån marknadsregim (bull/korrektion/bear) och koncentrationsrisk i USA-tech, med konkreta kandidater per klass. En riskhanteringsregel – inte en prognos. |
| **Portfölj** | Lägg in dina innehav (ticker + antal/GAV, eller bara kronvärde, eller manuella fonder) och få en hälsokoll: värde, vinst/förlust och **riskbilden** – koncentration per innehav, bransch- och landfördelning, vägd avgift. Regelbaserade **sälj-/trimförslag** (ATR-stop, bear market, trendbrott) som du kvitterar manuellt. Ingen handel sker här. |
| **Möjligheter** | Dagens köpsignaler (dipp, momentum, trend) för OMXS- och Nasdaq-bolag, med kvalitetsspärr, relativ styrka och historisk edge per bolag. Du kan öppna de historiska affärerna bakom varje signal. |
| **Utdelning** | Rankning av utdelningsaktier utifrån direktavkastning, payout-kvot, P/E och trend – med varning för utdelningsfällor. |
| **Analysera** | Leder med *vad bolaget gör* och *hur det är värderat* (P/E, direktavkastning, pris i sitt 5-årsspann i klarspråk). Teknisk trend visas som kontext, tillsammans med insyns- och kongresshandel. |
| **Marknadsläge** | Teknisk trend (glidande medelvärden + RSI) för bevakade aktier. Uttryckligen *inte* köp-/säljråd. |
| **Backtest** | Simulerar regelstyrda strategier *ärligt*: köp fylls på nästa dags öppningskurs, courtage/spread/valutaväxling dras av, och resultatet jämförs alltid med "köp allt och behåll". Plus walk-forward som visar om strategin är överanpassad, och en historisk test av allokeringsregeln. |
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
katalogen den ligger i skapas automatiskt), `AKTIEANALYS_HISTORY`, `RUN_SCHEDULER`
(`1` = kör den inbyggda nattsynken kl. 23:30 och 04:00).

## Tester

```bash
pip install pytest
python -m pytest tests
```

## API

JSON-endpoints finns under både `/api/portal/…` (används av gränssnittet) och `/api/…`,
t.ex. `/api/portal/analyze?symbol=ERIC-B.ST`, `/portfolio/health`, `/sell-alerts`,
`/opportunities`, `/recommendations`, `/top-dividends` och `POST /backtest`. Se
`src/api/routes.py` för hela listan.

## Säkerhet

Appen har **ingen inloggning** och är gjord för ett privat nätverk (hemmanätverk eller
VPN). Exponera den inte direkt mot internet utan en autentiserande proxy framför. Portföljen
sparas i SQLite-filen i klartext.

## Container / k3s

```bash
podman build -t localhost/aktieanalys:latest -f Containerfile .
podman run -d --name aktieanalys -p 4000:4000 -v aktieanalys-data:/app/data localhost/aktieanalys:latest
```

Containern kör gunicorn med en worker och fyra trådar (cacharna är processlokala, så en
worker gör att uppvärmningen efter synk gäller alla anrop).

k3s: `./deploy.sh` bygger image:n, strömmar den via ssh till k3s-värden, applicerar `aktieanalys.yaml`
och en genererad ingress samt väntar på utrullningen. Kopiera `deploy.env.example` till `deploy.env`
och ange `DEPLOY_HOST` (ssh-värd, eller `local`) och `INGRESS_HOSTS`. Extra CA-certifikat (t.ex. vid
SSL-inspektion) läggs som `*.crt` i `certs/` före bygget. `vol.yaml` skapar
datavolymen (`PersistentVolumeClaim`) som måste finnas innan `aktieanalys.yaml` appliceras.

## Datakällor & förbehåll

Kurser från Yahoo Finance via `yfinance` – fördröjda, och universumet är *dagens*
indexbolag (avnoterade bolag saknas, vilket smickrar historiska backtest –
"survivorship bias"). Insynsdata från Finansinspektionen, kongressdata från en öppen
datadump. **Inget i appen är finansiell rådgivning.**
