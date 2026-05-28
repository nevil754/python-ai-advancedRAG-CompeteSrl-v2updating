# Qdrant client singleton + gestione collection per tenant.
# Ogni tenant ha la sua collection separata in Qdrant.

from __future__ import annotations
from functools import lru_cache
from typing import Any
from loguru import logger
from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

@lru_cache(maxsize=1)    #decoratore che trasforma la funzione in un singleton, quindi get_qdrant_client() ritorna sempre la stessa istanza di QdrantClient, evitando overhead di connessioni multiple
def get_qdrant_client() -> QdrantClient:  
    """
    Ritorna il client Qdrant sincrono (singleton).
    Usato nei worker Celery e nei task di ingestion.
    """
    from app.core.settings import get_settings
    settings = get_settings()
    logger.info("Connessione Qdrant", url=settings.qdrant_url)
    kwargs: dict[str, Any] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)


@lru_cache(maxsize=1)
def get_async_qdrant_client() -> AsyncQdrantClient:
    """
    Ritorna il client Qdrant asincrono (singleton).
    Usato nelle route FastAPI per non bloccare l'event loop.
    """
    from app.core.settings import get_settings
    settings = get_settings()
    kwargs: dict[str, Any] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return AsyncQdrantClient(**kwargs)

def get_collection_name(tenant_slug: str) -> str:
    """
    Genera il nome della collection Qdrant per un tenant.
    Convenzione: tenant_{slug}_documents
    Args:
        tenant_slug: es. "acme-corp" → "tenant_acme_corp_documents"
    """
    safe_slug = tenant_slug.replace("-", "_").lower()
    return f"tenant_{safe_slug}_documents"

def get_memory_collection_name(tenant_slug: str) -> str:
    """Collection per la semantic memory (fatti utente estratti da Zep-like layer)."""
    safe_slug = tenant_slug.replace("-", "_").lower()
    return f"tenant_{safe_slug}_memory"

def ensure_collection(
    tenant_slug: str,
    force_recreate: bool = False,
) -> str:
    """
    Crea la collection Qdrant per un tenant se non esiste.
    Idempotente — chiamabile più volte senza effetti collaterali.
    Args:
        tenant_slug: slug del tenant
        force_recreate: se True, cancella e ricrea la collection
    Returns:
        Nome della collection creata/esistente
    """
    from app.core.settings import get_settings
    from app.core.embeddings import get_embedding_dimension
    settings = get_settings()
    client = get_qdrant_client()
    collection_name = get_collection_name(tenant_slug)

    try:
        existing = client.get_collection(collection_name)
        if not force_recreate:
            logger.debug(f"Collection già esistente: {collection_name}")
            return collection_name
        logger.warning(f"force_recreate=True — cancello collection {collection_name}")
        client.delete_collection(collection_name)
    except UnexpectedResponse:
        pass  #collection non esiste — la creiamo

    dimension = get_embedding_dimension()
    # Configurazione vettori
    vectors_config: dict[str, Any] = {
        # Vettori densi per semantic search
        "dense": qmodels.VectorParams(
            size=dimension,
            distance=qmodels.Distance[settings.qdrant_distance],
            on_disk=True,             # vettori su disco per risparmiare RAM
        )
    }
    # Vettori sparsi per BM25 hybrid search
    sparse_vectors_config = None
    if settings.qdrant_use_sparse:
        sparse_vectors_config = {
            "sparse": qmodels.SparseVectorParams(
                index=qmodels.SparseIndexParams(on_disk=True)
            )
        }
    client.create_collection(
        collection_name=collection_name,
        vectors_config=vectors_config,
        sparse_vectors_config=sparse_vectors_config,
        on_disk_payload=settings.qdrant_on_disk_payload,
        # ottimizza per ricerche frequenti
        optimizers_config=qmodels.OptimizersConfigDiff(
            indexing_threshold=20_000,
            memmap_threshold=50_000,
        ),
    )
    # Crea indice su tenant_id per filtri veloci
    client.create_payload_index(
        collection_name=collection_name,
        field_name="tenant_id",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="document_id",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="doc_type",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )
    logger.info(
        "Collection Qdrant creata",
        collection=collection_name,
        dimension=dimension,
        sparse=settings.qdrant_use_sparse,
    )
    return collection_name

async def aensure_collection(tenant_slug: str, force_recreate: bool = False) -> str:
    """Versione async di ensure_collection."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ensure_collection, tenant_slug, force_recreate)

async def adelete_tenant_collections(tenant_slug: str) -> None:
    """
    Cancella tutte le collection Qdrant di un tenant.
    Chiamato durante l'offboarding del tenant.
    """
    client = get_async_qdrant_client()
    for get_name in [get_collection_name, get_memory_collection_name]:
        name = get_name(tenant_slug)
        try:
            await client.delete_collection(name)
            logger.info(f"Collection cancellata: {name}")
        except Exception as e:
            logger.warning(f"Impossibile cancellare collection {name}: {e}")


