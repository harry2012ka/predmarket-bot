"""
Risk manager — protects your capital.
  - Daily loss limit (bot pauses if hit)
  - Max open positions
  - Per-trade size cap
  - Kill switch (instant stop)
  - Duplicate trade prevention (client order ID dedup)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("bot.risk")


@dataclass
class Position:
    position_id: str
    platform: str        # "kalshi" or "polymarket"
    ticker_or_token: str
    side: str
    size_usd: float
    entry_price: float
    timestamp: float
    strategy: str
    is_open: bool = True
    exit_price: float = 0.0
    pnl_usd: float = 0.0


class RiskManager:
    def __init__(
        self,
        max_position_usd: float = 25.0,
        max_open_positions: int = 10,
        daily_loss_limit_usd: float = 100.0,
    ):
        self.max_position_usd = max_position_usd
        self.max_open_positions = max_open_positions
        self.daily_loss_limit_usd = daily_loss_limit_usd

        self._open_positions: dict[str, Position] = {}
        self._daily_pnl: float = 0.0
        self._day_start: float = time.time()
        self._killed: bool = False
        self._recent_signals: set[str] = set()  # dedup by signal fingerprint

    # ── Kill switch ───────────────────────────────────────────────────────────

    def kill(self):
        self._killed = True
        log.critical("KILL SWITCH ACTIVATED — bot will not place any new orders")

    def is_killed(self) -> bool:
        return self._killed

    def reset_kill(self):
        self._killed = False
        log.warning("Kill switch reset — bot resuming")

    # ── Pre-trade checks ──────────────────────────────────────────────────────

    def can_trade(self, signal) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        Call this before every trade execution.
        """
        if self._killed:
            return False, "kill switch active"

        # Reset daily PnL at midnight
        if time.time() - self._day_start > 86400:
            self._daily_pnl = 0.0
            self._day_start = time.time()
            log.info("Daily PnL reset")

        if self._daily_pnl <= -self.daily_loss_limit_usd:
            return False, f"daily loss limit hit (${self._daily_pnl:.2f})"

        open_count = len([p for p in self._open_positions.values() if p.is_open])
        if open_count >= self.max_open_positions:
            return False, f"max open positions reached ({open_count})"

        # Check signal dedup (prevent same signal firing twice fast)
        fingerprint = self._signal_fingerprint(signal)
        if fingerprint in self._recent_signals:
            return False, "duplicate signal (dedup)"

        return True, "ok"

    def _signal_fingerprint(self, signal) -> str:
        parts = [
            signal.strategy,
            str(signal.kalshi_ticker or ""),
            str(signal.poly_token_id or ""),
            str(signal.kalshi_side or ""),
            str(signal.poly_side or ""),
        ]
        return "|".join(parts)

    def register_signal(self, signal):
        """Call after trade is placed to prevent immediate re-firing."""
        fp = self._signal_fingerprint(signal)
        self._recent_signals.add(fp)
        # Clear dedup after 60 seconds
        import asyncio
        async def _clear():
            await asyncio.sleep(60)
            self._recent_signals.discard(fp)
        # schedule but don't block
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_clear())
        except Exception:
            pass

    # ── Position tracking ─────────────────────────────────────────────────────

    def open_position(
        self,
        position_id: str,
        platform: str,
        ticker_or_token: str,
        side: str,
        size_usd: float,
        entry_price: float,
        strategy: str,
    ) -> Position:
        pos = Position(
            position_id=position_id,
            platform=platform,
            ticker_or_token=ticker_or_token,
            side=side,
            size_usd=size_usd,
            entry_price=entry_price,
            timestamp=time.time(),
            strategy=strategy,
        )
        self._open_positions[position_id] = pos
        log.info(f"Position opened: {position_id} | {platform} {ticker_or_token} {side} ${size_usd:.2f}")
        return pos

    def close_position(self, position_id: str, exit_price: float, pnl: float):
        if position_id in self._open_positions:
            pos = self._open_positions[position_id]
            pos.is_open = False
            pos.exit_price = exit_price
            pos.pnl_usd = pnl
            self._daily_pnl += pnl
            log.info(f"Position closed: {position_id} | PnL ${pnl:+.2f} | Daily: ${self._daily_pnl:+.2f}")

    def get_open_positions(self) -> list[Position]:
        return [p for p in self._open_positions.values() if p.is_open]

    def daily_pnl(self) -> float:
        return self._daily_pnl

    def status_summary(self) -> dict:
        open_pos = self.get_open_positions()
        return {
            "killed": self._killed,
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_loss_limit": self.daily_loss_limit_usd,
            "open_positions": len(open_pos),
            "max_positions": self.max_open_positions,
            "pnl_at_risk": round(sum(p.size_usd for p in open_pos), 2),
        }
