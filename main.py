"""
VEX EXPRESS Bot — точка входа.
Запускает Telegram-бота (Aiogram 3) и API-сервер (FastAPI) параллельно.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
import uvicorn

from config import BOT_TOKEN
from bot.handlers import router
from api.routes import app as fastapi_app
from db.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vex")


async def start_bot():
    """Запуск Telegram-бота"""
    bot = Bot(token=BOT_TOKEN, default={"parse_mode": ParseMode.HTML})
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("🤖 Бот VEX EXPRESS запущен")
    await dp.start_polling(bot)


async def start_api():
    """Запуск FastAPI-сервера для Mini App"""
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logger.info("🌐 API-сервер запущен на :8080")
    await server.serve()


async def main():
    # Инициализация БД
    await init_db()
    logger.info("📦 База данных инициализирована")

    # Запускаем бота и API параллельно
    await asyncio.gather(
        start_bot(),
        start_api(),
    )


if __name__ == "__main__":
    asyncio.run(main())
