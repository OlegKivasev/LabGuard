# 3XUI Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить Marzban-интеграцию на 3X-UI API для выдачи подписки, статуса пользователя и admin-операций.

**Architecture:** Ввести новый `XUIClient` и новые env-переменные, затем поэтапно перевести выдачу, Mini App и admin-операции на 3X-UI при сохранении текущего пользовательского UX. На первом этапе система работает с одним inbound, но интерфейсы клиента панели делаются нейтральными для будущего мультисерверного расширения.

**Tech Stack:** Python, FastAPI, aiogram, httpx, SQLite, unittest.

---

## File Structure

- Create: `xui.py` — клиент 3X-UI API.
- Modify: `config.py` — новые `XUI_*` настройки.
- Modify: `database.py` — новое поле `panel_client_id`.
- Modify: `bot.py` — wiring нового клиента вместо Marzban.
- Modify: `handlers/get_vpn.py` — выдача trial через 3X-UI.
- Modify: `webapp.py` — status/get-vpn/admin operations через 3X-UI.
- Modify: `tests/test_support_flow.py` — stub-клиент и Mini App сценарии.

### Task 1: Добавить конфиг и клиент 3X-UI
- [ ] Создать `xui.py` с базовыми методами login/get_inbound/create_client/get_client/update_client/delete_client.
- [ ] Добавить `XUI_*` настройки в `config.py`.
- [ ] Подготовить нейтральные helper-имена для `panel_client_id`, subscription name `LabGuard` и server name `Финляндия`.

### Task 2: Перевести пользовательскую выдачу VPN
- [ ] Заменить в `handlers/get_vpn.py` использование `MarzbanClient` на `XUIClient`.
- [ ] Создавать клиента в одном inbound по `XUI_INBOUND_ID`.
- [ ] Формировать и сохранять subscription link.

### Task 3: Перевести Mini App status/get-vpn
- [ ] Обновить `webapp.py` для получения пользователя и подписки из 3X-UI.
- [ ] Обеспечить сохранение `subscription_url` и `panel_client_id`.
- [ ] Сохранить имена `LabGuard` и `Финляндия`.

### Task 4: Перевести admin-операции и метрики
- [ ] deactivate/delete/update trial через 3X-UI.
- [ ] metric snapshot / online / traffic через 3X-UI, где возможно.

### Task 5: Выпилить Marzban runtime-зависимости
- [ ] Убрать runtime-использование `marzban.py` в рабочих путях.
- [ ] Обновить проверки и зависимости в `bot.py`.
- [ ] Оставить только те места, которые нужны для безопасного перехода, если такие останутся.
