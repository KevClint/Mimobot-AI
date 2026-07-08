# MiMoBot AI Setup Guide

This page contains detailed install, configuration, and troubleshooting notes.

## Quick Start

### Docker (Recommended)

Clone the repo, configure your keys, and run with Docker:

```bash
git clone https://github.com/KevClint/Mimobot-AI.git
cd Mimobot-AI
copy config.example.env config.env
# Edit config.env with your keys, then:
docker compose up -d --build mimobot
```

### Manual

Clone the repo, create a virtual environment, install dependencies, configure your keys, and run the bot.

```bash
git clone https://github.com/KevClint/Mimobot-AI.git
cd Mimobot-AI
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
pip install -r requirements.txt
copy config.example.env config.env
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
3. Enter a **name** for your bot (e.g., `MiMoBot`)
4. Enter a **username** for your bot (must end in `bot`, e.g., `MiMoAI_bot`)
5. BotFather will give you a token like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
6. Copy this token — you'll need it for `config.env`

---

## Step 2: Get Your Telegram User ID

1. Open Telegram and search for **@userinfobot**
2. Send any message to it
3. It will reply with your user ID (a number like `123456789`)
4. Copy this number — you'll need it for `ADMIN_IDS`

> This gives you admin access to use `/stats` and `/broadcast` commands.

---

## Step 3: Get API Keys (Optional)

MiMoBot works out of the box with free models, but you can add your own keys for more options:

### HuggingFace (for Gemma, Qwen, Mistral)

1. Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Create a new token
3. Copy the token for `HF_API_KEY`

### Groq (for Llama, GPT-OSS)

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up / log in
3. Go to **API Keys** and create one
4. Copy the key for `GROQ_API_KEY`

### MiMo (for MiMo V2.5)

1. Go to [api.xiaomimimo.com](https://api.xiaomimimo.com)
2. Sign up / log in
3. Create an API key
4. Copy the key for `MIMO_API_KEY`

### OpenRouter / DeepSeek / Claude (BYOK)

Users can add their own keys via the `/setkey` command in Telegram. No server-side setup needed.

---

## Step 4: Configure Environment

Copy the example config and fill in your values:

```bash
copy config.example.env config.env
```

Open `config.env` and edit:

```env
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_IDS=123456789
GROQ_API_KEY=gsk_...
HF_API_KEY=hf_...
MIMO_API_KEY=...
ENCRYPTION_KEY=...
```

### Generate Encryption Key (Optional)

If you want a persistent encryption key for API keys stored by users:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output into `ENCRYPTION_KEY` in `config.env`.

> If you skip this, a random key is generated on each restart — existing saved API keys will stop working.

---

## Step 5: Run the Bot

### Docker (Recommended)

```bash
cd D:\Docker
docker compose up -d --build mimobot
```

To view logs:

```bash
docker compose logs -f mimobot
```

To stop:

```bash
docker compose stop mimobot
```

### Manual

```bash
python bot.py
```

You should see:

```
Bot started polling...
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
pip install -r requirements.txt
```

### Run

You need to activate the venv each time you open a new terminal:

```powershell
cd D:\Docker\mimobot
.\venv\Scripts\Activate.ps1
python bot.py
```

Or run directly without activating:

```powershell
D:\Docker\mimobot\venv\Scripts\python.exe bot.py
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
pip install -r requirements.txt
```

### Run

You need to activate the venv each time you open a new terminal:

```bash
cd ~/Mimobot-AI
source venv/bin/activate
python bot.py
```

Or run directly without activating:

```bash
~/Mimobot-AI/venv/bin/python bot.py
```

---

## Configuration Reference

### Rate Limits (in `src/mimobot/handlers.py`)

Edit these values in the `MimoAIBot.__init__` method:

```python
self.max_history = 10      # Messages kept in context
self.min_interval = 2.0    # Seconds between messages per user
self.daily_limit = 100     # Max messages per user per day
```

### Telegram Message Limit (in `src/mimobot/config.py`)

```python
TELEGRAM_MSG_LIMIT = 4000  # Max characters per message
```

### OpenRouter Settings (in `src/mimobot/config.py`)

```python
OR_PAGE_SIZE = 8       # Models per page when browsing
OR_CACHE_TTL = 3600    # Cache duration in seconds
```

---

## Adding a New Provider

In `src/mimobot/providers.py`, add a new entry to `AI_PROVIDERS`:

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

Then add the API key to `config.env`:

```env
MY_API_KEY=your_key_here
```

---

## Adding a New Persona

In `src/mimobot/providers.py`, add a new entry to `PERSONAS`:

```python
"my-persona": {
    "label": "My Custom Persona",
    "prompt": "You are a helpful assistant that..."
},
```

Users can then select it with `/persona` in Telegram.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `ADMIN_IDS` | No | Comma-separated Telegram user IDs |
| `ENCRYPTION_KEY` | No | Persistent key for API key encryption |
| `GROQ_API_KEY` | No | For Llama, GPT-OSS models |
| `HF_API_KEY` | No | For Gemma, Qwen, Mistral models |
| `MIMO_API_KEY` | No | For MiMo V2.5 model |

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

- Check `TELEGRAM_TOKEN` is correct in `config.env`
- Make sure `python bot.py` is running
- Check if the bot was stopped with `/stop` in Telegram

### "Not authorized" on admin commands

- Make sure your `ADMIN_IDS` matches your Telegram user ID
- Use @userinfobot to get your correct ID

### API errors

- Verify your API keys are valid
- Check if you've exceeded rate limits
- Try a different model with `/model`

### Saved API keys stop working after restart

- You need a persistent `ENCRYPTION_KEY` in `config.env`
- Generate one with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### Virtual environment issues (Windows)

If `.\venv\Scripts\Activate.ps1` doesn't work:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venv\Scripts\Activate.ps1
```

### Module not found errors

Make sure you're in the project root directory and the virtual environment is activated.

### Docker build fails

Make sure Docker Desktop is running and you're in the correct directory:

```bash
cd D:\Docker
docker compose up -d --build mimobot
```

### Container keeps restarting

Check the logs for errors:

```bash
docker compose logs mimobot
```

Common issues:
- Missing `config.env` file
- Invalid `TELEGRAM_TOKEN`
- Port conflicts (MimobotAI doesn't use ports, so this is rare)

---

## Project Structure

```
Mimobot-AI/
├── bot.py                  # Entry point
├── Dockerfile              # Docker build file
├── src/
│   └── mimobot/
│       ├── __init__.py
│       ├── handlers.py     # Command & callback handlers
│       ├── ai_client.py    # AI provider client
│       ├── database.py     # SQLite database layer
│       ├── providers.py    # Provider & persona definitions
│       ├── config.py       # Configuration & encryption
│       └── utils.py        # Utility functions
├── docs/
│   ├── README.md
│   └── setup.md
├── config.env              # Environment variables (git-ignored)
├── mimo_bot.db             # SQLite database (git-ignored)
├── requirements.txt
└── LICENSE
```

---

## Security Notes

- Keep `config.env` out of Git — it contains your API keys
- API keys stored by users are encrypted with Fernet encryption
- The `ENCRYPTION_KEY` should be kept secret and backed up
- Do not share your bot token publicly
- Use `ADMIN_IDS` to restrict admin commands to trusted users only
