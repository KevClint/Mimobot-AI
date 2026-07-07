from typing import Dict, Any

AI_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "smollm3": {
        "name": "SmolLM3 3B (Free)",
        "url": "https://api-inference.huggingface.co/v1/chat/completions",
        "model_id": "HuggingFaceTB/SmolLM3-3B",
        "is_free": True,
        "env_key": "HF_API_KEY",
        "group": "huggingface"
    },
    "llama": {
        "name": "Llama 3.3 70B (Free)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "llama-3.3-70b-versatile",
        "is_free": True,
        "env_key": "GROQ_API_KEY",
        "group": "groq"
    },
    "qwen": {
        "name": "Qwen 3.6 27B (Free)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "qwen/qwen3.6-27b",
        "is_free": True,
        "env_key": "GROQ_API_KEY",
        "group": "groq"
    },
    "gpt-oss": {
        "name": "GPT-OSS 20B (Free)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "openai/gpt-oss-20b",
        "is_free": True,
        "env_key": "GROQ_API_KEY",
        "group": "groq"
    },
    "mimo": {
        "name": "MiMo V2.5 (Free)",
        "url": "https://api.xiaomimimo.com/v1/chat/completions",
        "model_id": "mimo-v2.5",
        "is_free": True,
        "env_key": "MIMO_API_KEY",
        "group": "mimo"
    },
}

PERSONAS: Dict[str, Dict[str, str]] = {
    "default":    {"label": "Default Assistant",    "prompt": "You are a highly helpful and intelligent AI assistant."},
    "coder":      {"label": "Expert Coder",          "prompt": "You are a senior software engineer. Give precise, correct, production-quality code with brief explanations."},
    "translator": {"label": "English Translator",    "prompt": "You are a professional translator. Translate whatever the user sends into clear, natural English, preserving tone and meaning."},
    "pirate":     {"label": "Sarcastic Pirate",      "prompt": "You are a sarcastic pirate captain. Answer correctly but stay in pirate character with dry wit."},
    "tutor":      {"label": "Academic Tutor",        "prompt": "You are a patient academic tutor. Explain concepts step by step, check understanding, and use simple examples."},
}
DEFAULT_PERSONA = "default"

BROWSE_GROUPS: Dict[str, Dict[str, str]] = {
    "openrouter": {"name": "OpenRouter API", "url": "https://openrouter.ai/api/v1/chat/completions"},
    "deepseek":   {"name": "DeepSeek API",   "url": "https://api.deepseek.com/v1/chat/completions"},
    "claude":     {"name": "Claude API",      "url": "https://api.anthropic.com/v1/messages"},
}
ANTHROPIC_GROUPS = {"claude"}

for _g in BROWSE_GROUPS.values():
    _g["label"] = _g["name"]
    _g["chat_url"] = _g["url"]
    _g["models_url"] = _g["url"].replace("/chat/completions", "/models").replace("/messages", "/models")
