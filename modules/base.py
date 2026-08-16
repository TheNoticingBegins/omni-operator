"""Abstract base class for all bot plugins."""

from abc import ABC, abstractmethod
from typing import List

from telegram import Update
from telegram.ext import Application, filters


class BotPlugin(ABC):
    """Each plugin registers its /commands and message handlers."""

    def __init__(self, config) -> None:
        self._cfg = config

    @property
    def _auth(self) -> filters.BaseFilter:
        """Filter that only allows authorized users."""
        return filters.User(user_id=self._cfg.authorized_users)

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in logs and /help."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in logs and /help."""

    @abstractmethod
    def register(self, app: Application) -> None:
        """Called at startup — add handlers to the Application."""

    @abstractmethod
    def help_text(self) -> str:
        """One or two lines shown in /help output."""