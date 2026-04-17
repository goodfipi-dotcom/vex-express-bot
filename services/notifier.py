"""
VEX EXPRESS — сервис уведомлений об истечении подписки.

Запускается фоновой задачей из main.py (каждые 30 минут или по cron).
Копирует поведение @ultimavpnbot: уведомить за 3 дня, за 1 день и в день истечения.

Интеграция с ботом:
    from services.notifier import run_expiry_scheduler
    asyncio.create_task(run_expiry_scheduler(bot))
"""

import asyncio
import logging
from datetime import datetime
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import WEBAPP_URL, SUPPORT_USERNAME
from db.database import get_users_for_expiry_notify, mark_notified_expiry

logger = logging.getLogger("vex.notifier")

# Маска уведомлений: 1=за 3 дня, 2=за 1 день, 4=в день истечения
NOTIFY_MASKS = {3: 1, 1: 2, 0: 4}

TEXTS = {
    3: (
        "⏳ <b>Подписка истекает через 3 дня</b>\n"
        "Продлите сейчас — не теряйте VPN. Откройте VEX и выберите тариф."
    ),
    1: (
        "⚠️ <b>Подписка истекает завтра</b>\n"
        "Продлите, чтобы не прерывать соединение."
    ),
    0: (
        "🔕 <b>Подписка истекла сегодня</b>\n"
        "Продлите, чтобы восстановить доступ — это займёт минуту."
    ),
}


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Продлить подписку", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")],
    ])


async def send_expiry_notifications(bot: Bot):
    """Один проход: для каждого порога (3, 1, 0 дней) найти юзеров и разослать."""
    for days_left, mask in NOTIFY_MASKS.items():
        users = await get_users_for_expiry_notify(days_left)
        for u in users:
            # Если этот бит уже выставлен — пропустить
            notified = u["notified_expiry"] or 0
            if notified & mask:
                continue

            try:
                await bot.send_message(
                    u["telegram_id"],
                    TEXTS[days_left],
                    reply_markup=_keyboard(),
                    parse_mode="HTML",
                )
                await mark_notified_expiry(u["telegram_id"], days_left)
                logger.info(f"Уведомление отправлено: tg_id={u['telegram_id']}, days_left={days_left}")
            except Exception as e:
                logger.warning(f"Не смогли отправить: tg_id={u['telegram_id']}, err={e}")
            await asyncio.sleep(0.05)  # не долбить Telegram API


async def run_expiry_scheduler(bot: Bot, interval_sec: int = 1800):
    """Фоновый цикл — каждые 30 минут проверять и рассылать.
    Запускать в main.py: asyncio.create_task(run_expiry_scheduler(bot))"""
    logger.info(f"🕒 Планировщик уведомлений запущен (раз в {interval_sec // 60} мин)")
    while True:
        try:
            await send_expiry_notifications(bot)
        except Exception as e:
            logger.exception(f"Ошибка в планировщике: {e}")
        await asyncio.sleep(interval_sec)
