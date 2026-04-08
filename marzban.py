from datetime import datetime, timedelta, timezone
import statistics
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

    async def get_user_online_status(self, username: str) -> dict[str, Any]:
        user = await self.get_user(username)
        if user is None:
            return {"online_now": None, "online_status": "unknown"}

        online_at = user.get("online_at")
        online_now = bool(online_at)
        return {
            "online_now": online_now,
            "online_status": "online" if online_now else "offline",
        }

    async def get_inbounds(self) -> dict[str, list[dict[str, Any]]]:
        response = await self._request_with_fallback("GET", "/api/inbounds")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {}

    async def create_user(
        self,
        username: str,
        expire_at: datetime,
    ) -> dict[str, Any]:
        expire_utc = expire_at if expire_at.tzinfo else expire_at.replace(tzinfo=timezone.utc)
        expire_ts = int(expire_utc.timestamp())

        inbounds_payload = await self.get_inbounds()
        vless_tags = [
            str(item.get("tag", "")).strip()
            for item in inbounds_payload.get("vless", [])
        ]
        vless_tags = [tag for tag in vless_tags if tag]

        if not vless_tags:
            raise RuntimeError("No enabled VLESS inbounds found in Marzban")

        payload = {
            "username": username,
            "proxies": {"vless": {}},
            "inbounds": {"vless": vless_tags},
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
        if response.status_code >= 400:
            raise RuntimeError(f"Marzban create user failed: {response.status_code} {response.text}")
        return response.json()

    async def disable_user(self, username: str) -> bool:
        payload = {"status": "disabled"}
        response = await self._request_with_fallback("PUT", f"/api/user/{username}", json=payload)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    async def update_user_trial(
        self,
        username: str,
        expire_at: datetime | None,
        active: bool = True,
    ) -> bool:
        payload: dict[str, Any] = {"status": "active" if active else "disabled"}
        if expire_at is None:
            payload["expire"] = 0
        else:
            expire_utc = expire_at if expire_at.tzinfo else expire_at.replace(tzinfo=timezone.utc)
            payload["expire"] = int(expire_utc.timestamp())

        response = await self._request_with_fallback("PUT", f"/api/user/{username}", json=payload)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    async def delete_user(self, username: str) -> bool:
        response = await self._request_with_fallback("DELETE", f"/api/user/{username}")
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    async def get_users_usage_snapshot(self, limit: int = 2000) -> dict[str, Any]:
        response = await self._request_with_fallback("GET", f"/api/users?limit={limit}")
        response.raise_for_status()
        payload = response.json()
        users = payload.get("users", []) if isinstance(payload, dict) else []

        used_traffic_values = [int(u.get("used_traffic", 0) or 0) for u in users]
        connected_users = sum(1 for v in used_traffic_values if v > 0)
        active_users = sum(1 for u in users if str(u.get("status", "")) == "active")
        total_traffic_bytes = sum(used_traffic_values)

        avg_traffic = (total_traffic_bytes / len(used_traffic_values)) if used_traffic_values else 0.0
        median_traffic = statistics.median(used_traffic_values) if used_traffic_values else 0.0
        heavy_users = sum(1 for v in used_traffic_values if v >= 5 * 1024 * 1024 * 1024)

        return {
            "total_users": len(users),
            "connected_users": connected_users,
            "active_users": active_users,
            "total_traffic_gb": round(total_traffic_bytes / (1024 ** 3), 2),
            "avg_traffic_gb": round(avg_traffic / (1024 ** 3), 2),
            "median_traffic_gb": round(median_traffic / (1024 ** 3), 2),
            "heavy_users_5gb": heavy_users,
        }

    async def get_system_snapshot(self) -> dict[str, Any]:
        response = await self._request_with_fallback("GET", "/api/system")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {}

        mem_total = int(payload.get("mem_total", 0) or 0)
        mem_used = int(payload.get("mem_used", 0) or 0)
        ram_pct = round((mem_used / mem_total) * 100, 2) if mem_total else 0.0
        return {
            "cpu_pct": round(float(payload.get("cpu_usage", 0) or 0), 2),
            "ram_pct": ram_pct,
            "online_users": int(payload.get("online_users", 0) or 0),
            "version": str(payload.get("version", "")),
        }
