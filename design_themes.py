"""Lord Design theme engine: restyles Discord channel/category names with emoji + fancy Unicode fonts."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# ---------------- Fancy Unicode font maps ----------------
# (upper_start, lower_start, digit_start) in the Mathematical Alphanumeric Symbols block (no holes for these).
_MATH_FONTS: dict[str, tuple[int, int, Optional[int]]] = {
    "bold_serif": (0x1D400, 0x1D41A, 0x1D7CE),
    "bold_sans": (0x1D5D4, 0x1D5EE, 0x1D7EC),
    "italic_bold_sans": (0x1D63C, 0x1D656, 0x1D7EC),
    "script_bold": (0x1D4D0, 0x1D4EA, 0x1D7CE),
    "fraktur_bold": (0x1D56C, 0x1D586, 0x1D7CE),
    "monospace": (0x1D670, 0x1D68A, 0x1D7F6),
}

_SMALL_CAPS = dict(zip(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
))
_SMALL_CAPS_REV = {v: k for k, v in _SMALL_CAPS.items()}

ACRONYMS = {
    "vc", "vip", "bgmi", "exe", "gg", "fps", "pubg", "gta", "cs", "ai", "faq",
    "dm", "id", "rp", "op", "pc", "lfg", "afk", "fx", "ff", "cod", "esp", "sfx",
}


def apply_font(text: str, font: str) -> str:
    if font == "plain":
        return text
    if font == "small_caps":
        return "".join(_SMALL_CAPS.get(ch.lower(), ch) for ch in text)
    spec = _MATH_FONTS.get(font)
    if not spec:
        return text
    up, low, dig = spec
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(up + ord(ch) - 65))
        elif "a" <= ch <= "z":
            out.append(chr(low + ord(ch) - 97))
        elif dig is not None and "0" <= ch <= "9":
            out.append(chr(dig + ord(ch) - 48))
        else:
            out.append(ch)
    return "".join(out)


def clean_words(name: str) -> list[str]:
    """Strip emoji/decorations/fancy fonts from an existing name and return plain words."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(_SMALL_CAPS_REV.get(ch, ch) for ch in s)
    s = re.sub(r"[^A-Za-z0-9\s\-_]", " ", s)
    return [w for w in re.split(r"[\s\-_]+", s) if w]


def _case_word(word: str, mode: str) -> str:
    low = word.lower()
    if mode == "upper":
        return low.upper()
    if mode == "lower":
        return low
    if low in ACRONYMS:
        return low.upper()
    return low[:1].upper() + low[1:]


# ---------------- Emoji keyword engine ----------------
# Ordered by priority: first match wins.
CHANNEL_EMOJI_RULES: list[tuple[tuple[str, ...], str]] = [
    (("welcome",), "👋"),
    (("goodbye", "bye", "leave", "left"), "🚪"),
    (("rule", "rules"), "📜"),
    (("announcement", "announcements", "announce"), "📢"),
    (("news",), "📰"),
    (("ticket", "support", "help"), "🎫"),
    (("faq",), "❓"),
    (("report", "bug", "bugs"), "🐞"),
    (("music", "song", "songs", "spotify"), "🎵"),
    (("meme", "memes", "fun"), "😂"),
    (("screenshot", "screenshots", "media", "gameplay", "photo", "photos"), "📸"),
    (("clip", "clips", "highlight", "highlights", "video", "videos"), "🎬"),
    (("giveaway", "giveaways", "free", "loot", "gamesloot", "drop", "drops"), "🎁"),
    (("winner", "winners"), "🏆"),
    (("event", "events"), "🎉"),
    (("poll", "polls", "vote"), "📊"),
    (("key", "keys"), "🔑"),
    (("exe", "download", "downloads", "file", "files", "apk"), "💾"),
    (("bot", "bots", "flavibot"), "🤖"),
    (("update", "updates", "patch", "patchnotes", "changelog"), "🔄"),
    (("staff", "mod", "mods", "admin", "admins"), "🛡️"),
    (("log", "logs"), "📋"),
    (("role", "roles"), "🎭"),
    (("owner", "owners"), "👑"),
    (("vip", "premium"), "💎"),
    (("lag", "boost", "ping"), "⚡"),
    (("lfg", "squad", "team", "duo", "trio"), "🎯"),
    (("chat", "chatting", "chaating", "general", "talk", "lounge"), "💬"),
    (("create", "join"), "➕"),
    (("afk",), "💤"),
    (("chill",), "🛋️"),
    (("rob", "run", "robrun"), "🏃"),
    (("hax", "hack", "hacks", "cheat", "cheats", "mod", "mods"), "🛠️"),
    (("game", "games", "gaming"), "🎮"),
]

CATEGORY_EMOJI_RULES: list[tuple[tuple[str, ...], str]] = [
    (("announcement", "announcements", "info", "information", "news"), "📢"),
    (("welcome",), "👋"),
    (("community", "public", "general"), "🌐"),
    (("office", "work", "hax", "tools"), "💼"),
    (("vc", "voice", "lounge"), "🔊"),
    (("staff", "admin", "mod", "mods"), "🛡️"),
    (("support", "ticket", "tickets", "help"), "🎫"),
    (("event", "events", "giveaway", "giveaways"), "🎉"),
    (("game", "games", "gaming", "hub"), "🎮"),
    (("music",), "🎵"),
]


def pick_emoji(words: list[str], rules: list[tuple[tuple[str, ...], str]], default: str) -> str:
    lowered = {w.lower() for w in words}
    joined = "-".join(w.lower() for w in words)
    for keys, emoji in rules:
        for k in keys:
            if k in lowered or (len(k) >= 5 and k in joined):
                return emoji
    return default


