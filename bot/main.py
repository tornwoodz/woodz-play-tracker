import os
import re
import json
import base64
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

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
MAX_RECENT_SCAN_MESSAGES = 15

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

def default_store() -> Dict[str, Any]:
    return {
        "graded_slips": [],
        "record": {
            "wins": 0,
            "losses": 0,
            "pushes": 0
        },
        "parsed_slips": []
    }

def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return default_store()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        if "graded_slips" not in loaded:
            loaded["graded_slips"] = []
        if "record" not in loaded:
            loaded["record"] = {"wins": 0, "losses": 0, "pushes": 0}
        if "parsed_slips" not in loaded:
            loaded["parsed_slips"] = []

        return loaded
    except Exception:
        return default_store()

def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

data_store = load_data()

# =========================================================
# GENERAL HELPERS
# =========================================================

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def clean_text_block(text: str) -> str:
    text = text or ""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

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

def has_any_attachment(message: discord.Message) -> bool:
    return bool(message.attachments)

def message_has_picktrax_mention(message: discord.Message) -> bool:
    return bot.user is not None and bot.user in message.mentions

def is_allowed_channel(message: discord.Message) -> bool:
    return message.channel.id in ALLOWED_CHANNEL_IDS

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
        "deeplink",
        "deep link",
    ]

    if "link" in text or "deeplink" in text or "deep link" in text:
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

def safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None

def compact_json_payload(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")

def truncate(text: str, max_len: int = 1800) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."

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
            "- track a basic record\n"
            "- parse text-based slips into a deep link foundation payload\n\n"
            "Next upgrades:\n"
            "- OCR bet slip reading from screenshots\n"
            "- sportsbook-specific deep links\n"
            "- auto leg extraction from images\n"
            "- AI recap generation\n"
            "- unit/profit tracking"
        )

    return None

# =========================================================
# TARGET MESSAGE RESOLUTION
# =========================================================

async def get_referenced_message(message: discord.Message) -> Optional[discord.Message]:
    if message.reference and message.reference.message_id:
        try:
            referenced = message.reference.resolved
            if referenced is None:
                referenced = await message.channel.fetch_message(message.reference.message_id)
            if isinstance(referenced, discord.Message):
                return referenced
        except Exception:
            return None
    return None

async def get_target_image_message(message: discord.Message) -> Optional[discord.Message]:
    if has_image_attachment(message):
        return message

    referenced = await get_referenced_message(message)
    if referenced and has_image_attachment(referenced):
        return referenced

    return None

async def get_recent_candidate_message(message: discord.Message) -> Optional[discord.Message]:
    # Fallback for natural behavior: find the most recent non-bot message
    # with content or attachments before the current command message.
    try:
        async for msg in message.channel.history(limit=MAX_RECENT_SCAN_MESSAGES + 1, before=message.created_at):
            if msg.author.bot:
                continue
            if msg.id == message.id:
                continue
            if has_any_attachment(msg) or clean_text_block(msg.content):
                return msg
    except Exception:
        return None
    return None

async def resolve_link_target_message(message: discord.Message) -> Optional[discord.Message]:
    # 1) Same message
    if has_any_attachment(message) or clean_text_block(message.content):
        return message

    # 2) Reply target
    referenced = await get_referenced_message(message)
    if referenced and (has_any_attachment(referenced) or clean_text_block(referenced.content)):
        return referenced

    # 3) Recent fallback
    recent = await get_recent_candidate_message(message)
    if recent:
        return recent

    return None

# =========================================================
# DEEP LINK FOUNDATION
# =========================================================

def empty_leg() -> Dict[str, Any]:
    return {
        "market_type": None,
        "selection": None,
        "line": None,
        "odds": None,
        "event": None,
        "league": None,
        "sport": None,
        "raw": None,
        "confidence": 0.0,
    }

def detect_sport_and_league(text: str) -> Dict[str, Optional[str]]:
    lower = normalize_text(text)

    if any(k in lower for k in ["nba", "lakers", "celtics", "knicks", "warriors", "rockets"]):
        return {"sport": "basketball", "league": "NBA"}
    if any(k in lower for k in ["ncaa", "ncaab", "march madness", "ohio state", "wisconsin", "vanderbilt", "louisville", "tcu", "nebraska"]):
        return {"sport": "basketball", "league": "NCAAB"}
    if any(k in lower for k in ["nfl", "touchdown", "passing yards", "rushing yards"]):
        return {"sport": "football", "league": "NFL"}
    if any(k in lower for k in ["mlb", "home runs", "strikeouts", "runs batted in"]):
        return {"sport": "baseball", "league": "MLB"}
    if any(k in lower for k in ["nhl", "shots on goal", "goals", "assists", "puck line"]):
        return {"sport": "hockey", "league": "NHL"}

    return {"sport": None, "league": None}

