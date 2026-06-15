#!/usr/bin/env python3

# =============================================================
# scripts/benchmark_retrieval.py
# Misura qualità RAG con ragas: faithfulness, context relevance.
# Utile per confrontare diverse configurazioni di retrieval.
# Uso: python scripts/benchmark_retrieval.py --tenant demo-corp
# =============================================================

import argparse  #x CLI args 
import asyncio  #x async functs
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  #__file__ è il path di questo script, poi sali su con parent e ancora con parent ed arrivi a root prj. aggiunge il path all'inizio del PYTHONPATH così quando importi moduli python cerca prima qui

#dataset di domande + risposte attese per il tenant demo
BENCHMARK_DATASET = [   #mini dataset di test per benchmark retrieval
    {
        "question": "Quando scade il contratto di fornitura software?",
        "expected_keywords": ["31/12/2024", "dicembre 2024", "annuale"],
    },
    {
        "question": "Quanto costa il servizio mensile?",
        "expected_keywords": ["5.000", "euro", "mensili"],
    },
    {
        "question": "Chi è il Responsabile della Protezione Dati?",
        "expected_keywords": ["dpo@demo-corp.com", "DPO"],
    },
    {
        "question": "Con quale preavviso si può risolvere il contratto?",
        "expected_keywords": ["90 giorni", "preavviso scritto"],
    },
]


async def main():
    parser = argparse.ArgumentParser(description="Benchmark qualità RAG")  #crea parser CLI. ora se da cli runni 'python create_tenant.py --help' vedrai result "Crea un nuovo tenant RAG"
    parser.add_argument("--tenant", default="demo-corp")  #e.g. runni '--slug acme-corp' allora return args.slug
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", default="benchmark_results.json")
    args = parser.parse_args()   #🔥qui argparse LEGGE i parametri reali!!

    from app.db.sqlserver import tenant_db
    from sqlalchemy import text

    async with tenant_db._async_factory() as session:
        row = await session.execute(
            text("SELECT id FROM shared.tenants WHERE slug = :slug"),
            {"slug": args.tenant}
        )
        result = row.fetchone()
        if not result:
            print(f"Tenant non trovato: {args.tenant}")
            sys.exit(1)
        tenant_id = str(result.id)

    from app.rag.retrieval.retriever import retrieve
    from app.rag.generation.chain import arun_rag_chain

    results = []
    total_score = 0.0

    print(f"\nBenchmark RAG — Tenant: {args.tenant}")
    print("=" * 60)

    for item in BENCHMARK_DATASET:
        question = item["question"]
        expected = item["expected_keywords"]

        print(f"\nQ: {question}")

        # Retrieval
        chunks = retrieve(
            query=question,
            tenant_slug=args.tenant,
            tenant_id=tenant_id,
            top_k=args.top_k,
        )

        # Generation
        result = await arun_rag_chain(
            question=question,
            chunks=chunks,
            session_messages=[],
        )

        answer = result["answer"]
        print(f"A: {answer[:150]}...")

        # Valutazione keyword matching (semplice, senza LLM)
        answer_lower = answer.lower()
        matches = sum(1 for kw in expected if kw.lower() in answer_lower)
        keyword_score = matches / len(expected) if expected else 0.0

        # Hallucination check
        from app.rag.generation.hallucination import check_faithfulness
        faith_score = await check_faithfulness(question, answer, chunks)

        combined_score = (keyword_score + faith_score) / 2
        total_score += combined_score

        print(f"   Keyword score: {keyword_score:.2f}")
        print(f"   Faithfulness:  {faith_score:.2f}")
        print(f"   Combined:      {combined_score:.2f}")
        print(f"   Chunks:        {len(chunks)}")

        results.append({
            "question": question,
            "answer": answer,
            "chunks_retrieved": len(chunks),
            "keyword_score": keyword_score,
            "faithfulness_score": faith_score,
            "combined_score": combined_score,
            "top_sources": [c.filename for c in chunks[:3]],
        })

    avg_score = total_score / len(BENCHMARK_DATASET)
    print(f"\n{'='*60}")
    print(f"SCORE MEDIO: {avg_score:.2f}/1.00")

    # Salva risultati
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({
            "tenant": args.tenant,
            "avg_score": avg_score,
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"Risultati salvati in: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
