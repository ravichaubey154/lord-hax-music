from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import re
import shutil
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Literal, Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from config import BASE_DIR, BotConfig

logger = logging.getLogger("music_bot")

URL_REGEX = re.compile(r"^https?://", re.IGNORECASE)

FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"
)
FFMPEG_OPTIONS = "-vn"


def _resolve_cookiefile() -> Optional[str]:
    """Support optional YouTube cookies (cookies.txt or YTDLP_COOKIES_B64 env) for cloud IPs."""
    b64 = os.getenv("YTDLP_COOKIES_B64", "").strip()
    if b64:
        try:
            decoded = base64.b64decode(b64)
            tmp_path = Path(tempfile.gettempdir()) / "lord_hax_yt_cookies.txt"
            tmp_path.write_bytes(decoded)
            return str(tmp_path)
        except Exception as exc:
            logger.warning("Failed to decode YTDLP_COOKIES_B64: %s", exc)
    local_cookies = BASE_DIR / "cookies.txt"
    if local_cookies.is_file():
        return str(local_cookies)
    return None


YTDL_BASE_OPTIONS: dict = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "geo_bypass": True,
}

_COOKIE_FILE = _resolve_cookiefile()
if _COOKIE_FILE:
    YTDL_BASE_OPTIONS["cookiefile"] = _COOKIE_FILE
    logger.info("Loaded yt-dlp cookies file: %s", _COOKIE_FILE)

YTDL_PLAYLIST_OPTIONS: dict = {
    **YTDL_BASE_OPTIONS,
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
}


