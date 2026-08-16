#!/usr/bin/env python3
"""Telegram multi-capability bot — entrypoint.

Discovers all modules/plugins and registers them with the Application.
"""

import importlib
import logging
import os
import signal
import sys
from pathlib import Path
from typing import List

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from config import Config
from modules.base import BotPlugin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plugin auto‑discovery
# ---------------------------------------------------------------------------
def _discover_plugins(config: Config) -> List[BotPlugin]:
    """Scan modules/*.py for subclasses of BotPlugin and instantiate."""
    plugins: List[BotPlugin] = []
    modules_dir = Path(__file__).parent / "modules"

    for fpath in sorted(modules_dir.glob("*.py")):
        if fpath.name in ("__init__.py", "base.py"):
            continue
        mod_name = f"modules.{fpath.stem}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:
            logger.warning("Failed to import %s: %s", mod_name, exc)
            continue

        # Find any class in the module that subclasses BotPlugin (and isn't BotPlugin itself)
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BotPlugin)
                and attr is not BotPlugin
            ):
                try:
                    instance = attr(config)
                    plugins.append(instance)
                    logger.info("Loaded plugin: %s (%s)", instance.name, mod_name)
                except Exception as exc:
                    logger.error("Failed to instantiate plugin %s: %s", attr_name, exc)
    return plugins


# ---------------------------------------------------------------------------
# /help handler (aggregates all plugin help texts)
# ---------------------------------------------------------------------------
async def _help_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["**Available commands:**\n"]
    lines.append("/help — show this message")
    for p in _plugins:
        lines.append(p.help_text())
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
_plugins: List[BotPlugin] = []


def main() -> None:
    config = Config()
    if not config.valid:
        sys.exit(1)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Optional Prometheus metrics endpoint (port 8080 by convention)
    if config.metrics_port:
        try:
            from prometheus_client import start_http_server
            start_http_server(config.metrics_port)
            logger.info("Metrics server started on port %d", config.metrics_port)
        except Exception as exc:
            logger.warning("Failed to start metrics server: %s", exc)

    # Build application
    app: Application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .build()
    )

    # Authorization filter — applied to all handlers
    from telegram.ext import filters as ext_filters
    user_filter = ext_filters.User(user_id=config.authorized_users)

    # Discover and register plugins
    global _plugins
    _plugins = _discover_plugins(config)
    for p in _plugins:
        try:
            p.register(app)
            logger.info("Registered plugin: %s", p.name)
        except Exception as exc:
            logger.error("Failed to register plugin %s: %s", p.name, exc)

    # Register /help
    app.add_handler(CommandHandler("help", _help_cmd, filters=user_filter))

    # Set bot commands for menu
    from telegram import BotCommand
    bot_commands = [BotCommand(command="help", description="Show all commands")]
    for p in _plugins:
        first_line = p.help_text().split("\n")[0][:100]
        bot_commands.append(BotCommand(command=p.name, description=first_line))

    # Graceful shutdown
    async def shutdown() -> None:
        logger.info("Shutting down...")
        await app.stop()

    loop = app.loop
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda: loop.create_task(shutdown()),
        )

    logger.info("Starting bot with %d plugin(s)", len(_plugins))
    app.run_polling()


if __name__ == "__main__":
    main()