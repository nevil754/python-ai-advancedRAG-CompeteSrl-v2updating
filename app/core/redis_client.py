# app/core/redis_client.py
# TenantRedis: wrapper Redis con namespace isolation per tenant.
# Ogni chiave è prefissata con tenant:{id}: per isolamento completo.
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import json
from functools import lru_cache  #x singleton cache
from typing import Any  #x typing generico python
import redis.asyncio as aioredis   #x versione async di redis
from loguru import logger

@lru_cache(maxsize=1)   #decoratore che trasforma la funzione in un singleton, quindi get_qdrant_client() ritorna sempre la stessa istanza di QdrantClient, evitando overhead di connessioni multiple
def get_redis() -> aioredis.Redis:
    """
    Ritorna il client Redis asincrono (singleton).
    Connesso al DB 0 — broker Celery + sessioni + rate limiting.
    """
    from app.core.settings import get_settings
    settings = get_settings()

    logger.info("Connessione Redis", url=settings.redis_url)
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )


@lru_cache(maxsize=1)
def get_cache_redis() -> aioredis.Redis:
    """
    Client Redis per il DB 1 — cache RAG separata dal broker.
    Separare i DB permette di fare FLUSHDB sulla cache
    senza toccare le code Celery.
    """
    from app.core.settings import get_settings
    settings = get_settings()

    return aioredis.from_url(
        settings.redis_cache_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


class TenantRedis:
    """
    Wrapper Redis con namespace isolation per tenant.
    Tutte le chiavi sono prefissate con 'tenant:{tenant_id}:'.

    Uso:
        redis = TenantRedis(tenant_id="acme-uuid")
        await redis.set_session(session_id, messages)
        await redis.get_query_cache(query_hash)
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._redis = get_redis()
        self._cache = get_cache_redis()

    def _key(self, *parts: str) -> str:
        """Costruisce chiave prefissata con tenant_id."""
        return f"tenant:{self.tenant_id}:" + ":".join(parts)

    # ── Sessioni chat (short-term memory) ─────────────────────

    async def get_session(self, session_id: str) -> list[dict]:
        """
        Ritorna gli ultimi N messaggi della conversazione da Redis.
        Usato dal context_builder prima di ogni query RAG.
        """
        key = self._key("session", session_id)
        raw = await self._redis.lrange(key, 0, -1)
        return [json.loads(m) for m in raw]

    async def append_message(
        self,
        session_id: str,
        message: dict,
        max_turns: int = 10,
    ) -> None:
        """
        Aggiunge un messaggio alla sessione e mantiene solo gli ultimi max_turns*2.
        (max_turns*2 perché ogni turno = 1 user + 1 assistant)
        """
        from app.core.settings import get_settings
        settings = get_settings()

        key = self._key("session", session_id)
        ttl = settings.cache_session_ttl_seconds

        pipe = self._redis.pipeline()
        pipe.rpush(key, json.dumps(message, ensure_ascii=False))
        pipe.ltrim(key, -(max_turns * 2), -1)
        pipe.expire(key, ttl)
        await pipe.execute()

    async def clear_session(self, session_id: str) -> None:
        """Cancella la sessione — chiamato quando l'utente chiude la chat."""
        await self._redis.delete(self._key("session", session_id))

    # ── Cache query RAG ───────────────────────────────────────

    async def get_query_cache(self, query_hash: str) -> str | None:
        """
        Cerca risposta cached per questa query.
        query_hash: hash MD5/SHA del testo della query normalizzato.
        """
        return await self._cache.get(self._key("cache", "query", query_hash))

    async def set_query_cache(
        self,
        query_hash: str,
        response: str,
        ttl: int | None = None,
    ) -> None:
        """Salva risposta RAG in cache con TTL configurabile."""
        from app.core.settings import get_settings
        settings = get_settings()

        key = self._key("cache", "query", query_hash)
        await self._cache.setex(key, ttl or settings.cache_query_ttl_seconds, response)

    async def invalidate_query_cache(self) -> int:
        """
        Invalida tutta la cache query di questo tenant.
        Chiamato dopo ogni nuova ingestion — i nuovi doc cambiano le risposte.
        """
        pattern = self._key("cache", "query", "*")
        keys = await self._cache.keys(pattern)
        if keys:
            await self._cache.delete(*keys)
        return len(keys)

    # ── Rate limiting ─────────────────────────────────────────

    async def check_rate_limit(
        self,
        user_id: str,
        limit: int | None = None,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """
        Verifica e incrementa il rate limit per un utente.

        Returns:
            Tuple (allowed, current_count)
            allowed: True se sotto il limite, False se superato
        """
        from app.core.settings import get_settings
        settings = get_settings()

        max_requests = limit or settings.rate_limit_requests_per_minute
        key = self._key("ratelimit", user_id)

        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        count = results[0]

        return count <= max_requests, count

    # ── Job status (per polling frontend) ────────────────────

    async def set_job_status(
        self,
        job_id: str,
        status: dict,
        ttl: int = 86400,
    ) -> None:
        """Salva status di un job di ingestion — polling dal frontend."""
        key = self._key("job", job_id)
        await self._redis.setex(key, ttl, json.dumps(status))

    async def get_job_status(self, job_id: str) -> dict | None:
        """Legge status job — ritorna None se scaduto o inesistente."""
        raw = await self._redis.get(self._key("job", job_id))
        return json.loads(raw) if raw else None

    # ── Pulizia tenant ────────────────────────────────────────

    async def flush_tenant(self) -> int:
        """
        Cancella TUTTE le chiavi di questo tenant da Redis.
        Chiamato durante l'offboarding.
        ATTENZIONE: usa SCAN non KEYS per non bloccare Redis in prod.
        """
        pattern = f"tenant:{self.tenant_id}:*"
        deleted = 0
        cursor = 0

        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor, match=pattern, count=100
            )
            if keys:
                await self._redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break

        # Stessa cosa sul DB cache
        cursor = 0
        while True:
            cursor, keys = await self._cache.scan(
                cursor=cursor, match=pattern, count=100
            )
            if keys:
                await self._cache.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break

        logger.info(f"Flush tenant Redis completato", tenant=self.tenant_id, deleted=deleted)
        return deleted

    # ── Health check ──────────────────────────────────────────

    @staticmethod
    async def ping() -> bool:
        """Verifica che Redis sia raggiungibile. Usato in /health endpoint."""
        try:
            client = get_redis()
            return await client.ping()
        except Exception as e:
            logger.error(f"Redis ping fallito: {e}")
            return False


