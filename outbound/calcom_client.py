"""
Cal.com API client — detects new confirmed bookings.
"""

import logging
import aiohttp

log = logging.getLogger("outbound.calcom")

CALCOM_BASE = "https://api.cal.com/v2"


class CalcomClient:
    def __init__(self, api_key: str):
        self.api_key = "".join(api_key.split())
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "cal-api-version": "2024-08-13",
        }

    async def get_confirmed_bookings(self, limit: int = 100) -> list[dict]:
        """
        Returns confirmed bookings.
        Each dict: uid, attendee_email, title, start_time
        """
        params = {"status": "accepted", "take": limit}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CALCOM_BASE}/bookings",
                params=params,
                headers=self._headers,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    log.error(f"Cal.com get_bookings failed {resp.status}: {text}")
                    return []
                data = await resp.json()
                bookings_raw = data.get("data", {}).get("bookings", [])
                results = []
                for b in bookings_raw:
                    attendees = b.get("attendees", [])
                    lead_email = attendees[0].get("email", "") if attendees else ""
                    results.append({
                        "uid":        b.get("uid", ""),
                        "lead_email": lead_email,
                        "title":      b.get("title", ""),
                        "start_time": b.get("startTime", ""),
                    })
                return results
