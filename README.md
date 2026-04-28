# Prediction Market Trading Bot

Automated trading bot for Polymarket + Kalshi.
Strategies: Cross-platform arbitrage, Edge hunting, Market making.

---

## Before you start — important context

**Kalshi** is CFTC-regulated, US-legal, uses RSA key auth, settles in USD.

**Polymarket** is crypto-native (Polygon/USDC). As of February 18, 2026, Polymarket
removed the 500ms taker delay and introduced dynamic fees. The winning strategy
is now **maker orders** (limit orders = zero fees + earn rebates), not taker arb.
This bot is built for the 2026 rules.

---

## Setup: Step by step

### 1. Install Python + dependencies

```bash
python3 --version   # need 3.10+
pip install -r requirements.txt
```

### 2. Create your keys directory

```bash
mkdir -p keys data logs
```

### 3. Get your Kalshi API key

1. Go to https://kalshi.com/account/profile
2. Scroll to the **API Keys** section
3. Click **Create New API Key**
4. A `.pem` file will download automatically — save it to `keys/kalshi_private.pem`
5. Copy the **Key ID** shown on screen

For demo testing first: create an account at https://demo.kalshi.co (separate from your live account).

### 4. Get your Polymarket credentials

**Private key** (two ways):

- *Email/Google account*: Log in → Cash → three-dot menu → Export Private Key
- *MetaMask*: MetaMask → Account Details → Export Private Key

**Funder address**:
- Go to https://polymarket.com/settings
- Copy the wallet address shown there
- ⚠️ This is NOT always your MetaMask address — always get it from Polymarket settings

**One-time setup** — approve exchange contracts (run once per wallet):
```python
# Run this script once to approve USDC spending before trading
from py_clob_client.client import ClobClient
client = ClobClient("https://clob.polymarket.com", key="0xYOUR_KEY", chain_id=137)
client.set_api_creds(client.create_or_derive_api_creds())
# Then make one small manual trade on polymarket.com to finalize allowances
```

### 5. Configure .env

```bash
cp .env.example .env
# Edit .env with your credentials
```

Key settings in `.env`:
```
KALSHI_DEMO_MODE=true          ← KEEP THIS TRUE until you've tested for 1 week
MAX_POSITION_USD=25            ← Start small
DAILY_LOSS_LIMIT_USD=100       ← Hard stop
BOT_MODE=all                   ← arb + edge + maker
```

### 6. Run in demo mode first

```bash
python main.py
```

You should see:
```
Kalshi connected | Balance: $X.XX | DEMO
Polymarket connected | Balance: $X.XX
Scan loop started | interval=5.0s | mode=all
```

Watch the logs. Let it run for at least 48 hours in demo before going live.

### 7. Go live

When ready:
1. Set `KALSHI_DEMO_MODE=false` in `.env`
2. Make sure your Kalshi live account has funds (ACH transfer from bank)
3. Make sure your Polymarket account has USDC (buy on Coinbase, bridge to Polygon)
4. Start small: keep `MAX_POSITION_USD=10` for your first week live

---

## File structure

```
predmarket_bot/
├── main.py              ← entry point
├── config.py            ← all settings
├── engine.py            ← orchestration loop
├── kalshi_client.py     ← Kalshi API (RSA auth, orders, WS)
├── polymarket_client.py ← Polymarket CLOB (maker-first, WS)
├── matcher.py           ← cross-platform market matching
├── strategies.py        ← arb, edge, maker logic
├── risk.py              ← position limits, daily loss stop
├── database.py          ← SQLite trade log
├── logger.py            ← rotating log files
├── requirements.txt
├── .env.example
├── .gitignore
├── keys/                ← your private keys (gitignored)
├── data/                ← SQLite DB (gitignored)
└── logs/                ← rotating log files (gitignored)
```

---

## Strategy details

### Arbitrage
Scans matched market pairs across both platforms. If YES on Kalshi + NO on Polymarket
costs less than $1.00 combined (guaranteed $1 payout), fires both legs simultaneously.
Minimum edge threshold: configurable via `ARB_MIN_EDGE_PCT` (default 2%).

**Risk**: Simultaneous fill is not guaranteed. If one leg misses, you have naked
directional exposure. The bot handles this: if the Kalshi leg fails, it will NOT
place the Polymarket leg.

### Edge hunting
Compares market prices to a fair-value model. Trades when deviation exceeds threshold.
The model in `strategies.py > EdgeStrategy._estimate_fair_value()` is currently a
placeholder — it returns None until you wire in a real signal source.

**To add real signals**: Edit `_estimate_fair_value()` to return estimated probabilities
from news APIs, polling averages, options implied vol, etc.

### Market making
Posts limit orders on both sides of active markets. Earns the bid-ask spread.
On Polymarket, maker orders earn USDC rebates (zero fees). On Kalshi, 0% fees as of 2026.

---

## Deploying 24/7 (VPS)

### Option A: Railway / Fly.io (easiest)
```bash
# Upload your bot (without .env and keys/)
# Set environment variables in Railway/Fly dashboard
# Deploy
```

### Option B: Linux VPS (cheapest, ~$5/mo on DigitalOcean/Hetzner)
```bash
# On your VPS:
git clone your-repo
pip install -r requirements.txt
cp .env.example .env && nano .env

# Run as a systemd service (auto-restarts on crash)
sudo nano /etc/systemd/system/predbot.service
```

```ini
[Unit]
Description=Prediction Market Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/predmarket_bot
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/predmarket_bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable predbot
sudo systemctl start predbot
sudo journalctl -u predbot -f   # watch logs
```

---

## Monitoring

View today's trades:
```bash
sqlite3 data/trades.db "SELECT ts, platform, ticker, side, price, size_usd, status FROM orders ORDER BY ts DESC LIMIT 20;"
```

View PnL by strategy:
```bash
sqlite3 data/trades.db "SELECT strategy, SUM(pnl_usd), COUNT(*) FROM pnl GROUP BY strategy;"
```

---

## FAQ

**Q: My Polymarket orders show $0 balance.**
A: Your funder address in `.env` is wrong. Get it from polymarket.com/settings, not MetaMask.

**Q: Kalshi auth errors.**
A: Check that your .pem file is at `keys/kalshi_private.pem` and the Key ID matches.

**Q: No arb signals firing.**
A: Real arb gaps between Poly and Kalshi are rare and small. The scanner is working if
it says "Found X matched market pairs" — it just means no gap above your threshold exists right now.

**Q: How do I know if it's actually making money?**
A: Check `data/trades.db` with the sqlite commands above. Or add Telegram alerts to `engine.py`.

**Q: The bot placed one leg of an arb but not the other.**
A: Check logs for "ARB: Kalshi leg failed" or "ARB: Poly leg failed" messages.
This is the safety mechanism working — it prevented a naked position.
