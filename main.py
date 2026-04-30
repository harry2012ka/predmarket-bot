"""
Prediction Market Trading Bot
Supports: Polymarket + Kalshi
Strategies: Cross-platform arbitrage, Edge hunting, Market making
Author: Built for harry2k12
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from config import BotConfig
from engine import TradingEngine
from logger import setup_logging


async def main():
    setup_logging()
    log = logging.getLogger("bot.main")

    # ── Trading bot ───────────────────────────────────────────────────────────
    config = BotConfig.from_env()
    log.info("Starting Prediction Market Bot")
    log.info(f"Mode: {config.mode} | Platforms: {config.platforms}")
    log.info(f"Max position per trade: ${config.max_position_usd}")
    log.info(f"Daily loss limit: ${config.daily_loss_limit_usd}")

    engine = TradingEngine(config)

    # ── Outbound sales pipeline ───────────────────────────────────────────────
    pipeline = None
    if os.getenv("APOLLO_API_KEY") and os.getenv("INSTANTLY_API_KEY"):
        try:
            from outbound.pipeline import OutboundPipeline
            pipeline = OutboundPipeline()
            pipeline.start()
            log.info("Outbound pipeline started alongside trading bot")
        except Exception as e:
            log.error(f"Outbound pipeline failed to start: {e}")

    # ── Video production pipeline ─────────────────────────────────────────────
    video_pipeline = None
    if os.getenv("ELEVENLABS_API_KEY") and os.getenv("ANTHROPIC_API_KEY"):
        try:
            from video_system.pipeline import VideoPipeline
            video_pipeline = VideoPipeline()
            video_pipeline.start()
            log.info("Video pipeline started | TikTok@10am | YouTube@Mon/Wed/Fri 6am")
        except Exception as e:
            log.error(f"Video pipeline failed to start: {e}")

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()

    def _shutdown():
        log.warning("Shutdown signal received — cancelling open orders...")
        asyncio.create_task(engine.shutdown())
        if pipeline:
            pipeline.stop()
        if video_pipeline:
            video_pipeline.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
