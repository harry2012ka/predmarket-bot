"""
Strategy modules:
  1. ArbStrategy     — cross-platform arbitrage (Poly ↔ Kalshi)
  2. EdgeStrategy    — edge hunting on mispriced markets
  3. MakerStrategy   — market making (post limit orders, collect spread)
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("bot.strategy")


@dataclass
class TradeSignal:
    strategy: str          # "arb", "edge", "maker"
    description: str

    # Kalshi leg (None if not trading Kalshi)
    kalshi_ticker: Optional[str] = None
    kalshi_side: Optional[str] = None    # "yes" or "no"
    kalshi_action: Optional[str] = None  # "buy" or "sell"
    kalshi_price: Optional[float] = None
    kalshi_count: Optional[int] = None

    # Polymarket leg (None if not trading Poly)
    poly_token_id: Optional[str] = None
    poly_side: Optional[str] = None     # "BUY" or "SELL"
    poly_price: Optional[float] = None
    poly_size_usd: Optional[float] = None

    # Signal metadata
    expected_edge_pct: float = 0.0
    confidence: float = 0.0


# ── Shared Kelly sizing ────────────────────────────────────────────────────────

def kelly_size(
    edge_pct: float,
    win_prob: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_position: float = 25.0,
) -> float:
    """
    Fractional Kelly criterion position sizing.
    edge_pct: expected edge as percentage (e.g. 3.0 = 3%)
    win_prob: estimated probability of winning (0-1)
    Returns dollar amount to bet.
    """
    if win_prob <= 0 or win_prob >= 1 or edge_pct <= 0:
        return 0.0
    # Kelly formula: f = (bp - q) / b  where b = odds, p = win prob, q = 1-p
    b = (1 / (1 - win_prob)) - 1  # implied odds
    p = win_prob
    q = 1 - p
    kelly_pct = (b * p - q) / b
    fractional = kelly_pct * kelly_fraction
    size = bankroll * max(0, fractional)
    return round(min(size, max_position), 2)


# ── Strategy 1: Cross-platform arbitrage ──────────────────────────────────────

class ArbStrategy:
    """
    Identifies risk-free arbitrage between Polymarket and Kalshi.
    Fires when YES(A) + NO(B) < $1.00 (combined cost < 1, guaranteed $1 payout).
    """

    def __init__(self, min_edge_pct: float = 2.0, max_position_usd: float = 25.0):
        self.min_edge_pct = min_edge_pct
        self.max_position_usd = max_position_usd

    def evaluate(self, pair, bankroll: float) -> Optional[TradeSignal]:
        """
        pair: MatchedPair
        Returns a TradeSignal if arb exists above threshold, else None.
        """
        arb = pair.arb_opportunity
        if arb is None:
            return None

        direction, edge_pct = arb
        if edge_pct < self.min_edge_pct:
            return None

        # Size: use edge as proxy for win prob in Kelly (arb = ~certainty)
        size = min(self.max_position_usd, bankroll * 0.05)  # max 5% of bankroll per arb

        if direction == "kalshi_yes_poly_no":
            # Buy YES on Kalshi, Buy NO on Poly (= Sell YES on Poly)
            contracts = max(1, int(size / (pair.kalshi_yes_ask * 100)))
            return TradeSignal(
                strategy="arb",
                description=f"ARB {edge_pct:.2f}% edge | {pair.kalshi_title[:50]}",
                kalshi_ticker=pair.kalshi_ticker,
                kalshi_side="yes",
                kalshi_action="buy",
                kalshi_price=pair.kalshi_yes_ask,
                kalshi_count=contracts,
                poly_token_id=pair.poly_token_id,
                poly_side="SELL",  # Selling YES on Poly = buying NO
                poly_price=pair.poly_yes_bid,
                poly_size_usd=size,
                expected_edge_pct=edge_pct,
                confidence=0.95,
            )
        else:  # poly_yes_kalshi_no
            contracts = max(1, int(size / ((1 - pair.kalshi_yes_bid) * 100)))
            return TradeSignal(
                strategy="arb",
                description=f"ARB {edge_pct:.2f}% edge | {pair.kalshi_title[:50]}",
                kalshi_ticker=pair.kalshi_ticker,
                kalshi_side="no",
                kalshi_action="buy",
                kalshi_price=1.0 - pair.kalshi_yes_bid,
                kalshi_count=contracts,
                poly_token_id=pair.poly_token_id,
                poly_side="BUY",
                poly_price=pair.poly_yes_ask,
                poly_size_usd=size,
                expected_edge_pct=edge_pct,
                confidence=0.95,
            )


# ── Strategy 2: Edge hunting (mispriced markets) ──────────────────────────────

class EdgeStrategy:
    """
    Finds markets where the price deviates significantly from a model estimate.
    The model is a simple news-aware base rate model — extend with better signals.
    """

    def __init__(
        self,
        min_deviation_pct: float = 5.0,
        kelly_fraction: float = 0.25,
        max_position_usd: float = 25.0,
        signal_refresh_interval_sec: float = 60.0,
    ):
        self.min_deviation_pct = min_deviation_pct
        self.kelly_fraction = kelly_fraction
        self.max_position_usd = max_position_usd
        self.signal_refresh_interval_sec = signal_refresh_interval_sec
        self._signal_cache: dict[str, float] = {}
        self._last_refresh: float = 0.0

    def _estimate_fair_value(self, question: str, current_price: float) -> Optional[float]:
        """Returns Manifold cross-market probability as fair value, or None if no match."""
        return self._signal_cache.get(question)

    async def refresh_signals(self, markets) -> None:
        """
        Fetch Manifold cross-reference signals for the top active markets.
        Throttled to once per signal_refresh_interval_sec — safe to call every scan.
        """
        now = time.time()
        if now - self._last_refresh < self.signal_refresh_interval_sec:
            return
        self._last_refresh = now

        candidates = [m for m in markets if 0.05 <= m.yes_mid <= 0.95][:25]
        if not candidates:
            return

        from signals import fetch_signals
        titles = [m.title for m in candidates]
        fresh = await fetch_signals(titles)
        hits = sum(1 for v in fresh.values() if v is not None)
        self._signal_cache.update({k: v for k, v in fresh.items() if v is not None})
        log.info(f"Signal refresh: {hits}/{len(titles)} Manifold matches | cache={len(self._signal_cache)}")

    def evaluate_kalshi(
        self, market, bankroll: float
    ) -> Optional[TradeSignal]:
        fair = self._estimate_fair_value(market.title, market.yes_mid)
        if fair is None:
            return None

        deviation = (fair - market.yes_mid) * 100
        if abs(deviation) < self.min_deviation_pct:
            return None

        side = "yes" if fair > market.yes_mid else "no"
        price = market.yes_ask if side == "yes" else (1 - market.yes_bid)
        size = kelly_size(abs(deviation), fair, bankroll, self.kelly_fraction, self.max_position_usd)

        if size < 1.0:
            return None

        contracts = max(1, int(size / (price * 100)))
        log.info(f"Edge signal on {market.ticker}: fair={fair:.2f} market={market.yes_mid:.2f} dev={deviation:.1f}%")

        return TradeSignal(
            strategy="edge",
            description=f"EDGE {deviation:+.1f}% | {market.title[:50]}",
            kalshi_ticker=market.ticker,
            kalshi_side=side,
            kalshi_action="buy",
            kalshi_price=price,
            kalshi_count=contracts,
            expected_edge_pct=abs(deviation),
            confidence=0.6,
        )

    def evaluate_poly(self, market, bankroll: float) -> Optional[TradeSignal]:
        fair = self._estimate_fair_value(market.question, market.yes_mid)
        if fair is None:
            return None

        deviation = (fair - market.yes_mid) * 100
        if abs(deviation) < self.min_deviation_pct:
            return None

        side = "BUY" if fair > market.yes_mid else "SELL"
        price = market.yes_ask if side == "BUY" else market.yes_bid
        size = kelly_size(abs(deviation), fair, bankroll, self.kelly_fraction, self.max_position_usd)

        if size < 1.0:
            return None

        return TradeSignal(
            strategy="edge",
            description=f"EDGE {deviation:+.1f}% | {market.question[:50]}",
            poly_token_id=market.yes_token_id,
            poly_side=side,
            poly_price=price,
            poly_size_usd=size,
            expected_edge_pct=abs(deviation),
            confidence=0.6,
        )


# ── Strategy 3: Market making ─────────────────────────────────────────────────

class MakerStrategy:
    """
    Posts limit orders on both sides of a market to collect the bid-ask spread.
    Works best on Kalshi (CLOB) and Polymarket (zero fees for makers + rebates).
    Only trade markets with enough liquidity and reasonable spread.
    """

    def __init__(
        self,
        target_spread_pct: float = 1.0,  # minimum spread to post around
        max_position_usd: float = 20.0,
        min_volume_24h: float = 500,     # only make markets with decent volume
    ):
        self.target_spread_pct = target_spread_pct
        self.max_position_usd = max_position_usd
        self.min_volume_24h = min_volume_24h

    def get_kalshi_quotes(self, market) -> Optional[tuple[TradeSignal, TradeSignal]]:
        """
        Returns (bid_signal, ask_signal) — post limit orders on both sides.
        """
        if market.volume_24h < self.min_volume_24h:
            return None

        current_spread = (market.yes_ask - market.yes_bid) * 100
        if current_spread < self.target_spread_pct:
            return None  # Spread too tight, not worth making

        mid = market.yes_mid
        half_spread = (self.target_spread_pct / 100) / 2

        bid_price = round(mid - half_spread, 4)
        ask_price = round(mid + half_spread, 4)

        # Keep prices valid
        bid_price = max(0.02, min(0.98, bid_price))
        ask_price = max(0.02, min(0.98, ask_price))

        contracts = max(1, int(self.max_position_usd / 100))

        bid_signal = TradeSignal(
            strategy="maker",
            description=f"MAKE BID {bid_price:.3f} | {market.title[:40]}",
            kalshi_ticker=market.ticker,
            kalshi_side="yes",
            kalshi_action="buy",
            kalshi_price=bid_price,
            kalshi_count=contracts,
            expected_edge_pct=current_spread / 2,
            confidence=0.5,
        )
        ask_signal = TradeSignal(
            strategy="maker",
            description=f"MAKE ASK {ask_price:.3f} | {market.title[:40]}",
            kalshi_ticker=market.ticker,
            kalshi_side="no",
            kalshi_action="buy",
            kalshi_price=1.0 - ask_price,
            kalshi_count=contracts,
            expected_edge_pct=current_spread / 2,
            confidence=0.5,
        )
        return bid_signal, ask_signal

    def get_poly_quotes(self, market) -> Optional[tuple[TradeSignal, TradeSignal]]:
        """Returns (bid_signal, ask_signal) for Polymarket maker orders."""
        if market.volume_24h < self.min_volume_24h:
            return None
        if not market.enable_order_book:
            return None

        current_spread = (market.yes_ask - market.yes_bid) * 100
        if current_spread < self.target_spread_pct:
            return None

        mid = market.yes_mid
        half_spread = (self.target_spread_pct / 100) / 2

        bid_price = round(max(0.02, min(0.98, mid - half_spread)), 4)
        ask_price = round(max(0.02, min(0.98, mid + half_spread)), 4)

        bid_signal = TradeSignal(
            strategy="maker",
            description=f"POLY MAKE BID {bid_price:.3f} | {market.question[:40]}",
            poly_token_id=market.yes_token_id,
            poly_side="BUY",
            poly_price=bid_price,
            poly_size_usd=self.max_position_usd,
            expected_edge_pct=current_spread / 2,
            confidence=0.5,
        )
        ask_signal = TradeSignal(
            strategy="maker",
            description=f"POLY MAKE ASK {ask_price:.3f} | {market.question[:40]}",
            poly_token_id=market.yes_token_id,
            poly_side="SELL",
            poly_price=ask_price,
            poly_size_usd=self.max_position_usd,
            expected_edge_pct=current_spread / 2,
            confidence=0.5,
        )
        return bid_signal, ask_signal
