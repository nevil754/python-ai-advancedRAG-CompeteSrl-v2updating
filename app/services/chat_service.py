# =============================================================
# app/services/chat_service.py
# Orchestrazione completa di una query RAG.
# Coordina: cache → retrieval → generation → memory → DB.
# =============================================================

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import hashlib   #x creare le hash x le queries
import json   #x fare json.dumps() converts python obj in corrisponding json formatted string
import time
from typing import AsyncGenerator, Any  
from uuid import uuid4
from loguru import logger   #x logging strutturato
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession  #x session db asyncrona
from app.core.redis_client import TenantRedis
from app.core.settings import get_settings
from app.rag.retrieval.retriever import retrieve
from app.rag.generation.chain import arun_rag_chain, astream_rag_chain
from app.rag.memory.context_builder import format_sources_for_response


settings = get_settings()

class ChatService:
    """
    Servizio che gestisce il ciclo completo di una query RAG.
    Flusso completo:
    1. Check cache Redis (risposta già calcolata?)
    2. Carica sessione chat da Redis (short-term memory)
    3. Retrieval: dense + sparse -> RRF -> MMR -> reranker
    4. Generation: prompt -> LLM -> risposta
    5. Salva messaggio in SQL Server
    6. Aggiorna sessione Redis
    7. Salva in cache Redis
    8. Incrementa usage stats
    """

    def __init__(
        self,
        db: AsyncSession,
        redis: TenantRedis,
        tenant_id: str,
        tenant_slug: str,
        user_id: str,
    ):
        self.db = db
        self.redis = redis
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.user_id = user_id

    async def query(
        self,
        question: str,
        conversation_id: str | None = None,
        collection_id: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """
        Esegue una query RAG completa (non streaming).

        Returns:
            dict con answer, conversation_id, message_id, sources, ecc.
        """
        # 1. Genera o usa conversation_id esistente
        conv_id = conversation_id or str(uuid4())

        # 2. Check cache
        query_hash = _hash_query(question, conv_id)
        cached = await self.redis.get_query_cache(query_hash)
        if cached:
            logger.debug("Cache hit per query RAG")
            return json.loads(cached)

        # 3. Carica sessione (short-term memory)
        session_messages = await self.redis.get_session(conv_id)

        # 4. Retrieval
        chunks = retrieve(
            query=question,
            tenant_slug=self.tenant_slug,
            tenant_id=self.tenant_id,
            collection_id=collection_id,
        )

        # 5. Generation
        result = await arun_rag_chain(
            question=question,
            chunks=chunks,
            session_messages=session_messages,
        )

        # 6. Salva messaggi in SQL Server
        message_id = await self._save_messages(
            conv_id=conv_id,
            question=question,
            answer=result["answer"],
            sources=result["sources"],
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            latency_ms=result.get("latency_ms", 0),
        )

        # 7. Aggiorna sessione Redis
        await self.redis.append_message(conv_id, {
            "role": "user", "content": question
        }, settings.memory_short_term_turns)
        await self.redis.append_message(conv_id, {
            "role": "assistant", "content": result["answer"]
        }, settings.memory_short_term_turns)

        # 8. Cache risposta
        response = {
            "answer": result["answer"],
            "conversation_id": conv_id,
            "message_id": message_id,
            "sources": result["sources"],
            "tokens_in": result.get("tokens_in"),
            "tokens_out": result.get("tokens_out"),
            "latency_ms": result.get("latency_ms"),
        }
        await self.redis.set_query_cache(query_hash, json.dumps(response))

        # 9. Incrementa stats Redis per usage rollup notturno
        await self._increment_usage_stats(
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
        )

        return response

    async def stream_query(
        self,
        question: str,
        conversation_id: str | None = None,
        collection_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Esegue una query RAG in streaming — genera token per token.
        Usato dalla route SSE /chat/stream.
        """
        conv_id = conversation_id or str(uuid4())
        session_messages = await self.redis.get_session(conv_id)

        chunks = retrieve(
            query=question,
            tenant_slug=self.tenant_slug,
            tenant_id=self.tenant_id,
            collection_id=collection_id,
        )

        full_answer = ""
        async for token in astream_rag_chain(
            question=question,
            chunks=chunks,
            session_messages=session_messages,
        ):
            full_answer += token
            yield token

        # Dopo lo streaming, salva in DB e Redis
        await self._save_messages(
            conv_id=conv_id,
            question=question,
            answer=full_answer,
            sources=format_sources_for_response(chunks),
        )
        await self.redis.append_message(conv_id, {"role": "user", "content": question})
        await self.redis.append_message(conv_id, {"role": "assistant", "content": full_answer})

    async def _save_messages(
        self,
        conv_id: str,
        question: str,
        answer: str,
        sources: list[dict],
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
    ) -> int:
        """Salva domanda + risposta in SQL Server. Ritorna message_id della risposta."""
        from app.core.settings import get_settings
        settings = get_settings()

        # Crea conversazione se non esiste
        await self.db.execute(
            text("""
                IF NOT EXISTS (SELECT 1 FROM conversations WHERE id = :id)
                INSERT INTO conversations (id, user_id, mode)
                VALUES (:id, :user_id, 'rag')
            """),
            {"id": conv_id, "user_id": self.user_id}
        )

        # Salva messaggio utente
        await self.db.execute(
            text("""
                INSERT INTO messages (conversation_id, role, content)
                VALUES (:conv_id, 'user', :content)
            """),
            {"conv_id": conv_id, "content": question}
        )

        # Salva risposta assistant
        result = await self.db.execute(
            text("""
                INSERT INTO messages
                    (conversation_id, role, content, sources,
                     tokens_in, tokens_out, latency_ms)
                OUTPUT INSERTED.id
                VALUES (:conv_id, 'assistant', :content, :sources,
                        :tokens_in, :tokens_out, :latency_ms)
            """),
            {
                "conv_id": conv_id,
                "content": answer,
                "sources": json.dumps(sources),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_ms": latency_ms,
            }
        )
        row = result.fetchone()
        return row[0] if row else 0

    async def _increment_usage_stats(self, tokens_in: int, tokens_out: int) -> None:
        """Incrementa contatori Redis per il rollup notturno."""
        from datetime import date
        today = date.today().isoformat()
        base = f"tenant:{self.tenant_id}:stats:{today}"

        pipe = self.redis._redis.pipeline()
        pipe.incrby(f"{base}:tokens_in", tokens_in)
        pipe.incrby(f"{base}:tokens_out", tokens_out)
        pipe.incr(f"{base}:queries")
        pipe.expire(f"{base}:tokens_in", 172800)   # 48h TTL
        pipe.expire(f"{base}:tokens_out", 172800)
        pipe.expire(f"{base}:queries", 172800)
        await pipe.execute()


def _hash_query(question: str, conv_id: str) -> str:
    """Hash deterministica per la cache query."""
    normalized = question.strip().lower()
    return hashlib.md5(f"{conv_id}:{normalized}".encode()).hexdigest()
