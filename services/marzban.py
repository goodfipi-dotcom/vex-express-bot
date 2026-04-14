"""Клиент для Marzban API.

- Один долгий aiohttp-канал вместо новой сессии на каждый запрос
- Автоматическое обновление JWT-токена при истечении (401)
- Понятные ошибки через MarzbanError
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta

from config import MARZBAN_URL, MARZBAN_USERNAME, MARZBAN_PASSWORD, INBOUND_TAG


class MarzbanError(Exception):
    """Ошибка при работе с Marzban API"""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"Marzban API {status}: {message}")


class MarzbanAPI:
    def __init__(self):
        self.base_url = MARZBAN_URL.rstrip("/")
        self.token: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._login_lock = asyncio.Lock()

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def login(self) -> str:
        """Получить JWT-токен у Marzban"""
        session = await self._session_get()
        async with session.post(
            f"{self.base_url}/api/admin/token",
            data={"username": MARZBAN_USERNAME, "password": MARZBAN_PASSWORD},
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise MarzbanError(resp.status, f"login failed: {text}")
            data = await resp.json()
            self.token = data["access_token"]
            return self.token

    async def _request(self, method: str, path: str, **kwargs):
        """Запрос с авто-повтором при истёкшем токене (401)"""
        session = await self._session_get()

        async with self._login_lock:
            if not self.token:
                await self.login()

        def _make_headers():
            h = kwargs.pop("headers", {}) if "headers" in kwargs else {}
            h["Authorization"] = f"Bearer {self.token}"
            return h

        headers = _make_headers()
        resp = await session.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)

        if resp.status == 401:
            await resp.release()
            async with self._login_lock:
                await self.login()
            headers["Authorization"] = f"Bearer {self.token}"
            resp = await session.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)

        return resp

    # ─── Публичные методы ─────────────────────────────────────────

    async def create_user(self, username: str, days: int) -> dict:
        """Создать VPN-пользователя. Если уже существует — продлить."""
        expire_ts = int((datetime.now() + timedelta(days=days)).timestamp())
        payload = {
            "username": username,
            "proxies": {"vless": {"flow": "xtls-rprx-vision"}},
            "inbounds": {"vless": [INBOUND_TAG]},
            "expire": expire_ts,
            "data_limit": 0,
            "status": "active",
        }

        resp = await self._request("POST", "/api/user", json=payload)
        async with resp:
            text = await resp.text()
            # Marzban может вернуть 409 или 400 с сообщением "already exists"
            if resp.status == 409 or (resp.status == 400 and "already exists" in text.lower()):
                return await self.update_user(username, days)
            if resp.status >= 400:
                raise MarzbanError(resp.status, text)
            return await resp.json(content_type=None)

    async def update_user(self, username: str, days: int) -> dict:
        """Продлить подписку: прибавить days к текущему сроку (или к 'сейчас', если истёк)"""
        existing = await self.get_user(username)
        if not existing:
            return await self.create_user(username, days)

        current_expire = existing.get("expire") or 0
        now_ts = int(datetime.now().timestamp())
        base_ts = max(current_expire, now_ts)
        new_expire = base_ts + (days * 86400)

        resp = await self._request(
            "PUT",
            f"/api/user/{username}",
            json={"expire": new_expire, "status": "active"},
        )
        async with resp:
            if resp.status >= 400:
                raise MarzbanError(resp.status, await resp.text())
            return await resp.json(content_type=None)

    async def get_user(self, username: str) -> dict | None:
        resp = await self._request("GET", f"/api/user/{username}")
        async with resp:
            if resp.status == 404:
                return None
            if resp.status >= 400:
                raise MarzbanError(resp.status, await resp.text())
            return await resp.json(content_type=None)

    async def get_vless_link(self, username: str) -> str | None:
        user = await self.get_user(username)
        if not user:
            return None
        links = user.get("links") or []
        for link in links:
            if link.startswith("vless://"):
                return link
        return links[0] if links else None


# Singleton — один на всё приложение
marzban = MarzbanAPI()
