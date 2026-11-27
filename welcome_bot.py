from __future__ import annotations

import asyncio
import io
import json
import logging
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

logger = logging.getLogger("lord_welcome")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "welcome_data"
BACKGROUNDS_DIR = DATA_DIR / "backgrounds"
SETTINGS_FILE = DATA_DIR / "guilds.json"
DEFAULT_WELCOME_BANNER = BASE_DIR / "default_welcome.gif"
DEFAULT_GOODBYE_BANNER = BASE_DIR / "default_goodbye.gif"

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

DEFAULT_TITLE = "Welcome to {server}!"
DEFAULT_MESSAGE = (
    "Welcome {mention} to **{server}**! "
    "Enjoy your stay — you are member **#{count}**."
)
DEFAULT_GOODBYE_TITLE = "Goodbye from {server}!"
DEFAULT_GOODBYE = "**{user}** has left **{server}**. We now have **{count}** members."

CARD_WIDTH = 1024
CARD_HEIGHT = 420

BOLD_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _parse_color(raw: str, default: int = 0x38BDF8) -> int:
    cleaned = raw.strip().lstrip("#")
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    if not cleaned:
        return default
    try:
        val = int(cleaned, 16)
        return val if 0 <= val <= 0xFFFFFF else default
    except ValueError:
        return default


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (BOLD_FONT_CANDIDATES if bold else REGULAR_FONT_CANDIDATES):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _hex_to_rgb(color_int: int) -> tuple[int, int, int]:
    return ((color_int >> 16) & 0xFF, (color_int >> 8) & 0xFF, color_int & 0xFF)


def _create_default_bg(accent_rgb: tuple[int, int, int]) -> Image.Image:
    bg = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (10, 14, 24, 255))
    draw = ImageDraw.Draw(bg)
    for y in range(CARD_HEIGHT):
        t = y / CARD_HEIGHT
        draw.line(
            [(0, y), (CARD_WIDTH, y)],
            fill=(int(10 + 10 * t), int(14 + 14 * t), int(26 + 22 * t), 255),
        )
    glow = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([-120, -140, 420, 400], fill=(*accent_rgb, 75))
    gdraw.ellipse([660, 60, 1180, 560], fill=(139, 92, 246, 70))
    gdraw.ellipse([320, -180, 740, 220], fill=(*accent_rgb, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=75))
    bg = Image.alpha_composite(bg, glow)
    grid = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    g2 = ImageDraw.Draw(grid)
    for x in range(0, CARD_WIDTH, 48):
        g2.line([(x, 0), (x, CARD_HEIGHT)], fill=(255, 255, 255, 10), width=1)
    for y in range(0, CARD_HEIGHT, 48):
        g2.line([(0, y), (CARD_WIDTH, y)], fill=(255, 255, 255, 10), width=1)
    return Image.alpha_composite(bg, grid)


