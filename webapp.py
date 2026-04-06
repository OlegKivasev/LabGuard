import asyncio

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import uvicorn

from config import Settings
from database import Database
from miniapp_auth import verify_admin_token


def _verify_admin(settings: Settings, token: str) -> int:
    admin_id = verify_admin_token(settings.bot_token, token)
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if settings.admin_telegram_ids and admin_id not in settings.admin_telegram_ids:
        raise HTTPException(status_code=403, detail="Forbidden")

    return admin_id


def build_app(db: Database, settings: Settings) -> FastAPI:
    app = FastAPI(title="VPN Admin Mini App", docs_url=None, redoc_url=None)

    @app.get("/admin-app", response_class=HTMLResponse)
    async def admin_app_page(token: str = Query("")) -> HTMLResponse:
        _verify_admin(settings, token)
        return HTMLResponse(_ADMIN_APP_HTML)

    @app.get("/admin-app/api/overview")
    async def admin_overview(token: str = Query("")) -> dict:
        _verify_admin(settings, token)
        return db.get_admin_overview()

    @app.get("/admin-app/api/users")
    async def admin_users(token: str = Query(""), limit: int = Query(20, ge=1, le=100)) -> dict:
        _verify_admin(settings, token)
        return {"users": db.list_recent_users(limit=limit)}

    return app


async def start_web_app_server(db: Database, settings: Settings) -> tuple[uvicorn.Server, asyncio.Task]:
    app = build_app(db, settings)
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
  <style>
    :root { color-scheme: dark; }
    body { font-family: -apple-system, Segoe UI, sans-serif; margin: 0; background: #0f1420; color: #e7eefc; }
    .wrap { max-width: 960px; margin: 0 auto; padding: 16px; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; margin-bottom: 16px; }
    .card { background: #1b2334; border: 1px solid #2a3550; border-radius: 12px; padding: 12px; }
    .k { font-size: 12px; opacity: .75; }
    .v { font-size: 24px; font-weight: 700; margin-top: 6px; }
    .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
    button { background: #2f6df6; color: #fff; border: 0; border-radius: 10px; padding: 8px 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 8px; border-bottom: 1px solid #2a3550; text-align: left; }
    th { opacity: .75; font-weight: 500; }
    .muted { opacity: .7; }
    @media (max-width: 800px) { .grid { grid-template-columns: 1fr 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h2 style="margin:0">LabGuard Admin</h2>
      <button id="refreshBtn">Обновить</button>
    </div>
    <div class="grid" id="metrics"></div>
    <div class="card">
      <div class="head"><h3 style="margin:0">Пользователи</h3></div>
      <table>
        <thead>
          <tr><th>Telegram ID</th><th>Username</th><th>Marzban</th><th>Expires</th></tr>
        </thead>
        <tbody id="usersBody"></tbody>
      </table>
      <div class="muted" id="hint" style="margin-top:10px"></div>
    </div>
  </div>

  <script>
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token') || ''

    async function loadOverview() {
      const res = await fetch(`/admin-app/api/overview?token=${encodeURIComponent(token)}`)
      if (!res.ok) throw new Error('overview failed')
      return res.json()
    }

    async function loadUsers() {
      const res = await fetch(`/admin-app/api/users?limit=30&token=${encodeURIComponent(token)}`)
      if (!res.ok) throw new Error('users failed')
      return res.json()
    }

    function metricCard(title, value) {
      return `<div class="card"><div class="k">${title}</div><div class="v">${value}</div></div>`
    }

    async function refresh() {
      try {
        const [overview, usersPayload] = await Promise.all([loadOverview(), loadUsers()])
        const metrics = document.getElementById('metrics')
        metrics.innerHTML = [
          metricCard('Всего пользователей', overview.total_users),
          metricCard('Активных триалов', overview.active_trials),
          metricCard('Новых сегодня', overview.new_today),
          metricCard('/start сегодня', overview.start_today),
          metricCard('/get сегодня', overview.get_today),
          metricCard('Открытых тикетов', overview.open_tickets),
        ].join('')

        const body = document.getElementById('usersBody')
        body.innerHTML = ''
        for (const u of usersPayload.users) {
          const tr = document.createElement('tr')
          tr.innerHTML = `<td>${u.telegram_id}</td><td>${u.username || '-'}</td><td>${u.marzban_id || '-'}</td><td>${u.expires_at || '-'}</td>`
          body.appendChild(tr)
        }
        document.getElementById('hint').textContent = `Показано ${usersPayload.users.length} последних пользователей`
      } catch (e) {
        document.getElementById('hint').textContent = 'Ошибка загрузки данных'
      }
    }

    document.getElementById('refreshBtn').addEventListener('click', refresh)
    refresh()
  </script>
</body>
</html>
"""
