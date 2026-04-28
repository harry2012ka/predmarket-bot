"""
Kalshi API client
- RSA-PSS authentication (2025+ format)
- Fixed-point prices as dollar strings (March 2026 migration)
- Demo and production support
- WebSocket streaming
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import aiohttp
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

log = logging.getLogger("bot.kalshi")

KALSHI_PROD_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_DEMO_URL = "https://demo-api.kalshi.co/trade-api/v2"
KALSHI_PROD_WS  = "wss://api.elections.kalshi.com/trade-api/ws/v2"
KALSHI_DEMO_WS  = "wss://demo-api.kalshi.co/trade-api/ws/v2"


@dataclass
class KalshiMarket:
    ticker: str
    title: str
    yes_bid: float   # dollar value 0.0 – 1.0
    yes_ask: float
    no_bid: float
    no_ask: float
    yes_mid: float
    volume_24h: float
    open_interest: float
    status: str


@dataclass
class KalshiOrder:
    order_id: str
    ticker: str
    side: str    # "yes" or "no"
    action: str  # "buy" or "sell"
    count: int
    price: float
    status: str


class KalshiClient:
    def __init__(self, api_key_id: str, private_key_path: str, demo: bool = True):
        self.api_key_id = api_key_id
        self.demo = demo
        self.base_url = KALSHI_DEMO_URL if demo else KALSHI_PROD_URL
        self.ws_url = KALSHI_DEMO_WS if demo else KALSHI_PROD_WS
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

        with open(private_key_path, "rb") as f:
            self._private_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
        log.info(f"Kalshi client initialized ({'DEMO' if demo else 'LIVE'})")

    def _sign(self, method: str, path: str) -> dict:
        """Generate RSA-PSS signed headers for Kalshi API."""
        ts = str(int(time.time() * 1000))
        # Strip query params before signing
        clean_path = path.split("?")[0]
        # Both demo and live require the full path including the /trade-api/v2 prefix
        sign_path = "/trade-api/v2" + clean_path
        msg = ts + method.upper() + sign_path
        sig = self._private_key.sign(
            msg.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
            "Content-Type": "application/json",
        }

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get(self, path: str, params: dict = None) -> dict:
        session = await self._session_get()
        url = self.base_url + path
        headers = self._sign("GET", path)
        async with session.get(url, headers=headers, params=params) as r:
            r.raise_for_status()
            return await r.json()

    async def post(self, path: str, body: dict) -> dict:
        session = await self._session_get()
        url = self.base_url + path
        headers = self._sign("POST", path)
        async with session.post(url, headers=headers, json=body) as r:
            r.raise_for_status()
            return await r.json()

    async def delete(self, path: str, params: dict = None) -> dict:
        session = await self._session_get()
        url = self.base_url + path
        headers = self._sign("DELETE", path)
        async with session.delete(url, headers=headers, params=params) as r:
            r.raise_for_status()
            return await r.json()

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_balance(self) -> float:
        """Returns balance in dollars."""
        data = await self.get("/portfolio/balance")
        # Kalshi returns balance in cents
        return data.get("balance", 0) / 100.0

    # Liquid series to scan. The generic /markets endpoint returns unpriced sports
    # parlays by default — fetching by series_ticker is required to get real markets.
    LIQUID_SERIES = [
        "KXGDP", "KXCPI", "KXFED", "KXUNRATE", "KXNONFARM", "KXPCE",
        "KXBTC", "KXETH", "KXINX", "KXNDX",
        "KXSENATE", "KXHOUSE", "KXPRESIDENT",
        "KXOIL", "KXGOLD",
    ]

    async def get_markets(
        self,
        limit: int = 100,
        status: str = "open",
        series_ticker: str = None,
    ) -> list[KalshiMarket]:
        params: dict = {"limit": limit, "status": status}
        if series_ticker:
            params["series_ticker"] = series_ticker
        data = await self.get("/markets", params=params)
        return self._parse_markets(data.get("markets", []))

    async def get_liquid_markets(self, limit_per_series: int = 20) -> list[KalshiMarket]:
        """
        Fetch priced, liquid markets across all known active series in parallel.
        Much more reliable than the generic /markets endpoint which returns unpriced parlays.
        """
        tasks = [
            self.get_markets(limit=limit_per_series, series_ticker=s)
            for s in self.LIQUID_SERIES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_markets: list[KalshiMarket] = []
        for r in results:
            if isinstance(r, list):
                all_markets.extend(m for m in r if m.yes_bid > 0 and m.yes_ask > 0)
        all_markets.sort(key=lambda x: x.volume_24h, reverse=True)
        return all_markets

    def _parse_markets(self, raw: list) -> list[KalshiMarket]:
        markets = []
        for m in raw:
            try:
                yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
                yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0)
                markets.append(KalshiMarket(
                    ticker=m["ticker"],
                    title=m.get("title", ""),
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=float(m.get("no_bid_dollars") or m.get("no_bid") or 0),
                    no_ask=float(m.get("no_ask_dollars") or m.get("no_ask") or 0),
                    yes_mid=(yes_bid + yes_ask) / 2 if yes_bid and yes_ask else 0,
                    volume_24h=float(m.get("volume_24h_fp") or m.get("volume_24h") or 0),
                    open_interest=float(m.get("open_interest_fp") or m.get("open_interest") or 0),
                    status=m.get("status", ""),
                ))
            except Exception as e:
                log.debug(f"Skipping malformed market {m.get('ticker')}: {e}")
        markets.sort(key=lambda x: x.volume_24h, reverse=True)
        return markets

    async def get_orderbook(self, ticker: str, depth: int = 5) -> dict:
        data = await self.get(f"/markets/{ticker}/orderbook", params={"depth": depth})
        return data.get("orderbook", {})

    # ── Order management ──────────────────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,       # "yes" or "no"
        action: str,     # "buy" or "sell"
        count: int,      # number of contracts
        order_type: str, # "limit" or "market"
        price: float = None,  # required for limit orders (0.0 – 1.0 dollar format)
    ) -> KalshiOrder:
        """Place a limit or market order."""
        body = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": order_type,
            "client_order_id": str(uuid.uuid4()),
        }
        if order_type == "limit" and price is not None:
            # Kalshi prices are integer cents (e.g. 0.72 dollars → 72)
            cent_price = int(round(price * 100))
            if side == "yes":
                body["yes_price"] = cent_price
            else:
                body["no_price"] = cent_price

        resp = await self.post("/portfolio/orders", body)
        order = resp.get("order", {})
        log.info(f"Kalshi order placed: {ticker} {action} {count}x {side} @ {price}")
        return KalshiOrder(
            order_id=order.get("order_id", ""),
            ticker=ticker,
            side=side,
            action=action,
            count=count,
            price=price or 0,
            status=order.get("status", ""),
        )

    async def cancel_order(self, order_id: str) -> bool:
        try:
            await self.delete(f"/portfolio/orders/{order_id}")
            log.info(f"Kalshi order cancelled: {order_id}")
            return True
        except Exception as e:
            log.error(f"Failed to cancel Kalshi order {order_id}: {e}")
            return False

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders by fetching and cancelling each one."""
        try:
            data = await self.get("/portfolio/orders", params={"status": "resting"})
            orders = data.get("orders", [])
            if not orders:
                return 0
            results = await asyncio.gather(
                *[self.cancel_order(o["order_id"]) for o in orders],
                return_exceptions=True,
            )
            cancelled = sum(1 for r in results if r is True)
            log.info(f"Kalshi: cancelled {cancelled}/{len(orders)} open orders")
            return cancelled
        except Exception as e:
            log.error(f"Kalshi cancel_all failed: {e}")
            return 0

    async def get_positions(self) -> list[dict]:
        data = await self.get("/portfolio/positions")
        return data.get("market_positions", [])

    # ── WebSocket streaming ───────────────────────────────────────────────────

    async def stream_markets(self, tickers: list[str], callback):
        """
        Stream real-time orderbook updates via WebSocket.
        callback(ticker, yes_bid, yes_ask) is called on each update.
        """
        headers = self._sign("GET", "/trade-api/ws/v2")
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.ws_url, headers=headers) as ws:
                self._ws = ws
                # Subscribe to orderbook channels
                sub_msg = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": tickers,
                    }
                }
                await ws.send_json(sub_msg)
                log.info(f"Kalshi WS subscribed to {len(tickers)} markets")

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            msg_type = data.get("type")
                            if msg_type in ("orderbook_snapshot", "orderbook_delta"):
                                ticker = data.get("market_ticker", "")
                                yes_bids = data.get("yes", {}).get("bids", [])
                                yes_asks = data.get("yes", {}).get("asks", [])
                                if yes_bids and yes_asks:
                                    best_bid = float(yes_bids[0][0])
                                    best_ask = float(yes_asks[0][0])
                                    await callback(ticker, best_bid, best_ask)
                        except Exception as e:
                            log.debug(f"Kalshi WS parse error: {e}")
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        log.warning("Kalshi WebSocket closed/error — will reconnect")
                        break

    async def close(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
