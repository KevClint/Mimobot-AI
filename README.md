<div align="center">

# MiMoBot AI

**A multi-provider AI assistant for Telegram**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

</div>

---

## Features

- **Multi-Provider AI** — Free models via Groq, HuggingFace, and MiMo, plus BYOK support for OpenRouter, DeepSeek, and Claude
- **Model Browsing** — Browse and select from hundreds of hosted models via API
- **Personas** — Switch between Default, Expert Coder, Translator, Pirate, and Tutor personalities
- **Session Memory** — Persistent chat history with configurable context window
- **BYOK Encryption** — Your API keys are encrypted at rest with Fernet
- **Rate Limiting** — Per-user cooldowns and daily message limits
- **Fallback Chains** — Automatic failover between providers on rate limits or errors
- **Admin Tools** — Broadcast messages and view user stats

## Free Models

| Key | Model | Provider |
|-----|-------|----------|
| `gemma-2b` | Gemma 2 2B | HuggingFace |
| `qwen-3b` | Qwen2.5 3B | HuggingFace |
| `llama-8b` | Llama 3.1 8B | Groq |
| `mistral-nemo` | Mistral Nemo 12B | HuggingFace |
| `gpt-oss` | GPT-OSS 20B | Groq |
| `mimo` | MiMo V2.5 | MiMo |


## Quick Start

### 1. Clone

```bash
git clone https://github.com/yourusername/mimobot-ai.git
cd mimobot-ai
```

### 2. Install dependencies

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
pip install -r requirements.txt
```

### 3. Configure

Copy `config.example.env` to `config.env` and fill in your keys:

```env
TELEGRAM_TOKEN=your_bot_token
ADMIN_IDS=your_telegram_id
GROQ_API_KEY=gsk_...
```

### 4. Run

```bash
python bot.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/new` | Clear memory, keep keys and model |
| `/model` | Switch AI engine or browse hosted models |
| `/persona` | Change assistant behavior |
| `/setkey <provider> <key>` | Save a BYOK API key |
| `/info` | View your dashboard |
| `/session` | View current session details |
| `/retry` | Regenerate last response |
| `/cancel` | Cancel in-progress request |
| `/help` | Help menu |

**Admin only:**

| Command | Description |
|---------|-------------|
| `/stats` | View registered user count |
| `/broadcast <message>` | Send message to all users |

## Personas

| Key | Name | Behavior |
|-----|------|----------|
| `default` | Default Assistant | General-purpose helpful AI |
| `coder` | Expert Coder | Senior engineer, precise code |
| `translator` | English Translator | Translate to clear English |
| `pirate` | Sarcastic Pirate | Correct answers, pirate character |
| `tutor` | Academic Tutor | Step-by-step explanations |

## Tech Stack

- **Python 3.11+**
- **python-telegram-bot** — Telegram Bot API
- **aiosqlite** — Async SQLite
- **httpx** — Async HTTP client
- **cryptography** — Fernet encryption for API keys
- **python-dotenv** — Environment config

## Project Structure

```
mimobot-ai/
├── bot.py           # Entry point
├── handlers.py      # Command & callback handlers
├── ai_client.py     # AI provider client
├── database.py      # SQLite database layer
├── providers.py     # Provider & persona definitions
├── config.py        # Configuration & encryption
├── utils.py         # Utility functions
├── config.env       # Environment variables (git-ignored)
└── mimo_bot.db      # SQLite database (git-ignored)
```

## License

MIT
