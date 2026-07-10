# AGENTS.md — KevlarBot AI

Multi-provider AI chatbot for Telegram. Python 3.11+, `python-telegram-bot`, SQLite, async.

## Commands

```bash
# Lint & format (Ruff only — no Black, no Prettier)
python -m ruff format .
python -m ruff check --fix .

# Run locally
python -m venv venv && .\venv\Scripts\Activate.ps1  # Windows
pip install -e .
python bot.py

# Deploy (from parent directory D:\Docker, NOT from kevlarbot/)
docker compose up -d --build

# View logs
docker compose logs -f kevlarbot
```

## Architecture

- **Entrypoint:** `bot.py` → calls `kevlarbot.handlers.main()`
- **`KevlarBot`** (`handlers/__init__.py`) inherits 5 mixins: `HelpHandlers`, `SettingsHandlers`, `ModelHandlers`, `ChatHandlers`, `AdminHandlers`, `KevlarBotBase`
- New Telegram commands go in the appropriate mixin file under `src/kevlarbot/handlers/`, then get registered in `handlers/__init__.py:60-88`
- **Providers** (`providers.py`): `AI_PROVIDERS` dict defines free models; `PERSONAS` dict defines 7 personas (README says 5 — it's outdated)
- **AI client** (`ai_client.py`): OpenAI-compatible and Anthropic request paths; `max_tokens: 256` hardcoded
- **Database** (`database.py`): SQLite via `aiosqlite`, single `users_v3` table, auto-migrates columns on startup
- **Config** (`config.py`): env vars loaded at import time via `os.getenv()`; `Fernet` encryption for stored API keys
- **Docker entrypoint** reads `/run/secrets/*` files into env vars — no `.env` file is used

## Gotchas

- **Docker build context is `D:\Docker`**, not `kevlarbot/`. The `docker-compose.yml` lives at `D:\Docker/docker-compose.yml` and mounts `./kevlarbot/src:/app/src` for live code reload without rebuild.
- **Secrets** are individual files in `secrets/` (gitignored), not env vars or `.env`. Each file contains only the value.
- **`ENCRYPTION_KEY`** must be persisted in `secrets/encryption_key`. Without it, a random key is generated each restart and all user-stored API keys break.
- **No tests exist** — `tests/` is empty. Don't assume test infrastructure is in place.
- **Rate limits** are hardcoded in `base.py:21-23`: `max_history=15`, `min_interval=2.0s`, `daily_limit=100`.
- **Provider fallback** tries primary model then all free models. A 400 error is logged and skipped, not fatal.
- **Handler registration order matters** — `ConversationHandler` (admin conv) must be added before the catch-all `MessageHandler` at line 88.
- **Inline queries** use a separate code path (`inline_query_handler` in `chat.py`) with `/chat` prefix.
