import asyncio
import os

import uvicorn
from bot import bot, dp


async def main():
    config = uvicorn.Config(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        log_level="info",
    )
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(
            server.serve(),
            dp.start_polling(bot),
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
