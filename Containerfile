FROM python:3.12-slim

# Valfria extra CA-certifikat (t.ex. för SSL-inspektion i ett företags- eller hemmanätverk):
# lägg *.crt-filer i certs/ innan bygget. Katalogen är tom i repot.
COPY certs/ /usr/local/share/ca-certificates/
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates && rm -rf /var/lib/apt/lists/*

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# App-inställningar (se src/core/settings.py)
ENV AKTIEANALYS_DB=/app/data/trading.db
ENV RUN_SCHEDULER=1

WORKDIR /app

# Install dependencies first (separate layer for cache efficiency)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app.py .
COPY src/ src/
COPY templates/ templates/

# Data dir for the SQLite database (mount a volume here)
RUN mkdir -p /app/data
VOLUME /app/data
EXPOSE 4000

# gunicorn: 1 worker med 4 trådar (cache-uppvärmningen efter synk gäller då alla anrop), 120s timeout (yfinance kan vara långsamt).
# Nattsynken skyddas av ett fillås i data.sync_all_stocks mot dubbelkörning.
CMD ["gunicorn", "--bind", "0.0.0.0:4000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
