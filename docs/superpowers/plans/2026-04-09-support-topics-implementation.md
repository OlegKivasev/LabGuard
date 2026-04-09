# Support Topics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести поддержку из одного админского чата в Telegram Topics, где каждый пользователь получает отдельную тему.

**Architecture:** Support-бот больше не шлет каждое обращение как отдельное сообщение в личку админу. Вместо этого бот работает через одну приватную супергруппу поддержки, создает или переиспользует topic на пользователя и пишет все сообщения пользователя в этот topic. Ответ админа из topic маршрутизируется обратно пользователю через существующий mapping тикетов.

**Tech Stack:** Python, aiogram, Telegram Bot API, SQLite.

---

## File Structure

- Modify: `config.py` — добавить `SUPPORT_FORUM_CHAT_ID`.
- Modify: `database.py` — хранить `support_thread_id` для пользователя/тикета.
- Modify: `handlers/support_bot.py` — отправка в forum topic, reply из topic обратно пользователю.
- Modify: `tests/test_support_flow.py` — минимальные тесты на topic-маршрутизацию.

### Task 1: Добавить конфиг и storage для topic id

### Task 2: Перевести отправку новых обращений в отдельные Telegram Topics

### Task 3: Маршрутизировать ответы админа из конкретной темы обратно пользователю

### Task 4: Прогнать минимальные тесты и запушить
