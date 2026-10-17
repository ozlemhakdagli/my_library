#!/usr/bin/env bash
# Smoke test: build and start the container, then check the running app.
set -euo pipefail

cd "$(dirname "$0")/.."
BASE="http://localhost:8765"

docker compose up -d --build

deadline=$((SECONDS + 30))
until curl -fs "$BASE/health" > /dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "smoke: /health did not respond within 30 s" >&2
        exit 1
    fi
    sleep 1
done
echo "smoke: /health ok"

curl -fs "$BASE/" > /dev/null
echo "smoke: / ok"

curl -fs "$BASE/?lang=tr" | grep -q Kitaplar
echo "smoke: ?lang=tr shows Kitaplar"
