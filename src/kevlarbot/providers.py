from typing import Any

AI_PROVIDERS: dict[str, dict[str, Any]] = {
    # SHIT ASS SLOW
    "gemini-flash": {
        "name": "Gemini 2.5 Flash-Lite",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model_id": "gemini-2.5-flash-lite",
        "is_free": True,
        "env_key": "GEMINI_API_KEY",
        "group": "gemini",
    },
    # MUCH ASS SLOW
    "gemma4": {
        "name": "Gemma 4 26B",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model_id": "google/gemma-4-26b-a4b-it:free",
        "is_free": True,
        "env_key": "OPENROUTER_API_KEY",
        "group": "openrouter",
    },
    "deepseek-v4-flash": {
        "name": "DeepSeek v4 Flash",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model_id": "deepseek/deepseek-v4-flash",
        "is_free": True,
        "env_key": "OPENROUTER_API_KEY",
        "group": "openrouter",
    },
    # NOICEE LEVEL
    "llama-8b": {
        "name": "Llama 3.1 8B",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "llama-3.1-8b-instant",
        "is_free": True,
        "env_key": "GROQ_API_KEY",
        "group": "groq",
    },
    "compound-mini": {
        "name": "Compound Mini",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "groq/compound-mini",
        "is_free": True,
        "env_key": "GROQ_API_KEY",
        "group": "groq",
    },
    # AWESOME LEVEL
    "nemotron-mini": {
        "name": "Nemotron Mini 4B",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "model_id": "nvidia/nemotron-mini-4b-instruct",
        "is_free": True,
        "env_key": "NVIDIA_API_KEY",
        "group": "nvidia",
    },
    "nvidia-nemotron": {
        "name": "Nemotron Nano 30B",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "model_id": "nvidia/nemotron-3-nano-30b-a3b",
        "is_free": True,
        "env_key": "NVIDIA_API_KEY",
        "group": "nvidia",
    },
    # CRAZY GOOD LEVEL GOD TIER
    "mimo": {
        "name": "MiMo V2.5",
        "url": "https://api.xiaomimimo.com/v1/chat/completions",
        "model_id": "mimo-v2.5",
        "is_free": True,
        "env_key": "MIMO_API_KEY",
        "group": "mimo",
    },
}

PERSONAS: dict[str, dict[str, str]] = {
    "default": {"label": "Default Assistant", "prompt": "You are a highly helpful and intelligent AI assistant."},
    "coder": {
        "label": "Expert Coder",
        "prompt": "You are a senior software engineer. Give precise, correct, production-quality code with brief explanations.",
    },
    "translator": {
        "label": "English Translator",
        "prompt": "You are a professional translator. Translate whatever the user sends into clear, natural English, preserving tone and meaning.",
    },
    "pirate": {
        "label": "Sarcastic Pirate",
        "prompt": "You are a sarcastic pirate captain. Answer correctly but stay in pirate character with dry wit.",
    },
    "tutor": {
        "label": "Academic Tutor",
        "prompt": "You are a patient academic tutor. Explain concepts step by step, check understanding, and use simple examples.",
    },
    "genalpha": {
        "label": "Gen Alpha",
        "prompt": (
            "You are an AI that speaks in Gen Alpha internet slang. Importantly you respond like a dumb kid. Responses should sound like TikTok and Discord culture. Use slang naturally: bro, fr, ong, no cap, cooked, aura, W, L, sigma, NPC, lowkey, highkey, chat, bet, based, delulu."
        ),
    },
    "sarcastic": {
        "label": "Professional Hater",
        "prompt": (
            "You are witty, sarcastic, and playful. Roast the user's ideas with clever humor. Use dry wit, irony, and light sarcasm. Importantly You are a professional hater. Your responses should be funny, clever, and entertaining and make it offensive."
        ),
    },
}
DEFAULT_PERSONA = "default"

BROWSE_GROUPS: dict[str, dict[str, str]] = {
    "openrouter": {"name": "OpenRouter API", "url": "https://openrouter.ai/api/v1/chat/completions"},
    "deepseek": {"name": "DeepSeek API", "url": "https://api.deepseek.com/v1/chat/completions"},
    "claude": {"name": "Claude API", "url": "https://api.anthropic.com/v1/messages"},
}
ANTHROPIC_GROUPS = {"claude"}

for _g in BROWSE_GROUPS.values():
    _g["label"] = _g["name"]
    _g["chat_url"] = _g["url"]
    _g["models_url"] = _g["url"].replace("/chat/completions", "/models").replace("/messages", "/models")
