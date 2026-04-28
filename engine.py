"""
Trading engine — orchestrates everything.
  - Initializes both clients
  - Runs market scan loop
  - Evaluates strategies
  - Executes trades through risk manager
  - Handles failures gracefully
"""

import asyncio
import logging
import time
import uuid
from typing import Optional

from config import BotConfig
from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from matcher import MarketMatcher
from strategies import ArbStrategy, EdgeStrategy, MakerStrategy, TradeSignal
from risk import RiskManager
from database import TradeDB

log = logging.getLogger("bot.engine")


class TradingEngine:
    def __init__(self, config: BotConfig):
        self.cfg = config
        self.running = False

        # Clients
        self.kalshi: Optional[KalshiClient] = None
        self.poly: Optional[PolymarketClient] = None

        # Components
        self.matcher = MarketMatcher(min_score=0.4)
        self.risk = RiskManager(
            max_position_usd=config.max_position_usd,
            max_open_positions=config.max_open_positions,
            daily_loss_limit_usd=config.daily_loss_limit_usd,
        )
        self.db = TradeDB(config.db_path)

        # Strategies
        self.arb = ArbStrategy(
            min_edge_pct=config.arb_min_edge_pct,
            max_position_usd=config.max_position_usd,
        )
        self.edge = EdgeStrategy(
            min_deviation_pct=config.edge_min_deviation_pct,
            kelly_fraction=config.kelly_fraction,
            max_position_usd=config.max_position_usd,
        )
        self.maker = MakerStrategy(
            max_position_usd=config.max_position_usd,
        )

        self._scan_count = 0
        self._start_time = time.time()

    async def run(self):
        self.running = True
        log.info("Trading engine starting...")

        await self._initialize_clients()
        await self._run_scan_loop()

    async def _initialize_clients(self):
        """Connect to exchanges."""
        if "kalshi" in self.cfg.platforms:
            self.kalshi = KalshiClient(
                api_key_id=self.cfg.kalshi_api_key_id,
                private_key_path=self.cfg.kalshi_private_key_path,
                private_key_bytes=self.cfg.kalshi_private_key_bytes,
                demo=self.cfg.kalshi_demo_mode,
            )
            bal = await self.kalshi.get_balance()
            log.info(f"Kalshi connected | Balance: ${bal:.2f} | {'DEMO' if self.cfg.kalshi_demo_mode else 'LIVE'}")

        if "polymarket" in self.cfg.platforms:
            self.poly = PolymarketClient(
                private_key=self.cfg.polymarket_private_key,
                funder_address=self.cfg.polymarket_funder_address,
            )
            await self.poly.connect()
            bal = await self.poly.get_balance()
            log.info(f"Polymarket connected | Balance: ${bal:.2f}")

    async def _run_scan_loop(self):
        """Main loop: scan markets, find signals, execute trades."""
        log.info(f"Scan loop started | interval={self.cfg.scan_interval_sec}s | mode={self.cfg.mode}")

        while self.running:
            try:
                await self._scan_cycle()
                self._scan_count += 1

                # Print status every 10 scans
                if self._scan_count % 10 == 0:
                    self._log_status()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Scan error: {e}", exc_info=True)

            await asyncio.sleep(self.cfg.scan_interval_sec)

    async def _scan_cycle(self):
        """One scan: fetch markets, find opportunities, fire signals."""
        kalshi_markets = []
        poly_markets = []

        # Fetch markets in parallel
        tasks = []
        if self.kalshi:
            tasks.append(self._fetch_kalshi_markets())
        if self.poly:
            tasks.append(self._fetch_poly_markets())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                log.warning(f"Market fetch error: {r}")
                continue
            if r and isinstance(r, list):
                if r and hasattr(r[0], "ticker"):  # Kalshi
                    kalshi_markets = r
                elif r and hasattr(r[0], "condition_id"):  # Poly
                    poly_markets = r

        # ── Arbitrage strategy ────────────────────────────────────────────────
        if self.cfg.mode in ("arb", "all") and kalshi_markets and poly_markets:
            pairs = self.matcher.find_pairs(kalshi_markets, poly_markets)
            bankroll = self.cfg.max_position_usd * self.cfg.max_open_positions

            for pair in pairs[:20]:  # top 20 pairs only
                signal = self.arb.evaluate(pair, bankroll)
                if signal:
                    await self._execute_signal(signal)

        # ── Edge hunting ──────────────────────────────────────────────────────
        if self.cfg.mode in ("edge", "all"):
            if kalshi_markets:
                await self.edge.refresh_signals(kalshi_markets)
            bankroll = self.cfg.max_position_usd * self.cfg.max_open_positions
            for market in kalshi_markets[:50]:
                signal = self.edge.evaluate_kalshi(market, bankroll)
                if signal:
                    await self._execute_signal(signal)
            for market in poly_markets[:50]:
                signal = self.edge.evaluate_poly(market, bankroll)
                if signal:
                    await self._execute_signal(signal)

        # ── Market making ─────────────────────────────────────────────────────
        if self.cfg.mode in ("maker", "all"):
            for market in kalshi_markets[:10]:  # make top 10 by volume
                quotes = self.maker.get_kalshi_quotes(market)
                if quotes:
                    for q in quotes:
                        await self._execute_signal(q)
            for market in poly_markets[:10]:
                quotes = self.maker.get_poly_quotes(market)
                if quotes:
                    for q in quotes:
                        await self._execute_signal(q)

    async def _fetch_kalshi_markets(self):
        try:
            return await self.kalshi.get_liquid_markets()
        except Exception as e:
            log.error(f"Kalshi market fetch failed: {e}")
            return []

    async def _fetch_poly_markets(self):
        try:
            return await self.poly.get_markets(limit=100)
        except Exception as e:
            log.error(f"Poly market fetch failed: {e}")
            return []

    async def _execute_signal(self, signal: TradeSignal):
        """Execute a trade signal through risk checks, then both platforms."""
        can, reason = self.risk.can_trade(signal)
        if not can:
            log.debug(f"Signal blocked: {reason} | {signal.description}")
            return

        signal_id = self.db.log_signal(signal, fired=True)
        self.risk.register_signal(signal)

        log.info(f"Executing: {signal.description}")

        # ── Kalshi leg ────────────────────────────────────────────────────────
        kalshi_ok = True
        if signal.kalshi_ticker and self.kalshi:
            try:
                order = await self.kalshi.place_order(
                    ticker=signal.kalshi_ticker,
                    side=signal.kalshi_side,
                    action=signal.kalshi_action,
                    count=signal.kalshi_count,
                    order_type="limit",
                    price=signal.kalshi_price,
                )
                size_usd = (signal.kalshi_count or 0) * (signal.kalshi_price or 0) * 100
                self.db.log_order(
                    platform="kalshi",
                    order_id=order.order_id,
                    ticker_or_token=signal.kalshi_ticker,
                    side=signal.kalshi_side,
                    action=signal.kalshi_action,
                    price=signal.kalshi_price,
                    size_usd=size_usd,
                    count=signal.kalshi_count,
                    status=order.status,
                    strategy=signal.strategy,
                    signal_id=signal_id,
                )
                pos_id = f"kalshi_{order.order_id}"
                self.risk.open_position(
                    pos_id, "kalshi", signal.kalshi_ticker,
                    signal.kalshi_side, size_usd, signal.kalshi_price, signal.strategy
                )
            except Exception as e:
                log.error(f"Kalshi order failed: {e}")
                kalshi_ok = False

        # ── Polymarket leg ────────────────────────────────────────────────────
        # CRITICAL for arb: if kalshi leg failed, don't place poly leg
        if signal.poly_token_id and self.poly:
            if signal.strategy == "arb" and not kalshi_ok:
                log.warning("ARB: Kalshi leg failed — skipping Poly leg to avoid naked exposure")
                return

            try:
                if signal.poly_side in ("BUY",) and signal.strategy != "maker":
                    # Use market order for arb (speed matters), limit for maker
                    order = await self.poly.place_market_order(
                        signal.poly_token_id, signal.poly_side, signal.poly_size_usd
                    )
                else:
                    order = await self.poly.place_limit_order(
                        signal.poly_token_id,
                        signal.poly_side,
                        signal.poly_price,
                        signal.poly_size_usd,
                    )
                if order:
                    self.db.log_order(
                        platform="polymarket",
                        order_id=order.order_id,
                        ticker_or_token=signal.poly_token_id,
                        side=signal.poly_side,
                        action="buy" if signal.poly_side == "BUY" else "sell",
                        price=signal.poly_price or 0,
                        size_usd=signal.poly_size_usd,
                        count=0,
                        status=order.status,
                        strategy=signal.strategy,
                        signal_id=signal_id,
                    )
                    self.risk.open_position(
                        f"poly_{order.order_id}", "polymarket", signal.poly_token_id,
                        signal.poly_side, signal.poly_size_usd, signal.poly_price or 0,
                        signal.strategy,
                    )
            except Exception as e:
                log.error(f"Polymarket order failed: {e}")
                if signal.strategy == "arb" and kalshi_ok:
                    log.critical("ARB: Poly leg failed after Kalshi filled — NAKED POSITION! Manual review needed.")

    def _log_status(self):
        status = self.risk.status_summary()
        uptime = (time.time() - self._start_time) / 3600
        log.info(
            f"STATUS | uptime={uptime:.1f}h | scans={self._scan_count} | "
            f"open_pos={status['open_positions']} | daily_pnl=${status['daily_pnl']:+.2f} | "
            f"killed={status['killed']}"
        )

    async def shutdown(self):
        """Graceful shutdown: cancel all open orders first."""
        log.warning("Shutdown initiated...")
        self.running = False

        tasks = []
        if self.kalshi:
            tasks.append(self.kalshi.cancel_all_orders())
        if self.poly:
            tasks.append(self.poly.cancel_all_orders())

        await asyncio.gather(*tasks, return_exceptions=True)

        if self.kalshi:
            await self.kalshi.close()
        if self.poly:
            await self.poly.close()

        self.db.close()
        log.info("Shutdown complete")
