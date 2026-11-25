from __future__ import annotations

import hashlib
import logging
import os
import sys
from typing import Optional

from aiohttp import web
import discord
from discord.ext import commands

from config import BASE_DIR, BotConfig
from music import MusicCog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("music_bot")


class MusicBot(commands.Bot):
    def __init__(self, config: BotConfig):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.command_prefix),
            intents=intents,
            help_command=None,
            max_messages=100,
        )
        self.config = config
        self._profile_synced = False
        self._web_runner: Optional[web.AppRunner] = None

    async def _start_health_server(self) -> None:
        """Start a lightweight HTTP health endpoint when hosted on cloud platforms that provide PORT."""
        port_raw = os.getenv("PORT", "").strip()
        if not port_raw:
            return
        try:
            port = int(port_raw)
        except ValueError:
            logger.warning("Invalid PORT value '%s'; skipping health server.", port_raw)
            return

        app = web.Application()

        async def _health(_request: web.Request) -> web.Response:
            return web.Response(text=f"{self.config.bot_name} is online")

        app.router.add_get("/", _health)
        app.router.add_get("/health", _health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        self._web_runner = runner
        logger.info("Health server listening on 0.0.0.0:%d", port)

    async def setup_hook(self) -> None:
        await self._start_health_server()
        await self.add_cog(MusicCog(self, self.config))
        synced = await self.tree.sync()
        logger.info("Synced %d slash command(s).", len(synced))

    async def close(self) -> None:
        if self._web_runner is not None:
            await self._web_runner.cleanup()
            self._web_runner = None
        await super().close()

    async def _sync_bot_profile(self) -> None:
        """Apply bot icon (assets/bot_icon.png) and bot name once, avoiding rate limits."""
        if self._profile_synced or not self.user:
            return
        self._profile_synced = True

        icon_path = self.config.icon_path
        force_avatar = os.getenv("SYNC_AVATAR_ON_START", "").strip().lower() in {"1", "true", "yes"}
        if icon_path.is_file() and (self.user.avatar is None or force_avatar):
            icon_bytes = icon_path.read_bytes()
            digest = hashlib.sha256(icon_bytes).hexdigest()
            marker = BASE_DIR / ".avatar_synced.sha256"
            prev_digest = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
            if prev_digest != digest:
                try:
                    await self.user.edit(avatar=icon_bytes)
                    marker.write_text(digest, encoding="utf-8")
                    logger.info("Updated Discord bot avatar from %s", icon_path.name)
                except discord.HTTPException as exc:
                    logger.warning("Could not auto-update bot avatar (can upload manually in portal): %s", exc)

        if self.user.name != self.config.bot_name:
            try:
                await self.user.edit(username=self.config.bot_name)
                logger.info("Updated Discord bot username to '%s'", self.config.bot_name)
            except discord.HTTPException as exc:
                logger.warning("Could not auto-update bot username (set it in Developer Portal): %s", exc)

    async def on_ready(self) -> None:
        await self._sync_bot_profile()
        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name=f"/play | {self.config.command_prefix}play",
        )
        await self.change_presence(status=discord.Status.online, activity=activity)
        logger.info(
            "%s is online! Logged in as %s (ID: %s) | Servers: %d",
            self.config.bot_name,
            self.user,
            self.user.id if self.user else "N/A",
            len(self.guilds),
        )

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"Argument missing hai. Example: `{self.config.command_prefix}play Kesariya` ya `/play`"
            )
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(f"Galat input: `{error}`")
            return
        logger.exception("Unhandled command error: %s", error)
        await ctx.send("Command chalate waqt kuch error aa gaya. Console logs check karo.")


def main() -> None:
    config = BotConfig.from_env()
    if not config.token or config.token == "YOUR_BOT_TOKEN_HERE":
        logger.error(
            "DISCORD_TOKEN missing hai! `.env` file open karke apna Discord Bot Token paste karo."
        )
        sys.exit(1)

    bot = MusicBot(config)
    try:
        bot.run(config.token, log_handler=None)
    except discord.LoginFailure:
        logger.error("Invalid DISCORD_TOKEN! Discord Developer Portal se sahi token copy karo.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        logger.error(
            "Message Content Intent enabled nahi hai! Discord Developer Portal -> Bot -> "
            "Privileged Gateway Intents -> 'Message Content Intent' ON karo."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
