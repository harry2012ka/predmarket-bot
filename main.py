"""
Prediction Market Trading Bot
Supports: Polymarket + Kalshi
Strategies: Cross-platform arbitrage, Edge hunting, Market making
Author: Built for harry2k12
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from config import BotConfig
from engine import TradingEngine
from logger import setup_logging


async def main():
    setup_logging()
    log = logging.getLogger("bot.main")

    config = BotConfig.from_env()
    log.info("Starting Prediction Market Bot")
    log.info(f"Mode: {config.mode} | Platforms: {config.platforms}")
    log.info(f"Max position per trade: ${config.max_position_usd}")
    log.info(f"Daily loss limit: ${config.daily_loss_limit_usd}")

    engine = TradingEngine(config)

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()

    def _shutdown():
        log.warning("Shutdown signal received — cancelling open orders...")
        asyncio.create_task(engine.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
