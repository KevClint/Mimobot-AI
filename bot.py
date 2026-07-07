import os
import time
import json
import asyncio
import logging
import httpx
import aiosqlite
from typing import List, Dict, Tuple, Any
from dotenv import load_dotenv

from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest

# FREE AI MODELS thats already configured in config.env cuz why not lmao
AI_PROVIDERS = {
    "mimo": {
        "name": "MiMo V2.5 (Free)",
        "url": "https://api.xiaomimimo.com/v1/chat/completions",
        "model_id": "mimo-v2.5",
        "is_free": True,
        "env_key": "MIMO_API_KEY",
        "group": "mimo"
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
    }
}

# ==========================================
# 2. PERSONAS
# ==========================================
PERSONAS = {
    "default":  {"label": "Default Assistant",   "prompt": "You are a highly helpful and intelligent AI assistant."},
    "coder":    {"label": "Expert Coder",         "prompt": "You are a senior software engineer. Give precise, correct, production-quality code with brief explanations."},
    "translator": {"label": "English Translator", "prompt": "You are a professional translator. Translate whatever the user sends into clear, natural English, preserving tone and meaning."},
    "pirate":   {"label": "Sarcastic Pirate",     "prompt": "You are a sarcastic pirate captain. Answer correctly but stay in pirate character with dry wit."},
    "tutor":    {"label": "Academic Tutor",       "prompt": "You are a patient academic tutor. Explain concepts step by step, check understanding, and use simple examples."},
}
DEFAULT_PERSONA = "default"

# ==========================================
# 3. CONFIGURATION & LOGGING
# ==========================================
load_dotenv("config.env")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_MSG_LIMIT = 4000  # safety margin under Telegram's 4096 cap
OR_PAGE_SIZE = 8
OR_CACHE_TTL = 3600  # seconds

# Providers whose full model list can be browsed once the user sets a key.
# auth: "bearer" -> Authorization: Bearer <key> (OpenAI-style body/response)
#       "anthropic" -> x-api-key + anthropic-version (different body/response)
BROWSE_GROUPS = {
    "openrouter": {"name": "OpenRouter API", "url": "https://openrouter.ai/api/v1/chat/completions"},
    "deepseek": {"name": "DeepSeek API", "url": "https://api.deepseek.com/v1/chat/completions"},
    "claude": {"name": "Claude API", "url": "https://api.anthropic.com/v1/messages"},
}
ANTHROPIC_GROUPS = {"claude"}  # groups needing x-api-key + anthropic-version instead of Bearer

for _g in BROWSE_GROUPS.values():
    _g["label"] = _g["name"]
    _g["chat_url"] = _g["url"]
    _g["models_url"] = _g["url"].replace("/chat/completions", "/models").replace("/messages", "/models")


def make_bar(used: int, total: int, width: int = 10) -> str:
    used = max(0, min(used, total))
    filled = round((used / total) * width) if total else 0
    return "█" * filled + "░" * (width - filled)


