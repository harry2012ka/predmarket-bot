"""
Instantly.ai API v2 client.
- Add leads to campaign
- Poll for new replies
- Send reply emails (booking link, etc.)
"""

import logging
import aiohttp

log = logging.getLogger("outbound.instantly")

INSTANTLY_BASE = "https://api.instantly.ai/api/v2"


class InstantlyClient:
    def __init__(self, api_key: str, campaign_id: str):
        self.api_key = "".join(api_key.split())
        self.campaign_id = "".join(campaign_id.split())
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ── Lead upload ───────────────────────────────────────────────────────────

    async def add_leads(self, leads: list[dict]) -> int:
        """
        Upload leads to the campaign.
        leads: list of dicts with keys: email, first_name, last_name, company
        Returns count of successfully added leads.
        """
        if not leads:
            return 0

        # Instantly accepts up to 1000 per bulk call
        payload = {
            "campaign_id": self.campaign_id,
            "leads": [
                {
                    "email":      l["email"],
                    "first_name": l.get("first_name", ""),
                    "last_name":  l.get("last_name", ""),
                    "company_name": l.get("company", ""),
                    "custom_variables": {
                        "title":   l.get("title", ""),
                        "linkedin": l.get("linkedin", ""),
                    },
                }
                for l in leads
            ],
            "skip_if_in_workspace": True,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{INSTANTLY_BASE}/lead/add/bulk",
                json=payload,
                headers=self._headers,
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    log.error(f"Instantly add_leads failed {resp.status}: {text}")
                    return 0
                data = await resp.json()
                added = data.get("total_new_leads", len(leads))
                log.info(f"Instantly: uploaded {added} leads to campaign {self.campaign_id}")
                return added

    # ── Reply polling ─────────────────────────────────────────────────────────

    async def get_recent_replies(self, limit: int = 100) -> list[dict]:
        """
        Fetch recent reply emails from the campaign.
        Returns list of dicts: id, from_address, subject, body, timestamp
        """
        params = {
            "campaign_id": self.campaign_id,
            "type": "reply",
            "limit": limit,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{INSTANTLY_BASE}/emails",
                params=params,
                headers=self._headers,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    log.error(f"Instantly get_replies failed {resp.status}: {text}")
                    return []
                data = await resp.json()
                items = data.get("items", data) if isinstance(data, dict) else data
                replies = []
                for item in (items if isinstance(items, list) else []):
                    replies.append({
                        "id":           item.get("id", ""),
                        "from_address": item.get("from_address", item.get("from", "")),
                        "subject":      item.get("subject", ""),
                        "body":         item.get("body", item.get("text", "")),
                        "timestamp":    item.get("timestamp", item.get("created_at", "")),
                    })
                return replies

    # ── Send reply ────────────────────────────────────────────────────────────

    async def reply_to_email(self, email_id: str, body: str) -> bool:
        """Send a reply to an email thread by email ID."""
        payload = {"body": body}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{INSTANTLY_BASE}/emails/{email_id}/reply",
                json=payload,
                headers=self._headers,
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    log.error(f"Instantly reply failed {resp.status}: {text}")
                    return False
                log.info(f"Instantly: replied to email {email_id}")
                return True

    # ── Campaign helpers ──────────────────────────────────────────────────────

    async def list_campaigns(self) -> list[dict]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{INSTANTLY_BASE}/campaign/list",
                headers=self._headers,
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data if isinstance(data, list) else data.get("campaigns", [])
