import os
import re
import json
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

# =========================
# YOUR CHANNEL IDS (ALREADY SET)
# =========================
GENERAL_CHAT_ID = 1483436461423333376
VIP_GENERAL_CHAT_ID = 1483435285231702137
POST_YOUR_WINS_ID = 1483439779390427341
DAILY_RECAP_ID = 1483927105992392865

HAMMERS_CHANNEL_ID = 1483485837810335744
PARLAYS_CHANNEL_ID = 1483433966227947619
WEEKLY_LOCKS_CHANNEL_ID = 1483436117536542882
LIVE_BETS_CHANNEL_ID = 1483435130235260928

TRACKED_CHANNELS = {
    HAMMERS_CHANNEL_ID: "hammer",
    PARLAYS_CHANNEL_ID: "parlay",
    WEEKLY_LOCKS_CHANNEL_ID: "weekly",
    LIVE_BETS_CHANNEL_ID: "live",
}

WIN_CHANNELS = {GENERAL_CHAT_ID, VIP_GENERAL_CHAT_ID}

VIP_ROLE = "🏆VIP"
PUB_ROLE = "🆓PUB"

DATA_FILE = "data.json"

# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DATA
# =========================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"picks": [], "map": {}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

# =========================
# HELPERS
# =========================
def detect_result(text):
    t = text.lower()
    if any(x in t for x in ["win","won","cash","cashed","hit","green","winner"]):
        return "win"
    if any(x in t for x in ["loss","lost","miss","missed","red"]):
        return "loss"
    if "push" in t:
        return "push"
    return None

def get_role(member):
    roles = [r.name for r in member.roles]

    if VIP_ROLE in roles:
        return VIP_ROLE
    if PUB_ROLE in roles:
        return PUB_ROLE

    for r in reversed(member.roles):
        if r.name != "@everyone":
            return r.name

    return "Member"

def extract_units(text):
    match = re.search(r"(\d+(\.\d+)?)u", text.lower())
    if match:
        return float(match.group(1))
    return 1.0

# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower()
    mentioned = bot.user in message.mentions

    # =========================
    # AUTO TRACK YOUR PICKS
    # =========================
    if message.channel.id in TRACKED_CHANNELS:
        if message.attachments:
            if str(message.id) not in data["map"]:
                pick = {
                    "id": len(data["picks"]) + 1,
                    "message_id": message.id,
                    "channel": message.channel.id,
                    "type": TRACKED_CHANNELS[message.channel.id],
                    "units": extract_units(message.content),
                    "status": "pending"
                }
                data["picks"].append(pick)
                data["map"][str(message.id)] = pick["id"]
                save_data(data)
                await message.add_reaction("📌")

    # =========================
    # OWNER GRADING
    # =========================
    if message.reference and mentioned:
        ref = await message.channel.fetch_message(message.reference.message_id)
        pick_id = data["map"].get(str(ref.id))

        if pick_id:
            pick = next(p for p in data["picks"] if p["id"] == pick_id)
            result = detect_result(content)

            if result:
                pick["status"] = result
                save_data(data)

                await message.channel.send(f"✅ Pick graded as {result.upper()}")

                # SEND TO WINS IF WIN
                if result == "win":
                    wins_channel = bot.get_channel(POST_YOUR_WINS_ID)

                    embed = discord.Embed(
                        title="🏆 Official Win",
                        description=ref.content or "Winning Pick",
                        color=discord.Color.gold()
                    )

                    embed.add_field(name="Type", value=pick["type"], inline=True)
                    embed.add_field(name="Units", value=f"{pick['units']}U", inline=True)

                    files = []
                    for a in ref.attachments:
                        files.append(await a.to_file())

                    await wins_channel.send(embed=embed, files=files)

    # =========================
    # MEMBER WIN SUBMISSIONS
    # =========================
    if message.channel.id in WIN_CHANNELS and mentioned:
        result = detect_result(content)

        if result == "win":
            wins_channel = bot.get_channel(POST_YOUR_WINS_ID)

            role = get_role(message.author)

            embed = discord.Embed(
                title="🏆 New Winner Submitted",
                description=message.content,
                color=discord.Color.green() if role == VIP_ROLE else discord.Color.blue()
            )

            embed.add_field(name="User", value=message.author.mention, inline=True)
            embed.add_field(name="Role", value=role, inline=True)
            embed.add_field(name="Source", value=message.channel.mention, inline=True)

            files = []
            for a in message.attachments:
                files.append(await a.to_file())

            await wins_channel.send(embed=embed, files=files)
            await message.add_reaction("✅")

    await bot.process_commands(message)

# =========================
# RUN
# =========================
bot.run("")
