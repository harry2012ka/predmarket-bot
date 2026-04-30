"""
Reddit scraper — uses public JSON feed, no API key required.
"""

import logging
import aiohttp

log = logging.getLogger("video.reddit")

SUBREDDITS = ["ProRevenge", "AmItheAsshole", "NuclearRevenge", "pettyrevenge"]
HEADERS    = {"User-Agent": "Mozilla/5.0 (compatible; video_bot/1.0)"}


async def get_top_stories(count: int = 10) -> list[dict]:
    """
    Fetches top posts from all drama subreddits via public JSON feed.
    Returns list of {title, body, score, subreddit, url}
    """
    stories = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for sub in SUBREDDITS:
            url = f"https://www.reddit.com/r/{sub}/top.json?sort=top&t=day&limit=10"
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        log.warning(f"Reddit JSON {sub} returned {resp.status}")
                        continue
                    data = await resp.json()
                    posts = data.get("data", {}).get("children", [])
                    for post in posts:
                        p = post.get("data", {})
                        body = p.get("selftext", "")
                        if len(body) < 200 or body == "[removed]":
                            continue
                        stories.append({
                            "title":     p.get("title", ""),
                            "body":      body[:3000],
                            "score":     p.get("score", 0),
                            "subreddit": sub,
                            "url":       f"https://reddit.com{p.get('permalink', '')}",
                        })
            except Exception as e:
                log.error(f"Reddit fetch failed for r/{sub}: {e}")

    stories.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Reddit: fetched {len(stories)} stories")
    return stories[:count]
