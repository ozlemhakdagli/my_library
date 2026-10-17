# Personal Library

A single-user personal book library web app. It runs on your own computer in Docker, and your data never leaves it. The UI is available in English and Turkish.

## Setup

1. Copy the example environment file and set the path to your raw data folder (read-only inside the container):

   ```bash
   cp .env.example .env
   ```

   `.env` is not committed. `LIBRARY_RAW_DIR` defaults to `./data/raw`.

2. Start the app from the project directory:

   ```bash
   docker compose up -d --build
   ```

3. Open http://localhost:8765 in your browser.

## Language

English is the default. Switch to Turkish with `?lang=tr`, for example http://localhost:8765/?lang=tr. The choice is remembered in a cookie named `lang`. Use `?lang=en` to switch back.

## Importing the raw data

The one-time import reads the `*.jsonl` files from the mounted raw folder and writes into the `library-data` volume. It is safe to run again: existing books are not duplicated, and the script fails without writing anything if the counts differ from the expected ones (431 books, 78 review items, 410 photos).

```bash
bash scripts/import_books.sh
```

## Backups

Use the Settings page (http://localhost:8765/settings) and press the backup button. Backups are written inside the volume to `/data/backups`. To copy them to the host:

```bash
docker compose cp library:/data/backups ./backups
```

## Stopping

```bash
docker compose down
```

This keeps the `library-data` volume, so your data is preserved. Do not add `-v`, which deletes the volume.

## Tests

```bash
.venv/bin/python -m pytest -v
bash tests/test_smoke.sh   # needs Docker; builds and checks the running app
```
