from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from kevlarbot.config import OR_PAGE_SIZE
from kevlarbot.providers import AI_PROVIDERS, BROWSE_GROUPS
from kevlarbot.utils import safe_delete


class ModelHandlers:
    """Model selection, browsing, and API key management."""

    async def model_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat.id
        await self.db.get_user_data(chat_id)
        keyboard = self._model_category_keyboard()
        await update.message.reply_text(
            "*Select your preferred AI Model:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def model_category_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        category = query.data.split("_", 1)[1]
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="modelcat_back")]])

        if category == "back":
            keyboard = self._model_category_keyboard()
            keyboard.append([InlineKeyboardButton("Back", callback_data="settings_root")])
            await query.edit_message_text(
                "*Select your preferred AI Model:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if category == "free":
            _, active_model, _, _ = await self.db.get_user_data(chat_id)
            keyboard = []
            for key, provider in AI_PROVIDERS.items():
                prefix = "> " if key == active_model else ""
                keyboard.append([InlineKeyboardButton(f"{prefix}\U0001f193 {provider['name']}", callback_data=f"setmodel_{key}")])
            keyboard.append([InlineKeyboardButton("Back", callback_data="modelcat_back")])
            await query.edit_message_text(
                "*Free Models*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )
            return

        if category == "byok":
            keyboard = []
            for group, g in BROWSE_GROUPS.items():
                keyboard.append([InlineKeyboardButton(f"\U0001f511 Browse {g['label']} models", callback_data=f"browse_{group}_0")])
            keyboard.append([InlineKeyboardButton("Back", callback_data="modelcat_back")])
            await query.edit_message_text(
                "*BYOK Providers*\nSet a key first with `/setkey`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if category == "custom":
            _, _, custom_keys, _ = await self.db.get_user_data(chat_id)
            custom_endpoints = {k: v for k, v in custom_keys.items() if isinstance(v, dict) and v.get("custom")}
            if not custom_endpoints:
                await query.edit_message_text(
                    "*Custom Endpoints*\n\nNo custom endpoints added.\nUse `/setkey <name> <base_url> <key>` to add one.",
                    reply_markup=back_kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            keyboard = []
            for group_name in custom_endpoints:
                keyboard.append([InlineKeyboardButton(f"\u2699\ufe0f Browse {group_name} models", callback_data=f"browse_{group_name}_0")])
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
        keyboard = [
            [InlineKeyboardButton(m["name"][:60], callback_data=f"browseset_{group}_{start + i}")]
            for i, m in enumerate(chunk)
        ]

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
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
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
            await query.edit_message_text(
                f"Set a key first: `/setkey {group} <your_key>`", parse_mode=ParseMode.MARKDOWN
            )
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
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await status_msg.edit_text(f"Invalid key: rejected by `{group_name}`. Check the URL and key.")

        else:
            await context.bot.send_message(
                chat_id,
                "Usage:\n"
                "`/setkey <provider> <key>`\n"
                "`/setkey <name> <base_url> <key>` (custom endpoint)",
                parse_mode=ParseMode.MARKDOWN,
            )
