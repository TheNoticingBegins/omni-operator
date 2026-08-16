"""Persona reply plugin — configurable persona via YAML text file."""

import logging
import os
from pathlib import Path
from typing import Dict

import yaml
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from modules.base import BotPlugin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-user persona selection (in-memory)
# ---------------------------------------------------------------------------
_user_persona: Dict[int, str] = {}  # user_id → persona key


def _load_personas(path: str) -> Dict[str, str]:
    """Load persona definitions from a YAML file."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return {k: v.strip() for k, v in data.items() if isinstance(v, str)}
    except FileNotFoundError:
        logger.warning("Personas file not found at %s — using defaults", path)
        return {"default": "You are a helpful assistant."}
    except yaml.YAMLError as exc:
        logger.error("Error parsing personas YAML: %s", exc)
        return {"default": "You are a helpful assistant."}


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
class PersonaReplyPlugin(BotPlugin):
    def __init__(self, config) -> None:
        super().__init__(config)
        self._client: OpenAI | None = None
        self._personas: Dict[str, str] = {}
        self._last_mtime: float = 0
        self._path = Path(config.personas_path)

    def _reload_if_needed(self) -> None:
        """Reload YAML on change so editing the file takes effect instantly."""
        p = self._path
        if not p.exists():
            return
        mtime = p.stat().st_mtime
        if mtime > self._last_mtime:
            self._personas = _load_personas(str(p))
            self._last_mtime = mtime
            logger.info("Reloaded %d personas from %s", len(self._personas), p)

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
        return "persona"

    def help_text(self) -> str:
        return (
            "🎭 /reply [prompt] — reply as configured persona\n"
            "     /setpersona <name> — set your active persona\n"
            "     /personas — list available personas"
        )

    def register(self, app: Application) -> None:
        app.add_handler(CommandHandler("reply", self._reply, filters=self._auth, block=False))
        app.add_handler(CommandHandler("setpersona", self._set_persona, filters=self._auth, block=False))
        app.add_handler(CommandHandler("personas", self._list_personas, filters=self._auth, block=False))

    async def _reply(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        self._reload_if_needed()

        msg = update.effective_message
        if not msg or not msg.from_user:
            return

        uid = msg.from_user.id
        # The rest of the message after /reply is either persona override or context
        args = msg.text.removeprefix("/reply").strip()

        persona_key = _user_persona.get(uid, "default")
        override_prompt = None  # passed as system prompt override

        # Check if the first word is a known persona key
        first_word = args.split()[0] if args else ""
        if first_word in self._personas:
            persona_key = first_word
            args = " ".join(args.split()[1:])  # rest is context

        system = self._personas.get(persona_key, self._personas.get("default", ""))
        if not system:
            await msg.reply_text("No persona set and no default found.")
            return

        # Build user message: args = what to reply to
        if not args:
            # Find the most recent message in chat that isn't from the bot
            await msg.reply_text(
                "Usage: /reply <what to say>  — for example:\n"
                "/reply hey how's it going?\n"
                "Or: /reply pirate arr tell me about the treasure\n"
                "Use /setpersona <name> to choose your default persona."
            )
            return

        try:
            await msg.chat.send_action("typing")
            resp = self._llm.chat.completions.create(
                model=self._cfg.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": args},
                ],
                temperature=0.7,
                max_tokens=400,
            )
            reply = resp.choices[0].message.content.strip()
            await msg.reply_text(reply)
        except Exception as exc:
            logger.error("Persona reply LLM call failed: %s", exc)
            await msg.reply_text("Couldn't generate a reply right now.")

    async def _set_persona(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        self._reload_if_needed()
        msg = update.effective_message
        if not msg or not msg.from_user:
            return

        key = msg.text.removeprefix("/setpersona").strip().lower()
        if not key:
            known = ", ".join(self._personas.keys())
            await msg.reply_text(f"Available personas: {known}\nUsage: /setpersona <name>")
            return

        if key in self._personas:
            _user_persona[msg.from_user.id] = key
            await msg.reply_text(f"✅ Your persona is now *{key}*.", parse_mode="Markdown")
        else:
            known = ", ".join(self._personas.keys())
            await msg.reply_text(f"Unknown persona '{key}'. Choose from: {known}")

    async def _list_personas(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        self._reload_if_needed()
        msg = update.effective_message
        if not msg:
            return
        lines = ["**Available Personas:**"]
        uid = msg.from_user.id
        current = _user_persona.get(uid, "default")
        for key in self._personas:
            marker = "→ " if key == current else "  "
            lines.append(f"{marker}*{key}*")
        lines.append(f"\nYour active persona: *{current}*")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown")