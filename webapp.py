import asyncio
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

from config import Settings
from database import Database
from miniapp_auth import verify_admin_token, verify_telegram_init_data
from marzban import MarzbanClient


def _is_admin_allowed(settings: Settings, admin_id: int, username: str = "") -> bool:
    if settings.admin_telegram_ids and admin_id in settings.admin_telegram_ids:
        return True
    if settings.admin_telegram_usernames and username in settings.admin_telegram_usernames:
        return True
    if not settings.admin_telegram_ids and not settings.admin_telegram_usernames:
        return True
    return False


def _verify_admin(settings: Settings, token: str, init_data: str) -> int:
    admin_id: int | None = None
    admin_username = ""
    if token:
        admin_id = verify_admin_token(settings.bot_token, token)

    if admin_id is None and init_data:
        payload = verify_telegram_init_data(settings.bot_token, init_data)
        if payload is not None:
            admin_id, admin_username = payload

    if admin_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired auth")

    if not _is_admin_allowed(settings, admin_id, admin_username):
        raise HTTPException(status_code=403, detail="Forbidden")

    return admin_id


def _candidate_marzban_usernames(user: dict, telegram_id: int) -> list[str]:
    candidates: list[str] = []
    for value in (user.get("marzban_id"), user.get("username"), f"tg_{telegram_id}"):
        name = str(value or "").strip()
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def _verify_user(settings: Settings, init_data: str) -> tuple[int, str]:
    payload = verify_telegram_init_data(settings.bot_token, init_data)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid Telegram auth")
    return payload


def _parse_sqlite_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _extract_subscription_text(marzban_user: dict) -> tuple[str, bool]:
    for key in ("subscription_url", "subscription_link", "sub_url", "subscription"):
        value = str(marzban_user.get(key, "")).strip()
        if value:
            return value, True

    for key in ("subscription_urls", "subscriptions"):
        values = marzban_user.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value).strip()
                if text:
                    return text, True

    links = marzban_user.get("links") or []
    for link in links:
        link_text = str(link).strip()
        if link_text.lower().startswith("vless://"):
            return link_text, False

    return "", False


def _normalize_subscription_url(raw_url: str, base_url: str) -> str:
    url = raw_url.strip()
    if not url or url.startswith("vless://"):
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url

    base = base_url.strip().rstrip("/")
    if not base:
        return url
    return f"{base}/{url.lstrip('/')}"


def _build_marzban_username(telegram_id: int, username: str) -> str:
    base = (username or f"tg_{telegram_id}").lower()
    safe = re.sub(r"[^a-z0-9_]", "_", base)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        safe = f"tg_{telegram_id}"
    return f"labguard_{safe}"[:48].rstrip("_")


class AdminTrialPayload(BaseModel):
    days: int = 14
    unlimited: bool = False
    no_trial_limits: bool = False


