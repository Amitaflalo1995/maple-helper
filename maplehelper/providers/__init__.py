"""The AI CLIs a player can run Maple Helper on, each with their own account: Claude Code, Codex, Antigravity (Gemini) or Grok Build."""
from __future__ import annotations

from .base import Provider
from .claude import Claude
from .codex import Codex
from .gemini import Gemini
from .grok import Grok

PROVIDERS: dict[str, Provider] = {"claude": Claude(), "codex": Codex(), "gemini": Gemini(), "grok": Grok()}
DEFAULT = "claude"


def get(name: str | None) -> Provider:
    """The provider by name; unknown or missing names (old settings) mean Claude."""
    return PROVIDERS.get(name or DEFAULT) or PROVIDERS[DEFAULT]
