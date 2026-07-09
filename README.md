<div align="center">

# Kevlarbot AI

**Multi-provider AI chatbot for Telegram**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## Features

- 6 free AI models (MiMo, Llama, Gemma, Qwen, Mistral, GPT-OSS)
- BYOK support for OpenRouter, DeepSeek, and Claude
- 5 personas: Default, Coder, Translator, Pirate, Tutor
- Session memory with persistent chat history
- Encrypted API keys (Fernet)
- Rate limiting (2s cooldown, 100 msgs/day)
- Admin tools: broadcast & stats
- Docker secrets for secure API key management

## Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/KevClint/Kevlarbot-AI.git
cd Kevlarbot-AI

# Create secrets directory and add your keys
mkdir -p secrets
echo "YOUR_TELEGRAM_TOKEN" > secrets/telegram_token
echo "YOUR_MIMO_API_KEY" > secrets/mimo_api_key
echo "YOUR_GROQ_API_KEY" > secrets/groq_api_key
echo "YOUR_HF_API_KEY" > secrets/hf_api_key
echo "YOUR_ADMIN_ID" > secrets/admin_ids
echo "YOUR_ENCRYPTION_KEY" > secrets/encryption_key

# Run from the parent directory (D:\Docker)
docker compose up -d --build
```

### Local Development

```bash
git clone https://github.com/KevClint/Kevlarbot-AI.git
cd Kevlarbot-AI
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
python bot.py
```

> **New?** Follow the full [Setup Guide](docs/setup.md) for detailed installation, configuration, and troubleshooting instructions.

## Docker Secrets

API keys are stored as Docker secrets (individual files in `secrets/`), not in a single config file.

### Secret Files

| File | Description |
|------|-------------|
| `secrets/telegram_token` | Bot token from @BotFather |
| `secrets/mimo_api_key` | MiMo V2.5 API key |
| `secrets/groq_api_key` | Groq API key (Llama, GPT-OSS) |
| `secrets/hf_api_key` | HuggingFace API key (Gemma, Qwen, Mistral) |
| `secrets/admin_ids` | Comma-separated Telegram user IDs |
| `secrets/encryption_key` | Fernet key for encrypting user-stored keys |

### Changing a Key

```powershell
# Edit the secret file
notepad D:\Docker\kevlarbot\secrets\groq_api_key

# Restart the container
docker compose restart kevlarbot
```

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

## Free Models

| Key | Model | Provider |
|-----|-------|----------|
| `gemma-2b` | Gemma 2 2B | HuggingFace |
| `qwen-3b` | Qwen2.5 3B | HuggingFace |
| `llama-8b` | Llama 3.1 8B | Groq |
| `mistral-nemo` | Mistral Nemo 12B | HuggingFace |
| `gpt-oss` | GPT-OSS 20B | Groq |
| `mimo` | MiMo V2.5 | MiMo |

## Personas

| Key | Name | Behavior |
|-----|------|----------|
| `default` | Default Assistant | General-purpose helpful AI |
| `coder` | Expert Coder | Senior engineer, precise code |
| `translator` | English Translator | Translate to clear English |
| `pirate` | Sarcastic Pirate | Correct answers, pirate character |
| `tutor` | Academic Tutor | Step-by-step explanations |

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

## License

[MIT](LICENSE)
