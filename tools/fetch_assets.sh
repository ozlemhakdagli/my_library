#!/usr/bin/env bash
# Downloads the pinned Tailwind standalone CLI into tools/ and the pinned
# HTMX build into src/library/web/static/, then builds static/app.css.
# Run from anywhere; requires curl.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/tools"
STATIC="$ROOT/src/library/web/static"

TAILWIND_VERSION="v4.1.16"
HTMX_VERSION="2.0.4"

mkdir -p "$TOOLS"

TAILWIND_BIN="$TOOLS/tailwindcss"
if [[ ! -x "$TAILWIND_BIN" ]]; then
  echo "Downloading Tailwind CLI $TAILWIND_VERSION"
  curl -fsSL -o "$TAILWIND_BIN.tmp" \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64"
  chmod +x "$TAILWIND_BIN.tmp"
  mv "$TAILWIND_BIN.tmp" "$TAILWIND_BIN"
fi

echo "Downloading HTMX $HTMX_VERSION"
curl -fsSL -o "$STATIC/htmx.min.js.tmp" \
  "https://cdn.jsdelivr.net/npm/htmx.org@${HTMX_VERSION}/dist/htmx.min.js"
mv "$STATIC/htmx.min.js.tmp" "$STATIC/htmx.min.js"

echo "Building app.css"
"$TAILWIND_BIN" -i "$STATIC/tailwind.input.css" -o "$STATIC/app.css" --minify

echo "Done"
