from __future__ import annotations

from fastapi import FastAPI, HTTPException

from bot.services.analytics import AnalyticsService
from bot.services.security import SecurityService
from bot.utils.premium import PremiumRequiredError



def create_api(analytics: AnalyticsService, security: SecurityService) -> FastAPI:
    app = FastAPI(title="Discord Invite Security Bot API", version="1.0.0")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/guild/{guild_id}/overview")
    async def guild_overview(guild_id: int) -> dict:
        data = await analytics.guild_overview(guild_id)
        if not data:
            raise HTTPException(status_code=404, detail="Guild not found")
        return data

    @app.get("/api/guild/{guild_id}/invites")
    async def guild_invites(guild_id: int) -> list[dict]:
        return await analytics.guild_invites(guild_id)

    @app.get("/api/guild/{guild_id}/security")
    async def guild_security(guild_id: int) -> dict:
        return await analytics.guild_security(guild_id)

    @app.get("/api/leaderboard")
    async def leaderboard(limit: int = 25) -> list[dict]:
        bounded = max(1, min(limit, 100))
        return await analytics.leaderboard(limit=bounded)

    @app.get("/api/incidents")
    async def incidents(limit: int = 100) -> list[dict]:
        bounded = max(1, min(limit, 500))
        return await analytics.incidents(limit=bounded)

    @app.get("/api/guild/{guild_id}/security/analytics")
    async def security_analytics(guild_id: int) -> dict:
        try:
            return await analytics.security_analytics(guild_id)
        except PremiumRequiredError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/api/guild/{guild_id}/fraud-scores")
    async def fraud_scores(guild_id: int) -> list[dict]:
        try:
            rows = await security.invite_fraud_scoring(guild_id)
        except PremiumRequiredError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return [dict(r) for r in rows]

    return app
