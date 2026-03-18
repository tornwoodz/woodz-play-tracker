import os
import re
import json
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

DATA_FILE = "picktrax_data.json"

# ===== CHANNEL / ROLE CONFIG =====
TRACKED_PICK_CHANNELS = {
    "hammers-aka-singles🔨🔨": "hammer",
    "parlays-🍀": "parlay",
    "weekly-locks📄": "weekly",
    "🚨live-bets🚨": "live",
}

WIN_SUBMISSION_CHANNELS = {
    "general-chat💬",
    "vip-general-chatroom💬",
}

POST_YOUR_WINS_CHANNEL = "post-your-wins"
DAILY_RECAP_CHANNEL = "daily-recap📄"

VIP_ROLE_NAME = "🏆VIP"
PUB_ROLE_NAME = "🆓PUB"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_data() -> dict:
    return {
        "owner_id": None,
        "record": {
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "units": 0.0,
        },
        "show_dollars": False,
        "unit_value": 100.0,
        "picks": [],
        "graded_history": [],
        "message_pick_map": {},
        "registered_source_messages": [],
    }


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = default_data()
        save_data(data)

    defaults = default_data()
    for key, value in defaults.items():
        if key not in data:
            data[key] = value

    return data


data = load_data()


def is_owner_user(user_id: int) -> bool:
    owner_id = data.get("owner_id")
    return owner_id is not None and user_id == owner_id


def get_best_member_role(member: discord.Member) -> str:
    role_names = {role.name for role in member.roles}
    if VIP_ROLE_NAME in role_names:
        return VIP_ROLE_NAME
    if PUB_ROLE_NAME in role_names:
        return PUB_ROLE_NAME
    return "Member"


def has_member_submission_role(member: discord.Member) -> bool:
    role_names = {role.name for role in member.roles}
    return VIP_ROLE_NAME in role_names or PUB_ROLE_NAME in role_names


def format_profit(units: float) -> str:
    if data["show_dollars"]:
        dollars = units * float(data["unit_value"])
        sign = "+" if dollars >= 0 else ""
        return f"{sign}${dollars:,.2f}"
    sign = "+" if units >= 0 else ""
    return f"{sign}{units:.2f}U"


def extract_units_from_text(text: str) -> float:
    if not text:
        return 1.0

    patterns = [
        r"([+-]?\d+(?:\.\d+)?)\s*u\b",
        r"([+-]?\d+(?:\.\d+)?)\s*unit\b",
        r"([+-]?\d+(?:\.\d+)?)\s*units\b",
    ]

    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            try:
                return abs(float(match.group(1)))
            except Exception:
                pass

    return 1.0


def detect_result(text: str) -> Optional[str]:
    exact = text.strip().lower()

    if exact in {"win", "w", "cash", "cashed", "hit"}:
        return "win"
    if exact in {"loss", "l", "lost", "miss", "missed"}:
        return "loss"
    if exact in {"push", "p"}:
        return "push"

    if (
        "as a win" in exact
        or "grade win" in exact
        or "mark win" in exact
        or "this hit" in exact
        or "cash it" in exact
        or "winner" in exact
        or "i won" in exact
    ):
        return "win"

    if (
        "as a loss" in exact
        or "grade loss" in exact
        or "mark loss" in exact
        or "it lost" in exact
        or "missed" in exact
    ):
        return "loss"

    if "as a push" in exact or "grade push" in exact or "mark push" in exact:
        return "push"

    return None


def pending_picks() -> list:
    return [p for p in data["picks"] if p["status"] == "pending"]


def graded_history() -> list:
    return data["graded_history"]


def find_pick_by_id(pick_id: int) -> Optional[dict]:
    for pick in data["picks"]:
        if pick["id"] == pick_id:
            return pick
    return None


def build_pick_embed(pick: dict) -> discord.Embed:
    color = discord.Color.blurple()
    if pick["status"] == "win":
        color = discord.Color.green()
    elif pick["status"] == "loss":
        color = discord.Color.red()
    elif pick["status"] == "push":
        color = discord.Color.light_grey()

    embed = discord.Embed(
        title=f"Pick #{pick['id']} • {pick['play_type'].title()}",
        description=pick["bet"],
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Units", value=f"{pick['units']:.2f}U", inline=True)
    embed.add_field(name="Odds", value=f"{pick['odds']:+d}", inline=True)
    embed.add_field(name="Status", value=pick["status"].upper(), inline=True)

    if pick["status"] != "pending":
        embed.add_field(
            name="Profit",
            value=format_profit(float(pick.get("profit_units", 0.0))),
            inline=False,
        )

    source_channel = pick.get("source_channel_name")
    if source_channel:
        embed.add_field(name="Source Channel", value=source_channel, inline=False)

    return embed


def build_record_embed() -> discord.Embed:
    rec = data["record"]
    graded_decisions = rec["wins"] + rec["losses"]
    win_rate = (rec["wins"] / graded_decisions * 100) if graded_decisions > 0 else 0.0

    embed = discord.Embed(
        title="📊 Official Record",
        color=discord.Color.green(),
    )
    embed.add_field(name="Wins", value=str(rec["wins"]), inline=True)
    embed.add_field(name="Losses", value=str(rec["losses"]), inline=True)
    embed.add_field(name="Pushes", value=str(rec["pushes"]), inline=True)
    embed.add_field(name="Profit", value=format_profit(rec["units"]), inline=True)
    embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)
    return embed


