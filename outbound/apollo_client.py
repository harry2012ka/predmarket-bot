"""
Apollo.io API client — pulls SaaS founder leads (CEO/Founder/Co-Founder, 1-50 employees).
"""

import logging
import aiohttp

log = logging.getLogger("outbound.apollo")

APOLLO_BASE = "https://api.apollo.io/api/v1"

FOUNDER_TITLES = [
    "CEO", "Founder", "Co-Founder", "Co Founder",
    "Chief Executive Officer", "Founding CEO",
]


class ApolloClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_leads(self, count: int = 500, page: int = 1) -> list[dict]:
        """
        Returns up to `count` SaaS founder leads.
        Each dict has: email, first_name, last_name, title, company, linkedin_url
        """
        payload = {
            "api_key": self.api_key,
            "per_page": min(count, 100),
            "page": page,
            "person_titles": FOUNDER_TITLES,
            "organization_num_employees_ranges": ["1,50"],
            "prospected_by_current_team": ["no"],
            "email_status": ["verified"],
            "q_keywords": "SaaS software",
        }

        all_leads = []
        async with aiohttp.ClientSession() as session:
            pages_needed = (count + 99) // 100
            for p in range(1, pages_needed + 1):
                payload["page"] = p
                try:
                    async with session.post(
                        f"{APOLLO_BASE}/mixed_people/search",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                        people = data.get("people", [])
                        if not people:
                            break
                        for p_data in people:
                            email = p_data.get("email")
                            if not email or email == "email_not_unlocked@domain.com":
                                continue
                            all_leads.append({
                                "email":       email,
                                "first_name":  p_data.get("first_name", ""),
                                "last_name":   p_data.get("last_name", ""),
                                "title":       p_data.get("title", ""),
                                "company":     (p_data.get("organization") or {}).get("name", ""),
                                "linkedin":    p_data.get("linkedin_url", ""),
                            })
                        if len(all_leads) >= count:
                            break
                except Exception as e:
                    log.error(f"Apollo fetch page {p} failed: {e}")
                    break

        log.info(f"Apollo: fetched {len(all_leads)} leads")
        return all_leads[:count]
