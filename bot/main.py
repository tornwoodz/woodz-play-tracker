from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import load_settings
from .db import Database
from .utils import parse_odds, parse_units, format_mode
from .views import TrackedPlayView

logging.basicConfig(level=logging.INFO)


PLAY_TYPES = {
    "live-bets": "LIVE",
    "hammers-aka-singles": "HAMMER",
    "parlays": "PARLAY",
    "weekly-locks": "WEEKLY LOCK",
}


class PlayTrackerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = load_settings()
        self.db = Database("data/tracker.db")
        self.guild_obj = discord.Object(id=self.settings.guild_id) if self.settings.guild_id else None
        self.owner_user_id = self.settings.owner_user_id

    async def setup_hook(self):
        await self.db.init()
        await self.ensure_boot_settings()
        if self.guild_obj:
            self.tree.copy_global_to(guild=self.guild_obj)
            await self.tree.sync(guild=self.guild_obj)
        else:
            await self.tree.sync()
        await self.restore_pending_views()
        self.daily_recap.start()

    async def ensure_boot_settings(self):
        defaults = {
            "unit_value": str(self.settings.default_unit_value),
            "recap_channel_name": self.settings.recap_channel_name,
            "display_mode_default": "units",
            "owner_user_id": str(self.settings.owner_user_id),
        }
        for k, v in defaults.items():
            existing = await self.db.get_setting(k)
            if existing is None:
                await self.db.set_setting(k, v)

    async def restore_pending_views(self):
        for play in await self.db.pending_plays():
            play_id = play[0]
            message_id = play[1]
            self.add_view(TrackedPlayView(self, play_id), message_id=message_id)

    async def on_ready(self):
        logging.info("Logged in as %s", self.user)

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        owner_id = int(await self.db.get_setting("owner_user_id", str(self.owner_user_id)) or 0)
        if message.author.id != owner_id:
            return

        channel_name = message.channel.name
        tier = None
        if channel_name in self.settings.tracked_channels_vip:
            tier = "VIP"
        elif channel_name in self.settings.tracked_channels_pub:
            tier = "PUB"
        if not tier:
            return

        existing = await self.db.get_play_by_message(message.id)
        if existing:
            return

        units = parse_units(message.content)
        odds = parse_odds(message.content)
        play_type = PLAY_TYPES.get(channel_name, channel_name.upper())

        play_id = await self.db.create_play({
            "message_id": message.id,
            "channel_id": message.channel.id,
            "guild_id": message.guild.id,
            "author_id": message.author.id,
            "channel_name": channel_name,
            "tier": tier,
            "play_type": play_type,
            "content": (message.content or "").strip()[:1500],
            "odds": odds,
            "units": units,
        })

        embed = discord.Embed(
            title=f"{play_type} TRACKED",
            description=f"Play #{play_id} has been logged.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Tier", value=tier, inline=True)
        embed.add_field(name="Units", value=f"{units:.2f}U", inline=True)
        embed.add_field(name="Odds", value=str(odds) if odds else "Not parsed", inline=True)
        embed.add_field(name="Status", value="Pending", inline=True)
        embed.set_footer(text=self.settings.footer)

        view = TrackedPlayView(self, play_id)
        sent = await message.reply(embed=embed, view=view, mention_author=False)

        # store reply message id as the tracked record's message id for persistent view stability if needed later
        await self.db.set_setting(f"reply_message:{play_id}", str(sent.id))
        self.add_view(view, message_id=sent.id)

    def build_stats_embed(self, stats: dict, scope: str, mode: str, unit_value: float) -> discord.Embed:
        title = f"{self.settings.brand_name} {scope} RECORD"
        embed = discord.Embed(title=title, color=discord.Color.gold())
        embed.description = (
            f"**Record:** {stats['wins']}-{stats['losses']}-{stats['voids']}\n"
            f"**Units:** {format_mode(stats['units'], unit_value, mode)}\n"
            f"**Win Rate:** {stats['win_rate']}%\n"
            f"**Cashouts:** {stats['cashouts']}"
        )
        for play_type, row in stats["breakdown"].items():
            embed.add_field(
                name=play_type,
                value=f"{row.get('WIN',0)}-{row.get('LOSS',0)}-{row.get('VOID',0)} | Cashouts: {row.get('CASHOUT',0)}",
                inline=False,
            )
        embed.set_footer(text=self.settings.footer)
        return embed

    @tasks.loop(minutes=1)
    async def daily_recap(self):
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        if now.hour != 22 or now.minute != 30:
            return
        for guild in self.guilds:
            recap_name = await self.db.get_setting("recap_channel_name", self.settings.recap_channel_name) or self.settings.recap_channel_name
            channel = discord.utils.get(guild.text_channels, name=recap_name)
            if not channel:
                continue
            stats = await self.db.stats(days=1)
            if stats["graded_count"] == 0:
                continue
            unit_value = float(await self.db.get_setting("unit_value", str(self.settings.default_unit_value)) or self.settings.default_unit_value)
            mode = await self.db.get_setting("display_mode_default", "units") or "units"
            embed = self.build_stats_embed(stats, "DAILY RECAP", mode, unit_value)
            await channel.send(embed=embed)
            await asyncio.sleep(1)