async def post_recap_if_configured(guild: discord.Guild) -> None:
    recap_channel = discord.utils.get(guild.text_channels, name=DAILY_RECAP_CHANNEL)
    if not recap_channel:
        return

    rec = data["record"]
    graded_decisions = rec["wins"] + rec["losses"]
    win_rate = (rec["wins"] / graded_decisions * 100) if graded_decisions > 0 else 0.0

    embed = discord.Embed(
        title="🧾 Current Recap",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Wins", value=str(rec["wins"]), inline=True)
    embed.add_field(name="Losses", value=str(rec["losses"]), inline=True)
    embed.add_field(name="Pushes", value=str(rec["pushes"]), inline=True)
    embed.add_field(name="Profit", value=format_profit(rec["units"]), inline=True)
    embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)

    try:
        await recap_channel.send(embed=embed)
    except Exception as e:
        print(f"Failed to post recap: {e}")


async def disable_pick_buttons_for_message(
    channel: discord.abc.Messageable,
    message_id: Optional[int],
    pick: dict,
) -> None:
    if not message_id:
        return

    try:
        message = await channel.fetch_message(message_id)
        await message.edit(embed=build_pick_embed(pick), view=None)
    except Exception as e:
        print(f"Failed to disable buttons: {e}")


def apply_grade_to_pick(pick: dict, result: str, grader_id: int) -> tuple[bool, str]:
    if pick["status"] != "pending":
        return False, "That pick is already graded."

    odds = int(pick["odds"])
    units = float(pick["units"])

    pick["status"] = result
    pick["result"] = result
    pick["graded_at"] = utc_now_iso()
    pick["graded_by"] = grader_id

    if result == "win":
        if odds > 0:
            profit_units = units * (odds / 100)
        else:
            profit_units = units * (100 / abs(odds))
        data["record"]["wins"] += 1
    elif result == "loss":
        profit_units = -units
        data["record"]["losses"] += 1
    else:
        profit_units = 0.0
        data["record"]["pushes"] += 1

    pick["profit_units"] = round(profit_units, 4)
    data["record"]["units"] = round(data["record"]["units"] + profit_units, 4)

    data["picks"] = [p for p in data["picks"] if p["status"] == "pending"]
    data["graded_history"].append(pick)
    save_data(data)

    return True, (
        f"✅ Pick #{pick['id']} graded as **{result.upper()}**\n"
        f"Type: {pick['play_type'].title()}\n"
        f"Units: {pick['units']:.2f}U\n"
        f"Profit: {format_profit(pick['profit_units'])}"
    )


def create_auto_pick_from_message(message: discord.Message, play_type: str) -> dict:
    next_id = len(data["picks"]) + len(data["graded_history"]) + 1
    units = extract_units_from_text(message.content)

    pick = {
        "id": next_id,
        "bet": message.content[:500] if message.content else f"Graphic pick from message {message.id}",
        "units": units,
        "odds": -110,
        "status": "pending",
        "created_by": message.author.id,
        "created_at": utc_now_iso(),
        "graded_at": None,
        "graded_by": None,
        "result": None,
        "profit_units": 0.0,
        "play_type": play_type,
        "source_message_id": message.id,
        "source_channel_name": message.channel.name,
    }

    data["picks"].append(pick)
    data["message_pick_map"][str(message.id)] = pick["id"]
    data["registered_source_messages"].append(message.id)
    save_data(data)
    return pick


