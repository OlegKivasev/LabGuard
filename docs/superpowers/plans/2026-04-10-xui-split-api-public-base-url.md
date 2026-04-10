# XUI Split API/Public Base URL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разделить API base URL и public subscription base URL для 3X-UI, чтобы бот логинился локально, а пользователям отдавал внешние рабочие ссылки подписки.

**Architecture:** `XUIClient` будет хранить отдельный API base URL для `/login` и `/panel/api/*` и отдельный public base URL для построения subscription URL. Конфиг останется обратно совместимым: `XUI_PUBLIC_BASE_URL` optional и fallback-ится в `XUI_BASE_URL`.

**Tech Stack:** Python, dataclasses, httpx, unittest, environment-based config.

---

### Task 1: Добавить конфиг public base URL

**Files:**
- Modify: `config.py`
- Modify: `.env.example`

- [ ] Добавить поле `xui_public_base_url` в `Settings`
- [ ] Читать `XUI_PUBLIC_BASE_URL` из окружения
- [ ] Обновить `.env.example` новой переменной

### Task 2: Разделить URL в XUI client

**Files:**
- Modify: `xui.py`

- [ ] Обновить `XUIClient.__init__` так, чтобы он принимал `public_base_url`
- [ ] Оставить API-запросы на `base_url`
- [ ] Строить `subscription_url` от `public_base_url`
- [ ] Добавить fallback `public_base_url = base_url`, если значение пустое

### Task 3: Использовать public base URL при нормализации подписок

**Files:**
- Modify: `handlers/get_vpn.py`
- Modify: `webapp.py`

- [ ] Переключить нормализацию subscription URL на public base URL клиента

### Task 4: Обновить тесты

**Files:**
- Modify: `tests/test_support_flow.py`

- [ ] Добавить/обновить тест на сценарий с разными API/public base URL

### Task 5: Проверить реализацию

**Files:**
- Verify: `tests/test_support_flow.py`

- [ ] Запустить точечные тесты
- [ ] Запустить полный релевантный тестовый набор
