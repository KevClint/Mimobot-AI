import os
import time
import asyncio
from typing import Dict, Tuple, Any

from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes, ConversationHandler
from telegram.error import BadRequest

from kevlarbot.config import TELEGRAM_TOKEN, ADMIN_IDS, OR_PAGE_SIZE, logger
from kevlarbot.providers import AI_PROVIDERS, PERSONAS, DEFAULT_PERSONA, BROWSE_GROUPS, ANTHROPIC_GROUPS
from kevlarbot.database import MimoDB
from kevlarbot.ai_client import AIClient, AuthError, RateLimitError
from kevlarbot.utils import safe_delete, send_reply, make_bar

WAITING_BROADCAST, WAITING_ADD_USER, WAITING_REMOVE_USER = range(3)


class MimoAIBot:
    def __init__(self):
        self.max_history = 15
        self.min_interval = 2.0
        self.daily_limit = 100
        self.db = MimoDB()
        self.ai = AIClient()
        self.last_msg_time: Dict[int, float] = {}
        self._daily_counts: Dict[int, Tuple[str, int]] = {}
        self._last_user_msg: Dict[int, str] = {}
        self._cancel_flags: Dict[int, asyncio.Event] = {}

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
        for key, provider in AI_PROVIDERS.items():
            if provider.get("is_free") and not os.getenv(provider["env_key"]):
                missing.append(provider["env_key"])
        if missing:
            logger.warning(f"Missing env vars: {', '.join(missing)}. Related providers may not work.")
        if not ADMIN_IDS:
            logger.warning("No ADMIN_IDS set. Admin commands will be unavailable.")

    # --- COMMANDS ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        user = update.effective_user
        username = user.username if user else None
        display_name = user.full_name if user else None

        exists = await self.db.user_exists(chat_id)

        if self.is_admin(chat_id):
            if not exists:
                await self.db.save_user_data(chat_id, [], "mimo", {}, DEFAULT_PERSONA, username, display_name)
                await self.db.set_user_allowed(chat_id, True)
            else:
                await self.db.save_user_data(chat_id, [], "mimo", {}, DEFAULT_PERSONA, username, display_name)
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
            return

        if not exists:
            await self.db.save_user_data(chat_id, [], "mimo", {}, DEFAULT_PERSONA, username, display_name)
            await update.message.reply_text(
                "Access denied. Contact an admin to get access."
            )
            return

        if not await self.db.is_user_allowed(chat_id):
            await update.message.reply_text(
                "Access denied. Contact an admin to get access."
            )
            return

        history, model, keys, persona = await self.db.get_user_data(chat_id)
        await self.db.save_user_data(chat_id, history, model, keys, persona, username, display_name)
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
        await self.db.clear_history(chat_id)
        await safe_delete(update.message)
        await context.bot.send_message(
            chat_id, "Fresh session started. Memory cleared, keys and model kept.",
            parse_mode=ParseMode.MARKDOWN
        )

    async def chat_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        user = update.effective_user
        username = user.username if user else None
        display_name = user.full_name if user else None

        if not self.is_admin(chat_id) and not await self.db.is_user_allowed(chat_id):
            if not await self.db.user_exists(chat_id):
                await self.db.save_user_data(chat_id, [], "mimo", {}, DEFAULT_PERSONA, username, display_name)
            await update.message.reply_text("Access denied. Contact an admin to get access.")
            return

        prompt = " ".join(context.args) if context.args else ""
        if not prompt:
            await update.message.reply_text(
                "Usage: `/chat <your message>`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if not self._check_daily_limit(chat_id):
            await update.message.reply_text(f"Daily limit of {self.daily_limit} messages reached. Try again tomorrow.")
            return

        now = time.time()
        if now - self.last_msg_time.get(chat_id, 0) < self.min_interval:
            await update.message.reply_text("Slow down a bit, please.")
            return
        self.last_msg_time[chat_id] = now

        await update.message.reply_chat_action(constants.ChatAction.TYPING)

        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        persona_data = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])
        system_prompt = persona_data["prompt"]

        history.append({"role": "user", "content": prompt})
        if len(history) > self.max_history * 2:
            history[:] = history[-(self.max_history * 2):]

        messages = [{"role": "system", "content": system_prompt}] + history

        providers = self.ai.get_fallback_chain(active_model, custom_keys)
        reply = None

        for provider in providers:
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
            except RateLimitError:
                continue
            except Exception:
                continue

        if reply is None:
            reply = "AI is currently unavailable. Try again later."
            if history and history[-1]["role"] == "user":
                history.pop()

        await send_reply(update, reply)

    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.new_session(update, context)

    async def retry_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        last_msg = self._last_user_msg.get(chat_id)
        if not last_msg:
            await update.message.reply_text("Nothing to retry. Send a message first.")
            return
        update.message.text = last_msg
        await self.handle_message(update, context)

    async def cancel_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        event = self._cancel_flags.get(chat_id)
        if event:
            event.set()
            await update.message.reply_text("Cancelled.")
        else:
            await update.message.reply_text("Nothing to cancel.")

    async def info_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        provider = self.ai.resolve_provider(active_model, custom_keys)
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

    async def session_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        provider = self.ai.resolve_provider(active_model, custom_keys)
        persona_label = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["label"]
        used_turns = len(history) // 2
        bar = make_bar(used_turns, self.max_history)

        lines = [
            f"Current Session\n",
            f"Model: {provider['name']}",
            f"Persona: {persona_label}",
            f"Memory: {used_turns}/{self.max_history} turns",
            f"[{bar}]\n",
        ]

        if history:
            lines.append("Recent messages:")
            recent = history[-6:]
            for msg in recent:
                role = msg.get("role", "?")
                content = (msg.get("content", "") or "")[:80].replace("\n", " ")
                if role == "user":
                    lines.append(f"You: {content}")
                elif role == "assistant":
                    lines.append(f"AI: {content}")
        else:
            lines.append("No messages yet.")

        lines.append("\n/new to clear - /retry to regenerate last reply")
        text = "\n".join(lines)
        if len(text) > 4000:
            await send_reply(update, text)
        else:
            await update.message.reply_text(text)

    # --- PERSONA ---
    async def persona_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        _, _, _, current = await self.db.get_user_data(chat_id)
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
            history, active_model, custom_keys, _ = await self.db.get_user_data(chat_id)
            await self.db.save_user_data(chat_id, history, active_model, custom_keys, key)
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
                "/chat <message> - chat with AI (with memory)\n"
                "/new - clear memory, keep keys and model\n"
                "/retry - regenerate the last response\n"
                "/cancel - cancel an in-progress request\n"
                "/settings - view and change your settings\n"
                "/model - switch AI engine or browse models\n"
                "/persona - change assistant behavior\n"
                "/setkey <provider> <key> - save a BYOK key\n"
                "/setkey <name> <base\\_url> <key> - add custom endpoint\n"
                "/help - this menu\n\n"
                "*Admin Commands*\n"
                "/admin - admin panel (interactive)\n"
                "/adduser @username - whitelist a user\n"
                "/removeuser @username - revoke access\n"
                "/broadcast <message> - send to all users"
            )
        elif section == "keys":
            text = (
                "*Getting API Keys*\n"
                "OpenRouter: create a key at openrouter.ai/keys\n"
                "DeepSeek: create a key at platform.deepseek.com\n"
                "Claude: create a key at console.anthropic.com\n"
                "Groq: create a key at console.groq.com\n\n"
                "Standard: /setkey <provider> <your\\_key>\n"
                "Custom: /setkey <name> <base\\_url> <your\\_key>\n"
                "Your key is verified before saving."
            )
        elif section == "admin":
            text = "*Contact Admin*\nMessage the bot owner directly for support or bug reports."
        else:
            text = "Unknown section."

        try:
            await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        except BadRequest:
            await query.edit_message_text(text, reply_markup=back_kb)

    # --- ADMIN ---
    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return
        count = await self.db.user_count()
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

        ids = await self.db.all_chat_ids()
        status = await update.message.reply_text(f"Sending to {len(ids)} users...")

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
        await status.edit_text(f"Broadcast done. Sent: {sent}, Failed: {failed}")

    # --- WHITELIST MANAGEMENT ---
    async def adduser_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return

        target_id = None
        target_label = None

        if update.message.reply_to_message:
            target_id = update.message.reply_to_message.from_user.id
            target_label = update.message.reply_to_message.from_user.username
            if not target_id:
                await update.message.reply_text("Could not identify the replied user.")
                return
        elif context.args:
            arg = context.args[0]
            if arg.lstrip("-").isdigit():
                target_id = int(arg)
                if not await self.db.get_user_by_id(target_id):
                    await update.message.reply_text(
                        f"ID `{target_id}` not found. They need to message the bot first.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                target_label = None
            else:
                target_id = await self.db.get_user_by_username(arg)
                target_label = arg
                if not target_id:
                    await update.message.reply_text(
                        f"User `{arg}` not found. They need to message the bot first.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
        else:
            await update.message.reply_text(
                "Usage: `/adduser @username`, `/adduser <chat_id>`, or reply to a message with `/adduser`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        await self.db.set_user_allowed(target_id, True)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been whitelisted.")

    async def removeuser_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return

        target_id = None
        target_label = None

        if update.message.reply_to_message:
            target_id = update.message.reply_to_message.from_user.id
            target_label = update.message.reply_to_message.from_user.username
            if not target_id:
                await update.message.reply_text("Could not identify the replied user.")
                return
        elif context.args:
            arg = context.args[0]
            if arg.lstrip("-").isdigit():
                target_id = int(arg)
                if not await self.db.get_user_by_id(target_id):
                    await update.message.reply_text(
                        f"ID `{target_id}` not found.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                target_label = None
            else:
                target_id = await self.db.get_user_by_username(arg)
                target_label = arg
                if not target_id:
                    await update.message.reply_text(
                        f"User `{arg}` not found.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
        else:
            await update.message.reply_text(
                "Usage: `/removeuser @username`, `/removeuser <chat_id>`, or reply to a message with `/removeuser`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        await self.db.set_user_allowed(target_id, False)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been removed.")

    async def listusers_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return

        users = await self.db.get_all_users()
        if not users:
            await update.message.reply_text("No users found.")
            return

        allowed_count = sum(1 for u in users if u["is_allowed"])
        pending_count = len(users) - allowed_count
        lines = [f"All Users ({len(users)}):\n"]

        for u in users:
            status = "✅" if u["is_allowed"] else "❌"
            name_parts = []
            if u["username"]:
                name_parts.append(f"@{u['username']}")
            if u["display_name"]:
                name_parts.append(f"({u['display_name']})")
            if not name_parts:
                name_parts.append(f"(ID: {u['chat_id']})")
            else:
                name_parts.append(f"(ID: {u['chat_id']})")
            lines.append(f"{status} {' '.join(name_parts)}")

        lines.append(f"\n✅ Allowed ({allowed_count})  ❌ Pending ({pending_count})")
        await update.message.reply_text("\n".join(lines))

    # --- ADMIN PANEL ---
    async def admin_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return
        count = await self.db.user_count()
        users = await self.db.get_all_users()
        allowed_count = sum(1 for u in users if u["is_allowed"])
        pending_count = len(users) - allowed_count

        text = (
            "*Admin Panel*\n\n"
            f"Registered users: `{count}`\n"
            f"Allowed: `{allowed_count}` | Pending: `{pending_count}`"
        )
        keyboard = [
            [InlineKeyboardButton("Stats", callback_data="admin_stats"),
             InlineKeyboardButton("Users", callback_data="admin_users")],
            [InlineKeyboardButton("Broadcast", callback_data="admin_broadcast"),
             InlineKeyboardButton("Add User", callback_data="admin_adduser")],
            [InlineKeyboardButton("Remove User", callback_data="admin_removeuser")],
        ]
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        if not self.is_admin(chat_id):
            await query.edit_message_text("Not authorized.")
            return

        section = query.data.split("_", 1)[1]
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_root")]])

        if section == "root":
            count = await self.db.user_count()
            users = await self.db.get_all_users()
            allowed_count = sum(1 for u in users if u["is_allowed"])
            pending_count = len(users) - allowed_count
            text = (
                "*Admin Panel*\n\n"
                f"Registered users: `{count}`\n"
                f"Allowed: `{allowed_count}` | Pending: `{pending_count}`"
            )
            keyboard = [
                [InlineKeyboardButton("Stats", callback_data="admin_stats"),
                 InlineKeyboardButton("Users", callback_data="admin_users")],
                [InlineKeyboardButton("Broadcast", callback_data="admin_broadcast"),
                 InlineKeyboardButton("Add User", callback_data="admin_adduser")],
                [InlineKeyboardButton("Remove User", callback_data="admin_removeuser")],
            ]
            await query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if section == "stats":
            count = await self.db.user_count()
            users = await self.db.get_all_users()
            allowed_count = sum(1 for u in users if u["is_allowed"])
            pending_count = len(users) - allowed_count
            text = (
                "*Bot Stats*\n\n"
                f"Total registered: `{count}`\n"
                f"Allowed: `{allowed_count}`\n"
                f"Pending: `{pending_count}`"
            )
            await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
            return

        if section == "users":
            users = await self.db.get_all_users()
            if not users:
                await query.edit_message_text("No users found.", reply_markup=back_kb)
                return
            lines = [f"*All Users ({len(users)})*\n"]
            for u in users[:8]:
                status = "✅" if u["is_allowed"] else "❌"
                name_parts = []
                if u["username"]:
                    name_parts.append(f"@{u['username']}")
                if u["display_name"]:
                    name_parts.append(f"({u['display_name']})")
                name_parts.append(f"(ID: {u['chat_id']})")
                lines.append(f"{status} {' '.join(name_parts)}")
            allowed_count = sum(1 for u in users if u["is_allowed"])
            pending_count = len(users) - allowed_count
            lines.append(f"\n✅ Allowed ({allowed_count})  ❌ Pending ({pending_count})")
            await query.edit_message_text("\n".join(lines), reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
            return

        if section == "broadcast":
            await query.edit_message_text(
                "Type your broadcast message:", reply_markup=back_kb
            )
            return

        if section == "adduser":
            await query.edit_message_text(
                "Send me the username (e.g. @johndoe) or chat ID:",
                reply_markup=back_kb
            )
            return

        if section == "removeuser":
            await query.edit_message_text(
                "Send me the username (e.g. @johndoe) or chat ID:",
                reply_markup=back_kb
            )
            return

    # --- ADMIN CONVERSATION HANDLERS ---
    async def admin_broadcast_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        if not self.is_admin(chat_id):
            await query.edit_message_text("Not authorized.")
            return ConversationHandler.END
        await query.edit_message_text("Type your broadcast message:")
        return WAITING_BROADCAST

    async def receive_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return ConversationHandler.END

        text = update.message.text
        ids = await self.db.all_chat_ids()
        status = await update.message.reply_text(f"Sending to {len(ids)} users...")

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
        await status.edit_text(f"Broadcast done. Sent: {sent}, Failed: {failed}")
        return ConversationHandler.END

    async def admin_adduser_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        if not self.is_admin(chat_id):
            await query.edit_message_text("Not authorized.")
            return ConversationHandler.END
        await query.edit_message_text("Send me the username (e.g. @johndoe) or chat ID:")
        return WAITING_ADD_USER

    async def receive_adduser_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return ConversationHandler.END

        arg = update.message.text.strip()
        target_id = None
        target_label = None

        if arg.lstrip("-").isdigit():
            target_id = int(arg)
            if not await self.db.get_user_by_id(target_id):
                await update.message.reply_text(
                    f"ID `{target_id}` not found. They need to message the bot first.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END
        else:
            clean = arg.lstrip("@").lower()
            target_id = await self.db.get_user_by_username(clean)
            target_label = clean
            if not target_id:
                await update.message.reply_text(
                    f"User `{arg}` not found. They need to message the bot first.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END

        await self.db.set_user_allowed(target_id, True)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been whitelisted.")
        return ConversationHandler.END

    async def admin_removeuser_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        if not self.is_admin(chat_id):
            await query.edit_message_text("Not authorized.")
            return ConversationHandler.END
        await query.edit_message_text("Send me the username (e.g. @johndoe) or chat ID:")
        return WAITING_REMOVE_USER

    async def receive_removeuser_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id):
            await update.message.reply_text("Not authorized.")
            return ConversationHandler.END

        arg = update.message.text.strip()
        target_id = None
        target_label = None

        if arg.lstrip("-").isdigit():
            target_id = int(arg)
            if not await self.db.get_user_by_id(target_id):
                await update.message.reply_text(
                    f"ID `{target_id}` not found.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END
        else:
            clean = arg.lstrip("@").lower()
            target_id = await self.db.get_user_by_username(clean)
            target_label = clean
            if not target_id:
                await update.message.reply_text(
                    f"User `{arg}` not found.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END

        await self.db.set_user_allowed(target_id, False)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been removed.")
        return ConversationHandler.END

    async def cancel_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END

    # --- SETTINGS ---
    async def settings_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        if not self.is_admin(chat_id) and not await self.db.is_user_allowed(chat_id):
            await update.message.reply_text("Access denied. Contact an admin to get access.")
            return

        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        provider = self.ai.resolve_provider(active_model, custom_keys)
        persona_label = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["label"]
        used_turns = len(history) // 2
        bar = make_bar(used_turns, self.max_history)
        keys_list = ", ".join(custom_keys.keys()) or "none"

        text = (
            "*Settings*\n\n"
            f"Model: `{provider['name']}`\n"
            f"Persona: `{persona_label}`\n"
            f"Memory: {used_turns}/{self.max_history} turns\n"
            f"`[{bar}]`\n"
            f"Keys: `{keys_list}`"
        )
        keyboard = [
            [InlineKeyboardButton("Model", callback_data="settings_model"),
             InlineKeyboardButton("Persona", callback_data="settings_persona")],
            [InlineKeyboardButton("Keys", callback_data="settings_keys"),
             InlineKeyboardButton("Session", callback_data="settings_session")],
            [InlineKeyboardButton("Help", callback_data="help_root")],
        ]
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def settings_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        if not self.is_admin(chat_id) and not await self.db.is_user_allowed(chat_id):
            await query.edit_message_text("Access denied.")
            return

        section = query.data.split("_", 1)[1]
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="settings_root")]])

        if section == "root":
            history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
            provider = self.ai.resolve_provider(active_model, custom_keys)
            persona_label = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["label"]
            used_turns = len(history) // 2
            bar = make_bar(used_turns, self.max_history)
            keys_list = ", ".join(custom_keys.keys()) or "none"
            text = (
                "*Settings*\n\n"
                f"Model: `{provider['name']}`\n"
                f"Persona: `{persona_label}`\n"
                f"Memory: {used_turns}/{self.max_history} turns\n"
                f"`[{bar}]`\n"
                f"Keys: `{keys_list}`"
            )
            keyboard = [
                [InlineKeyboardButton("Model", callback_data="settings_model"),
                 InlineKeyboardButton("Persona", callback_data="settings_persona")],
                [InlineKeyboardButton("Keys", callback_data="settings_keys"),
                 InlineKeyboardButton("Session", callback_data="settings_session")],
                [InlineKeyboardButton("Help", callback_data="help_root")],
            ]
            await query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if section == "model":
            _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
            keyboard = [
                [InlineKeyboardButton("🆓 Free Models", callback_data="modelcat_free")],
                [InlineKeyboardButton("🔑 BYOK Providers", callback_data="modelcat_byok")],
                [InlineKeyboardButton("⚙️ Custom Endpoints", callback_data="modelcat_custom")],
            ]
            keyboard.append([InlineKeyboardButton("Back", callback_data="settings_root")])
            await query.edit_message_text(
                "*Select your preferred AI Model:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if section == "persona":
            _, _, _, current = await self.db.get_user_data(chat_id)
            keyboard = []
            for key, p in PERSONAS.items():
                prefix = "> " if key == current else ""
                keyboard.append([InlineKeyboardButton(f"{prefix}{p['label']}", callback_data=f"setpersona_{key}")])
            keyboard.append([InlineKeyboardButton("Back", callback_data="settings_root")])
            await query.edit_message_text(
                "*Choose a persona:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if section == "keys":
            _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
            keys_list = "\n".join(f"• `{k}`" for k in custom_keys) if custom_keys else "No keys saved."
            text = (
                "*API Keys*\n\n"
                f"{keys_list}\n\n"
                "To add/update a key:\n"
                "`/setkey <provider> <key>`\n"
                "`/setkey <name> <base_url> <key>` (custom endpoint)"
            )
            await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
            return

        if section == "session":
            history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
            provider = self.ai.resolve_provider(active_model, custom_keys)
            persona_label = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])["label"]
            used_turns = len(history) // 2
            bar = make_bar(used_turns, self.max_history)

            lines = [
                "*Current Session*\n",
                f"Model: {provider['name']}",
                f"Persona: {persona_label}",
                f"Memory: {used_turns}/{self.max_history} turns",
                f"[{bar}]\n",
            ]
            if history:
                lines.append("Recent messages:")
                recent = history[-6:]
                for msg in recent:
                    role = msg.get("role", "?")
                    content = (msg.get("content", "") or "")[:80].replace("\n", " ")
                    if role == "user":
                        lines.append(f"You: {content}")
                    elif role == "assistant":
                        lines.append(f"AI: {content}")
            else:
                lines.append("No messages yet.")
            lines.append("\n/new to clear memory")
            text = "\n".join(lines)
            await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
            return

    # --- INLINE QUERY ---
    async def inline_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.inline_query
        if not query:
            return

        user = query.from_user
        chat_id = user.id
        text = query.query.strip()

        if not text.startswith("/chat"):
            return

        prompt = text[len("/chat"):].strip()
        if not prompt:
            results = [
                InlineQueryResultArticle(
                    id="help",
                    title="Usage",
                    description="Type /chat <your message>",
                    input_message_content=InputTextMessageContent(
                        "Usage: `@kvlraiBot /chat <your message>`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                )
            ]
            await query.answer(results, cache_time=0)
            return

        if not self.is_admin(chat_id) and not await self.db.is_user_allowed(chat_id):
            return

        if not self._check_daily_limit(chat_id):
            results = [
                InlineQueryResultArticle(
                    id="limit",
                    title="Daily limit reached",
                    description=f"You've reached the {self.daily_limit} message daily limit.",
                    input_message_content=InputTextMessageContent(
                        f"Daily limit of {self.daily_limit} messages reached. Try again tomorrow."
                    )
                )
            ]
            await query.answer(results, cache_time=0)
            return

        thinking_results = [
            InlineQueryResultArticle(
                id="thinking",
                title="Thinking...",
                description=prompt[:100],
                input_message_content=InputTextMessageContent("Thinking...")
            )
        ]
        await query.answer(thinking_results, cache_time=0)

        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        persona_data = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])
        system_prompt = persona_data["prompt"]

        history.append({"role": "user", "content": prompt})
        if len(history) > self.max_history * 2:
            history[:] = history[-(self.max_history * 2):]

        messages = [{"role": "system", "content": system_prompt}] + history

        providers = self.ai.get_fallback_chain(active_model, custom_keys)
        reply = None

        for provider in providers:
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
            except RateLimitError:
                continue
            except Exception:
                continue

        if reply is None:
            reply = "AI is currently unavailable. Try again later."
            if history and history[-1]["role"] == "user":
                history.pop()

        source_chat = query.inline_message_id
        if source_chat:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"*{prompt}*\n\n{reply}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest:
                await context.bot.send_message(chat_id=chat_id, text=reply)

    # --- API KEY MANAGEMENT ---
    async def setkey_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        args = context.args
        await safe_delete(update.message)

        if len(args) == 2:
            group_name = args[0].lower()
            api_key = args[1]

            byok_groups = {p["group"] for p in AI_PROVIDERS.values() if not p.get("is_free")} | set(BROWSE_GROUPS.keys())
            if group_name not in byok_groups:
                await context.bot.send_message(chat_id, f"'{group_name}' is not a valid BYOK provider.")
                return

            status_msg = await context.bot.send_message(chat_id, f"Verifying your {group_name} key...")
            is_valid = await self.ai.verify_key(group_name, api_key)

            if is_valid:
                history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
                custom_keys[group_name] = api_key
                await self.db.save_user_data(chat_id, history, active_model, custom_keys, persona)
                await status_msg.edit_text(f"Key verified. Saved securely for `{group_name}`.", parse_mode=ParseMode.MARKDOWN)
            else:
                await status_msg.edit_text(f"Invalid key: rejected by {group_name}. Check the key and try again.")

        elif len(args) == 3:
            group_name = args[0].lower()
            base_url = args[1].rstrip("/")
            api_key = args[2]

            chat_url = f"{base_url}/chat/completions"
            models_url = f"{base_url}/models"

            endpoint_meta = {
                "api_key": api_key,
                "base_url": base_url,
                "chat_url": chat_url,
                "models_url": models_url,
                "custom": True,
            }

            status_msg = await context.bot.send_message(chat_id, f"Verifying your `{group_name}` key...")
            is_valid = await self.ai.verify_key(group_name, api_key, endpoint_meta)

            if is_valid:
                history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
                custom_keys[group_name] = endpoint_meta
                await self.db.save_user_data(chat_id, history, active_model, custom_keys, persona)
                await status_msg.edit_text(
                    f"Custom endpoint `{group_name}` verified and saved.\n"
                    f"Base URL: `{base_url}`\n"
                    f"Use `/model` to browse and select models.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await status_msg.edit_text(f"Invalid key: rejected by `{group_name}`. Check the URL and key.")

        else:
            await context.bot.send_message(
                chat_id,
                "Usage:\n"
                "`/setkey <provider> <key>`\n"
                "`/setkey <name> <base_url> <key>` (custom endpoint)",
                parse_mode=ParseMode.MARKDOWN
            )

    # --- MODEL SELECTION ---
    async def model_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
        keyboard = [
            [InlineKeyboardButton("🆓 Free Models", callback_data="modelcat_free")],
            [InlineKeyboardButton("🔑 BYOK Providers", callback_data="modelcat_byok")],
            [InlineKeyboardButton("⚙️ Custom Endpoints", callback_data="modelcat_custom")],
        ]
        await update.message.reply_text(
            "*Select your preferred AI Model:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def model_category_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        category = query.data.split("_", 1)[1]
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="modelcat_back")]])

        if category == "back":
            _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
            keyboard = [
                [InlineKeyboardButton("🆓 Free Models", callback_data="modelcat_free")],
                [InlineKeyboardButton("🔑 BYOK Providers", callback_data="modelcat_byok")],
                [InlineKeyboardButton("⚙️ Custom Endpoints", callback_data="modelcat_custom")],
            ]
            keyboard.append([InlineKeyboardButton("Back", callback_data="settings_root")])
            await query.edit_message_text(
                "*Select your preferred AI Model:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if category == "free":
            _, active_model, _, _ = await self.db.get_user_data(chat_id)
            keyboard = []
            for key, provider in AI_PROVIDERS.items():
                prefix = "> " if key == active_model else ""
                keyboard.append([InlineKeyboardButton(f"{prefix}🆓 {provider['name']}", callback_data=f"setmodel_{key}")])
            keyboard.append([InlineKeyboardButton("Back", callback_data="modelcat_back")])
            await query.edit_message_text(
                "*Free Models*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if category == "byok":
            keyboard = []
            for group, g in BROWSE_GROUPS.items():
                keyboard.append([InlineKeyboardButton(f"🔑 Browse {g['label']} models", callback_data=f"browse_{group}_0")])
            keyboard.append([InlineKeyboardButton("Back", callback_data="modelcat_back")])
            await query.edit_message_text(
                "*BYOK Providers*\nSet a key first with `/setkey`",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if category == "custom":
            _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
            custom_endpoints = {k: v for k, v in custom_keys.items() if isinstance(v, dict) and v.get("custom")}
            if not custom_endpoints:
                await query.edit_message_text(
                    "*Custom Endpoints*\n\nNo custom endpoints added.\nUse `/setkey <name> <base_url> <key>` to add one.",
                    reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN
                )
                return
            keyboard = []
            for group_name in custom_endpoints:
                keyboard.append([InlineKeyboardButton(f"⚙️ Browse {group_name} models", callback_data=f"browse_{group_name}_0")])
            keyboard.append([InlineKeyboardButton("Back", callback_data="modelcat_back")])
            await query.edit_message_text(
                "*Custom Endpoints*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

    async def browse_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        _, group, page = query.data.split("_")
        page = int(page)

        _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
        key_data = custom_keys.get(group)
        if not key_data:
            await query.edit_message_text(
                f"Set a key first: `/setkey {group} <your_key>`", parse_mode=ParseMode.MARKDOWN
            )
            return

        if isinstance(key_data, dict) and key_data.get("custom"):
            api_key = key_data["api_key"]
            endpoint_meta = key_data
            label = group
        else:
            api_key = key_data
            endpoint_meta = None
            label = BROWSE_GROUPS.get(group, {}).get("label", group)

        models = await self.ai.get_group_models(group, api_key, endpoint_meta)
        if not models:
            await query.edit_message_text(f"Could not fetch {label} models. Try again shortly.")
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
            f"*{label} Models* (page {page + 1}/{total_pages})",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )

    async def browse_set_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        _, group, index = query.data.split("_")
        index = int(index)

        history, _, custom_keys, persona = await self.db.get_user_data(chat_id)
        key_data = custom_keys.get(group)
        if not key_data:
            await query.edit_message_text(f"Set a key first: `/setkey {group} <your_key>`", parse_mode=ParseMode.MARKDOWN)
            return

        if isinstance(key_data, dict) and key_data.get("custom"):
            api_key = key_data["api_key"]
            endpoint_meta = key_data
        else:
            api_key = key_data
            endpoint_meta = None

        models = await self.ai.get_group_models(group, api_key, endpoint_meta)
        if index >= len(models):
            await query.edit_message_text("That model list has refreshed, please run /model again.")
            return

        model_id = models[index]["id"]
        await self.db.save_user_data(chat_id, history, f"{group}:{model_id}", custom_keys, persona)
        await query.edit_message_text(f"AI Engine changed to: *{model_id}*", parse_mode=ParseMode.MARKDOWN)

    async def model_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        data = query.data

        if data.startswith("setmodel_"):
            selected = data.split("_")[1]
            if selected in AI_PROVIDERS:
                history, _, custom_keys, persona = await self.db.get_user_data(chat_id)
                await self.db.save_user_data(chat_id, history, selected, custom_keys, persona)
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

        if not self.is_admin(chat_id) and not await self.db.is_user_allowed(chat_id):
            await update.message.reply_text(
                "Access denied. Contact an admin to get access."
            )
            return

        if now - self.last_msg_time.get(chat_id, 0) < self.min_interval:
            await update.message.reply_text("Slow down a bit, please.")
            return
        self.last_msg_time[chat_id] = now

        if not self._check_daily_limit(chat_id):
            await update.message.reply_text(f"Daily limit of {self.daily_limit} messages reached. Try again tomorrow.")
            return

        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        persona_data = PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])
        system_prompt = persona_data["prompt"]

        self._last_user_msg[chat_id] = user_text
        history.append({"role": "user", "content": user_text})
        if len(history) > self.max_history * 2:
            history[:] = history[-(self.max_history * 2):]

        messages = [{"role": "system", "content": system_prompt}] + history
        typing_task = asyncio.create_task(self._keep_typing(chat_id, context))
        cancel_event = asyncio.Event()
        self._cancel_flags[chat_id] = cancel_event

        providers = self.ai.get_fallback_chain(active_model, custom_keys)
        reply = None

        for provider in providers:
            if cancel_event.is_set():
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
            except AuthError as e:
                reply = f"Authentication error: your saved key for `{e.group}` is invalid or expired.\nUpdate it: `/setkey {e.group} <new_key>`"
                history.pop()
                break
            except RateLimitError as e:
                logger.warning(f"Rate limited by {e.provider_name}, trying fallback...")
                continue
            except Exception as e:
                logger.error(f"API Error with {provider['name']}: {e}")
                continue

        if reply is None:
            reply = "All providers are currently unavailable. Please try again later."
            if history and history[-1]["role"] == "user":
                history.pop()

        self._cancel_flags.pop(chat_id, None)
        typing_task.cancel()
        await send_reply(update, reply)

    # --- LIFECYCLE ---
    async def post_init(self, application: Application) -> None:
        await self.db.connect()
        self._validate_config()
        logger.info("KevlarBot AI initialized.")

    async def post_shutdown(self, application: Application) -> None:
        await self.db.close()
        await self.ai.close()


def main():
    bot = MimoAIBot()
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(bot.post_init).post_shutdown(bot.post_shutdown).build()

    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(bot.admin_broadcast_conv, pattern="^admin_broadcast$"),
            CallbackQueryHandler(bot.admin_adduser_conv, pattern="^admin_adduser$"),
            CallbackQueryHandler(bot.admin_removeuser_conv, pattern="^admin_removeuser$"),
        ],
        states={
            WAITING_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.receive_broadcast)],
            WAITING_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.receive_adduser_input)],
            WAITING_REMOVE_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.receive_removeuser_input)],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel_conv)],
    )

    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("new", bot.new_session))
    app.add_handler(CommandHandler("chat", bot.chat_cmd))
    app.add_handler(CommandHandler("reset", bot.reset))
    app.add_handler(CommandHandler("retry", bot.retry_cmd))
    app.add_handler(CommandHandler("cancel", bot.cancel_cmd))
    app.add_handler(CommandHandler("model", bot.model_cmd))
    app.add_handler(CommandHandler("setkey", bot.setkey_cmd))
    app.add_handler(CommandHandler("persona", bot.persona_cmd))
    app.add_handler(CommandHandler("help", bot.help_cmd))
    app.add_handler(CommandHandler("admin", bot.admin_cmd))
    app.add_handler(CommandHandler("settings", bot.settings_cmd))
    app.add_handler(CommandHandler("broadcast", bot.broadcast_cmd))
    app.add_handler(CommandHandler("adduser", bot.adduser_cmd))
    app.add_handler(CommandHandler("removeuser", bot.removeuser_cmd))

    app.add_handler(admin_conv)
    app.add_handler(CallbackQueryHandler(bot.admin_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(bot.settings_callback, pattern="^settings_"))
    app.add_handler(CallbackQueryHandler(bot.model_category_callback, pattern="^modelcat_"))
    app.add_handler(CallbackQueryHandler(bot.model_callback, pattern="^setmodel_"))
    app.add_handler(CallbackQueryHandler(bot.persona_callback, pattern="^setpersona_"))
    app.add_handler(CallbackQueryHandler(bot.help_callback, pattern="^help_"))
    app.add_handler(CallbackQueryHandler(bot.browse_callback, pattern="^browse_"))
    app.add_handler(CallbackQueryHandler(bot.browse_set_callback, pattern="^browseset_"))

    app.add_handler(InlineQueryHandler(bot.inline_query_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
