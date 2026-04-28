"""
External signal sources for fair-value estimation.
Uses Manifold Markets (free, no auth required) as a cross-market reference price.
Fetched in batch once per minute — not on every scan — to avoid hammering a free API.
"""

import asyncio
import logging
from typing import Optional

import aiohttp

log = logging.getLogger("bot.signals")

MANIFOLD_SEARCH = "https://api.manifold.markets/v0/search-markets"
_SEM = asyncio.Semaphore(5)  # max 5 concurrent Manifold requests


def _keyword_overlap(a: str, b: str) -> float:
    """Jaccard similarity of significant words between two market titles."""
    noise = {"will", "the", "and", "for", "this", "that", "with", "from",
             "have", "been", "does", "what", "when", "than", "its", "into"}
    def sig(s: str) -> set[str]:
        return {w.lower().rstrip("?.,") for w in s.split()
                if len(w) >= 4 and w.lower() not in noise}
    wa, wb = sig(a), sig(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


async def _fetch_one(
    session: aiohttp.ClientSession,
    title: str,
    min_overlap: float = 0.30,
) -> Optional[float]:
    """Search Manifold for a market matching `title`. Returns probability or None."""
    query = " ".join(title.split()[:7])
    async with _SEM:
        try:
            async with session.get(
                MANIFOLD_SEARCH,
                params={"term": query, "limit": 5, "sort": "score"},
                timeout=aiohttp.ClientTimeout(total=6),
            ) as r:
                if r.status != 200:
                    return None
                markets = await r.json()
        except Exception as e:
            log.debug(f"Manifold fetch error for '{title[:40]}': {e}")
            return None

    for m in markets:
        prob = m.get("probability")
        if prob is None or m.get("isResolved"):
            continue
        overlap = _keyword_overlap(title, m.get("question", ""))
        if overlap >= min_overlap:
            log.debug(
                f"Manifold match ({overlap:.0%}): "
                f"'{m['question'][:60]}' → {prob:.2f} (kalshi: '{title[:40]}')"
            )
            return float(prob)

    return None


async def fetch_signals(titles: list[str]) -> dict[str, Optional[float]]:
    """
    Fetch Manifold cross-reference probabilities for a batch of Kalshi market titles.
    Returns {title: probability} where probability is None if no match was found.
    """
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *[_fetch_one(session, t) for t in titles],
            return_exceptions=True,
        )
    return {
        title: (r if not isinstance(r, Exception) else None)
        for title, r in zip(titles, results)
    }
