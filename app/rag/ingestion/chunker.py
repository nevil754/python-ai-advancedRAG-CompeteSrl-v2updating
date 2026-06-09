# =============================================================
# app/rag/ingestion/chunker.py
# Divide il testo in chunk ottimizzati per il retrieval.
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain.text_splitter import MarkdownTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

from app.core.settings import get_settings

settings = get_settings()


@dataclass
class Chunk:
    """Un singolo chunk di testo pronto per l'embedding."""
    text: str
    chunk_index: int
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_document(
    text: str,
    pages: list[str] | None = None,
    base_metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """
    Divide il testo in chunk con la strategia configurata.

    Strategie:
    - markdown: rispetta titoli e sezioni (ottimo per contratti strutturati)
    - recursive: fallback generico con separatori multipli
    - sentence: divide per frasi (ottimo per testi continui)

    Args:
        text: testo completo del documento
        pages: testo diviso per pagina (per tracciare page_number)
        base_metadata: metadata di base da includere in ogni chunk

    Returns:
        Lista di Chunk pronti per l'embedding
    """
    strategy = settings.ingestion_chunk_strategy
    chunk_size = settings.ingestion_chunk_size
    overlap = settings.ingestion_chunk_overlap

    if strategy == "markdown":
        splitter = MarkdownTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
        )
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    raw_chunks = splitter.split_text(text)

    # Filtra chunk troppo piccoli (meno di min_chunk_size caratteri)
    min_size = max(50, chunk_size // 20)
    raw_chunks = [c for c in raw_chunks if len(c.strip()) >= min_size]

    chunks: list[Chunk] = []
    for i, chunk_text in enumerate(raw_chunks):
        page_num = _find_page_number(chunk_text, pages) if pages else None

        chunks.append(Chunk(
            text=chunk_text.strip(),
            chunk_index=i,
            page_number=page_num,
            metadata={**(base_metadata or {}), "chunk_index": i},
        ))

    logger.debug(
        f"Chunking completato: {len(raw_chunks)} → {len(chunks)} chunk validi",
        strategy=strategy,
        chunk_size=chunk_size,
    )
    return chunks


def _find_page_number(chunk_text: str, pages: list[str]) -> int | None:
    """Trova in quale pagina appare il chunk cercando il testo."""
    for i, page_text in enumerate(pages, 1):
        if chunk_text[:100] in page_text:
            return i
    return None
