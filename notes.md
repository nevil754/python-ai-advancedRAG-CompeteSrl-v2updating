
questo prj batterà app RAG internazionalmente famose come Legora/Harvey/ LexRoom (italiana)

```
langchain
langgraph
langchain-openai
langchain-ollama

pydantic  #🔥validazione e struttura dati in Python.
chainlit  #🔥 x ui chat per vedere result
python-dotenv   #x caricare .env
qdrant-client    #x qdrant(db vector)
fastembed   #lo usi e wrappi model from huggingface BAAI/BGE-M3. better better di OllamaEmbeddings( here model ollama x embedding)
sentence-transformers   #x modelli re-ranking & semantic similarity tecnhique. il vecchio 'transformers' oggi è sostituito da questo o BETTER da 'fastembed'
rank-bm25    #keyword search classico

#ingestion docs
docling[vlm]  #parsing document avanzato, preserva anche struttura complessa, ottimo x contratti legali/bilanci docs/ect, RAG pro. e.g.PDF → testo strutturato
unstructured  #general document parsing .pdf/html/ect
pypdf  #estrazione base testo pdf, veloce ma limitato
python-docx  #estrazione testo da .docx
openpyxl  #estrazione testo da file excel
markitdown #converte docs->markdown pulito strutturato
markdown2  #converte markdown → HTML
xhtml2pdf  #converte HTML → PDF

pandas #x tabelle/csv/ect
tavily-python  #motore di ricerca web progettato per RAG e agenti, è “LLM-ready results” quindi ti restituisce gia anche summary-extracted text-relevance score, 💰free con 1,000 API credits/month (OTTIMO QUINDI DOVE QUESTA FEAT NON E' FONDAMENTALE MA VUOI AVERLA & easy)
ddgs   #duckduckgo search, ti da i links come te li darebbe google se fai una ricerca manualmente. "Dimmi dove si trova l’informazione"
beautifulsoup4  #scraping web pages, estrazione testo da pagine web. "Apri quella pagina e leggimi tutto"s

# senza tavily-python faresti
# User query
#    ↓
# DDGS
#    ↓
# scraping (BeautifulSoup)
#    ↓
# cleaning
#    ↓
# LLM
# invece con tavily-python fai solo
# User query
#    ↓
# Tavily search
#    ↓
# clean context (no scraping)
#    ↓
# LLM answer


fastapi
uvicorn
sse-starlette  #streaming sse (token-by-token)

psycopg[binary]  #postgreSQL driver
sqlalchemy   #orm, scrivere db in modo astratto
redis  #🔥cache, VISTO CHE TU USI ANCHE celery(eseguire lavori async/background), allora in questo caso redis lavora ANCHE come message broker.g

aiohttp  #async http client
httpx  #alternative moderna a requests, serve per async + sync HTTP calls
celery  #🔥x eseguire lavori async/background, x async ingestion, e job scheduling

#observability
langsmith
opentelemetry-api  
opentelemetry-sdk

ragas   #valutare qualità RAG, hallucination detection
tiktoken  #token count, stimare costi LLM

aiosqlite  #sqlite async, x piccoli storage
asyncpg    #driver PostgreSQL async e velocissimo

loguru  #logging avanzato python, mooolto piu avanzato di semplice import logging, in un sistema rag/ai devi poter vedere tutto!

##testing
pytest   #test automatici in python
pytest-asyncio   #test async automatici in python
```


