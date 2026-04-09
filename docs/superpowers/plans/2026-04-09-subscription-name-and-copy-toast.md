# Subscription Name And Copy Toast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Исправить показ старого имени подписки из БД и заменить встроенное сообщение копирования на toast-уведомление.

**Architecture:** Нормализовать `subscription_url` как при создании, так и при чтении из БД, чтобы старые сохраненные fragment тоже переписывались в `🇫🇮 Финляндия`. Для UI добавить отдельный toast-слой и использовать его для результата копирования вместо `statusError`.

**Tech Stack:** Python, FastAPI, JavaScript, unittest, py_compile.

---

## File Structure

- Modify: `webapp.py` — нормализация сохраненной ссылки при чтении и frontend toast.
- Modify: `tests/test_support_flow.py` — тесты на нормализацию сохраненного `subscription_url`.

### Task 1: Нормализовать старые subscription_url при чтении

**Files:**
- Modify: `webapp.py`
- Modify: `tests/test_support_flow.py`

- [ ] **Step 1: Add a failing test for stored Marzban-style subscription URL**
- [ ] **Step 2: Normalize stored `subscription_url` in status/get-vpn routes and save back when changed**
- [ ] **Step 3: Re-run lightweight verification**

### Task 2: Заменить встроенное сообщение копирования на toast

**Files:**
- Modify: `webapp.py`

- [ ] **Step 1: Add toast markup/styles/helpers in Mini App HTML**
- [ ] **Step 2: Switch copy button handler from `statusError` to `showToast(...)`**
- [ ] **Step 3: Re-run lightweight verification**

### Task 3: Проверить и запушить ветку

**Files:**
- Modify: `webapp.py`
- Modify: `tests/test_support_flow.py`

- [ ] **Step 1: Run `python -m py_compile webapp.py tests/test_support_flow.py`**
- [ ] **Step 2: Commit and push `fix/subscription-name-and-copy-toast`**
