import os
import re
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import discord
from discord.ext import commands

# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Optional: if you want to limit actions to certain channels, add IDs here
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
        "link this",
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

    loss_patterns = [
        "grade this a loss",
        "grade as loss",
        "mark loss",
        "this is a loss",
        "graded loss",
        "grade loss",
        "loss",
        "l",
    ]

    win_patterns = [
        "grade this a win",
        "grade as win",
        "mark win",
        "this is a win",
        "graded win",
        "grade win",
        "win",
        "w",
    ]

    push_patterns = [
        "grade this a push",
        "grade as push",
        "mark push",
        "this is a push",
        "graded push",
        "grade push",
        "push",
        "void",
    ]

    # smarter checks first
    if "grade" in text or "mark" in text or "graded" in text:
        if "loss" in text:
            return "loss"
        if re.search(r"\bwin\b", text):
            return "win"
        if "push" in text or "void" in text:
            return "push"

    # fallback looser checks
    if any(p == text for p in loss_patterns):
        return "loss"
    if any(p == text for p in win_patterns):
        return "win"
    if any(p == text for p in push_patterns):
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
    # If you want it everywhere, just return True
    return message.channel.id in ALLOWED_CHANNEL_IDS

# =========================================================
# FUTURE AI PLACEHOLDER
# =========================================================

async def ai_brain_router(message: discord.Message, clean_text: str) -> Optional[str]:
    """
    Placeholder for future AI features.
    Right now this keeps your bot 'AI-ready' without requiring OpenAI setup yet.
    Later you can plug in:
    - OCR parsing
    - betslip extraction
    - auto summaries
    - smarter grading
    - auto recap
    """

    text = clean_text.lower()

    if "what can you do" in text or "help" in text:
        return (
            "**Pick Trax is live.**\n\n"
            "Here’s what I can do right now:\n"
            "- Respond when you @mention me\n"
            "- Detect link requests\n"
            "- React with 🔗 on image posts that need linking\n"
            "- Grade slips as win/loss/push\n"
            "- Track basic record\n\n"
            "Next upgrades:\n"
            "- OCR bet slip reading\n"
            "- Auto link formatting\n"
            "- AI recap generation\n"
            "- Unit/profit tracking\n"
            "- Daily/weekly summaries"
        )

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
    replied = False

    # react to image so you know it understands what needs to be done
    if has_image_attachment(message):
        try:
            await message.add_reaction("🔗")
        except Exception:
            pass

    # always reply when asked for a link while bot is mentioned
    try:
        await message.reply("I got you!", mention_author=False)
        replied = True
    except Exception:
        pass

    # placeholder for actual future link-building logic
    # later this is where you can parse the image, read slip text, and generate sportsbook links
    if not replied:
        try:
            await message.channel.send("I got you!")
        except Exception:
            pass

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

    # -----------------------------------------------------
    # ONLY respond when Pick Trax is actually mentioned
    # -----------------------------------------------------
    if message_has_picktrax_mention(message):
        # 1) link requests
        if is_link_request(clean_text):
            await handle_link_request(message)
            await bot.process_commands(message)
            return

        # 2) grade requests
        grade_action = detect_grade_action(clean_text)
        if grade_action:
            await handle_grade(message, grade_action)
            await bot.process_commands(message)
            return

        # 3) AI-ready responses
        ai_response = await ai_brain_router(message, clean_text)
        if ai_response:
            await message.reply(ai_response, mention_author=False)
            await bot.process_commands(message)
            return

        # 4) fallback response when mentioned but unclear
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
    await ctx.send(
        "**Pick Trax Commands**\n"
        "`!record` → shows current record\n"
        "`!resetrecord` → resets tracked record (admin only)\n\n"
        "**Mention Triggers**\n"
        f"`@{bot.user.display_name} link it` → replies *I got you!* and reacts 🔗 if image attached\n"
        f"`@{bot.user.display_name} grade this a loss` → grades loss\n"
        f"`@{bot.user.display_name} grade this a win` → grades win\n"
        f"`@{bot.user.display_name} grade this a push` → grades push"
    )

# =========================================================
# START
# =========================================================

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN environment variable.")

bot.run(DISCORD_TOKEN)