class GradeView(discord.ui.View):
    def __init__(self, pick_id: int):
        super().__init__(timeout=None)
        self.pick_id = pick_id

    async def grade_pick(self, interaction: discord.Interaction, result: str):
        if data.get("owner_id") and not is_owner_user(interaction.user.id):
            await interaction.response.send_message(
                "Only the owner can grade official picks.",
                ephemeral=True,
            )
            return

        pick = find_pick_by_id(self.pick_id)
        if not pick:
            await interaction.response.send_message(
                "That pick no longer exists or was already graded.",
                ephemeral=True,
            )
            return

        ok, msg = apply_grade_to_pick(pick, result, interaction.user.id)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return

        embed = build_pick_embed(pick)
        await interaction.response.edit_message(embed=embed, view=None)
        await interaction.followup.send(msg)

        if interaction.guild:
            await post_recap_if_configured(interaction.guild)

    @discord.ui.button(label="Win", style=discord.ButtonStyle.success, custom_id="picktrax_win")
    async def win_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.grade_pick(interaction, "win")

    @discord.ui.button(label="Loss", style=discord.ButtonStyle.danger, custom_id="picktrax_loss")
    async def loss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.grade_pick(interaction, "loss")

    @discord.ui.button(label="Push", style=discord.ButtonStyle.secondary, custom_id="picktrax_push")
    async def push_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.grade_pick(interaction, "push")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Sync error: {e}")

    print(f"🔥 Logged in as {bot.user} ({bot.user.id})")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"❌ Slash command error: {error}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(f"Error: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except Exception as e:
        print(f"❌ Failed to send error message: {e}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").lower().strip()
    bot_mentioned = bot.user in message.mentions if bot.user else False

    # ===== AUTO REGISTER YOUR PICKS FROM PICK CHANNELS =====
    if message.author.id == data.get("owner_id"):
        channel_name = message.channel.name
        has_graphic = len(message.attachments) > 0 or len(message.embeds) > 0

        if channel_name in TRACKED_PICK_CHANNELS and has_graphic:
            if message.id not in data.get("registered_source_messages", []):
                play_type = TRACKED_PICK_CHANNELS[channel_name]
                create_auto_pick_from_message(message, play_type)

                try:
                    await message.add_reaction("📌")
                except Exception:
                    pass

    # ===== OWNER REPLY-TO-GRADE YOUR PICK POSTS =====
    result = detect_result(content)

    if message.reference and bot_mentioned and message.author.id == data.get("owner_id"):
        try:
            referenced = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            await bot.process_commands(message)
            return

        pick_id = data["message_pick_map"].get(str(referenced.id))
        if pick_id:
            pick = find_pick_by_id(int(pick_id))

            if pick and result in {"win", "loss", "push"}:
                ok, msg = apply_grade_to_pick(pick, result, message.author.id)
                if ok:
                    await message.channel.send(msg)
                    if message.guild:
                        await post_recap_if_configured(message.guild)
                else:
                    await message.channel.send(msg)

                await bot.process_commands(message)
                return

            if pick and "grade this" in content:
                await message.channel.send(
                    f"Pick #{pick['id']} ready to grade:",
                    embed=build_pick_embed(pick),
                    view=GradeView(pick["id"]),
                )
                await bot.process_commands(message)
                return

    # ===== MEMBER WIN SUBMISSIONS TO POST-YOUR-WINS =====
    if (
        message.channel.name in WIN_SUBMISSION_CHANNELS
        and bot_mentioned
        and isinstance(message.author, discord.Member)
        and has_member_submission_role(message.author)
    ):
        win_result = detect_result(content)
        if win_result == "win":
            wins_channel = discord.utils.get(message.guild.text_channels, name=POST_YOUR_WINS_CHANNEL)
            if wins_channel:
                role_name = get_best_member_role(message.author)

                embed = discord.Embed(
                    title="🏆 New Winner Submitted",
                    description=message.content,
                    color=discord.Color.green() if role_name == VIP_ROLE_NAME else discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="User", value=message.author.mention, inline=True)
                embed.add_field(name="Role", value=role_name, inline=True)
                embed.add_field(name="Source", value=f"#{message.channel.name}", inline=True)

                files = []
                for attachment in message.attachments:
                    try:
                        file = await attachment.to_file()
                        files.append(file)
                    except Exception:
                        pass

                try:
                    await wins_channel.send(embed=embed, files=files)
                    await message.add_reaction("✅")
                except Exception as e:
                    print(f"Failed forwarding winner: {e}")

    await bot.process_commands(message)


@bot.tree.command(name="ping", description="Test if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 pong")


@bot.tree.command(name="record", description="Show official record")
async def record(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_record_embed())


@bot.tree.command(name="pending", description="List pending official plays")
async def pending(interaction: discord.Interaction):
    items = pending_picks()

    if not items:
        await interaction.response.send_message("📭 No pending picks.")
        return

    lines = ["📋 **Pending Picks**"]
    for idx, p in enumerate(items, start=1):
        lines.append(
            f"{idx}. ID {p['id']} — {p['play_type'].title()} — {p['units']:.2f}U — #{p['source_channel_name']}"
        )

    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="grade", description="Grade a pending pick")