# ---------------- Themes ----------------
@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    icon: str
    color: int
    description: str
    font: str
    case: str
    sep: str
    cat_font: str
    cat_case: str
    cat_fmt: str
    voice_default: str = "🔊"
    text_default: str = "💬"


THEMES: dict[str, Theme] = {
    t.key: t
    for t in [
        Theme(
            key="lord_neon", name="Lord Neon", icon="⚡", color=0x38BDF8,
            description="Electric cyan bold serif — matches the Lord icon & Cyber City banner",
            font="bold_serif", case="title", sep="・",
            cat_font="bold_sans", cat_case="upper", cat_fmt="╭───・{cemoji} {name} {cemoji}・───➤",
        ),
        Theme(
            key="royal_empire", name="Royal Empire", icon="👑", color=0xFBBF24,
            description="Golden royal script font with crown frames",
            font="script_bold", case="title", sep="┃",
            cat_font="bold_serif", cat_case="upper", cat_fmt="꧁・👑 {name} 👑・꧂",
        ),
        Theme(
            key="cyber_hacker", name="Cyber Hacker", icon="💻", color=0x22C55E,
            description="Terminal monospace hacker style",
            font="monospace", case="lower", sep="〢",
            cat_font="monospace", cat_case="upper", cat_fmt="▸ {cemoji} [ {name} ] ━━━━━━",
        ),
        Theme(
            key="inferno_gamer", name="Inferno Gamer", icon="🔥", color=0xF97316,
            description="Heavy bold sans with blazing fire bars",
            font="bold_sans", case="title", sep="・",
            cat_font="bold_sans", cat_case="upper", cat_fmt="▬▬▬ 🔥 {name} 🔥 ▬▬▬",
        ),
        Theme(
            key="galaxy_aesthetic", name="Galaxy Aesthetic", icon="🌌", color=0xA855F7,
            description="Soft small-caps aesthetic with star dividers",
            font="small_caps", case="lower", sep="⋆",
            cat_font="small_caps", cat_case="lower", cat_fmt="✦ ── {cemoji} {name} ── ✦",
        ),
        Theme(
            key="anime_sakura", name="Anime Sakura", icon="🌸", color=0xF472B6,
            description="Cute anime italic sans with sakura frames",
            font="italic_bold_sans", case="title", sep="︱",
            cat_font="small_caps", cat_case="lower", cat_fmt="❀・{cemoji} {name} ・❀ ─────",
        ),
        Theme(
            key="dark_shadow", name="Dark Shadow", icon="☠️", color=0xEF4444,
            description="Gothic fraktur letters with skull frames",
            font="fraktur_bold", case="title", sep="⌇",
            cat_font="bold_serif", cat_case="upper", cat_fmt="☠ ═══ {name} ═══ ☠",
        ),
        Theme(
            key="esports_clean", name="Esports Clean", icon="🎮", color=0x60A5FA,
            description="Clean pro-esports look, plain readable text",
            font="plain", case="lower", sep="│",
            cat_font="plain", cat_case="upper", cat_fmt="━━ {cemoji} {name} ━━",
        ),
    ]
}


def _style_words(words: list[str], font: str, case: str, joiner: str) -> str:
    return joiner.join(apply_font(_case_word(w, case), font) for w in words)


def style_channel(name: str, theme: Theme, *, is_voice: bool = False) -> Optional[str]:
    words = clean_words(name)
    if not words:
        return None
    emoji = pick_emoji(words, CHANNEL_EMOJI_RULES, theme.voice_default if is_voice else theme.text_default)
    joiner = " " if is_voice else "-"
    styled = _style_words(words, theme.font, theme.case, joiner)
    return f"{emoji}{theme.sep}{styled}"[:100]


def style_category(name: str, theme: Theme) -> Optional[str]:
    words = clean_words(name)
    if not words:
        return None
    cemoji = pick_emoji(words, CATEGORY_EMOJI_RULES, theme.icon)
    styled = _style_words(words, theme.cat_font, theme.cat_case, "-")
    return theme.cat_fmt.format(name=styled, cemoji=cemoji, icon=theme.icon)[:100]


# ---------------- Ready-made module packs ----------------
# Each entry: (kind, base_name) where kind is "text" or "voice".
MODULES: dict[str, dict] = {
    "gaming_hub": {
        "title": "Gaming Hub",
        "category": "Gaming Hub",
        "channels": [("text", "game-chat"), ("text", "clips-highlights"), ("text", "lfg-squad"),
                     ("text", "game-news"), ("voice", "Squad 1"), ("voice", "Squad 2")],
    },
    "support_desk": {
        "title": "Support Desk",
        "category": "Support",
        "channels": [("text", "open-ticket"), ("text", "faq"), ("text", "report-bug")],
    },
    "events_giveaways": {
        "title": "Events & Giveaways",
        "category": "Events",
        "channels": [("text", "giveaways"), ("text", "events"), ("text", "winners"), ("text", "polls")],
    },
    "vc_lounge": {
        "title": "VC Lounge",
        "category": "VC Lounge",
        "channels": [("text", "vc-chat"), ("voice", "Chill Lounge"), ("voice", "Gaming VC 1"),
                     ("voice", "Gaming VC 2"), ("voice", "AFK")],
    },
    "staff_zone": {
        "title": "Staff Zone (private)",
        "category": "Staff",
        "channels": [("text", "staff-chat"), ("text", "staff-announcements"), ("text", "mod-logs"),
                     ("voice", "Staff Meeting")],
        "private": True,
    },
    "information": {
        "title": "Information",
        "category": "Information",
        "channels": [("text", "rules"), ("text", "announcements"), ("text", "updates"), ("text", "roles")],
    },
}
