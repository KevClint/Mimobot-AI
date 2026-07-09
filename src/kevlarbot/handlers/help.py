from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest


class HelpHandlers:
    """Help command and callback navigation."""

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("Commands", callback_data="help_commands")],
            [InlineKeyboardButton("How to get API Keys", callback_data="help_keys")],
            [InlineKeyboardButton("Contact Admin", callback_data="help_admin")],
        ]
        await update.message.reply_text(
            "*Help Menu*\nChoose a topic:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
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
            await query.edit_message_text(
                "*Help Menu*\nChoose a topic:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
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
