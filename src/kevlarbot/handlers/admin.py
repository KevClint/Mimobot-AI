from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

WAITING_BROADCAST, WAITING_ADD_USER, WAITING_REMOVE_USER = range(3)


class AdminHandlers:
    """Admin panel, broadcast, user management, and conversation handlers."""

    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return
        count = await self.db.user_count()
        await update.message.reply_text(f"*Bot Stats*\nRegistered users: `{count}`", parse_mode=ParseMode.MARKDOWN)

    async def broadcast_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return
        text = " ".join(context.args)
        if not text:
            await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN)
            return

        ids = await self.db.all_chat_ids()
        status = await update.message.reply_text(f"Sending to {len(ids)} users...")
        sent, failed = await self._broadcast_message(text, context)
        await status.edit_text(f"Broadcast done. Sent: {sent}, Failed: {failed}")

    async def adduser_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return
        result = await self._resolve_target(update, context)
        if not result:
            return
        target_id, target_label = result
        await self.db.set_user_allowed(target_id, True)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been whitelisted.")

    async def removeuser_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return
        result = await self._resolve_target(update, context)
        if not result:
            return
        target_id, target_label = result
        await self.db.set_user_allowed(target_id, False)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been removed.")

    async def listusers_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return
        users = await self.db.get_all_users()
        if not users:
            await update.message.reply_text("No users found.")
            return
        await update.message.reply_text(self._format_user_list(users))

    async def admin_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return
        text, keyboard = await self._admin_panel(update.message.chat.id)
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    async def admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not await self._callback_admin_guard(query):
            return

        section = query.data.split("_", 1)[1]
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_root")]])

        if section == "root":
            text, keyboard = await self._admin_panel(query.message.chat.id)
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
            return

        if section == "stats":
            text = await self._admin_stats_text()
            await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
            return

        if section == "users":
            users = await self.db.get_all_users()
            if not users:
                await query.edit_message_text("No users found.", reply_markup=back_kb)
                return
            text = self._format_user_list(users, limit=8)
            await query.edit_message_text(text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
            return

        if section == "broadcast":
            await query.edit_message_text("Type your broadcast message:", reply_markup=back_kb)
            return

        if section == "adduser":
            await query.edit_message_text("Send me the username (e.g. @johndoe) or chat ID:", reply_markup=back_kb)
            return

        if section == "removeuser":
            await query.edit_message_text("Send me the username (e.g. @johndoe) or chat ID:", reply_markup=back_kb)
            return

    # --- Conversation handlers ---

    async def admin_broadcast_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not await self._callback_admin_guard(query):
            return ConversationHandler.END
        await query.edit_message_text("Type your broadcast message:")
        return WAITING_BROADCAST

    async def receive_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return ConversationHandler.END
        text = update.message.text
        ids = await self.db.all_chat_ids()
        status = await update.message.reply_text(f"Sending to {len(ids)} users...")
        sent, failed = await self._broadcast_message(text, context)
        await status.edit_text(f"Broadcast done. Sent: {sent}, Failed: {failed}")
        return ConversationHandler.END

    async def admin_adduser_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not await self._callback_admin_guard(query):
            return ConversationHandler.END
        await query.edit_message_text("Send me the username (e.g. @johndoe) or chat ID:")
        return WAITING_ADD_USER

    async def receive_adduser_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return ConversationHandler.END

        arg = update.message.text.strip()
        target_id = None
        target_label = None

        if arg.lstrip("-").isdigit():
            target_id = int(arg)
            if not await self.db.get_user_by_id(target_id):
                await update.message.reply_text(
                    f"ID `{target_id}` not found. They need to message the bot first.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return ConversationHandler.END
        else:
            clean = arg.lstrip("@").lower()
            target_id = await self.db.get_user_by_username(clean)
            target_label = clean
            if not target_id:
                await update.message.reply_text(
                    f"User `{arg}` not found. They need to message the bot first.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return ConversationHandler.END

        await self.db.set_user_allowed(target_id, True)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been whitelisted.")
        return ConversationHandler.END

    async def admin_removeuser_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not await self._callback_admin_guard(query):
            return ConversationHandler.END
        await query.edit_message_text("Send me the username (e.g. @johndoe) or chat ID:")
        return WAITING_REMOVE_USER

    async def receive_removeuser_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._admin_guard(update):
            return ConversationHandler.END

        arg = update.message.text.strip()
        target_id = None
        target_label = None

        if arg.lstrip("-").isdigit():
            target_id = int(arg)
            if not await self.db.get_user_by_id(target_id):
                await update.message.reply_text(
                    f"ID `{target_id}` not found.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return ConversationHandler.END
        else:
            clean = arg.lstrip("@").lower()
            target_id = await self.db.get_user_by_username(clean)
            target_label = clean
            if not target_id:
                await update.message.reply_text(
                    f"User `{arg}` not found.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return ConversationHandler.END

        await self.db.set_user_allowed(target_id, False)
        label = f"@{target_label}" if target_label else str(target_id)
        await update.message.reply_text(f"User {label} has been removed.")
        return ConversationHandler.END

    async def cancel_conv(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END
