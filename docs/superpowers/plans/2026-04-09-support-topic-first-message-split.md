# Support Topic First Message Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Изменить формат отправки сообщений в support topic так, чтобы новая или восстановленная тема начиналась отдельной шапкой, а первое пользовательское сообщение и все последующие сообщения шли отдельным обычным текстом.

**Architecture:** Сохранить текущую схему topic-маршрутизации и уже добавленное восстановление удаленной темы, но разделить отправку на два режима: `header + text` для новой темы и `text only` для существующей. Логику сосредоточить в `handlers/support_bot.py`, а минимальные регрессионные проверки держать в `tests/test_support_flow.py` и `tests/test_support_topic_recovery.py`.

**Tech Stack:** Python, aiogram, unittest, Telegram Bot API.

---

## File Structure

- Modify: `handlers/support_bot.py` — отделить служебную шапку от текста первого обращения и повторно использовать этот режим при восстановлении темы.
- Modify: `tests/test_support_flow.py` — обновить поведение для новой и существующей темы.
- Modify: `tests/test_support_topic_recovery.py` — обновить сценарий восстановления удаленной темы под новый формат из двух сообщений.

### Task 1: Сделать новую тему двухсообщной

**Files:**
- Modify: `handlers/support_bot.py`
- Test: `tests/test_support_flow.py`

- [ ] **Step 1: Write the failing test for a newly created topic sending header and text separately**

```python
async def test_forward_user_message_to_admin_creates_topic_and_sends_header_then_text(self) -> None:
    from handlers.support_bot import forward_user_message_to_admin

    db = Mock()
    db.create_ticket.return_value = 17
    db.get_support_topic_by_telegram_id.return_value = None
    db.set_support_topic.return_value = None

    bot = AsyncMock()
    bot.create_forum_topic.return_value = type("Topic", (), {"message_thread_id": 321})()
    settings = type("S", (), {"support_forum_chat_id": -100555})()

    await forward_user_message_to_admin(
        bot=bot,
        db=db,
        settings=settings,
        telegram_id=123456789,
        username="demo_user",
        text="Не работает VPN",
    )

    self.assertEqual(bot.send_message.await_count, 2)
    first_call = bot.send_message.await_args_list[0].kwargs
    second_call = bot.send_message.await_args_list[1].kwargs

    self.assertEqual(first_call["text"], "Пользователь: @demo_user\nTelegram ID: 123456789")
    self.assertEqual(second_call["text"], "Не работает VPN")
    self.assertEqual(first_call["message_thread_id"], 321)
    self.assertEqual(second_call["message_thread_id"], 321)
```

- [ ] **Step 2: Run the focused test and confirm it fails on the current single-message payload**

Run: `python -m unittest tests.test_support_flow.SupportBotFlowTests.test_forward_user_message_to_admin_creates_topic_and_sends_header_then_text`
Expected: FAIL because the handler still sends one combined message for a new topic.

- [ ] **Step 3: Implement separate helpers for header and text sending in new topics**

```python
async def _send_support_topic_header(bot, forum_chat_id: int, message_thread_id: int, username_text: str, telegram_id: int) -> None:
    await bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=message_thread_id,
        text=f"Пользователь: {username_text}\nTelegram ID: {telegram_id}",
    )


async def _send_support_user_text(bot, forum_chat_id: int, message_thread_id: int, text: str) -> None:
    await bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=message_thread_id,
        text=text,
    )


async def forward_user_message_to_admin(...):
    ...
    is_new_topic = topic is None
    if is_new_topic:
        message_thread_id = await _create_support_topic(...)
    else:
        message_thread_id = int(topic["message_thread_id"])

    try:
        if is_new_topic:
            await _send_support_topic_header(...)
        await _send_support_user_text(...)
    except TelegramBadRequest:
        ...
```
```

- [ ] **Step 4: Re-run the focused test and confirm it passes**

Run: `python -m unittest tests.test_support_flow.SupportBotFlowTests.test_forward_user_message_to_admin_creates_topic_and_sends_header_then_text`
Expected: PASS.

- [ ] **Step 5: Commit the new-topic formatting change**

```bash
git add handlers/support_bot.py tests/test_support_flow.py
git commit -m "fix: split first support topic message"
```

### Task 2: Оставить существующую тему обычным диалогом

**Files:**
- Modify: `tests/test_support_flow.py`
- Modify: `handlers/support_bot.py`

- [ ] **Step 1: Write the failing test for existing topics sending only plain text**

```python
async def test_forward_user_message_to_admin_reuses_existing_topic_and_sends_plain_text_only(self) -> None:
    from handlers.support_bot import forward_user_message_to_admin

    db = Mock()
    db.create_ticket.return_value = 21
    db.get_support_topic_by_telegram_id.return_value = {
        "forum_chat_id": -100555,
        "message_thread_id": 654,
        "telegram_id": 123456789,
    }

    bot = AsyncMock()
    settings = type("S", (), {"support_forum_chat_id": -100555})()

    await forward_user_message_to_admin(
        bot=bot,
        db=db,
        settings=settings,
        telegram_id=123456789,
        username="demo_user",
        text="вцйвйцвцйв",
    )

    bot.create_forum_topic.assert_not_called()
    bot.send_message.assert_awaited_once_with(
        chat_id=-100555,
        message_thread_id=654,
        text="вцйвйцвцйв",
    )
