import aiohttp
from datetime import datetime, timedelta
from config import MARZBAN_URL, MARZBAN_USERNAME, MARZBAN_PASSWORD


class MarzbanAPI:
    """Клиент для Marzban API"""

    def __init__(self):
        self.base_url = MARZBAN_URL
        self.token = None

    async def login(self):
        """Авторизация в панели Marzban — получение JWT токена"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/admin/token",
                data={
                    "username": MARZBAN_USERNAME,
                    "password": MARZBAN_PASSWORD,
                },
            ) as resp:
                data = await resp.json()
                self.token = data["access_token"]
                return self.token

    async def _headers(self):
        if not self.token:
            await self.login()
        return {"Authorization": f"Bearer {self.token}"}

    async def create_user(self, username: str, days: int) -> dict:
        """Создать пользователя VPN в Marzban"""
        headers = await self._headers()
        expire_ts = int((datetime.now() + timedelta(days=days)).timestamp())

        payload = {
            "username": username,
            "proxies": {
                "vless": {
                    "flow": "xtls-rprx-vision",
                },
            },
            "inbounds": {
                "vless": ["VLESS TCP REALITY"],
            },
            "expire": expire_ts,
            "data_limit": 0,  # безлимит
            "status": "active",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/user",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status == 409:
                    # Пользователь уже существует — обновляем
                    return await self.extend_user(username, days)
                return await resp.json()

    async def extend_user(self, username: str, days: int) -> dict:
        """Продлить подписку существующего пользователя"""
        headers = await self._headers()

        # Получаем текущего пользователя
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/api/user/{username}",
                headers=headers,
            ) as resp:
                user_data = await resp.json()

        # Рассчитываем новую дату
        current_expire = user_data.get("expire", 0)
        now_ts = int(datetime.now().timestamp())
        base_ts = max(current_expire, now_ts)
        new_expire = base_ts + (days * 86400)

        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{self.base_url}/api/user/{username}",
                json={"expire": new_expire, "status": "active"},
                headers=headers,
            ) as resp:
                return await resp.json()

    async def get_user(self, username: str) -> dict | None:
        """Получить данные пользователя из Marzban"""
        headers = await self._headers()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/api/user/{username}",
                headers=headers,
            ) as resp:
                if resp.status == 404:
                    return None
                return await resp.json()

    async def get_vless_link(self, username: str) -> str | None:
        """Получить ссылку vless:// для подключения"""
        user = await self.get_user(username)
        if not user:
            return None

        links = user.get("links", [])
        for link in links:
            if link.startswith("vless://"):
                return link
        return links[0] if links else None


# Синглтон
marzban = MarzbanAPI()
