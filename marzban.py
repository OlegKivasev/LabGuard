from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


class MarzbanClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        username: str = "",
        password: str = "",
        verify_tls: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.username = username.strip()
        self.password = password.strip()
        self.verify_tls = verify_tls

        self._token: str = ""
        self._token_expires_at: datetime | None = None

    @property
    def is_configured(self) -> bool:
        has_token = bool(self.api_key)
        has_credentials = bool(self.username and self.password)
        return bool(self.base_url and (has_token or has_credentials))

    def _token_is_valid(self) -> bool:
        if not self._token or self._token_expires_at is None:
            return False
        return datetime.now(timezone.utc) < self._token_expires_at

    async def _fetch_admin_token(self) -> str:
        async with httpx.AsyncClient(timeout=15.0, verify=self.verify_tls) as client:
            response = await client.post(
                f"{self.base_url}/api/admin/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"username": self.username, "password": self.password},
            )
            response.raise_for_status()
            payload = response.json()

        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise RuntimeError("Marzban token endpoint returned empty access_token")

        self._token = token
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        return token

    async def _get_bearer_token(self) -> str:
        if self.api_key:
            return self.api_key

        if self._token_is_valid():
            return self._token

        return await self._fetch_admin_token()

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_bearer_token()
        return {"Authorization": f"Bearer {token}"}

    async def _request_with_fallback(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if not self.is_configured:
            raise RuntimeError("Marzban client is not configured")

        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(timeout=15.0, verify=self.verify_tls) as client:
            if self.api_key:
                response = await client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=json,
                )
                if response.status_code != 401:
                    return response

            if self.username and self.password:
                token = await self._fetch_admin_token()
                response = await client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json=json,
                )
                return response

            return response

    async def healthcheck(self) -> bool:
        if not self.is_configured:
            return False

        response = await self._request_with_fallback("GET", "/api/admin")
        return response.status_code < 400

    async def get_user(self, username: str) -> dict[str, Any] | None:
        response = await self._request_with_fallback("GET", f"/api/user/{username}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def create_user(
        self,
        username: str,
        expire_at: datetime,
    ) -> dict[str, Any]:
        expire_utc = expire_at if expire_at.tzinfo else expire_at.replace(tzinfo=timezone.utc)
        expire_ts = int(expire_utc.timestamp())
        payload = {
            "username": username,
            "proxies": {"vless": {}},
            "expire": expire_ts,
            "data_limit": 0,
            "data_limit_reset_strategy": "no_reset",
            "note": "created_by_telegram_bot",
        }
        response = await self._request_with_fallback("POST", "/api/user", json=payload)
        if response.status_code == 409:
            existing = await self.get_user(username)
            if existing is None:
                raise RuntimeError("Marzban returned 409 but user was not found")
            return existing
        response.raise_for_status()
        return response.json()