```

- [ ] **Step 2: Run the focused test and confirm it fails if the handler still prepends header text**

Run: `python -m unittest tests.test_support_flow.SupportBotFlowTests.test_forward_user_message_to_admin_reuses_existing_topic_and_sends_plain_text_only`
Expected: FAIL until the handler distinguishes existing topics from new ones.

- [ ] **Step 3: Keep header sending only for new or recreated topics**

```python
async def forward_user_message_to_admin(...):
    ...
    is_new_topic = topic is None

    try:
        if is_new_topic:
            await _send_support_topic_header(
                bot=bot,
                forum_chat_id=forum_chat_id,
                message_thread_id=message_thread_id,
                username_text=username_text,
                telegram_id=telegram_id,
            )
        await _send_support_user_text(
            bot=bot,
            forum_chat_id=forum_chat_id,
            message_thread_id=message_thread_id,
            text=text,
        )
    except TelegramBadRequest:
        ...
```

- [ ] **Step 4: Re-run the focused test and confirm it passes**

Run: `python -m unittest tests.test_support_flow.SupportBotFlowTests.test_forward_user_message_to_admin_reuses_existing_topic_and_sends_plain_text_only`
Expected: PASS.

- [ ] **Step 5: Commit the existing-topic plain-text behavior**

```bash
git add handlers/support_bot.py tests/test_support_flow.py
git commit -m "fix: keep follow-up support messages plain"
```

### Task 3: Повторить формат `header + text` при восстановлении удаленной темы

**Files:**
- Modify: `tests/test_support_topic_recovery.py`
- Modify: `handlers/support_bot.py`

- [ ] **Step 1: Update the failing recovery test to expect three send attempts: failed plain send, then header, then text**

```python
async def test_recreates_topic_when_stored_thread_was_deleted(self) -> None:
    _install_fake_aiogram()
    _install_fake_dotenv()

    from aiogram.exceptions import TelegramBadRequest

    ...

    bot.send_message.side_effect = [
        TelegramBadRequest("thread not found"),
        None,
        None,
    ]

    ticket_id = await support_bot.forward_user_message_to_admin(...)

    self.assertEqual(ticket_id, 42)
    self.assertEqual(bot.send_message.await_count, 3)
    second_call = bot.send_message.await_args_list[1].kwargs
    third_call = bot.send_message.await_args_list[2].kwargs
    self.assertEqual(second_call["text"], "Пользователь: @demo_user\nTelegram ID: 123456789")
    self.assertEqual(third_call["text"], "Не работает VPN")
```

- [ ] **Step 2: Run the recovery test and confirm it fails before the retry path is updated**

Run: `python -m unittest tests.test_support_topic_recovery`
Expected: FAIL because the recovery path still sends one combined message after recreating the topic.

- [ ] **Step 3: Make recreated topics reuse the same `header + text` flow as brand-new topics**

```python
    except TelegramBadRequest:
        if topic is None:
            raise
        message_thread_id = await _create_support_topic(
            bot=bot,
            db=db,
            forum_chat_id=forum_chat_id,
            telegram_id=telegram_id,
            username_text=username_text,
            ticket_id=ticket_id,
        )
        await _send_support_topic_header(
            bot=bot,
            forum_chat_id=forum_chat_id,
            message_thread_id=message_thread_id,
            username_text=username_text,
            telegram_id=telegram_id,
        )
        await _send_support_user_text(
            bot=bot,
            forum_chat_id=forum_chat_id,
            message_thread_id=message_thread_id,
            text=text,
        )
```

- [ ] **Step 4: Re-run the recovery test and confirm it passes**

Run: `python -m unittest tests.test_support_topic_recovery`
Expected: PASS.

- [ ] **Step 5: Commit the deleted-topic recovery formatting**

```bash
git add handlers/support_bot.py tests/test_support_topic_recovery.py
git commit -m "fix: resend support topic header after recreation"
```

### Task 4: Проверить минимальный регрессионный набор

**Files:**
- Test: `tests/test_support_flow.py`
- Test: `tests/test_support_topic_recovery.py`

- [ ] **Step 1: Run the focused support-flow test methods that do not require FastAPI imports**

Run: `python -m unittest tests.test_support_flow.SupportBotFlowTests`
Expected: PASS for the support topic formatting tests and the unchanged user confirmation test.

- [ ] **Step 2: Run the deleted-topic recovery test again as the final verification**

Run: `python -m unittest tests.test_support_topic_recovery`
Expected: PASS.

- [ ] **Step 3: Compile the touched Python files to catch syntax errors in this lightweight environment**

Run: `python -m py_compile handlers/support_bot.py tests/test_support_flow.py tests/test_support_topic_recovery.py`
Expected: exit code 0 and no output.

- [ ] **Step 4: Commit the final verified state if the earlier task commits were skipped**

```bash
git add handlers/support_bot.py tests/test_support_flow.py tests/test_support_topic_recovery.py
git commit -m "fix: split first support topic message flow"
```
