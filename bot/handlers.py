from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from aiogram.filters import CommandStart
from datetime import datetime, timedelta

from config import PLANS, PAYMENT_PROVIDER_TOKEN, WEBAPP_URL, SUPPORT_USERNAME
from db.database import (
    create_or_update_user,
    get_user,
    add_transaction,
    update_subscription,
    transaction_exists,
)
from services.marzban import marzban, MarzbanError

router = Router()


def main_keyboard():
    """Главная клавиатура с кнопкой Mini App"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚡ Открыть VEX",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )],
        [
            InlineKeyboardButton(text="💳 Тарифы", callback_data="show_plans"),
            InlineKeyboardButton(text="📖 Как подключить", callback_data="show_guide"),
        ],
        [InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")],
    ])


def plans_keyboard():
    """Клавиатура выбора тарифа"""
    labels = {
        "1month": "1 месяц",
        "3months": "3 месяца · выгодно",
        "1year": "1 год · максимум",
    }
    buttons = []
    for plan_id, (name, price, days) in PLANS.items():
        price_rub = price // 100
        label = labels.get(plan_id, name)
        buttons.append([
            InlineKeyboardButton(
                text=f"{label} — {price_rub} ₽",
                callback_data=f"buy:{plan_id}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="back_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


START_TEXT = (
    "<b>VEX</b> — быстрый VPN без рекламы и лимитов\n"
    "\n"
    "⚡ Высокая скорость — стримы, игры, звонки\n"
    "🔒 Шифрование — никто не увидит ваш трафик\n"
    "📱 Одна подписка — iPhone, Android, Mac, PC\n"
    "\n"
    "<b>От 150 ₽ в месяц.</b> Подключение за 2 минуты.\n"
    "Нажмите <b>⚡ Открыть VEX</b>, чтобы начать."
)


# ─── /start ───

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    await create_or_update_user(user.id, user.username or "", user.first_name or "")
    await message.answer(START_TEXT, reply_markup=main_keyboard(), parse_mode="HTML")


# ─── Показать тарифы ───

@router.callback_query(F.data == "show_plans")
async def show_plans(callback: CallbackQuery):
    text = (
        "<b>Тарифы VEX</b>\n"
        "\n"
        "• <b>1 месяц</b> — 150 ₽\n"
        "• <b>3 месяца</b> — 390 ₽  <i>— экономия 13%</i>\n"
        "• <b>1 год</b> — 1 290 ₽  <i>— экономия 28%</i>\n"
        "\n"
        "Во все тарифы включено: безлимит, все страны, все устройства.\n"
        "Оплата картой или Telegram Stars."
    )
    await callback.message.edit_text(text, reply_markup=plans_keyboard(), parse_mode="HTML")
    await callback.answer()


# ─── Как подключить ───

@router.callback_query(F.data == "show_guide")
async def show_guide(callback: CallbackQuery):
    text = (
        "<b>Как подключить VPN</b>\n"
        "\n"
        "1. Оплатите любой тариф\n"
        "2. Откройте <b>⚡ VEX</b> — получите ключ\n"
        "3. Скачайте приложение под своё устройство:\n"
        "   • iPhone — <b>V2Box</b> (App Store)\n"
        "   • Android — <b>v2rayNG</b> (Google Play)\n"
        "   • Mac — <b>V2Box</b> (Mac App Store)\n"
        "   • Windows — <b>Nekoray</b> (GitHub)\n"
        "4. Вставьте ключ из буфера и нажмите ▶\n"
        "\n"
        "Всё. VPN работает."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚡ Открыть VEX",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )],
        [InlineKeyboardButton(text="← Назад", callback_data="back_home")],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery):
    await callback.message.edit_text(
        START_TEXT, reply_markup=main_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


# ─── Покупка тарифа (Telegram Payments) ───

@router.callback_query(F.data.startswith("buy:"))
async def buy_plan(callback: CallbackQuery):
    plan_id = callback.data.split(":")[1]

    if plan_id not in PLANS:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    name, price, days = PLANS[plan_id]

    if not PAYMENT_PROVIDER_TOKEN:
        await callback.answer(
            "Платежи ещё не настроены. Обратитесь в поддержку.",
            show_alert=True,
        )
        return

    await callback.message.answer_invoice(
        title=f"VEX EXPRESS — {name}",
        description=f"Безлимитный VPN на {days} дней. Высокая скорость, все устройства.",
        payload=f"{plan_id}:{callback.from_user.id}",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=name, amount=price)],
    )
    await callback.answer()


# ─── Pre-checkout ───

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


# ─── Успешная оплата ───

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    charge_id = payment.telegram_payment_charge_id
    payload = payment.invoice_payload  # "plan_id:user_id"
    plan_id = payload.split(":")[0]

    if plan_id not in PLANS:
        return

    # Защита от двойной обработки одного и того же платежа
    if await transaction_exists(charge_id):
        return

    name, price, days = PLANS[plan_id]
    user = message.from_user
    marzban_username = f"vex_{user.id}"

    try:
        # Создаём/продлеваем пользователя в Marzban
        await marzban.create_user(marzban_username, days)
        vless_link = await marzban.get_vless_link(marzban_username)
        end_date = datetime.now() + timedelta(days=days)

        # Сохраняем в БД (charge_id — защита от двойных оплат)
        await update_subscription(user.id, vless_link or "", marzban_username, end_date)
        await add_transaction(user.id, plan_id, name, price // 100, "paid", charge_id)

        text = (
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"Тариф: <b>{name}</b>\n"
            f"Действует до: <b>{end_date.strftime('%d.%m.%Y')}</b>\n\n"
            f"Откройте Mini App, чтобы скопировать ключ подключения 👇"
        )
        await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")

    except MarzbanError as e:
        await message.answer(
            f"❌ VPN-панель недоступна. Деньги не списаны или будут возвращены.\n"
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
