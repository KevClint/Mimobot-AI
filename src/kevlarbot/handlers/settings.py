from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from kevlarbot.providers import PERSONAS
from kevlarbot.utils import send_reply, make_bar


class SettingsHandlers:
    """Settings, persona, session, and info commands."""

    async def info_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        history, active_model, custom_keys, persona = await self.db.get_user_data(chat_id)
        provider = self.ai.resolve_provider(active_model, custom_keys)
        persona_label = self._get_persona_label(persona)
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
        text = await self._user_info_text(chat_id, include_history=True)
        if len(text) > 4000:
            await send_reply(update, text)
        else:
            await update.message.reply_text(text)

    async def persona_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        _, _, _, current = await self.db.get_user_data(chat_id)
        keyboard = []
        for key, p in PERSONAS.items():
            prefix = "> " if key == current else ""
            keyboard.append([InlineKeyboardButton(f"{prefix}{p['label']}", callback_data=f"setpersona_{key}")])
        await update.message.reply_text(
            "*Choose a persona:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def persona_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        key = query.data.split("_", 1)[1]
        if key in PERSONAS:
            history, active_model, custom_keys, _ = await self.db.get_user_data(chat_id)
            await self.db.save_user_data(chat_id, history, active_model, custom_keys, key)
            await query.edit_message_text(f"Persona set to: *{self._get_persona_label(key)}*", parse_mode=ParseMode.MARKDOWN)

    async def settings_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._access_guard(update):
            return

        chat_id = update.message.chat.id
        text = await self._user_info_text(chat_id)
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
        if not await self._callback_access_guard(query):
            return

        section = query.data.split("_", 1)[1]
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="settings_root")]])

        if section == "root":
            text = await self._user_info_text(chat_id)
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
            keyboard = self._model_category_keyboard()
            keyboard.append([InlineKeyboardButton("Back", callback_data="settings_root")])
            await query.edit_message_text(
                "*Select your preferred AI Model:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
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
                "*Choose a persona:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if section == "keys":
            _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
            keys_list = "\n".join(f"\u2022 `{k}`" for k in custom_keys) if custom_keys else "No keys saved."
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
            text = await self._user_info_text(chat_id, include_history=True)
            await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
            return