```
rag-enterprise/
│
├── docker/
│   ├── fastapi.Dockerfile
│   ├── celery.Dockerfile          ← separato da fastapi (dipendenze diverse)
│   └── sqlserver/
│       ├── init.sql               ← ★ montato come volume, eseguito al primo avvio
│       └── entrypoint.sh          ← attende SQL Server ready, poi esegue init.sql
│
├── docker-compose.yml
├── docker-compose.override.yml    ← sovrascritture dev (porte, volumi locali, ecc.)
│
├── config/
│   ├── config.yaml                ← configurazione app (embeddings, retriever, ecc.)
│   ├── prompts.yaml               ← tutti i prompt centralizzati qui
│   └── metadata.yaml              ← mapping metadati documenti
│
├── app/
│   │
│   ├── main.py                    ← FastAPI app factory, lifespan, router include
│   │
│   ├── api/
│   │   ├── deps.py                ← ⭐️ dipendenze condivise (get_tenant, get_db, ecc.)
│   │   │
│   │   ├── routes/
│   │   │   ├── auth.py            ← login, logout, token refresh, api_keys
│   │   │   ├── tenants.py         ← CRUD tenant (solo superadmin)
│   │   │   ├── users.py           ← CRUD utenti dentro il tenant
│   │   │   ├── collections.py     ← gestione collection (cartelle doc)
│   │   │   ├── documents.py       ← upload, status, delete
│   │   │   ├── chat.py            ← query RAG, streaming SSE
│   │   │   ├── jobs.py            ← status ingestion jobs
│   │   │   └── health.py          ← /health /ready /metrics
│   │   │
│   │   └── middleware/
│   │       ├── tenant.py          ← ⭐️ estrae tenant_id da JWT, inietta nel request.state
│   │       ├── auth.py            ← verifica JWT, api key
│   │       ├── rate_limit.py      ← per-tenant rate limiting via Redis
│   │       └── logging.py         ← structured logging con request_id
│   │
│   ├── core/
│   │   ├── settings.py            ← pydantic-settings, carica .env + config.yaml
│   │   ├── security.py            ← JWT encode/decode, password hashing
│   │   ├── llm_factory.py         ← costruisce LLM da config (ollama/openai/google)
│   │   ├── embeddings.py          ← fastembed wrapper, lazy-loaded
│   │   ├── vectorstore.py         ← qdrant client, collection management per tenant
│   │   ├── redis_client.py        ← ⭐️ TenantRedis (namespace isolation)
│   │   └── observability.py       ← opentelemetry + langsmith setup
│   │
│   ├── db/
│   │   ├── sqlserver.py           ← ⭐️ TenantDB: engine, session, schema switching
│   │   ├── models/
│   │   │   ├── shared.py          ← SQLAlchemy models per schema shared
│   │   │   └── tenant.py          ← SQLAlchemy models per schema tenant_*
│   │   └── repositories/          ← ★ pattern repository: tutta la logica DB qui
│   │       ├── base.py
│   │       ├── tenant_repo.py
│   │       ├── document_repo.py
│   │       ├── conversation_repo.py
│   │       └── user_repo.py
│   │
│   ├── rag/
│   │   │
│   │   ├── ingestion/
│   │   │   ├── parser.py          ← docling + unstructured routing per mime_type
│   │   │   ├── cleaner.py         ← rimozione artefatti, normalizzazione testo
│   │   │   ├── chunker.py         ← semantic/markdown chunking
│   │   │   ├── embedder.py        ← fastembed batch embedding
│   │   │   ├── metadata.py        ← estrazione + arricchimento metadata
│   │   │   └── pipeline.py        ← ★ orchestra parser→clean→chunk→embed→upsert
│   │   │
│   │   ├── retrieval/
│   │   │   ├── dense.py           ← vector search su Qdrant
│   │   │   ├── sparse.py          ← BM25 keyword search
│   │   │   ├── hybrid.py          ← ★ RRF fusion di dense + sparse
│   │   │   ├── mmr.py             ← diversificazione risultati
│   │   │   ├── reranker.py        ← cross-encoder BAAI/bge-reranker
│   │   │   ├── filters.py         ← filtri metadata (data, autore, collection)
│   │   │   └── retriever.py       ← ★ facade: espone retrieve(query, tenant_ctx)
│   │   │
│   │   ├── generation/
│   │   │   ├── prompts.py         ← carica da prompts.yaml, formatta con context
│   │   │   ├── chain.py           ← ★ LangChain chain: retriever → prompt → LLM
│   │   │   ├── streaming.py       ← SSE token streaming
│   │   │   ├── citations.py       ← estrae e formatta citazioni dalle sources
│   │   │   ├── hallucination.py   ← ragas faithfulness check
│   │   │   └── answer_validator.py ← validazione risposta (lunghezza, sicurezza)
│   │   │
│   │   ├── memory/
│   │   │   ├── short_term.py      ← Redis: ultimi N turni chat
│   │   │   ├── long_term.py       ← SQL: summary conversazione persistito
│   │   │   └── context_builder.py ← ★ assembla history + retrieved docs → prompt
│   │   │
│   │   ├── agents/
│   │   │   ├── router_agent.py    ← decide quale agent/tool usare
│   │   │   ├── rag_agent.py       ← agent RAG classico
│   │   │   ├── web_agent.py       ← tavily(1k/req free inzialia, fa web scraping e ti return gia dati strutturati x llm e.g.chatgpt) + beautifulsoup per ricerca web
│   │   │   ├── sql_agent.py       ← NL→SQL su DB del tenant
│   │   │   └── tools/
│   │   │       ├── search_tool.py
│   │   │       ├── calculator_tool.py
│   │   │       └── date_tool.py
│   │   │
│   │   └── graph/                 ← LangGraph workflows
│   │       ├── state.py           ← RAGState TypedDict
│   │       ├── nodes.py           ← ogni nodo del grafo
│   │       ├── edges.py           ← logica di routing condizionale
│   │       └── graph.py           ← ★ assembla e compila il grafo
│   │
│   ├── workers/
│   │   ├── celery_app.py          ← ★ Celery factory, config code per tenant
│   │   ├── ingestion_tasks.py     ← task: ingest_document, reprocess_document
│   │   ├── cleanup_tasks.py       ← task: purge_tenant, expire_sessions
│   │   └── scheduled_tasks.py     ← celery beat: usage rollup, cache warmup
│   │
│   ├── services/                  ← ★ orchestration layer (cresce con complessità)
│   │   ├── tenant_service.py      ← provisioning, offboarding, billing hooks
│   │   ├── document_service.py    ← coordina upload → job → status
│   │   └── chat_service.py        ← coordina retrieval + generation + memory
│   │
│   └── schemas/                   ← Pydantic v2 request/response models
│       ├── auth.py
│       ├── tenant.py
│       ├── document.py
│       ├── chat.py
│       └── common.py              ← PaginatedResponse, ErrorResponse, ecc.
│
├── tests/
│   ├── conftest.py                ← fixtures: test DB, tenant mock, client
│   ├── unit/
│   │   ├── test_chunker.py
│   │   ├── test_hybrid_retrieval.py
│   │   ├── test_citations.py
│   │   └── test_hallucination.py
│   ├── integration/
│   │   ├── test_ingestion_pipeline.py
│   │   ├── test_chat_flow.py
│   │   └── test_multitenant_isolation.py
│   └── e2e/
│       └── test_full_rag_flow.py
│
├── scripts/
│   ├── create_tenant.py           ← CLI: python scripts/create_tenant.py --slug acme
│   ├── seed_demo_data.py          ← inserisce doc demo per tenant demo-corp
│   └── benchmark_retrieval.py     ← misura qualità RAG con ragas
│
├── .env                           ← mai committato
├── .env.example                   ← committato, con valori placeholder
├── requirements.txt
├── requirements-dev.txt           ← pytest, black, ruff, mypy
├── pyproject.toml
├── docker-compose.yml
└── README.md
```

//in futuro fovrai pensare anche al GDPR per la privacy, quindi anonimizzare i dati sensibili!

//⚠️⚠️ mancano ancora i files 'test_...' !!

