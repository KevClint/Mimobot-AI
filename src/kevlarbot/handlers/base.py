import asyncio
import os
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from kevlarbot.ai_client import AIClient, AuthError, RateLimitError
from kevlarbot.config import ADMIN_IDS, TELEGRAM_TOKEN, logger
from kevlarbot.database import KevlarDB
from kevlarbot.providers import AI_PROVIDERS, DEFAULT_PERSONA, PERSONAS
from kevlarbot.utils import make_bar


class KevlarBotBase:
    """Shared state, helpers, and utility methods for all handler mixins."""

    def __init__(self):
        self.max_history = 15
        self.min_interval = 2.0
        self.daily_limit = 100
        self.db = KevlarDB()
        self.ai = AIClient()
        self.last_msg_time: dict[int, float] = {}
        self._daily_counts: dict[int, tuple[str, int]] = {}
        self._last_user_msg: dict[int, str] = {}
        self._cancel_flags: dict[int, asyncio.Event] = {}

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in ADMIN_IDS

    def _check_daily_limit(self, chat_id: int) -> bool:
        today = time.strftime("%Y-%m-%d")
        entry = self._daily_counts.get(chat_id)
        if entry and entry[0] == today:
            if entry[1] >= self.daily_limit:
                return False
            self._daily_counts[chat_id] = (today, entry[1] + 1)
        else:
            self._daily_counts[chat_id] = (today, 1)
        return True

    def _validate_config(self):
        missing = []
        if not TELEGRAM_TOKEN:
            missing.append("TELEGRAM_TOKEN")
        for _key, provider in AI_PROVIDERS.items():
            if provider.get("is_free") and not os.getenv(provider["env_key"]):
                missing.append(provider["env_key"])
        if missing:
            logger.warning(f"Missing env vars: {', '.join(missing)}. Related providers may not work.")
        if not ADMIN_IDS:
            logger.warning("No ADMIN_IDS set. Admin commands will be unavailable.")

    # --- Guard helpers ---

    async def _access_guard(self, update: Update) -> bool:
        """Return True if user is allowed; reply and return False otherwise."""
        chat_id = update.message.chat.id
        if self.is_admin(chat_id):
            return True
        if await self.db.is_user_allowed(chat_id):
            return True
        await update.message.reply_text("Access denied. Contact an admin to get access.")
        return False

    async def _admin_guard(self, update: Update) -> bool:
        """Return True if user is admin; reply and return False otherwise."""
        if self.is_admin(update.message.chat.id):
            return True
        await update.message.reply_text("Not authorized.")
        return False

    async def _callback_access_guard(self, query) -> bool:
        """Return True if callback user is allowed; edit message and return False otherwise."""
        chat_id = query.message.chat.id
        if self.is_admin(chat_id) or await self.db.is_user_allowed(chat_id):
            return True
        await query.edit_message_text("Access denied.")
        return False

    async def _callback_admin_guard(self, query) -> bool:
        """Return True if callback user is admin; edit message and return False otherwise."""
        if self.is_admin(query.message.chat.id):
            return True
        await query.edit_message_text("Not authorized.")
        return False

    # --- Shared broadcast logic ---

    async def _broadcast_message(self, text: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[int, int]:
        """Broadcast text to all registered users. Returns (sent, failed)."""
        ids = await self.db.all_chat_ids()
        sem = asyncio.Semaphore(20)
        sent, failed = 0, 0

        async def send_one(uid):
            nonlocal sent, failed
            async with sem:
                try:
                    await context.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN)
                    sent += 1
                except BadRequest:
                    failed += 1
                except Exception as e:
                    if "RetryAfter" in type(e).__name__:
                        await asyncio.sleep(e.retry_after + 1)
                        try:
                            await context.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN)
                            sent += 1
                        except Exception:
                            failed += 1
                    else:
                        failed += 1

        await asyncio.gather(*(send_one(uid) for uid in ids), return_exceptions=True)
        return sent, failed

    # --- User target resolution ---

    async def _resolve_target(self, update: Update, context) -> tuple[int, str | None] | None:
        """Resolve target user from reply, numeric ID, or username. Returns (chat_id, label) or None."""
        if update.message.reply_to_message:
            target_id = update.message.reply_to_message.from_user.id
            target_label = update.message.reply_to_message.from_user.username
            if not target_id:
                await update.message.reply_text("Could not identify the replied user.")
                return None
            return target_id, target_label

        if not context.args:
            await update.message.reply_text(
                "Usage: `/adduser @username`, `/adduser <chat_id>`, or reply to a message with `/adduser`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return None

        arg = context.args[0]
        if arg.lstrip("-").isdigit():
            target_id = int(arg)
            if not await self.db.get_user_by_id(target_id):
                await update.message.reply_text(
                    f"ID `{target_id}` not found. They need to message the bot first.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return None
            return target_id, None

        target_id = await self.db.get_user_by_username(arg)
        if not target_id:
            await update.message.reply_text(
                f"User `{arg}` not found. They need to message the bot first.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return None
        return target_id, arg

    # --- Shared AI chat logic ---

    async def _run_ai_chat(
        self,
        chat_id: int,
        prompt: str,
        cancel_event: asyncio.Event | None = None,
    ) -> str | None:
        """Run AI chat with fallback chain. Returns reply text or None."""
        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        system_prompt = self._get_persona_prompt(persona)

        history.append({"role": "user", "content": prompt})
        if len(history) > self.max_history * 2:
            history[:] = history[-(self.max_history * 2) :]

        messages = [{"role": "system", "content": system_prompt}] + history
        providers = self.ai.get_fallback_chain(active_model, custom_keys)
        reply = None

        for provider in providers:
            if cancel_event and cancel_event.is_set():
                reply = "Request cancelled."
                break
            if provider["is_free"]:
                api_key = os.getenv(provider["env_key"])
            else:
                group_name = provider.get("group", active_model)
                key_data = custom_keys.get(group_name)
                if isinstance(key_data, dict) and key_data.get("custom"):
                    api_key = key_data["api_key"]
                else:
                    api_key = key_data
                if not api_key:
                    continue
            try:
                reply = await self.ai.chat(provider, messages, api_key, system_prompt)
                history.append({"role": "assistant", "content": reply})
                await self.db.save_user_data(chat_id, history, active_model, custom_keys, persona)
                break
            except AuthError:
                raise
            except RateLimitError:
                logger.warning(f"Rate limited by {provider.get('name', 'unknown')}, trying fallback...")
                continue
            except Exception as e:
                logger.error(f"API Error with {provider['name']}: {e}")
                continue

        if reply is None:
            if history and history[-1]["role"] == "user":
                history.pop()

        return reply

    # --- Persona helpers ---

    @staticmethod
    def _get_persona_prompt(persona: str) -> str:
        return PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["prompt"]

    @staticmethod
    def _get_persona_label(persona: str) -> str:
        return PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["label"]

    # --- Shared keyboard builders ---

    def _model_category_keyboard(self) -> list[list[InlineKeyboardButton]]:
        return [
            [InlineKeyboardButton("\U0001f193 Free Models", callback_data="modelcat_free")],
            [InlineKeyboardButton("\U0001f511 BYOK Providers", callback_data="modelcat_byok")],
            [InlineKeyboardButton("\u2699\ufe0f Custom Endpoints", callback_data="modelcat_custom")],
        ]

    # --- Shared text builders ---

    async def _user_info_text(self, chat_id: int, include_history: bool = False) -> str:
        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        provider = self.ai.resolve_provider(active_model, custom_keys)
        persona_label = self._get_persona_label(persona)
        used_turns = len(history) // 2
        bar = make_bar(used_turns, self.max_history)

        if not include_history:
            keys_list = ", ".join(custom_keys.keys()) or "none"
            return (
                "*Settings*\n\n"
                f"Model: `{provider['name']}`\n"
                f"Persona: `{persona_label}`\n"
                f"Memory: {used_turns}/{self.max_history} turns\n"
                f"`[{bar}]`\n"
                f"Keys: `{keys_list}`"
            )

        lines = [
            "*Current Session*\n",
            f"Model: {provider['name']}",
            f"Persona: {persona_label}",
            f"Memory: {used_turns}/{self.max_history} turns",
            f"[{bar}]\n",
        ]
        if history:
            lines.append("Recent messages:")
            for msg in history[-6:]:
                role = msg.get("role", "?")
                content = (msg.get("content", "") or "")[:80].replace("\n", " ")
                if role == "user":
                    lines.append(f"You: {content}")
                elif role == "assistant":
                    lines.append(f"AI: {content}")
        else:
            lines.append("No messages yet.")
        lines.append("\n/new to clear memory")
        return "\n".join(lines)

    async def _admin_panel(self, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
        count = await self.db.user_count()
        users = await self.db.get_all_users()
        allowed_count = sum(1 for u in users if u["is_allowed"])
        pending_count = len(users) - allowed_count
        text = f"*Admin Panel*\n\nRegistered users: `{count}`\nAllowed: `{allowed_count}` | Pending: `{pending_count}`"
        keyboard = [
            [
                InlineKeyboardButton("Stats", callback_data="admin_stats"),
                InlineKeyboardButton("Users", callback_data="admin_users"),
            ],
            [
                InlineKeyboardButton("Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton("Add User", callback_data="admin_adduser"),
            ],
            [InlineKeyboardButton("Remove User", callback_data="admin_removeuser")],
        ]
        return text, InlineKeyboardMarkup(keyboard)

    async def _admin_stats_text(self) -> str:
        users = await self.db.get_all_users()
        allowed_count = sum(1 for u in users if u["is_allowed"])
        pending_count = len(users) - allowed_count
        return (
            f"*Bot Stats*\n\nTotal registered: `{len(users)}`\nAllowed: `{allowed_count}`\nPending: `{pending_count}`"
        )

    def _format_user_list(self, users: list, limit: int | None = None) -> str:
        items = users[:limit] if limit else users
        lines = [f"*All Users ({len(users)})*\n"]
        for u in items:
            status = "\u2705" if u["is_allowed"] else "\u274c"
            name_parts = []
            if u["username"]:
                name_parts.append(f"@{u['username']}")
            if u["display_name"]:
                name_parts.append(f"({u['display_name']})")
            name_parts.append(f"(ID: {u['chat_id']})")
            lines.append(f"{status} {' '.join(name_parts)}")
        allowed_count = sum(1 for u in users if u["is_allowed"])
        pending_count = len(users) - allowed_count
        lines.append(f"\n\u2705 Allowed ({allowed_count})  \u274c Pending ({pending_count})")
        return "\n".join(lines)