def parse_single_leg_from_line(line: str) -> Optional[Dict[str, Any]]:
    raw_line = clean_text_block(line)
    if not raw_line:
        return None

    lower = raw_line.lower()
    leg = empty_leg()
    leg["raw"] = raw_line

    meta = detect_sport_and_league(raw_line)
    leg["sport"] = meta["sport"]
    leg["league"] = meta["league"]

    odds_match = re.search(r"([+-]\d{3,4}|[+-]\d{2})\b", raw_line)
    if odds_match:
        leg["odds"] = odds_match.group(1)

    # Event matcher
    event_match = re.search(r"([A-Za-z0-9 .&'/-]+)\s+@\s+([A-Za-z0-9 .&'/-]+)", raw_line)
    if event_match:
        leg["event"] = f"{event_match.group(1).strip()} @ {event_match.group(2).strip()}"

    # Total points / over-under
    ou_match = re.search(r"\b(over|under)\s+(\d+(?:\.\d+)?)\b", lower)
    if ou_match:
        leg["market_type"] = "total"
        leg["selection"] = ou_match.group(1).title()
        leg["line"] = safe_float(ou_match.group(2))
        leg["confidence"] = 0.85
        return leg

    # Moneyline
    if "moneyline" in lower:
        leg["market_type"] = "moneyline"
        cleaned = re.sub(r"\bmoneyline\b", "", raw_line, flags=re.IGNORECASE).strip(" -")
        cleaned = re.sub(r"\s+[+-]\d{2,4}\b", "", cleaned).strip(" -")
        leg["selection"] = cleaned
        leg["confidence"] = 0.8
        return leg

    # Spread
    spread_match = re.search(r"([A-Za-z0-9 .&'/-]+)\s+([+-]\d+(?:\.\d+)?)\b", raw_line)
    if spread_match and ("spread" in lower or not ou_match):
        team_candidate = spread_match.group(1).strip()
        line_candidate = spread_match.group(2)
        if team_candidate and not team_candidate.lower().startswith(("over", "under")):
            leg["market_type"] = "spread"
            leg["selection"] = team_candidate
            leg["line"] = safe_float(line_candidate)
            leg["confidence"] = 0.72
            return leg

    # Player prop patterns
    player_prop_match = re.search(
        r"([A-Za-z .'-]+)\s+(\d+(?:\.\d+)?\+?)\s*(points|pts|rebounds|reb|assists|ast|pra|threes|3pm|hits|shots|goals)",
        lower,
        flags=re.IGNORECASE
    )
    if player_prop_match:
        leg["market_type"] = "player_prop"
        leg["selection"] = player_prop_match.group(1).title().strip()
        raw_line_val = player_prop_match.group(2).replace("+", "")
        leg["line"] = safe_float(raw_line_val)
        stat = player_prop_match.group(3).lower()
        leg["event"] = leg["event"] or stat.upper()
        leg["confidence"] = 0.7
        return leg

    return None

def parse_legs_from_text(text: str) -> List[Dict[str, Any]]:
    text = clean_text_block(text)
    if not text:
        return []

    raw_lines = [ln.strip("•*- ").strip() for ln in text.split("\n")]
    raw_lines = [ln for ln in raw_lines if ln]

    parsed: List[Dict[str, Any]] = []
    seen_raw = set()

    for line in raw_lines:
        leg = parse_single_leg_from_line(line)
        if leg and leg["raw"] not in seen_raw:
            parsed.append(leg)
            seen_raw.add(leg["raw"])

    return parsed

def build_canonical_slip(legs: List[Dict[str, Any]], source_message: discord.Message) -> Dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "version": "1.0",
        "source_message_id": str(source_message.id),
        "source_channel_id": str(source_message.channel.id),
        "source_author_id": str(source_message.author.id),
        "created_at": created_at,
        "legs": legs,
        "leg_count": len(legs),
    }
    return payload

def build_picktrax_internal_link(payload: Dict[str, Any]) -> str:
    encoded = compact_json_payload(payload)
    return f"picktrax://slip?payload={encoded}"

def build_picktrax_web_preview_link(payload: Dict[str, Any]) -> str:
    # Placeholder preview route for future web app/site
    encoded = compact_json_payload(payload)
    return f"https://picktrax.app/slip?payload={urllib.parse.quote(encoded)}"

