from kevlarbot.config import TELEGRAM_TOKEN, logger
from kevlarbot.database import KevlarDB as KevlarDB
from kevlarbot.ai_client import AIClient as AIClient

from kevlarbot.handlers.base import KevlarBotBase
from kevlarbot.handlers.admin import AdminHandlers, WAITING_BROADCAST, WAITING_ADD_USER, WAITING_REMOVE_USER
from kevlarbot.handlers.chat import ChatHandlers
from kevlarbot.handlers.models import ModelHandlers
from kevlarbot.handlers.settings import SettingsHandlers
from kevlarbot.handlers.help import HelpHandlers

from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    InlineQueryHandler, filters, ConversationHandler,
)


class KevlarBot(
    HelpHandlers,
    SettingsHandlers,
    ModelHandlers,
    ChatHandlers,
    AdminHandlers,
    KevlarBotBase,
):
    """KevlarBot AI — multi-provider Telegram chatbot assembled from handler mixins."""

    async def post_init(self, application: Application) -> None:
        await self.db.connect()
        self._validate_config()
        logger.info("KevlarBot AI initialized.")

    async def post_shutdown(self, application: Application) -> None:
        await self.db.close()
        await self.ai.close()


def main():
    bot = KevlarBot()
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(bot.post_init)
        .post_shutdown(bot.post_shutdown)
        .build()
    )

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