@app_commands.describe(
    index="The pending pick number from /pending",
    result="win, loss, or push",
)
@app_commands.choices(
    result=[
        app_commands.Choice(name="win", value="win"),
        app_commands.Choice(name="loss", value="loss"),
        app_commands.Choice(name="push", value="push"),
    ]
)
async def grade(interaction: discord.Interaction, index: int, result: app_commands.Choice[str]):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the owner can grade official picks.", ephemeral=True)
        return

    items = pending_picks()
    if not items:
        await interaction.response.send_message("No pending picks to grade.")
        return

    if index < 1 or index > len(items):
        await interaction.response.send_message("Invalid pending pick number.")
        return

    pick = items[index - 1]
    ok, msg = apply_grade_to_pick(pick, result.value, interaction.user.id)

    if not ok:
        await interaction.response.send_message(msg)
        return

    await interaction.response.send_message(msg)
    if interaction.guild:
        await post_recap_if_configured(interaction.guild)


@bot.tree.command(name="recap", description="Show recap for the last N graded picks")
@app_commands.describe(count="How many recently graded picks to include")
async def recap(interaction: discord.Interaction, count: Optional[int] = 10):
    await interaction.response.defer()

    count = max(1, min(count or 10, 25))
    history = graded_history()[-count:]

    if not history:
        await interaction.followup.send("📭 No graded picks yet.")
        return

    wins = sum(1 for p in history if p["result"] == "win")
    losses = sum(1 for p in history if p["result"] == "loss")
    pushes = sum(1 for p in history if p["result"] == "push")
    units = sum(float(p.get("profit_units", 0.0)) for p in history)

    lines = [
        f"🧾 **Recap — Last {len(history)} Graded Picks**",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Pushes: {pushes}",
        f"Profit: {format_profit(units)}",
        "",
    ]

    for p in reversed(history):
        emoji = "✅" if p["result"] == "win" else "❌" if p["result"] == "loss" else "➖"
        lines.append(
            f"{emoji} ID {p['id']} — {p['play_type'].title()} — {p['units']:.2f}U — {format_profit(p['profit_units'])}"
        )

    await interaction.followup.send("\n".join(lines))


@bot.tree.command(name="tailboard", description="Show simple tailing leaderboard")
async def tailboard(interaction: discord.Interaction):
    rec = data["record"]
    total = rec["wins"] + rec["losses"] + rec["pushes"]
    msg = (
        "🏆 **Tailboard**\n"
        f"Official picks graded: {total}\n"
        f"Current profit: {format_profit(rec['units'])}\n"
        f"Owner set: {'Yes' if data['owner_id'] else 'No'}"
    )
    await interaction.response.send_message(msg)


settings_group = app_commands.Group(name="settings", description="Bot settings commands")


@settings_group.command(name="show", description="Show current settings")
async def settings_show(interaction: discord.Interaction):
    owner_id = data.get("owner_id")
    owner_text = f"<@{owner_id}>" if owner_id else "Not set"
    dollars_text = "On" if data["show_dollars"] else "Off"

    msg = (
        "⚙️ **Current Settings**\n"
        f"Owner: {owner_text}\n"
        f"1 Unit Value: ${float(data['unit_value']):,.2f}\n"
        f"Show Dollars: {dollars_text}\n"
        f"Tracked Pick Channels: {', '.join(TRACKED_PICK_CHANNELS.keys())}\n"
        f"Win Submission Channels: {', '.join(WIN_SUBMISSION_CHANNELS)}"
    )
    await interaction.response.send_message(msg)


@settings_group.command(name="set_owner", description="Set the owner user")
async def settings_set_owner(interaction: discord.Interaction, user: discord.User):
    data["owner_id"] = user.id
    save_data(data)
    await interaction.response.send_message(f"👑 Owner set to {user.mention}")


@settings_group.command(name="set_unit_value", description="Set dollar value for 1 unit")
async def settings_set_unit_value(interaction: discord.Interaction, amount: float):
    if amount <= 0:
        await interaction.response.send_message("Unit value must be greater than 0.")
        return

    data["unit_value"] = float(amount)
    save_data(data)
    await interaction.response.send_message(f"💵 1 unit is now set to ${amount:,.2f}")


@settings_group.command(name="toggle_dollars", description="Turn dollar display on or off")
async def settings_toggle_dollars(interaction: discord.Interaction, enabled: bool):
    data["show_dollars"] = enabled
    save_data(data)
    state = "On" if enabled else "Off"
    await interaction.response.send_message(f"💰 Dollar display is now {state}")


bot.tree.add_command(settings_group)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in your environment variables.")

bot.run(TOKEN)
