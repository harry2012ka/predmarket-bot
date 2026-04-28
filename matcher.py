"""
Market matcher — finds equivalent markets across Polymarket and Kalshi.
Uses keyword/NLP matching to correlate identical real-world events.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("bot.matcher")


@dataclass
class MatchedPair:
    """An identical market available on both platforms."""
    kalshi_ticker: str
    kalshi_title: str
    kalshi_yes_bid: float
    kalshi_yes_ask: float

    poly_token_id: str
    poly_question: str
    poly_yes_bid: float
    poly_yes_ask: float

    match_score: float   # 0.0 – 1.0 confidence
    match_reason: str

    @property
    def arb_opportunity(self) -> Optional[tuple[str, float]]:
        """
        Returns (direction, edge_pct) if an arb opportunity exists, else None.

        Arb logic:
          - Buy YES on Kalshi + Buy NO on Polymarket (or vice versa)
          - Arb exists if the combined cost < $1.00 (i.e., cost_yes + cost_no < 1.0)
          - Edge = 1.0 - (best_yes + best_no) across platforms

        Returns direction as "kalshi_yes_poly_no" or "poly_yes_kalshi_no"
        """
        # Strategy A: Buy YES on Kalshi (at ask), Buy NO on Poly (at ask)
        # NO price on Poly = 1 - poly_yes_bid (best bid for YES = best for selling NO)
        poly_no_ask = 1.0 - self.poly_yes_bid
        kalshi_yes_ask = self.kalshi_yes_ask
        cost_a = kalshi_yes_ask + poly_no_ask
        edge_a = 1.0 - cost_a

        # Strategy B: Buy YES on Poly (at ask), Buy NO on Kalshi (at ask)
        kalshi_no_ask = 1.0 - self.kalshi_yes_bid
        poly_yes_ask = self.poly_yes_ask
        cost_b = poly_yes_ask + kalshi_no_ask
        edge_b = 1.0 - cost_b

        if edge_a > edge_b and edge_a > 0:
            return ("kalshi_yes_poly_no", round(edge_a * 100, 3))
        elif edge_b > 0:
            return ("poly_yes_kalshi_no", round(edge_b * 100, 3))
        return None


# ── Keyword mapping — expand this list with common market topics ──────────────
TOPIC_KEYWORDS = {
    "fed_rate": ["fed", "federal reserve", "interest rate", "rate cut", "rate hike", "fomc"],
    "bitcoin": ["bitcoin", "btc", "crypto", "cryptocurrency"],
    "cpi": ["cpi", "inflation", "consumer price"],
    "unemployment": ["unemployment", "jobs", "payroll", "nonfarm"],
    "gdp": ["gdp", "gross domestic product", "economic growth"],
    "election": ["election", "vote", "president", "senator", "governor"],
    "nfl": ["nfl", "super bowl", "football"],
    "nba": ["nba", "basketball", "champion"],
    "oil": ["oil", "crude", "wti", "brent", "opec"],
    "gold": ["gold", "xau"],
    "s&p500": ["s&p", "spx", "sp500", "stock market"],
    "nvidia": ["nvidia", "nvda"],
    "apple": ["apple", "aapl"],
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def _get_topics(text: str) -> set[str]:
    normalized = _normalize(text)
    found = set()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in normalized for kw in keywords):
            found.add(topic)
    return found


def _keyword_overlap_score(text_a: str, text_b: str) -> float:
    """Score 0-1 based on shared topic keywords."""
    topics_a = _get_topics(text_a)
    topics_b = _get_topics(text_b)
    if not topics_a or not topics_b:
        return 0.0
    overlap = topics_a & topics_b
    union = topics_a | topics_b
    return len(overlap) / len(union)


def _threshold_match(text_a: str, text_b: str) -> Optional[float]:
    """
    Check if both texts reference a threshold value (e.g. 'above 70', '$4500').
    Returns the threshold value if found in both, else None.
    """
    pattern = r"[\$]?\s*(\d+(?:\.\d+)?)\s*(?:k|m|b|%|cents?|dollars?)?"
    nums_a = set(re.findall(r"\d+(?:\.\d+)?", text_a.lower()))
    nums_b = set(re.findall(r"\d+(?:\.\d+)?", text_b.lower()))
    shared = nums_a & nums_b
    if shared:
        return float(next(iter(shared)))
    return None


class MarketMatcher:
    """Matches equivalent markets across Polymarket and Kalshi."""

    def __init__(self, min_score: float = 0.4):
        self.min_score = min_score

    def find_pairs(
        self,
        kalshi_markets: list,  # list[KalshiMarket]
        poly_markets: list,    # list[PolyMarket]
    ) -> list[MatchedPair]:
        pairs = []

        for km in kalshi_markets:
            for pm in poly_markets:
                score = self._score_pair(km.title, pm.question)
                if score >= self.min_score:
                    pairs.append(MatchedPair(
                        kalshi_ticker=km.ticker,
                        kalshi_title=km.title,
                        kalshi_yes_bid=km.yes_bid,
                        kalshi_yes_ask=km.yes_ask,
                        poly_token_id=pm.yes_token_id,
                        poly_question=pm.question,
                        poly_yes_bid=pm.yes_bid,
                        poly_yes_ask=pm.yes_ask,
                        match_score=score,
                        match_reason=self._match_reason(km.title, pm.question),
                    ))

        # Sort by arb edge (best opportunities first)
        pairs.sort(key=lambda p: (
            p.arb_opportunity[1] if p.arb_opportunity else 0
        ), reverse=True)

        log.info(f"Found {len(pairs)} matched market pairs")
        return pairs

    def _score_pair(self, title_a: str, title_b: str) -> float:
        topic_score = _keyword_overlap_score(title_a, title_b)
        threshold_match = _threshold_match(title_a, title_b)
        threshold_bonus = 0.2 if threshold_match else 0.0
        return min(1.0, topic_score + threshold_bonus)

    def _match_reason(self, title_a: str, title_b: str) -> str:
        topics = _get_topics(title_a) & _get_topics(title_b)
        return f"shared topics: {', '.join(topics)}" if topics else "numeric threshold match"
