import os
import re
import io
import json
import random
import asyncio
import aiohttp
import discord
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont

DATA_FILE = "picktrax_data.json"

# =========================================================
# CONFIG
# =========================================================

GENERAL_CHAT_ID = 1483436461423333376
VIP_GENERAL_CHAT_ID = 1483435285231702137
POST_YOUR_WINS_ID = 1483439779390427341
DAILY_RECAP_ID = 1483927105992392865

HAMMERS_CHANNEL_ID = 1483485837810335744
PARLAYS_CHANNEL_ID = 1483433966227947619
WEEKLY_LOCKS_CHANNEL_ID = 1483436117536542882
LIVE_BETS_CHANNEL_ID = 1483435130235260928

BOT_CONTROL_CHANNEL_ID = 1484587775188664460
TEST_CHANNEL_ID = 1484587826040275004

TRACKED_PICK_CHANNELS = {
    HAMMERS_CHANNEL_ID: "hammer",
    PARLAYS_CHANNEL_ID: "parlay",
    WEEKLY_LOCKS_CHANNEL_ID: "weekly",
    LIVE_BETS_CHANNEL_ID: "live",
}

TRACKED_PLAY_LABELS = {
    "hammer": "Hammer",
    "parlay": "Parlay",
    "weekly": "Weekly",
    "live": "Live",
    "test": "Test",
    "manual": "Manual",
}

CHANNEL_RECAP_TARGETS = {
    "hammer": HAMMERS_CHANNEL_ID,
    "parlay": PARLAYS_CHANNEL_ID,
    "weekly": WEEKLY_LOCKS_CHANNEL_ID,
    "live": LIVE_BETS_CHANNEL_ID,
}

WIN_SUBMISSION_CHANNELS = {
    GENERAL_CHAT_ID,
    VIP_GENERAL_CHAT_ID,
    HAMMERS_CHANNEL_ID,
    PARLAYS_CHANNEL_ID,
    WEEKLY_LOCKS_CHANNEL_ID,
    LIVE_BETS_CHANNEL_ID,
}

CLEANUP_CHANNEL_IDS = (
    WEEKLY_LOCKS_CHANNEL_ID,
    HAMMERS_CHANNEL_ID,
    PARLAYS_CHANNEL_ID,
    LIVE_BETS_CHANNEL_ID,
)

CLEANUP_TIMEZONE = os.getenv("CLEANUP_TIMEZONE", "America/New_York")

VIP_ROLE_NAME = "🏆VIP"
PUB_ROLE_NAME = "🆓PUB"

WIN_HYPE_MESSAGES = [
    "‼️‼️🐓 BANG BANG CHICKEN 🐓‼️‼️",
    "💰 CASH ITTTTT",
    "🧹 SWEPT",
    "🔒 LOCK CITY",
]

MEMBER_WIN_FORWARD_PHRASES = [
    "cash it",
    "cash this",
    "cashed",
    "cashed this",
    "this cashed",
    "bang",
    "banged",
    "this banged",
    "green",
    "green this",
    "winner",
    "won this",
    "this hit",
    "it hit",
    "we hit",
    "hit this",
    "smacked",
    "swept",
]

OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_API_KEY", "helloworld")
SUPPORTED_BOOKS = [
    b.strip().lower()
    for b in os.getenv(
        "SUPPORTED_BOOKS",
        "fanduel,draftkings,betmgm,caesars,espnbet,fanatics"
    ).split(",")
    if b.strip()
]

BOOK_URLS = {
    "fanduel": "https://sportsbook.fanduel.com/",
    "draftkings": "https://sportsbook.draftkings.com/",
    "betmgm": "https://sports.betmgm.com/",
    "caesars": "https://www.caesars.com/sportsbook-and-casino",
    "espnbet": "https://espnbet.com/",
    "fanatics": "https://sportsbook.fanatics.com/",
    "hardrockbet": "https://app.hardrock.bet/",
    "bet365": "https://www.bet365.com/",
}

TEAM_ALIASES = {
    "oklahoma city thunder": "Oklahoma City Thunder",
    "brooklyn nets": "Brooklyn Nets",
    "boston celtics": "Boston Celtics",
    "golden state warriors": "Golden State Warriors",
    "new york knicks": "New York Knicks",
    "los angeles lakers": "Los Angeles Lakers",
    "denver nuggets": "Denver Nuggets",
    "phoenix suns": "Phoenix Suns",
    "milwaukee bucks": "Milwaukee Bucks",
    "miami heat": "Miami Heat",
    "cleveland cavaliers": "Cleveland Cavaliers",
    "indiana pacers": "Indiana Pacers",
    "los angeles clippers": "Los Angeles Clippers",
    "new orleans pelicans": "New Orleans Pelicans",
    "portland trail blazers": "Portland Trail Blazers",
    "dallas mavericks": "Dallas Mavericks",
    "memphis grizzlies": "Memphis Grizzlies",
    "minnesota timberwolves": "Minnesota Timberwolves",
    "orlando magic": "Orlando Magic",
    "philadelphia 76ers": "Philadelphia 76ers",
    "sacramento kings": "Sacramento Kings",
    "toronto raptors": "Toronto Raptors",
    "atlanta hawks": "Atlanta Hawks",
    "detroit pistons": "Detroit Pistons",
    "chicago bulls": "Chicago Bulls",
    "utah jazz": "Utah Jazz",
    "washington wizards": "Washington Wizards",
    "charlotte hornets": "Charlotte Hornets",
    "san antonio spurs": "San Antonio Spurs",
    "houston rockets": "Houston Rockets",
    "miami (oh)": "Miami (OH)",
    "prairie view a&m": "Prairie View A&M",
    "tcu": "TCU",
    "ohio state": "Ohio State",
    "troy": "Troy",
    "nebraska": "Nebraska",
    "louisville": "Louisville",
    "wisconsin": "Wisconsin",
    "vanderbilt": "Vanderbilt",
    "smu": "SMU",
    "umbc": "UMBC",
    "howard": "Howard",
    "lehigh": "Lehigh",
    "south florida": "South Florida",
    "high point": "High Point",
    "mcneese": "McNeese",
    "houston": "Houston Rockets",
    "kansas": "Kansas",
    "kentucky": "Kentucky",
    "north carolina": "North Carolina",
    "villanova": "Villanova",
}

STAT_ALIASES = {
    "points": "Points",
    "point": "Points",
    "pts": "Points",
    "assists": "Assists",
    "assist": "Assists",
    "ast": "Assists",
    "rebounds": "Rebounds",
    "rebound": "Rebounds",
    "reb": "Rebounds",
    "three pointers": "3PT Made",
    "threes": "3PT Made",
    "3pt": "3PT Made",
    "3pt made": "3PT Made",
    "pra": "PRA",
    "pa": "Points + Assists",
    "pr": "Points + Rebounds",
    "ar": "Assists + Rebounds",
}

# =========================================================
# STORAGE
# =========================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def blank_record() -> dict:
    return {
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "units": 0.0,
    }


def default_data() -> dict:
    return {
        "owner_id": None,
        "show_dollars": False,
        "unit_value": 100.0,
        "record": blank_record(),
        "channel_records": {
            "hammer": blank_record(),
            "parlay": blank_record(),
            "weekly": blank_record(),
            "live": blank_record(),
        },
        "recap_message_ids": {
            "overall": None,
            "hammer": None,
            "parlay": None,
            "weekly": None,
            "live": None,
        },
        "picks": [],
        "graded_history": [],
        "message_pick_map": {},
        "registered_source_messages": [],
    }


def save_data(data_obj: dict) -> None:
    temp_file = f"{DATA_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data_obj, f, indent=2)
    os.replace(temp_file, DATA_FILE)


def ensure_data_shape(data_obj: dict) -> dict:
    defaults = default_data()
    for key, value in defaults.items():
        if key not in data_obj:
            data_obj[key] = value

    if not isinstance(data_obj.get("channel_records"), dict):
        data_obj["channel_records"] = {}

    for play_type in ["hammer", "parlay", "weekly", "live"]:
        if play_type not in data_obj["channel_records"] or not isinstance(data_obj["channel_records"][play_type], dict):
            data_obj["channel_records"][play_type] = blank_record()
        for k, v in blank_record().items():
            if k not in data_obj["channel_records"][play_type]:
                data_obj["channel_records"][play_type][k] = v

    if not isinstance(data_obj.get("recap_message_ids"), dict):
        data_obj["recap_message_ids"] = {}

    for key in ["overall", "hammer", "parlay", "weekly", "live"]:
        if key not in data_obj["recap_message_ids"]:
            data_obj["recap_message_ids"][key] = None

    if not isinstance(data_obj.get("picks"), list):
        data_obj["picks"] = []

    if not isinstance(data_obj.get("graded_history"), list):
        data_obj["graded_history"] = []

    if not isinstance(data_obj.get("message_pick_map"), dict):
        data_obj["message_pick_map"] = {}

    if not isinstance(data_obj.get("registered_source_messages"), list):
        data_obj["registered_source_messages"] = []

    return data_obj


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        data_obj = default_data()
        save_data(data_obj)
        return data_obj

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data_obj = json.load(f)
    except Exception:
        data_obj = default_data()
        save_data(data_obj)
        return data_obj

    data_obj = ensure_data_shape(data_obj)
    save_data(data_obj)
    return data_obj


