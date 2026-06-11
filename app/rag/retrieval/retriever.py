# =============================================================
# app/rag/retrieval/retriever.py
# Facade del sistema di retrieval.
# Orchestrata: dense search + sparse BM25 → RRF fusion → MMR → reranker
# =============================================================

from __future__ import annotations  #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from dataclasses import dataclass  #messo sopra una classe, ti da automaticamente __init__, __repr__, __eq__, ect
from typing import Any
from loguru import logger
from app.core.settings import get_settings   #ur custom


settings = get_settings()

@dataclass
class RetrievedChunk:
    """Chunk recuperato con score e metadata."""
    text: str
    score: float
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    doc_type: str
    metadata: dict[str, Any]

def retrieve(
    query: str,
    tenant_slug: str,
    tenant_id: str,
    collection_id: str | None = None,
    top_k: int | None = None,
    filters: dict | None = None,
) -> list[RetrievedChunk]:
    """
    Pipeline di retrieval completa.
    Flusso:
    1. Embed query (dense vector)
    2. Dense search su Qdrant (semantic)
    3. Sparse BM25 search su Qdrant (keyword)
    4. RRF fusion dei due risultati
    5. MMR diversification
    6. Reranking cross-encoder (riduce da top_k a reranker_top_k)
    Args:
        query: domanda dell'utente
        tenant_slug: per collection name e filtro tenant
        tenant_id: per filtro isolamento multi-tenant
        collection_id: filtra per collection specifica (opzionale)
        top_k: override del top_k di config
        filters: filtri metadata aggiuntivi (doc_type, data, ecc.)

    Returns:
        Lista di RetrievedChunk ordinati per rilevanza
    """
    k = top_k or settings.retriever_top_k
    logger.debug(f"Retrieval: query='{query[:50]}...', top_k={k}")
    # 1. Embedding query
    from app.core.embeddings import embed_query  #ur custom
    query_vector = embed_query(query)
    from app.core.vectorstore import get_qdrant_client, get_collection_name
    from qdrant_client.http import models as qmodels
    client = get_qdrant_client()
    collection_name = get_collection_name(tenant_slug)
    must_conditions = [  #costruisci filtro qdrant
        qmodels.FieldCondition(
            key="tenant_id",
            match=qmodels.MatchValue(value=tenant_id)  #🔥🔥SEMPRE TENENT ISOLATION!!
        )
    ]
    if collection_id:
        must_conditions.append(
            qmodels.FieldCondition(
                key="collection_id",
                match=qmodels.MatchValue(value=collection_id)
            )
        )
    if filters:
        for key, value in filters.items():
            must_conditions.append(
                qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))
            )
    qdrant_filter = qmodels.Filter(must=must_conditions)
    #🔥🔥 Dense Search (semantic similarity)
    dense_results = client.search(
        collection_name=collection_name,
        query_vector=qmodels.NamedVector(name="dense", vector=query_vector),
        query_filter=qdrant_filter,
        limit=k,
        with_payload=True,
        score_threshold=0.3,
    )
    #🔥🔥 Sparse Search (BM25 keyword) se abilitato
    sparse_results = []
    if settings.qdrant_use_sparse:
        try:
            sparse_vector = _build_sparse_vector(query)
            sparse_results = client.search(
                collection_name=collection_name,
                query_vector=qmodels.NamedSparseVector(
                    name="sparse", vector=sparse_vector
                ),
                query_filter=qdrant_filter,
                limit=k,
                with_payload=True,
            )
        except Exception as e:
            logger.warning(f"Sparse search fallita: {e}")
    # 4. RRF fusion
    fused = _rrf_fusion(dense_results, sparse_results, k=k)
    # 5. MMR diversification
    if settings.retriever_strategy == "mmr" and len(fused) > 1:
        fused = _mmr_rerank(query_vector, fused, lambda_param=settings.retriever_mmr_lambda)

    # 6. Reranking cross-encoder
    if settings.reranker_enabled and len(fused) > 1:
        fused = _cross_encoder_rerank(query, fused, top_k=settings.reranker_top_k)

    # Converti in RetrievedChunk
    chunks = []
    for item in fused:
        payload = item["payload"]
        chunks.append(RetrievedChunk(
            text=payload.get("text", ""),
            score=item["score"],
            chunk_id=item["id"],
            document_id=payload.get("document_id", ""),
            filename=payload.get("filename", ""),
            page_number=payload.get("page_number"),
            chunk_index=payload.get("chunk_index", 0),
            doc_type=payload.get("doc_type", "generic"),
            metadata=payload,
        ))

    logger.debug(f"Retrieval completato: {len(chunks)} chunk")
    return chunks

