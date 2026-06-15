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
    from app.core.embeddings import embed_query  #ur custom
    query_vector = embed_query(query)
    from app.core.vectorstore import get_qdrant_client, get_collection_name
    from qdrant_client.http import models as qmodels
    client = get_qdrant_client()
    collection_name = get_collection_name(tenant_slug)
    must_conditions = [  #costruisci filtro qdrant
        qmodels.FieldCondition(   #FieldCondition è di qdrant
            key="tenant_id",
            match=qmodels.MatchValue( value=tenant_id )  #🔥🔥SEMPRE TENENT ISOLATION!!
        )
    ]
    if collection_id:
        must_conditions.append(   #ne aggiungi un'altro a must_conditions
            qmodels.FieldCondition(
                key="collection_id",
                match=qmodels.MatchValue(value=collection_id)
            )
        )
    if filters:
        for key, value in filters.items():
            must_conditions.append(
                qmodels.FieldCondition(
                    key=key, 
                    match=qmodels.MatchValue(value=value)
                )
            )
    qdrant_filter = qmodels.Filter( must=must_conditions )   #define il filtro finale da passare a qdrant search
    #🔥🔥Dense Search (semantic similarity)
    dense_results = client.search(
        collection_name=collection_name,
        query_vector=qmodels.NamedVector( name="dense", vector=query_vector ),  #NamedVector è di qdrant, serve per specificare quale campo vettoriale usare per la ricerca, in questo caso "dense" che è quello che usiamo per i chunk embedding.
        query_filter=qdrant_filter,   #apply the filter
        limit=k,   #prende top k results
        with_payload=True,  
        score_threshold=0.3,   #scarta risultati con score < 0.3 (puoi regolare questo valore in base alla qualità dei risultati, ma 0.3 è un buon punto di partenza per cosine similarity)
    )
    #🔥🔥Sparse Search (BM25 keyword) se abilitato
    sparse_results = []
    if settings.qdrant_use_sparse:
        try:
            sparse_vector = _build_sparse_vector(query)
            sparse_results = client.search(  #esegui ricerca!
                collection_name=collection_name,
                query_vector=qmodels.NamedSparseVector( name="sparse", vector=sparse_vector ),
                query_filter=qdrant_filter,
                limit=k,
                with_payload=True,
            )
        except Exception as e:
            logger.warning(f"Sparse search fallita: {e}")

    #ora che hai entrambi i results, applichi RRF!! i risulati forti in entrambi i ranking salgono mentre quelli deboli scendono!
    fused = _rrf_fusion( dense_results, sparse_results, k=k )  #una volta che hai dense e sparse results, non ti rimane che fonderli con fusion 🔥🔥RRF (Reciprocal Rank Fusion) technique!! formula score=1/(rank+k)

    if settings.retriever_strategy == "mmr" and len(fused) > 1:   #MMR technique!!
        fused = _mmr_rerank( query_vector, fused, lambda_param=settings.retriever_mmr_lambda )  #applichi il Re-Ranking (MRR) technique !!
    if settings.reranker_enabled and len(fused) > 1:    #🔥🔥ReRanking technique w Cross-Encoder(BEST!)!!
        fused = _cross_encoder_rerank(query, fused, top_k=settings.reranker_top_k)

    #principalmente faccio questo 
    #1. Hybrid Search (dense + sparse BM25) → Top 20 risultati
    #2. RRF (Reciprocal Rank Fusion) → in input 2 ranking separati (1 di dense e 1 di sparse) i risulati forti in entrambi i ranking salgono (mentre quelli deboli scendono) come output 1 ranking unico.
    #2. MMR (Maximal Marginal Relevance) → Top 10 diversificati. penalizza i chunk troppo simili tra loro, in questo modo hai solo risultati diversi (no clones) i piu importanti.
    #3. ReRanker (Cross-Encoder technique w model BAAI/bge-reranker-base) → Top 5 precisi. prende in input i risultati e con model BAAI/bge-reranker-base assegna un ranking a ciascuno, quindi poi return solo i X bests.


    # Converti in RetrievedChunk
    chunks = []
    for item in fused:
        payload = item["payload"]
        chunks.append( RetrievedChunk(
            text= payload.get("text", ""),
            score= item["score"],
            chunk_id= item["id"],
            document_id= payload.get("document_id", ""),
            filename= payload.get("filename", ""),
            page_number= payload.get("page_number"),
            chunk_index= payload.get("chunk_index", 0),
            doc_type= payload.get("doc_type", "generic"),
            metadata= payload,
        ))
    logger.debug(f"Retrieval completato: {len(chunks)} chunk")
    return chunks


