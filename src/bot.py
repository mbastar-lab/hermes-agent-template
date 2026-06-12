"""Slack Bolt (Socket Mode) entry point for the SEO agent.

Design notes:
- One `message` listener (not app_mention) so a thread's "approve" follow-up —
  a plain reply with no @mention — is still handled, without the double-fire you
  get when both message and app_mention subscriptions deliver a mention.
- A turn is processed only when it's (a) a DM, (b) @-mentions the bot, or
  (c) a reply in a thread we already have a session for. Keeps a busy channel
  from waking the agent on every message.
- Heavy work runs in a background task; the listener returns immediately so the
  Socket Mode envelope is acked well within Slack's redelivery window.
- Jobs are serialized through the FIFO queue (one shared /workspace checkout).
"""
from __future__ import annotations

import asyncio
import logging
import re

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from . import config
from .agent import run_turn
from .job_queue import FifoQueue
from .session_store import SessionStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seo-agent")

app = AsyncApp(token=config.SLACK_BOT_TOKEN)
store = SessionStore(config.DATABASE_URL)
queue = FifoQueue()
_bot_user_id: str | None = None
_mention_re: re.Pattern[str] | None = None


async def _ensure_bot_identity(client) -> None:
    global _bot_user_id, _mention_re
    if _bot_user_id is None:
        _bot_user_id = (await client.auth_test())["user_id"]
        _mention_re = re.compile(rf"<@{_bot_user_id}>")


def _strip_mention(text: str) -> str:
    return _mention_re.sub("", text).strip() if _mention_re else text.strip()


async def _process(event: dict, say, client) -> None:
    thread_ts = event.get("thread_ts") or event["ts"]
    prompt = _strip_mention(event.get("text", ""))
    if not prompt:
        return

    async with queue.slot() as ahead:
        if ahead > 0:
            await say(text=f"⏳ Queued — {ahead} job(s) ahead of you.", thread_ts=thread_ts)
        else:
            await say(text="⏳ On it…", thread_ts=thread_ts)

        session_id = await store.get(thread_ts)
        try:
            result = await asyncio.wait_for(
                run_turn(prompt, session_id), timeout=config.AGENT_TURN_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            await say(
                text="⚠️ That turn ran past the time limit and was stopped. "
                "Try a smaller step, or check the logs.",
                thread_ts=thread_ts,
            )
            return
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the worker
            log.exception("agent turn failed")
            await say(text=f"⚠️ The run failed: `{exc}`", thread_ts=thread_ts)
            return

        if result.session_id:
            await store.put(thread_ts, result.session_id)
        await say(text=result.text or "(done)", thread_ts=thread_ts)


@app.event("message")
async def on_message(event, say, client):
    # Ignore bot/system messages and edits to avoid loops.
    if event.get("bot_id") or event.get("subtype"):
        return
    if _bot_user_id and event.get("user") == _bot_user_id:
        return

    await _ensure_bot_identity(client)

    is_dm = event.get("channel_type") == "im"
    mentions_bot = bool(_mention_re and _mention_re.search(event.get("text", "")))
    thread_ts = event.get("thread_ts") or event["ts"]
    known_thread = await store.get(thread_ts) is not None

    if not (is_dm or mentions_bot or known_thread):
        return

    # Fire-and-forget so the socket envelope acks immediately.
    asyncio.create_task(_process(event, say, client))


async def main() -> None:
    config.require_runtime()
    await store.connect()
    handler = AsyncSocketModeHandler(app, config.SLACK_APP_TOKEN)
    log.info("SEO agent starting (workspace=%s)", config.WORKSPACE)
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
