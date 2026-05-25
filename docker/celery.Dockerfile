# =============================================================
# RAG Enterprise Legal — Celery worker image
# Separato da FastAPI: i worker caricano modelli pesanti
# (fastembed, reranker) che non servono all'API server
# =============================================================

FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    unixodbc-dev \
    build-essential \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Pre-scarica i modelli fastembed nel layer di build
# Così non vengono scaricati ad ogni restart del container
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/BGE-M3')" \
    || echo "fastembed model preload skipped (no internet in build)"

FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    unixodbc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/lib/x86_64-linux-gnu/libodbc* /usr/lib/x86_64-linux-gnu/
COPY --from=builder /opt/microsoft /opt/microsoft
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin
# Copia cache modelli pre-scaricati
COPY --from=builder /root/.cache /root/.cache

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    C_FORCE_ROOT=1

WORKDIR /app

COPY app/ ./app/
COPY config/ ./config/

# Il CMD viene sovrascritto dal docker-compose.yml per ogni worker
# (high priority vs default priority queue)
CMD ["celery", "-A", "app.workers.celery_app.celery_app", "worker", \
     "--loglevel=info", "--concurrency=2"]
