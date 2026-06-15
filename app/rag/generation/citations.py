# =============================================================
# app/rag/generation/citations.py
# Estrazione e formattazione citazioni nella risposta LLM.
# =============================================================

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.retrieval.retriever import RetrievedChunk


@dataclass
class Citation:
    index: int
    filename: str
    page_number: int | None
    chunk_id: str
    document_id: str
    snippet: str


def extract_citations(
    answer: str,
    chunks: list[RetrievedChunk],
) -> tuple[str, list[Citation]]:
    """
    Estrae le citazioni dalla risposta LLM e le abbina ai chunk sorgente.
    Il LLM usa il formato [Fonte N: filename, p.X] — questa funzione le parsa.

    Args:
        answer: risposta grezza dell'LLM con citazioni inline
        chunks: chunk usati come contesto (ordinati come inviati al LLM)

    Returns:
        Tuple (answer_clean, citations)
        answer_clean: risposta con citazioni normalizzate [1], [2], ...
        citations: lista Citation con metadata completi
    """
    citations: list[Citation] = []
    citation_map: dict[str, int] = {}  # filename → indice citazione

    # Pattern: [Fonte N: filename, p.X] oppure [Fonte N: filename]
    pattern = r'\[Fonte\s*(\d+):\s*([^\],]+?)(?:,\s*p\.(\d+))?\]'

    def replace_citation(match: re.Match) -> str:
        source_idx = int(match.group(1)) - 1  # 0-based
        filename = match.group(2).strip()
        page = int(match.group(3)) if match.group(3) else None

        # Trova il chunk corrispondente
        chunk = None
        if 0 <= source_idx < len(chunks):
            chunk = chunks[source_idx]
        else:
            # Cerca per filename
            for c in chunks:
                if c.filename == filename:
                    chunk = c
                    break

        if not chunk:
            return match.group(0)  # lascia invariato se non trovato

        # Crea o riusa indice citazione
        key = f"{chunk.document_id}:{chunk.chunk_index}"
        if key not in citation_map:
            idx = len(citations) + 1
            citation_map[key] = idx
            citations.append(Citation(
                index=idx,
                filename=chunk.filename,
                page_number=page or chunk.page_number,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                snippet=chunk.text[:200],
            ))
        else:
            idx = citation_map[key]

        return f"[{idx}]"

    answer_clean = re.sub(pattern, replace_citation, answer)
    return answer_clean, citations


def format_citations_markdown(citations: list[Citation]) -> str:
    """Formatta le citazioni come sezione markdown in fondo alla risposta."""
    if not citations:
        return ""

    lines = ["\n\n---\n**Fonti:**"]
    for c in citations:
        page_info = f", p. {c.page_number}" if c.page_number else ""
        lines.append(f"[{c.index}] {c.filename}{page_info}")

    return "\n".join(lines)