def _rrf_fusion(  #🔥🔥RRF technique!! formula score=1/(rank+k)
    dense: list,
    sparse: list,
    k: int = 60,
) -> list[dict]:
    """
    Reciprocal Rank Fusion — combina risultati dense e sparse.
    RRF score = Σ 1/(k + rank_i) per ogni lista.
    k=60 è il valore standard dalla letteratura.
    """
    scores: dict[str, dict] = {}
    for rank, result in enumerate(dense):  #enumarate() iteri e ti da anche l'index 
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {"id": rid, "payload": result.payload, "score": 0.0}  #pk ricorda scores dict[str, dict], e lo inizializzi
        scores[rid]["score"] += 1.0 / (60 + rank + 1)   #accedi all campo e fai update 
    for rank, result in enumerate(sparse):
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {"id": rid, "payload": result.payload, "score": 0.0}
        scores[rid]["score"] += 1.0 / (60 + rank + 1)   #accedi all campo e fai update
    return sorted( scores.values(), key=lambda x: x["score"], reverse=True )    #

def _mmr_rerank(      #Re-RAnking technique, formual  λ*relevance-(1-λ)*similarity
    query_vector: list[float],
    results: list[dict],
    lambda_param: float = 0.5,
    top_k: int | None = None,
) -> list[dict]:
    """
    Maximal Marginal Relevance — diversifica i risultati.
    Bilancia rilevanza (similarity con query) e diversità (dissimilarity tra chunk).
    lambda_param: 0=massima diversità, 1=massima rilevanza
    """
    import numpy as np   #serve INSTALLARE LIB numpy !!
    if not results:
        return results
    k = top_k or len(results)
    selected = []
    remaining = list(results)
    #Vettori dei chunk (usiamo lo score come proxy della similarity)
    while len(selected) < k and remaining:
        if not selected:
            # Prima iterazione: prendi il più rilevante
            best = remaining[0]
        else:
            # MMR: massimizza λ*relevance - (1-λ)*max_similarity_to_selected
            best_score = float("-inf")
            best = remaining[0]
            for candidate in remaining:
                relevance = candidate["score"]
                # Similarità con i già selezionati (approssimazione tramite score overlap)
                max_sim = max(
                    _score_similarity(candidate, sel) for sel in selected
                )
                mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
                if mmr_score > best_score:
                    best_score = mmr_score
                    best = candidate
        selected.append(best)
        remaining.remove(best)
    return selected

def _score_similarity(a: dict, b: dict) -> float:
    """Similarità approssimata tra due chunk basata sul filename e chunk_index."""
    pa, pb = a["payload"], b["payload"]
    if pa.get("document_id") == pb.get("document_id"):
        # Stessa fonte — alta similarità se chunk adiacenti
        diff = abs(pa.get("chunk_index", 0) - pb.get("chunk_index", 0))
        return max(0, 1.0 - diff * 0.1)
    return 0.0

def _cross_encoder_rerank(
    query: str,
    results: list[dict],
    top_k: int,
) -> list[dict]:
    """
    Reranking con cross-encoder BAAI/bge-reranker-base.
    Più preciso del bi-encoder per la rilevanza finale.
    Riduce da initial_k (20) a top_k (5).
    """
    from app.core.embeddings import get_reranker_model
    reranker = get_reranker_model()
    if not reranker:
        return results[:top_k]
    pairs = [(query, r["payload"].get("text", "")) for r in results]
    scores = reranker.predict(pairs)
    for result, score in zip(results, scores):
        result["rerank_score"] = float(score)
    reranked = sorted(results, key=lambda x: x.get("rerank_score", 0), reverse=True)
    logger.debug(f"Reranking: {len(results)} → {top_k} chunk")
    return reranked[:top_k]

def _build_sparse_vector(query: str) -> Any:
    """Costruisce vettore sparso BM25 per la query."""
    from fastembed import SparseTextEmbedding
    # Usa SPLADE o BM25 per il vettore sparso
    model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")
    vectors = list(model.embed([query]))
    v = vectors[0]
    return {"indices": v.indices.tolist(), "values": v.values.tolist()}


