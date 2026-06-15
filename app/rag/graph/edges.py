# =============================================================
# app/rag/graph/edges.py
# Logica di routing condizionale tra i nodi del grafo.
# =============================================================

from __future__ import annotations

from app.rag.graph.state import RAGState


def edge_route_decision(state: RAGState) -> str:
    """
    Dopo il nodo route, decide quale percorso seguire.
    Ritorna il nome del prossimo nodo.
    """
    route = state.get("route", "rag")
    if route == "web":
        return "web_search"
    return "retrieve"  # rag | sql | general → tutti passano dal retrieve
