"""
SQLite storage for the outbound pipeline.
Tables: leads, replies, bookings, payments
"""

import sqlite3
import logging
from datetime import datetime

log = logging.getLogger("outbound.db")


class OutboundDB:
    def __init__(self, path: str = "data/outbound.db"):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT UNIQUE NOT NULL,
                first_name  TEXT,
                last_name   TEXT,
                title       TEXT,
                company     TEXT,
                linkedin    TEXT,
                fetched_at  TEXT NOT NULL,
                uploaded_at TEXT
            );

            CREATE TABLE IF NOT EXISTS replies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                instantly_id    TEXT UNIQUE,
                lead_email      TEXT NOT NULL,
                subject         TEXT,
                body            TEXT,
                received_at     TEXT NOT NULL,
                classification  TEXT,   -- 'interested' | 'not_interested' | 'ooo' | 'unknown'
                responded_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cal_uid     TEXT UNIQUE NOT NULL,
                lead_email  TEXT NOT NULL,
                title       TEXT,
                start_time  TEXT,
                detected_at TEXT NOT NULL,
                payment_sent_at TEXT
            );

            CREATE TABLE IF NOT EXISTS payments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_email      TEXT NOT NULL,
                stripe_link_url TEXT NOT NULL,
                stripe_link_id  TEXT,
                sent_at         TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── Leads ─────────────────────────────────────────────────────────────────

    def upsert_lead(self, email, first_name, last_name, title, company, linkedin):
        now = datetime.utcnow().isoformat()
        self._conn.execute("""
            INSERT INTO leads (email, first_name, last_name, title, company, linkedin, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO NOTHING
        """, (email, first_name, last_name, title, company, linkedin, now))
        self._conn.commit()

    def mark_leads_uploaded(self, emails: list[str]):
        now = datetime.utcnow().isoformat()
        self._conn.executemany(
            "UPDATE leads SET uploaded_at=? WHERE email=?",
            [(now, e) for e in emails],
        )
        self._conn.commit()

    def get_pending_upload(self, limit=500) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM leads WHERE uploaded_at IS NULL ORDER BY fetched_at LIMIT ?", (limit,)
        ).fetchall()

    def lead_count_today(self) -> int:
        today = datetime.utcnow().date().isoformat()
        return self._conn.execute(
            "SELECT COUNT(*) FROM leads WHERE fetched_at >= ?", (today,)
        ).fetchone()[0]

    # ── Replies ───────────────────────────────────────────────────────────────

    def upsert_reply(self, instantly_id, lead_email, subject, body, received_at) -> bool:
        try:
            self._conn.execute("""
                INSERT INTO replies (instantly_id, lead_email, subject, body, received_at)
                VALUES (?, ?, ?, ?, ?)
            """, (instantly_id, lead_email, subject, body, received_at))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # already seen

    def classify_reply(self, instantly_id: str, classification: str):
        self._conn.execute(
            "UPDATE replies SET classification=? WHERE instantly_id=?",
            (classification, instantly_id),
        )
        self._conn.commit()

    def mark_reply_responded(self, instantly_id: str):
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            "UPDATE replies SET responded_at=? WHERE instantly_id=?",
            (now, instantly_id),
        )
        self._conn.commit()

    def get_unresponded_interested(self) -> list[sqlite3.Row]:
        return self._conn.execute("""
            SELECT * FROM replies
            WHERE classification='interested' AND responded_at IS NULL
        """).fetchall()

    # ── Bookings ──────────────────────────────────────────────────────────────

    def upsert_booking(self, cal_uid, lead_email, title, start_time) -> bool:
        now = datetime.utcnow().isoformat()
        try:
            self._conn.execute("""
                INSERT INTO bookings (cal_uid, lead_email, title, start_time, detected_at)
                VALUES (?, ?, ?, ?, ?)
            """, (cal_uid, lead_email, title, start_time, now))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_bookings_without_payment(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM bookings WHERE payment_sent_at IS NULL"
        ).fetchall()

    def mark_payment_sent(self, cal_uid: str):
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            "UPDATE bookings SET payment_sent_at=? WHERE cal_uid=?",
            (now, cal_uid),
        )
        self._conn.commit()

    # ── Payments ──────────────────────────────────────────────────────────────

    def log_payment(self, lead_email, stripe_link_url, stripe_link_id):
        now = datetime.utcnow().isoformat()
        self._conn.execute("""
            INSERT INTO payments (lead_email, stripe_link_url, stripe_link_id, sent_at)
            VALUES (?, ?, ?, ?)
        """, (lead_email, stripe_link_url, stripe_link_id, now))
        self._conn.commit()

    # ── Report data ───────────────────────────────────────────────────────────

    def daily_stats(self) -> dict:
        today = datetime.utcnow().date().isoformat()
        leads_fetched  = self._conn.execute("SELECT COUNT(*) FROM leads WHERE fetched_at >= ?",  (today,)).fetchone()[0]
        leads_uploaded = self._conn.execute("SELECT COUNT(*) FROM leads WHERE uploaded_at >= ?", (today,)).fetchone()[0]
        replies_total  = self._conn.execute("SELECT COUNT(*) FROM replies WHERE received_at >= ?", (today,)).fetchone()[0]
        interested     = self._conn.execute("SELECT COUNT(*) FROM replies WHERE classification='interested' AND received_at >= ?", (today,)).fetchone()[0]
        not_interested = self._conn.execute("SELECT COUNT(*) FROM replies WHERE classification='not_interested' AND received_at >= ?", (today,)).fetchone()[0]
        ooo            = self._conn.execute("SELECT COUNT(*) FROM replies WHERE classification='ooo' AND received_at >= ?", (today,)).fetchone()[0]
        bookings       = self._conn.execute("SELECT COUNT(*) FROM bookings WHERE detected_at >= ?", (today,)).fetchone()[0]
        payments       = self._conn.execute("SELECT COUNT(*) FROM payments WHERE sent_at >= ?", (today,)).fetchone()[0]
        return {
            "leads_fetched": leads_fetched,
            "leads_uploaded": leads_uploaded,
            "replies_total": replies_total,
            "interested": interested,
            "not_interested": not_interested,
            "ooo": ooo,
            "bookings": bookings,
            "payments_sent": payments,
        }

    def close(self):
        self._conn.close()