def get_ffmpeg_path() -> str:
    """Return system ffmpeg if installed, otherwise fallback to bundled imageio-ffmpeg."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "FFmpeg not found. Install FFmpeg or `pip install imageio-ffmpeg`."
        ) from exc


def format_duration(seconds: Optional[int | float]) -> str:
    if seconds is None:
        return "Live"
    total = int(seconds)
    if total <= 0:
        return "Live"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@dataclass
class Track:
    title: str
    webpage_url: str
    requester_id: int
    requester_name: str
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    stream_url: Optional[str] = None
    http_headers: dict[str, str] = field(default_factory=dict)

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)


class YTDLPExtractor:
    """Async wrapper around yt-dlp for searching and resolving YouTube audio streams."""

    @staticmethod
    def _is_url(query: str) -> bool:
        return bool(URL_REGEX.match(query.strip()))

    @classmethod
    async def search_tracks(
        cls,
        query: str,
        requester: discord.abc.User,
        max_playlist_items: int = 50,
    ) -> list[Track]:
        return await asyncio.to_thread(
            cls._search_tracks_sync, query, requester.id, requester.display_name, max_playlist_items
        )

    @classmethod
    def _search_tracks_sync(
        cls,
        query: str,
        requester_id: int,
        requester_name: str,
        max_playlist_items: int,
    ) -> list[Track]:
        cleaned = query.strip()
        is_url = cls._is_url(cleaned)
        search_target = cleaned if is_url else f"ytsearch1:{cleaned}"

        # Use flat extraction for playlist URLs so large playlists queue quickly
        opts = dict(YTDL_PLAYLIST_OPTIONS if is_url else YTDL_BASE_OPTIONS)
        if not is_url:
            opts["noplaylist"] = True

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_target, download=False)

        if not info:
            return []

        entries = info.get("entries")
        if entries is not None:
            raw_items = [entry for entry in entries if entry]
            if not is_url:
                raw_items = raw_items[:1]
            else:
                raw_items = raw_items[:max_playlist_items]
        else:
            raw_items = [info]

        tracks: list[Track] = []
        for item in raw_items:
            webpage_url = item.get("webpage_url") or item.get("url")
            if not webpage_url:
                continue
            if not URL_REGEX.match(webpage_url):
                # Flat playlist entries often store the 11-char video ID in `url`
                webpage_url = f"https://www.youtube.com/watch?v={webpage_url}"

            # Only store direct stream_url if this was a full extraction (not flat playlist)
            stream_url = item.get("url") if item.get("acodec") or item.get("vcodec") else None
            if stream_url and stream_url == webpage_url:
                stream_url = None

            thumbnail = item.get("thumbnail")
            if not thumbnail and item.get("thumbnails"):
                thumbnail = item["thumbnails"][-1].get("url")

            tracks.append(
                Track(
                    title=item.get("title") or "Unknown Title",
                    webpage_url=webpage_url,
                    requester_id=requester_id,
                    requester_name=requester_name,
                    duration=item.get("duration"),
                    thumbnail=thumbnail,
                    uploader=item.get("uploader") or item.get("channel"),
                    stream_url=stream_url,
                    http_headers=dict(item.get("http_headers") or {}),
                )
            )

        return tracks

    @classmethod
    async def resolve_stream(cls, track: Track) -> Track:
        """Fetch a fresh playable audio stream URL right before starting playback."""
        return await asyncio.to_thread(cls._resolve_stream_sync, track)

    @classmethod
    def _resolve_stream_sync(cls, track: Track) -> Track:
        opts = {
            **YTDL_BASE_OPTIONS,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(track.webpage_url, download=False)

        if not info:
            raise RuntimeError(f"Could not extract stream for: {track.title}")

        if "entries" in info and info["entries"]:
            info = next((e for e in info["entries"] if e), None)
            if not info:
                raise RuntimeError(f"No playable stream found for: {track.title}")

        stream_url = info.get("url")
        if not stream_url:
            raise RuntimeError(f"No audio stream URL returned for: {track.title}")

        track.stream_url = stream_url
        track.title = info.get("title") or track.title
        track.duration = info.get("duration") or track.duration
        track.uploader = info.get("uploader") or info.get("channel") or track.uploader
        track.thumbnail = info.get("thumbnail") or track.thumbnail
        track.http_headers = dict(info.get("http_headers") or {})
        return track


class MusicControlsView(discord.ui.View):
    """Interactive buttons attached to the Now Playing message."""

    def __init__(self, player: "GuildPlayer"):
        super().__init__(timeout=None)
        self.player = player
        self._sync_labels()

    def _sync_labels(self) -> None:
        vc = self.player.voice_client
        is_paused = bool(vc and vc.is_paused())
        self.pause_resume_btn.label = "Resume" if is_paused else "Pause"
        self.pause_resume_btn.emoji = "▶️" if is_paused else "⏸️"

        loop_labels = {
            "off": "Loop: Off",
            "song": "Loop: Song",
            "queue": "Loop: Queue",
        }
        self.loop_btn.label = loop_labels[self.player.loop_mode]
        self.loop_btn.style = (
            discord.ButtonStyle.success
            if self.player.loop_mode != "off"
            else discord.ButtonStyle.secondary
        )

    async def _validate_user_vc(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        vc = self.player.voice_client
        if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                "Pehle voice channel join karo, phir buttons use kar sakte ho.",
                ephemeral=True,
            )
            return False
        if vc and vc.channel and member.voice.channel.id != vc.channel.id:
            await interaction.response.send_message(
                f"Tumhe {vc.channel.mention} voice channel mein hona chahiye.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.primary)
    async def pause_resume_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not await self._validate_user_vc(interaction):
            return
        vc = self.player.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            await interaction.response.send_message("Abhi koi song play nahi ho raha.", ephemeral=True)
            return
        if vc.is_paused():
            vc.resume()
            msg = "Resumed playback."
        else:
            vc.pause()
            msg = "Paused playback."
        self._sync_labels()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not await self._validate_user_vc(interaction):
            return
        vc = self.player.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            await interaction.response.send_message("Skip karne ke liye koi song nahi chal raha.", ephemeral=True)
            return
        self.player.skip_requested = True
        vc.stop()
        await interaction.response.send_message("Skipped to next track.", ephemeral=True)

    @discord.ui.button(label="Loop: Off", emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not await self._validate_user_vc(interaction):
            return
        cycle: dict[Literal["off", "song", "queue"], Literal["off", "song", "queue"]] = {
            "off": "song",
            "song": "queue",
            "queue": "off",
        }
        self.player.loop_mode = cycle[self.player.loop_mode]
        self._sync_labels()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Shuffle", emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not await self._validate_user_vc(interaction):
            return
        if len(self.player.queue) < 2:
            await interaction.response.send_message(
                "Shuffle karne ke liye queue mein kam se kam 2 songs chahiye.",
                ephemeral=True,
            )
            return
        self.player.shuffle()
        await interaction.response.send_message("Queue shuffled!", ephemeral=True)

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not await self._validate_user_vc(interaction):
            return
        await interaction.response.send_message("Stopped music and cleared queue.", ephemeral=True)
        await self.player.stop_and_disconnect()


class GuildPlayer:
    """Manages audio playback, queue, loop mode, volume, and auto-disconnect per Discord server."""

    def __init__(self, bot: commands.Bot, guild: discord.Guild, config: BotConfig, ffmpeg_path: str):
        self.bot = bot
        self.guild = guild
        self.config = config
        self.ffmpeg_path = ffmpeg_path

        self.queue: Deque[Track] = deque()
        self.current: Optional[Track] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self.loop_mode: Literal["off", "song", "queue"] = "off"
        self.volume: float = 0.75
        self.skip_requested: bool = False

        self._lock = asyncio.Lock()
        self._idle_task: Optional[asyncio.Task] = None
        self._now_playing_msg: Optional[discord.Message] = None

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        vc = self.guild.voice_client
        return vc if isinstance(vc, discord.VoiceClient) else None

    def shuffle(self) -> None:
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)

    def _cancel_idle_timer(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    def _start_idle_timer(self) -> None:
        self._cancel_idle_timer()

        async def _auto_disconnect() -> None:
            try:
                await asyncio.sleep(self.config.inactivity_timeout)
                vc = self.voice_client
                if vc and vc.is_connected() and not vc.is_playing() and not vc.is_paused():
                    await self.stop_and_disconnect(notify=True)
            except asyncio.CancelledError:
                pass

        self._idle_task = self.bot.loop.create_task(_auto_disconnect())

    async def _clear_old_controls(self) -> None:
        if self._now_playing_msg is not None:
            try:
                await self._now_playing_msg.edit(view=None)
            except discord.HTTPException:
                pass
            self._now_playing_msg = None

    def _bot_icon_url(self) -> Optional[str]:
        return self.bot.user.display_avatar.url if self.bot.user else None

    def build_now_playing_embed(self, track: Track) -> discord.Embed:
        embed = discord.Embed(
            title="Now Playing",
            description=f"**[{track.title}]({track.webpage_url})**",
            color=self.config.embed_color,
        )
        embed.add_field(name="Duration", value=track.duration_text, inline=True)
        embed.add_field(name="Volume", value=f"{int(self.volume * 100)}%", inline=True)
        embed.add_field(name="Loop", value=self.loop_mode.capitalize(), inline=True)
        if track.uploader:
            embed.add_field(name="Channel", value=track.uploader, inline=True)
        embed.add_field(name="Requested by", value=f"<@{track.requester_id}>", inline=True)
        embed.add_field(name="Up Next", value=f"{len(self.queue)} song(s)", inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(text=self.config.bot_name, icon_url=self._bot_icon_url())
        return embed

    async def enqueue(self, tracks: list[Track], text_channel: discord.abc.Messageable) -> bool:
        """Add tracks to the queue and start playback immediately if idle. Returns True if playback started."""
        self.text_channel = text_channel
        self._cancel_idle_timer()
        self.queue.extend(tracks)

        vc = self.voice_client
        if vc and not vc.is_playing() and not vc.is_paused() and self.current is None:
            await self.play_next()
            return True
        return False

    async def play_next(self) -> None:
        async with self._lock:
            vc = self.voice_client
            if not vc or not vc.is_connected():
                self.current = None
                self.queue.clear()
                await self._clear_old_controls()
                return

            if vc.is_playing() or vc.is_paused():
                return

            finished_track = self.current
            was_skipped = self.skip_requested
            self.skip_requested = False

            if finished_track is not None and not was_skipped:
                if self.loop_mode == "song":
                    self.queue.appendleft(finished_track)
                elif self.loop_mode == "queue":
                    self.queue.append(finished_track)

            while self.queue:
                next_track = self.queue.popleft()
                try:
                    # Always refresh stream URL if missing or reused via loop
                    if not next_track.stream_url or next_track is finished_track:
                        await YTDLPExtractor.resolve_stream(next_track)

                    audio = discord.FFmpegPCMAudio(
                        next_track.stream_url,
                        executable=self.ffmpeg_path,
                        before_options=FFMPEG_BEFORE_OPTIONS,
                        options=FFMPEG_OPTIONS,
                    )
                    source = discord.PCMVolumeTransformer(audio, volume=self.volume)
                    self.current = next_track

                    def _after_play(error: Optional[Exception]) -> None:
                        if error:
                            logger.error("Playback error in guild %s: %s", self.guild.id, error)
                        fut = asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)
                        try:
                            fut.result()
                        except Exception as cb_err:
                            logger.debug("After-play callback exception: %s", cb_err)

                    vc.play(source, after=_after_play)
                    self._cancel_idle_timer()

                    await self._clear_old_controls()
                    if self.text_channel:
                        embed = self.build_now_playing_embed(next_track)
                        view = MusicControlsView(self)
                        try:
                            self._now_playing_msg = await self.text_channel.send(
                                embed=embed, view=view
                            )
                        except discord.HTTPException:
                            pass
                    return
                except Exception as exc:
                    logger.exception("Failed to play '%s': %s", next_track.title, exc)
                    if self.text_channel:
                        try:
                            await self.text_channel.send(
                                f"Track skip kar diya kyunki stream load nahi ho payi: **{next_track.title}** (`{exc}`)"
                            )
                        except discord.HTTPException:
                            pass

            # Queue finished
            self.current = None
            await self._clear_old_controls()
            self._start_idle_timer()

    async def stop_and_disconnect(self, notify: bool = False) -> None:
        self._cancel_idle_timer()
        self.queue.clear()
        self.current = None
        self.loop_mode = "off"
        self.skip_requested = True

        vc = self.voice_client
        if vc:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            if vc.is_connected():
                await vc.disconnect(force=False)

        await self._clear_old_controls()
        if notify and self.text_channel:
            try:
                await self.text_channel.send("Inactivity ki wajah se voice channel leave kar diya.")
            except discord.HTTPException:
                pass


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot, config: BotConfig):
        self.bot = bot
        self.config = config
        self.ffmpeg_path = get_ffmpeg_path()
        self.players: dict[int, GuildPlayer] = {}
        logger.info("Using FFmpeg executable: %s", self.ffmpeg_path)

    def get_player(self, guild: discord.Guild) -> GuildPlayer:
        player = self.players.get(guild.id)
        if player is None:
            player = GuildPlayer(self.bot, guild, self.config, self.ffmpeg_path)
            self.players[guild.id] = player
        return player

    async def _ensure_voice(self, ctx: commands.Context) -> Optional[discord.VoiceClient]:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send("Ye command sirf Discord server ke andar kaam karti hai.")
            return None

        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Pehle kisi Voice Channel mein join karo, phir `/play` chalao!")
            return None

        target_channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client

        if vc is None:
            perms = target_channel.permissions_for(ctx.guild.me)
            if not perms.connect or not perms.speak:
                await ctx.send(
                    f"Mujhe {target_channel.mention} mein **Connect** aur **Speak** permission chahiye."
                )
                return None
            return await target_channel.connect(self_deaf=True)

        if vc.channel.id != target_channel.id:
            if vc.is_playing() or vc.is_paused():
                await ctx.send(
                    f"Main abhi {vc.channel.mention} mein play kar raha hoon. Wahan join karo ya pehle `/stop` karo."
                )
                return None
            await vc.move_to(target_channel)

        return vc

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        vc = member.guild.voice_client
        if not vc or not vc.channel:
            return

        # If the bot itself was disconnected manually by an admin
        if member.id == self.bot.user.id and after.channel is None:
            player = self.players.get(member.guild.id)
            if player:
                player.queue.clear()
                player.current = None
                player._cancel_idle_timer()
                await player._clear_old_controls()
            return

        # Auto-leave if no human listeners remain in the bot's channel
        if before.channel == vc.channel and after.channel != vc.channel:
            humans = [m for m in vc.channel.members if not m.bot]
            if not humans:
                player = self.get_player(member.guild)
                await player.stop_and_disconnect()

    @commands.hybrid_command(
        name="play",
        aliases=["p"],
        description="Song name ya YouTube link se music play karo",
    )
    @app_commands.describe(query="Song ka naam ya YouTube link")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if not vc or not ctx.guild:
            return

        player = self.get_player(ctx.guild)
        try:
            tracks = await YTDLPExtractor.search_tracks(
                query,
                ctx.author,
                max_playlist_items=self.config.max_playlist_items,
            )
        except Exception as exc:
            logger.exception("yt-dlp search failed for query '%s': %s", query, exc)
            await ctx.send(f"Song search/load karte waqt error aa gaya: `{exc}`")
            return

        if not tracks:
            await ctx.send(f"Koi matching song nahi mila for: `{query}`")
            return

        started_now = await player.enqueue(tracks, ctx.channel)

        if len(tracks) == 1:
            track = tracks[0]
            if started_now:
                await ctx.send(f"Playing: **{track.title}** (`{track.duration_text}`)")
            else:
                embed = discord.Embed(
                    title="Added to Queue",
                    description=f"**[{track.title}]({track.webpage_url})**",
                    color=self.config.embed_color,
                )
                embed.add_field(name="Duration", value=track.duration_text, inline=True)
                embed.add_field(name="Position", value=f"#{len(player.queue)}", inline=True)
                embed.add_field(name="Requested by", value=ctx.author.mention, inline=True)
                if track.thumbnail:
                    embed.set_thumbnail(url=track.thumbnail)
                bot_icon = self.bot.user.display_avatar.url if self.bot.user else None
                embed.set_footer(text=self.config.bot_name, icon_url=bot_icon)
                await ctx.send(embed=embed)
        else:
            await ctx.send(
                f"Playlist se **{len(tracks)} songs** queue mein add ho gaye! (Max limit: {self.config.max_playlist_items})"
            )

    @commands.hybrid_command(name="pause", description="Current song ko pause karo")
    async def pause(self, ctx: commands.Context) -> None:
        vc = ctx.guild.voice_client if ctx.guild else None
        if not vc or not vc.is_playing():
            await ctx.send("Abhi koi song play nahi ho raha.")
            return
        vc.pause()
        await ctx.send("Paused! `/resume` se dobara chala sakte ho.")

    @commands.hybrid_command(name="resume", aliases=["r"], description="Paused song ko resume karo")
    async def resume(self, ctx: commands.Context) -> None:
        vc = ctx.guild.voice_client if ctx.guild else None
        if not vc or not vc.is_paused():
            await ctx.send("Koi song paused nahi hai.")
            return
        vc.resume()
        await ctx.send("Resumed playback!")

    @commands.hybrid_command(name="skip", aliases=["s", "next"], description="Current song skip karo")
    async def skip(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        vc = ctx.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            await ctx.send("Skip karne ke liye koi song nahi chal raha.")
            return
        player = self.get_player(ctx.guild)
        skipped_title = player.current.title if player.current else "current track"
        player.skip_requested = True
        vc.stop()
        await ctx.send(f"Skipped: **{skipped_title}**")

    @commands.hybrid_command(name="stop", description="Music band karo aur queue clear karo")
    async def stop(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        player = self.get_player(ctx.guild)
        await player.stop_and_disconnect()
        await ctx.send("Music stopped aur queue clear ho gayi.")

    @commands.hybrid_command(name="queue", aliases=["q"], description="Current queue dekho")
    async def queue(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        player = self.get_player(ctx.guild)
        if not player.current and not player.queue:
            await ctx.send("Queue abhi khaali hai. `/play <song>` se song chalao!")
            return

        lines: list[str] = []
        if player.current:
            lines.append(
                f"**Now Playing:** [{player.current.title}]({player.current.webpage_url}) "
                f"(`{player.current.duration_text}`)\n"
            )

        if player.queue:
            preview = list(player.queue)[:15]
            lines.append("**Up Next:**")
            for idx, track in enumerate(preview, start=1):
                lines.append(
                    f"`{idx}.` [{track.title}]({track.webpage_url}) (`{track.duration_text}`)"
                )
            remaining = len(player.queue) - len(preview)
            if remaining > 0:
                lines.append(f"... aur **{remaining}** more song(s)")
        else:
            lines.append("*Queue mein aur koi song nahi hai.*")

        bot_icon = self.bot.user.display_avatar.url if self.bot.user else None
        embed = discord.Embed(
            title=f"{self.config.bot_name} — Queue",
            description="\n".join(lines),
            color=self.config.embed_color,
        )
        if bot_icon:
            embed.set_thumbnail(url=bot_icon)
        embed.set_footer(
            text=f"Loop: {player.loop_mode.capitalize()} | Volume: {int(player.volume * 100)}%",
            icon_url=bot_icon,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="nowplaying",
        aliases=["np"],
        description="Abhi kaunsa song chal raha hai dekho",
    )
    async def nowplaying(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        player = self.get_player(ctx.guild)
        if not player.current:
            await ctx.send("Abhi koi song nahi chal raha.")
            return
        await ctx.send(
            embed=player.build_now_playing_embed(player.current),
            view=MusicControlsView(player),
        )

    @commands.hybrid_command(
        name="loop",
        description="Loop mode set karo (off / song / queue)",
    )
    @app_commands.describe(mode="Loop mode chuno: off, song, ya queue")
    async def loop(
        self,
        ctx: commands.Context,
        mode: Optional[Literal["off", "song", "queue"]] = None,
    ) -> None:
        if not ctx.guild:
            return
        player = self.get_player(ctx.guild)
        if mode is None:
            cycle: dict[Literal["off", "song", "queue"], Literal["off", "song", "queue"]] = {
                "off": "song",
                "song": "queue",
                "queue": "off",
            }
            player.loop_mode = cycle[player.loop_mode]
        else:
            player.loop_mode = mode
        await ctx.send(f"Loop mode set to: **{player.loop_mode.capitalize()}**")

    @commands.hybrid_command(name="shuffle", description="Queue ke songs shuffle karo")
    async def shuffle(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        player = self.get_player(ctx.guild)
        if len(player.queue) < 2:
            await ctx.send("Shuffle karne ke liye queue mein kam se kam 2 songs chahiye.")
            return
        player.shuffle()
        await ctx.send(f"Queue mein **{len(player.queue)} songs** shuffle ho gaye!")

    @commands.hybrid_command(
        name="remove",
        aliases=["rm"],
        description="Queue se kisi number ka song hatao",
    )
    @app_commands.describe(position="Queue list mein song ka number (1 se start)")
    async def remove(self, ctx: commands.Context, position: int) -> None:
        if not ctx.guild:
            return
        player = self.get_player(ctx.guild)
        if position < 1 or position > len(player.queue):
            await ctx.send(f"Valid position daalo (`1` se `{len(player.queue)}` ke beech).")
            return
        items = list(player.queue)
        removed = items.pop(position - 1)
        player.queue = deque(items)
        await ctx.send(f"Queue se remove kar diya: **{removed.title}**")

    @commands.hybrid_command(name="clear", description="Upcoming queue ko khaali karo")
    async def clear(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        player = self.get_player(ctx.guild)
        count = len(player.queue)
        player.queue.clear()
        await ctx.send(f"Queue se **{count} song(s)** clear kar diye.")

    @commands.hybrid_command(
        name="volume",
        aliases=["vol"],
        description="Volume set karo (1 se 150 percent)",
    )
    @app_commands.describe(level="Volume percentage (1 - 150)")
    async def volume(self, ctx: commands.Context, level: int) -> None:
        if not ctx.guild:
            return
        if level < 1 or level > 150:
            await ctx.send("Volume `1` se `150` ke beech rakho.")
            return
        player = self.get_player(ctx.guild)
        player.volume = level / 100.0
        vc = player.voice_client
        if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = player.volume
        await ctx.send(f"Volume set to **{level}%**")

    @commands.hybrid_command(name="join", description="Bot ko apne voice channel mein bulao")
    async def join(self, ctx: commands.Context) -> None:
        vc = await self._ensure_voice(ctx)
        if vc and vc.channel:
            await ctx.send(f"Joined {vc.channel.mention}!")

    @commands.hybrid_command(
        name="leave",
        aliases=["dc", "disconnect"],
        description="Bot ko voice channel se disconnect karo",
    )
    async def leave(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            await ctx.send("Main abhi kisi voice channel mein nahi hoon.")
            return
        player = self.get_player(ctx.guild)
        await player.stop_and_disconnect()
        await ctx.send("Disconnected from voice channel.")

    @commands.hybrid_command(name="help", description="Saare music commands ki list dekho")
    async def help_cmd(self, ctx: commands.Context) -> None:
        p = self.config.command_prefix
        embed = discord.Embed(
            title=f"{self.config.bot_name} — Commands",
            description=(
                f"Tum **slash commands** (`/play`) ya **prefix commands** (`{p}play`) dono use kar sakte ho."
            ),
            color=self.config.embed_color,
        )
        embed.add_field(
            name="Playback",
            value=(
                f"`/play <song ya YouTube link>` (`{p}p`) — Song play ya queue karo\n"
                f"`/pause` — Pause karo\n"
                f"`/resume` (`{p}r`) — Resume karo\n"
                f"`/skip` (`{p}s`) — Next song pe jao\n"
                f"`/stop` — Band karke VC leave karo\n"
                f"`/nowplaying` (`{p}np`) — Current song dekho"
            ),
            inline=False,
        )
        embed.add_field(
            name="Queue & Controls",
            value=(
                f"`/queue` (`{p}q`) — Queue list dekho\n"
                f"`/loop [off|song|queue]` — Loop toggle karo\n"
                f"`/shuffle` — Queue shuffle karo\n"
                f"`/remove <number>` (`{p}rm`) — Song queue se hatao\n"
                f"`/clear` — Queue clear karo\n"
                f"`/volume <1-150>` (`{p}vol`) — Volume badlo\n"
                f"`/join` / `/leave` (`{p}dc`) — VC join ya leave karo"
            ),
            inline=False,
        )
        bot_icon = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_footer(text=self.config.bot_name, icon_url=bot_icon)
        if bot_icon:
            embed.set_thumbnail(url=bot_icon)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot, config: BotConfig) -> None:
    await bot.add_cog(MusicCog(bot, config))
