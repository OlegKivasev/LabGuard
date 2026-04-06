import asyncio
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
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

        local = db.get_local_metrics_snapshot()
        marzban_usage: dict[str, Any] = {}
        marzban_system: dict[str, Any] = {}
        marzban_error = ""
        try:
            marzban_usage = await marzban.get_users_usage_snapshot()
            marzban_system = await marzban.get_system_snapshot()
        except Exception as exc:
            marzban_error = str(exc)

        funnel = local["funnel"]
        connected = int(marzban_usage.get("connected_users", 0))
        get_total = int(funnel.get("get_total", 0))
        connect_rate = round((connected / get_total) * 100, 2) if get_total else 0.0

        return {
            "local": local,
            "marzban": {
                "usage": marzban_usage,
                "system": marzban_system,
                "error": marzban_error,
            },
            "kpi": {
                "start_to_get_pct": funnel.get("start_to_get_pct", 0),
                "get_to_connected_pct": connect_rate,
                "active_7d_pct": local["retention"].get("active_7d_pct", 0),
                "avg_traffic_gb": marzban_usage.get("avg_traffic_gb", 0),
                "heavy_users_5gb": marzban_usage.get("heavy_users_5gb", 0),
                "ticket_rate_pct": local["support"].get("ticket_rate_from_active_pct", 0),
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
            raise HTTPException(status_code=404, detail="User not found")

        marzban_changed = False
        for candidate in _candidate_marzban_usernames(user, telegram_id):
            if await marzban.delete_user(candidate):
                marzban_changed = True
                break

        db.delete_user(telegram_id)
        db.log_event(telegram_id, "admin_delete_webapp")
        return {"ok": True, "marzban_changed": marzban_changed}

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
      <button id="refreshBtn">Обновить</button>
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
              <tr><th>Telegram ID</th><th>Username</th><th>Срок триала</th><th>Дата регистрации</th><th>Действия</th></tr>
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
          tr.innerHTML = `<td>${u.telegram_id}</td><td>${u.username || '-'}</td><td>${u.expires_at || '-'}</td><td>${u.created_at || '-'}</td><td><div class="actions"><button data-action="deactivate" data-id="${u.telegram_id}">Деактивировать</button><button class="red" data-action="delete" data-id="${u.telegram_id}">Удалить</button></div></td>`
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

    refreshAll()
  </script>
</body>
</html>
"""