bot = PlayTrackerBot()


@bot.tree.command(name="record", description="Show official record")
@app_commands.describe(scope="ALL, VIP, or PUB", mode="units or dollars")
async def record(interaction: discord.Interaction, scope: str = "ALL", mode: str = "units"):
    stats = await bot.db.stats(scope=scope.upper())
    unit_value = float(await bot.db.get_setting("unit_value", str(bot.settings.default_unit_value)) or bot.settings.default_unit_value)
    await interaction.response.send_message(embed=bot.build_stats_embed(stats, scope.upper(), mode.lower(), unit_value), ephemeral=True)


@bot.tree.command(name="pending", description="List pending official plays")
async def pending(interaction: discord.Interaction):
    plays = await bot.db.pending_plays()
    if not plays:
        await interaction.response.send_message("No pending plays.", ephemeral=True)
        return
    lines = []
    for play in plays[:20]:
        lines.append(f"#{play[0]} | {play[7]} | {play[6]} | {play[10]:.2f}U | odds: {play[9] or 'n/a'}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="tailboard", description="Show tailing leaderboard")
async def tailboard(interaction: discord.Interaction):
    rows = await bot.db.tail_leaderboard()
    if not rows:
        await interaction.response.send_message("No tailing data yet.", ephemeral=True)
        return
    desc = []
    for i, (user_id, tails, wins, losses) in enumerate(rows, 1):
        member = interaction.guild.get_member(user_id) if interaction.guild else None
        name = member.display_name if member else str(user_id)
        desc.append(f"**{i}. {name}** — Tails: {tails} | Wins: {wins} | Losses: {losses}")
    embed = discord.Embed(title="Tailing Leaderboard", description="\n".join(desc), color=discord.Color.green())
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="recap", description="Show a recap for the last N days")
async def recap(interaction: discord.Interaction, days: app_commands.Range[int, 1, 30] = 1, mode: str = "units"):
    stats = await bot.db.stats(days=days)
    unit_value = float(await bot.db.get_setting("unit_value", str(bot.settings.default_unit_value)) or bot.settings.default_unit_value)
    await interaction.response.send_message(embed=bot.build_stats_embed(stats, f"LAST {days} DAY(S)", mode.lower(), unit_value), ephemeral=True)


