"""
VEX EXPRESS — Telegram Bot handlers.

Философия (скопировано с @ultimavpnbot):
— /start отправляет ОДНО короткое сообщение с одной главной кнопкой «Открыть» (WebApp)
— Все сложные экраны (тарифы, гайды, профиль) — в Mini App
— Deep-links: ?start=ref_<uid> (реферал) | ?startapp=buy_1month/3months/1year | ?startapp=refer
— Команды: /start, /help, /refer, /status
— Успешная оплата: короткое подтверждение + кнопка открыть Mini App
— Уведомления об истечении: отправляет services/notifier.py через планировщик
"""

from pathlib import Path

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    FSInputFile,
)
from aiogram.filters import CommandStart, Command
from datetime import datetime, timedelta

from config import PLANS, PAYMENT_PROVIDER_TOKEN, WEBAPP_URL, SUPPORT_USERNAME
from db.database import (
    create_or_update_user,
    get_user,
    add_transaction,
    update_subscription,
    transaction_exists,
    grant_referral_bonus,
    user_payment_count,
)
from services.marzban import marzban, MarzbanError

router = Router()

# Путь к приветственному видео и кэш file_id (чтобы не грузить файл каждый раз)
WELCOME_VIDEO_PATH = Path(__file__).resolve().parent.parent / "assets" / "welcome.mov"
_welcome_video_file_id: str | None = None


# ═══════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════════

def webapp_button(label: str = "⚡ Открыть VEX", path: str = "") -> InlineKeyboardButton:
    """Кнопка открытия Mini App. path — подставляется в конец WEBAPP_URL для deep-link."""
    url = f"{WEBAPP_URL.rstrip('/')}/{path.lstrip('/')}" if path else WEBAPP_URL
    return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))


def main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура: одна большая WebApp-кнопка + строчка с поддержкой."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [webapp_button("⚡ Открыть VEX")],
        [InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")],
    ])


def payment_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [webapp_button("⚡ Скопировать VPN-ключ")],
        [InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")],
    ])


# ═══════════════════════════════════════════════════════════════
# ТЕКСТЫ
# ═══════════════════════════════════════════════════════════════

START_TEXT = (
    "<b>Добро пожаловать в VEX VPN</b>\n"
    "\n"
    "Скорость. Качество. Безопасность — наши главные преимущества!"
)

HELP_TEXT = (
    "<b>Команды VEX</b>\n"
    "\n"
    "/start — главное меню\n"
    "/status — состояние вашей подписки\n"
    "/refer — реферальная ссылка (+7 дней за друга)\n"
    "/help — это сообщение\n"
    "\n"
    f"Нужна помощь? @{SUPPORT_USERNAME}"
)


# ═══════════════════════════════════════════════════════════════
# Приветствие: видео + текст + кнопка в одном сообщении
# ═══════════════════════════════════════════════════════════════

async def _send_welcome(message: Message) -> None:
    """
    Приветствие в стиле Ultima:
    1) отдельное сообщение с видео (без caption)
    2) отдельное сообщение с текстом и кнопками
    После первой отправки кэшируем file_id, чтобы не перезаливать файл.
    """
    global _welcome_video_file_id

    if _welcome_video_file_id:
        video = _welcome_video_file_id
    elif WELCOME_VIDEO_PATH.exists():
        video = FSInputFile(WELCOME_VIDEO_PATH)
    else:
        video = None

    if video is not None:
        sent = await message.answer_video(video=video, supports_streaming=True)
        if _welcome_video_file_id is None and sent.video:
            _welcome_video_file_id = sent.video.file_id

    await message.answer(START_TEXT, reply_markup=main_keyboard(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════
# /start — с deep-link парсингом
# ═══════════════════════════════════════════════════════════════

@router.message(CommandStart(deep_link=True))
async def cmd_start_with_args(message: Message):
    """Обработка /start с параметром: ref_<id> | buy_<plan_id>"""
    user = message.from_user
    args = message.text.split(maxsplit=1)
    payload = args[1].strip() if len(args) > 1 else ""

    referrer_id = None
    if payload.startswith("ref_"):
        try:
            referrer_id = int(payload[4:])
        except ValueError:
            referrer_id = None

    await create_or_update_user(user.id, user.username or "", user.first_name or "", referrer_id)

    # Deep-link на конкретный тариф — открываем invoice сразу
    if payload.startswith("buy_") and payload[4:] in PLANS and PAYMENT_PROVIDER_TOKEN:
        await _send_invoice(message, payload[4:])
        return

    await _send_welcome(message)


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    await create_or_update_user(user.id, user.username or "", user.first_name or "")
    await _send_welcome(message)


# ═══════════════════════════════════════════════════════════════
# /help
# ═══════════════════════════════════════════════════════════════

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════
# /status — состояние подписки
# ═══════════════════════════════════════════════════════════════

@router.message(Command("status"))
async def cmd_status(message: Message):
    user_row = await get_user(message.from_user.id)
    if not user_row or not user_row["subscription_end"]:
        await message.answer(
            "<b>Подписка не оформлена</b>\n"
            "Откройте VEX и выберите тариф.",
            reply_markup=main_keyboard(),
            parse_mode="HTML",
        )
        return

    end = datetime.fromisoformat(user_row["subscription_end"])
    days_left = (end - datetime.now()).days

    if end < datetime.now():
        text = (
            "⚠️ <b>Подписка истекла</b>\n"
            f"Дата окончания: {end.strftime('%d.%m.%Y')}\n\n"
            "Продлите подписку — откройте VEX."
        )
    else:
        text = (
            f"✅ <b>Подписка активна</b>\n"
            f"Действует до: <b>{end.strftime('%d.%m.%Y')}</b> ({days_left} дн.)\n\n"
            f"Ключ подключения — в Mini App."
        )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════
# /refer — реферальная ссылка
# ═══════════════════════════════════════════════════════════════

@router.message(Command("refer"))
async def cmd_refer(message: Message):
    uid = message.from_user.id
    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"

    user_row = await get_user(uid)
    bonus_total = user_row["bonus_days_total"] if user_row and user_row["bonus_days_total"] else 0

    text = (
        "<b>Реферальная программа</b>\n"
        "\n"
        "За каждого друга, который оформит подписку по вашей ссылке,\n"
        "вам <b>+7 дней</b> бесплатно.\n"
        "\n"
        f"Ваша ссылка:\n<code>{ref_link}</code>\n"
        "\n"
        f"Всего получено бонусов: <b>{bonus_total} дн.</b>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📤 Поделиться ссылкой",
            url=f"https://t.me/share/url?url={ref_link}&text=VEX%20VPN%20—%20быстрый%20и%20без%20рекламы",
        )
    ]])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════
