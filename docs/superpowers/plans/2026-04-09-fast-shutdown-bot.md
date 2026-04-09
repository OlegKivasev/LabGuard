# Fast Shutdown Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ускорить остановку сервиса бота, чтобы `systemctl restart` не ждал полный `TimeoutStopSec` из-за зависания shutdown webapp.

**Architecture:** Ограничить время ожидания `web_task` в `bot.py` через bounded graceful shutdown: попросить uvicorn завершиться, подождать несколько секунд, затем отменить задачу, если она не вышла. Остальной shutdown (`scheduler`, `support_bot.session`, `bot.session`) оставить последовательным.

**Tech Stack:** Python, asyncio, uvicorn, aiogram, unittest/py_compile.

---

## File Structure

- Modify: `bot.py` — ограничить ожидание `web_task` и добавить безопасную отмену.

### Task 1: Ограничить graceful shutdown webapp

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: Implement bounded wait for `web_task`**

```python
    finally:
        if web_server is not None and web_task is not None:
            web_server.should_exit = True
            try:
                await asyncio.wait_for(web_task, timeout=5)
            except asyncio.TimeoutError:
                web_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await web_task
        scheduler.shutdown(wait=False)
        if support_bot is not None:
            await support_bot.session.close()
        await bot.session.close()
```

- [ ] **Step 2: Verify syntax of the modified file**

Run: `python -m py_compile bot.py`
Expected: exit code 0 and no output.

- [ ] **Step 3: Commit and push the change**

```bash
git add bot.py docs/superpowers/plans/2026-04-09-fast-shutdown-bot.md
git commit -m "fix: bound bot shutdown wait"
git push
```