data = load_data()

# =========================================================
# GENERAL HELPERS
# =========================================================

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def is_owner_user(user_id: int) -> bool:
    owner_id = data.get("owner_id")
    return owner_id is not None and user_id == owner_id


def is_test_channel(channel_id: Optional[int]) -> bool:
    return channel_id == TEST_CHANNEL_ID


def determine_play_type_for_channel(channel_id: int) -> Optional[str]:
    if channel_id in TRACKED_PICK_CHANNELS:
        return TRACKED_PICK_CHANNELS[channel_id]
    if is_test_channel(channel_id):
        return "test"
    return None


def format_profit(units: float) -> str:
    if data["show_dollars"]:
        dollars = units * float(data["unit_value"])
        sign = "+" if dollars >= 0 else ""
        return f"{sign}${dollars:,.2f}"
    sign = "+" if units >= 0 else ""
    return f"{sign}{units:.2f}U"


def record_stats(record: dict) -> tuple[int, int, int, float, float]:
    wins = int(record.get("wins", 0))
    losses = int(record.get("losses", 0))
    pushes = int(record.get("pushes", 0))
    units = float(record.get("units", 0.0))
    graded_decisions = wins + losses
    win_rate = (wins / graded_decisions * 100) if graded_decisions > 0 else 0.0
    return wins, losses, pushes, units, win_rate


