#!/usr/bin/env bash
# Runs the importer inside the container against the read-only /raw mount.
# LIBRARY_RAW_DIR (from the environment or .env) selects the host raw directory.
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose up -d
docker compose exec -T library python -m library.importer --raw /raw --db /data/library.db
