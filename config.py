"""
Configuration — all settings loaded from environment variables.
Copy .env.example to .env and fill in your credentials.
"""

import base64
import os
import tempfile
from dataclasses import dataclass, field
from typing import Literal
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BotConfig:
    # ── Platform toggles ──────────────────────────────────────────────────────
    platforms: list[str] = field(default_factory=lambda: ["kalshi", "polymarket"])

    # ── Strategy mode ─────────────────────────────────────────────────────────
    # "arb"        → cross-platform arbitrage only
    # "maker"      → market making on both platforms
    # "edge"       → edge hunting (mispriced markets)
    # "all"        → arb + maker + edge combined
    mode: str = "all"

    # ── Risk controls ─────────────────────────────────────────────────────────
    max_position_usd: float = 25.0       # max $ per single trade leg
    max_open_positions: int = 10         # max simultaneous open positions
    daily_loss_limit_usd: float = 100.0  # bot pauses if daily loss hits this
    arb_min_edge_pct: float = 2.0        # min arb gap % to fire (after fees)
    edge_min_deviation_pct: float = 5.0  # min model vs market gap to trade
    kelly_fraction: float = 0.25         # fractional Kelly sizing (0.25 = quarter Kelly)

    # ── Kalshi credentials ────────────────────────────────────────────────────
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = "keys/kalshi_private.pem"
    kalshi_demo_mode: bool = True        # START IN DEMO — set False for live

    # ── Polymarket credentials ────────────────────────────────────────────────
    polymarket_private_key: str = ""     # your Polygon wallet private key (0x...)
    polymarket_funder_address: str = ""  # your Polymarket proxy/funder address

    # ── Infrastructure ────────────────────────────────────────────────────────
    scan_interval_sec: float = 5.0       # how often to scan for new opportunities
    heartbeat_interval_sec: float = 20.0 # WebSocket heartbeat (Polymarket requires this)
    db_path: str = "data/trades.db"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "BotConfig":
        cfg = cls()
        cfg.kalshi_api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
        cfg.kalshi_demo_mode = os.getenv("KALSHI_DEMO_MODE", "true").lower() == "true"

        # Support key as base64 env var (for Railway/cloud) or local file path
        key_b64 = os.getenv("KALSHI_PRIVATE_KEY_B64", "")
        if key_b64:
            # Strip all whitespace — Railway's UI can silently inject spaces/newlines
            pem_bytes = base64.b64decode("".join(key_b64.split()))
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            tmp.write(pem_bytes)
            tmp.flush()
            tmp.close()
            cfg.kalshi_private_key_path = tmp.name
        else:
            cfg.kalshi_private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "keys/kalshi_private.pem")

        cfg.polymarket_private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        cfg.polymarket_funder_address = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")

        cfg.mode = os.getenv("BOT_MODE", "all")
        cfg.max_position_usd = float(os.getenv("MAX_POSITION_USD", "25"))
        cfg.daily_loss_limit_usd = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100"))
        cfg.arb_min_edge_pct = float(os.getenv("ARB_MIN_EDGE_PCT", "2.0"))
        cfg.edge_min_deviation_pct = float(os.getenv("EDGE_MIN_DEVIATION_PCT", "5.0"))
        cfg.kelly_fraction = float(os.getenv("KELLY_FRACTION", "0.25"))
        cfg.log_level = os.getenv("LOG_LEVEL", "INFO")

        # Determine which platforms are enabled
        platforms_env = os.getenv("PLATFORMS", "kalshi,polymarket")
        cfg.platforms = [p.strip() for p in platforms_env.split(",")]

        return cfg

    def validate(self):
        errors = []
        if "kalshi" in self.platforms:
            if not self.kalshi_api_key_id:
                errors.append("KALSHI_API_KEY_ID is not set")
            if not os.path.exists(self.kalshi_private_key_path):
                errors.append(f"Kalshi private key not found at: {self.kalshi_private_key_path}")
        if "polymarket" in self.platforms:
            if not self.polymarket_private_key:
                errors.append("POLYMARKET_PRIVATE_KEY is not set")
            if not self.polymarket_funder_address:
                errors.append("POLYMARKET_FUNDER_ADDRESS is not set")
        if errors:
            raise ValueError("Config errors:\n" + "\n".join(f"  - {e}" for e in errors))
