import io
from typing import List

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest

from config import TELEGRAM_MSG_LIMIT


async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


def split_message(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> List[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_pos = text.rfind("\n\n", 0, limit)
        if split_pos == -1:
            split_pos = text.rfind("\n", 0, limit)
        if split_pos == -1:
            split_pos = text.rfind(". ", 0, limit)
        if split_pos == -1:
            split_pos = limit
        else:
            split_pos += 1
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    return chunks


async def send_reply(update: Update, text: str, **kwargs):
    if len(text) <= TELEGRAM_MSG_LIMIT:
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
        except BadRequest:
            await update.message.reply_text(text, **kwargs)
        return

    chunks = split_message(text)
    if len(chunks) <= 5:
        for chunk in chunks:
            try:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, **kwargs)
            except BadRequest:
                await update.message.reply_text(chunk, **kwargs)
    else:
        await send_as_file(update, text)


async def send_as_file(update: Update, text: str):
    ext = "py" if "def " in text or "import " in text else "txt"
    bio = io.BytesIO(text.encode("utf-8"))
    bio.name = f"response.{ext}"
    await update.message.reply_document(
        document=bio,
        caption="Response was long, so I sent it as a file."
    )


def make_bar(used: int, total: int, width: int = 10) -> str:
    used = max(0, min(used, total))
    filled = round((used / total) * width) if total else 0
    return "█" * filled + "░" * (width - filled)
