"""
Stripe client — creates and sends $500/month payment links.
"""

import logging
import aiohttp

log = logging.getLogger("outbound.stripe")

STRIPE_BASE = "https://api.stripe.com/v1"
STARTER_PRICE_USD = 500
PRODUCT_NAME = "Starter Plan"


class StripeClient:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self._auth = aiohttp.BasicAuth(secret_key, "")

    async def create_payment_link(self, price_usd: int = STARTER_PRICE_USD) -> tuple[str, str]:
        """
        Creates a one-time-use Stripe payment link for $price_usd/month.
        Returns (payment_link_id, payment_link_url).
        """
        async with aiohttp.ClientSession() as session:
            # Step 1: create a price object for the recurring product
            price_resp = await session.post(
                f"{STRIPE_BASE}/prices",
                auth=self._auth,
                data={
                    "currency": "usd",
                    "unit_amount": price_usd * 100,
                    "recurring[interval]": "month",
                    "product_data[name]": PRODUCT_NAME,
                },
            )
            price_resp.raise_for_status()
            price_data = await price_resp.json()
            price_id = price_data["id"]

            # Step 2: create payment link
            link_resp = await session.post(
                f"{STRIPE_BASE}/payment_links",
                auth=self._auth,
                data={
                    "line_items[0][price]": price_id,
                    "line_items[0][quantity]": "1",
                },
            )
            link_resp.raise_for_status()
            link_data = await link_resp.json()
            link_id  = link_data["id"]
            link_url = link_data["url"]

            log.info(f"Stripe payment link created: {link_url}")
            return link_id, link_url
