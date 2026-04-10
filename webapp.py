import asyncio
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

from config import Settings
from database import Database
from miniapp_auth import verify_admin_token, verify_telegram_init_data
from xui import XUIClient


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
    for value in (user.get("panel_client_id"), user.get("marzban_id"), user.get("username"), f"tg_{telegram_id}"):
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


def _apply_subscription_display_names(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return text

    fixed_name = "Финляндия"
    encoded_name = quote(fixed_name)

    if text.lower().startswith("vless://"):
        base, sep, _fragment = text.partition("#")
        if sep:
            return f"{base}#{encoded_name}"
        return f"{text}#{encoded_name}"

    if text.lower().startswith(("http://", "https://")):
        base, _sep, _fragment = text.partition("#")
        return base

    return text


def _build_marzban_username(telegram_id: int, username: str) -> str:
    base = (username or f"tg_{telegram_id}").lower()
    safe = re.sub(r"[^a-z0-9_]", "_", base)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        safe = f"tg_{telegram_id}"
    return f"labguard_{safe}"[:48].rstrip("_")


class AdminTrialPayload(BaseModel):
    expires_at: str
    no_trial_limits: bool = False


def _parse_admin_datetime_local(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid expires_at format") from exc


def _to_admin_datetime_local(expires_at: str | None) -> str:
    if expires_at:
        try:
            dt = _parse_sqlite_dt(expires_at)
        except ValueError:
            dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=14)
    else:
        dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=14)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _format_trial_notification(expires_at: str) -> str:
    return (
        "✨ Администратор обновил ваш пробный период LabGuard.\n\n"
        f"Новый срок действия доступа: {expires_at} UTC.\n"
        "Если приложение уже открыто, просто обновите статус и продолжайте пользоваться сервисом."
    )


