# =============================================================
# RAG Enterprise Legal — FastAPI image
# Multi-stage build: builder installa dipendenze,
# runtime è l'immagine finale leggera
# =============================================================

# ── Stage 1: builder ──────────────────────────────────────────
FROM python:3.11-slim AS builder

# Installa driver ODBC per SQL Server (Microsoft)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copia solo requirements prima del codice — sfrutta la cache Docker
# Se requirements.txt non cambia, questo layer non viene rieseguito
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --no-deps -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Riduce immagine finale: solo pacchetti runtime, non build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    unixodbc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copia driver ODBC e pacchetti installati dal builder
COPY --from=builder /usr/lib/x86_64-linux-gnu/libodbc* /usr/lib/x86_64-linux-gnu/
COPY --from=builder /opt/microsoft /opt/microsoft
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# Variabili ambiente per comportamento deterministico Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copia codice applicazione
COPY app/ ./app/
COPY config/ ./config/
COPY main.py .

# Utente non-root per sicurezza
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

# Directory cache embeddings (fastembed scarica i modelli qui)
RUN mkdir -p /app/.cache/embeddings

EXPOSE 8000

# --workers 1 in dev — in prod usa gunicorn o aumenta i worker
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", "--http", "httptools"]