def _build_sparse_vector(query: str) -> Any:  #🔥utilizzo Sparse Search w SPLADE type (better than BM25 type base)
    """Costruisce vettore sparso SPLADE per la query."""
    from fastembed import SparseTextEmbedding  #fastembed supporta BM25, SPLADE e altri modelli di spare retrieval
    model = SparseTextEmbedding( model_name="prithivida/Splade_PP_en_v1" )  #STO UTILIZZANDO SPLADE type!! non BM25 type (che non è neurale)!
    vectors = list( model.embed([query]) )
    v = vectors[0]  #[0] hai passato 1 sola query, quindi è l'unica, prendi la query convertita in sparse vector.
    return {"indices": v.indices.tolist(), "values": v.values.tolist()}   #.indices() NON sono le parole ma sono posizioni nel vocabolario del modello! .values() sono i pesi associati a quelle parole. quindi stai costruendo un vettore sparso in formato {indices: [...], values: [...]}, che è quello che qdrant si aspetta per la ricerca sparse.

def _rrf_fusion(  #🔥🔥RRF fusion technique!! formula score=1/(rank+k). k=60 stabilizza la curva, rank è la posizione nel risultato.
    dense: list,  #risultati semantic search Qdrant
    sparse: list,  #risultati keyword search
    k: int = 60,  #k=60 stabilizza la curva
) -> list[dict]:
    """
    Reciprocal Rank Fusion — combina risultati dense e sparse.
    RRF score = Σ 1/(k + rank_i) per ogni lista.
    k = 60 è il valore standard dalla letteratura.
    """
    scores: dict[str, dict] = {}
    for rank, result in enumerate(dense):  #enumerate() iteri e ti da anche l'index 
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {
                "id": rid, 
                "payload": result.payload, 
                "score": 0.0
            }   #pk ricorda scores dict[str, dict], e lo inizializzi
        scores[rid]["score"] += 1.0 / (60 + rank + 1)   #accedi all campo target e fai update. rank+1 perché enumerate parte da 0, quindi formula è 1/(k + rank) quindi e.g. per il primo risultato rank=0 quindi 1/(60+0+1)=1/61, per il secondo rank=1 quindi 1/(60+1+1)=1/62, ecc. in questo modo i primi risultati sono piu bassi e hanno un boost maggiore
    for rank, result in enumerate(sparse):
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {
                "id": rid, 
                "payload": result.payload, 
                "score": 0.0
            }
        scores[rid]["score"] += 1.0 / (60 + rank + 1)   #accedi all campo target e fai update
    return sorted( scores.values(), key=lambda x: x["score"], reverse=True )    #prende tutti i chunks, e li ordin per score decrescente.

