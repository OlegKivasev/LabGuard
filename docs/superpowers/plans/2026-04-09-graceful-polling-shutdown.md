# Graceful Polling Shutdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать зависание процесса на `asyncio.gather(*polling_tasks)` при остановке сервиса и обеспечить быстрый выход после `SIGTERM`.

**Architecture:** Хранить polling-задачи явно и в `finally` отменять все незавершенные задачи перед bounded shutdown webapp. После отмены собрать их через `asyncio.gather(..., return_exceptions=True)`, затем продолжить уже существующее закрытие webapp, scheduler и bot sessions.

**Tech Stack:** Python, asyncio, aiogram, uvicorn, py_compile.

---

## File Structure

- Modify: `bot.py` — явно отменить незавершенные polling-задачи и дождаться их завершения без зависания.

### Task 1: Явно завершить polling-задачи при shutdown

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: Implement explicit cancellation and collection of polling tasks**

```python
    polling_tasks: list[asyncio.Task] = []
    try:
        polling_tasks.append(asyncio.create_task(dp.start_polling(bot)))
        if support_dp is not None and support_bot is not None:
            polling_tasks.append(asyncio.create_task(support_dp.start_polling(support_bot)))
        await asyncio.gather(*polling_tasks)
    finally:
        for task in polling_tasks:
            if not task.done():
                task.cancel()
        if polling_tasks:
            await asyncio.gather(*polling_tasks, return_exceptions=True)

        if web_server is not None and web_task is not None:
            web_server.should_exit = True
            try:
                await asyncio.wait_for(web_task, timeout=5)
            except asyncio.TimeoutError:
                web_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await web_task
```

- [ ] **Step 2: Verify syntax of the modified file**

Run: `python -m py_compile bot.py`
Expected: exit code 0 and no output.

- [ ] **Step 3: Commit and push the change**

```bash
git add bot.py docs/superpowers/specs/2026-04-09-graceful-polling-shutdown-design.md docs/superpowers/plans/2026-04-09-graceful-polling-shutdown.md
git commit -m "fix: cancel polling tasks on shutdown"
git push
```