def build_app(
    db: Database,
    settings: Settings,
    marzban: XUIClient,
    bot: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="VPN Admin Mini App", docs_url=None, redoc_url=None)

    async def _resolve_online_state(user: dict[str, Any], telegram_id: int) -> dict[str, Any]:
        for candidate in _candidate_marzban_usernames(user, telegram_id):
            try:
                status = await marzban.get_user_online_status(candidate)
            except Exception:
                return {"online_now": None, "online_status": "unknown"}
            if status.get("online_status") != "unknown":
                return status
        return {"online_now": None, "online_status": "unknown"}

    async def _notify_trial_changed(telegram_id: int, expires_at: str) -> bool:
        if bot is None:
            return False
        try:
            await bot.send_message(telegram_id, _format_trial_notification(expires_at))
        except Exception:
            return False
        return True

    async def _notify_admin_about_vpn_issued(telegram_id: int, username: str | None) -> bool:
        if bot is None:
            return False
        admin_ids = sorted(settings.admin_telegram_ids)
        if not admin_ids:
            return False
        username_text = f"@{username}" if username else "без username"
        text = (
            "Новый пользователь получил VPN-ссылку.\n\n"
            f"Пользователь: {username_text}\n"
            f"Telegram ID: {telegram_id}\n"
            f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        try:
            await bot.send_message(admin_ids[0], text)
        except Exception:
            return False
        return True

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
        panel_error = ""
        try:
            marzban_usage = await marzban.get_users_usage_snapshot()
            marzban_system = await marzban.get_system_snapshot()
            connected_users = int(marzban_usage.get("connected_users", 0))
            online_now = int(marzban_system.get("online_users", 0))
        except Exception as exc:
            panel_error = str(exc)

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
                "marzban_error": panel_error,
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

    @app.get("/admin-app/api/user/{telegram_id}")
    async def admin_user_detail(
        telegram_id: int,
        token: str = Query(""),
        init_data: str = Query(""),
        x_tg_init_data: str = Header(default="", alias="X-TG-Init-Data"),
    ) -> dict:
        _verify_admin(settings, token, x_tg_init_data or init_data)

        user = db.get_admin_user_detail(telegram_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        online_state = await _resolve_online_state(user, telegram_id)
        return {
            "user": {
                **user,
                **online_state,
                "edit_expires_at": _to_admin_datetime_local(user.get("expires_at")),
            }
        }

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

        target_dt = _parse_admin_datetime_local(payload.expires_at)
        local_expires = target_dt.strftime("%Y-%m-%d %H:%M:%S")

        marzban_changed = False
        for candidate in _candidate_marzban_usernames(user, telegram_id):
            if await marzban.update_user_trial(candidate, expire_at=target_dt, active=True):
                marzban_changed = True
                break

        if not marzban_changed:
            marzban_username = _build_marzban_username(telegram_id, str(user.get("username") or ""))
            marzban_user = await marzban.create_user(username=marzban_username, expire_at=target_dt)
            marzban_changed = bool(marzban_user)
            user = db.get_user_by_telegram_id(telegram_id) or user
            db.set_panel_binding(
                telegram_id=telegram_id,
                panel_client_id=str(marzban_user.get("email", marzban_username)),
                expires_at=local_expires,
            )

        db.set_user_expiry(telegram_id, local_expires)
        db.set_no_trial_limits(telegram_id, payload.no_trial_limits)
        if payload.no_trial_limits:
            db.clear_trial_lock(telegram_id)
        else:
            db.mark_trial_used(telegram_id)

        db.log_event(telegram_id, "admin_set_trial_webapp")
        notification_sent = await _notify_trial_changed(telegram_id, local_expires)
        return {
            "ok": True,
            "expires_at": local_expires,
            "trial_active": True,
            "no_trial_limits": payload.no_trial_limits,
            "marzban_changed": marzban_changed,
            "notification_sent": notification_sent,
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
            stored_subscription_url = str(user.get("subscription_url") or "").strip()
            if stored_subscription_url:
                subscription_url = stored_subscription_url
            for candidate in _candidate_marzban_usernames(user, telegram_id):
                try:
                    marzban_user = await marzban.get_user(candidate)
                except Exception:
                    marzban_user = None
                if marzban_user:
                    if not subscription_url:
                        subscription_url, is_subscription = _extract_subscription_text(marzban_user)
                        if is_subscription:
                            subscription_url = _normalize_subscription_url(subscription_url, marzban.public_base_url)
                        subscription_url = _apply_subscription_display_names(subscription_url)
                        if subscription_url:
                            db.set_subscription_url(telegram_id, subscription_url)
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
                    try:
                        marzban_user = await marzban.get_user(candidate)
                    except Exception:
                        marzban_user = None
                    if marzban_user:
                        break

                sub_text = ""
                is_subscription = False
                if marzban_user:
                    stored_subscription_url = str(existing.get("subscription_url") or "").strip()
                    if stored_subscription_url:
                        sub_text = stored_subscription_url
                    else:
                        sub_text, is_subscription = _extract_subscription_text(marzban_user)
                        if is_subscription:
                            sub_text = _normalize_subscription_url(sub_text, marzban.public_base_url)
                        sub_text = _apply_subscription_display_names(sub_text)
                        if sub_text:
                            db.set_subscription_url(telegram_id, sub_text)

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
            raise HTTPException(status_code=503, detail="3X-UI API не настроен")

        expiry_dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=settings.free_trial_days)
        marzban_username = _build_marzban_username(telegram_id, username)

        try:
            marzban_user = await marzban.create_user(username=marzban_username, expire_at=expiry_dt)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Не удалось создать подписку через 3X-UI: {exc}") from exc

        expires_at = datetime.fromtimestamp(
            int(marzban_user.get("expire", int(expiry_dt.timestamp()))),
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S")

        db.set_panel_binding(
            telegram_id=telegram_id,
            panel_client_id=str(marzban_user.get("email", marzban_username)),
            expires_at=expires_at,
        )
        db.mark_trial_used(telegram_id)
        db.touch_last_active(telegram_id)
        db.log_event(telegram_id, "app_get")

        config_text, is_subscription = _extract_subscription_text(marzban_user)
        if is_subscription:
            config_text = _normalize_subscription_url(config_text, marzban.public_base_url)
        config_text = _apply_subscription_display_names(config_text)
        if config_text:
            db.set_subscription_url(telegram_id, config_text)
        await _notify_admin_about_vpn_issued(telegram_id, username)

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
    marzban: XUIClient,
    bot: Any | None = None,
) -> tuple[uvicorn.Server, asyncio.Task]:
    app = build_app(db, settings, marzban, bot=bot)
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
    :root {
      color-scheme: light;
      --bg: #eef4fb;
      --bg-strong: #dfeaf8;
      --surface: rgba(255, 255, 255, 0.84);
      --surface-strong: #ffffff;
      --surface-soft: #f4f8fd;
      --line: rgba(129, 153, 189, 0.28);
      --line-strong: rgba(104, 132, 176, 0.38);
      --text: #203049;
      --muted: #627493;
      --accent: #3e6fd9;
      --accent-soft: #e8f0ff;
      --success: #2c8b63;
      --success-soft: #e9f7f0;
      --warn: #b9792c;
      --warn-soft: #fff6e6;
      --danger: #bf5a68;
      --danger-soft: #fff0f2;
      --shadow: 0 20px 48px rgba(56, 83, 125, 0.14);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
      --radius-sm: 12px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(132, 169, 255, 0.32), transparent 28%),
        radial-gradient(circle at top right, rgba(157, 208, 196, 0.28), transparent 24%),
        linear-gradient(180deg, #f8fbff 0%, var(--bg) 45%, #e8eff8 100%);
    }
    body::before,
    body::after {
      content: "";
      position: fixed;
      inset: auto;
      pointer-events: none;
      z-index: 0;
      border-radius: 999px;
      filter: blur(16px);
      opacity: 0.7;
    }
    body::before {
      width: 240px;
      height: 240px;
      top: 64px;
      right: -60px;
      background: rgba(126, 171, 255, 0.18);
    }
    body::after {
      width: 220px;
      height: 220px;
      bottom: 48px;
      left: -44px;
      background: rgba(140, 205, 190, 0.14);
    }
    .wrap {
      position: relative;
      z-index: 1;
      max-width: 1120px;
      margin: 0 auto;
      padding: 18px 14px 28px;
    }
    .fade-up {
      animation: fadeUp .42s ease both;
    }
    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }
    .hero {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 22px;
      margin-bottom: 14px;
      background:
        linear-gradient(140deg, rgba(255, 255, 255, 0.92) 0%, rgba(243, 248, 255, 0.82) 62%, rgba(231, 241, 255, 0.92) 100%);
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(232, 240, 255, 0.92);
      border: 1px solid rgba(95, 132, 199, 0.22);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .title {
      margin: 12px 0 8px;
      font-size: 34px;
      line-height: 1.05;
    }
    .subtitle {
      margin: 0;
      max-width: 620px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
    }
    .hero-actions,
    .tabs {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    button,
    .tab {
      appearance: none;
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease, border-color .18s ease;
    }
    button:hover,
    .tab:hover { transform: translateY(-1px); }
    button:disabled { opacity: .58; cursor: default; transform: none; }
    .btn-primary {
      background: linear-gradient(135deg, #3e6fd9 0%, #5a8df2 100%);
      color: #fff;
      box-shadow: 0 14px 28px rgba(73, 110, 191, 0.24);
    }
    .btn-secondary,
    .tab {
      background: rgba(255, 255, 255, 0.7);
      color: var(--text);
      border: 1px solid rgba(108, 134, 175, 0.22);
      box-shadow: 0 10px 24px rgba(90, 115, 153, 0.08);
    }
    .btn-soft {
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid rgba(96, 135, 206, 0.18);
    }
    .btn-danger {
      background: var(--danger-soft);
      color: var(--danger);
      border: 1px solid rgba(191, 90, 104, 0.16);
    }
    .tab.active {
      background: linear-gradient(135deg, #3e6fd9 0%, #5a8df2 100%);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 14px 28px rgba(73, 110, 191, 0.22);
    }
    .section { display: none; }
    .section.active { display: block; }
    .section-shell {
      padding: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.78) 0%, rgba(246,250,255,0.9) 100%);
    }
    .metrics-head {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }
    .metrics-title,
    .users-title {
      margin: 0 0 4px;
      font-size: 23px;
    }
    .metrics-subtitle,
    .users-subtitle,
    .metrics-meta,
    .muted {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .metrics-warning,
    .status-banner {
      display: none;
      margin-bottom: 14px;
      padding: 12px 14px;
      border-radius: var(--radius-md);
      background: var(--danger-soft);
      border: 1px solid rgba(191, 90, 104, 0.18);
      color: #9d4252;
      font-size: 13px;
      line-height: 1.45;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    .metric-card {
      padding: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94) 0%, rgba(244,248,253,0.98) 100%);
      border-radius: 20px;
      border: 1px solid rgba(117, 147, 191, 0.16);
      box-shadow: 0 16px 34px rgba(87, 113, 155, 0.11);
    }
    .tone-primary { box-shadow: inset 0 0 0 1px rgba(132, 169, 255, 0.26), 0 16px 34px rgba(87, 113, 155, 0.11); }
    .tone-accent { box-shadow: inset 0 0 0 1px rgba(94, 139, 219, 0.26), 0 16px 34px rgba(87, 113, 155, 0.11); }
    .tone-success { box-shadow: inset 0 0 0 1px rgba(72, 155, 118, 0.26), 0 16px 34px rgba(87, 113, 155, 0.11); }
    .tone-info { box-shadow: inset 0 0 0 1px rgba(92, 157, 184, 0.26), 0 16px 34px rgba(87, 113, 155, 0.11); }
    .tone-warn { box-shadow: inset 0 0 0 1px rgba(201, 149, 82, 0.24), 0 16px 34px rgba(87, 113, 155, 0.11); }
    .tone-danger { box-shadow: inset 0 0 0 1px rgba(191, 90, 104, 0.22), 0 16px 34px rgba(87, 113, 155, 0.11); }
    .k {
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      font-weight: 700;
    }
    .v {
      margin-top: 14px;
      font-size: 34px;
      line-height: 1;
      font-weight: 800;
      color: var(--text);
    }
    .metric-caption {
      margin-top: 10px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.45;
    }
    .users-shell {
      display: grid;
      gap: 14px;
    }
    .search-panel,
    .users-list-card {
      padding: 18px;
    }
    .search {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    input {
      flex: 1 1 260px;
      width: 100%;
      min-width: 0;
      min-height: 48px;
      border-radius: 14px;
      border: 1px solid rgba(106, 132, 172, 0.22);
      background: rgba(255, 255, 255, 0.82);
      color: var(--text);
      padding: 12px 14px;
      font: inherit;
      line-height: 1.2;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
    }
    input::placeholder { color: #8a9ab5; }
    #usersSection .card {
      background: linear-gradient(180deg, rgba(255,255,255,0.92) 0%, rgba(244,248,253,0.96) 100%);
      border: 1px solid rgba(117, 147, 191, 0.16);
      box-shadow: 0 16px 34px rgba(87, 113, 155, 0.11);
    }
    .users-alert {
      display: none;
      margin: 14px 0 0;
      border-radius: var(--radius-md);
      padding: 12px 14px;
      font-size: 13px;
      line-height: 1.45;
    }
    .users-alert.info { display: block; background: var(--accent-soft); border: 1px solid rgba(94, 139, 219, 0.16); color: #29406d; }
    .users-alert.success { display: block; background: var(--success-soft); border: 1px solid rgba(44, 139, 99, 0.16); color: #24533a; }
    .users-alert.warn { display: block; background: var(--warn-soft); border: 1px solid rgba(185, 121, 44, 0.16); color: #80531e; }
    .users-alert.error { display: block; background: var(--danger-soft); border: 1px solid rgba(191, 90, 104, 0.16); color: #8f2b37; }
    .user-list { display: flex; flex-direction: column; gap: 12px; margin-top: 14px; }
    .user-row {
      width: 100%;
      border: 1px solid rgba(117, 147, 191, 0.16);
      background: rgba(255, 255, 255, 0.82);
      border-radius: 18px;
      padding: 16px;
      text-align: left;
      color: var(--text);
      cursor: pointer;
      box-shadow: 0 12px 28px rgba(87, 113, 155, 0.1);
    }
    .user-row:hover { transform: translateY(-1px); box-shadow: 0 16px 32px rgba(87, 113, 155, 0.16); }
    .user-row-head,
    .user-detail-head,
    .detail-topline,
    .inline-form-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .user-row-id,
    .detail-username { font-size: 18px; font-weight: 700; color: var(--text); }
    .user-row-meta,
    .detail-subtitle { margin-top: 4px; font-size: 13px; color: var(--muted); }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .badge-success {
      background: var(--success-soft);
      color: var(--success);
      border: 1px solid rgba(44, 139, 99, 0.14);
    }
    .badge-muted {
      background: rgba(233, 239, 248, 0.88);
      color: #647692;
      border: 1px solid rgba(114, 137, 169, 0.14);
    }
    .badge-warn {
      background: var(--warn-soft);
      color: var(--warn);
      border: 1px solid rgba(185, 121, 44, 0.14);
    }
    .badge-info {
      background: var(--accent-soft);
      color: #2f4f88;
      border: 1px solid rgba(94, 139, 219, 0.16);
    }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    .actions button {
      padding: 8px 12px;
      font-size: 12px;
      box-shadow: none;
    }
    .detail-layout { display: grid; grid-template-columns: 1.35fr 1fr; gap: 14px; margin-top: 14px; }
    .detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
    .detail-field {
      padding: 14px;
      border: 1px solid rgba(121, 147, 186, 0.16);
      border-radius: var(--radius-md);
      background: rgba(255, 255, 255, 0.78);
    }
    .detail-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 700; }
    .detail-value { font-size: 15px; font-weight: 700; color: var(--text); }
    .secondary-button,
    .ghost-button {
      background: rgba(255, 255, 255, 0.72);
      color: var(--text);
      border: 1px solid rgba(108, 134, 175, 0.22);
      box-shadow: 0 10px 24px rgba(90, 115, 153, 0.08);
    }
    .warn-button {
      background: var(--warn-soft);
      color: var(--warn);
      border: 1px solid rgba(185, 121, 44, 0.16);
      box-shadow: none;
    }
    .inline-form { margin-top: 14px; padding-top: 14px; border-top: 1px solid rgba(121, 147, 186, 0.16); }
    .inline-form[hidden] { display: none; }
    .empty-state {
      padding: 22px;
      text-align: center;
      color: var(--muted);
      background: linear-gradient(180deg, rgba(255,255,255,0.86) 0%, rgba(245,249,255,0.96) 100%);
      border: 1px dashed rgba(116, 144, 186, 0.28);
      border-radius: 18px;
    }
    @media (max-width: 920px) {
      .hero,
      .metrics-head { flex-direction: column; align-items: stretch; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .title { font-size: 30px; }
    }
    @media (max-width: 820px) {
      .detail-layout,
      .detail-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 640px) {
      .wrap { padding-left: 12px; padding-right: 12px; }
      .hero,
      .section-shell,
      .search-panel { padding: 16px; }
      .grid { grid-template-columns: 1fr; }
      .search input { flex: none; }
      .actions button,
      .hero-actions button,
      .search button,
      .tabs button,
      .inline-form-actions button,
      .ghost-button { width: 100%; justify-content: center; }
      .user-row-head,
      .user-detail-head,
      .detail-topline,
      .search,
      .inline-form-actions { flex-direction: column; }
    }
  </style>
</head>
<body>
  <div class="wrap fade-up">
    <header class="hero card">
      <div>
        <div class="eyebrow">LabGuard Admin</div>
        <h1 class="title">Единая панель управления</h1>
        <p class="subtitle">Метрики, пользователи и действия администратора собраны в одном спокойном, светлом и аккуратном интерфейсе.</p>
      </div>
      <div class="hero-actions">
        <button id="backToUserBtn" class="btn-secondary" style="display:none">В приложение пользователя</button>
        <button id="refreshBtn" class="btn-primary">Обновить данные</button>
      </div>
    </header>

    <div class="tabs" style="margin-bottom: 14px;">
      <button class="tab active" data-tab="metrics">Метрика</button>
      <button class="tab" data-tab="users">Пользователи</button>
    </div>

    <section id="metricsSection" class="section active fade-up">
      <div class="card section-shell">
        <div class="metrics-head">
          <div>
            <h2 class="metrics-title">Ключевые метрики</h2>
            <p class="metrics-subtitle">Сводка по воронке, подключениям и текущему состоянию пробных периодов.</p>
          </div>
          <p id="metricsGeneratedAt" class="metrics-meta">Сформировано: —</p>
        </div>
        <div id="metricsWarning" class="metrics-warning"></div>
        <div class="grid metrics-grid" id="kpiGrid"></div>
      </div>
    </section>

    <section id="usersSection" class="section fade-up">
      <div class="users-shell">
        <div class="card search-panel">
          <h2 class="users-title">Пользователи</h2>
          <p class="users-subtitle">Поиск, карточка пользователя и управление сроком пробного периода в одном спокойном интерфейсе.</p>
          <div class="search">
            <input id="searchInput" placeholder="Поиск по username или Telegram ID" />
            <button id="searchBtn" class="btn-primary">Найти</button>
          </div>
          <div id="usersFlash" class="users-alert"></div>
          <div id="userListSection">
            <div id="userList" class="user-list"></div>
            <div class="muted" id="usersHint" style="margin-top:10px"></div>
          </div>
          <div id="userDetailSection" hidden>
            <button id="backToListBtn" class="ghost-button">← Назад к списку</button>
            <div id="userDetailBody" style="margin-top:12px"></div>
          </div>
        </div>
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
    const userState = {
      search: '',
      users: [],
      selectedUserId: null,
      currentUser: null,
    }

    async function loadUsers(search) {
      const q = search ? `&q=${encodeURIComponent(search)}` : ''
      const res = await fetch(withAuth(`/admin-app/api/users?limit=50${q}`), { headers: authHeaders() })
      if (!res.ok) throw new Error('users failed')
      return res.json()
    }
    async function loadUserDetail(telegramId) {
      const res = await fetch(withAuth(`/admin-app/api/user/${telegramId}`), { headers: authHeaders() })
      if (!res.ok) throw new Error('user detail failed')
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
    async function setTrial(telegramId, expiresAt, noTrialLimits) {
      const res = await fetch(withAuth(`/admin-app/api/user/${telegramId}/trial`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ expires_at: expiresAt, no_trial_limits: noTrialLimits }),
      })
      if (!res.ok) throw new Error('set trial failed')
      return res.json()
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
    }
    function badgeClass(active) { return active ? 'badge-success' : 'badge-muted' }
    function trialLabel(active) { return active ? 'Активен' : 'Неактивен' }
    function onlineLabel(status) {
      if (status === 'online') return 'Да'
      if (status === 'offline') return 'Нет'
      return 'Не удалось определить'
    }
    function setUsersFlash(message, tone='info') {
      const el = document.getElementById('usersFlash')
      if (!message) {
        el.className = 'users-alert'
        el.textContent = ''
        return
      }
      el.className = `users-alert ${tone}`
      el.textContent = message
    }
    function showUserList() {
      document.getElementById('userListSection').hidden = false
      document.getElementById('userDetailSection').hidden = true
    }
    function showUserDetail() {
      document.getElementById('userListSection').hidden = true
      document.getElementById('userDetailSection').hidden = false
    }
    function renderUsersList(users) {
      const list = document.getElementById('userList')
      if (!users.length) {
        list.innerHTML = '<div class="empty-state">Ничего не найдено. Попробуйте другой username или Telegram ID.</div>'
        return
      }
      list.innerHTML = users.map((u) => `
        <button class="user-row" data-id="${u.telegram_id}">
          <div class="user-row-head">
            <div>
              <div class="user-row-id">${escapeHtml(u.telegram_id)}</div>
              <div class="user-row-meta">(${u.username ? '@' + escapeHtml(u.username) : 'без username'})</div>
            </div>
            <span class="badge ${badgeClass(Boolean(u.trial_active))}">${Boolean(u.trial_active) ? '✅' : '❌'} ${trialLabel(Boolean(u.trial_active))}</span>
          </div>
        </button>
      `).join('')
    }
    function renderUserDetail(user) {
      const body = document.getElementById('userDetailBody')
      body.innerHTML = `
        <div class="detail-layout">
          <div class="card">
            <div class="user-detail-head">
              <div>
                <div class="detail-username">${user.username ? '@' + escapeHtml(user.username) : 'Без username'}</div>
                <div class="detail-subtitle">Telegram ID: ${escapeHtml(user.telegram_id)}</div>
              </div>
              <span class="badge ${badgeClass(Boolean(user.trial_active))}">${trialLabel(Boolean(user.trial_active))}</span>
            </div>
            <div class="detail-grid">
              <div class="detail-field"><div class="detail-label">Telegram ID</div><div class="detail-value">${escapeHtml(user.telegram_id)}</div></div>
              <div class="detail-field"><div class="detail-label">Username</div><div class="detail-value">${user.username ? '@' + escapeHtml(user.username) : 'Без username'}</div></div>
              <div class="detail-field"><div class="detail-label">Дата регистрации</div><div class="detail-value">${escapeHtml(user.created_at || '—')}</div></div>
              <div class="detail-field"><div class="detail-label">Пробный период действует до</div><div class="detail-value">${escapeHtml(user.expires_at || '—')}</div></div>
              <div class="detail-field"><div class="detail-label">Статус пробного периода</div><div class="detail-value">${trialLabel(Boolean(user.trial_active))}</div></div>
              <div class="detail-field"><div class="detail-label">Сейчас онлайн</div><div class="detail-value">${onlineLabel(user.online_status)}</div></div>
            </div>
          </div>
          <div class="card">
            <div class="k" style="color:#5a6e96;opacity:1;">Действия</div>
            <div class="detail-subtitle" style="margin-bottom:12px;">Управление пользователем и сроком пробного периода.</div>
            <div class="actions">
              <button data-action="edit-trial" data-id="${user.telegram_id}">Изменить дату подписки</button>
              <button class="warn-button" data-action="deactivate" data-id="${user.telegram_id}">Деактивировать</button>
              <button class="btn-danger" data-action="delete" data-id="${user.telegram_id}">Удалить</button>
            </div>
            <div id="trialEditor" class="inline-form" hidden>
              <div class="detail-label">Дата окончания пробного периода</div>
              <input id="trialDateInput" type="datetime-local" value="${escapeHtml(user.edit_expires_at || '')}" />
              <div class="inline-form-actions">
                <button id="saveTrialBtn" data-action="save-trial" data-id="${user.telegram_id}" disabled>Сохранить</button>
                <button id="cancelTrialBtn" class="secondary-button" data-action="cancel-trial">Отмена</button>
              </div>
            </div>
          </div>
        </div>
      `
      showUserDetail()
    }

    function metricCard(title, value, caption, tone) {
      const toneClass = tone ? ` tone-${tone}` : ''
      return `<div class="metric-card${toneClass}"><div class="k">${title}</div><div class="v">${fmt(value)}</div><div class="metric-caption">${caption}</div></div>`
    }
    function setTabs(tab) {
      document.querySelectorAll('.tab').forEach((el) => el.classList.toggle('active', el.dataset.tab === tab))
      document.getElementById('metricsSection').classList.toggle('active', tab === 'metrics')
      document.getElementById('usersSection').classList.toggle('active', tab === 'users')
    }

    async function refreshMetrics() {
      const warning = document.getElementById('metricsWarning')
      const generatedAtEl = document.getElementById('metricsGeneratedAt')
      try {
        const data = await loadMetrics()
        const metrics = data.metrics || {}
        const meta = data.meta || {}
        generatedAtEl.textContent = `Сформировано: ${meta.generated_at || '—'}`

        document.getElementById('kpiGrid').innerHTML = [
          metricCard('Нажали /start', metrics.start_users, 'Уникальные пользователи, открывшие бота.', 'primary'),
          metricCard('Получили VPN ссылку', metrics.vpn_link_users, 'Пользователи, дошедшие до выдачи ссылки.', 'accent'),
          metricCard('Подключили и потратили трафик', metrics.connected_users, 'Есть подтвержденное подключение с трафиком.', 'success'),
          metricCard('Онлайн сейчас', metrics.online_now, 'Текущее число активных подключений в Marzban.', 'info'),
          metricCard('Активный триал', metrics.active_trials, 'Триальные подписки, срок которых еще не истек.', 'warn'),
          metricCard('Триал закончился', metrics.expired_trials, 'Пользователи с завершенным пробным периодом.', 'danger'),
        ].join('')

        const marzbanError = meta.marzban_error || ''
        if (marzbanError) {
          warning.style.display = 'block'
          warning.textContent = `Некоторые данные могут быть неполными: ${marzbanError}`
        } else {
          warning.style.display = 'none'
          warning.textContent = ''
        }
      } catch (e) {
        generatedAtEl.textContent = 'Сформировано: —'
        warning.style.display = 'block'
        warning.textContent = 'Ошибка загрузки метрик'
      }
    }

    async function openUserDetail(telegramId) {
      const payload = await loadUserDetail(telegramId)
      userState.selectedUserId = Number(telegramId)
      userState.currentUser = payload.user
      renderUserDetail(payload.user)
    }

    async function refreshUsers(preserveDetail = true) {
      try {
        const searchText = document.getElementById('searchInput').value.trim()
        userState.search = searchText
        const usersPayload = await loadUsers(searchText)
        userState.users = usersPayload.users || []
        renderUsersList(userState.users)
        document.getElementById('usersHint').textContent = `Показано ${usersPayload.users.length} пользователей`
        if (preserveDetail && userState.selectedUserId) {
          await openUserDetail(userState.selectedUserId)
        } else if (!userState.selectedUserId) {
          showUserList()
        }
      } catch (e) {
        document.getElementById('usersHint').textContent = 'Ошибка загрузки пользователей'
        setUsersFlash('Не удалось загрузить список пользователей.', 'error')
      }
    }

    async function refreshAll() { await Promise.all([refreshMetrics(), refreshUsers(Boolean(userState.selectedUserId))]) }

    document.querySelectorAll('.tab').forEach((el) => {
      el.addEventListener('click', () => setTabs(el.dataset.tab))
    })
    document.getElementById('userList').addEventListener('click', async (event) => {
      const target = event.target
      const row = target instanceof HTMLElement ? target.closest('.user-row') : null
      if (!row) return
      try {
        setUsersFlash('')
        await openUserDetail(row.dataset.id)
      } catch (e) {
        setUsersFlash('Не удалось открыть карточку пользователя.', 'error')
      }
    })
    document.getElementById('userDetailBody').addEventListener('click', async (event) => {
      const target = event.target
      if (!(target instanceof HTMLButtonElement)) return
      const action = target.dataset.action
      const id = target.dataset.id
      try {
        if (action === 'edit-trial') {
          document.getElementById('trialEditor').hidden = false
          return
        }
        if (action === 'cancel-trial') {
          document.getElementById('trialEditor').hidden = true
          document.getElementById('trialDateInput').value = userState.currentUser.edit_expires_at || ''
          document.getElementById('saveTrialBtn').disabled = true
          return
        }
        if (action === 'deactivate' && id) {
          if (!confirm(`Деактивировать триал для ${id}?`)) return
          await deactivateUser(id)
          setUsersFlash('Пробный период пользователя деактивирован.', 'success')
        }
        if (action === 'delete' && id) {
          if (!confirm(`Удалить пользователя ${id}?`)) return
          await deleteUser(id)
          userState.selectedUserId = null
          userState.currentUser = null
          showUserList()
          setUsersFlash('Пользователь удален. Триал можно будет выдать заново.', 'success')
          await refreshUsers(false)
          await refreshMetrics()
          return
        }
        if (action === 'save-trial' && id) {
          const dateValue = document.getElementById('trialDateInput').value
          if (!dateValue) {
            setUsersFlash('Укажите дату окончания пробного периода.', 'warn')
            return
          }
          const result = await setTrial(id, dateValue, Boolean(userState.currentUser && userState.currentUser.no_trial_limits))
          if (result.notification_sent) {
            setUsersFlash(`Дата пробного периода обновлена до ${result.expires_at}. Пользователь уведомлен.`, 'success')
          } else {
            setUsersFlash(`Дата пробного периода обновлена до ${result.expires_at}, но уведомление не отправлено.`, 'warn')
          }
        }
        await refreshUsers(true)
        await refreshMetrics()
      } catch (e) {
        setUsersFlash('Не удалось выполнить действие для пользователя.', 'error')
      }
    })
    document.getElementById('userDetailBody').addEventListener('input', (event) => {
      const target = event.target
      if (!(target instanceof HTMLInputElement) || target.id !== 'trialDateInput') return
      const saveBtn = document.getElementById('saveTrialBtn')
      if (!(saveBtn instanceof HTMLButtonElement)) return
      saveBtn.disabled = target.value === (userState.currentUser && userState.currentUser.edit_expires_at)
    })
    document.getElementById('refreshBtn').addEventListener('click', refreshAll)
    document.getElementById('searchBtn').addEventListener('click', () => refreshUsers(false))
    document.getElementById('searchInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); refreshUsers(false) }
    })
    document.getElementById('backToListBtn').addEventListener('click', () => {
      userState.selectedUserId = null
      userState.currentUser = null
      setUsersFlash('')
      showUserList()
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
    :root {
      color-scheme: light;
      --bg: #eef4fb;
      --surface: rgba(255, 255, 255, 0.84);
      --surface-strong: #ffffff;
      --surface-soft: #f4f8fd;
      --line: rgba(129, 153, 189, 0.28);
      --text: #203049;
      --muted: #627493;
      --accent: #3e6fd9;
      --accent-soft: #e8f0ff;
      --success: #2c8b63;
      --success-soft: #e9f7f0;
      --warn: #b9792c;
      --warn-soft: #fff6e6;
      --danger: #bf5a68;
      --danger-soft: #fff0f2;
      --shadow: 0 20px 48px rgba(56, 83, 125, 0.14);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
      --radius-sm: 12px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(132, 169, 255, 0.3), transparent 30%),
        radial-gradient(circle at top right, rgba(157, 208, 196, 0.22), transparent 26%),
        linear-gradient(180deg, #f8fbff 0%, var(--bg) 50%, #e8eff8 100%);
    }
    .wrap { max-width: 760px; margin: 0 auto; padding: 18px 14px 28px; }
    .card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 18px;
      margin-bottom: 14px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }
    .hero {
      padding: 22px;
      background: linear-gradient(140deg, rgba(255,255,255,0.94) 0%, rgba(243,248,255,0.82) 62%, rgba(231,241,255,0.92) 100%);
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(232, 240, 255, 0.92);
      color: var(--accent);
      border: 1px solid rgba(95, 132, 199, 0.22);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    h1 { margin: 12px 0 8px; font-size: 32px; line-height: 1.05; }
    h2 { margin: 0 0 8px; font-size: 22px; }
    .muted { color: var(--muted); font-size: 13px; line-height: 1.5; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      background: linear-gradient(135deg, #3e6fd9 0%, #5a8df2 100%);
      color: #fff;
      cursor: pointer;
      font-weight: 600;
      font: inherit;
      box-shadow: 0 14px 28px rgba(73, 110, 191, 0.22);
      transition: transform .18s ease, box-shadow .18s ease, opacity .18s ease;
    }
    button:hover { transform: translateY(-1px); }
    button.secondary {
      background: rgba(255, 255, 255, 0.72);
      color: var(--text);
      border: 1px solid rgba(108, 134, 175, 0.22);
      box-shadow: 0 10px 24px rgba(90, 115, 153, 0.08);
    }
    button:disabled { opacity: .6; cursor: default; }
    .status-card {
      background: linear-gradient(180deg, rgba(255,255,255,0.94) 0%, rgba(244,248,253,0.98) 100%);
    }
    .status-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 16px;
    }
    .status { font-size: 28px; font-weight: 800; line-height: 1.05; margin: 0; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .badge-active {
      background: var(--success-soft);
      color: var(--success);
      border: 1px solid rgba(44, 139, 99, 0.14);
    }
    .badge-inactive {
      background: rgba(233, 239, 248, 0.88);
      color: #647692;
      border: 1px solid rgba(114, 137, 169, 0.14);
    }
    .badge-warn {
      background: var(--warn-soft);
      color: var(--warn);
      border: 1px solid rgba(185, 121, 44, 0.14);
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }
    .meta-item {
      padding: 14px;
      border-radius: var(--radius-md);
      border: 1px solid rgba(121, 147, 186, 0.16);
      background: rgba(255, 255, 255, 0.72);
    }
    .meta-label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 700;
    }
    .meta-value {
      margin-top: 6px;
      font-size: 15px;
      font-weight: 700;
      color: var(--text);
      word-break: break-word;
    }
    .sub-link {
      font-size: 13px;
      word-break: break-all;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.76);
      border: 1px solid rgba(106, 132, 172, 0.22);
      flex: 1;
      min-width: 0;
      color: var(--text);
    }
    .sub-row { display: flex; gap: 10px; align-items: center; margin-top: 14px; }
    .icon-btn {
      width: 42px;
      min-width: 42px;
      height: 42px;
      padding: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 17px;
    }
    .alert {
      margin-top: 12px;
      font-size: 13px;
      color: #9d4252;
      padding: 12px 14px;
      border-radius: var(--radius-md);
      background: var(--danger-soft);
      border: 1px solid rgba(191, 90, 104, 0.16);
      display: none;
    }
    .support-note {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    @media (max-width: 640px) {
      .wrap { padding-left: 12px; padding-right: 12px; }
      .hero,
      .card { padding: 16px; }
      h1 { font-size: 28px; }
      .status-top { flex-direction: column; }
      .meta-grid { grid-template-columns: 1fr; }
      .row button,
      .sub-row button { width: 100%; }
      .sub-row { flex-direction: column; align-items: stretch; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card hero">
      <div class="eyebrow">LabGuard</div>
      <h1>VPN без лишних шагов</h1>
      <div class="muted">Подключайся быстро, получай стабильный доступ и управляй подпиской в пару нажатий.</div>
      <div class="row" style="margin-top: 10px;">
        <button id="adminSwitchBtn" class="secondary" style="display:none">Перейти в админ-панель</button>
      </div>
    </div>

    <div class="card status-card">
      <div class="status-top">
        <div>
          <h2>Статус подписки</h2>
          <p class="muted">Актуальное состояние доступа, срок действия и расход трафика в одном блоке.</p>
        </div>
        <div id="statusBadge" class="badge badge-inactive">Проверяем статус</div>
      </div>
      <p id="statusText" class="status">Загружаем...</p>
      <div id="statusMeta" class="meta-grid"></div>
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
      <div class="muted">Если нужен доступ, продление или помощь с настройкой, здесь самый короткий путь к оператору.</div>
      <div class="row" style="margin-top: 10px;">
        <button id="supportLinkBtn">Открыть бота поддержки</button>
      </div>
      <div id="supportInfo" class="support-note">Раздел поддержки в приложении скоро появится.</div>
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

    function formatLocalDate(value) {
      if (!value) return '—'
      const normalized = String(value).includes('T') ? String(value) : String(value).replace(' ', 'T')
      const parsed = new Date(`${normalized}Z`)
      if (Number.isNaN(parsed.getTime())) return '—'
      return new Intl.DateTimeFormat('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(parsed)
    }

    function renderStatus(data) {
      const statusText = document.getElementById('statusText')
      const statusMeta = document.getElementById('statusMeta')
      const statusBadge = document.getElementById('statusBadge')
      const getBtn = document.getElementById('getVpnBtn')
      const refreshBtn = document.getElementById('refreshBtn')
      const trafficText = formatTraffic(data.consumed_traffic_gb)

      if (data.subscription_url) showSubscription(data.subscription_url)
      else showSubscription('')

      if (data.is_active) {
        statusText.textContent = 'VPN активен'
        statusBadge.style.display = 'inline-flex'
        statusBadge.textContent = 'Активен'
        statusBadge.className = 'badge badge-active'
        statusMeta.innerHTML = `<div class="meta-item"><div class="meta-label">Осталось</div><div class="meta-value">${data.remaining_days} дн.</div></div><div class="meta-item"><div class="meta-label">Действует до</div><div class="meta-value">${formatLocalDate(data.expires_at)}</div></div><div class="meta-item"><div class="meta-label">Расход трафика</div><div class="meta-value">${trafficText}</div></div>`
      } else if (data.trial_used) {
        statusText.textContent = 'Подписка истекла'
        statusBadge.style.display = 'none'
        statusMeta.innerHTML = `<div class="muted" style="grid-column:1/-1;">Для продления подписки можно обратиться в поддержку. Приятного пользования.</div>`
      } else {
        statusText.textContent = 'Подписка не активирована'
        statusBadge.style.display = 'none'
        statusMeta.innerHTML = `<div class="muted" style="grid-column:1/-1;">Чтобы получить подписку, нажми кнопку ниже.</div>`
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
      const error = document.getElementById('statusError')
      error.textContent = ''
      error.style.display = 'none'
      try {
        const res = await fetch(withAuth('/app/api/status'), { headers: authHeaders() })
        if (!res.ok) throw new Error('status_failed')
        const data = await res.json()
        renderStatus(data)
      } catch (e) {
        error.textContent = 'Не удалось загрузить статус. Открой приложение из Telegram.'
        error.style.display = 'block'
      }
    }

    async function getVpn() {
      const btn = document.getElementById('getVpnBtn')
      btn.disabled = true
      const error = document.getElementById('statusError')
      error.textContent = ''
      error.style.display = 'none'
      try {
        const res = await fetch(withAuth('/app/api/get-vpn'), { method: 'POST', headers: authHeaders() })
        const raw = await res.text()
        let data = {}
        try {
          data = raw ? JSON.parse(raw) : {}
        } catch (_e) {
          if (!res.ok) {
            throw new Error(raw || 'Не удалось получить VPN')
          }
          throw new Error('Некорректный ответ сервера')
        }
        if (!res.ok || data.ok === false) {
          throw new Error(data.detail || data.message || 'Не удалось получить VPN')
        }
        if (data.subscription_url) showSubscription(data.subscription_url)
        await loadStatus()
      } catch (e) {
        error.textContent = String(e.message || e)
        error.style.display = 'block'
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
      const url = `https://t.me/${username}?start=app_support`
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
        const error = document.getElementById('statusError')
        error.textContent = 'Ссылка скопирована'
        error.style.display = 'block'
      } catch (e) {
        const error = document.getElementById('statusError')
        error.textContent = latestSubscriptionUrl
        error.style.display = 'block'
      }
    })

    loadStatus()
  </script>
</body>
</html>
"""
