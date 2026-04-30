"""
Reddit scraper — pulls top posts from drama/revenge subreddits.
"""

import logging
import os
import praw

log = logging.getLogger("video.reddit")

SUBREDDITS = ["ProRevenge", "AmItheAsshole", "NuclearRevenge", "pettyrevenge"]


class RedditScraper:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id="".join(os.environ["REDDIT_CLIENT_ID"].split()),
            client_secret="".join(os.environ["REDDIT_CLIENT_SECRET"].split()),
            user_agent=os.getenv("REDDIT_USER_AGENT", "video_bot/1.0"),
        )

    def get_top_stories(self, count: int = 10) -> list[dict]:
        """
        Returns top stories across all drama subreddits.
        Each dict: title, selftext, score, subreddit, url
        """
        stories = []
        for sub in SUBREDDITS:
            try:
                subreddit = self.reddit.subreddit(sub)
                for post in subreddit.top(time_filter="day", limit=5):
                    if len(post.selftext) < 200:
                        continue
                    stories.append({
                        "title":     post.title,
                        "body":      post.selftext[:3000],
                        "score":     post.score,
                        "subreddit": sub,
                        "url":       f"https://reddit.com{post.permalink}",
                    })
            except Exception as e:
                log.error(f"Reddit fetch failed for r/{sub}: {e}")

        stories.sort(key=lambda x: x["score"], reverse=True)
        log.info(f"Reddit: fetched {len(stories)} stories")
        return stories[:count]
