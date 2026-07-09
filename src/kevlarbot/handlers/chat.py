import os
import time
import asyncio

from telegram import Update, constants, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from kevlarbot.providers import PERSONAS, DEFAULT_PERSONA
from kevlarbot.ai_client import AuthError, RateLimitError
from kevlarbot.utils import safe_delete, send_reply
from kevlarbot.config import logger


class ChatHandlers:
    """Chat commands, message handling, and inline query support."""

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
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if not exists:
            await self.db.save_user_data(chat_id, [], "mimo", {}, DEFAULT_PERSONA, username, display_name)
            await update.message.reply_text("Access denied. Contact an admin to get access.")
            return

        if not await self.db.is_user_allowed(chat_id):
            await update.message.reply_text("Access denied. Contact an admin to get access.")
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
            parse_mode=ParseMode.MARKDOWN,
        )

    async def new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        await self.db.clear_history(chat_id)
        await safe_delete(update.message)
        await context.bot.send_message(
            chat_id, "Fresh session started. Memory cleared, keys and model kept.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def chat_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id

        if not await self._access_guard(update):
            return

        prompt = " ".join(context.args) if context.args else ""
        if not prompt:
            await update.message.reply_text("Usage: `/chat <your message>`", parse_mode=ParseMode.MARKDOWN)
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

        reply = await self._run_ai_chat(chat_id, prompt)
        if reply is None:
            reply = "AI is currently unavailable. Try again later."

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
            await update.message.reply_text("Access denied. Contact an admin to get access.")
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
            except RateLimitError:
                logger.warning(f"Rate limited by {provider.get('name', 'unknown')}, trying fallback...")
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
                        "Usage: `@kvlraiBot /chat <your message>`", parse_mode=ParseMode.MARKDOWN
                    ),
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
                    ),
                )
            ]
            await query.answer(results, cache_time=0)
            return

        thinking_results = [
            InlineQueryResultArticle(
                id="thinking",
                title="Thinking...",
                description=prompt[:100],
                input_message_content=InputTextMessageContent("Thinking..."),
            )
        ]
        await query.answer(thinking_results, cache_time=0)

        reply = await self._run_ai_chat(chat_id, prompt)
        if reply is None:
            reply = "AI is currently unavailable. Try again later."

        source_chat = query.inline_message_id
        if source_chat:
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=f"*{prompt}*\n\n{reply}", parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest:
                await context.bot.send_message(chat_id=chat_id, text=reply)
