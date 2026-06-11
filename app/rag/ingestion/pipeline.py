# =============================================================
# app/rag/ingestion/pipeline.py
# Orchestra la pipeline completa: parse→clean→chunk→embed→upsert.
# Chiamato dal task Celery ingest_document.
# =============================================================

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from app.rag.ingestion.parser import parse_document
from app.rag.ingestion.cleaner import clean_text
from app.rag.ingestion.chunker import chunk_document
from app.rag.ingestion.metadata import build_chunk_metadata
from app.core.embeddings import embed_texts
from app.core.vectorstore import get_qdrant_client, get_collection_name, ensure_collection
from app.core.settings import get_settings

settings = get_settings()


def run_ingestion_pipeline(
    tenant_id: str,
    tenant_slug: str,
    document_id: str,
    file_path: str,
    collection_id: str | None = None,
) -> dict[str, Any]:
    """
    Pipeline completa di ingestion.
    Flusso:
    1. Parse → ParsedDocument (testo + pagine + tabelle)
    2. Clean → testo pulito
    3. Chunk → lista di Chunk
    4. Embed → vettori float per ogni chunk
    5. Upsert → inserimento in Qdrant con payload metadata
    Returns:
        dict con chunk_count, page_count, collection_name
    """
    path = Path(file_path)
    filename = path.name
    file_type = path.suffix

    logger.info(
        "Pipeline ingestion avviata",
        file=filename,
        tenant=tenant_slug,
        document_id=document_id,
    )

    # 1. Parse
    parsed = parse_document(file_path)
    logger.debug(f"Parsing: {parsed.page_count} pagine, {len(parsed.text)} chars")

    # 2. Clean
    clean = clean_text(parsed.text)
    logger.debug(f"Pulizia: {len(parsed.text)} → {len(clean)} chars")

    # 3. Chunk
    base_metadata = {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "filename": filename,
    }
    chunks = chunk_document(clean, pages=parsed.pages, base_metadata=base_metadata)
    logger.debug(f"Chunking: {len(chunks)} chunk")

    if not chunks:
        raise ValueError(f"Nessun chunk estratto dal documento {filename}")

    # 4. Embed — batch per efficienza
    texts = [c.text for c in chunks]
    vectors = embed_texts(texts)
    logger.debug(f"Embedding: {len(vectors)} vettori generati")

    # 5. Upsert in Qdrant
    collection_name = ensure_collection(tenant_slug)
    client = get_qdrant_client()

    from qdrant_client.http import models as qmodels

    points = []
    for chunk, vector in zip(chunks, vectors):
        payload = build_chunk_metadata(
            tenant_id=tenant_id,
            collection_id=collection_id or "",
            document_id=document_id,
            filename=filename,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            file_type=file_type,
            document_text_sample=clean[:500],
        )
        # Aggiunge il testo del chunk nel payload per le citazioni
        payload["text"] = chunk.text

        points.append(qmodels.PointStruct(
            id=str(uuid.uuid4()),
            vector={"dense": vector},
            payload=payload,
        ))

    # Inserimento a batch da 100 per non sovraccaricare Qdrant
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)
        logger.debug(f"Upserted batch {i // batch_size + 1}: {len(batch)} punti")

    logger.info(
        "Pipeline ingestion completata",
        file=filename,
        chunks=len(chunks),
        collection=collection_name,
    )

    return {
        "chunk_count": len(chunks),
        "page_count": parsed.page_count,
        "collection_name": collection_name,
    }
