import asyncio

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import uvicorn

from config import Settings
from database import Database
from miniapp_auth import verify_admin_token
from marzban import MarzbanClient


def _verify_admin(settings: Settings, token: str) -> int:
    admin_id = verify_admin_token(settings.bot_token, token)
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if settings.admin_telegram_ids and admin_id not in settings.admin_telegram_ids:
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
    async def admin_app_page(token: str = Query("")) -> HTMLResponse:
        _verify_admin(settings, token)
        return HTMLResponse(_ADMIN_APP_HTML)

    @app.get("/admin-app/api/overview")
    async def admin_overview(token: str = Query("")) -> dict:
        _verify_admin(settings, token)
        return db.get_admin_overview()

    @app.get("/admin-app/api/users")
    async def admin_users(
        token: str = Query(""),
        limit: int = Query(30, ge=1, le=100),
        q: str = Query(""),
    ) -> dict:
        _verify_admin(settings, token)
        users = db.search_users(query=q, limit=limit)
        return {"users": users}

    @app.post("/admin-app/api/user/{telegram_id}/deactivate")
    async def admin_deactivate(telegram_id: int, token: str = Query("")) -> dict:
        _verify_admin(settings, token)

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
    async def admin_delete(telegram_id: int, token: str = Query("")) -> dict:
        _verify_admin(settings, token)

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
  <style>
    :root { color-scheme: dark; }
    body { font-family: -apple-system, Segoe UI, sans-serif; margin: 0; background: #0f1420; color: #e7eefc; }
    .wrap { max-width: 960px; margin: 0 auto; padding: 16px; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; margin-bottom: 16px; }
    .card { background: #1b2334; border: 1px solid #2a3550; border-radius: 12px; padding: 12px; }
    .k { font-size: 12px; opacity: .75; }
    .v { font-size: 24px; font-weight: 700; margin-top: 6px; }
    .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 8px; }
    button { background: #2f6df6; color: #fff; border: 0; border-radius: 10px; padding: 8px 12px; cursor: pointer; }
    button.red { background: #d94c4c; }
    .search { display: flex; gap: 8px; margin-bottom: 12px; }
    input { flex: 1; background: #121a29; color: #e7eefc; border: 1px solid #2a3550; border-radius: 10px; padding: 8px 10px; }
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
    <div class="search">
      <input id="searchInput" placeholder="Поиск: Telegram ID или username" />
      <button id="searchBtn">Найти</button>
    </div>
    <div class="grid" id="metrics"></div>
    <div class="card">
      <div class="head"><h3 style="margin:0">Пользователи</h3></div>
      <table>
        <thead>
          <tr><th>Telegram ID</th><th>Username</th><th>Срок триала</th><th>Дата регистрации</th><th>Действия</th></tr>
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

    async function loadUsers(search) {
      const q = search ? `&q=${encodeURIComponent(search)}` : ''
      const res = await fetch(`/admin-app/api/users?limit=50&token=${encodeURIComponent(token)}${q}`)
      if (!res.ok) throw new Error('users failed')
      return res.json()
    }

    async function deactivateUser(telegramId) {
      const res = await fetch(`/admin-app/api/user/${telegramId}/deactivate?token=${encodeURIComponent(token)}`, { method: 'POST' })
      if (!res.ok) throw new Error('deactivate failed')
      return res.json()
    }

    async function deleteUser(telegramId) {
      const res = await fetch(`/admin-app/api/user/${telegramId}?token=${encodeURIComponent(token)}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('delete failed')
      return res.json()
    }

    function metricCard(title, value) {
      return `<div class="card"><div class="k">${title}</div><div class="v">${value}</div></div>`
    }

    async function refresh() {
      try {
        const searchText = document.getElementById('searchInput').value.trim()
        const [overview, usersPayload] = await Promise.all([loadOverview(), loadUsers(searchText)])
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
          tr.innerHTML = `<td>${u.telegram_id}</td><td>${u.username || '-'}</td><td>${u.expires_at || '-'}</td><td>${u.created_at || '-'}</td><td><button data-action="deactivate" data-id="${u.telegram_id}">Деактивировать</button> <button class="red" data-action="delete" data-id="${u.telegram_id}">Удалить</button></td>`
          body.appendChild(tr)
        }
        document.getElementById('hint').textContent = `Показано ${usersPayload.users.length} пользователей`
      } catch (e) {
        document.getElementById('hint').textContent = 'Ошибка загрузки данных'
      }
    }

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
        await refresh()
      } catch (e) {
        document.getElementById('hint').textContent = 'Ошибка выполнения действия'
      }
    })

    document.getElementById('refreshBtn').addEventListener('click', refresh)
    document.getElementById('searchBtn').addEventListener('click', refresh)
    document.getElementById('searchInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        refresh()
      }
    })
    refresh()
  </script>
</body>
</html>
"""
