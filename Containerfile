FROM python:3.12-slim

# Trust UniFi SSL inspection certificate
COPY unifi-ca.crt /usr/local/share/ca-certificates/unifi-ca.crt
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (separate layer for cache efficiency)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app.py .
COPY templates/ templates/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Data dir for watchlist.json and portfolio.json (mount a volume here)
RUN mkdir -p /app/data

VOLUME /app/data
EXPOSE 4000

ENTRYPOINT ["/entrypoint.sh"]
# gunicorn: 2 workers, 120s timeout (yfinance calls can be slow)
CMD ["gunicorn", "--bind", "0.0.0.0:4000", "--workers", "2", "--timeout", "120", "app:app"]