def extract_units_from_text(text: str) -> float:
    if not text:
        return 1.0

    lowered = text.lower()
    patterns = [
        r"([+-]?\d+(?:\.\d+)?)\s*u\b",
        r"([+-]?\d+(?:\.\d+)?)\s*unit\b",
        r"([+-]?\d+(?:\.\d+)?)\s*units\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            try:
                return abs(float(match.group(1)))
            except Exception:
                pass

    return 1.0


def extract_odds_from_text(text: str) -> int:
    if not text:
        return -110

    match = re.search(r"(?<!\d)([+-]\d{3,4})(?!\d)", text)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass

    return -110


def parse_units_update(text: str) -> Optional[float]:
    lowered = normalize_text(text)
    patterns = [
        r"set units?\s+([+-]?\d+(?:\.\d+)?)",
        r"set\s+([+-]?\d+(?:\.\d+)?)\s*u\b",
        r"\bset\s+([+-]?\d+(?:\.\d+)?)\b",
        r"\bunits?\s+([+-]?\d+(?:\.\d+)?)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, lowered)
        if m:
            try:
                return abs(float(m.group(1)))
            except Exception:
                return None
    return None


def parse_odds_update(text: str) -> Optional[int]:
    lowered = normalize_text(text)
    patterns = [
        r"set odds?\s*([+-]\d{3,4})",
        r"\bodds?\s*([+-]\d{3,4})",
        r"\b([+-]\d{3,4})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, lowered)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def detect_result(text: str) -> Optional[str]:
    exact = text.strip().lower()

    if exact in {"win", "w", "cash", "cashed", "hit", "winner", "won", "green"}:
        return "win"
    if exact in {"loss", "l", "lost", "miss", "missed", "red"}:
        return "loss"
    if exact in {"push", "p"}:
        return "push"

    win_phrases = [
        "as a win",
        "grade win",
        "mark win",
        "this hit",
        "cash it",
        "cash this",
        "this won",
        "i won",
        "winner",
        "won this",
        "green this",
        "graded win",
        "we hit",
        "it hit",
        "banged",
        "bang",
        "banged this",
        "cashed this",
        "this cashed",
        "winner @",
    ]
    loss_phrases = [
        "as a loss",
        "grade loss",
        "mark loss",
        "it lost",
        "missed",
        "this lost",
        "graded loss",
        "this missed",
        "it missed",
        "red this",
    ]
    push_phrases = [
        "as a push",
        "grade push",
        "mark push",
        "this pushed",
        "graded push",
    ]

    for phrase in win_phrases:
        if phrase in exact:
            return "win"
    for phrase in loss_phrases:
        if phrase in exact:
            return "loss"
    for phrase in push_phrases:
        if phrase in exact:
            return "push"

    return None


def should_trigger_link_builder(content: str) -> bool:
    text = (content or "").lower().strip()

    if not re.search(r"\blink\b", text):
        return False

    blocked_phrases = [
        "grade this",
        "cash this",
        "mark win",
        "mark loss",
        "mark push",
        "grade win",
        "grade loss",
        "grade push",
        "this hit",
        "this lost",
        "this pushed",
        "won this",
        "green this",
        "red this",
        "track this play",
        "track this pick",
        "set units",
        "set odds",
    ]

    return not any(phrase in text for phrase in blocked_phrases)


def detect_ping_request(text: str) -> bool:
    t = normalize_text(text)
    return t == "ping" or " ping" in f" {t}" or "status" in t or "you there" in t


def detect_show_record_request(text: str) -> bool:
    t = normalize_text(text)
    patterns = [
        "show record",
        "show my record",
        "record",
        "show stats",
        "stats",
        "what's the record",
        "whats the record",
        "current record",
    ]
    return any(p in t for p in patterns)


def detect_channel_record_request(text: str) -> Optional[str]:
    t = normalize_text(text)

    if ("hammer" in t or "hammers" in t) and ("record" in t or "stats" in t):
        return "hammer"
    if ("parlay" in t or "parlays" in t) and ("record" in t or "stats" in t):
        return "parlay"
    if "weekly" in t and ("record" in t or "stats" in t):
        return "weekly"
    if ("live" in t or "live bets" in t) and ("record" in t or "stats" in t):
        return "live"

    return None


def detect_who_is_owner_request(text: str) -> bool:
    t = normalize_text(text)
    patterns = ["who is owner", "who's owner", "whos owner", "show owner", "owner?"]
    return any(p in t for p in patterns)


def detect_set_owner_request(text: str) -> bool:
    t = normalize_text(text)
    return "set owner" in t or "make owner" in t or "owner is" in t


def detect_reset_record_request(text: str) -> bool:
    return "reset record" in normalize_text(text)


def detect_cash_it_request(text: str) -> bool:
    return "cash it" in normalize_text(text)


def detect_let_it_ride_request(text: str) -> bool:
    t = normalize_text(text)
    return "let it ride" in t or "ride it" in t


def detect_track_this_play_request(text: str) -> bool:
    t = normalize_text(text)
    return "track this play" in t or "track this pick" in t or t == "track this"


def detect_grade_this_request(text: str) -> bool:
    return "grade this" in normalize_text(text)


def detect_set_values_request(text: str) -> bool:
    t = normalize_text(text)
    return "set units" in t or "set odds" in t or re.search(r"\bset\s+\d+(\.\d+)?u\b", t) is not None


def detect_show_tracked_plays_request(text: str) -> bool:
    t = normalize_text(text)
    phrases = [
        "show tracked plays",
        "tracked plays",
        "show picks",
        "show tracked picks",
        "show all tracked plays",
    ]
    return any(p in t for p in phrases)


def detect_remove_play_request(text: str) -> Optional[int]:
    t = normalize_text(text)
    patterns = [
        r"remove play\s+#?(\d+)",
        r"delete play\s+#?(\d+)",
        r"untrack play\s+#?(\d+)",
        r"remove tracked play\s+#?(\d+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, t)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def is_member_win_forward_request(text: str) -> bool:
    t = normalize_text(text)
    return any(phrase in t for phrase in MEMBER_WIN_FORWARD_PHRASES)


def get_best_member_role(member: discord.Member) -> str:
    role_names = {role.name for role in member.roles}

    if VIP_ROLE_NAME in role_names:
        return VIP_ROLE_NAME
    if PUB_ROLE_NAME in role_names:
        return PUB_ROLE_NAME

    custom_roles = [role for role in member.roles if role.name != "@everyone"]
    if custom_roles:
        top_role = max(custom_roles, key=lambda r: r.position)
        return top_role.name

    return "Member"


def find_pick_by_id(pick_id: int) -> Optional[dict]:
    combined = list(data.get("picks", [])) + list(data.get("graded_history", []))
    for pick in combined:
        if pick["id"] == pick_id:
            return pick
    return None


def find_pick_by_source_message_id(message_id: int) -> Optional[dict]:
    pick_id = data.get("message_pick_map", {}).get(str(message_id))
    if pick_id is None:
        return None
    return find_pick_by_id(int(pick_id))


def pending_picks() -> list:
    return [p for p in data["picks"] if p["status"] == "pending"]


def graded_history() -> list:
    return data["graded_history"]


def build_pick_embed(pick: dict) -> discord.Embed:
    color = discord.Color.blurple()
    if pick["status"] == "win":
        color = discord.Color.green()
    elif pick["status"] == "loss":
        color = discord.Color.red()
    elif pick["status"] == "push":
        color = discord.Color.light_grey()

    play_label = TRACKED_PLAY_LABELS.get(pick["play_type"], pick["play_type"].title())

    embed = discord.Embed(
        title=f"Pick #{pick['id']} • {play_label}",
        description=pick["bet"][:4000] if pick.get("bet") else "No description",
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

    if pick.get("source_channel_name"):
        embed.add_field(name="Source Channel", value=pick["source_channel_name"], inline=False)

    if pick.get("source_jump_url"):
        embed.add_field(name="Source Message", value=f"[Jump to original post]({pick['source_jump_url']})", inline=False)

    return embed


def build_overall_record_embed() -> discord.Embed:
    rec = data["record"]
    wins, losses, pushes, units, win_rate = record_stats(rec)

    embed = discord.Embed(
        title="📊 Official Overall Record",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Wins", value=str(wins), inline=True)
    embed.add_field(name="Losses", value=str(losses), inline=True)
    embed.add_field(name="Pushes", value=str(pushes), inline=True)
    embed.add_field(name="Profit", value=format_profit(units), inline=True)
    embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)
    embed.set_footer(text="This card updates automatically.")
    return embed


def build_channel_record_embed(play_type: str) -> discord.Embed:
    rec = data["channel_records"].get(play_type, blank_record())
    wins, losses, pushes, units, win_rate = record_stats(rec)

    embed = discord.Embed(
        title=f"📊 {TRACKED_PLAY_LABELS.get(play_type, play_type.title())} Record",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Wins", value=str(wins), inline=True)
    embed.add_field(name="Losses", value=str(losses), inline=True)
    embed.add_field(name="Pushes", value=str(pushes), inline=True)
    embed.add_field(name="Profit", value=format_profit(units), inline=True)
    embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)
    embed.set_footer(text="This card updates automatically.")
    return embed


def build_record_embed() -> discord.Embed:
    embed = build_overall_record_embed()
    for play_type in ["hammer", "parlay", "weekly", "live"]:
        cw, cl, cp, cu, cwr = record_stats(data["channel_records"].get(play_type, blank_record()))
        embed.add_field(
            name=f"{TRACKED_PLAY_LABELS[play_type]} Record",
            value=f"{cw}-{cl}-{cp} • {format_profit(cu)} • {cwr:.1f}%",
            inline=False,
        )
    return embed


def build_tracked_plays_embed(include_graded: bool = False) -> discord.Embed:
    active = sorted(data.get("picks", []), key=lambda p: p.get("id", 0))
    graded = sorted(data.get("graded_history", []), key=lambda p: p.get("id", 0), reverse=True)[:10]

    embed = discord.Embed(
        title="📌 Tracked Plays",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )

    if active:
        lines = []
        for p in active[:25]:
            lines.append(
                f"#{p['id']} • {TRACKED_PLAY_LABELS.get(p['play_type'], p['play_type'].title())} • "
                f"{p['status'].upper()} • {p['units']:.2f}U • {p['odds']:+d} • "
                f"{p.get('source_channel_name', 'unknown')}"
            )
        embed.add_field(name="Pending / Active", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="Pending / Active", value="None", inline=False)

    if include_graded:
        if graded:
            lines = []
            for p in graded:
                lines.append(
                    f"#{p['id']} • {TRACKED_PLAY_LABELS.get(p['play_type'], p['play_type'].title())} • "
                    f"{p['status'].upper()} • {format_profit(float(p.get('profit_units', 0.0)))}"
                )
            embed.add_field(name="Recent Graded", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Recent Graded", value="None", inline=False)

    embed.set_footer(text="Use /removeplay or /editplay with the play ID.")
    return embed


def find_target_user_for_owner(message: discord.Message) -> Optional[discord.Member]:
    others = [m for m in message.mentions if bot.user is None or m.id != bot.user.id]
    if others:
        member = others[0]
        if isinstance(member, discord.Member):
            return member

    text = normalize_text(message.content)
    if "set owner me" in text or "make me owner" in text:
        if isinstance(message.author, discord.Member):
            return message.author

    return None


def has_graphic(message: discord.Message) -> bool:
    return len(message.attachments) > 0 or len(message.embeds) > 0


def get_cleanup_tz() -> ZoneInfo:
    try:
        return ZoneInfo(CLEANUP_TIMEZONE)
    except Exception:
        return ZoneInfo("America/New_York")

# =========================================================
# IMAGE / OCR HELPERS
# =========================================================

def is_image_attachment(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower()
    name = (att.filename or "").lower()
    return ct.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))


async def ocr_image_attachment(att: discord.Attachment) -> str:
    if not is_image_attachment(att):
        return ""

    try:
        raw = await att.read()
    except Exception:
        return ""

    form = aiohttp.FormData()
    form.add_field("apikey", OCR_SPACE_API_KEY)
    form.add_field("language", "eng")
    form.add_field("isOverlayRequired", "false")
    form.add_field("OCREngine", "2")
    form.add_field("file", raw, filename=att.filename or "image.png", content_type=att.content_type or "image/png")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.ocr.space/parse/image", data=form, timeout=60) as resp:
                if resp.status != 200:
                    return ""
                payload = await resp.json()
    except Exception:
        return ""

    parsed = payload.get("ParsedResults") or []
    out = []
    for item in parsed:
        text = item.get("ParsedText")
        if text:
            out.append(text)
    return "\n".join(out).strip()


def clean_ocr_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r", "")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace("•", "• ")
    text = text.replace("|", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_ocr_lines(text: str) -> list[str]:
    junk_contains = [
        "must be 21",
        "call 1-800-gambler",
        "bet id",
        "my bets",
        "settled",
        "open",
        "saved",
        "cash out",
        "accept odds movements",
        "enter wager amount",
        "to win",
        "wager",
        "bonus bet",
        "same game parlay",
        "sgp",
        "professional sports bettor",
        "hit rate",
        "builders",
        "ovr",
        "psb",
        "woodzdabookie",
        "straight bets",
        "round robin",
        "save for later",
        "balance:$",
        "balance: $",
        "remove all selections",
    ]

    out = []
    for raw in clean_ocr_text(text).split("\n"):
        line = raw.strip()
        if not line:
            continue

        lower = line.lower()

        if any(j in lower for j in junk_contains):
            continue

        if re.fullmatch(r"\$?\d+(?:\.\d+)?", line):
            continue

        if re.fullmatch(r"[+-]\d{3,4}", line):
            continue

        if len(line) < 2:
            continue

        out.append(line)

    return out


def is_footer_or_betslip_junk_line(line: str) -> bool:
    lower = line.lower().strip()

    footer_starts = [
        "straight bets",
        "round robin",
        "accept odds movements",
        "save for later",
        "enter wager amount",
        "remove all selections",
        "wager",
        "to win",
        "balance:",
        "balance $",
        "balance:$",
    ]

    if any(lower.startswith(x) for x in footer_starts):
        return True

    if re.fullmatch(r"\$?\d+(?:\.\d+)?", lower):
        return True

    return False


def normalize_stat(raw: str) -> str:
    return STAT_ALIASES.get(raw.strip().lower(), raw.strip().title())


def normalize_team(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw).strip(" -")
    lowered = cleaned.lower()
    return TEAM_ALIASES.get(lowered, cleaned.title())


def normalize_player(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw).strip(" .-")
    return cleaned.title()


def leg_to_display(leg: dict) -> str:
    if leg["type"] == "player_prop":
        direction = leg.get("direction", "Over")
        comparator = leg.get("comparator", "")
        if comparator == "+":
            return f"{leg['player']} {leg['line']}+ {leg['stat']}"
        return f"{leg['player']} {direction} {leg['line']} {leg['stat']}"

    if leg["type"] == "spread":
        period = f" ({leg['period']})" if leg.get("period") else ""
        return f"{leg['team']} {leg['line']} Spread{period}"

    if leg["type"] == "moneyline":
        return f"{leg['team']} Moneyline"

    if leg["type"] == "total":
        matchup = f" — {leg['matchup']}" if leg.get("matchup") else ""
        return f"{leg['direction']} {leg['line']} Total{matchup}"

    return leg.get("raw", "Unknown leg")


def detect_sportsbook(ocr_text: str) -> str:
    t = (ocr_text or "").lower()

    if "bonus bet" in t or "same game parlay" in t or "accept odds movements" in t:
        return "fanduel"
    if "draftkings" in t:
        return "draftkings"
    if "betmgm" in t:
        return "betmgm"
    if "caesars" in t:
        return "caesars"
    if "fanatics" in t:
        return "fanatics"
    if "espnbet" in t or "espn bet" in t:
        return "espnbet"
    if "hard rock" in t or "hardrock" in t:
        return "hardrockbet"
    return "unknown"


def looks_like_matchup(line: str) -> bool:
    lower = line.lower()
    return " v " in lower or " vs " in lower or " @ " in lower


def is_schedule_or_status_line(line: str) -> bool:
    lower = line.lower().strip()

    if re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)\b", lower):
        return True
    if re.search(r"\b\d{1,2}:\d{2}\s*(am|pm)\b", lower):
        return True
    if lower.endswith(" et") or lower == "et":
        return True
    if lower == "live" or lower == "finished":
        return True
    return False


def group_lines_into_blocks(lines: list[str]) -> list[list[str]]:
    blocks = []
    current = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        if is_footer_or_betslip_junk_line(stripped):
            if current:
                blocks.append(current)
            break

        starts_new = False

        if re.search(r"^(over|under)\s+\d+(\.\d+)?$", stripped, re.IGNORECASE):
            starts_new = True
        elif re.search(r"^[a-z0-9&().' \-]+\s+(ml|moneyline)$", stripped, re.IGNORECASE):
            starts_new = True
        elif re.search(r"^[a-z0-9&().' \-]+\s+[+-]\d+(\.\d+)?$", stripped, re.IGNORECASE):
            starts_new = True
        elif re.search(r"^\d+(\.\d+)?\+\s+[a-z.'\- ]+\s*-\s*(points|assists|rebounds|pra|pa|pr|ar|pts|ast|reb)$", stripped, re.IGNORECASE):
            starts_new = True
        elif re.search(r"^[a-z.'\- ]+\s+(over|under)\s+\d+(\.\d+)?\s+(points|assists|rebounds|pra|pa|pr|ar|pts|ast|reb)$", stripped, re.IGNORECASE):
            starts_new = True
        elif i + 1 < len(lines) and lines[i + 1].strip().lower() == "moneyline":
            starts_new = True

        if starts_new and current:
            blocks.append(current)
            current = [stripped]
        else:
            current.append(stripped)

        i += 1

    if current:
        blocks.append(current)

    return blocks


def parse_single_line_leg(line: str) -> Optional[dict]:
    spread_period_match = re.search(
        r"^([A-Za-z0-9&()\.'](?:[A-Za-z0-9&()\. '\-]*[A-Za-z0-9&()\.'])?)\s+([+-]\d+(?:\.\d+)?)\s+(1st Half|1st Quarter|2nd Half|2nd Quarter|3rd Quarter|4th Quarter)$",
        line,
        re.IGNORECASE,
    )
    if spread_period_match:
        return {
            "type": "spread",
            "team": normalize_team(spread_period_match.group(1)),
            "line": spread_period_match.group(2),
            "period": spread_period_match.group(3).title(),
            "raw": line,
        }

    spread_match = re.search(
        r"^([A-Za-z0-9&()\.'](?:[A-Za-z0-9&()\. '\-]*[A-Za-z0-9&()\.'])?)\s+([+-]\d+(?:\.\d+)?)$",
        line,
        re.IGNORECASE,
    )
    if spread_match:
        return {
            "type": "spread",
            "team": normalize_team(spread_match.group(1)),
            "line": spread_match.group(2),
            "raw": line,
        }

    ml_match = re.search(
        r"^([A-Za-z0-9&()\.'](?:[A-Za-z0-9&()\. '\-]*[A-Za-z0-9&()\.'])?)\s+(ML|Moneyline)$",
        line,
        re.IGNORECASE,
    )
    if ml_match:
        return {
            "type": "moneyline",
            "team": normalize_team(ml_match.group(1)),
            "raw": line,
        }

    total_match = re.search(
        r"^(Over|Under)\s+(\d+(?:\.\d+)?)$",
        line,
        re.IGNORECASE,
    )
    if total_match:
        return {
            "type": "total",
            "direction": total_match.group(1).title(),
            "line": total_match.group(2),
            "raw": line,
        }

    player_plus_match = re.search(
        r"^(\d+(?:\.\d+)?)\+\s+([A-Za-z\.'\-\s]+?)\s*-\s*(Points|Assists|Rebounds|PRA|PA|PR|AR|Pts|Ast|Reb)$",
        line,
        re.IGNORECASE,
    )
    if player_plus_match:
        return {
            "type": "player_prop",
            "player": normalize_player(player_plus_match.group(2)),
            "line": player_plus_match.group(1),
            "comparator": "+",
            "stat": normalize_stat(player_plus_match.group(3)),
            "raw": line,
        }

    player_ou_match = re.search(
        r"^([A-Za-z\.'\-\s]+?)\s+(Over|Under)\s+(\d+(?:\.\d+)?)\s+(Points|Assists|Rebounds|PRA|PA|PR|AR|Pts|Ast|Reb)$",
        line,
        re.IGNORECASE,
    )
    if player_ou_match:
        return {
            "type": "player_prop",
            "player": normalize_player(player_ou_match.group(1)),
            "direction": player_ou_match.group(2).title(),
            "line": player_ou_match.group(3),
            "stat": normalize_stat(player_ou_match.group(4)),
            "raw": line,
        }

    return None


def parse_grouped_blocks(blocks: list[list[str]]) -> list[dict]:
    legs = []

    for block in blocks:
        filtered_block = []
        for line in block:
            if is_footer_or_betslip_junk_line(line):
                break
            if not is_schedule_or_status_line(line):
                filtered_block.append(line)

        if not filtered_block:
            continue

        text = " | ".join(filtered_block)

        parsed = None
        for line in filtered_block:
            parsed = parse_single_line_leg(line)
            if parsed:
                break

        if parsed:
            if parsed["type"] == "total":
                for b in filtered_block:
                    if looks_like_matchup(b):
                        parsed["matchup"] = b
                        break
            legs.append(parsed)
            continue

        if len(filtered_block) >= 2:
            team_line = filtered_block[0]
            market_line = filtered_block[1].strip().lower()

            if market_line == "moneyline":
                leg = {
                    "type": "moneyline",
                    "team": normalize_team(team_line),
                    "raw": text,
                }

                for extra in filtered_block[2:]:
                    if looks_like_matchup(extra):
                        leg["matchup"] = extra
                        break

                legs.append(leg)
                continue

        if len(filtered_block) >= 2:
            first = filtered_block[0]
            second = filtered_block[1]

            m_total = re.search(r"^(Over|Under)\s+(\d+(?:\.\d+)?)$", first, re.IGNORECASE)
            if m_total and ("total" in second.lower()):
                leg = {
                    "type": "total",
                    "direction": m_total.group(1).title(),
                    "line": m_total.group(2),
                    "raw": text,
                }
                matchup_lines = [x for x in filtered_block[2:] if not is_schedule_or_status_line(x)]
                if len(matchup_lines) >= 2:
                    leg["matchup"] = f"{normalize_team(matchup_lines[0])} vs {normalize_team(matchup_lines[1])}"
                elif len(matchup_lines) == 1:
                    leg["matchup"] = matchup_lines[0]
                legs.append(leg)
                continue

        if len(filtered_block) >= 2 and filtered_block[1].lower() == "moneyline":
            legs.append({
                "type": "moneyline",
                "team": normalize_team(filtered_block[0]),
                "raw": text,
            })
            continue

        m_spread = re.search(
            r"^([A-Za-z0-9&()\.'](?:[A-Za-z0-9&()\. '\-]*[A-Za-z0-9&()\.'])?)\s+([+-]\d+(?:\.\d+)?)$",
            filtered_block[0],
            re.IGNORECASE,
        ) if filtered_block else None
        if m_spread and len(filtered_block) >= 2 and "spread" in filtered_block[1].lower():
            leg = {
                "type": "spread",
                "team": normalize_team(m_spread.group(1)),
                "line": m_spread.group(2),
                "raw": text,
            }
            for extra in filtered_block[2:]:
                if looks_like_matchup(extra):
                    leg["matchup"] = extra
                    break
            legs.append(leg)
            continue

        if len(filtered_block) >= 3:
            player_line = filtered_block[0]
            line_line = filtered_block[1]
            stat_line = filtered_block[2]

            if re.search(r"^\d+(\.\d+)?\+$", line_line) and stat_line.lower() in {
                "points", "assists", "rebounds", "pra", "pa", "pr", "ar", "pts", "ast", "reb"
            }:
                legs.append({
                    "type": "player_prop",
                    "player": normalize_player(player_line),
                    "line": line_line.replace("+", ""),
                    "comparator": "+",
                    "stat": normalize_stat(stat_line),
                    "raw": text,
                })
                continue

    deduped = []
    seen = set()
    for leg in legs:
        key = json.dumps(leg, sort_keys=True)
        if key not in seen:
            seen.add(key)
            deduped.append(leg)

    return deduped


def parse_fanduel_legs(ocr_text: str) -> list[dict]:
    lines = clean_ocr_lines(ocr_text)
    blocks = group_lines_into_blocks(lines)
    return parse_grouped_blocks(blocks)


def parse_generic_legs(ocr_text: str) -> list[dict]:
    lines = clean_ocr_lines(ocr_text)
    blocks = group_lines_into_blocks(lines)
    return parse_grouped_blocks(blocks)


def parse_betslip_meta(ocr_text: str) -> dict:
    cleaned = clean_ocr_text(ocr_text)
    odds = extract_odds_from_text(cleaned)
    leg_count = None

    m = re.search(r"(\d+)\s*LEG", cleaned, re.IGNORECASE)
    if m:
        try:
            leg_count = int(m.group(1))
        except Exception:
            leg_count = None

    return {"odds": odds, "leg_count": leg_count}


def score_parse_confidence(book: str, legs: list[dict], meta: dict, ocr_text: str) -> tuple[int, str]:
    score = 0

    if book != "unknown":
        score += 2
    if meta.get("leg_count"):
        score += 2
    if meta.get("odds"):
        score += 1

    score += min(len(legs), 8)

    leg_count = meta.get("leg_count")
    if leg_count and legs:
        diff = abs(leg_count - len(legs))
        if diff == 0:
            score += 3
        elif diff == 1:
            score += 1
        else:
            score -= min(diff, 3)

    if len(clean_ocr_lines(ocr_text)) < 3:
        score -= 2

    if score >= 10:
        return score, "high"
    if score >= 6:
        return score, "medium"
    return score, "low"


def build_book_search_query(legs: list[dict]) -> str:
    return " | ".join(leg_to_display(leg) for leg in legs[:8])


class SportsbookLinksView(discord.ui.View):
    def __init__(self, legs: list[dict]):
        super().__init__(timeout=600)
        query = build_book_search_query(legs)

        for book in SUPPORTED_BOOKS[:5]:
            url = BOOK_URLS.get(book)
            if not url:
                continue

            target = f"{url}?q={quote_plus(query)}" if query else url
            self.add_item(discord.ui.Button(label=book.title(), url=target))

# =========================================================
# LINK / WIN CONTEXT HELPERS
# =========================================================

async def resolve_target_message_for_link(message: discord.Message) -> Optional[discord.Message]:
    if message.reference and message.reference.message_id:
        try:
            if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
                return message.reference.resolved
            return await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            return None
    return message


async def get_forwardable_win_context(message: discord.Message) -> tuple[list[discord.Attachment], Optional[discord.Message]]:
    current_images = [a for a in message.attachments if is_image_attachment(a)]
    if current_images:
        return current_images, message

    if message.reference and message.reference.message_id:
        try:
            if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
                source = message.reference.resolved
            else:
                source = await message.channel.fetch_message(message.reference.message_id)
            source_images = [a for a in source.attachments if is_image_attachment(a)]
            if source_images:
                return source_images, source
        except Exception:
            pass

    return [], None


async def build_link_this_response(message: discord.Message) -> tuple[discord.Embed, Optional[discord.ui.View], Optional[discord.File], dict]:
    target_message = await resolve_target_message_for_link(message)
    if target_message is None:
        return (
            discord.Embed(
                title="🔗 Pick Trax Betslip Builder",
                description="Reply to a betslip image or attach one when you say `link`.",
                color=discord.Color.red(),
            ),
            None,
            None,
            {},
        )

    image_attachments = [a for a in target_message.attachments if is_image_attachment(a)]
    if not image_attachments:
        return (
            discord.Embed(
                title="🔗 Pick Trax Betslip Builder",
                description="I couldn't find an image on that message.",
                color=discord.Color.red(),
            ),
            None,
            None,
            {},
        )

    att = image_attachments[0]
    ocr_text = await ocr_image_attachment(att)
    cleaned = clean_ocr_text(ocr_text)

    book = detect_sportsbook(cleaned)
    meta = parse_betslip_meta(cleaned)
    if book == "fanduel":
        legs = parse_fanduel_legs(cleaned)
    else:
        legs = parse_generic_legs(cleaned)

    score, confidence = score_parse_confidence(book, legs, meta, cleaned)

    desc_lines = []
    if legs:
        for idx, leg in enumerate(legs[:12], start=1):
            desc_lines.append(f"{idx}. {leg_to_display(leg)}")
    else:
        desc_lines.append("I couldn't confidently parse the legs from this slip.")

    if meta.get("odds"):
        desc_lines.append(f"\nOdds detected: {int(meta['odds']):+d}")
    if meta.get("leg_count"):
        desc_lines.append(f"Leg count detected: {meta['leg_count']}")
    desc_lines.append(f"Sportsbook: {book.title() if book != 'unknown' else 'Unknown'}")
    desc_lines.append(f"Confidence: {confidence.upper()} ({score})")

    embed = discord.Embed(
        title="🔗 Pick Trax Betslip Builder",
        description="\n".join(desc_lines)[:4000],
        color=discord.Color.green() if legs else discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )

    if target_message.jump_url:
        embed.add_field(name="Source", value=f"[Jump to slip]({target_message.jump_url})", inline=False)

    view = SportsbookLinksView(legs) if legs else None
    return embed, view, None, {"book": book, "legs": legs, "meta": meta, "ocr_text": cleaned}

# =========================================================
# RECAP CARD HELPERS
# =========================================================

async def _fetch_channel_message(channel: discord.TextChannel, message_id: Optional[int]) -> Optional[discord.Message]:
    if not message_id:
        return None
    try:
        return await channel.fetch_message(int(message_id))
    except Exception:
        return None


def _is_recap_embed_message(message: discord.Message, title: str) -> bool:
    if not message.author.bot or not message.embeds:
        return False
    embed = message.embeds[0]
    return (
        (embed.title or "") == title
        and "updates automatically" in ((embed.footer.text or "").lower() if embed.footer else "")
    )


async def _cleanup_duplicate_recap_messages(channel: discord.TextChannel, title: str, keep_message_id: Optional[int] = None) -> Optional[discord.Message]:
    matches = []
    try:
        async for msg in channel.history(limit=50):
            if _is_recap_embed_message(msg, title):
                matches.append(msg)
    except Exception:
        return None

    if not matches:
        return None

    matches.sort(key=lambda m: m.created_at, reverse=True)

    keeper = None
    if keep_message_id:
        for msg in matches:
            if msg.id == keep_message_id:
                keeper = msg
                break

    if keeper is None:
        keeper = matches[0]

    for msg in matches:
        if msg.id != keeper.id:
            try:
                await msg.delete()
            except Exception:
                pass

    try:
        if not keeper.pinned:
            await keeper.pin(reason="Pick Trax live recap card")
    except Exception:
        pass

    return keeper


async def _ensure_recap_message(
    channel: discord.TextChannel,
    recap_key: str,
    embed: discord.Embed,
    pin_message: bool = True,
) -> None:
    title = embed.title or ""
    existing_id = data["recap_message_ids"].get(recap_key)

    existing_msg = await _fetch_channel_message(channel, existing_id)
    cleaned_keeper = await _cleanup_duplicate_recap_messages(channel, title, existing_id)
    if cleaned_keeper is not None:
        existing_msg = cleaned_keeper

    if existing_msg:
        try:
            await existing_msg.edit(embed=embed, content=None)
            data["recap_message_ids"][recap_key] = existing_msg.id
            save_data(data)

            if pin_message:
                try:
                    if not existing_msg.pinned:
                        await existing_msg.pin(reason="Pick Trax live recap card")
                except Exception:
                    pass
            return
        except Exception:
            pass

    try:
        new_msg = await channel.send(embed=embed)
        data["recap_message_ids"][recap_key] = new_msg.id
        save_data(data)

        if pin_message:
            try:
                await new_msg.pin(reason="Pick Trax live recap card")
            except Exception:
                pass

        keeper = await _cleanup_duplicate_recap_messages(channel, title, new_msg.id)
        if keeper:
            data["recap_message_ids"][recap_key] = keeper.id
            save_data(data)
    except Exception as e:
        print(f"Failed creating recap card {recap_key}: {e}")


async def update_recap_cards(guild: discord.Guild) -> None:
    overall_channel = guild.get_channel(DAILY_RECAP_ID)
    if isinstance(overall_channel, discord.TextChannel):
        await _ensure_recap_message(
            overall_channel,
            "overall",
            build_overall_record_embed(),
            pin_message=True,
        )

    for play_type, channel_id in CHANNEL_RECAP_TARGETS.items():
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            await _ensure_recap_message(
                channel,
                play_type,
                build_channel_record_embed(play_type),
                pin_message=True,
            )

# =========================================================
# WEEKLY CLEANUP HELPERS
# =========================================================

async def clear_channel_non_pinned_messages(channel: discord.TextChannel) -> None:
    try:
        pinned_messages = await channel.pins()
        pinned_ids = {m.id for m in pinned_messages}
    except Exception as e:
        print(f"[CLEANUP] Failed to fetch pins for #{channel.name}: {e}")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    newer_than_14 = []
    older_than_14 = []

    try:
        async for msg in channel.history(limit=None, oldest_first=False):
            if msg.id in pinned_ids:
                continue

            if msg.created_at >= cutoff:
                newer_than_14.append(msg)
            else:
                older_than_14.append(msg)
    except Exception as e:
        print(f"[CLEANUP] Failed to read history for #{channel.name}: {e}")
        return

    if newer_than_14:
        for i in range(0, len(newer_than_14), 100):
            chunk = newer_than_14[i:i + 100]
            try:
                if len(chunk) == 1:
                    await chunk[0].delete()
                else:
                    await channel.delete_messages(chunk)
                await asyncio.sleep(1)
            except Exception:
                for msg in chunk:
                    try:
                        await msg.delete()
                        await asyncio.sleep(0.35)
                    except Exception:
                        pass

    for msg in older_than_14:
        try:
            await msg.delete()
            await asyncio.sleep(0.35)
        except Exception:
            pass

    print(f"[CLEANUP] Finished #{channel.name} • kept pinned • deleted non-pinned")


def get_next_sunday_midnight(now_local: datetime) -> datetime:
    target = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    days_until_sunday = (6 - now_local.weekday()) % 7

    if days_until_sunday == 0 and now_local >= target:
        days_until_sunday = 7

    return target + timedelta(days=days_until_sunday)


async def weekly_cleanup_loop():
    await bot.wait_until_ready()

    tz = get_cleanup_tz()
    print(f"[CLEANUP] Weekly cleanup scheduler started in timezone: {tz}")

    while not bot.is_closed():
        now_local = datetime.now(tz)
        next_run = get_next_sunday_midnight(now_local)
        sleep_seconds = max((next_run - now_local).total_seconds(), 1)

        print(f"[CLEANUP] Next cleanup scheduled for {next_run.isoformat()}")
        await asyncio.sleep(sleep_seconds)

        for guild in bot.guilds:
            for channel_id in CLEANUP_CHANNEL_IDS:
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        await clear_channel_non_pinned_messages(channel)
                    except Exception as e:
                        print(f"[CLEANUP] Error cleaning #{channel.name}: {e}")

# =========================================================
# PICK TRACKING / RECAP HELPERS
# =========================================================

async def forward_owner_win(guild: discord.Guild, pick: dict, source_message: Optional[discord.Message]) -> None:
    if source_message and is_test_channel(source_message.channel.id):
        return

    wins_channel = guild.get_channel(POST_YOUR_WINS_ID)
    if wins_channel is None:
        return

    owner_id = data.get("owner_id")
    capper_text = f"<@{owner_id}>" if owner_id else "Official Pick"

    embed = discord.Embed(
        title="🏆 Official Win",
        description=pick["bet"][:4000],
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Capper", value=capper_text, inline=True)
    embed.add_field(name="Units", value=f"{pick['units']:.2f}U", inline=True)
    embed.add_field(name="Odds", value=f"{pick['odds']:+d}", inline=True)
    embed.add_field(name="Profit", value=format_profit(pick["profit_units"]), inline=True)
    if pick.get("source_channel_name"):
        embed.add_field(name="Source", value=pick["source_channel_name"], inline=True)

    files = []
    if source_message:
        for attachment in source_message.attachments:
            try:
                files.append(await attachment.to_file())
            except Exception:
                pass

    try:
        await wins_channel.send(embed=embed, files=files)
    except Exception as e:
        print(f"Failed forwarding official win: {e}")


async def forward_member_win(message: discord.Message) -> bool:
    if is_test_channel(message.channel.id):
        return False

    wins_channel = message.guild.get_channel(POST_YOUR_WINS_ID)
    if wins_channel is None:
        print("Could not find post-your-wins channel by ID.")
        return False

    image_attachments, source_message = await get_forwardable_win_context(message)
    if not image_attachments:
        print("No image attachment found on current or replied message.")
        return False

    role_name = get_best_member_role(message.author)

    embed = discord.Embed(
        title="🏆 New Winner Submitted",
        description=message.content[:4000] if message.content else "Winner submitted",
        color=discord.Color.green() if role_name == VIP_ROLE_NAME else discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=message.author.mention, inline=True)
    embed.add_field(name="Role", value=role_name, inline=True)
    embed.add_field(name="Source", value=message.channel.mention, inline=True)

    if source_message and source_message.id != message.id:
        embed.add_field(name="Betslip Source", value=f"[Reply Target Jump]({source_message.jump_url})", inline=False)

    files = []
    for attachment in image_attachments:
        try:
            files.append(await attachment.to_file())
        except Exception as e:
            print(f"attachment error: {e}")

    if not files:
        print("No files were converted for forwarding.")
        return False

    try:
        await wins_channel.send(embed=embed, files=files)
        await message.add_reaction("✅")
        return True
    except Exception as e:
        print(f"Failed forwarding winner: {e}")
        return False


def apply_grade_to_pick(pick: dict, result: str, grader_id: int) -> tuple[bool, str]:
    if pick["status"] != "pending":
        return False, "That pick is already graded."

    odds = int(pick["odds"])
    units = float(pick["units"])
    channel_type = pick.get("channel_type") or pick.get("play_type")

    pick["status"] = result
    pick["result"] = result
    pick["graded_at"] = utc_now_iso()
    pick["graded_by"] = grader_id

    if result == "win":
        if odds > 0:
            profit_units = units * (odds / 100)
        else:
            profit_units = units * (100 / abs(odds))
        if channel_type != "test":
            data["record"]["wins"] += 1
            if channel_type in data["channel_records"]:
                data["channel_records"][channel_type]["wins"] += 1
    elif result == "loss":
        profit_units = -units
        if channel_type != "test":
            data["record"]["losses"] += 1
            if channel_type in data["channel_records"]:
                data["channel_records"][channel_type]["losses"] += 1
    else:
        profit_units = 0.0
        if channel_type != "test":
            data["record"]["pushes"] += 1
            if channel_type in data["channel_records"]:
                data["channel_records"][channel_type]["pushes"] += 1

    pick["profit_units"] = round(profit_units, 4)

    if channel_type != "test":
        data["record"]["units"] = round(data["record"]["units"] + profit_units, 4)

        if channel_type in data["channel_records"]:
            data["channel_records"][channel_type]["units"] = round(
                data["channel_records"][channel_type]["units"] + profit_units,
                4,
            )

    data["picks"] = [p for p in data["picks"] if p["status"] == "pending"]
    data["graded_history"].append(pick)
    save_data(data)

    return True, (
        f"✅ Pick #{pick['id']} graded as **{result.upper()}**\n"
        f"Units: {pick['units']:.2f}U\n"
        f"Profit: {format_profit(pick['profit_units'])}"
    )


def build_pick_from_message(message: discord.Message, play_type: str) -> dict:
    next_id = len(data["picks"]) + len(data["graded_history"]) + 1
    units = extract_units_from_text(message.content)
    odds = extract_odds_from_text(message.content)

    return {
        "id": next_id,
        "bet": message.content[:500] if message.content else f"Graphic pick from message {message.id}",
        "units": units,
        "odds": odds,
        "status": "pending",
        "created_by": message.author.id,
        "created_at": utc_now_iso(),
        "graded_at": None,
        "graded_by": None,
        "result": None,
        "profit_units": 0.0,
        "play_type": play_type,
        "channel_type": play_type,
        "source_message_id": message.id,
        "source_channel_id": message.channel.id,
        "source_channel_name": f"#{message.channel.name}",
        "source_jump_url": message.jump_url,
    }


def register_pick(pick: dict) -> dict:
    data["picks"].append(pick)
    data["message_pick_map"][str(pick["source_message_id"])] = pick["id"]
    if pick["source_message_id"] not in data["registered_source_messages"]:
        data["registered_source_messages"].append(pick["source_message_id"])
    save_data(data)
    return pick


def create_auto_pick_from_message(message: discord.Message, play_type: str) -> dict:
    pick = build_pick_from_message(message, play_type)
    return register_pick(pick)


async def add_pin_reaction(message: discord.Message) -> None:
    try:
        await message.add_reaction("📌")
    except Exception:
        pass


async def post_tracking_card(channel: discord.abc.Messageable, pick: dict, prefix: Optional[str] = None) -> None:
    content = prefix or f"📌 Pick #{pick['id']} tracked and waiting to be graded."
    await channel.send(
        content=content,
        embed=build_pick_embed(pick),
        view=GradeView(pick["id"]),
    )


async def ensure_pick_tracked_from_message(source_message: discord.Message, owner_id: int) -> tuple[Optional[dict], str]:
    if not is_owner_user(owner_id):
        return None, "Only the owner can track official picks."

    if source_message.author.bot:
        return None, "You can only track a real source message, not a bot message."

    play_type = determine_play_type_for_channel(source_message.channel.id)
    if play_type is None:
        return None, "That message is not in one of your tracked official channels."

    if not has_graphic(source_message):
        return None, "That post needs an image or embed to be tracked."

    existing = find_pick_by_source_message_id(source_message.id)
    if existing:
        return existing, "existing"

    pick = create_auto_pick_from_message(source_message, play_type)
    await add_pin_reaction(source_message)
    return pick, "created"


def reset_all_records() -> None:
    data["record"] = blank_record()
    data["channel_records"] = {
        "hammer": blank_record(),
        "parlay": blank_record(),
        "weekly": blank_record(),
        "live": blank_record(),
    }
    data["picks"] = []
    data["graded_history"] = []
    data["message_pick_map"] = {}
    data["registered_source_messages"] = []
    save_data(data)


def update_pending_pick_values(pick: dict, units: Optional[float], odds: Optional[int]) -> tuple[bool, str]:
    if pick["status"] != "pending":
        return False, "You can only edit units/odds on pending picks."

    changed = []

    if units is not None:
        if units <= 0:
            return False, "Units must be greater than 0."
        pick["units"] = round(float(units), 4)
        changed.append(f"Units: {pick['units']:.2f}U")

    if odds is not None:
        pick["odds"] = int(odds)
        changed.append(f"Odds: {pick['odds']:+d}")

    if not changed:
        return False, "I couldn't find units or odds to update."

    save_data(data)
    return True, " • ".join(changed)


def remove_pick_by_id(pick_id: int) -> tuple[bool, str]:
    pending = data.get("picks", [])
    graded = data.get("graded_history", [])

    pending_match = next((p for p in pending if p["id"] == pick_id), None)
    if pending_match:
        data["picks"] = [p for p in pending if p["id"] != pick_id]
        source_message_id = str(pending_match.get("source_message_id"))
        if source_message_id in data.get("message_pick_map", {}):
            data["message_pick_map"].pop(source_message_id, None)
        try:
            sid = int(source_message_id)
            data["registered_source_messages"] = [x for x in data.get("registered_source_messages", []) if int(x) != sid]
        except Exception:
            pass
        save_data(data)
        return True, f"🗑️ Removed pending Pick #{pick_id}."

    graded_match = next((p for p in graded if p["id"] == pick_id), None)
    if graded_match:
        return False, "You can only remove pending/untracked mistakes with remove. Graded plays should not be deleted casually."

    return False, f"Pick #{pick_id} was not found in pending tracked plays."


def owner_only_check(user_id: int) -> bool:
    owner_id = data.get("owner_id")
    return owner_id is None or user_id == owner_id

# =========================================================
# DISCORD SETUP
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)


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

        if interaction.guild:
            source_message = None
            try:
                if pick.get("source_channel_id") and pick.get("source_message_id"):
                    source_channel = interaction.guild.get_channel(pick["source_channel_id"]) or interaction.channel
                    source_message = await source_channel.fetch_message(pick["source_message_id"])
            except Exception:
                pass

            if result == "win" and not is_test_channel(interaction.channel.id):
                await forward_owner_win(interaction.guild, pick, source_message)
                await interaction.followup.send(random.choice(WIN_HYPE_MESSAGES))

            if not is_test_channel(interaction.channel.id):
                await update_recap_cards(interaction.guild)

    @discord.ui.button(label="Win", style=discord.ButtonStyle.success, custom_id="picktrax_win")
    async def win_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.grade_pick(interaction, "win")

    @discord.ui.button(label="Loss", style=discord.ButtonStyle.danger, custom_id="picktrax_loss")
    async def loss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.grade_pick(interaction, "loss")

    @discord.ui.button(label="Push", style=discord.ButtonStyle.secondary, custom_id="picktrax_push")
    async def push_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.grade_pick(interaction, "push")

# =========================================================
# EVENTS
# =========================================================

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Sync error: {e}")

    print(f"🔥 Logged in as {bot.user} ({bot.user.id})")

    if not hasattr(bot, "weekly_cleanup_started"):
        bot.weekly_cleanup_started = True
        bot.loop.create_task(weekly_cleanup_loop())

    for guild in bot.guilds:
        try:
            await update_recap_cards(guild)
        except Exception as e:
            print(f"Failed updating recap cards on ready for guild {guild.id}: {e}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").strip()
    lowered = content.lower()
    bot_mentioned = bot.user in message.mentions if bot.user else False

    # Auto-track fresh owner picks in tracked and test channels
    if message.author.id == data.get("owner_id"):
        play_type = determine_play_type_for_channel(message.channel.id)
        if play_type and has_graphic(message):
            if message.id not in data.get("registered_source_messages", []):
                pick = create_auto_pick_from_message(message, play_type)

                await add_pin_reaction(message)

                try:
                    await post_tracking_card(
                        message.channel,
                        pick,
                        prefix=f"📌 Pick #{pick['id']} tracked • {TRACKED_PLAY_LABELS.get(play_type, play_type.title())}",
                    )
                except Exception as e:
                    print(f"Failed posting tracking card: {e}")

                if message.guild and not is_test_channel(message.channel.id):
                    try:
                        await update_recap_cards(message.guild)
                    except Exception as e:
                        print(f"Failed updating recap cards after auto-track: {e}")

    link_requested = should_trigger_link_builder(lowered)
    result = detect_result(lowered)

    # Link builder
    if message.guild and bot_mentioned and link_requested:
        target_message = await resolve_target_message_for_link(message)

        try:
            await message.reply("I got you!", mention_author=False)
        except Exception:
            pass

        if target_message:
            for att in target_message.attachments:
                if is_image_attachment(att):
                    try:
                        await target_message.add_reaction("🔗")
                    except Exception:
                        pass
                    break

        try:
            embed, view, file, _ = await build_link_this_response(message)
            if file:
                await message.channel.send(embed=embed, view=view, file=file)
            else:
                await message.channel.send(embed=embed, view=view)
        except Exception as e:
            await message.channel.send(
                embed=discord.Embed(
                    title="🔗 Pick Trax Betslip Builder",
                    description=f"Something went wrong while building the slip: {e}",
                    color=discord.Color.red(),
                )
            )
        await bot.process_commands(message)
        return

    # Owner reply actions on original messages
    if message.reference and bot_mentioned and message.author.id == data.get("owner_id"):
        try:
            if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
                referenced = message.reference.resolved
            else:
                referenced = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            await bot.process_commands(message)
            return

        pick = find_pick_by_source_message_id(referenced.id)

        if detect_reset_record_request(content):
            reset_all_records()
            await message.channel.send("🧹 Official record, channel records, and tracked plays have been reset.")
            if message.guild and not is_test_channel(message.channel.id):
                await update_recap_cards(message.guild)
            await bot.process_commands(message)
            return

        remove_id = detect_remove_play_request(content)
        if remove_id is not None:
            ok, msg = remove_pick_by_id(remove_id)
            await message.channel.send(msg)
            await bot.process_commands(message)
            return

        if detect_set_values_request(content):
            if not pick:
                tracked_pick, status = await ensure_pick_tracked_from_message(referenced, message.author.id)
                if not tracked_pick:
                    await message.channel.send(status)
                    await bot.process_commands(message)
                    return
                pick = tracked_pick
                if status == "created":
                    await message.channel.send(f"📌 Pick #{pick['id']} tracked from old post so it can be edited.")

            units_update = parse_units_update(content)
            odds_update = parse_odds_update(content)
            ok, msg = update_pending_pick_values(pick, units_update, odds_update)
            if not ok:
                await message.channel.send(msg)
                await bot.process_commands(message)
                return

            await message.channel.send(
                f"✏️ Pick #{pick['id']} updated • {msg}",
                embed=build_pick_embed(pick),
                view=GradeView(pick["id"]),
            )
            await bot.process_commands(message)
            return

        if detect_track_this_play_request(content):
            tracked_pick, status = await ensure_pick_tracked_from_message(referenced, message.author.id)
            if not tracked_pick:
                await message.channel.send(status)
                await bot.process_commands(message)
                return

            if status == "created":
                await message.channel.send(f"📌 Pick #{tracked_pick['id']} tracked from old post.")
                await post_tracking_card(message.channel, tracked_pick)
                if message.guild and not is_test_channel(message.channel.id):
                    await update_recap_cards(message.guild)
            else:
                await message.channel.send(f"That post is already tracked as Pick #{tracked_pick['id']}.")
            await bot.process_commands(message)
            return

        if detect_grade_this_request(content):
            if not pick:
                tracked_pick, status = await ensure_pick_tracked_from_message(referenced, message.author.id)
                if not tracked_pick:
                    await message.channel.send(status)
                    await bot.process_commands(message)
                    return
                pick = tracked_pick
                if status == "created":
                    await message.channel.send(f"📌 Pick #{pick['id']} tracked from old post and opened for grading.")
                    if message.guild and not is_test_channel(message.channel.id):
                        await update_recap_cards(message.guild)

            if pick["status"] != "pending":
                await message.channel.send(
                    f"Pick #{pick['id']} is already graded as **{pick['status'].upper()}**."
                )
                await bot.process_commands(message)
                return

            await message.channel.send(
                f"Pick #{pick['id']} ready to grade:",
                embed=build_pick_embed(pick),
                view=GradeView(pick["id"]),
            )
            await bot.process_commands(message)
            return

        if result in {"win", "loss", "push"}:
            if not pick:
                tracked_pick, status = await ensure_pick_tracked_from_message(referenced, message.author.id)
                if not tracked_pick:
                    await message.channel.send(status)
                    await bot.process_commands(message)
                    return
                pick = tracked_pick
                if status == "created":
                    await message.channel.send(f"📌 Pick #{pick['id']} tracked from old post before grading.")

            ok, msg = apply_grade_to_pick(pick, result, message.author.id)
            if ok:
                if result == "win":
                    if not is_test_channel(message.channel.id):
                        await forward_owner_win(message.guild, pick, referenced)
                        await message.channel.send(random.choice(WIN_HYPE_MESSAGES))
                else:
                    await message.channel.send(msg)

                if message.guild and not is_test_channel(message.channel.id):
                    await update_recap_cards(message.guild)
            else:
                await message.channel.send(msg)

            await bot.process_commands(message)
            return

    if message.guild and bot_mentioned and message.author.id == data.get("owner_id"):
        if detect_reset_record_request(content):
            reset_all_records()
            await message.channel.send("🧹 Official record, channel records, and tracked plays have been reset.")
            if not is_test_channel(message.channel.id):
                await update_recap_cards(message.guild)
            await bot.process_commands(message)
            return

        if detect_show_tracked_plays_request(content):
            await message.reply(embed=build_tracked_plays_embed(include_graded=True), mention_author=False)
            await bot.process_commands(message)
            return

        remove_id = detect_remove_play_request(content)
        if remove_id is not None:
            ok, msg = remove_pick_by_id(remove_id)
            await message.reply(msg, mention_author=False)
            await bot.process_commands(message)
            return

    # Member win forwarding / flex forwarding
    if (
        message.guild
        and bot_mentioned
        and message.channel.id in WIN_SUBMISSION_CHANNELS
        and isinstance(message.author, discord.Member)
        and message.author.id != data.get("owner_id")
        and is_member_win_forward_request(content)
    ):
        await forward_member_win(message)
        await bot.process_commands(message)
        return

    if message.guild and bot_mentioned:
        channel_record_type = detect_channel_record_request(content)
        if channel_record_type:
            await message.reply(embed=build_channel_record_embed(channel_record_type), mention_author=False)
            await bot.process_commands(message)
            return

        if detect_ping_request(content):
            await message.reply("🏓 pong", mention_author=False)
            await bot.process_commands(message)
            return

        if detect_show_record_request(content):
            await message.reply(embed=build_record_embed(), mention_author=False)
            await bot.process_commands(message)
            return

        if detect_who_is_owner_request(content):
            owner_id = data.get("owner_id")
            owner_text = f"<@{owner_id}>" if owner_id else "Not set"
            await message.reply(f"👑 Current owner: {owner_text}", mention_author=False)
            await bot.process_commands(message)
            return

        if detect_set_owner_request(content):
            target_user = find_target_user_for_owner(message)
            if not target_user:
                await message.reply("Reply with `@Pick Trax set owner me` or mention a user.", mention_author=False)
                await bot.process_commands(message)
                return

            current_owner = data.get("owner_id")
            if current_owner is not None and message.author.id != current_owner:
                await message.reply("🚫 Only the current owner can change the owner setting.", mention_author=False)
                await bot.process_commands(message)
                return

            data["owner_id"] = target_user.id
            save_data(data)
            await message.reply(f"👑 Owner set to {target_user.mention}", mention_author=False)
            if not is_test_channel(message.channel.id):
                await update_recap_cards(message.guild)
            await bot.process_commands(message)
            return

        if detect_cash_it_request(content):
            await message.reply("💰 CASH IT.", mention_author=False)
            await bot.process_commands(message)
            return

        if detect_let_it_ride_request(content):
            await message.reply("🎯 LET IT RIDE.", mention_author=False)
            await bot.process_commands(message)
            return

    await bot.process_commands(message)

# =========================================================
# ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    print(f"❌ Slash command error: {error}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(f"Error: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except Exception as e:
        print(f"❌ Failed to send error message: {e}")

# =========================================================
# COMMANDS
# =========================================================

@bot.tree.command(name="ping", description="Test if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 pong")


@bot.tree.command(name="record", description="Show official record")
async def record(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_record_embed())


@bot.tree.command(name="channelrecord", description="Show one channel record")
@app_commands.describe(channel_type="hammer, parlay, weekly, or live")
@app_commands.choices(
    channel_type=[
        app_commands.Choice(name="hammer", value="hammer"),
        app_commands.Choice(name="parlay", value="parlay"),
        app_commands.Choice(name="weekly", value="weekly"),
        app_commands.Choice(name="live", value="live"),
    ]
)
async def channelrecord(interaction: discord.Interaction, channel_type: app_commands.Choice[str]):
    await interaction.response.send_message(embed=build_channel_record_embed(channel_type.value))


@bot.tree.command(name="pending", description="List pending official plays")
async def pending(interaction: discord.Interaction):
    items = pending_picks()

    if not items:
        await interaction.response.send_message("📭 No pending picks.")
        return

    lines = ["📋 **Pending Picks**"]
    for idx, p in enumerate(items, start=1):
        lines.append(
            f"{idx}. ID {p['id']} — {TRACKED_PLAY_LABELS.get(p['play_type'], p['play_type'].title())} — {p['units']:.2f}U — {p['source_channel_name']}"
        )

    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="trackedplays", description="Owner only: view tracked plays")
@app_commands.describe(include_graded="Also include recent graded plays")
async def trackedplays(interaction: discord.Interaction, include_graded: Optional[bool] = False):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the owner can view tracked plays.", ephemeral=True)
        return

    await interaction.response.send_message(embed=build_tracked_plays_embed(include_graded=bool(include_graded)), ephemeral=True)


@bot.tree.command(name="removeplay", description="Owner only: remove a pending tracked play by ID")
@app_commands.describe(pick_id="The tracked play ID to remove")
async def removeplay(interaction: discord.Interaction, pick_id: int):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the owner can remove tracked plays.", ephemeral=True)
        return

    ok, msg = remove_pick_by_id(pick_id)
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="editplay", description="Owner only: edit pending play units and/or odds")
@app_commands.describe(
    pick_id="The tracked play ID",
    units="New unit size, like 2 or 2.5",
    odds="New odds, like -110 or +145",
)
async def editplay(
    interaction: discord.Interaction,
    pick_id: int,
    units: Optional[float] = None,
    odds: Optional[int] = None,
):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the owner can edit tracked plays.", ephemeral=True)
        return

    pick = next((p for p in data.get("picks", []) if p["id"] == pick_id), None)
    if not pick:
        await interaction.response.send_message("That pending play was not found.", ephemeral=True)
        return

    ok, msg = update_pending_pick_values(pick, units, odds)
    if not ok:
        await interaction.response.send_message(msg, ephemeral=True)
        return

    await interaction.response.send_message(
        f"✏️ Pick #{pick['id']} updated • {msg}",
        embed=build_pick_embed(pick),
        ephemeral=True,
    )


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

    if interaction.guild:
        source_message = None
        try:
            if pick.get("source_channel_id") and pick.get("source_message_id"):
                source_channel = interaction.guild.get_channel(pick["source_channel_id"])
                if source_channel:
                    source_message = await source_channel.fetch_message(pick["source_message_id"])
        except Exception:
            pass

        if result.value == "win" and not is_test_channel(interaction.channel.id):
            await forward_owner_win(interaction.guild, pick, source_message)
            await interaction.response.send_message(random.choice(WIN_HYPE_MESSAGES))
        else:
            await interaction.response.send_message(msg)

        if not is_test_channel(interaction.channel.id):
            await update_recap_cards(interaction.guild)
    else:
        await interaction.response.send_message(msg)


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
            f"{emoji} ID {p['id']} — {TRACKED_PLAY_LABELS.get(p['play_type'], p['play_type'].title())} — {p['units']:.2f}U — {format_profit(p['profit_units'])}"
        )

    await interaction.followup.send("\n".join(lines))


@bot.tree.command(name="tailboard", description="Show simple leaderboard summary")
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


@bot.tree.command(name="channelid", description="Show this channel ID")
async def channelid(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"{interaction.channel.name} -> {interaction.channel.id}",
        ephemeral=True,
    )


@bot.tree.command(name="updaterecaps", description="Force refresh all recap cards")
async def updaterecaps(interaction: discord.Interaction):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the owner can refresh recap cards.", ephemeral=True)
        return

    await update_recap_cards(interaction.guild)
    await interaction.response.send_message("✅ Recap cards refreshed.")

# =========================================================
# SETTINGS GROUP
# =========================================================

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
        f"Show Dollars: {dollars_text}"
    )
    await interaction.response.send_message(msg)


@settings_group.command(name="set_owner", description="Set the owner user")
async def settings_set_owner(interaction: discord.Interaction, user: discord.User):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the current owner can change the owner.", ephemeral=True)
        return

    data["owner_id"] = user.id
    save_data(data)
    await interaction.response.send_message(f"👑 Owner set to {user.mention}")
    await update_recap_cards(interaction.guild)


@settings_group.command(name="set_unit_value", description="Set dollar value for 1 unit")
async def settings_set_unit_value(interaction: discord.Interaction, amount: float):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the owner can change settings.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("Unit value must be greater than 0.")
        return

    data["unit_value"] = float(amount)
    save_data(data)
    await interaction.response.send_message(f"💵 1 unit is now set to ${amount:,.2f}")
    await update_recap_cards(interaction.guild)


@settings_group.command(name="toggle_dollars", description="Turn dollar display on or off")
async def settings_toggle_dollars(interaction: discord.Interaction, enabled: bool):
    if data.get("owner_id") and not is_owner_user(interaction.user.id):
        await interaction.response.send_message("Only the owner can change settings.", ephemeral=True)
        return

    data["show_dollars"] = enabled
    save_data(data)
    state = "On" if enabled else "Off"
    await interaction.response.send_message(f"💰 Dollar display is now {state}")
    await update_recap_cards(interaction.guild)


bot.tree.add_command(settings_group)

# =========================================================
# RUN
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in your environment variables.")

bot.run(TOKEN)
