"""Lord Designer Cog: /restyle, /undorestyle, /addmodule, /divider (animated GIF), /addemojis, /themes."""
from __future__ import annotations

import asyncio
import colorsys
import io
import json
import logging
import math
from pathlib import Path
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFilter

from design_themes import (
    MODULES,
    THEMES,
    Theme,
    clean_words,
    style_category,
    style_channel,
)

logger = logging.getLogger("lord_design")

BASE_DIR = Path(__file__).resolve().parent
UNDO_FILE = BASE_DIR / "welcome_data" / "restyle_undo.json"

ThemeChoice = Literal[
    "inferno_gamer",
    "lord_neon",
    "royal_empire",
    "cyber_hacker",
    "galaxy_aesthetic",
    "anime_sakura",
    "dark_shadow",
    "esports_clean",
]

ModuleChoice = Literal[
    "gaming_hub",
    "support_desk",
    "events_giveaways",
    "vc_lounge",
    "staff_zone",
    "information",
]

DividerStyle = Literal["fire", "neon", "rgb"]


def _is_plain_channel_name(name: str) -> bool:
    """Return True if a channel has no emojis or fancy decorations yet."""
    stripped = name.strip()
    if not stripped:
        return True
    # Plain ASCII letters, digits, hyphens, underscores, spaces only
    return all(ord(ch) < 128 for ch in stripped)


# ---------------- Pure-Pillow Animated GIF Generators ----------------

def render_animated_divider_gif(style: DividerStyle = "fire") -> bytes:
    """Render a crisp 760x28 animated neon laser divider GIF in memory."""
    w, h, n_frames = 760, 28, 20
    frames: list[Image.Image] = []

    for f in range(n_frames):
        phase = 2 * math.pi * f / n_frames
        t = f / n_frames
        base = Image.new("RGBA", (w, h), (11, 14, 22, 255))
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        core = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        cd = ImageDraw.Draw(core)

        cy = h // 2
        if style == "rgb":
            segs = 38
            step = w / segs
            for i in range(segs):
                hue = (i / segs + t) % 1.0
                rgb = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.95, 1.0))
                x1, x2 = int(i * step), int((i + 1) * step) + 1
                y1 = int(cy + math.sin(phase + i * 0.35) * 3)
                y2 = int(cy + math.sin(phase + (i + 1) * 0.35) * 3)
                gd.line([(x1, y1), (x2, y2)], fill=(*rgb, 240), width=7)
                cd.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, 230), width=2)
        elif style == "neon":
            pts = [(x, int(cy + math.sin(x * 0.025 + phase) * 3.5)) for x in range(12, w - 12, 16)]
            gd.line(pts, fill=(56, 189, 248, 240), width=8)
            gd.line(pts[len(pts) // 2 :], fill=(168, 85, 247, 230), width=8)
            cd.line(pts, fill=(235, 250, 255, 255), width=2)
        else:  # "fire" — Inferno Gamer default!
            pts = [
                (x, int(cy + math.sin(x * 0.032 + phase) * 4.5 + math.cos(x * 0.06 - phase) * 2))
                for x in range(12, w - 12, 14)
            ]
            gd.line(pts, fill=(249, 115, 22, 245), width=8)
            cd.line(pts, fill=(254, 240, 138, 255), width=2)

        # Scanning neon energy orb
        orb_x = int(20 + t * (w - 40))
        orb_col = (250, 204, 21) if style == "fire" else ((255, 255, 255) if style == "rgb" else (56, 189, 248))
        gd.ellipse([orb_x - 22, cy - 8, orb_x + 22, cy + 8], fill=(*orb_col, 255))
        cd.ellipse([orb_x - 8, cy - 4, orb_x + 8, cy + 4], fill=(255, 255, 255, 255))

        out = Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(5)))
        out = Image.alpha_composite(out, core).convert("RGB")
        frames.append(out.quantize(colors=96, method=Image.Quantize.FASTOCTREE))

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=55,
        loop=0,
        optimize=True,
    )
    return buf.getvalue()


