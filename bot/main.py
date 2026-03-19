import os
import re
import json
import aiohttp
import discord
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus
from discord.ext import commands
from discord import app_commands

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

TRACKED_PICK_CHANNELS = {
    HAMMERS_CHANNEL_ID: "hammer",
    PARLAYS_CHANNEL_ID: "parlay",
    WEEKLY_LOCKS_CHANNEL_ID: "weekly",
    LIVE_BETS_CHANNEL_ID: "live",
}

WIN_SUBMISSION_CHANNELS = {
    GENERAL_CHAT_ID,
    VIP_GENERAL_CHAT_ID,
}

VIP_ROLE_NAME = "🏆VIP"
PUB_ROLE_NAME = "🆓PUB"

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


def default_data() -> dict:
    return {
        "owner_id": None,
        "show_dollars": False,
        "unit_value": 100.0,
        "record": {
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "units": 0.0,
        },
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


# =========================================================
# HELPERS
# =========================================================

def is_owner_user(user_id: int) -> bool:
    owner_id = data.get("owner_id")
    return owner_id is not None and user_id == owner_id


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
    for pick in data["picks"]:
        if pick["id"] == pick_id:
            return pick
    return None


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

    embed = discord.Embed(
        title=f"Pick #{pick['id']} • {pick['play_type'].title()}",
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


def is_image_attachment(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower()
    name = (att.filename or "").lower()
    return ct.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))


def clean_ocr_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r", "")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace("•", "• ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_stat(raw: str) -> str:
    return STAT_ALIASES.get(raw.strip().lower(), raw.strip().title())


def normalize_team(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw).strip(" -")
    lowered = cleaned.lower()
    return TEAM_ALIASES.get(lowered, cleaned.title())


def leg_to_display(leg: dict) -> str:
    if leg["type"] == "player_prop":
        direction = leg.get("direction", "Over")
        return f"{leg['player']} {direction} {leg['line']} {leg['stat']}"
    if leg["type"] == "spread":
        period = f" ({leg['period']})" if leg.get("period") else ""
        return f"{leg['team']} {leg['line']} Spread{period}"
    if leg["type"] == "moneyline":
        return f"{leg['team']} Moneyline"
    return leg.get("raw", "Unknown leg")


def smart_parse_legs(ocr_text: str):
    lines = [l.strip() for l in clean_ocr_text(ocr_text).split("\n") if l.strip()]
    legs = []

    ignore_contains = [
        "must be 21",
        "call 1-800-gambler",
        "bet id",
        "professional sports bettor",
        "hit rate",
        "nba parlay",
        "sgp stack",
        "odds",
        "woodzdabookie",
        "builders",
        "ovr",
        "psb",
    ]

    for raw_line in lines:
        line = raw_line.replace("•", "").strip()
        lowered = line.lower()

        if any(bad in lowered for bad in ignore_contains):
            continue
        if len(line) < 4:
            continue
        if re.fullmatch(r"[+\-]?\d+(?:\.\d+)?", line):
            continue

        # Team spreads, including OCR where it inserts spaces around minus
        spread_match = re.search(
            r"^([A-Za-z][A-Za-z\s\.]+?)\s+([+-]\s*\d+(?:\.\d+)?)\s*$",
            line,
            re.IGNORECASE,
        )
        if spread_match:
            team = normalize_team(spread_match.group(1))
            spread = spread_match.group(2).replace(" ", "")
            legs.append({
                "type": "spread",
                "team": team,
                "line": spread,
                "raw": raw_line,
            })
            continue

        # Team spreads with period text on same line
        spread_period_match = re.search(
            r"^([A-Za-z][A-Za-z\s\.]+?)\s+([+-]\s*\d+(?:\.\d+)?)\s+(1st Half|1st Quarter|2nd Half|2nd Quarter|3rd Quarter|4th Quarter)$",
            line,
            re.IGNORECASE,
        )
        if spread_period_match:
            team = normalize_team(spread_period_match.group(1))
            spread = spread_period_match.group(2).replace(" ", "")
            period = spread_period_match.group(3).title()
            legs.append({
                "type": "spread",
                "team": team,
                "line": spread,
                "period": period,
                "raw": raw_line,
            })
            continue

        # Player alt lines: 14+ Michael Porter Jr. - Points
        player_plus_match = re.search(
            r"^(\d+(?:\.\d+)?)\+\s+([A-Za-z\.'\-\s]+?)\s*-\s*(Points|Assists|Rebounds|PRA|PA|PR|AR|Pts|Ast|Reb)\s*$",
            line,
            re.IGNORECASE,
        )
        if player_plus_match:
            line_val = player_plus_match.group(1)
            player = re.sub(r"\s+", " ", player_plus_match.group(2)).strip(" .-")
            stat = normalize_stat(player_plus_match.group(3))
            legs.append({
                "type": "player_prop",
                "player": player,
                "direction": "Over",
                "line": line_val,
                "stat": stat,
                "raw": raw_line,
            })
            continue

        # Player over/under format: Jayson Tatum Over 4.5 Assists
        player_ou_match = re.search(
            r"^([A-Za-z\.'\-\s]+?)\s+(Over|Under)\s+(\d+(?:\.\d+)?)\s+(Points|Assists|Rebounds|PRA|PA|PR|AR|Pts|Ast|Reb)\s*$",
            line,
            re.IGNORECASE,
        )
        if player_ou_match:
            player = re.sub(r"\s+", " ", player_ou_match.group(1)).strip(" .-")
            direction = player_ou_match.group(2).title()
            line_val = player_ou_match.group(3)
            stat = normalize_stat(player_ou_match.group(4))
            legs.append({
                "type": "player_prop",
                "player": player,
                "direction": direction,
                "line": line_val,
                "stat": stat,
                "raw": raw_line,
            })
            continue

        # Team moneyline
        ml_match = re.search(r"^([A-Za-z][A-Za-z\s\.]+?)\s+ML$", line, re.IGNORECASE)
        if ml_match:
            team = normalize_team(ml_match.group(1))
            legs.append({
                "type": "moneyline",
                "team": team,
                "raw": raw_line,
            })
            continue

    return legs


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


def build_book_search_query(legs: list[dict]) -> str:
    pieces = []
    for leg in legs[:8]:
        pieces.append(leg_to_display(leg))
    return " | ".join(pieces)


class SportsbookLinksView(discord.ui.View):
    def __init__(self, legs: list[dict]):
        super().__init__(timeout=600)
        query = build_book_search_query(legs)

        for book in SUPPORTED_BOOKS[:5]:
            url = BOOK_URLS.get(book)
            if not url:
                continue
            label = book.title()
            # keep buttons working even without exact deeplinks
            if query:
                target = f"{url}?q={quote_plus(query)}"
            else:
                target = url
            self.add_item(discord.ui.Button(label=label, url=target))


async def extract_text_from_image_url(image_url: str) -> str:
    payload = {
        "apikey": OCR_SPACE_API_KEY,
        "url": image_url,
        "language": "eng",
        "isOverlayRequired": False,
        "scale": True,
        "OCREngine": 2,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.ocr.space/parse/image", data=payload, timeout=45) as resp:
            if resp.status != 200:
                raise RuntimeError(f"OCR request failed with status {resp.status}")
            data_resp = await resp.json(content_type=None)

    if data_resp.get("IsErroredOnProcessing"):
        msg = "; ".join(data_resp.get("ErrorMessage", []) or ["OCR processing failed"])
        raise RuntimeError(msg)

    results = data_resp.get("ParsedResults") or []
    text = "\n".join((r.get("ParsedText") or "") for r in results)
    return clean_ocr_text(text)


async def get_image_attachment_from_context(message: discord.Message) -> Optional[discord.Attachment]:
    for att in message.attachments:
        if is_image_attachment(att):
            return att

    if message.reference and message.reference.message_id:
        try:
            referenced = await message.channel.fetch_message(message.reference.message_id)
            for att in referenced.attachments:
                if is_image_attachment(att):
                    return att
        except Exception:
            return None

    return None


async def build_link_this_response(message: discord.Message) -> tuple[discord.Embed, Optional[discord.ui.View]]:
    attachment = await get_image_attachment_from_context(message)
    if not attachment:
        embed = discord.Embed(
            title="🔗 Pick Trax Betslip Builder",
            description="I need a screenshot attachment or a reply to a screenshot to build the slip.",
            color=discord.Color.red(),
        )
        return embed, None

    ocr_text = await extract_text_from_image_url(attachment.url)
    legs = smart_parse_legs(ocr_text)
    meta = parse_betslip_meta(ocr_text)

    if not legs:
        preview = ocr_text[:900] if ocr_text else "No OCR text found."
        embed = discord.Embed(
            title="🔗 Pick Trax Betslip Builder",
            description="I read the screenshot, but I could not confidently parse the legs.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="OCR Preview", value=preview[:1024], inline=False)
        return embed, None

    embed = discord.Embed(
        title="🔗 Pick Trax Betslip Builder",
        description=f"Found **{len(legs)}** leg(s) from the screenshot.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )

    if meta.get("odds"):
        embed.add_field(name="Slip Odds", value=f"{meta['odds']:+d}", inline=True)
    if meta.get("leg_count"):
        embed.add_field(name="OCR Leg Count", value=str(meta["leg_count"]), inline=True)

    display_lines = []
    for idx, leg in enumerate(legs[:12], start=1):
        display_lines.append(f"**{idx}.** {leg_to_display(leg)}")

    embed.add_field(name="Parsed Legs", value="\n".join(display_lines)[:1024], inline=False)
    embed.set_footer(text="Link buttons open supported sportsbooks. Best for clear screenshots.")
    return embed, SportsbookLinksView(legs)


async def post_recap_if_configured(guild: discord.Guild) -> None:
    recap_channel = guild.get_channel(DAILY_RECAP_ID)
    if recap_channel is None:
        return

    rec = data["record"]
    graded_decisions = rec["wins"] + rec["losses"]
    win_rate = (rec["wins"] / graded_decisions * 100) if graded_decisions > 0 else 0.0

    embed = discord.Embed(
        title="🧾 Current Recap",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
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


async def forward_owner_win(guild: discord.Guild, pick: dict, source_message: Optional[discord.Message]) -> None:
    wins_channel = guild.get_channel(POST_YOUR_WINS_ID)
    if wins_channel is None:
        return

    embed = discord.Embed(
        title="🏆 Official Win",
        description=pick["bet"][:4000],
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Type", value=pick["play_type"].title(), inline=True)
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


async def forward_member_win(message: discord.Message) -> None:
    wins_channel = message.guild.get_channel(POST_YOUR_WINS_ID)
    if wins_channel is None:
        print("Could not find post-your-wins channel by ID.")
        return

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

    files = []
    for attachment in message.attachments:
        try:
            files.append(await attachment.to_file())
        except Exception as e:
            print(f"attachment error: {e}")

    try:
        await wins_channel.send(embed=embed, files=files)
        await message.add_reaction("✅")
        print("Forwarded winner successfully.")
    except Exception as e:
        print(f"Failed forwarding winner: {e}")


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
    odds = extract_odds_from_text(message.content)

    pick = {
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
        "source_message_id": message.id,
        "source_channel_name": f"#{message.channel.name}",
    }

    data["picks"].append(pick)
    data["message_pick_map"][str(message.id)] = pick["id"]
    data["registered_source_messages"].append(message.id)
    save_data(data)
    return pick


# =========================================================
# DISCORD SETUP
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

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
        await interaction.followup.send(msg)

        if interaction.guild:
            source_message = None
            try:
                if pick.get("source_message_id"):
                    source_message = await interaction.channel.fetch_message(pick["source_message_id"])
            except Exception:
                pass

            if result == "win":
                await forward_owner_win(interaction.guild, pick, source_message)
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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").lower().strip()
    bot_mentioned = bot.user in message.mentions if bot.user else False

    if message.author.id == data.get("owner_id"):
        has_graphic = len(message.attachments) > 0 or len(message.embeds) > 0
        if message.channel.id in TRACKED_PICK_CHANNELS and has_graphic:
            if message.id not in data.get("registered_source_messages", []):
                play_type = TRACKED_PICK_CHANNELS[message.channel.id]
                create_auto_pick_from_message(message, play_type)
                try:
                    await message.add_reaction("📌")
                except Exception:
                    pass

    # New: link this flow, separated from cash this / win forwarding
    if message.guild and bot_mentioned and "link this" in content:
        try:
            embed, view = await build_link_this_response(message)
            await message.reply(embed=embed, view=view, mention_author=False)
        except Exception as e:
            await message.reply(
                embed=discord.Embed(
                    title="🔗 Pick Trax Betslip Builder",
                    description=f"Something went wrong while building the slip: {e}",
                    color=discord.Color.red(),
                ),
                mention_author=False,
            )
        await bot.process_commands(message)
        return

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
                        if result == "win":
                            await forward_owner_win(message.guild, pick, referenced)
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

    if message.guild and bot_mentioned:
        if message.channel.id in WIN_SUBMISSION_CHANNELS and isinstance(message.author, discord.Member):
            win_result = detect_result(content)
            if win_result == "win":
                await forward_member_win(message)

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


@bot.tree.command(name="pending", description="List pending official plays")
async def pending(interaction: discord.Interaction):
    items = pending_picks()

    if not items:
        await interaction.response.send_message("📭 No pending picks.")
        return

    lines = ["📋 **Pending Picks**"]
    for idx, p in enumerate(items, start=1):
        lines.append(
            f"{idx}. ID {p['id']} — {p['play_type'].title()} — {p['units']:.2f}U — {p['source_channel_name']}"
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
        if result.value == "win":
            await forward_owner_win(interaction.guild, pick, None)
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


# =========================================================
# RUN
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in your environment variables.")

bot.run(TOKEN)
