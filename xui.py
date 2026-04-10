from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Any
from urllib.parse import urljoin

import httpx


def _build_subscription_url(base_url: str, sub_path: str, sub_id: str, title: str) -> str:
    base = base_url.rstrip("/") + "/"
    path = sub_path.strip() or "/sub/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return f"{urljoin(base, path.lstrip('/'))}{sub_id}#{title}"


@dataclass(frozen=True)
class XUIClientRecord:
    inbound_id: int
    client_id: str
    email: str
    sub_id: str
    used_traffic: int
    total: int
    expiry_time: int
    enable: bool
    subscription_url: str


class XUIClient:
    def __init__(
        self,
        base_url: str,
        public_base_url: str = "",
        username: str = "",
        password: str = "",
        inbound_id: int = 0,
        subscription_name: str = "LabGuard",
        server_name: str = "Финляндия",
        subscription_path: str = "/sub/",
        verify_tls: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.public_base_url = public_base_url.rstrip("/") or self.base_url
        self.username = username.strip()
        self.password = password.strip()
        self.inbound_id = int(inbound_id or 0)
        self.subscription_name = subscription_name.strip() or "LabGuard"
        self.server_name = server_name.strip() or "Финляндия"
        self.subscription_path = subscription_path.strip() or "/sub/"
        self.verify_tls = verify_tls
        self._cookies: dict[str, str] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password and self.inbound_id)

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _login(self) -> None:
        async with httpx.AsyncClient(timeout=20.0, verify=self.verify_tls, follow_redirects=True) as client:
            response = await client.post(
                self._build_url("/login"),
                data={"username": self.username, "password": self.password, "twoFactorCode": ""},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(payload.get("msg") or "3X-UI login failed")
            self._cookies = dict(client.cookies)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.is_configured:
            raise RuntimeError("3X-UI client is not configured")
        if not self._cookies:
            await self._login()

        async with httpx.AsyncClient(
            timeout=20.0,
            verify=self.verify_tls,
            follow_redirects=True,
            cookies=self._cookies,
        ) as client:
            response = await client.request(method, self._build_url(path), **kwargs)
            if response.status_code in {401, 403}:
                await self._login()
                client.cookies.clear()
                for key, value in self._cookies.items():
                    client.cookies.set(key, value)
                response = await client.request(method, self._build_url(path), **kwargs)
            response.raise_for_status()
            self._cookies = dict(client.cookies)
            payload = response.json()
            if isinstance(payload, dict) and payload.get("success") is False:
                raise RuntimeError(str(payload.get("msg") or "3X-UI request failed"))
            if isinstance(payload, dict) and "obj" in payload:
                obj = payload.get("obj")
                return obj if isinstance(obj, dict) else {"items": obj}
            return payload if isinstance(payload, dict) else {"items": payload}

    async def healthcheck(self) -> bool:
        if not self.is_configured:
            return False
        try:
            await self.get_inbound(self.inbound_id)
            return True
        except Exception:
            return False

    async def get_inbounds(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/panel/api/inbounds/list")
        items = payload.get("items", payload)
        return items if isinstance(items, list) else []

    async def get_inbound(self, inbound_id: int | None = None) -> dict[str, Any]:
        target_id = int(inbound_id or self.inbound_id)
        return await self._request("GET", f"/panel/api/inbounds/get/{target_id}")

    def _extract_clients(self, inbound: dict[str, Any]) -> list[dict[str, Any]]:
        settings_raw = inbound.get("settings") or "{}"
        if isinstance(settings_raw, dict):
            settings = settings_raw
        else:
            settings = json.loads(str(settings_raw) or "{}")
        clients = settings.get("clients") or []
        return clients if isinstance(clients, list) else []

    def _extract_client_stats(self, inbound: dict[str, Any]) -> dict[str, dict[str, Any]]:
        stats = inbound.get("clientStats") or []
        mapping: dict[str, dict[str, Any]] = {}
        if isinstance(stats, list):
            for stat in stats:
                if isinstance(stat, dict):
                    email = str(stat.get("email") or "").strip().lower()
                    if email:
                        mapping[email] = stat
        return mapping

    def _build_client_record(self, inbound: dict[str, Any], client: dict[str, Any]) -> XUIClientRecord:
        stats = self._extract_client_stats(inbound).get(str(client.get("email") or "").strip().lower(), {})
        sub_id = str(client.get("subId") or "").strip()
        return XUIClientRecord(
            inbound_id=int(inbound.get("id") or self.inbound_id),
            client_id=str(client.get("id") or "").strip(),
            email=str(client.get("email") or "").strip(),
            sub_id=sub_id,
            used_traffic=int(stats.get("up", 0) or 0) + int(stats.get("down", 0) or 0),
            total=int(stats.get("total", 0) or 0),
            expiry_time=int(client.get("expiryTime", 0) or 0),
            enable=bool(client.get("enable", False)),
            subscription_url=_build_subscription_url(self.public_base_url, self.subscription_path, sub_id, self.subscription_name),
        )

    async def get_user(self, email: str) -> dict[str, Any] | None:
        inbound = await self.get_inbound(self.inbound_id)
        for client in self._extract_clients(inbound):
            if str(client.get("email") or "").strip().lower() == email.strip().lower():
                record = self._build_client_record(inbound, client)
                return {
                    "username": record.email,
                    "expire": int(record.expiry_time / 1000) if record.expiry_time else 0,
                    "used_traffic": record.used_traffic,
                    "subscription_url": record.subscription_url,
                    "links": [],
                    "client_id": record.client_id,
                    "sub_id": record.sub_id,
                    "email": record.email,
                    "status": "active" if record.enable else "disabled",
                }
        return None

    async def create_user(self, username: str, expire_at: datetime) -> dict[str, Any]:
        expire_ms = int((expire_at if expire_at.tzinfo else expire_at.replace(tzinfo=timezone.utc)).timestamp() * 1000)
        client_id = str(uuid.uuid4())
        sub_id = uuid.uuid4().hex[:16]
        client = {
            "id": client_id,
            "flow": "xtls-rprx-vision",
            "email": username,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": expire_ms,
            "enable": True,
            "tgId": 0,
            "subId": sub_id,
            "comment": self.server_name,
            "reset": 0,
        }
        await self._request(
            "POST",
            "/panel/api/inbounds/addClient",
            data={"id": str(self.inbound_id), "settings": json.dumps({"clients": [client]}, ensure_ascii=False)},
        )
        created = await self.get_user(username)
        if created is None:
            raise RuntimeError("3X-UI created client but it was not found")
        return created

    async def disable_user(self, email: str) -> bool:
        inbound = await self.get_inbound(self.inbound_id)
        clients = self._extract_clients(inbound)
        target = None
        for client in clients:
            if str(client.get("email") or "").strip().lower() == email.strip().lower():
                client["enable"] = False
                target = client
                break
        if target is None:
            return False
        await self._request(
            "POST",
            f"/panel/api/inbounds/updateClient/{target['id']}",
            data={"id": str(self.inbound_id), "settings": json.dumps({"clients": [target]}, ensure_ascii=False)},
        )
        return True

    async def update_user_trial(self, email: str, expire_at: datetime | None, active: bool = True) -> bool:
        inbound = await self.get_inbound(self.inbound_id)
        clients = self._extract_clients(inbound)
        target = None
        for client in clients:
            if str(client.get("email") or "").strip().lower() == email.strip().lower():
                target = client
                break
        if target is None:
            return False
        if expire_at is None:
            target["expiryTime"] = 0
        else:
            dt = expire_at if expire_at.tzinfo else expire_at.replace(tzinfo=timezone.utc)
            target["expiryTime"] = int(dt.timestamp() * 1000)
        target["enable"] = bool(active)
        await self._request(
            "POST",
            f"/panel/api/inbounds/updateClient/{target['id']}",
            data={"id": str(self.inbound_id), "settings": json.dumps({"clients": [target]}, ensure_ascii=False)},
        )
        return True

    async def delete_user(self, email: str) -> bool:
        inbound = await self.get_inbound(self.inbound_id)
        clients = self._extract_clients(inbound)
        target = None
        for client in clients:
            if str(client.get("email") or "").strip().lower() == email.strip().lower():
                target = client
                break
        if target is None:
            return False
        await self._request("POST", f"/panel/api/inbounds/{self.inbound_id}/delClient/{target['id']}")
        return True

    async def get_user_online_status(self, email: str) -> dict[str, Any]:
        payload = await self._request("POST", "/panel/api/inbounds/onlines")
        items = payload.get("items", payload)
        emails = items if isinstance(items, list) else []
        online_now = email in emails
        return {"online_now": online_now, "online_status": "online" if online_now else "offline"}

    async def get_users_usage_snapshot(self, limit: int = 2000) -> dict[str, Any]:
        inbounds = await self.get_inbounds()
        total_users = 0
        connected_users = 0
        total_traffic_bytes = 0
        for inbound in inbounds:
            stats = inbound.get("clientStats") or []
            if not isinstance(stats, list):
                continue
            for stat in stats[:limit]:
                if not isinstance(stat, dict):
                    continue
                total_users += 1
                used = int(stat.get("up", 0) or 0) + int(stat.get("down", 0) or 0)
                total_traffic_bytes += used
                if used > 0:
                    connected_users += 1
        return {
            "total_users": total_users,
            "connected_users": connected_users,
            "total_traffic_bytes": total_traffic_bytes,
        }

    async def get_system_snapshot(self) -> dict[str, Any]:
        payload = await self._request("GET", "/panel/api/server/status")
        online_users = payload.get("xray", {}).get("state")
        if isinstance(online_users, dict):
            online_count = int(online_users.get("online", 0) or 0)
        else:
            online_count = 0
        return {"online_users": online_count}
