from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    discord_token: str
    application_id: int
    postgres_dsn: str
    redis_url: str
    log_level: str
    default_join_burst_count: int
    default_join_burst_window_seconds: int
    default_min_account_age_hours: int
    default_auto_kick_young_accounts: bool
    default_link_spam_threshold: int
    default_link_spam_window_seconds: int
    default_lockdown_slowmode_seconds: int
    default_quarantine_role_name: str
    api_host: str
    api_port: int
    security_timeout_minutes: int



def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}



def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    app_id = os.getenv("DISCORD_APPLICATION_ID", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required")
    if not app_id.isdigit():
        raise RuntimeError("DISCORD_APPLICATION_ID must be set to an integer")

    postgres_dsn = os.getenv("POSTGRES_DSN", "").strip()
    if not postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is required")

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        raise RuntimeError("REDIS_URL is required")

    return Settings(
        discord_token=token,
        application_id=int(app_id),
        postgres_dsn=postgres_dsn,
        redis_url=redis_url,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        default_join_burst_count=int(os.getenv("DEFAULT_JOIN_BURST_COUNT", "7")),
        default_join_burst_window_seconds=int(os.getenv("DEFAULT_JOIN_BURST_WINDOW_SECONDS", "10")),
        default_min_account_age_hours=int(os.getenv("DEFAULT_MIN_ACCOUNT_AGE_HOURS", "72")),
        default_auto_kick_young_accounts=_as_bool(os.getenv("DEFAULT_AUTO_KICK_YOUNG_ACCOUNTS"), False),
        default_link_spam_threshold=int(os.getenv("DEFAULT_LINK_SPAM_THRESHOLD", "3")),
        default_link_spam_window_seconds=int(os.getenv("DEFAULT_LINK_SPAM_WINDOW_SECONDS", "30")),
        default_lockdown_slowmode_seconds=int(os.getenv("DEFAULT_LOCKDOWN_SLOWMODE_SECONDS", "15")),
        default_quarantine_role_name=os.getenv("DEFAULT_QUARANTINE_ROLE_NAME", "Quarantine"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8080")),
        security_timeout_minutes=int(os.getenv("SECURITY_TIMEOUT_MINUTES", "30")),
    )
