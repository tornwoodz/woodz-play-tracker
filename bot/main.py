import os
import re
import json
import base64
import urllib.parse
from io import BytesIO
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

import discord
from discord.ext import commands

import cv2
import numpy as np
from PIL import Image
import pytesseract

# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

ENV_OWNER_ID = os.getenv("OWNER_ID", "").strip()

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
MAX_ATTACHMENTS_TO_SCAN = 3
MAX_OCR_CHARS = 7000

# =========================================================
# DISCORD SETUP
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# DATA HELPERS
# =========================================================

def default_store() -> Dict[str, Any]:
    owner_id = int(ENV_OWNER_ID) if ENV_OWNER_ID.isdigit() else None
    return {
        "graded_slips": [],
        "record": {
            "wins": 0,
            "losses": 0,
            "pushes": 0
        },
        "parsed_slips": [],
        "settings": {
            "owner_id": owner_id
        }
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
        if "settings" not in loaded:
            loaded["settings"] = {"owner_id": None}
        if "owner_id" not in loaded["settings"]:
            loaded["settings"]["owner_id"] = int(ENV_OWNER_ID) if ENV_OWNER_ID.isdigit() else None

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

def truncate(text: str, max_len: int = 1800) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."

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

def get_image_attachments(message: discord.Message) -> List[discord.Attachment]:
    image_attachments: List[discord.Attachment] = []
    for attachment in message.attachments:
        filename = attachment.filename.lower()
        if filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            image_attachments.append(attachment)
            continue
        if attachment.content_type and attachment.content_type.startswith("image/"):
            image_attachments.append(attachment)
    return image_attachments

def has_any_attachment(message: discord.Message) -> bool:
    return bool(message.attachments)

def message_has_picktrax_mention(message: discord.Message) -> bool:
    return bot.user is not None and bot.user in message.mentions

def is_allowed_channel(message: discord.Message) -> bool:
    return message.channel.id in ALLOWED_CHANNEL_IDS

def get_owner_id() -> Optional[int]:
    owner_id = data_store.get("settings", {}).get("owner_id")
    if isinstance(owner_id, int):
        return owner_id
    if isinstance(owner_id, str) and owner_id.isdigit():
        return int(owner_id)
    if ENV_OWNER_ID.isdigit():
        return int(ENV_OWNER_ID)
    return None

def set_owner_id(owner_id: int) -> None:
    if "settings" not in data_store:
        data_store["settings"] = {}
    data_store["settings"]["owner_id"] = owner_id
    save_data(data_store)

def user_is_owner(user_id: int) -> bool:
    owner_id = get_owner_id()
    return owner_id is not None and owner_id == user_id

def get_record_text() -> str:
    record = data_store["record"]
    return f"Record: ✅ {record['wins']} - ❌ {record['losses']} - ➖ {record['pushes']}"

def is_link_request(text: str) -> bool:
    text = normalize_text(text)
    link_patterns = [
        "link it", "link this", "send the link", "drop the link", "need the link",
        "give me the link", "post the link", "where the link", "make the link",
        "build the link", "create the link", "get the link", "can you link",
        "link that", "link these", "link slip", "link betslip",
        "one click", "one-click", "deeplink", "deep link",
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

def detect_ping_request(text: str) -> bool:
    text = normalize_text(text)
    return any(p in text for p in [" ping", " ping?", "ping", "are you up", "you there", "status"])

def detect_show_record_request(text: str) -> bool:
    text = normalize_text(text)
    patterns = [
        "show record", "show my record", "record", "show stats", "stats",
        "show tracker", "what's the record", "whats the record", "current record"
    ]
    return any(p in text for p in patterns)

def detect_who_is_owner_request(text: str) -> bool:
    text = normalize_text(text)
    patterns = ["who is owner", "who's owner", "whos owner", "show owner", "owner?"]
    return any(p in text for p in patterns)

def detect_set_owner_request(text: str) -> bool:
    text = normalize_text(text)
    return "set owner" in text or "make owner" in text or "owner is" in text

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
            "- OCR bet slip images\n"
            "- parse text-based slips into a deep link foundation payload\n"
            "- grade slips as win/loss/push\n"
            "- track a basic record\n"
            "- answer ping / owner / record requests by mention\n\n"
            "Examples:\n"
            "- `@Pick Trax ping`\n"
            "- `@Pick Trax show record`\n"
            "- `@Pick Trax who is owner`\n"
            "- `@Pick Trax set owner @user`\n"
            "- `@Pick Trax link this`\n"
            "- `@Pick Trax grade this a win`\n"
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

async def get_recent_candidate_message(message: discord.Message) -> Optional[discord.Message]:
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
    referenced = await get_referenced_message(message)
    if referenced and (has_any_attachment(referenced) or clean_text_block(referenced.content)):
        return referenced

    if has_any_attachment(message) or clean_text_block(message.content):
        return message

    recent = await get_recent_candidate_message(message)
    if recent:
        return recent

    return None

# =========================================================
# OCR HELPERS
# =========================================================

def preprocess_image_variants(image_bytes: bytes) -> List[np.ndarray]:
    pil_image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image = np.array(pil_image)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, inv_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, blur_otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return [gray, adaptive, otsu, inv_otsu, blur_otsu]

def run_tesseract_pass(img: np.ndarray, config: str) -> str:
    try:
        return pytesseract.image_to_string(img, config=config) or ""
    except Exception:
        return ""

def dedupe_ocr_blocks(blocks: List[str]) -> str:
    seen = set()
    cleaned_blocks: List[str] = []

    for block in blocks:
        block = clean_text_block(block)
        if not block:
            continue

        block_lines = []
        for line in block.split("\n"):
            normalized = normalize_text(line)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            block_lines.append(line.strip())

        if block_lines:
            cleaned_blocks.append("\n".join(block_lines))

    combined = "\n".join(cleaned_blocks)
    return truncate(clean_text_block(combined), MAX_OCR_CHARS)

async def ocr_attachment(attachment: discord.Attachment) -> str:
    try:
        image_bytes = await attachment.read()
    except Exception:
        return ""

    variants = preprocess_image_variants(image_bytes)
    configs = [
        r"--oem 3 --psm 6",
        r"--oem 3 --psm 11",
        r"--oem 3 --psm 12",
    ]

    results: List[str] = []
    for variant in variants:
        for config in configs:
            text = run_tesseract_pass(variant, config)
            if text:
                results.append(text)

    return dedupe_ocr_blocks(results)

def normalize_ocr_text(text: str) -> str:
    text = text or ""
    replacements = {
        "Ower ": "Over ",
        "Ouer ": "Over ",
        "0ver ": "Over ",
        "Undar ": "Under ",
        "Monayline": "Moneyline",
        "MONEYL INE": "MONEYLINE",
        "MONEY LINE": "MONEYLINE",
        "|": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return clean_text_block(text)

def build_candidate_leg_lines_from_ocr(text: str) -> List[str]:
    text = normalize_ocr_text(text)
    raw_lines = [ln.strip("•*- ").strip() for ln in text.split("\n")]
    raw_lines = [ln for ln in raw_lines if ln]

    candidates: List[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        lower = line.lower()

        if re.search(r"\b(over|under)\s+\d+(?:\.\d+)?\b", lower):
            combined = line
            if i + 1 < len(raw_lines):
                nxt = raw_lines[i + 1]
                if any(k in nxt.lower() for k in ["total", "points", "rebounds", "assists", "spread", "betting"]):
                    combined += f" | {nxt}"
                    i += 1
            if i + 1 < len(raw_lines):
                nxt = raw_lines[i + 1]
                if "@" in nxt:
                    combined += f" | {nxt}"
                    i += 1
            candidates.append(combined)

        elif "moneyline" in lower:
            prev_line = raw_lines[i - 1] if i - 1 >= 0 else ""
            combined = line
            if prev_line and "@" not in prev_line and not any(
                k in prev_line.lower() for k in ["thu", "fri", "sat", "sun", "pm", "et", "total", "spread"]
            ):
                combined = f"{prev_line} | {line}"
            if i + 1 < len(raw_lines) and "@" in raw_lines[i + 1]:
                combined += f" | {raw_lines[i + 1]}"
                i += 1
            candidates.append(combined)

        elif re.search(r"[A-Za-z].*[+-]\d+(?:\.\d+)?", line) and (
            i + 1 < len(raw_lines) and "spread" in raw_lines[i + 1].lower()
        ):
            combined = f"{line} | {raw_lines[i + 1]}"
            if i + 2 < len(raw_lines) and "@" in raw_lines[i + 2]:
                combined += f" | {raw_lines[i + 2]}"
                i += 2
            else:
                i += 1
            candidates.append(combined)

        i += 1

    for line in raw_lines:
        lower = line.lower()
        if "@" in line or "moneyline" in lower or "spread" in lower or "over " in lower or "under " in lower:
            candidates.append(line)

    out: List[str] = []
    seen = set()
    for line in candidates:
        key = normalize_text(line)
        if key and key not in seen:
            seen.add(key)
            out.append(line)

    return out

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
    if any(k in lower for k in ["ncaa", "ncaab", "march madness", "ohio state", "wisconsin", "vanderbilt", "louisville", "tcu", "nebraska", "south florida", "high point", "mcneese", "troy"]):
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

    raw_line = raw_line.replace(" | ", " - ")
    lower = raw_line.lower()

    leg = empty_leg()
    leg["raw"] = raw_line

    meta = detect_sport_and_league(raw_line)
    leg["sport"] = meta["sport"]
    leg["league"] = meta["league"]

    odds_match = re.search(r"([+-]\d{2,4})\b", raw_line)
    if odds_match:
        leg["odds"] = odds_match.group(1)

    event_match = re.search(r"([A-Za-z0-9 .&'/-]+)\s+@\s+([A-Za-z0-9 .&'/-]+)", raw_line)
    if event_match:
        leg["event"] = f"{event_match.group(1).strip()} @ {event_match.group(2).strip()}"

    ou_match = re.search(r"\b(over|under)\s+(\d+(?:\.\d+)?)\b", lower)
    if ou_match:
        leg["market_type"] = "total"
        leg["selection"] = ou_match.group(1).title()
        leg["line"] = safe_float(ou_match.group(2))
        leg["confidence"] = 0.87
        return leg

    if "moneyline" in lower:
        cleaned = re.sub(r"\bmoneyline\b", "", raw_line, flags=re.IGNORECASE).strip(" -")
        cleaned = re.sub(r"\s+[+-]\d{2,4}\b", "", cleaned).strip(" -")
        if " - " in cleaned:
            first_chunk = cleaned.split(" - ")[0].strip()
        else:
            first_chunk = cleaned.strip()

        leg["market_type"] = "moneyline"
        leg["selection"] = first_chunk
        leg["confidence"] = 0.82
        return leg

    spread_match = re.search(r"([A-Za-z0-9 .&'/-]+?)\s+([+-]\d+(?:\.\d+)?)\b", raw_line)
    if spread_match:
        team_candidate = spread_match.group(1).strip(" -")
        line_candidate = spread_match.group(2)
        if team_candidate and not team_candidate.lower().startswith(("over", "under")):
            leg["market_type"] = "spread"
            leg["selection"] = team_candidate
            leg["line"] = safe_float(line_candidate)
            leg["confidence"] = 0.76
            return leg

    player_prop_match = re.search(
        r"([A-Za-z .'-]+)\s+(\d+(?:\.\d+)?\+?)\s*(points|pts|rebounds|reb|assists|ast|pra|threes|3pm|hits|shots|goals)",
        lower,
        flags=re.IGNORECASE
    )
    if player_prop_match:
        leg["market_type"] = "player_prop"
        leg["selection"] = player_prop_match.group(1).title().strip()
        leg["line"] = safe_float(player_prop_match.group(2).replace("+", ""))
        leg["confidence"] = 0.70
        return leg

    return None

def canonical_leg_key(leg: Dict[str, Any]) -> str:
    selection = normalize_text(str(leg.get("selection") or ""))
    market_type = normalize_text(str(leg.get("market_type") or ""))
    line = str(leg.get("line") if leg.get("line") is not None else "")
    event = normalize_text(str(leg.get("event") or ""))
    odds = str(leg.get("odds") or "")
    return "|".join([selection, market_type, line, event, odds])

def clean_and_dedupe_legs(legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best_by_key: Dict[str, Dict[str, Any]] = {}

    for leg in legs:
        if not leg.get("selection") and not leg.get("event"):
            continue

        key = canonical_leg_key(leg)
        if not key.strip("|"):
            continue

        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = leg
            continue

        if float(leg.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
            best_by_key[key] = leg

    cleaned = list(best_by_key.values())

    filtered: List[Dict[str, Any]] = []
    for leg in cleaned:
        market_type = (leg.get("market_type") or "").lower()
        selection = normalize_text(str(leg.get("selection") or ""))

        if market_type == "moneyline" and selection in {"moneyline", "m", ""}:
            continue
        if market_type == "spread" and selection in {"spread", "betting", ""}:
            continue

        filtered.append(leg)

    filtered.sort(key=lambda x: (-float(x.get("confidence", 0.0)), normalize_text(str(x.get("selection") or ""))))
    return filtered[:12]

def parse_legs_from_text(text: str) -> List[Dict[str, Any]]:
    text = clean_text_block(text)
    if not text:
        return []

    raw_lines = [ln.strip("•*- ").strip() for ln in text.split("\n")]
    raw_lines = [ln for ln in raw_lines if ln]

    parsed: List[Dict[str, Any]] = []
    for line in raw_lines:
        leg = parse_single_leg_from_line(line)
        if leg:
            parsed.append(leg)

    return clean_and_dedupe_legs(parsed)

def parse_legs_from_ocr_text(ocr_text: str) -> List[Dict[str, Any]]:
    candidate_lines = build_candidate_leg_lines_from_ocr(ocr_text)
    parsed: List[Dict[str, Any]] = []
    for line in candidate_lines:
        leg = parse_single_leg_from_line(line)
        if leg:
            parsed.append(leg)

    return clean_and_dedupe_legs(parsed)

def build_canonical_slip(legs: List[Dict[str, Any]], source_message: discord.Message) -> Dict[str, Any]:
    return {
        "version": "1.2",
        "source_message_id": str(source_message.id),
        "source_channel_id": str(source_message.channel.id),
        "source_author_id": str(source_message.author.id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "legs": legs,
        "leg_count": len(legs),
    }

def build_picktrax_internal_link(payload: Dict[str, Any]) -> str:
    encoded = compact_json_payload(payload)
    return f"picktrax://slip?payload={encoded}"

def book_adapter_fanduel(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"book": "FanDuel", "status": "foundation_ready", "url": None}

def book_adapter_draftkings(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"book": "DraftKings", "status": "foundation_ready", "url": None}

def book_adapter_hardrock(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"book": "Hard Rock", "status": "foundation_ready", "url": None}

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

# =========================================================
# EXTRACTION PIPELINE
# =========================================================

async def extract_text_from_target_message(message: discord.Message) -> str:
    pieces: List[str] = []

    content = clean_text_block(message.content)
    if content:
        pieces.append(content)

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

async def extract_ocr_from_target_message(message: discord.Message) -> str:
    image_attachments = get_image_attachments(message)[:MAX_ATTACHMENTS_TO_SCAN]
    if not image_attachments:
        return ""

    ocr_blocks: List[str] = []
    for attachment in image_attachments:
        text = await ocr_attachment(attachment)
        text = normalize_ocr_text(text)
        if text:
            ocr_blocks.append(text)

    return clean_text_block("\n\n".join(ocr_blocks))

async def extract_structured_legs_from_message(target_message: discord.Message) -> Tuple[List[Dict[str, Any]], str, str]:
    target_text = await extract_text_from_target_message(target_message)
    parsed_legs = parse_legs_from_text(target_text)
    ocr_text = ""

    if has_image_attachment(target_message):
        ocr_text = await extract_ocr_from_target_message(target_message)
        ocr_legs = parse_legs_from_ocr_text(ocr_text)

        if not parsed_legs:
            parsed_legs = ocr_legs
        else:
            merged = parsed_legs + ocr_legs
            parsed_legs = clean_and_dedupe_legs(merged)

    return parsed_legs, target_text, ocr_text

# =========================================================
# OWNER / SMART COMMAND HELPERS
# =========================================================

async def resolve_owner_target_user(message: discord.Message) -> Optional[discord.Member]:
    non_bot_mentions = [m for m in message.mentions if bot.user is None or m.id != bot.user.id]
    if non_bot_mentions:
        member = non_bot_mentions[0]
        if isinstance(member, discord.Member):
            return member

    referenced = await get_referenced_message(message)
    if referenced and isinstance(referenced.author, discord.Member):
        return referenced.author

    text = normalize_text(message.content)
    if "set owner me" in text or "make me owner" in text:
        if isinstance(message.author, discord.Member):
            return message.author

    id_match = re.search(r"\b(\d{17,20})\b", message.content or "")
    if id_match and message.guild:
        try:
            member = message.guild.get_member(int(id_match.group(1)))
            if member:
                return member
        except Exception:
            pass

    return None

async def handle_ping_request(message: discord.Message) -> None:
    latency_ms = round(bot.latency * 1000)
    owner_id = get_owner_id()
    owner_note = f"\nOwner ID: `{owner_id}`" if owner_id else "\nOwner ID: `not set`"
    await message.reply(f"🏓 Pong! `{latency_ms}ms`{owner_note}", mention_author=False)

async def handle_show_record_request(message: discord.Message) -> None:
    await message.reply(f"📊 {get_record_text()}", mention_author=False)

async def handle_who_is_owner_request(message: discord.Message) -> None:
    owner_id = get_owner_id()
    if not owner_id:
        await message.reply("👑 No owner is set right now.", mention_author=False)
        return

    member = None
    if message.guild:
        member = message.guild.get_member(owner_id)

    if member:
        await message.reply(f"👑 Current owner: {member.mention} (`{owner_id}`)", mention_author=False)
    else:
        await message.reply(f"👑 Current owner ID: `{owner_id}`", mention_author=False)

async def handle_set_owner_request(message: discord.Message) -> None:
    current_owner_id = get_owner_id()

    # Only current owner can change it, unless none exists yet.
    if current_owner_id is not None and message.author.id != current_owner_id:
        await message.reply("🚫 Only the current owner can change the owner setting.", mention_author=False)
        return

    target_user = await resolve_owner_target_user(message)
    if not target_user:
        await message.reply(
            "I got you — reply to someone, mention someone, use `set owner me`, or include a user ID.",
            mention_author=False
        )
        return

    set_owner_id(target_user.id)
    await message.reply(f"👑 Owner set to {target_user.mention} (`{target_user.id}`)", mention_author=False)

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

    if not target_message:
        await message.reply(
            "I got you! I just need a slip message, image, or reply target to work from.",
            mention_author=False
        )
        return

    if has_image_attachment(target_message):
        try:
            await target_message.add_reaction("🔗")
        except Exception:
            pass

    parsed_legs, native_text, ocr_text = await extract_structured_legs_from_message(target_message)
    payload = None
    adapters: List[Dict[str, Any]] = []

    if parsed_legs:
        payload = build_canonical_slip(parsed_legs, target_message)
        adapters = build_book_adapters(payload)

        data_store["parsed_slips"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "native_text": truncate(native_text, 2000),
            "ocr_text": truncate(ocr_text, 2000),
        })
        save_data(data_store)

    response_lines = ["I got you!"]

    if parsed_legs and payload:
        response_lines.append("")
        response_lines.append("**Deep Link Foundation Ready**")
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

        if ocr_text:
            response_lines.append("")
            response_lines.append("**OCR Status**")
            response_lines.append("Slip image read successfully.")
    else:
        response_lines.append("")
        if has_image_attachment(target_message):
            response_lines.append("OCR ran, but I couldn’t confidently structure the legs yet.")
            if ocr_text:
                response_lines.append("")
                response_lines.append("**OCR Preview**")
                response_lines.append(f"```{truncate(ocr_text, 800)}```")
            response_lines.append("")
            response_lines.append("Foundation is installed. Next step would be improving sport/book-specific parsing.")
        else:
            response_lines.append("I found the target, but I still need readable slip text or an image to build the deep link payload.")

    try:
        await message.reply("\n".join(response_lines), mention_author=False)
    except Exception:
        try:
            await message.channel.send("\n".join(response_lines))
        except Exception:
            pass

# =========================================================
# TEXT COMMANDS
# =========================================================

@bot.command(name="record")
async def record_command(ctx: commands.Context):
    await ctx.send(get_record_text())

@bot.command(name="resetrecord")
@commands.has_permissions(administrator=True)
async def reset_record_command(ctx: commands.Context):
    data_store["record"] = {"wins": 0, "losses": 0, "pushes": 0}
    data_store["graded_slips"] = []
    save_data(data_store)
    await ctx.send("📊 Record reset.")

@bot.command(name="picktraxhelp")
async def picktrax_help(ctx: commands.Context):
    bot_name = bot.user.display_name if bot.user else "Pick Trax"
    await ctx.send(
        "**Pick Trax Commands**\n"
        "`!record` → shows current record\n"
        "`!resetrecord` → resets tracked record (admin only)\n"
        "`!ocrtest` → OCR preview on a replied slip image\n\n"
        "**Mention Triggers**\n"
        f"`@{bot_name} ping`\n"
        f"`@{bot_name} show record`\n"
        f"`@{bot_name} who is owner`\n"
        f"`@{bot_name} set owner @user`\n"
        f"`@{bot_name} set owner me`\n"
        f"`@{bot_name} link this`\n"
        f"`@{bot_name} grade this a win/loss/push`\n"
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

@bot.command(name="ocrtest")
async def ocrtest_command(ctx: commands.Context):
    target_message = await resolve_link_target_message(ctx.message)

    if not target_message or not has_image_attachment(target_message):
        await ctx.send("Reply to an image slip with `!ocrtest`.")
        return

    ocr_text = await extract_ocr_from_target_message(target_message)
    if not ocr_text:
        await ctx.send("OCR didn’t return readable text.")
        return

    await ctx.send(f"**OCR Preview**\n```{truncate(ocr_text, 1500)}```")

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
        # Mention-based modern AI commands
        if detect_set_owner_request(clean_text):
            await handle_set_owner_request(message)
            await bot.process_commands(message)
            return

        if detect_who_is_owner_request(clean_text):
            await handle_who_is_owner_request(message)
            await bot.process_commands(message)
            return

        if detect_show_record_request(clean_text):
            await handle_show_record_request(message)
            await bot.process_commands(message)
            return

        if detect_ping_request(clean_text):
            await handle_ping_request(message)
            await bot.process_commands(message)
            return

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
            "I’m here. Try `ping`, `show record`, `who is owner`, `set owner`, `link`, or `grade this a win/loss/push`.",
            mention_author=False
        )

    await bot.process_commands(message)

# =========================================================
# START
# =========================================================

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN environment variable.")

bot.run(DISCORD_TOKEN)
