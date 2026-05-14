
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
project/
│
├── app/
│
│   ├── api/
│   │   ├── routes/
│   │   │   ├── chat.py
│   │   │   ├── ingestion.py
│   │   │   ├── retrieval.py
│   │   │   ├── auth.py
│   │   │   └── health.py
│   │   |
│   │   └── middleware/
│   │       ├── auth.py
│   │       ├── logging.py
│   │       └── rate_limit.py
│   |   
│   ├── core/
│   │   ├── settings.py
│   │   ├── llm_factory.py
│   │   ├── embeddings.py
│   │   ├── vectorstore.py
│   │   ├── redis.py
│   │   ├── observability.py
│   │   └── security.py
│   |
│   ├── rag/
│   │   |
│   │   ├── ingestion/
│   │   │   ├── parser.py
│   │   │   ├── cleaner.py
│   │   │   ├── chunker.py
│   │   │   ├── metadata.py
│   │   │   └── pipeline.py
│   │   |
│   │   ├── retrieval/
│   │   │   ├── hybrid.py
│   │   │   ├── mmr.py
│   │   │   ├── reranker.py
│   │   │   ├── filters.py
│   │   │   └── retriever.py
│   │   |
│   │   ├── generation/
│   │   │   ├── prompts.py
│   │   │   ├── streaming.py
│   │   │   ├── citations.py
│   │   │   ├── hallucination.py
│   │   │   └── answer_validator.py
│   │   |
│   │   ├── memory/
│   │   │   ├── short_term.py
│   │   │   ├── long_term.py
│   │   │   └── semantic_memory.py
│   │   |
│   │   ├── agents/
│   │   │   ├── router_agent.py
│   │   │   ├── retrieval_agent.py
│   │   │   ├── web_agent.py
│   │   │   ├── sql_agent.py
│   │   │   └── tools_agent.py
│   │   |
│   │   └── pipelines/
│   │       ├── graph.py
│   │       ├── routing.py
│   │       └── workflows.py
│   |
│   ├── mcp/
│   │   ├── servers/
│   │   ├── tools/
│   │   └── clients/
│   |
│   ├── workers/
│   │   ├── celery_worker.py
│   │   ├── ingestion_tasks.py
│   │   └── cleanup_tasks.py
│   | 
│   └── db/
│       ├── postgres.py
│       ├── migrations/
│       └── models/
│
├── config/
│   ├── config.yaml
│   └── prompts.yaml
│
├── docker/
│   ├── fastapi.Dockerfile
│   ├── qdrant.yml
│   ├── postgres.yml
│   └── redis.yml
│
├── docker-compose.yml
├── .env
├── requirements.txt
├── main.py
└── README.md
```

se poi cresce complessita allora
app/
  services/   ← orchestration layer


//in futuro fovrai pensare anche al GDPR per la privacy, quindi anonimizzare i dati sensibili!