def _fit_text(
    draw: ImageDraw.ImageDraw, text: str, max_w: int, start: int, minimum: int, *, bold: bool = True
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    for size in range(start, minimum - 1, -2):
        font = _load_font(size, bold=bold)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_w:
            return text, font
    font = _load_font(minimum, bold=bold)
    trimmed = text
    while len(trimmed) > 3:
        cand = trimmed + "..."
        bb = draw.textbbox((0, 0), cand, font=font)
        if (bb[2] - bb[0]) <= max_w:
            return cand, font
        trimmed = trimmed[:-1]
    return trimmed, font


def generate_member_card(
    *,
    member_name: str,
    member_handle: str,
    server_name: str,
    member_count: int,
    avatar_bytes: Optional[bytes] = None,
    background_bytes: Optional[bytes] = None,
    accent_color: int = 0x38BDF8,
    bot_brand: str = "Lord Welcome",
    badge_text: str = "WELCOME",
    server_line_prefix: str = "Joined",
    count_label: Optional[str] = None,
) -> bytes:
    accent_rgb = _hex_to_rgb(accent_color)
    canvas: Optional[Image.Image] = None
    if background_bytes:
        try:
            with Image.open(io.BytesIO(background_bytes)) as raw:
                canvas = ImageOps.fit(
                    raw.convert("RGBA"),
                    (CARD_WIDTH, CARD_HEIGHT),
                    method=Image.Resampling.LANCZOS,
                )
        except Exception:
            canvas = None
    if canvas is None:
        canvas = _create_default_bg(accent_rgb)

    overlay = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle([0, 0, CARD_WIDTH, CARD_HEIGHT], fill=(6, 10, 18, 125))
    pad = 28
    odraw.rounded_rectangle(
        [pad, pad, CARD_WIDTH - pad, CARD_HEIGHT - pad],
        radius=28,
        fill=(10, 14, 24, 155),
        outline=(*accent_rgb, 185),
        width=3,
    )
    canvas = Image.alpha_composite(canvas, overlay)

    avatar_size = 210
    avatar_x = 84
    avatar_y = (CARD_HEIGHT - avatar_size) // 2

    ring = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        [avatar_x - 10, avatar_y - 10, avatar_x + avatar_size + 10, avatar_y + avatar_size + 10],
        fill=(*accent_rgb, 150),
    )
    canvas = Image.alpha_composite(canvas, ring.filter(ImageFilter.GaussianBlur(radius=14)))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse(
        [avatar_x - 6, avatar_y - 6, avatar_x + avatar_size + 6, avatar_y + avatar_size + 6],
        fill=(*accent_rgb, 255),
    )

    if avatar_bytes:
        try:
            with Image.open(io.BytesIO(avatar_bytes)) as av:
                avatar_img = ImageOps.fit(
                    av.convert("RGBA"), (avatar_size, avatar_size), method=Image.Resampling.LANCZOS
                )
        except Exception:
            avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (30, 41, 59, 255))
    else:
        avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (30, 41, 59, 255))
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, avatar_size, avatar_size], fill=255)
    canvas.paste(avatar_img, (avatar_x, avatar_y), mask)

    text_x = avatar_x + avatar_size + 52
    max_w = CARD_WIDTH - text_x - 62

    badge_font = _load_font(22, bold=True)
    bb = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w, badge_h, badge_y = (bb[2] - bb[0]) + 36, 38, 74

    count_font = _load_font(21, bold=True)
    count_text = count_label or f"Member #{member_count}"
    cb = draw.textbbox((0, 0), count_text, font=count_font)
    cw, ch, count_y = (cb[2] - cb[0]) + 32, 38, 322

    pills = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(pills)
    pdraw.rounded_rectangle(
        [text_x, badge_y, text_x + badge_w, badge_y + badge_h],
        radius=19,
        fill=(*accent_rgb, 42),
        outline=(*accent_rgb, 230),
        width=2,
    )
    pdraw.rounded_rectangle(
        [text_x, count_y, text_x + cw, count_y + ch],
        radius=12,
        fill=(255, 255, 255, 26),
        outline=(255, 255, 255, 90),
        width=1,
    )
    canvas = Image.alpha_composite(canvas, pills)
    draw = ImageDraw.Draw(canvas)

    draw.text(
        (text_x + (badge_w - (bb[2] - bb[0])) // 2 - bb[0], badge_y + (badge_h - (bb[3] - bb[1])) // 2 - bb[1]),
        badge_text,
        font=badge_font,
        fill=(241, 245, 249, 255),
    )

    name_str, name_font = _fit_text(draw, member_name, max_w, 54, 28, bold=True)
    draw.text((text_x + 2, 132), name_str, font=name_font, fill=(0, 0, 0, 180))
    draw.text((text_x, 130), name_str, font=name_font, fill=(255, 255, 255, 255))

    sub_text = f"@{member_handle}" if member_handle and member_handle != member_name else server_name
    sub_str, sub_font = _fit_text(draw, sub_text, max_w, 24, 16, bold=False)
    draw.text((text_x, 204), sub_str, font=sub_font, fill=(203, 213, 225, 240))

    draw.rounded_rectangle([text_x, 250, text_x + min(max_w, 420), 254], radius=2, fill=(*accent_rgb, 230))

    srv_str, srv_font = _fit_text(draw, f"{server_line_prefix} {server_name}", max_w, 28, 18, bold=True)
    draw.text((text_x, 270), srv_str, font=srv_font, fill=(241, 245, 249, 255))

    draw.text(
        (text_x + (cw - (cb[2] - cb[0])) // 2 - cb[0], count_y + (ch - (cb[3] - cb[1])) // 2 - cb[1]),
        count_text,
        font=count_font,
        fill=(241, 245, 249, 255),
    )

    brand_font = _load_font(18, bold=False)
    bbb = draw.textbbox((0, 0), bot_brand, font=brand_font)
    draw.text(
        (CARD_WIDTH - pad - 24 - (bbb[2] - bbb[0]), CARD_HEIGHT - pad - 36),
        bot_brand,
        font=brand_font,
        fill=(148, 163, 184, 210),
    )

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


@dataclass
class GuildWelcomeConfig:
    guild_id: int
    welcome_channel_id: Optional[int] = None
    goodbye_channel_id: Optional[int] = None
    goodbye_enabled: bool = True
    auto_role_id: Optional[int] = None
    title: str = DEFAULT_TITLE
    message: str = DEFAULT_MESSAGE
    goodbye_title: str = DEFAULT_GOODBYE_TITLE
    goodbye_message: str = DEFAULT_GOODBYE
    color: int = 0x38BDF8
    goodbye_color: int = 0xA855F7
    mode: Literal["card", "banner"] = "card"
    image_filename: Optional[str] = None
    image_url: Optional[str] = None
    image_source_channel_id: Optional[int] = None
    image_source_message_id: Optional[int] = None
    is_animated: bool = False
    goodbye_image_filename: Optional[str] = None
    goodbye_image_url: Optional[str] = None
    goodbye_image_source_channel_id: Optional[int] = None
    goodbye_image_source_message_id: Optional[int] = None
    goodbye_is_animated: bool = False

    def image_path(self, kind: str = "welcome") -> Optional[Path]:
        fname = self.goodbye_image_filename if kind == "goodbye" else self.image_filename
        if not fname:
            return None
        p = BACKGROUNDS_DIR / fname
        return p if p.is_file() else None


class ConfigStore:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
        self._cache: dict[int, GuildWelcomeConfig] = {}
        self._load()

    def _load(self) -> None:
        if not SETTINGS_FILE.is_file():
            return
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            known = set(GuildWelcomeConfig.__dataclass_fields__)
            for gid_str, item in raw.items():
                filtered = {k: v for k, v in item.items() if k in known}
                filtered["guild_id"] = int(gid_str)
                self._cache[int(gid_str)] = GuildWelcomeConfig(**filtered)
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps({str(k): asdict(v) for k, v in self._cache.items()}, indent=2),
            encoding="utf-8",
        )

    def export_json(self) -> str:
        return json.dumps({str(k): asdict(v) for k, v in self._cache.items()}, indent=2)

    def import_json(self, raw_text: str) -> int:
        raw = json.loads(raw_text)
        known = set(GuildWelcomeConfig.__dataclass_fields__)
        count = 0
        for gid_str, item in raw.items():
            filtered = {k: v for k, v in item.items() if k in known}
            filtered["guild_id"] = int(gid_str)
            self._cache[int(gid_str)] = GuildWelcomeConfig(**filtered)
            count += 1
        if count:
            self._save()
        return count

    def has_any_config(self) -> bool:
        return bool(self._cache)

    def get(self, guild_id: int) -> GuildWelcomeConfig:
        cfg = self._cache.get(guild_id)
        if cfg is None:
            cfg = GuildWelcomeConfig(guild_id=guild_id)
            self._cache[guild_id] = cfg
            self._save()
        return cfg

    def update(self, cfg: GuildWelcomeConfig) -> None:
        self._cache[cfg.guild_id] = cfg
        self._save()

    def save_bg(self, guild_id: int, data: bytes, ext: str, *, kind: str = "welcome") -> str:
        BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
        clean_ext = ext.lower().lstrip(".")
        if clean_ext not in ALLOWED_IMAGE_EXTENSIONS:
            clean_ext = "png"
        prefix = f"{kind}_{guild_id}"
        for old in BACKGROUNDS_DIR.glob(f"{prefix}.*"):
            try:
                old.unlink()
            except OSError:
                pass
        filename = f"{prefix}.{clean_ext}"
        (BACKGROUNDS_DIR / filename).write_bytes(data)
        return filename

    def clear_bg(self, guild_id: int, *, kind: str = "welcome") -> None:
        for old in BACKGROUNDS_DIR.glob(f"{kind}_{guild_id}.*"):
            try:
                old.unlink()
            except OSError:
                pass


def _render_tpl(tpl: str, member: discord.Member) -> str:
    count = member.guild.member_count or len(member.guild.members)
    return (
        tpl.replace("{mention}", member.mention)
        .replace("{user}", member.display_name)
        .replace("{username}", member.name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(count))
    )


def _guess_ext(name_or_url: str, ct: str = "") -> str:
    low = ct.lower()
    for ext in ("gif", "webp", "png"):
        if ext in low:
            return ext
    if "jpeg" in low or "jpg" in low:
        return "jpg"
    clean = name_or_url.split("?")[0].lower()
    for ext in ALLOWED_IMAGE_EXTENSIONS:
        if clean.endswith(f".{ext}"):
            return ext
    return "png"


async def _download_bytes(url: str) -> tuple[bytes, str]:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Image download failed (HTTP {resp.status})")
            data = await resp.read()
            if len(data) > MAX_IMAGE_BYTES:
                raise RuntimeError("Image 10 MB se badi hai — chhoti image upload karo.")
            return data, resp.headers.get("Content-Type", "")


class WelcomeCog(commands.Cog):
    BACKUP_MARKER = "[LORD_WELCOME_BACKUP_V1]"

    def __init__(self, bot: commands.Bot, bot_name: str, command_prefix: str, embed_color: int, store: ConfigStore):
        self.bot = bot
        self.bot_name = bot_name
        self.command_prefix = command_prefix
        self.embed_color = embed_color
        self.store = store
        self._restored = False

    def _icon(self) -> Optional[str]:
        return self.bot.user.display_avatar.url if self.bot.user else None

    async def _owner_dm(self) -> Optional[discord.DMChannel]:
        try:
            info = await self.bot.application_info()
            return await info.owner.create_dm() if info.owner else None
        except Exception:
            return None

    async def _backup_to_owner_dm(self) -> None:
        dm = await self._owner_dm()
        if not dm or not self.bot.user:
            return
        try:
            old_msgs = []
            async for msg in dm.history(limit=15):
                if msg.author.id == self.bot.user.id and msg.content.startswith(self.BACKUP_MARKER):
                    old_msgs.append(msg)
            f = discord.File(io.BytesIO(self.store.export_json().encode("utf-8")), filename="lord_welcome_config.json")
            await dm.send(
                content=f"{self.BACKUP_MARKER} Auto-backup of Lord Welcome settings (do not delete — auto-restores after cloud restarts).",
                file=f,
            )
            for old in old_msgs:
                try:
                    await old.delete()
                except discord.HTTPException:
                    pass
        except Exception as exc:
            logger.debug("Owner DM backup skipped: %s", exc)

    async def _restore_from_owner_dm(self) -> None:
        if self._restored:
            return
        self._restored = True
        if self.store.has_any_config():
            return
        dm = await self._owner_dm()
        if not dm or not self.bot.user:
            return
        try:
            async for msg in dm.history(limit=15):
                if msg.author.id == self.bot.user.id and msg.content.startswith(self.BACKUP_MARKER) and msg.attachments:
                    raw = (await msg.attachments[0].read()).decode("utf-8")
                    n = self.store.import_json(raw)
                    logger.info("Restored %d guild welcome config(s) from owner DM backup.", n)
                    return
        except Exception as exc:
            logger.warning("Could not restore owner DM backup: %s", exc)

    def _save(self, gcfg: GuildWelcomeConfig) -> None:
        self.store.update(gcfg)
        self.bot.loop.create_task(self._backup_to_owner_dm())

    @staticmethod
    def _norm_channel_name(name: str) -> str:
        """Normalize stylized Unicode fonts (e.g. '🤝・𝐖𝐞𝐥𝐜𝐨𝐦𝐞' -> 'welcome') for channel matching."""
        return unicodedata.normalize("NFKD", name).lower()

    def _find_welcome_ch(self, guild: discord.Guild, gcfg: GuildWelcomeConfig) -> Optional[discord.TextChannel]:
        if gcfg.welcome_channel_id:
            ch = guild.get_channel(gcfg.welcome_channel_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        for ch in guild.text_channels:
            if "welcome" in self._norm_channel_name(ch.name):
                perms = ch.permissions_for(guild.me)
                if perms.send_messages and perms.embed_links:
                    return ch
        if guild.system_channel:
            perms = guild.system_channel.permissions_for(guild.me)
            if perms.send_messages and perms.embed_links:
                return guild.system_channel
        return None

    def _find_goodbye_ch(self, guild: discord.Guild, gcfg: GuildWelcomeConfig) -> Optional[discord.TextChannel]:
        if gcfg.goodbye_channel_id:
            ch = guild.get_channel(gcfg.goodbye_channel_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        for ch in guild.text_channels:
            cname = self._norm_channel_name(ch.name)
            if any(k in cname for k in ("goodbye", "good-bye", "leave", "bye", "exit")):
                perms = ch.permissions_for(guild.me)
                if perms.send_messages and perms.embed_links:
                    return ch
        return self._find_welcome_ch(guild, gcfg)

    async def _load_bg(self, guild: discord.Guild, gcfg: GuildWelcomeConfig, kind: str) -> tuple[Optional[bytes], str]:
        p = gcfg.image_path(kind)
        if p is not None:
            return p.read_bytes(), p.suffix.lstrip(".").lower() or "png"
        src_ch = gcfg.goodbye_image_source_channel_id if kind == "goodbye" else gcfg.image_source_channel_id
        src_msg = gcfg.goodbye_image_source_message_id if kind == "goodbye" else gcfg.image_source_message_id
        ext_url = gcfg.goodbye_image_url if kind == "goodbye" else gcfg.image_url

        if src_ch and src_msg:
            try:
                ch = guild.get_channel(src_ch)
                if isinstance(ch, discord.TextChannel):
                    msg = await ch.fetch_message(src_msg)
                    if msg.attachments:
                        att = msg.attachments[0]
                        data = await att.read()
                        ext = _guess_ext(att.filename, att.content_type or "")
                        fname = self.store.save_bg(guild.id, data, ext, kind=kind)
                        if kind == "goodbye":
                            gcfg.goodbye_image_filename = fname
                        else:
                            gcfg.image_filename = fname
                        self.store.update(gcfg)
                        return data, ext
            except Exception as exc:
                logger.warning("Could not recover %s image: %s", kind, exc)

        if ext_url:
            try:
                data, ct = await _download_bytes(ext_url)
                ext = _guess_ext(ext_url, ct)
                fname = self.store.save_bg(guild.id, data, ext, kind=kind)
                if kind == "goodbye":
                    gcfg.goodbye_image_filename = fname
                else:
                    gcfg.image_filename = fname
                self.store.update(gcfg)
                return data, ext
            except Exception as exc:
                logger.warning("Could not fetch %s image URL: %s", kind, exc)

        return None, "png"

    async def _send_card(
        self, member: discord.Member, channel: discord.TextChannel, gcfg: GuildWelcomeConfig, *, kind: str
    ) -> None:
        guild = member.guild
        count = guild.member_count or len(guild.members)
        is_goodbye = kind == "goodbye"

        title = _render_tpl((gcfg.goodbye_title if is_goodbye else gcfg.title) or (DEFAULT_GOODBYE_TITLE if is_goodbye else DEFAULT_TITLE), member)
        desc = _render_tpl((gcfg.goodbye_message if is_goodbye else gcfg.message) or (DEFAULT_GOODBYE if is_goodbye else DEFAULT_MESSAGE), member)
        color = gcfg.goodbye_color if is_goodbye else gcfg.color

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_author(
            name=f"{member.display_name} left the server" if is_goodbye else f"{member.display_name} joined!",
            icon_url=member.display_avatar.url,
        )
        embed.set_footer(
            text=f"{self.bot_name} • {count} Members Remaining" if is_goodbye else f"{self.bot_name} • Member #{count}",
            icon_url=self._icon(),
        )

        bg_bytes, bg_ext = await self._load_bg(guild, gcfg, kind)
        used_anim = gcfg.goodbye_is_animated if is_goodbye else gcfg.is_animated
        fallback_url = gcfg.goodbye_image_url if is_goodbye else gcfg.image_url

        # Fall back to the baked-in animated neon gaming banner GIF when no custom override is set
        if bg_bytes is None and not fallback_url:
            default_gif = DEFAULT_GOODBYE_BANNER if is_goodbye else DEFAULT_WELCOME_BANNER
            if default_gif.is_file():
                bg_bytes = default_gif.read_bytes()
                bg_ext = "gif"
                used_anim = True

        mention_content = None if is_goodbye else member.mention
        if gcfg.mode == "banner" or (bg_bytes is not None and (used_anim or bg_ext == "gif")):
            embed.set_thumbnail(url=member.display_avatar.url)
            if bg_bytes is not None:
                fname = f"{kind}.{bg_ext}"
                embed.set_image(url=f"attachment://{fname}")
                await channel.send(content=mention_content, embed=embed, file=discord.File(io.BytesIO(bg_bytes), filename=fname))
                return
            if fallback_url:
                embed.set_image(url=fallback_url)
                await channel.send(content=mention_content, embed=embed)
                return

        avatar_bytes: Optional[bytes] = None
        try:
            avatar_bytes = await member.display_avatar.with_size(256).with_format("png").read()
        except Exception:
            pass

        png = await asyncio.to_thread(
            generate_member_card,
            member_name=member.display_name,
            member_handle=member.name,
            server_name=guild.name,
            member_count=count,
            avatar_bytes=avatar_bytes,
            background_bytes=bg_bytes,
            accent_color=color,
            bot_brand=self.bot_name,
            badge_text="GOODBYE" if is_goodbye else "WELCOME",
            server_line_prefix="Left" if is_goodbye else "Joined",
            count_label=f"Members Left: {count}" if is_goodbye else f"Member #{count}",
        )
        fname = f"{kind}_card.png"
        embed.set_image(url=f"attachment://{fname}")
        await channel.send(content=mention_content, embed=embed, file=discord.File(io.BytesIO(png), filename=fname))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self._restore_from_owner_dm()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        gcfg = self.store.get(member.guild.id)
        if gcfg.auto_role_id:
            role = member.guild.get_role(gcfg.auto_role_id)
            if role and member.guild.me.guild_permissions.manage_roles and member.guild.me.top_role > role:
                try:
                    await member.add_roles(role, reason=f"{self.bot_name} auto-role")
                except discord.HTTPException:
                    pass
        ch = self._find_welcome_ch(member.guild, gcfg)
        if ch:
            try:
                await self._send_card(member, ch, gcfg, kind="welcome")
            except Exception as exc:
                logger.exception("Welcome send failed: %s", exc)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        gcfg = self.store.get(member.guild.id)
        if not gcfg.goodbye_enabled:
            return
        ch = self._find_goodbye_ch(member.guild, gcfg)
        if ch:
            try:
                await self._send_card(member, ch, gcfg, kind="goodbye")
            except Exception as exc:
                logger.exception("Goodbye send failed: %s", exc)

    @commands.hybrid_command(name="setwelcome", description="Welcome channel set karo")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(channel="Welcome channel select karo (jaise #welcome)")
    async def setwelcome(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.welcome_channel_id = channel.id
        self._save(gcfg)
        await ctx.send(f"Welcome channel set ho gaya: {channel.mention}! `/testwelcome` se preview dekho.")

    async def _handle_set_image(
        self, ctx: commands.Context, image: Optional[discord.Attachment], url: Optional[str], *, kind: str
    ) -> None:
        if not ctx.guild:
            return
        await ctx.defer()
        if image is None and ctx.message and ctx.message.attachments:
            image = ctx.message.attachments[0]
        if image is None and not url:
            await ctx.send("Koi image attach karo ya URL paste karo!")
            return
        try:
            if image is not None:
                if image.size > MAX_IMAGE_BYTES:
                    await ctx.send("Image 10 MB se badi hai — chhoti image upload karo.")
                    return
                data = await image.read()
                ext = _guess_ext(image.filename, image.content_type or "")
                source_url = None
            else:
                assert url is not None
                data, ct = await _download_bytes(url.strip())
                ext = _guess_ext(url.strip(), ct)
                source_url = url.strip()
        except Exception as exc:
            await ctx.send(f"Image load nahi ho payi: `{exc}`")
            return

        gcfg = self.store.get(ctx.guild.id)
        fname = self.store.save_bg(ctx.guild.id, data, ext, kind=kind)
        label = "Goodbye/Leave" if kind == "goodbye" else "Welcome"
        test_cmd = "/testgoodbye" if kind == "goodbye" else "/testwelcome"
        sent = await ctx.send(
            content=f"New **{label}** image save ho gayi! Ab `{test_cmd}` se preview dekho.",
            file=discord.File(io.BytesIO(data), filename=f"{kind}_bg.{ext}"),
        )
        if kind == "goodbye":
            gcfg.goodbye_image_filename = fname
            gcfg.goodbye_image_url = source_url
            gcfg.goodbye_is_animated = ext == "gif"
            gcfg.goodbye_image_source_channel_id = sent.channel.id
            gcfg.goodbye_image_source_message_id = sent.id
        else:
            gcfg.image_filename = fname
            gcfg.image_url = source_url
            gcfg.is_animated = ext == "gif"
            gcfg.image_source_channel_id = sent.channel.id
            gcfg.image_source_message_id = sent.id
        self._save(gcfg)

    @commands.hybrid_command(name="setimage", description="Welcome card/banner ki image ya GIF change karo")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(image="Custom image ya GIF upload karo", url="Ya direct image URL paste karo")
    async def setimage(self, ctx: commands.Context, image: Optional[discord.Attachment] = None, url: Optional[str] = None) -> None:
        await self._handle_set_image(ctx, image, url, kind="welcome")

    @commands.hybrid_command(name="setgoodbyeimage", description="Leave/goodbye card ki image ya GIF change karo")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(image="Custom leave image ya GIF upload karo", url="Ya direct image URL paste karo")
    async def setgoodbyeimage(self, ctx: commands.Context, image: Optional[discord.Attachment] = None, url: Optional[str] = None) -> None:
        await self._handle_set_image(ctx, image, url, kind="goodbye")

    @commands.hybrid_command(name="resetimage", description="Custom welcome image hata kar default theme lagao")
    @commands.has_permissions(manage_guild=True)
    async def resetimage(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        self.store.clear_bg(ctx.guild.id, kind="welcome")
        gcfg.image_filename = gcfg.image_url = None
        gcfg.image_source_channel_id = gcfg.image_source_message_id = None
        gcfg.is_animated = False
        self._save(gcfg)
        await ctx.send("Custom welcome image remove kar di — default neon theme active hai.")

    @commands.hybrid_command(name="setmode", description="Style chuno: card (avatar+name) ya banner (raw image/GIF)")
    @commands.has_permissions(manage_guild=True)
    async def setmode(self, ctx: commands.Context, mode: Literal["card", "banner"]) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.mode = mode
        self._save(gcfg)
        await ctx.send(f"Welcome/Leave style set to: **`{mode}`**. `/testwelcome` se check karo!")

    @commands.hybrid_command(name="settitle", description="Welcome embed title badlo")
    @commands.has_permissions(manage_guild=True)
    async def settitle(self, ctx: commands.Context, *, title: str) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.title = title.strip()
        self._save(gcfg)
        await ctx.send(f"Welcome title updated: `{gcfg.title}`")

    @commands.hybrid_command(name="setmessage", description="Welcome text badlo ({mention}, {user}, {server}, {count})")
    @commands.has_permissions(manage_guild=True)
    async def setmessage(self, ctx: commands.Context, *, text: str) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.message = text.strip()
        self._save(gcfg)
        await ctx.send(f"Welcome message updated: `{gcfg.message}`")

    @commands.hybrid_command(name="setgoodbyemessage", description="Leave/goodbye text badlo ({user}, {server}, {count})")
    @commands.has_permissions(manage_guild=True)
    async def setgoodbyemessage(self, ctx: commands.Context, *, text: str) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.goodbye_message = text.strip()
        self._save(gcfg)
        await ctx.send(f"Goodbye message updated: `{gcfg.goodbye_message}`")

    @commands.hybrid_command(name="setcolor", description="Welcome card & embed accent color badlo (#38BDF8)")
    @commands.has_permissions(manage_guild=True)
    async def setcolor(self, ctx: commands.Context, hex_color: str) -> None:
        if not ctx.guild:
            return
        val = _parse_color(hex_color, default=-1)
        if val == -1:
            await ctx.send("Valid hex color daalo, jaise `#38BDF8` ya `#A855F7`.")
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.color = val
        self._save(gcfg)
        await ctx.send(f"Accent color set to `#{val:06X}`!")

    @commands.hybrid_command(name="setautorole", description="Naye member ko auto-role do (blank = off)")
    @commands.has_permissions(manage_guild=True)
    async def setautorole(self, ctx: commands.Context, role: Optional[discord.Role] = None) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.auto_role_id = role.id if role else None
        self._save(gcfg)
        await ctx.send(f"Auto-role set to: {role.mention}" if role else "Auto-role OFF kar diya gaya.")

    @commands.hybrid_command(name="setgoodbye", description="Leave/goodbye channel set karo (blank = auto)")
    @commands.has_permissions(manage_guild=True)
    async def setgoodbye(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.goodbye_channel_id = channel.id if channel else None
        gcfg.goodbye_enabled = True
        self._save(gcfg)
        await ctx.send(
            f"Goodbye channel set ho gaya: {channel.mention}! `/testgoodbye` se preview dekho."
            if channel
            else "Goodbye messages auto-channel (#goodbye ya #welcome) par ON ho gaye!"
        )

    @commands.hybrid_command(name="togglegoodbye", description="Leave/goodbye messages ON ya OFF karo")
    @commands.has_permissions(manage_guild=True)
    async def togglegoodbye(self, ctx: commands.Context, state: Literal["on", "off"]) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        gcfg.goodbye_enabled = state == "on"
        self._save(gcfg)
        await ctx.send(f"Leave/Goodbye messages ab **{'ON' if gcfg.goodbye_enabled else 'OFF'}** hain.")

    @commands.hybrid_command(name="testwelcome", description="Apne profile par live Welcome card preview dekho")
    @commands.has_permissions(manage_guild=True)
    async def testwelcome(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        await ctx.defer()
        gcfg = self.store.get(ctx.guild.id)
        ch = self._find_welcome_ch(ctx.guild, gcfg) or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if not ch:
            await ctx.send("Pehle `/setwelcome #channel` set karo.")
            return
        await self._send_card(ctx.author, ch, gcfg, kind="welcome")
        await ctx.send(f"Test welcome {ch.mention} mein bhej diya!", ephemeral=(ch.id == ctx.channel.id))

    @commands.hybrid_command(name="testgoodbye", description="Apne profile par live Leave/Goodbye card preview dekho")
    @commands.has_permissions(manage_guild=True)
    async def testgoodbye(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        await ctx.defer()
        gcfg = self.store.get(ctx.guild.id)
        ch = self._find_goodbye_ch(ctx.guild, gcfg) or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if not ch:
            await ctx.send("Pehle `/setgoodbye #channel` set karo.")
            return
        await self._send_card(ctx.author, ch, gcfg, kind="goodbye")
        await ctx.send(f"Test goodbye {ch.mention} mein bhej diya!", ephemeral=(ch.id == ctx.channel.id))

    @commands.hybrid_command(name="welcomeconfig", aliases=["wconfig"], description="Current Lord Welcome settings dekho")
    async def welcomeconfig(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        gcfg = self.store.get(ctx.guild.id)
        wch = self._find_welcome_ch(ctx.guild, gcfg)
        gch = self._find_goodbye_ch(ctx.guild, gcfg) if gcfg.goodbye_enabled else None
        role = ctx.guild.get_role(gcfg.auto_role_id) if gcfg.auto_role_id else None
        embed = discord.Embed(title=f"{self.bot_name} — Settings", color=gcfg.color)
        embed.add_field(name="Welcome Channel", value=wch.mention if wch else "Not set", inline=True)
        embed.add_field(name="Goodbye/Leave", value=f"ON ({gch.mention})" if gch else ("ON (auto)" if gcfg.goodbye_enabled else "Off"), inline=True)
        embed.add_field(name="Mode", value=f"`{gcfg.mode}`", inline=True)
        embed.add_field(name="Welcome Image", value="Custom set" if (gcfg.image_filename or gcfg.image_url or gcfg.image_source_message_id) else "Cyber City Storm (#1 GIF)", inline=True)
        embed.add_field(name="Goodbye Image", value="Custom set" if (gcfg.goodbye_image_filename or gcfg.goodbye_image_url or gcfg.goodbye_image_source_message_id) else "Void Army Portal (#10 GIF)", inline=True)
        embed.add_field(name="Auto-Role", value=role.mention if role else "Off", inline=True)
        if self._icon():
            embed.set_thumbnail(url=self._icon())
        embed.set_footer(text=self.bot_name, icon_url=self._icon())
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="help", description="Lord Welcome ke saare commands dekho")
    async def help_cmd(self, ctx: commands.Context) -> None:
        embed = discord.Embed(title=f"{self.bot_name} — Commands", color=self.embed_color)
        embed.add_field(
            name="Welcome Setup",
            value=(
                "`/setwelcome <#channel>` — Welcome tab/channel set karo\n"
                "`/setimage [image] [url]` — Custom welcome image ya GIF lagao\n"
                "`/resetimage` — Default neon theme wapas lagao\n"
                "`/setmode <card|banner>` — Avatar overlay card ya raw banner/GIF\n"
                "`/testwelcome` — Live welcome card preview"
            ),
            inline=False,
        )
        embed.add_field(
            name="Leave / Goodbye",
            value=(
                "`/setgoodbye [#channel]` — Leave channel set karo (default: #goodbye ya #welcome)\n"
                "`/togglegoodbye <on|off>` — Leave cards ON/OFF karo\n"
                "`/setgoodbyeimage [image] [url]` — Custom leave image/GIF lagao\n"
                "`/setgoodbyemessage <text>` — Leave text customize karo\n"
                "`/testgoodbye` — Live leave card preview"
            ),
            inline=False,
        )
        embed.add_field(
            name="Text & Extras",
            value=(
                "`/settitle <text>` | `/setmessage <text>` | `/setcolor <#HEX>`\n"
                "`/setautorole [@role]` | `/welcomeconfig`"
            ),
            inline=False,
        )
        if self._icon():
            embed.set_thumbnail(url=self._icon())
        embed.set_footer(text=self.bot_name, icon_url=self._icon())
        await ctx.send(embed=embed)


class WelcomeBot(commands.Bot):
    def __init__(self, bot_name: str = "Lord Welcome", command_prefix: str = "!", embed_color: int = 0x38BDF8):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or(command_prefix),
            intents=intents,
            help_command=None,
            max_messages=100,
        )
        self.bot_name = bot_name
        self.embed_color = embed_color
        self.store = ConfigStore()

    async def setup_hook(self) -> None:
        await self.add_cog(WelcomeCog(self, self.bot_name, "!", self.embed_color, self.store))
        synced = await self.tree.sync()
        logger.info("[%s] Synced %d slash command(s).", self.bot_name, len(synced))

    async def on_ready(self) -> None:
        activity = discord.Activity(type=discord.ActivityType.watching, name="new members | /help")
        await self.change_presence(status=discord.Status.online, activity=activity)
        logger.info(
            "%s is online! Logged in as %s (ID: %s) | Servers: %d",
            self.bot_name,
            self.user,
            self.user.id if self.user else "N/A",
            len(self.guilds),
        )

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Ye command sirf Server Admin / Manage Server wale chala sakte hain.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(f"Galat input: `{error}`")
            return
        logger.exception("[%s] Unhandled command error: %s", self.bot_name, error)


async def run_welcome_bot(
    *, token: str, bot_name: str = "Lord Welcome", command_prefix: str = "!", embed_color: int = 0x38BDF8
) -> None:
    bot = WelcomeBot(bot_name=bot_name, command_prefix=command_prefix, embed_color=embed_color)
    async with bot:
        await bot.start(token)
