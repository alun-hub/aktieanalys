#!/bin/sh
set -e

# Ensure data dir exists and initialize empty JSON files if missing
mkdir -p /app/data
[ -f /app/data/watchlist.json ] || echo '[]' > /app/data/watchlist.json
[ -f /app/data/portfolio.json  ] || echo '[]' > /app/data/portfolio.json

# Symlink data files into /app so app.py (which uses BASE=__file__ dir) finds them
ln -sf /app/data/watchlist.json /app/watchlist.json
ln -sf /app/data/portfolio.json  /app/portfolio.json

exec "$@"
