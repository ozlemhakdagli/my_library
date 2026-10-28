# Local LLM Assistant (LM Studio)

Date: 2026-10-24
Status: Draft, implementing on owner request ("4 ve 7 yi yap")

## 1. Scope

Three features, all using a local model through LM Studio's OpenAI-compatible server. No data leaves the machine.

1. **Ask (`/ask`):** a natural-language question about the library ("Ahmet Ümit'ten okumadığım kitaplar?"). The model turns the question into search filters; the app runs the normal search; the model writes a short answer using only the returned records.
2. **Suggestions (book page):** "Benzer kitap öner" returns up to 5 suggestions based on the book's title, authors, and types. Each suggestion shows whether it is already in the library. Suggestions are never saved.
3. **Metadata completion (edit page):** "Öneri al" suggests subtitle and publisher for a book with missing fields. The owner applies suggestions to the form; nothing is saved automatically.

Out of scope: writing to the database from model output, web search, cover generation.

## 2. Configuration

- `LIBRARY_LLM_URL` default `http://host.docker.internal:1234/v1`
- `LIBRARY_LLM_MODEL` default empty (the server uses the loaded model)
- `LIBRARY_LLM_TIMEOUT` default 60 seconds
- Docker: `extra_hosts: ["host.docker.internal:host-gateway"]` so the container reaches LM Studio on the host.

If the server is not reachable or returns an error, the pages show a clear message and keep working.

## 3. Client

- Plain `httpx` against `POST {url}/chat/completions` (OpenAI-compatible JSON). No SDK.
- The client is created by a factory so tests inject a fake transport. Tests do not need LM Studio.
- Responses are parsed defensively: extract the first JSON object, validate types, drop unknown keys, cap list lengths.

## 4. Safety rules

- Model output never writes to the database.
- Only library data already visible to the owner is sent to the model.
- Filters from the model are whitelisted (`q`, `shelf`, `type`, `status`, `needs_review`) and passed to the same search code as the normal list.
- Prompts ask for JSON only and in the requested language (EN/TR per the UI language).

## 5. Testing

- Unit: JSON extraction, filter whitelisting, suggestion validation, "already in library" matching via `norm()`.
- Web: `/ask` with fake transport returns filtered results and answer; unreachable server shows the message and HTTP 200; book page suggestions render; edit page suggestions do not change the book until the form is saved.
- Live check (manual, when LM Studio runs): one question against the real library.
