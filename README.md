# Lord Hax Music

Discord music bot that plays songs from **song names** or **YouTube links** (including playlists) with both **slash commands (`/play`)** and **prefix commands (`!play`)**, plus live playback control buttons.

## Setup (5 Minutes)

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application** (name it **Lord Hax Music**).
2. Go to the **Bot** tab:
   - Click **Reset Token** and copy your bot token.
   - Under **Privileged Gateway Intents**, turn ON **Message Content Intent** and click **Save Changes**.
3. Open `.env` in this folder and paste your token:
   ```env
   DISCORD_TOKEN=your_actual_token_here
   BOT_NAME=Lord Hax Music
   COMMAND_PREFIX=!
   ```
4. Invite the bot to your server:
   - Go to **OAuth2 -> URL Generator**
   - Scopes: check `bot` and `applications.commands`
   - Bot Permissions: check `Send Messages`, `Embed Links`, `Connect`, `Speak`, `Read Message History`
   - Open the generated URL and select your server.
5. Start the bot by double-clicking `start_bot.bat` or running:
   ```powershell
   python bot.py
   ```
   On first startup, the bot automatically applies `assets/bot_icon.png` as its Discord avatar and sets its username to `Lord Hax Music` (you can also upload `assets/bot_icon.png` manually in the Discord Developer Portal).

## Commands

| Command | Alias | Action |
|---|---|---|
| `/play <song or YouTube link>` | `!p` | Play song by name or YouTube URL |
| `/pause` | `!pause` | Pause playback |
| `/resume` | `!r` | Resume playback |
| `/skip` | `!s` | Skip current song |
| `/stop` | `!stop` | Stop playback, clear queue, leave VC |
| `/queue` | `!q` | Show current queue |
| `/nowplaying` | `!np` | Show current song + control buttons |
| `/loop [off\|song\|queue]` | `!loop` | Change loop mode |
| `/shuffle` | `!shuffle` | Shuffle upcoming queue |
| `/remove <number>` | `!rm` | Remove a track from queue |
| `/clear` | `!clear` | Clear upcoming queue |
| `/volume <1-150>` | `!vol` | Set playback volume |
| `/join` / `/leave` | `!dc` | Join or leave voice channel |
| `/help` | `!help` | Show all commands |
