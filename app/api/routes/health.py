# =============================================================
# app/api/routes/health.py
# Endpoint di health check per Docker e load balancer.
# /health  — app viva (liveness probe)
# /ready   — tutti i servizi pronti (readiness probe)
# =============================================================

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from loguru import logger

from app.core.settings import get_settings

router = APIRouter(tags=["health"])
settings = get_settings()

_start_time = time.time()


@router.get("/health")
async def health() -> dict[str, Any]:
    """
    Liveness probe — l'app è viva?
    Docker usa questo per decidere se riavviare il container.
    Risponde sempre 200 se il processo è in piedi.
    """
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_environment,
        "uptime_seconds": round(time.time() - _start_time),
    }


@router.get("/ready")
async def ready() -> dict[str, Any]:
    """
    Readiness probe — tutti i servizi sono raggiungibili?
    Usato da Docker depends_on e da load balancer.
    Ritorna 200 solo se Redis, SQL Server e Qdrant rispondono.
    Ritorna 503 se anche uno solo è down.
    """
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse

    checks: dict[str, Any] = {}
    all_ok = True

    # ── Redis ────────────────────────────────────────────────
    try:
        from app.core.redis_client import TenantRedis
        redis_ok = await TenantRedis.ping()
        checks["redis"] = "ok" if redis_ok else "error"
        if not redis_ok:
            all_ok = False
    except Exception as e:
        checks["redis"] = f"error: {e}"
        all_ok = False

    # ── SQL Server ───────────────────────────────────────────
    try:
        from app.db.sqlserver import TenantDB
        sql_ok = await TenantDB.ping()
        checks["sqlserver"] = "ok" if sql_ok else "error"
        if not sql_ok:
            all_ok = False
    except Exception as e:
        checks["sqlserver"] = f"error: {e}"
        all_ok = False

    # ── Qdrant ───────────────────────────────────────────────
    try:
        from app.core.vectorstore import get_async_qdrant_client
        client = get_async_qdrant_client()
        info = await client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as e:
        checks["qdrant"] = f"error: {e}"
        all_ok = False

    result = {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
        "uptime_seconds": round(time.time() - _start_time),
    }

    if not all_ok:
        logger.warning("Readiness check fallito", checks=checks)
        return JSONResponse(status_code=503, content=result)

    return result