@bot.tree.command(name="grade", description="Owner-only manual grading")
@app_commands.describe(play_id="Numeric play ID", result="WIN, LOSS, VOID, or CASHOUT", cashout_units="Required for CASHOUT")
async def grade(interaction: discord.Interaction, play_id: int, result: str, cashout_units: float | None = None):
    owner_id = int(await bot.db.get_setting("owner_user_id", str(bot.owner_user_id)) or 0)
    if interaction.user.id != owner_id:
        await interaction.response.send_message("Only the owner can grade official plays.", ephemeral=True)
        return
    play = await bot.db.get_play(play_id)
    if not play:
        await interaction.response.send_message("Play not found.", ephemeral=True)
        return
    odds = play[9]
    units = float(play[10])
    result = result.upper()
    if result == "WIN":
        from .utils import american_profit
        profit = american_profit(odds, units)
    elif result == "LOSS":
        profit = -units
    elif result == "VOID":
        profit = 0.0
    elif result == "CASHOUT":
        if cashout_units is None:
            await interaction.response.send_message("Provide cashout_units for CASHOUT.", ephemeral=True)
            return
        profit = cashout_units
    else:
        await interaction.response.send_message("Use WIN, LOSS, VOID, or CASHOUT.", ephemeral=True)
        return
    await bot.db.grade_play(play_id, result, profit)
    await interaction.response.send_message(f"Play #{play_id} graded {result}: {profit:+.2f}U", ephemeral=True)


settings_group = app_commands.Group(name="settings", description="Owner settings")


@settings_group.command(name="show", description="Show current settings")
async def settings_show(interaction: discord.Interaction):
    unit_value = await bot.db.get_setting("unit_value", str(bot.settings.default_unit_value))
    recap_channel_name = await bot.db.get_setting("recap_channel_name", bot.settings.recap_channel_name)
    mode = await bot.db.get_setting("display_mode_default", "units")
    owner_id = await bot.db.get_setting("owner_user_id", str(bot.owner_user_id))
    await interaction.response.send_message(
        f"owner_user_id={owner_id}\nunit_value=${float(unit_value):.2f}\nrecap_channel_name={recap_channel_name}\ndisplay_mode_default={mode}",
        ephemeral=True,
    )


@settings_group.command(name="set_unit_value", description="Set dollar value for 1 unit")
async def set_unit_value(interaction: discord.Interaction, amount: app_commands.Range[float, 1, 10000]):
    if interaction.user.id != int(await bot.db.get_setting("owner_user_id", str(bot.owner_user_id)) or 0):
        await interaction.response.send_message("Only the owner can change settings.", ephemeral=True)
        return
    await bot.db.set_setting("unit_value", str(amount))
    await interaction.response.send_message(f"Set 1U = ${amount:.2f}", ephemeral=True)


@settings_group.command(name="toggle_dollars", description="Set default display mode")
async def toggle_dollars(interaction: discord.Interaction, enabled: bool):
    if interaction.user.id != int(await bot.db.get_setting("owner_user_id", str(bot.owner_user_id)) or 0):
        await interaction.response.send_message("Only the owner can change settings.", ephemeral=True)
        return
    await bot.db.set_setting("display_mode_default", "dollars" if enabled else "units")
    await interaction.response.send_message(f"Default display mode set to {'dollars' if enabled else 'units'}.", ephemeral=True)


@settings_group.command(name="set_recap_channel", description="Set the daily recap channel")
async def set_recap_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.user.id != int(await bot.db.get_setting("owner_user_id", str(bot.owner_user_id)) or 0):
        await interaction.response.send_message("Only the owner can change settings.", ephemeral=True)
        return
    await bot.db.set_setting("recap_channel_name", channel.name)
    await interaction.response.send_message(f"Daily recap channel set to #{channel.name}", ephemeral=True)


@settings_group.command(name="set_owner", description="Set the owner user")
async def set_owner(interaction: discord.Interaction, user: discord.Member):
    if interaction.user.id != int(await bot.db.get_setting("owner_user_id", str(bot.owner_user_id)) or 0):
        await interaction.response.send_message("Only the current owner can change settings.", ephemeral=True)
        return
    await bot.db.set_setting("owner_user_id", str(user.id))
    bot.owner_user_id = user.id
    await interaction.response.send_message(f"Owner updated to {user.mention}", ephemeral=True)


bot.tree.add_command(settings_group, guild=bot.guild_obj)


if __name__ == "__main__":
    if not bot.settings.token:
        raise RuntimeError("Missing DISCORD_TOKEN in environment.")
    bot.run(bot.settings.token)
