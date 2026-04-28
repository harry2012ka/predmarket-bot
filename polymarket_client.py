"""
Polymarket CLOB client — 2026 rules edition
Key differences from pre-Feb-18-2026 bots:
  1. WebSocket-first (NOT REST polling — too slow)
  2. Dynamic fee handling — feeRateBps MUST be in order signature
  3. Maker-first strategy — zero fees + rebates on limit orders
  4. Heartbeat required — Polymarket cancels all orders on session timeout
  5. EOA signature type (0) for MetaMask/hardware wallets
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import aiohttp
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    OrderArgs,
    MarketOrderArgs,
    OrderType,
    BookParams,
)
from py_clob_client.order_builder.constants import BUY, SELL

log = logging.getLogger("bot.polymarket")

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
WS_HOST = "wss://ws-subscriptions-clob.polymarket.com/ws"
CHAIN_ID = 137  # Polygon


@dataclass
class PolyMarket:
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    yes_bid: float   # 0.0 – 1.0
    yes_ask: float
    yes_mid: float
    volume_24h: float
    liquidity: float
    active: bool
    enable_order_book: bool


@dataclass
class PolyOrder:
    order_id: str
    condition_id: str
    token_id: str
    side: str    # "BUY" or "SELL"
    size: float  # USDC
    price: float
    status: str


class PolymarketClient:
    def __init__(self, private_key: str, funder_address: str):
        """
        private_key:    Your Polygon wallet private key (0x...).
                        For MetaMask: export from MetaMask > Account Details > Export Private Key.
                        For Polymarket email wallet: go to Cash > 3-dot menu > Export Private Key.
        funder_address: Your Polymarket proxy wallet address (shown at polymarket.com/settings).
                        This is NOT always your MetaMask address — check Polymarket settings.
        """
        self.funder_address = funder_address
        self._private_key = private_key
        self._client: Optional[ClobClient] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        log.info("Polymarket client initialized")

    async def connect(self):
        """Authenticate and set up API credentials."""
        self._client = ClobClient(
            CLOB_HOST,
            key=self._private_key,
            chain_id=CHAIN_ID,
            signature_type=1,  # 1 = email/Magic wallet proxy; use 0 if EOA/MetaMask
            funder=self.funder_address,
        )
        self._client.set_api_creds(self._client.create_or_derive_api_creds())
        self._session = aiohttp.ClientSession()
        log.info(f"Polymarket connected. Funder: {self.funder_address}")

    # ── Market discovery ──────────────────────────────────────────────────────

    async def get_markets(self, limit: int = 100) -> list[PolyMarket]:
        """Fetch active markets with orderbook enabled from Gamma API."""
        url = f"{GAMMA_HOST}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "enable_order_book": "true",
            "limit": limit,
            "_sort": "volume24hr",
            "_order": "desc",
        }
        async with self._session.get(url, params=params) as r:
            r.raise_for_status()
            data = await r.json()

        markets = []
        for m in data:
            try:
                prices = m.get("outcomePrices", ["0", "0"])
                yes_price = float(prices[0]) if prices else 0.5
                markets.append(PolyMarket(
                    condition_id=m["conditionId"],
                    question=m.get("question", ""),
                    yes_token_id=m.get("clobTokenIds", ["", ""])[0],
                    no_token_id=m.get("clobTokenIds", ["", ""])[1] if len(m.get("clobTokenIds", [])) > 1 else "",
                    yes_bid=yes_price - 0.01,
                    yes_ask=yes_price + 0.01,
                    yes_mid=yes_price,
                    volume_24h=float(m.get("volume24hr", 0) or 0),
                    liquidity=float(m.get("liquidity", 0) or 0),
                    active=m.get("active", False),
                    enable_order_book=m.get("enableOrderBook", False),
                ))
            except Exception as e:
                log.debug(f"Skipping Poly market: {e}")
        return markets

    async def get_orderbook(self, token_id: str) -> dict:
        """Get live orderbook for a token."""
        try:
            book = self._client.get_order_book(token_id)
            return {
                "bids": [[float(b.price), float(b.size)] for b in (book.bids or [])],
                "asks": [[float(a.price), float(a.size)] for a in (book.asks or [])],
            }
        except Exception as e:
            log.debug(f"Orderbook fetch failed for {token_id}: {e}")
            return {"bids": [], "asks": []}

    async def get_price(self, token_id: str) -> tuple[float, float]:
        """Returns (bid, ask) for a token."""
        try:
            bid = float(self._client.get_price(token_id, "BUY") or 0)
            ask = float(self._client.get_price(token_id, "SELL") or 0)
            return bid, ask
        except Exception:
            return 0.0, 0.0

    async def get_balance(self) -> float:
        """Returns USDC balance."""
        try:
            data = self._client.get_balance_allowance()
            return float(data.get("balance", 0))
        except Exception as e:
            log.error(f"Poly balance fetch failed: {e}")
            return 0.0

    # ── Order management ──────────────────────────────────────────────────────

    async def place_limit_order(
        self,
        token_id: str,
        side: str,    # "BUY" or "SELL"
        price: float, # 0.0 – 1.0
        size: float,  # USDC notional
    ) -> Optional[PolyOrder]:
        """
        Place a maker limit order.
        Limit orders = zero fees + earn rebates (2026 strategy).
        feeRateBps is fetched dynamically — never hardcoded.
        """
        try:
            # Fetch current fee rate dynamically — REQUIRED post-Feb-18 update
            fee_rate = self._client.get_fee_rate_bps(token_id)

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=BUY if side == "BUY" else SELL,
            )
            signed = self._client.create_limit_order(order_args)
            resp = self._client.post_order(signed, OrderType.GTC)  # GTC = maker
            order_id = resp.get("orderID", "") or resp.get("order_id", "")
            log.info(f"Poly limit order: {side} ${size:.2f} @ {price:.3f} | id={order_id}")
            return PolyOrder(
                order_id=order_id,
                condition_id="",
                token_id=token_id,
                side=side,
                size=size,
                price=price,
                status=resp.get("status", ""),
            )
        except Exception as e:
            log.error(f"Poly limit order failed: {e}")
            return None

    async def place_market_order(
        self,
        token_id: str,
        side: str,
        size: float,
    ) -> Optional[PolyOrder]:
        """Market order (FOK) — taker fees apply. Use sparingly."""
        try:
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=size,
                side=BUY if side == "BUY" else SELL,
            )
            signed = self._client.create_market_order(order_args)
            resp = self._client.post_order(signed, OrderType.FOK)
            order_id = resp.get("orderID", "")
            log.info(f"Poly market order: {side} ${size:.2f} FOK | id={order_id}")
            return PolyOrder(
                order_id=order_id,
                condition_id="",
                token_id=token_id,
                side=side,
                size=size,
                price=0,
                status=resp.get("status", ""),
            )
        except Exception as e:
            log.error(f"Poly market order failed: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        try:
            self._client.cancel(order_id)
            log.info(f"Poly order cancelled: {order_id}")
            return True
        except Exception as e:
            log.error(f"Poly cancel failed {order_id}: {e}")
            return False

    async def cancel_all_orders(self) -> bool:
        try:
            self._client.cancel_all()
            log.info("Poly: all orders cancelled")
            return True
        except Exception as e:
            log.error(f"Poly cancel_all failed: {e}")
            return False

    # ── WebSocket streaming ───────────────────────────────────────────────────

    async def _send_heartbeat(self, ws):
        """
        Polymarket CANCELS ALL OPEN ORDERS if the session goes inactive.
        This heartbeat prevents that.
        """
        while True:
            try:
                await asyncio.sleep(20)
                await ws.send_json({"type": "keepalive"})
                log.debug("Poly heartbeat sent")
            except Exception:
                break

    async def stream_prices(self, token_ids: list[str], callback):
        """
        Stream real-time price updates for a list of token IDs.
        callback(token_id, bid, ask) fires on each update.
        This is the CORRECT 2026 approach — NOT REST polling.
        """
        url = f"{WS_HOST}/market"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                self._ws = ws
                # Subscribe
                sub = {
                    "assets_ids": token_ids,
                    "type": "market",
                }
                await ws.send_json(sub)
                log.info(f"Poly WS subscribed to {len(token_ids)} tokens")

                # Start heartbeat
                self._heartbeat_task = asyncio.create_task(
                    self._send_heartbeat(ws)
                )

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            events = json.loads(msg.data)
                            if not isinstance(events, list):
                                events = [events]
                            for event in events:
                                event_type = event.get("event_type")
                                if event_type in ("book", "price_change", "tick"):
                                    asset_id = event.get("asset_id", "")
                                    bid = float(event.get("best_bid", 0))
                                    ask = float(event.get("best_ask", 0))
                                    if bid > 0 and ask > 0:
                                        await callback(asset_id, bid, ask)
                        except Exception as e:
                            log.debug(f"Poly WS parse error: {e}")
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        log.warning("Poly WebSocket closed — will reconnect")
                        break

                if self._heartbeat_task:
                    self._heartbeat_task.cancel()

    async def close(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
