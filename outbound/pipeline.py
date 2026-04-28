"""
Outbound pipeline orchestrator.
Schedule:
  - 08:00 UTC daily  → pull 500 Apollo leads, upload to Instantly
  - Every hour       → check replies, send Cal.com link to interested
  - Every hour       → check Cal.com bookings, send Stripe payment link
  - 18:00 UTC daily  → send daily email report
"""

import asyncio
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from outbound.apollo_client  import ApolloClient
from outbound.instantly_client import InstantlyClient
from outbound.calcom_client  import CalcomClient
from outbound.stripe_client  import StripeClient
from outbound.classifier     import classify_reply
from outbound.report         import send_daily_report
from outbound.db             import OutboundDB

log = logging.getLogger("outbound.pipeline")

CALCOM_BOOKING_LINK = os.getenv("CALCOM_BOOKING_LINK", "https://cal.com/harry")
REPORT_EMAIL        = os.getenv("REPORT_EMAIL", "harry2012k@gmail.com")


class OutboundPipeline:
    def __init__(self):
        self.db        = OutboundDB("data/outbound.db")
        self.apollo    = ApolloClient(os.environ["APOLLO_API_KEY"])
        self.instantly = InstantlyClient(
            api_key=os.environ["INSTANTLY_API_KEY"],
            campaign_id=os.environ["INSTANTLY_CAMPAIGN_ID"],
        )
        self.calcom = CalcomClient(os.environ["CALCOM_API_KEY"])
        self.stripe = StripeClient(os.environ["STRIPE_SECRET_KEY"])
        self.scheduler = AsyncIOScheduler()

    def start(self):
        # Daily 8am UTC — pull leads + upload
        self.scheduler.add_job(
            self._job_pull_and_upload,
            CronTrigger(hour=8, minute=0, timezone="UTC"),
            id="pull_and_upload",
            max_instances=1,
        )
        # Hourly — check replies
        self.scheduler.add_job(
            self._job_check_replies,
            CronTrigger(minute=0, timezone="UTC"),
            id="check_replies",
            max_instances=1,
        )
        # Hourly (offset 30 min) — check bookings
        self.scheduler.add_job(
            self._job_check_bookings,
            CronTrigger(minute=30, timezone="UTC"),
            id="check_bookings",
            max_instances=1,
        )
        # Daily 6pm UTC — send report
        self.scheduler.add_job(
            self._job_send_report,
            CronTrigger(hour=18, minute=0, timezone="UTC"),
            id="daily_report",
            max_instances=1,
        )
        self.scheduler.start()
        log.info("Outbound pipeline started | jobs: pull@8am, replies@hourly, report@6pm")

    def stop(self):
        self.scheduler.shutdown(wait=False)
        self.db.close()

    # ── Jobs ──────────────────────────────────────────────────────────────────

    async def _job_pull_and_upload(self):
        log.info("Pipeline: pulling leads from Apollo...")
        try:
            leads = await self.apollo.fetch_leads(count=500)
        except Exception as e:
            log.error(f"Apollo pull failed: {e}")
            return

        if not leads:
            log.warning("Pipeline: Apollo returned 0 leads")
            return

        # Store in DB (deduped)
        for l in leads:
            self.db.upsert_lead(
                l["email"], l["first_name"], l["last_name"],
                l["title"], l["company"], l["linkedin"],
            )

        # Upload to Instantly
        pending = self.db.get_pending_upload(limit=500)
        if not pending:
            log.info("Pipeline: no new leads to upload")
            return

        leads_to_upload = [dict(r) for r in pending]
        try:
            added = await self.instantly.add_leads(leads_to_upload)
            emails = [r["email"] for r in pending]
            self.db.mark_leads_uploaded(emails)
            log.info(f"Pipeline: uploaded {added} leads to Instantly")
        except Exception as e:
            log.error(f"Instantly upload failed: {e}")

    async def _job_check_replies(self):
        log.info("Pipeline: checking Instantly replies...")
        try:
            replies = await self.instantly.get_recent_replies(limit=100)
        except Exception as e:
            log.error(f"Instantly reply fetch failed: {e}")
            return

        new_count = 0
        for r in replies:
            is_new = self.db.upsert_reply(
                r["id"], r["from_address"], r["subject"],
                r["body"], r["timestamp"],
            )
            if is_new:
                new_count += 1
                classification = classify_reply(r["body"])
                self.db.classify_reply(r["id"], classification)
                log.info(f"Reply from {r['from_address']}: {classification}")

        log.info(f"Pipeline: {new_count} new replies processed")

        # Respond to interested leads with Cal.com link
        await self._send_booking_links()

    async def _send_booking_links(self):
        pending = self.db.get_unresponded_interested()
        for row in pending:
            msg = (
                f"Hi,\n\nThanks for getting back to me! "
                f"I'd love to connect — you can grab a time here: {CALCOM_BOOKING_LINK}\n\n"
                f"Looking forward to chatting.\n\nHarry"
            )
            try:
                ok = await self.instantly.reply_to_email(row["instantly_id"], msg)
                if ok:
                    self.db.mark_reply_responded(row["instantly_id"])
                    log.info(f"Booking link sent to {row['lead_email']}")
            except Exception as e:
                log.error(f"Failed to send booking link to {row['lead_email']}: {e}")

    async def _job_check_bookings(self):
        log.info("Pipeline: checking Cal.com bookings...")
        try:
            bookings = await self.calcom.get_confirmed_bookings(limit=50)
        except Exception as e:
            log.error(f"Cal.com fetch failed: {e}")
            return

        for b in bookings:
            if not b["uid"] or not b["lead_email"]:
                continue
            is_new = self.db.upsert_booking(
                b["uid"], b["lead_email"], b["title"], b["start_time"]
            )
            if is_new:
                log.info(f"New booking: {b['lead_email']} @ {b['start_time']}")

        # Send Stripe payment links for bookings that don't have one yet
        await self._send_payment_links()

    async def _send_payment_links(self):
        pending = self.db.get_bookings_without_payment()
        for row in pending:
            try:
                link_id, link_url = await self.stripe.create_payment_link()
                self.db.log_payment(row["lead_email"], link_url, link_id)
                self.db.mark_payment_sent(row["cal_uid"])
                log.info(f"Stripe payment link sent to {row['lead_email']}: {link_url}")
            except Exception as e:
                log.error(f"Stripe link creation failed for {row['lead_email']}: {e}")

    async def _job_send_report(self):
        log.info("Pipeline: sending daily report...")
        stats = self.db.daily_stats()
        send_daily_report(stats, REPORT_EMAIL)
