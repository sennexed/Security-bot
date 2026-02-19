# Discord Invite Tracker + Security Bot

Production-ready Discord bot with advanced invite attribution, anti-raid controls, premium feature gating, and a FastAPI analytics API.

## Stack
- Python 3.12
- discord.py 2.x (slash commands only)
- PostgreSQL (asyncpg)
- Redis cache
- FastAPI
- Docker / Docker Compose

## Folder Structure
```text
discord-invite-security-bot/
├── api/
│   ├── __init__.py
│   └── app.py
├── bot/
│   ├── cogs/
│   │   ├── invites.py
│   │   ├── premium.py
│   │   └── security.py
│   ├── services/
│   │   ├── analytics.py
│   │   ├── invite_tracker.py
│   │   ├── premium.py
│   │   └── security.py
│   ├── utils/
│   │   ├── locks.py
│   │   └── premium.py
│   ├── cache.py
│   ├── config.py
│   ├── db.py
│   ├── logging.py
│   └── main.py
├── sql/
│   └── schema.sql
├── .dockerignore
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── run.py
```

## Core Features Implemented
- Invite tracking with snapshot-diff attribution and confidence scoring
- Invite create/delete handling and invite history persistence
- Per-inviter stats: total, real, fake, leaves, rejoins, bonus, net
- Leaderboard command
- Join burst detection via Redis sorted-set windows
- Young-account detection + optional auto-kick
- Link spam detection with auto-timeout
- Security incident logging table
- Lockdown mode:
  - Deletes active invites
  - Blocks new invite creation during lockdown
  - Applies slowmode to all text channels
  - Restores slowmode on unlock
  - Quarantine role assignment for new joins
- Premium system with license key activation
- Premium-gated features:
  - Advanced raid prediction
  - Cross-server blacklist checks
  - Invite fraud scoring
  - Security analytics REST endpoint
- FastAPI endpoints:
  - `GET /api/guild/{id}/overview`
  - `GET /api/guild/{id}/invites`
  - `GET /api/guild/{id}/security`
  - `GET /api/leaderboard`
  - `GET /api/incidents`

## Slash Commands
- `/invites`
- `/invites user:@member`
- `/leaderboard`
- `/security status`
- `/security lockdown`
- `/security unlock`
- `/security setlog`
- `/premium status`
- `/premium activate`

Additional premium utility command:
- `/raidprediction`

## Required Discord Permissions / Intents
Enable in the Developer Portal:
- `SERVER MEMBERS INTENT`
- `MESSAGE CONTENT INTENT`

Bot permissions recommended:
- Manage Guild
- Manage Channels
- Manage Roles
- Manage Messages
- Moderate Members
- Kick Members
- View Audit Log
- Create Instant Invite / Manage Guild Invites

## Local Setup (without Docker)
1. Copy env file:
```bash
cp .env.example .env
```
2. Set `DISCORD_TOKEN` and `DISCORD_APPLICATION_ID`.
3. Start Postgres and Redis.
4. Apply schema:
```bash
psql postgresql://postgres:postgres@localhost:5432/invitebot -f sql/schema.sql
```
5. Install deps:
```bash
pip install -r requirements.txt
```
6. Run:
```bash
python run.py
```

## Docker Setup
1. Copy env file and edit:
```bash
cp .env.example .env
```
2. Launch:
```bash
docker compose up --build
```

API runs on `http://localhost:8080`.

## Premium License Insert Example
Activation uses SHA-256 hash of the raw key.

Example raw key:
- `MY-ORG-PREMIUM-2026`

Generate hash:
```bash
python - <<'PY'
import hashlib
print(hashlib.sha256(b"MY-ORG-PREMIUM-2026").hexdigest())
PY
```

Insert license:
```sql
INSERT INTO premium_licenses (key_hash, plan_name, is_active, max_guilds, expires_at)
VALUES ('<sha256-hash-here>', 'premium', TRUE, 5, NOW() + INTERVAL '365 days');
```

Then activate in Discord:
- `/premium activate license_key:MY-ORG-PREMIUM-2026`

## Notes
- Invite attribution uses cached snapshots and guild-scoped async locks to reduce race risk under simultaneous joins.
- On restart, invite cache is rebuilt for all connected guilds.
- All core I/O is async and shard-ready via `AutoShardedBot`.
