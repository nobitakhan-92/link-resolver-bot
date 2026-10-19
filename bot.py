import asyncio
import os
from urllib.parse import urlsplit

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest

from resolver import resolve_url as resolve_link

TOKEN = os.environ.get("BOT_TOKEN", "").strip()

if not TOKEN:
    raise RuntimeError("Set the BOT_TOKEN environment variable.")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def get_url(text: str) -> str | None:
    """Extract one URL without accepting arbitrary text as a URL."""
    for part in text.split():
        candidate = part.strip(" <>\"'()[]{}.,")
        try:
            parsed = urlsplit(candidate)
            if (
                parsed.scheme.lower() in ("http", "https")
                and parsed.hostname
            ):
                return candidate
        except ValueError:
            continue
    return None


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Welcome to Link Resolver!\n\n"
        "Send me an HTTP(S) short link and I'll try to "
        "resolve its redirect destination.\n\n"
        "Note: some services require manual verification."
    )


@dp.message(F.text)
async def handle_link(message: Message):
    url = get_url(message.text or "")

    if not url:
        await message.answer(
            "Please send a valid HTTP(S) link."
        )
        return

    status = await message.answer("🔎 Checking the link...")

    result = await resolve_link(url)

    if not result.get("ok"):
        await status.edit_text(
            "❌ Couldn't resolve this link.\n\n"
            + result.get("message", "Unknown error")
        )
        return

    destination = result["destination_url"]

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌐 Open destination",
                    url=destination,
                )
            ]
        ]
    )

    text = (
        "✅ Link checked\n\n"
        f"HTTP status: {result['status_code']}\n"
        f"Redirects followed: {result['redirects']}\n\n"
        f"Destination:\n{destination}\n\n"
        f"Result: {result['message']}"
    )

    # Telegram messages have a length limit.
    if len(text) > 4000:
        text = (
            "✅ Link checked\n\n"
            f"Destination:\n{destination[:3500]}"
        )

    try:
        await status.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        await message.answer(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
