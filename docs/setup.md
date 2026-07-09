# Kevlarbot AI Setup Guide

This page contains detailed install, configuration, and troubleshooting notes.

## Quick Start

### Docker (Recommended)

Clone the repo, create your secrets, and run:

```bash
git clone https://github.com/KevClint/Kevlarbot-AI.git
cd Kevlarbot-AI

# Create secrets directory
mkdir -p secrets

# Add your keys (one value per file)
echo "YOUR_TELEGRAM_TOKEN" > secrets/telegram_token
echo "YOUR_ADMIN_ID" > secrets/admin_ids
echo "YOUR_ENCRYPTION_KEY" > secrets/encryption_key
```

Then run from the parent directory (`D:\Docker`):

```bash
docker compose up -d --build
```

### Manual

Clone the repo, create a virtual environment, install dependencies, and run:

```bash
git clone https://github.com/KevClint/Kevlarbot-AI.git
cd Kevlarbot-AI
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
pip install -e .
python bot.py
```

---

## Prerequisites

- Python 3.11 or higher (manual install only)
- Docker Desktop (for Docker setup)
- A Telegram account
- (Optional) API keys for additional models

---

## Step 1: Get Telegram Bot Token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Enter a **name** for your bot (e.g., `KevlarBot AI`)
4. Enter a **username** for your bot (must end in `bot`, e.g., `KevlarBot`)
5. BotFather will give you a token like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
6. Copy this token — you'll need it for `secrets/telegram_token`

---

## Step 2: Get Your Telegram User ID

1. Open Telegram and search for **@userinfobot**
2. Send any message to it
3. It will reply with your user ID (a number like `123456789`)
4. Copy this number — you'll need it for `secrets/admin_ids`

> This gives you admin access to use `/stats` and `/broadcast` commands.

---

## Step 3: Get API Keys (Optional)

KevlarBot AI works out of the box with free models (only in telegram bot, if you are using it locally u need the API keys), but you can add your own keys for more options:

### HuggingFace (for Gemma, Qwen, Mistral)

1. Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Create a new token
3. Copy the token for `secrets/hf_api_key`

### Groq (for Llama, GPT-OSS)

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up / log in
3. Go to **API Keys** and create one
4. Copy the key for `secrets/groq_api_key`

### MiMo (for MiMo V2.5)

