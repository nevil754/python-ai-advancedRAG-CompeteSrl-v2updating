# =============================================================
# app/api/routes/documents.py
# Route per la gestione documenti: upload, lista, status, delete.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status   #status x costanti http e.g. status.HTTP_200_OK ect
from loguru import logger
from sqlalchemy import text

from app.api.deps import AdminOnly, CurrentDB, CurrentRedis, CurrentTenant
from app.core.settings import get_settings
from app.schemas.common import PaginatedResponse
from app.schemas.document import DocumentSchema, IngestionJobSchema, UploadResponse
from app.services.document_service import DocumentService


router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()

ALLOWED_EXTENSIONS = set(
    settings.ingestion_loader_extensions 
    if hasattr(settings, 'ingestion_loader_extensions') 
    else [".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"]
)

@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    tenant: CurrentTenant,
    db: CurrentDB,
    redis: CurrentRedis,
    file: UploadFile = File(...),
    collection_id: str | None = Form(None),
) -> UploadResponse:
    """
    Carica un documento e lo mette in coda per l'ingestion.
    Risponde subito con 202 — il processing avviene in background.
    """
    suffix = "." + ( file.filename or "" ).rsplit(".", 1)[-1].lower()
    if suffix not in {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}:
        raise HTTPException(
            status_code=400,
            detail=f"Formato non supportato: {suffix}. Accettati: pdf, docx, xlsx, pptx, txt, md"
        )
    file_bytes = await file.read()
    service = DocumentService(
        db=db,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.tenant_slug,
        user_id=tenant.user_id,
    )
    try:
        result = await service.upload_and_queue(
            file_bytes=file_bytes,
            original_filename=file.filename or "documento",
            collection_id=collection_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return UploadResponse(**result)

@router.get("", response_model=PaginatedResponse[DocumentSchema])
async def list_documents(
    tenant: CurrentTenant,
    db: CurrentDB,
    page: int = 1,
    page_size: int = 20,
    collection_id: str | None = None,
    status_filter: str | None = None,
) -> PaginatedResponse[DocumentSchema]:
    """Lista documenti del tenant con paginazione e filtri."""
    offset = (page - 1) * page_size
    where = "WHERE 1=1"
    params: dict = {"limit": page_size, "offset": offset}
    if collection_id:
        where += " AND collection_id = :coll_id"
        params["coll_id"] = collection_id
    if status_filter:
        where += " AND status = :status"
        params["status"] = status_filter
    total_row = await db.execute(
        text(f"SELECT COUNT(*) FROM documents {where}"), params
    )
    total = total_row.scalar() or 0
    rows = await db.execute(
        text(f"""
            SELECT id, collection_id, filename, original_name, file_size,
                   mime_type, status, chunk_count, page_count, language,
                   created_at, updated_at
            FROM documents {where}
            ORDER BY created_at DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """),
        params
    )
    items = [DocumentSchema.model_validate(dict(r._mapping)) for r in rows]
    return PaginatedResponse.build(items=items, total=total, page=page, page_size=page_size)

@router.get("/{document_id}/status", response_model=IngestionJobSchema)
async def get_document_status(
    document_id: str,
    tenant: CurrentTenant,
    db: CurrentDB,
) -> IngestionJobSchema:
    """Ritorna lo status del job di ingestion per un documento."""
    row = await db.execute(
        text("""
            SELECT id, document_id, celery_task_id, status, progress_pct,
                   error_msg, retry_count, started_at, finished_at, created_at
            FROM ingestion_jobs
            WHERE document_id = :doc_id
        """),
        {"doc_id": document_id}
    )
    job = row.fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return IngestionJobSchema.model_validate(dict(job._mapping))

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    tenant: CurrentTenant,
    db: CurrentDB,
) -> None:
    """
    Cancella un documento: marca come deleted in SQL Server
    e rimuove i vettori da Qdrant.
    """
    # Verifica esistenza
    row = await db.execute(
        text("SELECT id, status FROM documents WHERE id = :id"),
        {"id": document_id}
    )
    doc = row.fetchone()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    # Cancella vettori da Qdrant
    from app.core.vectorstore import get_async_qdrant_client, get_collection_name
    from qdrant_client.http import models as qmodels

    client = get_async_qdrant_client()
    collection = get_collection_name(tenant.tenant_slug)
    try:
        await client.delete(
            collection_name=collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchValue(value=document_id)
                    )]
                )
            )
        )
    except Exception as e:
        logger.warning(f"Errore cancellazione vettori Qdrant: {e}")
    # Marca come deleted in SQL Server
    await db.execute(
        text("UPDATE documents SET status = 'deleted', updated_at = GETUTCDATE() WHERE id = :id"),
        {"id": document_id}
    )
    logger.info(f"Documento cancellato: {document_id}", tenant=tenant.tenant_slug)


