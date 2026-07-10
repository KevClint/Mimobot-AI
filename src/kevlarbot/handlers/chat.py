import asyncio
import time

from telegram import InlineQueryResultArticle, InputTextMessageContent, Update, constants
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from kevlarbot.ai_client import AuthError
from kevlarbot.providers import DEFAULT_PERSONA
from kevlarbot.utils import safe_delete, send_reply

WELCOME_TEXT = (
    "*Hi, I am your AI Assistant.*\n\n"
    "Free and BYOK (Bring Your Own Key) models are available.\n\n"
    "Quick start:\n"
    "/model - choose your AI engine\n"
    "/persona - change how I behave\n"
    "/session - view your current session\n"
    "/help - full command list"
)


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
                await self.db.set_user_allowed(chat_id, True)
            await self.db.save_user_data(chat_id, [], "mimo", {}, DEFAULT_PERSONA, username, display_name)
            await update.message.reply_text(WELCOME_TEXT, parse_mode=ParseMode.MARKDOWN)
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
        await update.message.reply_text(WELCOME_TEXT, parse_mode=ParseMode.MARKDOWN)

    async def new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        await self.db.clear_history(chat_id)
        await safe_delete(update.message)
        await context.bot.send_message(
            chat_id,
            "Fresh session started. Memory cleared, keys and model kept.",
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

        self._last_user_msg[chat_id] = user_text

        if user_text.lower().strip() in ("continue", "continue:"):
            user_text = "Please continue your previous response from where you left off."

        typing_task = asyncio.create_task(self._keep_typing(chat_id, context))
        cancel_event = asyncio.Event()
        self._cancel_flags[chat_id] = cancel_event

        try:
            reply = await self._run_ai_chat(chat_id, user_text, cancel_event=cancel_event)
        except AuthError as e:
            reply = (
                f"Authentication error: your saved key for `{e.group}` is invalid or expired.\n"
                f"Update it: `/setkey {e.group} <new_key>`"
            )
        finally:
            self._cancel_flags.pop(chat_id, None)
            typing_task.cancel()

        if reply is None:
            reply = "All providers are currently unavailable. Please try again later."

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

        prompt = text[len("/chat") :].strip()
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
