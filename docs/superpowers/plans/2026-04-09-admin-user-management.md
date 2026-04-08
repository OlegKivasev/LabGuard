# Admin User Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified admin user management flow with searchable user list, dedicated user detail screen, editable trial expiry, and Telegram notification after admin changes the trial date.

**Architecture:** Extend the existing FastAPI admin endpoints in `webapp.py`, add focused SQLite helpers in `database.py`, and keep Marzban-specific lookups in `marzban.py`. Reuse the current embedded admin HTML but reshape the users tab into a card-based master/detail flow that matches the metrics tab styling.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, SQLite, embedded HTML/CSS/JS, standard library `unittest`

---

## File Structure

- Modify: `database.py` - user search payload, trial activity helpers, user detail helper
- Modify: `marzban.py` - focused helper to resolve per-user online status
- Modify: `webapp.py` - new payload model, user detail endpoint, trial update flow, Telegram notification, admin HTML/JS redesign for users tab
- Create: `tests/test_admin_user_management.py` - regression tests for DB helpers and admin API behavior
- Modify: `docs/superpowers/specs/2026-04-08-admin-user-management-design.md` only if implementation uncovers a required clarification

### Task 1: Add failing backend tests for admin user management

**Files:**
- Create: `tests/test_admin_user_management.py`
- Modify: `webapp.py`
- Modify: `database.py`

- [ ] **Step 1: Write the failing test file**

```python
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from database import Database
from webapp import build_app


class StubSettings:
    bot_token = "test-token"
    admin_telegram_ids = set()
    admin_telegram_usernames = set()


class StubMarzban:
    async def get_user(self, username):
        return None

    async def update_user_trial(self, username, expire_at, active=True):
        return False

    async def create_user(self, username, expire_at):
        return {"username": username}

    async def disable_user(self, username):
        return False

    async def delete_user(self, username):
        return False


class AdminUserManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test.sqlite3")
        self.db = Database(self.db_path)
        self.db.init_schema()
        self.db.create_user_if_not_exists(telegram_id=1001, username="AlphaUser")
        self.db.set_user_expiry(1001, "2099-01-01 00:00:00")
        app = build_app(self.db, StubSettings(), StubMarzban())
        self.client = TestClient(app)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_search_users_returns_trial_activity_flag(self):
        users = self.db.search_users("alpha", limit=10)
        self.assertTrue(users[0]["trial_active"])

    def test_user_detail_endpoint_returns_profile_payload(self):
        response = self.client.get("/admin-app/api/user/1001?token=test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["telegram_id"], 1001)

    def test_trial_update_endpoint_accepts_absolute_expiry(self):
        response = self.client.post(
            "/admin-app/api/user/1001/trial?token=test",
            json={"expires_at": "2099-01-05T12:30", "no_trial_limits": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["expires_at"], "2099-01-05 12:30:00")
```

- [ ] **Step 2: Run test file to verify it fails**

Run: `python -m unittest tests.test_admin_user_management -v`
Expected: FAIL because `search_users` does not return `trial_active`, detail endpoint is missing, and trial endpoint still expects `days/unlimited`

- [ ] **Step 3: Add minimal app auth stub support if tokenless tests fail for auth reasons**

```python
from unittest.mock import patch

with patch("webapp.verify_admin_token", return_value=1):
    app = build_app(self.db, StubSettings(), StubMarzban())
```

- [ ] **Step 4: Run the test file again until failures reflect missing feature behavior only**

Run: `python -m unittest tests.test_admin_user_management -v`
Expected: FAIL only on missing user-management behavior

- [ ] **Step 5: Commit the red test scaffold**

```bash
git add tests/test_admin_user_management.py
git commit -m "test: add failing admin user management coverage"
```

### Task 2: Implement database and Marzban support for list/detail state

**Files:**
- Modify: `database.py`
- Modify: `marzban.py`
- Test: `tests/test_admin_user_management.py`

- [ ] **Step 1: Update `search_users()` to include `trial_active`**

```python
SELECT
    telegram_id,
    username,
    marzban_id,
    expires_at,
    created_at,
    no_trial_limits,
    CASE
        WHEN expires_at IS NOT NULL AND datetime(expires_at) > datetime('now') THEN 1
        ELSE 0
    END AS trial_active
FROM users
```

- [ ] **Step 2: Add focused DB helper for user detail payload**

```python
def get_admin_user_detail(self, telegram_id: int) -> dict[str, Any] | None:
    with self.connect() as conn:
        row = conn.execute(
            """
            SELECT
                telegram_id,
                username,
                marzban_id,
                created_at,
                expires_at,
                no_trial_limits,
                CASE
                    WHEN expires_at IS NOT NULL AND datetime(expires_at) > datetime('now') THEN 1
                    ELSE 0
                END AS trial_active
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["trial_used"] = self.has_received_trial(telegram_id)
        return payload
```

- [ ] **Step 3: Add Marzban helper to resolve per-user online status with fallback**

```python
async def get_user_online_status(self, username: str) -> dict[str, Any]:
    user = await self.get_user(username)
    if user is None:
        return {"online_now": None, "online_status": "unknown"}

    online_now = bool(user.get("online_at") or user.get("online") or user.get("status") == "on_hold")
    return {
        "online_now": online_now,
        "online_status": "online" if online_now else "offline",
    }
```