def _render_emoji_frames(kind: str) -> bytes:
    """Render a 128x128 animated neon gaming GIF emoji (<180 KB for Discord's 256 KB limit)."""
    s, n_frames = 128, 16
    frames: list[Image.Image] = []

    for f in range(n_frames):
        phase = 2 * math.pi * f / n_frames
        t = f / n_frames
        pulse = 0.5 + 0.5 * math.sin(phase)
        img = Image.new("RGBA", (s, s), (12, 14, 22, 255))
        glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        core = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        cd = ImageDraw.Draw(core)
        cx, cy = s // 2, s // 2

        if kind == "lord_fire":
            # Pulsing Inferno Neon Flame
            dy = int(math.sin(phase) * 5)
            outer_pts = [(cx, 18 + dy), (94, 58), (88, 96), (64, 112), (40, 96), (34, 58)]
            inner_pts = [(cx, 44 + dy), (78, 72), (72, 98), (64, 106), (56, 98), (50, 72)]
            gd.polygon(outer_pts, fill=(249, 115, 22, 255))
            gd.ellipse([24, 34, 104, 114], outline=(239, 68, 68, int(180 + 70 * pulse)), width=5)
            cd.polygon(outer_pts, fill=(249, 115, 22, 255))
            cd.polygon(inner_pts, fill=(254, 240, 138, 255))
        elif kind == "lord_bolt":
            # Electric Cyan Lightning Bolt
            bolt = [(72, 14), (34, 68), (60, 68), (52, 114), (94, 58), (68, 58)]
            gd.polygon(bolt, fill=(56, 189, 248, 255))
            r = int(48 + pulse * 6)
            gd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(168, 85, 247, 230), width=5)
            cd.polygon(bolt, fill=(224, 247, 255, 255))
        elif kind == "lord_star":
            # Spinning RGB Neon Star
            rgb = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(t, 0.92, 1.0))
            pts = []
            for i in range(8):
                ang = phase + i * (math.pi / 4)
                rad = 46 if i % 2 == 0 else 18
                pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
            gd.polygon(pts, fill=(*rgb, 255))
            cd.polygon(pts, fill=(255, 255, 255, 245))
        elif kind == "lord_crown":
            # Glowing Gold/Orange Royal Crown
            dy = int(math.sin(phase) * 4)
            crown = [(22, 92 + dy), (28, 42 + dy), (48, 66 + dy), (64, 32 + dy), (80, 66 + dy), (100, 42 + dy), (106, 92 + dy)]
            gd.polygon(crown, fill=(251, 191, 36, 255))
            cd.polygon(crown, fill=(254, 243, 199, 255))
            cd.rectangle([22, 96 + dy, 106, 106 + dy], fill=(249, 115, 22, 255))
        elif kind == "lord_eq":
            # Animated Neon Equalizer Bars
            cols = [(56, 189, 248), (168, 85, 247), (236, 72, 153), (249, 115, 22), (250, 204, 21)]
            for i, col in enumerate(cols):
                amp = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(phase * 2 + i * 1.1))
                bh = int(18 + amp * 82)
                x = 14 + i * 21
                gd.rounded_rectangle([x, 112 - bh, x + 15, 112], radius=4, fill=(*col, 255))
                cd.rounded_rectangle([x + 2, 110 - bh, x + 13, 110], radius=3, fill=(*col, 255))
        else:  # "lord_ok"
            # Neon Green Verified Checkmark
            r = int(46 + pulse * 4)
            gd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(34, 197, 94, 255), width=8)
            chk = [(38, 66), (56, 86), (92, 44)]
            gd.line(chk, fill=(34, 197, 94, 255), width=12)
            cd.line(chk, fill=(220, 255, 232, 255), width=6)

        out = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(7)))
        out = Image.alpha_composite(out, core).convert("RGB")
        frames.append(out.quantize(colors=96, method=Image.Quantize.FASTOCTREE))

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=65,
        loop=0,
        optimize=True,
    )
    return buf.getvalue()


