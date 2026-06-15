# =============================================================
# tests/conftest.py
# Fixtures pytest condivise tra tutti i test.
# =============================================================

from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from main import create_app
from app.core.settings import get_settings


@pytest.fixture(scope="session")
def event_loop():
    """Event loop condiviso per tutti i test async della sessione."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def app():
    """Istanza FastAPI per i test."""
    return create_app()


@pytest.fixture
async def client(app):
    """Client HTTP async per chiamare le API nei test."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def tenant_context():
    """Contesto tenant finto per i test unitari."""
    from app.api.deps import TenantContext
    return TenantContext(
        tenant_id="test-tenant-uuid",
        tenant_slug="test-tenant",
        user_id="test-user-uuid",
        user_role="admin",
        user_email="test@example.com",
    )


@pytest.fixture
def sample_chunks():
    """Chunk di esempio per i test di retrieval e generation."""
    from app.rag.retrieval.retriever import RetrievedChunk
    return [
        RetrievedChunk(
            text="Il contratto scade il 31 dicembre 2024 salvo rinnovo tacito.",
            score=0.92,
            chunk_id="chunk-001",
            document_id="doc-001",
            filename="contratto_acme.pdf",
            page_number=3,
            chunk_index=0,
            doc_type="contract",
            metadata={},
        ),
        RetrievedChunk(
            text="Le parti concordano un corrispettivo mensile di 5.000 euro.",
            score=0.87,
            chunk_id="chunk-002",
            document_id="doc-001",
            filename="contratto_acme.pdf",
            page_number=4,
            chunk_index=1,
            doc_type="contract",
            metadata={},
        ),
    ]