# ==========================================
# 4. BOT CLASS
# ==========================================
class MimoAIBot:
    def __init__(self):
        self.max_history = 10
        self.min_interval = 2.0
        self.db_name = "mimo_bot.db"
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.last_msg_time = {}
        self._model_cache = {}  # group -> {"data": [...], "ts": float}

    def resolve_provider(self, active_model: str) -> Dict[str, Any]:
        if active_model in AI_PROVIDERS:
            return AI_PROVIDERS[active_model]
        if ":" in active_model:
            group, model_id = active_model.split(":", 1)
            g = BROWSE_GROUPS.get(group)
            if g:
                return {"name": f"{model_id} ({g['label']})", "url": g["chat_url"],
                        "model_id": model_id, "is_free": False, "group": group}
        return AI_PROVIDERS["mimo"]

    async def get_group_models(self, group: str, api_key: str) -> List[Dict[str, str]]:
        g = BROWSE_GROUPS[group]
        now = time.time()
        cached = self._model_cache.get(group, {"data": [], "ts": 0})
        if cached["data"] and now - cached["ts"] < OR_CACHE_TTL:
            return cached["data"]
        try:
            if group in ANTHROPIC_GROUPS:
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            else:
                headers = {"Authorization": f"Bearer {api_key}"}
            resp = await self.http_client.get(g["models_url"], headers=headers)
            resp.raise_for_status()
            items = resp.json().get("data", [])
            models = [{"id": m["id"], "name": m.get("display_name") or m.get("name", m["id"])} for m in items]
            self._model_cache[group] = {"data": models, "ts": now}
            return models
        except Exception as e:
            logger.error(f"{group} model list fetch failed: {e}")
            return cached["data"]

    # --- DATABASE METHODS ---
    async def init_db(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users_v3 (
                    chat_id INTEGER PRIMARY KEY,
                    history TEXT,
                    active_model TEXT,
                    custom_keys TEXT,
                    persona TEXT DEFAULT 'default',
                    joined_at REAL,
                    last_updated REAL
                )
            ''')
            # migrate older DBs that lack new columns
            cursor = await db.execute("PRAGMA table_info(users_v3)")
            cols = {row[1] for row in await cursor.fetchall()}
            if "persona" not in cols:
                await db.execute("ALTER TABLE users_v3 ADD COLUMN persona TEXT DEFAULT 'default'")
            if "joined_at" not in cols:
                await db.execute("ALTER TABLE users_v3 ADD COLUMN joined_at REAL")
            await db.commit()

    async def get_user_data(self, chat_id: int) -> Tuple[List[Dict[str, str]], str, Dict[str, str], str]:
        """Returns (history, active_model, custom_keys, persona)"""
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                "SELECT history, active_model, custom_keys, persona FROM users_v3 WHERE chat_id = ?", (chat_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    history = json.loads(row[0]) if row[0] else []
                    active_model = row[1] or "mimo"
                    custom_keys = json.loads(row[2]) if row[2] else {}
                    persona = row[3] or DEFAULT_PERSONA
                    return history, active_model, custom_keys, persona
                return [], "mimo", {}, DEFAULT_PERSONA

    async def save_user_data(self, chat_id: int, history: List[Dict[str, str]], active_model: str,
                              custom_keys: Dict[str, str], persona: str = None):
        async with aiosqlite.connect(self.db_name) as db:
            now = time.time()
            if persona is None:
                _, _, _, persona = await self.get_user_data(chat_id)
            await db.execute('''
                INSERT INTO users_v3 (chat_id, history, active_model, custom_keys, persona, joined_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                history=excluded.history,
                active_model=excluded.active_model,
                custom_keys=excluded.custom_keys,
                persona=excluded.persona,
                last_updated=excluded.last_updated
            ''', (chat_id, json.dumps(history), active_model, json.dumps(custom_keys), persona, now, now))
            await db.commit()

    async def clear_history(self, chat_id: int):
        history, active_model, custom_keys, persona = await self.get_user_data(chat_id)
        await self.save_user_data(chat_id, [], active_model, custom_keys, persona)

    async def all_chat_ids(self) -> List[int]:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute("SELECT chat_id FROM users_v3") as cursor:
                return [row[0] for row in await cursor.fetchall()]

    async def user_count(self) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute("SELECT COUNT(*) FROM users_v3") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # --- HELPERS ---
    async def safe_delete(self, message):
        try:
            await message.delete()
        except Exception:
            pass

    async def send_reply(self, update: Update, text: str, **kwargs):
        """Sends text, auto-falling back to a document if it's too long, and
        stripping Markdown if Telegram rejects the formatting."""
        if len(text) > TELEGRAM_MSG_LIMIT:
            await self.send_as_file(update, text)
            return
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
        except BadRequest:
            await update.message.reply_text(text, **kwargs)

    async def send_as_file(self, update: Update, text: str):
        import io
        ext = "py" if "def " in text or "import " in text else "txt"
        bio = io.BytesIO(text.encode("utf-8"))
        bio.name = f"response.{ext}"
        await update.message.reply_document(
            document=bio,
            caption="Response was long, so I sent it as a file."
        )

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in ADMIN_IDS

    # --- COMMANDS ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        await self.get_user_data(chat_id)  # ensures row exists after first save
        await self.save_user_data(chat_id, [], "mimo", {}, DEFAULT_PERSONA)
        await update.message.reply_text(
            "*Hi, I am your AI Assistant.*\n\n"
            "Free and BYOK (Bring Your Own Key) models are available.\n\n"
            "Quick start:\n"
            "/model - choose your AI engine\n"
            "/persona - change how I behave\n"
            "/session - view your current session\n"
            "/help - full command list",
            parse_mode=ParseMode.MARKDOWN
        )

    async def new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        await self.clear_history(chat_id)
        await self.safe_delete(update.message)
        await context.bot.send_message(
            chat_id, "Fresh session started. Memory cleared, keys and model kept.",
            parse_mode=ParseMode.MARKDOWN
        )

    # kept for backwards compatibility
    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.new_session(update, context)

    async def info_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        history, active_model, custom_keys, persona = await self.get_user_data(chat_id)
        provider = self.resolve_provider(active_model)
        persona_label = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["label"]
        used_turns = len(history) // 2
        bar = make_bar(used_turns, self.max_history)
        keys_set = ", ".join(k for k in custom_keys) or "none"

        text = (
            "*Your Dashboard*\n\n"
            f"Active Model: `{provider['name']}`\n"
            f"Current Persona: `{persona_label}`\n"
            f"Context Memory: {used_turns}/{self.max_history} messages used\n"
            f"`[{bar}]`\n"
            f"Saved BYOK keys: `{keys_set}`\n\n"
            "Use /new to clear memory, /model to switch engines, /persona to change behavior."
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    # --- PERSONA ---
    async def persona_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        _, _, _, current = await self.get_user_data(chat_id)
        keyboard = []
        for key, p in PERSONAS.items():
            prefix = "> " if key == current else ""
            keyboard.append([InlineKeyboardButton(f"{prefix}{p['label']}", callback_data=f"setpersona_{key}")])
        await update.message.reply_text(
            "*Choose a persona:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def persona_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        key = query.data.split("_", 1)[1]
        if key in PERSONAS:
            history, active_model, custom_keys, _ = await self.get_user_data(chat_id)
            await self.save_user_data(chat_id, history, active_model, custom_keys, key)
            await query.edit_message_text(f"Persona set to: *{PERSONAS[key]['label']}*", parse_mode=ParseMode.MARKDOWN)

    # --- HELP ---
    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("Commands", callback_data="help_commands")],
            [InlineKeyboardButton("How to get API Keys", callback_data="help_keys")],
            [InlineKeyboardButton("Contact Admin", callback_data="help_admin")],
        ]
        await update.message.reply_text(
            "*Help Menu*\nChoose a topic:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        section = query.data.split("_", 1)[1]
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="help_root")]])

        if section == "root":
            keyboard = [
                [InlineKeyboardButton("Commands", callback_data="help_commands")],
                [InlineKeyboardButton("How to get API Keys", callback_data="help_keys")],
                [InlineKeyboardButton("Contact Admin", callback_data="help_admin")],
            ]
            await query.edit_message_text("*Help Menu*\nChoose a topic:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if section == "commands":
            text = (
                "*Commands*\n"
                "/new - clear memory, keep keys and model\n"
                "/model - switch AI engine or browse OpenRouter/DeepSeek/Claude models\n"
                "/persona - change assistant behavior\n"
                "/info - view your dashboard\n"
                "/session - view current session (model, persona, memory)\n"
                "/setkey <provider> <key> - save a BYOK key (openrouter, deepseek, claude)\n"
                "/help - this menu"
            )
        elif section == "keys":
            text = (
                "*Getting API Keys*\n"
                "OpenRouter: create a key at openrouter.ai/keys, unlocks browsing all its hosted models.\n"
                "DeepSeek: create a key at platform.deepseek.com under API Keys.\n"
                "Claude: create a key at console.anthropic.com under API Keys.\n\n"
                "Then run: `/setkey <provider> <your_key>`\n"
                "Your key is verified before saving and used only for your own requests."
            )
        elif section == "admin":
            text = "*Contact Admin*\nMessage the bot owner directly for support or bug reports."
        else:
            text = "Unknown section."

        await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)

    # --- ADMIN ---
    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return
        count = await self.user_count()
        await update.message.reply_text(f"*Bot Stats*\nRegistered users: `{count}`", parse_mode=ParseMode.MARKDOWN)

    async def broadcast_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return
        text = " ".join(context.args)
        if not text:
            await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN)
            return

        ids = await self.all_chat_ids()
        sent, failed = 0, 0
        status = await update.message.reply_text(f"Sending to {len(ids)} users...")
        for uid in ids:
            try:
                await context.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)  # avoid Telegram flood limits
        await status.edit_text(f"Broadcast done. Sent: {sent}, Failed: {failed}")

    # --- API KEY MANAGEMENT ---
    async def verify_key(self, group_name, api_key) -> bool:
        if group_name in BROWSE_GROUPS:
            g = BROWSE_GROUPS[group_name]
            try:
                if group_name in ANTHROPIC_GROUPS:
                    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
                else:
                    headers = {"Authorization": f"Bearer {api_key}"}
                resp = await self.http_client.get(g["models_url"], headers=headers, timeout=10.0)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Verification error for {group_name}: {e}")
                return False

        provider = next((p for p in AI_PROVIDERS.values() if p.get("group") == group_name), None)
        if not provider:
            return False
        try:
            response = await self.http_client.post(
                provider["url"],
                json={"model": provider["model_id"], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Verification error for {group_name}: {e}")
            return False

    async def setkey_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        args = context.args
        await self.safe_delete(update.message)

        if len(args) != 2:
            await context.bot.send_message(chat_id, "Usage: `/setkey <provider> <key>`", parse_mode=ParseMode.MARKDOWN)
            return

        group_name = args[0].lower()
        api_key = args[1]

        byok_groups = {p["group"] for p in AI_PROVIDERS.values() if not p.get("is_free")} | set(BROWSE_GROUPS.keys())
        if group_name not in byok_groups:
            await context.bot.send_message(chat_id, f"'{group_name}' is not a valid BYOK provider.")
            return

        status_msg = await context.bot.send_message(chat_id, f"Verifying your {group_name} key...")
        is_valid = await self.verify_key(group_name, api_key)

        if is_valid:
            history, active_model, custom_keys, persona = await self.get_user_data(chat_id)
            custom_keys[group_name] = api_key
            await self.save_user_data(chat_id, history, active_model, custom_keys, persona)
            await status_msg.edit_text(f"Key verified. Saved securely for `{group_name}`.", parse_mode=ParseMode.MARKDOWN)
        else:
            await status_msg.edit_text(f"Invalid key: rejected by {group_name}. Check the key and try again.")

    # --- MODEL SELECTION ---
    async def model_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        _, active_model, _, _ = await self.get_user_data(chat_id)
        keyboard = []
        for key, provider in AI_PROVIDERS.items():
            prefix = "> " if key == active_model else ""
            keyboard.append([InlineKeyboardButton(f"{prefix}{provider['name']}", callback_data=f"setmodel_{key}")])
        for group, g in BROWSE_GROUPS.items():
            keyboard.append([InlineKeyboardButton(f"Browse {g['label']} models", callback_data=f"browse_{group}_0")])
        await update.message.reply_text(
            "*Select your preferred AI Model:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def browse_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        _, group, page = query.data.split("_")
        page = int(page)

        _, _, custom_keys, _ = await self.get_user_data(chat_id)
        api_key = custom_keys.get(group)
        if not api_key:
            await query.edit_message_text(
                f"Set a key first: `/setkey {group} <your_key>`", parse_mode=ParseMode.MARKDOWN
            )
            return

        models = await self.get_group_models(group, api_key)
        if not models:
            await query.edit_message_text(f"Could not fetch {BROWSE_GROUPS[group]['label']} models. Try again shortly.")
            return

        start = page * OR_PAGE_SIZE
        chunk = models[start:start + OR_PAGE_SIZE]
        keyboard = [[InlineKeyboardButton(m["name"][:60], callback_data=f"browseset_{group}_{start + i}")] for i, m in enumerate(chunk)]

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("Prev", callback_data=f"browse_{group}_{page - 1}"))
        if start + OR_PAGE_SIZE < len(models):
            nav.append(InlineKeyboardButton("Next", callback_data=f"browse_{group}_{page + 1}"))
        if nav:
            keyboard.append(nav)

        total_pages = (len(models) - 1) // OR_PAGE_SIZE + 1
        await query.edit_message_text(
            f"*{BROWSE_GROUPS[group]['label']} Models* (page {page + 1}/{total_pages})",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def browse_set_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        _, group, index = query.data.split("_")
        index = int(index)

        history, _, custom_keys, persona = await self.get_user_data(chat_id)
        api_key = custom_keys.get(group)
        if not api_key:
            await query.edit_message_text(f"Set a key first: `/setkey {group} <your_key>`", parse_mode=ParseMode.MARKDOWN)
            return

        models = await self.get_group_models(group, api_key)
        if index >= len(models):
            await query.edit_message_text("That model list has refreshed, please run /model again.")
            return

        model_id = models[index]["id"]
        await self.save_user_data(chat_id, history, f"{group}:{model_id}", custom_keys, persona)
        await query.edit_message_text(f"AI Engine changed to: *{model_id}*", parse_mode=ParseMode.MARKDOWN)

    async def model_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        data = query.data

        if data.startswith("setmodel_"):
            selected = data.split("_")[1]
            if selected in AI_PROVIDERS:
                history, _, custom_keys, persona = await self.get_user_data(chat_id)
                await self.save_user_data(chat_id, history, selected, custom_keys, persona)
                provider = AI_PROVIDERS[selected]
                text = f"AI Engine changed to: *{provider['name']}*\n\n"
                grp = provider.get("group", selected)
                if not provider.get("is_free") and grp not in custom_keys:
                    text += f"Note: no key set yet.\nUse: `/setkey {grp} <your_key>`"
                await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

    # --- AI LOGIC ---
    async def _keep_typing(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        chat_id = update.message.chat.id
        user_text = update.message.text
        now = time.time()

        if now - self.last_msg_time.get(chat_id, 0) < self.min_interval:
            await update.message.reply_text("Slow down a bit, please.")
            return
        self.last_msg_time[chat_id] = now

        history, active_model, custom_keys, persona = await self.get_user_data(chat_id)
        provider = self.resolve_provider(active_model)
        system_prompt = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["prompt"]

        if provider["is_free"]:
            api_key = os.getenv(provider["env_key"])
        else:
            group_name = provider.get("group", active_model)
            api_key = custom_keys.get(group_name)
            if not api_key:
                await update.message.reply_text(
                    f"You need a personal API key for *{provider['name']}*.\nSend: `/setkey {group_name} <your_api_key>`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

        history.append({"role": "user", "content": user_text})
        if len(history) > self.max_history * 2:
            history[:] = history[-(self.max_history * 2):]

        messages = [{"role": "system", "content": system_prompt}] + history
        typing_task = asyncio.create_task(self._keep_typing(chat_id, context))
        is_anthropic = provider.get("group") in ANTHROPIC_GROUPS

        try:
            if is_anthropic:
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
                body = {"model": provider["model_id"], "system": system_prompt, "messages": history, "max_tokens": 1024}
            else:
                headers = {"Authorization": f"Bearer {api_key}"}
                body = {"model": provider["model_id"], "messages": messages}

            response = await self.http_client.post(provider["url"], json=body, headers=headers)

            if response.status_code == 401:
                grp = provider.get("group", active_model)
                reply = f"Authentication error: your saved key for `{grp}` is invalid or expired.\nUpdate it: `/setkey {grp} <new_key>`"
                history.pop()
            elif response.status_code == 429:
                reply = "Rate limit: too many requests. Please wait a moment."
                history.pop()
            else:
                response.raise_for_status()
                data = response.json()
                if is_anthropic:
                    reply = data["content"][0]["text"]
                else:
                    reply = data["choices"][0]["message"]["content"]
                history.append({"role": "assistant", "content": reply})
                await self.save_user_data(chat_id, history, active_model, custom_keys, persona)

        except Exception as e:
            logger.error(f"API Error with {active_model}: {e}")
            reply = f"Connection error contacting {provider['name']}. Please try again."
            if history and history[-1]["role"] == "user":
                history.pop()
        finally:
            typing_task.cancel()

        await self.send_reply(update, reply)

    # --- LIFECYCLE ---
    async def post_init(self, application: Application) -> None:
        await self.init_db()
        logger.info("MiMo Bot initialized.")

    async def post_shutdown(self, application: Application) -> None:
        await self.http_client.aclose()


def main():
    bot = MimoAIBot()
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(bot.post_init).post_shutdown(bot.post_shutdown).build()

    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("new", bot.new_session))
    app.add_handler(CommandHandler("reset", bot.reset))
    app.add_handler(CommandHandler("model", bot.model_cmd))
    app.add_handler(CommandHandler("setkey", bot.setkey_cmd))
    app.add_handler(CommandHandler("persona", bot.persona_cmd))
    app.add_handler(CommandHandler("info", bot.info_cmd))
    app.add_handler(CommandHandler("session", bot.info_cmd))
    app.add_handler(CommandHandler("help", bot.help_cmd))
    app.add_handler(CommandHandler("stats", bot.stats_cmd))
    app.add_handler(CommandHandler("broadcast", bot.broadcast_cmd))

    app.add_handler(CallbackQueryHandler(bot.model_callback, pattern="^setmodel_"))
    app.add_handler(CallbackQueryHandler(bot.persona_callback, pattern="^setpersona_"))
    app.add_handler(CallbackQueryHandler(bot.help_callback, pattern="^help_"))
    app.add_handler(CallbackQueryHandler(bot.browse_callback, pattern="^browse_"))
    app.add_handler(CallbackQueryHandler(bot.browse_set_callback, pattern="^browseset_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()