# Admin Metrics Redesign Design

## Goal

Completely redesign the admin metrics experience so it shows only the required business metrics in a clean, pleasant interface and nothing extra.

## Final Metrics Scope

The admin metrics tab must show exactly 6 metrics:

1. Users who opened bot and pressed start
2. Users who received VPN link
3. Users who connected VPN and consumed first traffic
4. Users online now
5. Users with active trial now
6. Users with expired trial

Metric "new users per day by first traffic" is explicitly excluded.

## Data Definitions

### 1) Start users

- Source: `events`
- Formula: `COUNT(DISTINCT telegram_id)` where `event = 'start'`

### 2) Received VPN link

- Source: `events`
- Formula: `COUNT(DISTINCT telegram_id)` where `event IN ('app_get', 'app_get_existing')`
- Meaning: user received a fresh trial or received an already-active VPN link in app flow.

### 3) Connected and consumed traffic

- Source: Marzban usage snapshot
- Field: `connected_users`
- Meaning: users with `used_traffic > 0`

### 4) Online now

- Source: Marzban system snapshot
- Field: `online_users`

### 5) Active trial now

- Source: `users`
- Formula: `COUNT(*)` where `expires_at IS NOT NULL` and `datetime(expires_at) > datetime('now')`

### 6) Expired trial

- Source: `users`
- Formula: `COUNT(*)` where `expires_at IS NOT NULL` and `datetime(expires_at) <= datetime('now')`

## API Design

Endpoint: `GET /admin-app/api/metrics`

Response shape:

```json
{
  "metrics": {
    "start_users": 0,
    "vpn_link_users": 0,
    "connected_users": 0,
    "online_now": 0,
    "active_trials": 0,
    "expired_trials": 0
  },
  "meta": {
    "generated_at": "2026-04-08T12:00:00Z",
    "marzban_error": ""
  }
}
```

Rules:

- Keep auth behavior unchanged.
- Remove old `kpi/local/marzban` response structure from frontend usage.
- If Marzban call fails, `connected_users` and `online_now` return `null` in backend and render as `—` in UI.
- `meta.marzban_error` contains concise technical message for non-blocking warning.

## UI/UX Design

Target: Full redesign of the `Метрика` tab only. `Пользователи` tab remains functionally unchanged.

### Visual direction

- Light theme with soft gradient background.
- Strong readability and calm color accents.
- Card-first layout with expressive values and concise labels.
- No charts, no extra analytic sections, no infrastructure/support KPI blocks.

### Layout

- Header row: title + last updated timestamp + refresh button.
- Metrics grid:
  - desktop: 3 columns x 2 rows
  - tablet: 2 columns
  - mobile: 1 column

### Card content

Each card contains:

- metric title
- big numeric value (or `—`)
- short helper caption

### Error handling in UI

- If `meta.marzban_error` is non-empty, show compact warning banner below header.
- UI does not break or hide local metrics when Marzban is unavailable.

## Backend Responsibilities

- Add focused DB helper for local admin metrics aggregation in `database.py`.
- Keep SQL simple and deterministic.
- Keep Marzban retrieval in `webapp.py`, but map data strictly into new response shape.
- Avoid touching unrelated routes.

## Frontend Responsibilities

- Replace current metrics rendering logic with one renderer for 6 cards.
- Remove code paths related to old blocks: funnel/retention/engagement/quality/infra.
- Keep tab switching and users tab interactions unchanged.

## Compatibility And Risk Notes

- Existing admin endpoint path remains unchanged (`/admin-app/api/metrics`).
- Existing auth token/init_data contract remains unchanged.
- Main risk is accidental dependency on removed response keys in current JS; redesign must remove those references fully.

## Testing Strategy

- API returns 6 metrics with expected keys.
- Page loads and renders all 6 cards.
- Mobile layout shows single-column stack.
- Marzban failure simulation still shows local metrics and warning banner.
- Manual admin flow verifies refresh works and users tab remains operational.

## Out Of Scope

- Daily new users by first traffic.
- Historical charts and trend analytics.
- Additional admin KPIs not listed in final scope.
