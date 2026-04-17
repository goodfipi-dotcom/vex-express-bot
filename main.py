"""
VEX EXPRESS Bot — точка входа.
Запускает Telegram-бота (Aiogram 3) + API-сервер (FastAPI) + планировщик уведомлений.
"""

import asyncio
import logging

from aiogram import Dispatcher
import uvicorn

from bot.instance import bot
from bot.handlers import router
from api.routes import app as fastapi_app
from db.database import init_db
from services.marzban import marzban
from services.notifier import run_expiry_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vex")


async def start_bot():
    """Запуск Telegram-бота"""
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
    await init_db()
    logger.info("📦 База данных инициализирована")

    try:
        await asyncio.gather(
            start_bot(),
            start_api(),
            run_expiry_scheduler(bot),
        )
    finally:
        await marzban.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
