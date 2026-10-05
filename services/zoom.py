from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime

import aiohttp

import config
from db import repo
from services import crypto

API = "https://api.zoom.us/v2"
TOKEN_URL = "https://zoom.us/oauth/token"
TOKENS_KEY = "zoom_tokens"
_TIMEOUT = aiohttp.ClientTimeout(total=20)


class ZoomError(Exception):
    pass


class ZoomNotConnected(ZoomError):
    """Админ ещё не авторизовал Zoom."""


class ZoomAuthError(ZoomError):
    """Токен не обновился: админу нужно переподключить Zoom."""


class ZoomUnavailable(ZoomError):
    """Сеть/5xx — можно повторить позже."""


class ZoomApiError(ZoomError):
    def __init__(self, status: int, body):
        super().__init__(f"Zoom API {status}: {body}")
        self.status = status
        self.body = body


@dataclass
class ZoomMeetingInfo:
    meeting_id: str
    join_url: str
    passcode: str


class ZoomClient:
    def __init__(self, http: aiohttp.ClientSession):
        self._http = http
        self._lock = asyncio.Lock()

    async def _load_tokens(self) -> dict | None:
        async with repo.Session() as s:
            raw = await repo.get_setting(s, TOKENS_KEY)
        return json.loads(crypto.decrypt(raw)) if raw else None

    async def _save_tokens(self, data: dict) -> None:
        tokens = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": time.time() + int(data.get("expires_in", 3600)),
        }
        async with repo.Session() as s:
            await repo.set_setting(s, TOKENS_KEY, crypto.encrypt(json.dumps(tokens)))

    async def _token_request(self, form: dict) -> dict:
        auth = aiohttp.BasicAuth(config.ZOOM_CLIENT_ID, config.ZOOM_CLIENT_SECRET)
        try:
            async with self._http.post(TOKEN_URL, data=form, auth=auth, timeout=_TIMEOUT) as r:
                body = await r.json(content_type=None)
                if r.status >= 500:
                    raise ZoomUnavailable(f"token endpoint {r.status}")
                if r.status != 200:
                    raise ZoomAuthError(f"token endpoint {r.status}: {body}")
                return body
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise ZoomUnavailable(str(e)) from e

    async def exchange_code(self, code: str) -> None:
        data = await self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.ZOOM_REDIRECT_URI,
        })
        await self._save_tokens(data)

    async def is_connected(self) -> bool:
        return await self._load_tokens() is not None

    async def _access_token(self, force_refresh: bool = False) -> str:
        async with self._lock:
            tokens = await self._load_tokens()
            if not tokens:
                raise ZoomNotConnected()
            if force_refresh or tokens["expires_at"] - 60 < time.time():
                data = await self._token_request({
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                })
                await self._save_tokens(data)
                return data["access_token"]
            return tokens["access_token"]

    async def _request(self, method: str, path: str, **kw):
        token = await self._access_token()
        for attempt in (1, 2):
            try:
                async with self._http.request(
                    method, f"{API}{path}", timeout=_TIMEOUT,
                    headers={"Authorization": f"Bearer {token}"}, **kw,
                ) as r:
                    if r.status == 401 and attempt == 1:
                        token = await self._access_token(force_refresh=True)
                        continue
                    if r.status >= 500:
                        raise ZoomUnavailable(f"Zoom {r.status}")
                    body = await r.json(content_type=None) if r.content_length != 0 else {}
                    return r.status, body
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise ZoomUnavailable(str(e)) from e
        raise ZoomAuthError("401 после обновления токена")

    async def create_meeting(
        self, topic: str, *, type: int,
        start_local: datetime | None = None, duration_min: int | None = None,
        use_pmi: bool = True,
    ) -> ZoomMeetingInfo:
        body: dict = {"topic": topic[:200], "type": type, "settings": {"use_pmi": use_pmi}}
        if type == 2:
            body.update(
                start_time=start_local.strftime("%Y-%m-%dT%H:%M:%S"),
                timezone="Europe/Moscow",
                duration=duration_min,
            )
        status, data = await self._request("POST", "/users/me/meetings", json=body)
        if status != 201:
            raise ZoomApiError(status, data)
        return ZoomMeetingInfo(str(data["id"]), data["join_url"], str(data.get("password", "")))

    async def delete_meeting(self, meeting_id: str) -> None:
        status, data = await self._request("DELETE", f"/meetings/{meeting_id}")
        if status in (204, 404):
            return
        raise ZoomApiError(status, data)
