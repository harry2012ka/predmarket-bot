"""
Daily email report — sends a summary of pipeline activity at 6pm UTC.
Uses Gmail SMTP (requires GMAIL_USER + GMAIL_APP_PASSWORD env vars).
"""

import logging
import smtplib
import os
from email.mime.text import MIMEText
from datetime import datetime

log = logging.getLogger("outbound.report")


def send_daily_report(stats: dict, to_email: str):
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")

    if not gmail_user or not gmail_pass:
        log.warning("Report: GMAIL_USER or GMAIL_APP_PASSWORD not set — skipping email")
        _log_report(stats)
        return

    today = datetime.utcnow().strftime("%b %d, %Y")
    subject = f"Outbound Pipeline Report — {today}"
    body = _build_body(stats, today)

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, gmail_pass)
            smtp.sendmail(gmail_user, [to_email], msg.as_string())
        log.info(f"Daily report sent to {to_email}")
    except Exception as e:
        log.error(f"Failed to send report: {e}")
        _log_report(stats)


def _build_body(stats: dict, today: str) -> str:
    reply_rate = (
        f"{stats['replies_total'] / stats['leads_uploaded'] * 100:.1f}%"
        if stats["leads_uploaded"] else "—"
    )
    interest_rate = (
        f"{stats['interested'] / stats['replies_total'] * 100:.1f}%"
        if stats["replies_total"] else "—"
    )
    return f"""Outbound Pipeline — Daily Report ({today})
{'=' * 45}

LEADS
  Fetched from Apollo:   {stats['leads_fetched']}
  Uploaded to Instantly: {stats['leads_uploaded']}

REPLIES
  Total replies:         {stats['replies_total']}
  Reply rate:            {reply_rate}
  Interested:            {stats['interested']}
  Not interested:        {stats['not_interested']}
  OOO:                   {stats['ooo']}
  Interest rate:         {interest_rate}

PIPELINE
  Calls booked:          {stats['bookings']}
  Payment links sent:    {stats['payments_sent']}

{'=' * 45}
Pipeline running 24/7 on Railway.
"""


def _log_report(stats: dict):
    log.info(
        f"DAILY REPORT | leads={stats['leads_fetched']} uploaded={stats['leads_uploaded']} "
        f"replies={stats['replies_total']} interested={stats['interested']} "
        f"bookings={stats['bookings']} payments={stats['payments_sent']}"
    )
