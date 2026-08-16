"""Summary plugin — per-user message summary via LLM.

Collects messages in-memory as they arrive.  On /summary <period>,
filters by requesting user and time window then asks an LLM to
summarise.  Result is DM'd to the user only.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List

from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from modules.base import BotPlugin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory message store:  chat_id → list of MessageRecord
# ---------------------------------------------------------------------------
MessageRecord = Dict[str, object]  # {user_id, text, timestamp}
_store: Dict[int, List[MessageRecord]] = {}


def _collect(chat_id: int, user_id: int, text: str | None) -> None:
    """Append a message to the in-memory ring buffer."""
    if not text or not text.strip():
        return
    if chat_id not in _store:
        _store[chat_id] = []
    _store[chat_id].append({
        "user_id": user_id,
        "text": text.strip(),
        "timestamp": time.time(),
    })
    # Trim to max size to avoid unbounded growth
    max_size = 5000  # hard ceiling
    if len(_store[chat_id]) > max_size:
        _store[chat_id] = _store[chat_id][-max_size:]


def _parse_period(arg: str | None) -> timedelta:
    """Parse user-friendly period string → timedelta."""
    if not arg:
        return timedelta(hours=24)  # default = last 24h
    arg = arg.strip().lower()
    for kw, td in [
        ("hour", timedelta(hours=1)),
        ("6h", timedelta(hours=6)),
        ("12h", timedelta(hours=12)),
        ("24h", timedelta(hours=24)),
        ("day", timedelta(days=1)),
        ("2d", timedelta(days=2)),
        ("3d", timedelta(days=3)),
        ("7d", timedelta(days=7)),
        ("week", timedelta(weeks=1)),
        ("14d", timedelta(days=14)),
        ("2w", timedelta(weeks=2)),
        ("30d", timedelta(days=30)),
        ("month", timedelta(days=30)),
    ]:
        if arg.startswith(kw) or arg.endswith(kw) or arg == kw:
            return td
    # fallback: try parse as number of hours
    try:
        return timedelta(hours=int(arg))
    except ValueError:
        return timedelta(hours=24)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
class SummaryPlugin(BotPlugin):
    def __init__(self, config) -> None:
        super().__init__(config)
        self._client: OpenAI | None = None

    @property
    def _llm(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=self._cfg.llm_base_url,
                api_key=self._cfg.llm_api_key,
            )
        return self._client

    @property
    def name(self) -> str:
        return "summary"

    def help_text(self) -> str:
        return "📊 /summary [7d|24h|week|…] — DM you a summary of your recent messages"

    def register(self, app: Application) -> None:
        # Collect every text message
        app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & self._auth,
                self._collect_message,
                block=False,
            )
        )
        # /summary command
        app.add_handler(CommandHandler("summary", self._summary, filters=self._auth, block=False))

    async def _collect_message(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        msg = update.effective_message
        if not msg or not msg.from_user:
            return
        _collect(
            chat_id=msg.chat.id,
            user_id=msg.from_user.id,
            text=msg.text,
        )

    async def _summary(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        msg = update.effective_message
        if not msg or not msg.from_user:
            return

        requesting_user = msg.from_user.id
        chat_id = msg.chat.id
        period_str = msg.text.removeprefix("/summary").strip()
        period = _parse_period(period_str)

        # Filter messages from this user within the time window
        cutoff = time.time() - period.total_seconds()
        chat_msgs = _store.get(chat_id, [])
        user_msgs = [
            m["text"]
            for m in chat_msgs
            if m["user_id"] == requesting_user and m["timestamp"] >= cutoff
        ]

        if not user_msgs:
            await msg.reply_text(
                f"No messages from you found in the last {period_str or '24h'} "
                f"({len(chat_msgs)} total messages in this chat)."
            )
            return

        # Build prompt
        window_label = period_str or "24 hours"
        prompt = (
            f"Below are messages sent by a user over the last {window_label} "
            f"in a chat group. Summarise the key topics, questions, and "
            f"notable content in a concise paragraph.\n\n---\n"
            + "\n".join(user_msgs[-self._cfg.summary_max_messages:])
            + "\n\n---\nSummary:"
        )

        try:
            await msg.chat.send_action("typing")
            resp = self._llm.chat.completions.create(
                model=self._cfg.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=600,
            )
            summary = resp.choices[0].message.content.strip()
        except Exception as exc:
            logger.error("Summary LLM call failed: %s", exc)
            await msg.reply_text("Sorry, the summary couldn't be generated right now.")
            return

        # DM the result to the requesting user only
        header = (
            f"📊 Your summary for the last *{window_label}* "
            f"({len(user_msgs)} messages):\n\n"
        )
        try:
            await msg.chat.send_message(
                text=header + summary,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception:
            # Fallback if parse_mode fails
            await msg.chat.send_message(
                text=header + summary,
                disable_web_page_preview=True,
            )