# Покупка тарифа (inline callback)
# ═══════════════════════════════════════════════════════════════

async def _send_invoice(message: Message, plan_id: str):
    name, price, days = PLANS[plan_id]

    if not PAYMENT_PROVIDER_TOKEN:
        await message.answer(
            "Платежи ещё не настроены. Обратитесь в поддержку.",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer_invoice(
        title=f"VEX EXPRESS — {name}",
        description=f"Безлимитный VPN на {days} дней. Высокая скорость, все устройства.",
        payload=f"{plan_id}:{message.from_user.id}",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=name, amount=price)],
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy_plan(callback: CallbackQuery):
    plan_id = callback.data.split(":")[1]
    if plan_id not in PLANS:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    await _send_invoice(callback.message, plan_id)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# Pre-checkout
# ═══════════════════════════════════════════════════════════════

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


# ═══════════════════════════════════════════════════════════════
# Успешная оплата
# ═══════════════════════════════════════════════════════════════

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    charge_id = payment.telegram_payment_charge_id
    payload = payment.invoice_payload  # "plan_id:user_id"
    plan_id = payload.split(":")[0]

    if plan_id not in PLANS:
        return

    # Защита от двойной обработки
    if await transaction_exists(charge_id):
        return

    name, price, days = PLANS[plan_id]
    user = message.from_user
    marzban_username = f"vex_{user.id}"

    # Первая ли это оплата — решает, начислить ли бонус рефереру
    is_first_payment = (await user_payment_count(user.id)) == 0

    try:
        await marzban.create_user(marzban_username, days)
        vless_link = await marzban.get_vless_link(marzban_username)
        end_date = datetime.now() + timedelta(days=days)

        await update_subscription(user.id, vless_link or "", marzban_username, end_date)
        await add_transaction(user.id, plan_id, name, price // 100, "paid", charge_id)

        # Реферальный бонус — только при первой оплате приглашённого
        if is_first_payment:
            referrer_id = await grant_referral_bonus(user.id, days=7)
            if referrer_id:
                try:
                    await message.bot.send_message(
                        referrer_id,
                        "🎁 <b>+7 дней подписки!</b>\n"
                        f"Ваш друг оформил подписку. Спасибо!",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

        text = (
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"Тариф: <b>{name}</b>\n"
            f"Действует до: <b>{end_date.strftime('%d.%m.%Y')}</b>\n\n"
            f"Откройте VEX — скопируйте ключ и настройте VPN."
        )
        await message.answer(text, reply_markup=payment_done_keyboard(), parse_mode="HTML")

    except MarzbanError as e:
        await message.answer(
            f"❌ VPN-панель временно недоступна. Деньги не списаны или будут возвращены.\n"
            f"Поддержка: @{SUPPORT_USERNAME}\n"
            f"<code>{e.status}: {e.message[:200]}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(
            f"❌ Неожиданная ошибка. Поддержка: @{SUPPORT_USERNAME}\n"
            f"<code>{type(e).__name__}: {e}</code>",
            parse_mode="HTML",
        )
