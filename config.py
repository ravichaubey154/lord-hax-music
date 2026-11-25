from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _parse_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        return max(value, minimum)
    except ValueError:
        return default


def _parse_color(raw: str, default: int = 0x5865F2) -> int:
    cleaned = raw.strip().lstrip("#")
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    if not cleaned:
        return default
    try:
        return int(cleaned, 16)
    except ValueError:
        return default


@dataclass(frozen=True)
class BotConfig:
    token: str
    bot_name: str
    command_prefix: str
    embed_color: int
    inactivity_timeout: int
    max_playlist_items: int
    icon_path: Path

    @classmethod
    def from_env(cls) -> "BotConfig":
        raw_icon = os.getenv("BOT_ICON_PATH", "assets/bot_icon.png").strip() or "assets/bot_icon.png"
        icon_path = Path(raw_icon)
        if not icon_path.is_absolute():
            icon_path = BASE_DIR / icon_path
        return cls(
            token=os.getenv("DISCORD_TOKEN", "").strip(),
            bot_name=os.getenv("BOT_NAME", "Lord Hax Music").strip() or "Lord Hax Music",
            command_prefix=os.getenv("COMMAND_PREFIX", "!").strip() or "!",
            embed_color=_parse_color(os.getenv("EMBED_COLOR", "38BDF8"), default=0x38BDF8),
            inactivity_timeout=_parse_int("INACTIVITY_TIMEOUT", 180, minimum=15),
            max_playlist_items=_parse_int("MAX_PLAYLIST_ITEMS", 50, minimum=1),
            icon_path=icon_path,
        )
