"""
Trade database — SQLite logging.
Records every signal, order, fill, and PnL event.
"""

import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("bot.db")


class TradeDB:
    def __init__(self, db_path: str = "data/trades.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()
        log.info(f"Trade DB initialized: {db_path}")

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                strategy TEXT,
                description TEXT,
                edge_pct REAL,
                confidence REAL,
                kalshi_ticker TEXT,
                poly_token_id TEXT,
                fired INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                platform TEXT NOT NULL,
                order_id TEXT,
                ticker_or_token TEXT,
                side TEXT,
                action TEXT,
                price REAL,
                size_usd REAL,
                count INTEGER,
                status TEXT,
                strategy TEXT,
                signal_id INTEGER,
                FOREIGN KEY (signal_id) REFERENCES signals(id)
            );

            CREATE TABLE IF NOT EXISTS pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                position_id TEXT,
                platform TEXT,
                pnl_usd REAL,
                strategy TEXT,
                entry_price REAL,
                exit_price REAL,
                holding_sec REAL
            );

            CREATE TABLE IF NOT EXISTS daily_summary (
                date TEXT PRIMARY KEY,
                total_trades INTEGER DEFAULT 0,
                arb_trades INTEGER DEFAULT 0,
                edge_trades INTEGER DEFAULT 0,
                maker_trades INTEGER DEFAULT 0,
                gross_pnl REAL DEFAULT 0,
                net_pnl REAL DEFAULT 0
            );
        """)
        self.conn.commit()

    def log_signal(self, signal, fired: bool = False) -> int:
        cur = self.conn.execute(
            """INSERT INTO signals
               (ts, strategy, description, edge_pct, confidence, kalshi_ticker, poly_token_id, fired)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                time.time(),
                signal.strategy,
                signal.description,
                signal.expected_edge_pct,
                signal.confidence,
                signal.kalshi_ticker or "",
                signal.poly_token_id or "",
                1 if fired else 0,
            )
        )
        self.conn.commit()
        return cur.lastrowid

    def log_order(
        self,
        platform: str,
        order_id: str,
        ticker_or_token: str,
        side: str,
        action: str,
        price: float,
        size_usd: float,
        count: int,
        status: str,
        strategy: str,
        signal_id: int = None,
    ):
        self.conn.execute(
            """INSERT INTO orders
               (ts, platform, order_id, ticker_or_token, side, action, price, size_usd, count, status, strategy, signal_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), platform, order_id, ticker_or_token, side, action,
             price, size_usd, count, status, strategy, signal_id)
        )
        self.conn.commit()

    def log_pnl(
        self,
        position_id: str,
        platform: str,
        pnl_usd: float,
        strategy: str,
        entry_price: float,
        exit_price: float,
        holding_sec: float,
    ):
        self.conn.execute(
            """INSERT INTO pnl
               (ts, position_id, platform, pnl_usd, strategy, entry_price, exit_price, holding_sec)
               VALUES (?,?,?,?,?,?,?,?)""",
            (time.time(), position_id, platform, pnl_usd, strategy,
             entry_price, exit_price, holding_sec)
        )
        self.conn.commit()

    def get_daily_pnl(self) -> float:
        today = time.strftime("%Y-%m-%d")
        cur = self.conn.execute(
            "SELECT SUM(pnl_usd) FROM pnl WHERE date(ts, 'unixepoch') = ?", (today,)
        )
        result = cur.fetchone()[0]
        return result or 0.0

    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        cur = self.conn.execute(
            """SELECT ts, platform, ticker_or_token, side, price, size_usd, status, strategy
               FROM orders ORDER BY ts DESC LIMIT ?""",
            (limit,)
        )
        cols = ["ts", "platform", "ticker", "side", "price", "size_usd", "status", "strategy"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_strategy_pnl(self) -> dict:
        cur = self.conn.execute(
            "SELECT strategy, SUM(pnl_usd), COUNT(*) FROM pnl GROUP BY strategy"
        )
        return {row[0]: {"pnl": round(row[1], 2), "trades": row[2]} for row in cur.fetchall()}

    def close(self):
        self.conn.close()