def _mmr_rerank(      #Re-Ranking technique, formuala  λ*relevance-(1-λ)*similarity. QUESTA MIA VERSIONE è meno potente della vera versione di mmr!!
    query_vector: list[float],
    results: list[dict],
    lambda_param: float = 0.5,
    top_k: int | None = None,
) -> list[dict]:
    """
    Maximal Marginal Relevance — diversifica i risultati.
    formula: MMR = λ*relevance - (1-λ)*max_similarity_to_selected
    Bilancia rilevanza (similarity con query) e diversità (dissimilarity tra chunk).
    lambda_param: 0=massima diversità, 1=massima rilevanza
    """
    import numpy as np   #serve INSTALLARE LIB numpy !! ma inttanto non viene utilizzato 
    if not results:
        return results
    k = top_k or len(results)
    selected = []
    remaining = list( results )  #clone
    #Vettori dei chunk (usiamo lo score come proxy della similarity)
    while len(selected) < k and remaining:   #continue finche lista selected non supera k(number) e che ci sono sempre ancora elementi dentro list 'remaining'
        if not selected:
            #prima iterazione: prendi il più rilevante cioe il primo della lista(quello che ha il massimo score) !
            best = remaining[0]
        else:
            #MMR: massimizza λ*relevance - (1-λ)*max_similarity_to_selected
            best_score = float("-inf")   #equivale a -∞
            best = remaining[0]
            for candidate in remaining:
                relevance = candidate["score"]
                # Similarità con i già selezionati (approssimazione tramite score overlap)
                max_sim = max(
                    _score_similarity(candidate, sel) for sel in selected  #run function here qua sotto
                )  #max() prende solo il valore max calcolato tra tutti quelli calcolati
                mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim   #formula mmr, prima parte → qualità del chunk seconda parte → penalità se è troppo simile
                if mmr_score > best_score:
                    best_score = mmr_score
                    best = candidate
        selected.append(best)
        remaining.remove(best)
        #sposti il best nei risultati finali e lo rimuovi da quelli rimanenti
    return selected  #return the bests

def _score_similarity(a: dict, b: dict) -> float:
    """Similarità approssimata tra due chunk basata sul filename e chunk_index."""
    pa, pb = a["payload"], b["payload"]
    if pa.get("document_id") == pb.get("document_id"):  #verifica se provengono dalla stessa fonte (se è cosi alta similarità se chunk adiacenti )
        diff = abs( pa.get("chunk_index", 0) - pb.get("chunk_index", 0) )
        #prende l'indice dei chunks e.g. pa["chunk_index"]=5  pb["chunk_index"]=6  e 
        #calcola la distanza tra i chunk (), più sono vicini più sono simili, quindi similarity è 1 quando diff=0, e decresce linearmente fino a 0 quando diff>=10 (puoi regolare questo valore in base alla lunghezza media dei tuoi chunk, ma 10 è un buon punto di partenza)
        return max(0, 1.0 - diff * 0.1)   #questa è la formula equivale a similarity = 1 - 0.1 * diff. e.g. diff=0  1-0*0.1 -> 1  result similarity = 1.0 (massima similarita),  se è invece diff=1 (chunks adiacenti) ... result similarity = 0.9
    return 0.0

def _cross_encoder_rerank(  #ReRanking technique usando Cross-Encoder (NON Bi-Encoder)
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
    if not reranker:  #se download fallito or altri problemi
        return results[:top_k]  #return solo i primi top_k senza aver fatto reranking technique
    pairs = [ (query, r["payload"].get("text", "")) for r in results ]   #per ogni item in results, couple {myquery, r["payload"].get("text")}
    scores = reranker.predict(pairs)  #il modello valuta ogni coppia, e assegna un punteggio di rilevanza. più alto è il punteggio, più rilevante è il chunk rispetto alla query.
    for result, score in zip(results, scores):  #zip accoppia gli elementi che sono nello stesso index (xk sono in 2 liste separate) 
        result["rerank_score"] = float(score)   #update
    reranked = sorted(results, key=lambda x: x.get("rerank_score", 0), reverse=True)  #ordina per il nuovo campo "rerank_score" in ordine decrescente, quindi i chunk più rilevanti secondo il reranker saranno in cima alla lista.
    logger.debug(f"Reranking: {len(results)} → {top_k} chunk")
    return reranked[:top_k]  #return solo i primi top_k dalla cima!!


