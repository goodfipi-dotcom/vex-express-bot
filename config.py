import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

# Marzban
MARZBAN_URL = os.getenv("MARZBAN_URL", "https://your-panel.example.com")
MARZBAN_USERNAME = os.getenv("MARZBAN_USERNAME", "admin")
MARZBAN_PASSWORD = os.getenv("MARZBAN_PASSWORD", "")

# Mini App
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-tma.vercel.app")

# Поддержка
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "vex_support")

# Тарифы: id -> (название, цена в копейках, дней)
PLANS = {
    "1month": ("1 месяц", 15000, 30),
    "3months": ("3 месяца", 39000, 90),
    "1year": ("1 год", 129000, 365),
}
