"""
Cal.com API client — detects new confirmed bookings.
"""

import logging
import aiohttp

log = logging.getLogger("outbound.calcom")

CALCOM_BASE = "https://api.cal.com/v1"


class CalcomClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def get_confirmed_bookings(self, limit: int = 100) -> list[dict]:
        """
        Returns confirmed bookings.
        Each dict: uid, attendee_email, title, start_time
        """
        params = {
            "apiKey": self.api_key,
            "status": "accepted",
            "take": limit,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CALCOM_BASE}/bookings",
                params=params,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    log.error(f"Cal.com get_bookings failed {resp.status}: {text}")
                    return []
                data = await resp.json()
                bookings_raw = data.get("bookings", [])
                results = []
                for b in bookings_raw:
                    attendees = b.get("attendees", [])
                    lead_email = attendees[0].get("email", "") if attendees else ""
                    results.append({
                        "uid":         b.get("uid", ""),
                        "lead_email":  lead_email,
                        "title":       b.get("title", ""),
                        "start_time":  b.get("startTime", ""),
                    })
                return results