def build_app(db: Database, settings: Settings, marzban: MarzbanClient) -> FastAPI:
    app = FastAPI(title="VPN Admin Mini App", docs_url=None, redoc_url=None)

    @app.get("/admin-app", response_class=HTMLResponse)
    async def admin_app_page(
        token: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> HTMLResponse:
        _ = token
        _ = x_tg_init_data
        return HTMLResponse(_ADMIN_APP_HTML)

    @app.get("/admin-app/api/overview")
    async def admin_overview(
        token: str = Query(""),
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        _verify_admin(settings, token, x_tg_init_data or init_data)
        return db.get_admin_overview()

    @app.get("/admin-app/api/metrics")
    async def admin_metrics(
        token: str = Query(""),
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        _verify_admin(settings, token, x_tg_init_data or init_data)

        local = db.get_admin_metrics_snapshot()
        connected_users: int | None = None
        online_now: int | None = None
        marzban_error = ""
        try:
            marzban_usage = await marzban.get_users_usage_snapshot()
            marzban_system = await marzban.get_system_snapshot()
            connected_users = int(marzban_usage.get("connected_users", 0))
            online_now = int(marzban_system.get("online_users", 0))
        except Exception as exc:
            marzban_error = str(exc)

        return {
            "metrics": {
                "start_users": int(local.get("start_users", 0)),
                "vpn_link_users": int(local.get("vpn_link_users", 0)),
                "connected_users": connected_users,
                "online_now": online_now,
                "active_trials": int(local.get("active_trials", 0)),
                "expired_trials": int(local.get("expired_trials", 0)),
            },
            "meta": {
                "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "marzban_error": marzban_error,
            },
        }

    @app.get("/admin-app/api/users")
    async def admin_users(
        token: str = Query(""),
        limit: int = Query(30, ge=1, le=100),
        q: str = Query(""),
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        _verify_admin(settings, token, x_tg_init_data or init_data)
        users = db.search_users(query=q, limit=limit)
        return {"users": users}

    @app.post("/admin-app/api/user/{telegram_id}/deactivate")
    async def admin_deactivate(
        telegram_id: int,
        token: str = Query(""),
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        _verify_admin(settings, token, x_tg_init_data or init_data)

        user = db.get_user_by_telegram_id(telegram_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        marzban_changed = False
        for candidate in _candidate_marzban_usernames(user, telegram_id):
            if await marzban.disable_user(candidate):
                marzban_changed = True
                break

        db.clear_trial(telegram_id)
        db.mark_trial_used(telegram_id)
        db.log_event(telegram_id, "admin_deactivate_webapp")
        return {"ok": True, "marzban_changed": marzban_changed}

    @app.delete("/admin-app/api/user/{telegram_id}")
    async def admin_delete(
        telegram_id: int,
        token: str = Query(""),
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        _verify_admin(settings, token, x_tg_init_data or init_data)

        user = db.get_user_by_telegram_id(telegram_id)
        if user is None:
            lock_cleared = db.clear_trial_lock(telegram_id)
            return {"ok": True, "marzban_changed": False, "lock_cleared": lock_cleared}

        marzban_changed = False
        for candidate in _candidate_marzban_usernames(user, telegram_id):
            if await marzban.delete_user(candidate):
                marzban_changed = True
                break

        db.clear_trial_lock(telegram_id)
        db.delete_user(telegram_id)
        db.log_event(telegram_id, "admin_delete_webapp")
        return {"ok": True, "marzban_changed": marzban_changed, "lock_cleared": True}

    @app.post("/admin-app/api/user/{telegram_id}/trial")
    async def admin_set_trial(
        telegram_id: int,
        payload: AdminTrialPayload,
        token: str = Query(""),
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        _verify_admin(settings, token, x_tg_init_data or init_data)

        user = db.get_user_by_telegram_id(telegram_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if payload.days < 1 or payload.days > 3650:
            raise HTTPException(status_code=400, detail="days must be in range 1..3650")

        target_dt = None
        if not payload.unlimited:
            target_dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=payload.days)
        local_expires = (
            "2099-12-31 23:59:59"
            if payload.unlimited
            else target_dt.strftime("%Y-%m-%d %H:%M:%S")
        )

        marzban_changed = False
        for candidate in _candidate_marzban_usernames(user, telegram_id):
            if await marzban.update_user_trial(candidate, expire_at=target_dt, active=True):
                marzban_changed = True
                break

        if not marzban_changed:
            marzban_username = _build_marzban_username(telegram_id, str(user.get("username") or ""))
            create_expiry = (
                datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=36500)
                if payload.unlimited
                else target_dt
            )
            marzban_user = await marzban.create_user(username=marzban_username, expire_at=create_expiry)
            marzban_changed = bool(marzban_user)
            user = db.get_user_by_telegram_id(telegram_id) or user
            db.set_marzban_binding(
                telegram_id=telegram_id,
                marzban_id=str(marzban_user.get("username", marzban_username)),
                expires_at=local_expires,
            )

        db.set_user_expiry(telegram_id, local_expires)
        db.set_no_trial_limits(telegram_id, payload.no_trial_limits)
        if payload.no_trial_limits:
            db.clear_trial_lock(telegram_id)
        else:
            db.mark_trial_used(telegram_id)

        db.log_event(telegram_id, "admin_set_trial_webapp")
        return {
            "ok": True,
            "expires_at": local_expires,
            "unlimited": payload.unlimited,
            "no_trial_limits": payload.no_trial_limits,
            "marzban_changed": marzban_changed,
        }

    @app.get("/app", response_class=HTMLResponse)
    async def user_app_page() -> HTMLResponse:
        return HTMLResponse(_USER_APP_HTML)

    @app.get("/app/api/status")
    async def user_status(
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        telegram_id, username = _verify_user(settings, x_tg_init_data or init_data)

        user = db.get_user_by_telegram_id(telegram_id)
        if user is None and not db.has_received_trial(telegram_id):
            db.create_user_if_not_exists(telegram_id=telegram_id, username=username or None)
            user = db.get_user_by_telegram_id(telegram_id)
        elif user is not None:
            db.touch_last_active(telegram_id)

        db.log_event(telegram_id, "app_status")
        expires_raw = user.get("expires_at") if user else None
        is_active = False
        expires_at = ""
        remaining_days = 0
        subscription_url = ""
        is_subscription = False
        used_traffic_bytes = 0
        if expires_raw:
            dt = _parse_sqlite_dt(str(expires_raw))
            now = datetime.now(timezone.utc)
            is_active = dt > now
            remaining_days = max(0, (dt - now).days)
            expires_at = dt.strftime("%Y-%m-%d %H:%M:%S")

        if user and is_active:
            for candidate in _candidate_marzban_usernames(user, telegram_id):
                try:
                    marzban_user = await marzban.get_user(candidate)
                except Exception:
                    marzban_user = None
                if marzban_user:
                    subscription_url, is_subscription = _extract_subscription_text(marzban_user)
                    if is_subscription:
                        subscription_url = _normalize_subscription_url(subscription_url, marzban.base_url)
                    used_traffic_bytes = int(marzban_user.get("used_traffic", 0) or 0)
                    break

        return {
            "ok": True,
            "is_active": is_active,
            "expires_at": expires_at,
            "remaining_days": remaining_days,
            "trial_used": db.has_received_trial(telegram_id),
            "support_username": settings.support_bot_username,
            "is_admin": _is_admin_allowed(settings, telegram_id, username),
            "subscription_url": subscription_url,
            "is_subscription": is_subscription,
            "consumed_traffic_gb": round(used_traffic_bytes / (1024 ** 3), 2),
        }

    @app.post("/app/api/get-vpn")
    async def user_get_vpn(
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        telegram_id, username = _verify_user(settings, x_tg_init_data or init_data)

        existing = db.get_user_by_telegram_id(telegram_id)
        if existing and existing.get("expires_at"):
            expires_at_dt = _parse_sqlite_dt(str(existing["expires_at"]))
            now = datetime.now(timezone.utc)
            if expires_at_dt > now:
                marzban_user = None
                for candidate in _candidate_marzban_usernames(existing, telegram_id):
                    marzban_user = await marzban.get_user(candidate)
                    if marzban_user:
                        break

                sub_text = ""
                is_subscription = False
                if marzban_user:
                    sub_text, is_subscription = _extract_subscription_text(marzban_user)
                    if is_subscription:
                        sub_text = _normalize_subscription_url(sub_text, marzban.base_url)

                db.mark_trial_used(telegram_id)
                db.touch_last_active(telegram_id)
                db.log_event(telegram_id, "app_get_existing")
                return {
                    "ok": True,
                    "status": "already_active",
                    "expires_at": expires_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "remaining_days": max(0, (expires_at_dt - now).days),
                    "subscription_url": sub_text,
                    "is_subscription": is_subscription,
                }

        if db.has_received_trial(telegram_id):
            db.touch_last_active(telegram_id)
            db.log_event(telegram_id, "app_get_denied_finished")
            return {
                "ok": False,
                "status": "denied",
                "message": "Пробный период уже был использован и повторно не выдается.",
            }

        db.create_user_if_not_exists(telegram_id=telegram_id, username=username or None)
        if existing is None:
            existing = db.get_user_by_telegram_id(telegram_id)

        if not marzban.is_configured:
            raise HTTPException(status_code=503, detail="Marzban API не настроен")

        expiry_dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=settings.free_trial_days)
        marzban_username = _build_marzban_username(telegram_id, username)

        try:
            marzban_user = await marzban.create_user(username=marzban_username, expire_at=expiry_dt)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Не удалось создать подписку: {exc}") from exc

        expires_at = datetime.fromtimestamp(
            int(marzban_user.get("expire", int(expiry_dt.timestamp()))),
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S")

        db.set_marzban_binding(
            telegram_id=telegram_id,
            marzban_id=str(marzban_user.get("username", marzban_username)),
            expires_at=expires_at,
        )
        db.mark_trial_used(telegram_id)
        db.touch_last_active(telegram_id)
        db.log_event(telegram_id, "app_get")

        config_text, is_subscription = _extract_subscription_text(marzban_user)
        if is_subscription:
            config_text = _normalize_subscription_url(config_text, marzban.base_url)

        return {
            "ok": True,
            "status": "activated",
            "expires_at": expires_at,
            "subscription_url": config_text,
            "is_subscription": is_subscription,
        }

    return app


async def start_web_app_server(
    db: Database,
    settings: Settings,
    marzban: MarzbanClient,
) -> tuple[uvicorn.Server, asyncio.Task]:
    app = build_app(db, settings, marzban)
    config = uvicorn.Config(
        app=app,
        host=settings.web_app_host,
        port=settings.web_app_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    return server, task


_ADMIN_APP_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LabGuard Admin</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root { color-scheme: dark; }
    body { font-family: -apple-system, Segoe UI, sans-serif; margin: 0; background: #0f1420; color: #e7eefc; }
    .wrap { max-width: 1024px; margin: 0 auto; padding: 14px; }
    .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
    .head-actions { display: flex; gap: 8px; }
    .title { margin: 0; font-size: 36px; }
    .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
    .tab { background: #1b2334; border: 1px solid #2a3550; color: #e7eefc; border-radius: 999px; padding: 8px 12px; cursor: pointer; }
    .tab.active { background: #2f6df6; border-color: #2f6df6; }
    .section { display: none; }
    .section.active { display: block; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; margin-bottom: 14px; }
    .card { background: #1b2334; border: 1px solid #2a3550; border-radius: 12px; padding: 12px; }
    .k { font-size: 12px; opacity: .75; }
    .v { font-size: 24px; font-weight: 700; margin-top: 6px; }
    .mini { font-size: 12px; opacity: .85; margin-top: 4px; }
    button { background: #2f6df6; color: #fff; border: 0; border-radius: 10px; padding: 8px 12px; cursor: pointer; }
    button.red { background: #d94c4c; }
    .search { display: flex; gap: 8px; margin-bottom: 12px; }
    input { flex: 1; background: #121a29; color: #e7eefc; border: 1px solid #2a3550; border-radius: 10px; padding: 8px 10px; }
    .table-wrap { width: 100%; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 720px; }
    th, td { padding: 8px; border-bottom: 1px solid #2a3550; text-align: left; }
    th { opacity: .75; font-weight: 500; }
    .muted { opacity: .7; }
    .actions { display: flex; flex-direction: column; gap: 6px; min-width: 132px; }
    .actions button { width: 100%; padding: 6px 10px; font-size: 12px; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr 1fr; } .title { font-size: 32px; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1 class="title">LabGuard Admin</h1>
      <div class="head-actions">
        <button id="backToUserBtn" style="display:none">В пользовательское приложение</button>
        <button id="refreshBtn">Обновить</button>
      </div>
    </div>

    <div class="tabs">
      <button class="tab active" data-tab="metrics">Метрика</button>
      <button class="tab" data-tab="users">Пользователи</button>
    </div>

    <section id="metricsSection" class="section active">
      <div class="grid" id="kpiGrid"></div>
      <div class="card" style="margin-bottom: 10px;">
        <h3 style="margin-top:0">Воронка и удержание</h3>
        <div id="funnelBox" class="mini"></div>
      </div>
      <div class="card" style="margin-bottom: 10px;">
        <h3 style="margin-top:0">Вовлеченность и трафик</h3>
        <div id="engagementBox" class="mini"></div>
      </div>
      <div class="card" style="margin-bottom: 10px;">
        <h3 style="margin-top:0">Качество сервиса и поддержка</h3>
        <div id="qualityBox" class="mini"></div>
      </div>
      <div class="card">
        <h3 style="margin-top:0">Инфраструктура</h3>
        <div id="infraBox" class="mini"></div>
        <div id="metricsError" class="mini muted" style="margin-top:8px;"></div>
      </div>
    </section>

    <section id="usersSection" class="section">
      <div class="search">
        <input id="searchInput" placeholder="Поиск: Telegram ID или username" />
        <button id="searchBtn">Найти</button>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Telegram ID</th><th>Username</th><th>Срок триала</th><th>Без лимитов</th><th>Дата регистрации</th><th>Действия</th></tr>
            </thead>
            <tbody id="usersBody"></tbody>
          </table>
        </div>
        <div class="muted" id="usersHint" style="margin-top:10px"></div>
      </div>
    </section>
  </div>

  <script>
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token') || ''
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null
    const initData = tg ? (tg.initData || '') : ''
    if (tg) { tg.ready(); tg.expand() }

    function authHeaders() { return initData ? { 'X-TG-Init-Data': initData } : {} }
    function withAuth(url) {
      const initQ = initData ? `&init_data=${encodeURIComponent(initData)}` : ''
      const sep = url.includes('?') ? '&' : '?'
      return `${url}${sep}token=${encodeURIComponent(token)}${initQ}`
    }
    function fmt(v) { return v === null || v === undefined ? '—' : v }

    function setupBackToUserButton() {
      const btn = document.getElementById('backToUserBtn')
      if (!initData) return
      btn.style.display = 'inline-block'
      btn.addEventListener('click', () => {
        window.location.href = `/app?init_data=${encodeURIComponent(initData)}`
      })
    }

    async function loadMetrics() {
      const res = await fetch(withAuth('/admin-app/api/metrics'), { headers: authHeaders() })
      if (!res.ok) throw new Error('metrics failed')
      return res.json()
    }
    async function loadUsers(search) {
      const q = search ? `&q=${encodeURIComponent(search)}` : ''
      const res = await fetch(withAuth(`/admin-app/api/users?limit=50${q}`), { headers: authHeaders() })
      if (!res.ok) throw new Error('users failed')
      return res.json()
    }
    async function deactivateUser(telegramId) {
      const res = await fetch(withAuth(`/admin-app/api/user/${telegramId}/deactivate`), { method: 'POST', headers: authHeaders() })
      if (!res.ok) throw new Error('deactivate failed')
      return res.json()
    }
    async function deleteUser(telegramId) {
      const res = await fetch(withAuth(`/admin-app/api/user/${telegramId}`), { method: 'DELETE', headers: authHeaders() })
      if (!res.ok) throw new Error('delete failed')
      return res.json()
    }
    async function setTrial(telegramId, days, unlimited, noTrialLimits) {
      const res = await fetch(withAuth(`/admin-app/api/user/${telegramId}/trial`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ days, unlimited, no_trial_limits: noTrialLimits }),
      })
      if (!res.ok) throw new Error('set trial failed')
      return res.json()
    }

    function metricCard(title, value, sub='') {
      return `<div class="card"><div class="k">${title}</div><div class="v">${fmt(value)}</div><div class="mini">${sub}</div></div>`
    }
    function setTabs(tab) {
      document.querySelectorAll('.tab').forEach((el) => el.classList.toggle('active', el.dataset.tab === tab))
      document.getElementById('metricsSection').classList.toggle('active', tab === 'metrics')
      document.getElementById('usersSection').classList.toggle('active', tab === 'users')
    }

    async function refreshMetrics() {
      try {
        const data = await loadMetrics()
        const kpi = data.kpi || {}
        const local = data.local || {}
        const retention = local.retention || {}
        const support = local.support || {}
        const usage = (data.marzban || {}).usage || {}
        const system = (data.marzban || {}).system || {}
        const err = (data.marzban || {}).error || ''

        document.getElementById('kpiGrid').innerHTML = [
          metricCard('Конверсия start→get', `${fmt(kpi.start_to_get_pct)}%`, 'Цель: >= 50%'),
          metricCard('Конверсия get→подключился', `${fmt(kpi.get_to_connected_pct)}%`, 'Цель: >= 70%'),
          metricCard('Активны на 7-й день', `${fmt(kpi.active_7d_pct)}%`, 'Цель: >= 30%'),
          metricCard('Средний трафик (GB)', fmt(kpi.avg_traffic_gb), 'Цель: >= 3 GB'),
          metricCard('Пользователи > 5GB', fmt(kpi.heavy_users_5gb), 'Реально пользуются'),
          metricCard('Тикеты от активных', `${fmt(kpi.ticket_rate_pct)}%`, 'Норма: < 10%'),
        ].join('')

        const funnel = local.funnel || {}
        document.getElementById('funnelBox').innerHTML = `
          • /start всего: <b>${fmt(funnel.start_total)}</b><br>
          • /get всего: <b>${fmt(funnel.get_total)}</b><br>
          • Start→Get: <b>${fmt(funnel.start_to_get_pct)}%</b><br>
          • Подключились (трафик > 0): <b>${fmt(usage.connected_users)}</b><br>
          • Get→Connected: <b>${fmt(kpi.get_to_connected_pct)}%</b><br>
          • Активны 3/7/14 дней: <b>${fmt(retention.active_3d_pct)}%</b> / <b>${fmt(retention.active_7d_pct)}%</b> / <b>${fmt(retention.active_14d_pct)}%</b>
        `

        document.getElementById('engagementBox').innerHTML = `
          • Всего трафика: <b>${fmt(usage.total_traffic_gb)} GB</b><br>
          • Средний трафик: <b>${fmt(usage.avg_traffic_gb)} GB</b><br>
          • Медианный трафик: <b>${fmt(usage.median_traffic_gb)} GB</b><br>
          • Активных VPN (Marzban status=active): <b>${fmt(usage.active_users)}</b><br>
          • Пик online (по system): <b>${fmt(system.online_users)}</b><br>
          • Среднее время первого подключения: <b>н/д</b> (нет тайм-серии)
        `

        const keywords = support.top_keywords || {}
        const keywordsText = Object.entries(keywords).map(([k, v]) => `${k}: ${v}`).join(', ') || 'нет данных'
        document.getElementById('qualityBox').innerHTML = `
          • Новых тикетов сегодня: <b>${fmt(support.new_tickets_today)}</b><br>
          • % тикетов от активных: <b>${fmt(support.ticket_rate_from_active_pct)}%</b><br>
          • Среднее сообщений в тикете: <b>${fmt(support.avg_messages_per_ticket)}</b><br>
          • % закрытых тикетов: <b>${fmt(support.closed_tickets_pct)}%</b><br>
          • Открытых тикетов: <b>${fmt(support.open_tickets)}</b><br>
          • Топ ключевые слова: <b>${keywordsText}</b>
        `

        document.getElementById('infraBox').innerHTML = `
          • CPU: <b>${fmt(system.cpu_pct)}%</b><br>
          • RAM: <b>${fmt(system.ram_pct)}%</b><br>
          • Версия Marzban: <b>${fmt(system.version)}</b>
        `
        document.getElementById('metricsError').textContent = err ? `Marzban API: ${err}` : ''
      } catch (e) {
        document.getElementById('metricsError').textContent = 'Ошибка загрузки метрик'
      }
    }

    async function refreshUsers() {
      try {
        const searchText = document.getElementById('searchInput').value.trim()
        const usersPayload = await loadUsers(searchText)
        const body = document.getElementById('usersBody')
        body.innerHTML = ''
        for (const u of usersPayload.users) {
          const tr = document.createElement('tr')
          const noLimits = Number(u.no_trial_limits || 0) === 1 ? '✅' : '—'
          tr.innerHTML = `<td>${u.telegram_id}</td><td>${u.username || '-'}</td><td>${u.expires_at || '-'}</td><td>${noLimits}</td><td>${u.created_at || '-'}</td><td><div class="actions"><button data-action="trial" data-id="${u.telegram_id}">Триал</button><button data-action="deactivate" data-id="${u.telegram_id}">Деактивировать</button><button class="red" data-action="delete" data-id="${u.telegram_id}">Удалить</button></div></td>`
          body.appendChild(tr)
        }
        document.getElementById('usersHint').textContent = `Показано ${usersPayload.users.length} пользователей`
      } catch (e) {
        document.getElementById('usersHint').textContent = 'Ошибка загрузки пользователей'
      }
    }

    async function refreshAll() { await Promise.all([refreshMetrics(), refreshUsers()]) }

    document.querySelectorAll('.tab').forEach((el) => {
      el.addEventListener('click', () => setTabs(el.dataset.tab))
    })
    document.getElementById('usersBody').addEventListener('click', async (event) => {
      const target = event.target
      if (!(target instanceof HTMLButtonElement)) return
      const action = target.dataset.action
      const id = target.dataset.id
      if (!action || !id) return
      try {
        if (action === 'deactivate') {
          if (!confirm(`Деактивировать триал для ${id}?`)) return
          await deactivateUser(id)
        }
        if (action === 'delete') {
          if (!confirm(`Удалить пользователя ${id}?`)) return
          await deleteUser(id)
        }
        if (action === 'trial') {
          const unlimited = confirm(`Сделать для ${id} без срока?\nОК = без срока, Отмена = задать дни`)
          let days = 14
          if (!unlimited) {
            const rawDays = prompt('На сколько дней выдать/возобновить триал?', '14')
            if (rawDays === null) return
            days = Number(rawDays)
            if (!Number.isFinite(days) || days < 1) {
              alert('Укажи число дней от 1')
              return
            }
          }
          const noTrialLimits = confirm('Включить галочку "без ограничений" (повторные триалы разрешены)?')
          await setTrial(id, days, unlimited, noTrialLimits)
        }
        await refreshUsers()
        await refreshMetrics()
      } catch (e) {
        document.getElementById('usersHint').textContent = 'Ошибка выполнения действия'
      }
    })
    document.getElementById('refreshBtn').addEventListener('click', refreshAll)
    document.getElementById('searchBtn').addEventListener('click', refreshUsers)
    document.getElementById('searchInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); refreshUsers() }
    })

    setupBackToUserButton()
    refreshAll()
  </script>
</body>
</html>
"""


_USER_APP_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LabGuard</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, Segoe UI, sans-serif;
      background: radial-gradient(circle at top, #1f2937 0%, #0b1020 60%, #070b14 100%);
      color: #e5ecff;
    }
    .wrap { max-width: 680px; margin: 0 auto; padding: 14px; }
    .card {
      background: rgba(19, 28, 48, 0.86);
      border: 1px solid #2b3859;
      border-radius: 16px;
      padding: 14px;
      margin-bottom: 12px;
    }
    h1 { margin: 0 0 8px; font-size: 28px; }
    h2 { margin: 0 0 8px; font-size: 18px; }
    .muted { opacity: .78; font-size: 13px; }
    .status { font-size: 16px; margin: 6px 0; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 12px;
      background: #2563eb;
      color: #fff;
      cursor: pointer;
      font-weight: 600;
    }
    button.secondary { background: #334155; }
    button:disabled { opacity: .6; cursor: default; }
    .sub-link {
      font-size: 13px;
      word-break: break-all;
      padding: 8px;
      border-radius: 10px;
      background: #0f172a;
      border: 1px solid #334155;
      flex: 1;
      min-width: 0;
    }
    .sub-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
    .icon-btn {
      width: 38px;
      min-width: 38px;
      height: 38px;
      padding: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 17px;
    }
    .alert { margin-top: 8px; font-size: 13px; color: #fca5a5; }
    .ok { color: #93c5fd; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>LabGuard</h1>
      <div class="muted">Управление VPN в одном окне</div>
      <div class="row" style="margin-top: 10px;">
        <button id="adminSwitchBtn" class="secondary" style="display:none">Перейти в админ-панель</button>
      </div>
    </div>

    <div class="card">
      <h2>Статус</h2>
      <div id="statusText" class="status">Загружаем...</div>
      <div id="statusMeta" class="muted"></div>
      <div id="statusError" class="alert"></div>
      <div class="row" style="margin-top: 10px;">
        <button id="getVpnBtn">Получить VPN</button>
        <button id="refreshBtn" class="secondary" style="display:none">Обновить статус</button>
      </div>
      <div id="subWrap" class="sub-row" style="display:none">
        <div id="subLink" class="sub-link"></div>
        <button id="copyBtn" class="secondary icon-btn" style="display:none" aria-label="Скопировать">&#128203;</button>
      </div>
    </div>

    <div class="card">
      <h2>Поддержка</h2>
      <div class="row" style="margin-top: 10px;">
        <button id="supportLinkBtn">Открыть бота поддержки</button>
      </div>
      <div id="supportInfo" class="muted" style="margin-top: 8px;">Раздел поддержки в приложении скоро появится.</div>
    </div>
  </div>

  <script>
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null
    const initData = tg ? (tg.initData || '') : ''
    if (tg) { tg.ready(); tg.expand() }

    function authHeaders() { return initData ? { 'X-TG-Init-Data': initData } : {} }
    function withAuth(url) {
      const initQ = initData ? `?init_data=${encodeURIComponent(initData)}` : ''
      return `${url}${initQ}`
    }

    let latestSubscriptionUrl = ''

    function formatTraffic(gbValue) {
      const gb = Number(gbValue || 0)
      if (!Number.isFinite(gb) || gb <= 0) return '0 MB'
      if (gb >= 1) return `${gb.toFixed(2)} GB`
      return `${Math.round(gb * 1024)} MB`
    }

    function renderStatus(data) {
      const statusText = document.getElementById('statusText')
      const statusMeta = document.getElementById('statusMeta')
      const getBtn = document.getElementById('getVpnBtn')
      const refreshBtn = document.getElementById('refreshBtn')

      if (data.subscription_url) showSubscription(data.subscription_url)
      else showSubscription('')

      if (data.is_active) {
        statusText.textContent = 'Активен'
        statusText.classList.add('ok')
        statusMeta.innerHTML = `Осталось: ${data.remaining_days} дн. До: ${data.expires_at} UTC<br>Трафик: ${formatTraffic(data.consumed_traffic_gb)}`
      } else if (data.trial_used) {
        statusText.textContent = 'Триал завершен'
        statusText.classList.remove('ok')
        statusMeta.innerHTML = `Повторная выдача недоступна. Напиши в поддержку.<br>Трафик: ${formatTraffic(data.consumed_traffic_gb)}`
      } else {
        statusText.textContent = 'Не активирован'
        statusText.classList.remove('ok')
        statusMeta.innerHTML = 'Нажми «Получить VPN», чтобы активировать подписку.'
      }

      if (data.trial_used) {
        refreshBtn.style.display = 'inline-block'
        getBtn.style.display = 'none'
      } else {
        getBtn.style.display = 'inline-block'
        getBtn.textContent = 'Получить VPN'
        refreshBtn.style.display = 'none'
      }

      const supportBtn = document.getElementById('supportLinkBtn')
      const supportInfo = document.getElementById('supportInfo')
      if (data.support_username) {
        supportBtn.disabled = false
        supportBtn.dataset.username = data.support_username
        supportInfo.textContent = `Напиши напрямую: @${data.support_username}`
      } else {
        supportBtn.disabled = true
        supportBtn.dataset.username = ''
        supportInfo.textContent = 'Поддержка скоро появится.'
      }

      const adminBtn = document.getElementById('adminSwitchBtn')
      adminBtn.style.display = data.is_admin ? 'inline-block' : 'none'
    }

    function showSubscription(url) {
      latestSubscriptionUrl = url || ''
      const wrap = document.getElementById('subWrap')
      const box = document.getElementById('subLink')
      const copyBtn = document.getElementById('copyBtn')
      if (!latestSubscriptionUrl) {
        wrap.style.display = 'none'
        copyBtn.style.display = 'none'
        return
      }
      wrap.style.display = 'flex'
      box.textContent = latestSubscriptionUrl
      copyBtn.style.display = 'inline-block'
    }

    async function loadStatus() {
      document.getElementById('statusError').textContent = ''
      try {
        const res = await fetch(withAuth('/app/api/status'), { headers: authHeaders() })
        if (!res.ok) throw new Error('status_failed')
        const data = await res.json()
        renderStatus(data)
      } catch (e) {
        document.getElementById('statusError').textContent = 'Не удалось загрузить статус. Открой приложение из Telegram.'
      }
    }

    async function getVpn() {
      const btn = document.getElementById('getVpnBtn')
      btn.disabled = true
      document.getElementById('statusError').textContent = ''
      try {
        const res = await fetch(withAuth('/app/api/get-vpn'), { method: 'POST', headers: authHeaders() })
        const data = await res.json()
        if (!res.ok || data.ok === false) {
          throw new Error(data.detail || data.message || 'Не удалось получить VPN')
        }
        if (data.subscription_url) showSubscription(data.subscription_url)
        await loadStatus()
      } catch (e) {
        document.getElementById('statusError').textContent = String(e.message || e)
      } finally {
        btn.disabled = false
      }
    }

    document.getElementById('refreshBtn').addEventListener('click', loadStatus)
    document.getElementById('getVpnBtn').addEventListener('click', getVpn)
    document.getElementById('supportLinkBtn').addEventListener('click', () => {
      const btn = document.getElementById('supportLinkBtn')
      const username = btn.dataset.username || ''
      if (!username) return
      const url = `https://t.me/${username}`
      if (tg && typeof tg.openTelegramLink === 'function') {
        tg.openTelegramLink(url)
      } else {
        window.open(url, '_blank')
      }
    })
    document.getElementById('adminSwitchBtn').addEventListener('click', () => {
      if (!initData) return
      window.location.href = `/admin-app?init_data=${encodeURIComponent(initData)}`
    })
    document.getElementById('copyBtn').addEventListener('click', async () => {
      if (!latestSubscriptionUrl) return
      try {
        await navigator.clipboard.writeText(latestSubscriptionUrl)
        document.getElementById('statusError').textContent = 'Ссылка скопирована'
      } catch (e) {
        document.getElementById('statusError').textContent = latestSubscriptionUrl
      }
    })

    loadStatus()
  </script>
</body>
</html>
"""