1. Go to [api.xiaomimimo.com](https://api.xiaomimimo.com)
2. Sign up / log in
3. Create an API key
4. Copy the key for `secrets/mimo_api_key`

### OpenRouter / DeepSeek / Claude (BYOK)

Users can add their own keys via the `/setkey` command in Telegram. No server-side setup needed.

---

## Step 4: Configure Secrets

### Docker Setup

Create individual secret files in the `secrets/` directory. Each file contains **only the value** — no variable name, no comments:

```bash
mkdir -p secrets
echo "123456789:ABCdefGHIjklMNOpqrsTUVwxyz" > secrets/telegram_token
echo "123456789" > secrets/admin_ids
echo "gsk_..." > secrets/groq_api_key
echo "hf_..." > secrets/hf_api_key
echo "sk-..." > secrets/mimo_api_key
```

### Generate Encryption Key (Optional)

If you want a persistent encryption key for API keys stored by users:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save the output to `secrets/encryption_key`.

> If you skip this, a random key is generated on each restart — existing saved API keys will stop working.

### Changing Keys

To update a key, edit the file and restart the container:

```powershell
notepad D:\Docker\kevlarbot\secrets\groq_api_key
# edit value, save
docker compose restart kevlarbot
```

---

## Step 5: Run the Bot

### Docker (Recommended)

```bash
docker compose up -d --build
```

To view logs:

```bash
docker compose logs -f kevlarbot
```

To stop:

```bash
docker compose stop kevlarbot
```

### Manual

```bash
python bot.py
```

You should see:

```
KevlarBot AI initialized.
Application started
```

Open Telegram, find your bot, and send `/start`.

---

## Windows Setup (PowerShell)

### Create Virtual Environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If you get an execution policy error:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Install Dependencies

```powershell
pip install -e .
```

### Run

You need to activate the venv each time you open a new terminal:

```powershell
cd Kevlarbot-AI
.\venv\Scripts\Activate.ps1
python bot.py
```

Or run directly without activating:

```powershell
.\venv\Scripts\python.exe bot.py
```

---

## Linux / macOS Setup

### Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -e .
```

### Run

You need to activate the venv each time you open a new terminal:

```bash
cd ~/Kevlarbot-AI
source venv/bin/activate
python bot.py
```

Or run directly without activating:

```bash
~/Kevlarbot-AI/venv/bin/python bot.py
```

---

## Configuration Reference

### Rate Limits (in `src/kevlarbot/handlers/base.py`)

Edit these values in the `KevlarBotBase.__init__` method:

```python
self.max_history = 10      # Messages kept in context
self.min_interval = 2.0    # Seconds between messages per user
self.daily_limit = 100     # Max messages per user per day
```

### Telegram Message Limit (in `src/kevlarbot/config.py`)

```python
TELEGRAM_MSG_LIMIT = 4000  # Max characters per message
```

### OpenRouter Settings (in `src/kevlarbot/config.py`)

```python
OR_PAGE_SIZE = 8       # Models per page when browsing
OR_CACHE_TTL = 3600    # Cache duration in seconds
```

---

## Adding a New Provider

In `src/kevlarbot/providers.py`, add a new entry to `AI_PROVIDERS`:

```python
"my-model": {
    "name": "My Model (Free)",
    "url": "https://api.example.com/v1/chat/completions",
    "model_id": "model-name-here",
    "is_free": True,
    "env_key": "MY_API_KEY",
    "group": "mygroup"
},
```

Then create a secret file:

```bash
echo "your_key_here" > secrets/my_api_key
```

---

## Adding a New Persona

In `src/kevlarbot/providers.py`, add a new entry to `PERSONAS`:

```python
"my-persona": {
    "label": "My Custom Persona",
    "prompt": "You are a helpful assistant that..."
},
```

Users can then select it with `/persona` in Telegram.

---

## Docker Secrets

| Secret File | Required | Description |
|-------------|----------|-------------|
| `secrets/telegram_token` | Yes | Bot token from @BotFather |
| `secrets/admin_ids` | No | Comma-separated Telegram user IDs |
| `secrets/encryption_key` | No | Persistent key for API key encryption |
| `secrets/groq_api_key` | No | For Llama, GPT-OSS models |
| `secrets/hf_api_key` | No | For Gemma, Qwen, Mistral models |
| `secrets/mimo_api_key` | No | For MiMo V2.5 model |

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/new` | Clear memory, keep keys & model |
| `/model` | Switch AI engine |
| `/persona` | Change assistant behavior |
| `/setkey <provider> <key>` | Save BYOK API key |
| `/info` | View dashboard |
| `/session` | View current session |
| `/retry` | Regenerate last response |
| `/cancel` | Cancel in-progress request |
| `/help` | Help menu |
| `/stats` | View user count *(admin)* |
| `/broadcast <msg>` | Send to all users *(admin)* |

---

## Troubleshooting

### Bot doesn't respond

- Check `TELEGRAM_TOKEN` is correct in `secrets/telegram_token`
- Make sure `python bot.py` is running (or container is up with `docker compose ps`)
- Check if the bot was stopped with `/stop` in Telegram

### "Not authorized" on admin commands

- Make sure your `ADMIN_IDS` matches your Telegram user ID
- Use @userinfobot to get your correct ID

### API errors

- Verify your API keys are valid
- Check if you've exceeded rate limits
- Try a different model with `/model`

### Saved API keys stop working after restart

- You need a persistent `ENCRYPTION_KEY` in `secrets/encryption_key`
- Generate one with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### Virtual environment issues (Windows)

If `.\venv\Scripts\Activate.ps1` doesn't work:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venv\Scripts\Activate.ps1
```

### Module not found errors

Make sure you're in the project root directory and the virtual environment is activated. If using `pip install -e .`, the package should be importable.

### Docker build fails

Make sure Docker Desktop is running and you're in the parent directory (`D:\Docker`):

```bash
docker compose up -d --build
```

### Container keeps restarting

Check the logs for errors:

```bash
docker compose logs kevlarbot
```

Common issues:
- Missing secret files in `secrets/` directory
- Invalid `TELEGRAM_TOKEN`
- Container name conflict — ensure `container_name: kevlarbot` is in `docker-compose.yml`

---

## Project Structure

```
kevlarbot/
├── bot.py                  # Entry point
├── pyproject.toml          # Build config & dependencies
├── Dockerfile
├── docker-entrypoint.sh    # Reads Docker secrets, exports env vars
├── secrets/                # Docker secrets (gitignored)
│   ├── telegram_token
│   ├── mimo_api_key
│   ├── groq_api_key
│   ├── hf_api_key
│   ├── admin_ids
│   └── encryption_key
├── src/
│   └── kevlarbot/
│       ├── __init__.py
│       ├── handlers/       # Command & callback handlers
│       │   ├── __init__.py
│       │   ├── base.py     # Shared state & helpers
│       │   ├── admin.py    # Admin panel & user management
│       │   ├── chat.py     # AI chat & inline queries
│       │   ├── models.py   # Model selection & BYOK
│       │   ├── settings.py # Settings & persona
│       │   └── help.py     # Help menu
│       ├── ai_client.py    # AI provider client
│       ├── database.py     # SQLite database layer
│       ├── providers.py    # Provider & persona definitions
│       ├── config.py       # Configuration & encryption
│       └── utils.py        # Utility functions
├── tests/
├── docs/
│   └── setup.md
└── LICENSE
```

---

## Security Notes

- API keys are stored as Docker secrets in `secrets/` (gitignored)
- Each secret is a separate file containing only the value
- API keys stored by users are encrypted with Fernet encryption
- The `ENCRYPTION_KEY` should be kept secret and backed up
- Do not share your bot token publicly
- Use `ADMIN_IDS` to restrict admin commands to trusted users only
