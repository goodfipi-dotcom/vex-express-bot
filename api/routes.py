"""API-роуты для Mini App (TMA)"""

import hashlib
import hmac
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from datetime import datetime

from config import BOT_TOKEN, PLANS, PAYMENT_PROVIDER_TOKEN
from db.database import get_user, get_transactions as db_get_transactions
from services.marzban import marzban

app = FastAPI(title="VEX EXPRESS API")


# ─── Валидация Telegram initData ───

def validate_init_data(init_data: str) -> dict | None:
    """Проверяет подлинность данных от Telegram Web App"""
    if not init_data:
        return None

    parsed = parse_qs(init_data)
    received_hash = parsed.get("hash", [None])[0]
    if not received_hash:
        return None

    # Собираем строку для проверки
    data_check = []
    for key, values in sorted(parsed.items()):
        if key != "hash":
            data_check.append(f"{key}={values[0]}")
    data_check_string = "\n".join(data_check)

    # Вычисляем HMAC
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if calculated_hash != received_hash:
        return None

    import json
    user_data = parsed.get("user", [None])[0]
    if user_data:
        return json.loads(user_data)
    return None


def get_telegram_user(request: Request) -> dict:
    """Извлекает и валидирует пользователя из заголовка"""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_init_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


# ─── Эндпоинты ───

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/user/status")
async def user_status(request: Request):
    """Статус подписки пользователя"""
    tg_user = get_telegram_user(request)
    user = await get_user(tg_user["id"])

    if not user:
        return {
            "active": False,
            "expires_at": None,
            "vless_key": None,
            "username": tg_user.get("first_name", ""),
        }

    # Проверяем активность подписки
    sub_end = user["subscription_end"]
    active = False
    if sub_end:
        active = datetime.fromisoformat(sub_end) > datetime.now()

    return {
        "active": active,
        "expires_at": sub_end,
        "vless_key": user["vless_key"] if active else None,
        "username": user["first_name"],
    }


class InvoiceRequest(BaseModel):
    plan_id: str


@app.post("/api/payment/invoice")
async def create_invoice(body: InvoiceRequest, request: Request):
    """Создание ссылки на инвойс Telegram"""
    tg_user = get_telegram_user(request)

    if body.plan_id not in PLANS:
        raise HTTPException(status_code=400, detail="Unknown plan")

    name, price, days = PLANS[body.plan_id]

    # Для реальных платежей нужно создать инвойс через Bot API
    # Пока возвращаем заглушку
    return {
        "invoice_url": f"https://t.me/$invoice_placeholder_{body.plan_id}",
        "plan": name,
        "price": price // 100,
    }


@app.get("/api/user/transactions")
async def user_transactions(request: Request):
    """История транзакций пользователя"""
    tg_user = get_telegram_user(request)
    rows = await db_get_transactions(tg_user["id"])

    transactions = []
    for row in rows:
        transactions.append({
            "plan_name": row["plan_name"],
            "amount": row["amount"],
            "status": row["status"],
            "created_at": row["created_at"],
        })

    return {"transactions": transactions}