EMOJI_NAMES = ["lord_fire", "lord_bolt", "lord_star", "lord_crown", "lord_eq", "lord_ok"]


class DesignCog(commands.Cog):
    def __init__(self, bot: commands.Bot, bot_name: str = "Lord Welcome"):
        self.bot = bot
        self.bot_name = bot_name

    def _icon(self) -> Optional[str]:
        return self.bot.user.display_avatar.url if self.bot.user else None

    @staticmethod
    def _save_undo(guild_id: int, snapshot: dict[str, str]) -> None:
        UNDO_FILE.parent.mkdir(parents=True, exist_ok=True)
        all_data: dict[str, dict[str, str]] = {}
        if UNDO_FILE.is_file():
            try:
                all_data = json.loads(UNDO_FILE.read_text(encoding="utf-8"))
            except Exception:
                all_data = {}
        all_data[str(guild_id)] = snapshot
        UNDO_FILE.write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _load_undo(guild_id: int) -> Optional[dict[str, str]]:
        if not UNDO_FILE.is_file():
            return None
        try:
            all_data = json.loads(UNDO_FILE.read_text(encoding="utf-8"))
            return all_data.get(str(guild_id))
        except Exception:
            return None

    @commands.hybrid_command(
        name="themes",
        description="Saare 8 built-in gaming themes aur 6 ready-made modules dekho",
    )
    async def themes_cmd(self, ctx: commands.Context) -> None:
        theme_lines = []
        for k, t in THEMES.items():
            default_tag = " **(Default)**" if k == "inferno_gamer" else ""
            sample = style_channel("free-loot", t, is_voice=False)
            theme_lines.append(f"{t.icon} **`{t.name}`**{default_tag} — `{sample}`")

        mod_lines = [
            f"• **`{mk}`** — {mv['title']} ({len(mv['channels'])} channels)"
            for mk, mv in MODULES.items()
        ]
        embed = discord.Embed(
            title=f"🔥 {self.bot_name} — Server Design Templates",
            description="Apne server ko 1 command mein **Inferno Gamer** (ya kisi bhi theme) mein design karo!",
            color=THEMES["inferno_gamer"].color,
        )
        embed.add_field(name="8 Built-in Themes (/restyle)", value="\n".join(theme_lines), inline=False)
        embed.add_field(name="6 Ready-Made Modules (/addmodule)", value="\n".join(mod_lines), inline=False)
        embed.add_field(
            name="Animated Extras",
            value=(
                "`/restyle [theme] [scope]` — Channels ko emoji + fancy font mein style karo\n"
                "`/undorestyle` — Purane channel names wapas lao\n"
                "`/addmodule <module> [theme]` — Ready-made gaming category add karo\n"
                "`/divider [fire|neon|rgb]` — Animated neon laser divider GIF post karo\n"
                "`/addemojis` — 6 animated neon gaming emojis server mein upload karo"
            ),
            inline=False,
        )
        if self._icon():
            embed.set_thumbnail(url=self._icon())
        embed.set_footer(text=self.bot_name, icon_url=self._icon())
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="restyle",
        description="Server ke channels & categories ko Inferno Gamer (ya kisi bhi theme) mein design karo",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        theme="Design theme chuno (default: Inferno Gamer)",
        scope="all = pura server | plain_only = sirf plain channels | category = sirf ek category",
        category="Agar scope=category chuna ho toh category select karo",
    )
    async def restyle(
        self,
        ctx: commands.Context,
        theme: ThemeChoice = "inferno_gamer",
        scope: Literal["all", "plain_only", "category"] = "all",
        category: Optional[discord.CategoryChannel] = None,
    ) -> None:
        if not ctx.guild:
            return
        if not ctx.guild.me.guild_permissions.manage_channels:
            await ctx.send(
                "Mujhe **Manage Channels** permission chahiye!\n"
                "Discord mein **Server Settings -> Roles -> Lord Hax Welcome** mein jaake **Manage Channels** ON kar do, phir `/restyle` chalao."
            )
            return
        if scope == "category" and category is None:
            await ctx.send("Jab `scope` = `category` ho toh `category` option mein apni category select karo!")
            return

        await ctx.defer()
        chosen: Theme = THEMES[theme]
        targets: list[discord.abc.GuildChannel] = []

        if scope == "category" and category is not None:
            targets.append(category)
            targets.extend(category.channels)
        else:
            for cat in ctx.guild.categories:
                if scope == "all":
                    targets.append(cat)
            for ch in ctx.guild.channels:
                if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
                    if scope == "plain_only" and not _is_plain_channel_name(ch.name):
                        continue
                    targets.append(ch)

        snapshot: dict[str, str] = {}
        renamed_cats = 0
        renamed_chans = 0
        skipped = 0

        for ch in targets:
            if isinstance(ch, discord.CategoryChannel):
                new_name = style_category(ch.name, chosen)
            elif isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                new_name = style_channel(ch.name, chosen, is_voice=True)
            else:
                new_name = style_channel(ch.name, chosen, is_voice=False)

            if not new_name or new_name == ch.name:
                skipped += 1
                continue

            snapshot[str(ch.id)] = ch.name
            try:
                await ch.edit(name=new_name, reason=f"{self.bot_name} /restyle ({chosen.name})")
                if isinstance(ch, discord.CategoryChannel):
                    renamed_cats += 1
                else:
                    renamed_chans += 1
                await asyncio.sleep(0.45)
            except discord.HTTPException as exc:
                logger.warning("Could not rename %s (%s): %s", ch.name, ch.id, exc)
                skipped += 1

        if snapshot:
            self._save_undo(ctx.guild.id, snapshot)

        embed = discord.Embed(
            title=f"{chosen.icon} Restyle Complete — {chosen.name}",
            description=(
                f"**{renamed_cats}** categories aur **{renamed_chans}** channels ko **{chosen.name}** theme mein update kar diya!\n"
                f"*(Skipped/unchanged: {skipped})*\n\n"
                "Agar kabhi purane names wapas chahiye hon toh `/undorestyle` chala dena."
            ),
            color=chosen.color,
        )
        embed.set_footer(text=self.bot_name, icon_url=self._icon())
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="undorestyle",
        description="Last /restyle se pehle wale purane channel names wapas lao",
    )
    @commands.has_permissions(manage_guild=True)
    async def undorestyle(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        if not ctx.guild.me.guild_permissions.manage_channels:
            await ctx.send("Mujhe **Manage Channels** permission chahiye!")
            return
        snapshot = self._load_undo(ctx.guild.id)
        if not snapshot:
            await ctx.send("Koi previous `/restyle` backup nahi mila.")
            return

        await ctx.defer()
        restored = 0
        for ch_id_str, old_name in snapshot.items():
            ch = ctx.guild.get_channel(int(ch_id_str))
            if ch and ch.name != old_name:
                try:
                    await ch.edit(name=old_name, reason=f"{self.bot_name} /undorestyle")
                    restored += 1
                    await asyncio.sleep(0.45)
                except discord.HTTPException:
                    pass
        await ctx.send(f"Done! **{restored}** channels/categories ke purane names wapas restore ho gaye.")

    @commands.hybrid_command(
        name="addmodule",
        description="Ready-made gaming module add karo (bina purane channels delete kiye)",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        module="Kaunsa module add karna hai",
        theme="Kis theme mein banana hai (default: Inferno Gamer)",
    )
    async def addmodule(
        self,
        ctx: commands.Context,
        module: ModuleChoice,
        theme: ThemeChoice = "inferno_gamer",
    ) -> None:
        if not ctx.guild:
            return
        if not ctx.guild.me.guild_permissions.manage_channels:
            await ctx.send(
                "Mujhe **Manage Channels** permission chahiye! "
                "Server Settings -> Roles -> Lord Hax Welcome mein **Manage Channels** ON karo."
            )
            return

        await ctx.defer()
        mod = MODULES[module]
        chosen = THEMES[theme]

        overwrites = None
        if mod.get("private"):
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                ctx.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }

        cat_name = style_category(mod["category"], chosen) or mod["category"]
        cat = await ctx.guild.create_category(
            name=cat_name,
            overwrites=overwrites,
            reason=f"{self.bot_name} /addmodule ({module})",
        )

        created: list[str] = []
        for kind, raw_name in mod["channels"]:
            ch_name = style_channel(raw_name, chosen, is_voice=(kind == "voice")) or raw_name
            if kind == "voice":
                c = await ctx.guild.create_voice_channel(name=ch_name, category=cat)
                created.append(f"🔊 {c.name}")
            else:
                c = await ctx.guild.create_text_channel(name=ch_name, category=cat)
                created.append(f"{c.mention}")
            await asyncio.sleep(0.35)

        embed = discord.Embed(
            title=f"{chosen.icon} Module Added — {mod['title']}",
            description=f"**Category:** `{cat.name}`\n**Channels:**\n" + "\n".join(created),
            color=chosen.color,
        )
        embed.set_footer(text=self.bot_name, icon_url=self._icon())
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="divider",
        description="Channel mein animated neon laser divider GIF post karo",
    )
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(style="fire = Inferno Gamer (default) | neon = Cyan-Purple | rgb = Rainbow")
    async def divider(self, ctx: commands.Context, style: DividerStyle = "fire") -> None:
        await ctx.defer()
        gif_bytes = await asyncio.to_thread(render_animated_divider_gif, style)
        await ctx.send(file=discord.File(io.BytesIO(gif_bytes), filename=f"lord_{style}_divider.gif"))

    @commands.hybrid_command(
        name="addemojis",
        description="6 animated neon gaming GIF emojis apne server mein upload karo",
    )
    @commands.has_permissions(manage_guild=True)
    async def addemojis(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        perms = ctx.guild.me.guild_permissions
        if not (getattr(perms, "manage_expressions", False) or getattr(perms, "create_expressions", False) or perms.administrator):
            await ctx.send(
                "Mujhe **Create Expressions / Manage Expressions** permission chahiye!\n"
                "Server Settings -> Roles -> Lord Hax Welcome mein ye permission ON karo, phir `/addemojis` chalao."
            )
            return

        await ctx.defer()
        existing = {e.name for e in ctx.guild.emojis}
        added: list[str] = []
        skipped: list[str] = []

        for ename in EMOJI_NAMES:
            if ename in existing:
                skipped.append(f"`:{ename}:`")
                continue
            gif_bytes = await asyncio.to_thread(_render_emoji_frames, ename)
            try:
                em = await ctx.guild.create_custom_emoji(
                    name=ename,
                    image=gif_bytes,
                    reason=f"{self.bot_name} /addemojis neon pack",
                )
                added.append(f"{em} `:{em.name}:`")
                await asyncio.sleep(0.5)
            except discord.HTTPException as exc:
                logger.warning("Emoji %s upload failed: %s", ename, exc)
                skipped.append(f"`:{ename}:` ({exc.status})")

        msg = ""
        if added:
            msg += "**Animated Neon Emojis Uploaded:**\n" + "  ".join(added) + "\n"
        if skipped:
            msg += f"\n*Already existed / skipped:* {', '.join(skipped)}"
        await ctx.send(msg or "Koi naya emoji upload nahi ho paya (server emoji limit full ho sakti hai).")
