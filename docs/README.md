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

## Quick Start

```bash
git clone https://github.com/KevClint/Kevlarbot-AI.git
cd Kevlarbot-AI
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.env config.env
python bot.py
```

### Docker

```bash
git clone https://github.com/KevClint/Kevlarbot-AI.git
cd Kevlarbot-AI
docker compose up -d --build
```

> **New?** Follow the full [Setup Guide](setup.md) for detailed installation, configuration, and troubleshooting instructions.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `ADMIN_IDS` | No | Comma-separated Telegram user IDs |
| `GROQ_API_KEY` | No | For Llama, GPT-OSS models |
| `HF_API_KEY` | No | For Gemma, Qwen, Mistral models |
| `MIMO_API_KEY` | No | For MiMo V2.5 model |

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

## Free Models (in telegram bot only)

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

## License

[MIT](LICENSE)