- [ ] **Step 4: Run the targeted tests**

Run: `python -m unittest tests.test_admin_user_management.AdminUserManagementTests.test_search_users_returns_trial_activity_flag tests.test_admin_user_management.AdminUserManagementTests.test_user_detail_endpoint_returns_profile_payload -v`
Expected: first test still FAIL until API is wired, DB assertions pass once helper exists

- [ ] **Step 5: Commit backend data helpers**

```bash
git add database.py marzban.py tests/test_admin_user_management.py
git commit -m "feat: add admin user detail data helpers"
```

### Task 3: Implement admin API for user detail and absolute expiry updates

**Files:**
- Modify: `webapp.py`
- Modify: `database.py`
- Modify: `marzban.py`
- Test: `tests/test_admin_user_management.py`

- [ ] **Step 1: Replace trial payload model with absolute datetime input**

```python
class AdminTrialPayload(BaseModel):
    expires_at: str
    no_trial_limits: bool = False
```

- [ ] **Step 2: Add helper to normalize admin datetime input**

```python
def _parse_admin_datetime_local(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    return parsed.replace(tzinfo=timezone.utc)
```

- [ ] **Step 3: Add user detail endpoint**

```python
@app.get("/admin-app/api/user/{telegram_id}")
async def admin_user_detail(...):
    _verify_admin(settings, token, x_tg_init_data or init_data)
    user = db.get_admin_user_detail(telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    online = await _resolve_user_online_state(user)
    return {"user": {**user, **online}}
```

- [ ] **Step 4: Update trial endpoint to save explicit expiry and send notification**

```python
target_dt = _parse_admin_datetime_local(payload.expires_at)
local_expires = target_dt.strftime("%Y-%m-%d %H:%M:%S")
db.set_user_expiry(telegram_id, local_expires)
db.mark_trial_used(telegram_id)
notification_sent = await _notify_trial_changed(telegram_id, local_expires)
return {
    "ok": True,
    "expires_at": local_expires,
    "trial_active": True,
    "notification_sent": notification_sent,
    "marzban_changed": marzban_changed,
}
```

- [ ] **Step 5: Run the test file to verify green**

Run: `python -m unittest tests.test_admin_user_management -v`
Expected: PASS

- [ ] **Step 6: Commit API behavior**

```bash
git add webapp.py database.py marzban.py tests/test_admin_user_management.py
git commit -m "feat: add admin user detail and expiry controls"
```

### Task 4: Redesign users tab into unified master/detail UI

**Files:**
- Modify: `webapp.py`
- Test: `tests/test_admin_user_management.py`

- [ ] **Step 1: Add failing HTML assertions for the new UI shell**

```python
def test_admin_html_contains_user_detail_shell(self):
    from webapp import _ADMIN_APP_HTML
    self.assertIn("userDetailSection", _ADMIN_APP_HTML)
    self.assertIn("Изменить дату подписки", _ADMIN_APP_HTML)
```

- [ ] **Step 2: Run the focused HTML test to verify red**

Run: `python -m unittest tests.test_admin_user_management.AdminUserManagementTests.test_admin_html_contains_user_detail_shell -v`
Expected: FAIL

- [ ] **Step 3: Replace users table interactions with master/detail cards**

```javascript
const state = { selectedUserId: null, users: [], currentUser: null }

function renderUsersList(users) { /* clickable rows with status badge */ }
function renderUserDetail(user) { /* profile card + details card + actions card */ }
function toggleTrialEditor(user) { /* datetime-local form with disabled save until changed */ }
```

- [ ] **Step 4: Run the full test file again**

Run: `python -m unittest tests.test_admin_user_management -v`
Expected: PASS

- [ ] **Step 5: Commit the UI redesign**

```bash
git add webapp.py tests/test_admin_user_management.py
git commit -m "feat: redesign admin users tab into detail workflow"
```

### Task 5: Minimal end-to-end verification and integration

**Files:**
- Modify: `webapp.py`
- Modify: `tests/test_admin_user_management.py`

- [ ] **Step 1: Add one regression test for notification result in API response**

```python
def test_trial_update_reports_notification_status(self):
    response = self.client.post(
        "/admin-app/api/user/1001/trial?token=test",
        json={"expires_at": "2099-01-05T12:30", "no_trial_limits": False},
    )
    self.assertIn("notification_sent", response.json())
```

- [ ] **Step 2: Run the complete suite**

Run: `python -m unittest tests.test_admin_user_management -v`
Expected: PASS with 0 failures

- [ ] **Step 3: Run lightweight syntax verification on modified modules**

Run: `python -m compileall webapp.py database.py marzban.py tests/test_admin_user_management.py`
Expected: all files compile successfully

- [ ] **Step 4: Commit the finished feature branch state**

```bash
git add webapp.py database.py marzban.py tests/test_admin_user_management.py docs/superpowers/plans/2026-04-09-admin-user-management.md docs/superpowers/specs/2026-04-08-admin-user-management-design.md
git commit -m "feat: add admin user management workflow"
```
