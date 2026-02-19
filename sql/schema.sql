CREATE TABLE IF NOT EXISTS guilds (
    guild_id BIGINT PRIMARY KEY,
    guild_name TEXT NOT NULL,
    security_log_channel_id BIGINT,
    lockdown_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    join_burst_count INT NOT NULL DEFAULT 7,
    join_burst_window_seconds INT NOT NULL DEFAULT 10,
    min_account_age_hours INT NOT NULL DEFAULT 72,
    auto_kick_young_accounts BOOLEAN NOT NULL DEFAULT FALSE,
    link_spam_threshold INT NOT NULL DEFAULT 3,
    link_spam_window_seconds INT NOT NULL DEFAULT 30,
    lockdown_slowmode_seconds INT NOT NULL DEFAULT 15,
    quarantine_role_name TEXT NOT NULL DEFAULT 'Quarantine',
    is_premium BOOLEAN NOT NULL DEFAULT FALSE,
    premium_license_id BIGINT,
    premium_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT NOT NULL,
    discriminator TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invites (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    invite_code TEXT NOT NULL,
    inviter_id BIGINT,
    uses INT NOT NULL DEFAULT 0,
    max_uses INT,
    is_temporary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (guild_id, invite_code)
);

CREATE TABLE IF NOT EXISTS invite_joins (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    member_id BIGINT NOT NULL,
    invite_code TEXT,
    inviter_id BIGINT,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attribution_confidence NUMERIC(4,3) NOT NULL DEFAULT 0.200,
    attribution_reason TEXT NOT NULL DEFAULT 'unknown',
    is_fake BOOLEAN NOT NULL DEFAULT FALSE,
    is_rejoin BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS invite_leaves (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    member_id BIGINT NOT NULL,
    inviter_id BIGINT,
    left_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bonus_invites (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    amount INT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS incidents (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    incident_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    actor_id BIGINT,
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS premium_licenses (
    id BIGSERIAL PRIMARY KEY,
    key_hash TEXT NOT NULL UNIQUE,
    plan_name TEXT NOT NULL DEFAULT 'premium',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    max_guilds INT NOT NULL DEFAULT 1,
    activated_guild_ids BIGINT[] NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fraud_flags (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    member_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    score NUMERIC(5,4) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_invite_stats (
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    total_invites INT NOT NULL DEFAULT 0,
    real_invites INT NOT NULL DEFAULT 0,
    fake_invites INT NOT NULL DEFAULT 0,
    leaves INT NOT NULL DEFAULT 0,
    rejoins INT NOT NULL DEFAULT 0,
    bonus_invites INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id)
);

ALTER TABLE guilds
    ADD CONSTRAINT guilds_premium_license_fk
    FOREIGN KEY (premium_license_id) REFERENCES premium_licenses(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_invite_joins_guild_joined_at ON invite_joins(guild_id, joined_at DESC);
CREATE INDEX IF NOT EXISTS idx_invite_joins_inviter ON invite_joins(guild_id, inviter_id);
CREATE INDEX IF NOT EXISTS idx_invite_leaves_guild_left_at ON invite_leaves(guild_id, left_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_guild_created ON incidents(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_flags_guild_created ON fraud_flags(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_flags_member ON fraud_flags(member_id);
CREATE INDEX IF NOT EXISTS idx_invites_guild_uses ON invites(guild_id, uses DESC);
