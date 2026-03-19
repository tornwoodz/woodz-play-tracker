import os
import re
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import discord
from discord.ext import commands

# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

ALLOWED_CHANNEL_IDS = {
    1483485837810335744,  # hammers-aka-singles
    1483433966227947619,  # parlays
    1483436117536542882,  # weekly-locks
    1483435130235260928,  # live-bets
    1483439779390427341,  # post-your-wins
    1483927105992392865,  # daily-recap
    1483435285231702137,  # vip-general-chat
    1483436461423333376,  # general-chat
}

DATA_FILE = "picktrax_data.json"

# =========================================================
# DISCORD SETUP
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# DATA HELPERS
# =========================================================

def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {
            "graded_slips": [],
            "record": {
                "wins": 0,
                "losses": 0,
                "pushes": 0
            }
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "graded_slips": [],
            "record": {
                "wins": 0,
                "losses": 0,
                "pushes": 0
            }
        }

def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

data_store = load_data()

# =========================================================
# TEXT HELPERS
# =========================================================

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()

def has_image_attachment(message: discord.Message) -> bool:
    if not message.attachments:
        return False

    for attachment in message.attachments:
        filename = attachment.filename.lower()
        if filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            return True
        if attachment.content_type and attachment.content_type.startswith("image/"):
            return True

    return False

def is_link_request(text: str) -> bool:
    text = normalize_text(text)

    link_patterns = [
        "link it",
        "link this",
        "send the link",
        "drop the link",
        "need the link",
        "give me the link",
        "post the link",
        "where the link",
        "make the link",
        "build the link",
        "create the link",
        "get the link",
        "can you link",
        "link that",
        "link these",
        "link slip",
        "link betslip",
        "one click",
        "one-click",
    ]

    if "link" in text:
        return True

    return any(p in text for p in link_patterns)

def detect_grade_action(text: str) -> Optional[str]:
    text = normalize_text(text)

    if "grade" in text or "mark" in text or "graded" in text:
        if "loss" in text:
            return "loss"
        if re.search(r"\bwin\b", text):
            return "win"
        if "push" in text or "void" in text:
            return "push"

    if text in {"loss", "l"}:
        return "loss"
    if text in {"win", "w"}:
        return "win"
    if text in {"push", "void"}:
        return "push"

    return None

def get_record_text() -> str:
    record = data_store["record"]
    return f"Record: ✅ {record['wins']} - ❌ {record['losses']} - ➖ {record['pushes']}"

def message_has_picktrax_mention(message: discord.Message) -> bool:
    if bot.user is None:
        return False
    return bot.user in message.mentions

def is_allowed_channel(message: discord.Message) -> bool:
    return message.channel.id in ALLOWED_CHANNEL_IDS

# =========================================================
# AI-READY PLACEHOLDER
# =========================================================

async def ai_brain_router(message: discord.Message, clean_text: str) -> Optional[str]:
    text = clean_text.lower()

    if "what can you do" in text or "help" in text:
        return (
            "**Pick Trax is live.**\n\n"
            "I can currently:\n"
            "- respond when you @mention me\n"
            "- detect link requests\n"
            "- react with 🔗 on image posts that need linking\n"
            "- detect replied-to image posts too\n"
            "- grade slips as win/loss/push\n"
            "- track a basic record\n\n"
            "Next upgrades:\n"
            "- OCR bet slip reading\n"
            "- auto leg extraction\n"
            "- auto one-click link flow\n"
            "- AI recap generation\n"
            "- unit/profit tracking"
        )

    return None

# =========================================================
# LINK HELPERS
# =========================================================

async def get_target_image_message(message: discord.Message) -> Optional[discord.Message]:
    # 1) current message has the image
    if has_image_attachment(message):
        return message

    # 2) replied-to message has the image
    if message.reference and message.reference.message_id:
        try:
            referenced = message.reference.resolved

            if referenced is None:
                referenced = await message.channel.fetch_message(message.reference.message_id)

            if referenced and has_image_attachment(referenced):
                return referenced
        except Exception:
            return None

    return None

# =========================================================
# GRADE HANDLERS
# =========================================================

async def handle_grade(message: discord.Message, result: str) -> None:
    record = data_store["record"]

    if result == "win":
        record["wins"] += 1
        emoji = "✅"
        word = "WIN"
    elif result == "loss":
        record["losses"] += 1
        emoji = "❌"
        word = "LOSS"
    else:
        record["pushes"] += 1
        emoji = "➖"
        word = "PUSH"

    data_store["graded_slips"].append({
        "message_id": str(message.id),
        "author_id": str(message.author.id),
        "channel_id": str(message.channel.id),
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    save_data(data_store)

    await message.reply(
        f"{emoji} Graded as **{word}**.\n{get_record_text()}",
        mention_author=False
    )

# =========================================================
# LINK HANDLER
# =========================================================

async def handle_link_request(message: discord.Message) -> None:
    target_message = await get_target_image_message(message)

    if target_message:
        try:
            await target_message.add_reaction("🔗")
        except Exception:
            pass

    try:
        await message.reply("I got you!", mention_author=False)
    except Exception:
        try:
            await message.channel.send("I got you!")
        except Exception:
            pass

    # future upgrade:
    # OCR target_message attachments
    # parse legs
    # build real link
    # send formatted card/link result

# =========================================================
# EVENTS
# =========================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Pick Trax is online.")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not is_allowed_channel(message):
        await bot.process_commands(message)
        return

    content = message.content or ""
    clean_text = normalize_text(content)

    if message_has_picktrax_mention(message):
        if is_link_request(clean_text):
            await handle_link_request(message)
            await bot.process_commands(message)
            return

        grade_action = detect_grade_action(clean_text)
        if grade_action:
            await handle_grade(message, grade_action)
            await bot.process_commands(message)
            return

        ai_response = await ai_brain_router(message, clean_text)
        if ai_response:
            await message.reply(ai_response, mention_author=False)
            await bot.process_commands(message)
            return

        await message.reply(
            "I’m here. Mention me with **link**, **win**, **loss**, or **push**.",
            mention_author=False
        )

    await bot.process_commands(message)

# =========================================================
# COMMANDS
# =========================================================

@bot.command(name="record")
async def record_command(ctx: commands.Context):
    await ctx.send(get_record_text())

@bot.command(name="resetrecord")
@commands.has_permissions(administrator=True)
async def reset_record_command(ctx: commands.Context):
    data_store["record"] = {
        "wins": 0,
        "losses": 0,
        "pushes": 0
    }
    data_store["graded_slips"] = []
    save_data(data_store)
    await ctx.send("📊 Record reset.")

@bot.command(name="picktraxhelp")
async def picktrax_help(ctx: commands.Context):
    bot_name = bot.user.display_name if bot.user else "Pick Trax"
    await ctx.send(
        "**Pick Trax Commands**\n"
        "`!record` → shows current record\n"
        "`!resetrecord` → resets tracked record (admin only)\n\n"
        "**Mention Triggers**\n"
        f"`@{bot_name} link it` → replies *I got you!*\n"
        f"`@{bot_name} link this` while replying to an image → reacts 🔗 on the image\n"
        f"`@{bot_name} grade this a loss` → grades loss\n"
        f"`@{bot_name} grade this a win` → grades win\n"
        f"`@{bot_name} grade this a push` → grades push"
    )

# =========================================================
# START
# =========================================================

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN environment variable.")

bot.run(DISCORD_TOKEN)
