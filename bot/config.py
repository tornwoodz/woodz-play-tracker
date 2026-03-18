from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    token: str
    guild_id: int
    owner_user_id: int
    default_unit_value: float
    timezone: str
    tracked_channels_vip: list[str]
    tracked_channels_pub: list[str]
    recap_channel_name: str
    pub_role_name: str
    vip_role_name: str
    brand_name: str
    footer: str


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "")
    guild_id = int(os.getenv("GUILD_ID", "0"))
    owner_user_id = int(os.getenv("OWNER_ID", "0"))
    return Settings(
        token=token,
        guild_id=guild_id,
        owner_user_id=owner_user_id,
        default_unit_value=float(os.getenv("DEFAULT_UNIT_VALUE", "50")),
        timezone=os.getenv("TIMEZONE", "America/New_York"),
        tracked_channels_vip=csv_env("TRACKED_CHANNELS_VIP", "live-bets,hammers-aka-singles,parlays"),
        tracked_channels_pub=csv_env("TRACKED_CHANNELS_PUB", "weekly-locks"),
        recap_channel_name=os.getenv("RECAP_CHANNEL_NAME", "daily-recap"),
        pub_role_name=os.getenv("PUB_ROLE_NAME", "🆓PUB"),
        vip_role_name=os.getenv("VIP_ROLE_NAME", "🏆VIP"),
        brand_name=os.getenv("BOT_BRAND_NAME", "DABOOKIE HQ"),
        footer=os.getenv("BOT_FOOTER", "@woodzdabookie"),
    )