def book_adapter_fanduel(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Foundation only: sportsbook-specific mapping comes next
    return {
        "book": "FanDuel",
        "status": "foundation_ready",
        "url": None,
        "reason": "Adapter scaffold created. Exact FanDuel mapping not added yet."
    }

def book_adapter_draftkings(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "book": "DraftKings",
        "status": "foundation_ready",
        "url": None,
        "reason": "Adapter scaffold created. Exact DraftKings mapping not added yet."
    }

def book_adapter_hardrock(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "book": "Hard Rock",
        "status": "foundation_ready",
        "url": None,
        "reason": "Adapter scaffold created. Exact Hard Rock mapping not added yet."
    }

def build_book_adapters(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        book_adapter_fanduel(payload),
        book_adapter_draftkings(payload),
        book_adapter_hardrock(payload),
    ]

def format_leg_summary(leg: Dict[str, Any], idx: int) -> str:
    parts = [f"**{idx}.**"]
    if leg.get("selection") is not None:
        parts.append(str(leg["selection"]))
    if leg.get("line") is not None:
        parts.append(str(leg["line"]))
    if leg.get("market_type"):
        parts.append(f"({leg['market_type']})")
    if leg.get("event"):
        parts.append(f"— {leg['event']}")
    if leg.get("odds"):
        parts.append(f"[{leg['odds']}]")
    return " ".join(parts)

async def extract_text_from_target_message(message: discord.Message) -> str:
    pieces: List[str] = []

    content = clean_text_block(message.content)
    if content:
        pieces.append(content)

    # Pull embed text when available
    for embed in message.embeds:
        if embed.title:
            pieces.append(embed.title)
        if embed.description:
            pieces.append(embed.description)
        for field in embed.fields:
            if field.name:
                pieces.append(field.name)
            if field.value:
                pieces.append(field.value)

    return clean_text_block("\n".join(pieces))

# =========================================================
# GRADE HANDLER
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
    target_message = await resolve_link_target_message(message)

    if target_message and has_image_attachment(target_message):
        try:
            await target_message.add_reaction("🔗")
        except Exception:
            pass

    target_text = ""
    if target_message:
        target_text = await extract_text_from_target_message(target_message)

    parsed_legs = parse_legs_from_text(target_text)
    payload = None
    adapters: List[Dict[str, Any]] = []

    if parsed_legs and target_message:
        payload = build_canonical_slip(parsed_legs, target_message)
        adapters = build_book_adapters(payload)

        data_store["parsed_slips"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload
        })
        save_data(data_store)

    response_lines = ["I got you!"]

    if parsed_legs and payload:
        response_lines.append("")
        response_lines.append(f"**Deep Link Foundation Ready**")
        response_lines.append(f"Recognized **{len(parsed_legs)}** leg(s).")
        response_lines.append("")
        response_lines.extend(format_leg_summary(leg, idx + 1) for idx, leg in enumerate(parsed_legs))
        response_lines.append("")
        response_lines.append("**Pick Trax Payload**")
        response_lines.append(f"`{truncate(build_picktrax_internal_link(payload), 350)}`")
        response_lines.append("")
        response_lines.append("**Book Adapters**")
        for adapter in adapters:
            response_lines.append(f"- {adapter['book']}: {adapter['status']}")
    else:
        response_lines.append("")
        response_lines.append("I found the slip target, but I still need OCR or text-based legs to turn it into sportsbook-ready deep links.")
        response_lines.append("Foundation is installed. Next step is OCR + book mapping.")

    try:
        await message.reply("\n".join(response_lines), mention_author=False)
    except Exception:
        try:
            await message.channel.send("\n".join(response_lines))
        except Exception:
            pass

# =========================================================
# COMMANDS / UTILITIES
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
        f"`@{bot_name} link it` → replies and starts deep link flow\n"
        f"`@{bot_name} link this` while replying to a message/image → reacts 🔗 and processes target\n"
        f"`@{bot_name} grade this a loss` → grades loss\n"
        f"`@{bot_name} grade this a win` → grades win\n"
        f"`@{bot_name} grade this a push` → grades push"
    )

@bot.command(name="parselegs")
async def parselegs_command(ctx: commands.Context, *, text: Optional[str] = None):
    source = text or ctx.message.content.replace("!parselegs", "", 1).strip()
    parsed = parse_legs_from_text(source)

    if not parsed:
        await ctx.send("No legs parsed.")
        return

    lines = [f"Parsed **{len(parsed)}** leg(s):"]
    lines.extend(format_leg_summary(leg, idx + 1) for idx, leg in enumerate(parsed))
    await ctx.send("\n".join(lines))

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
# START
# =========================================================

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN environment variable.")

bot.run(DISCORD_TOKEN)
