# =============================================================
# app/rag/ingestion/cleaner.py
# Pulizia testo estratto dal parser prima del chunking.
# =============================================================

from __future__ import annotations

import re


def clean_text(text: str) -> str:
    """
    Pulisce il testo estratto dal parser rimuovendo artefatti
    comuni nei PDF/DOCX e normalizzando il whitespace.
    """
    if not text:
        return ""

    # Rimuovi null bytes e caratteri di controllo (tranne newline e tab)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Normalizza line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Rimuovi linee che sono solo numeri di pagina (es. "- 42 -", "42")
    text = re.sub(r"^\s*-?\s*\d+\s*-?\s*$", "", text, flags=re.MULTILINE)

    # Rimuovi header/footer ripetuti (3+ occorrenze della stessa riga)
    lines = text.split("\n")
    line_counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if len(stripped) > 5:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1

    # Rimuovi linee che appaiono più di 5 volte (probabili header/footer)
    repeated = {line for line, count in line_counts.items() if count > 5}
    if repeated:
        lines = [l for l in lines if l.strip() not in repeated]
        text = "\n".join(lines)

    # Collassa spazi multipli in uno (ma non newline)
    text = re.sub(r"[ \t]+", " ", text)

    # Collassa più di 3 newline consecutive in 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Rimuovi spazi a inizio e fine di ogni riga
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    return text.strip()


def normalize_whitespace(text: str) -> str:
    """Normalizzazione leggera — solo whitespace, nessuna rimozione di contenuto."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
