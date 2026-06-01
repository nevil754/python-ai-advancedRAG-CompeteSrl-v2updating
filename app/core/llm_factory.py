# app/core/llm_factory.py
# Factory per costruire l'istanza LLM da config.yaml / .env.
# Cambiare provider = cambiare 1 riga in config.yaml, zero codice.
from __future__ import annotations
from functools import lru_cache
from typing import Any
from langchain_core.language_models import BaseChatModel
from loguru import logger
from app.core.settings import get_settings

@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """
    Costruisce e ritorna l'istanza LLM configurata.
    Singleton — creata una sola volta per tutto il processo.

    Provider supportati (da config.yaml llm.provider):
        - ollama   → ChatOllama (modello locale via Ollama)
        - openai   → ChatOpenAI (GPT-4, gpt-4.1-mini, ecc.)
        - google   → ChatGoogleGenerativeAI (Gemini)
    Returns:
        Istanza BaseChatModel pronta all'uso.
    """
    settings = get_settings()
    provider = settings.llm_provider.lower()
    logger.info(
        "Inizializzazione LLM",
        provider=provider,
        model=settings.llm_model,
    )
    if provider == "ollama":
        return _build_ollama(settings)
    elif provider == "openai":
        return _build_openai(settings)
    elif provider == "google":
        return _build_google(settings)
    else:
        raise ValueError(
            f"Provider LLM '{provider}' non supportato. "
            f"Usa: ollama | openai | google"
        )

def _build_ollama(settings: Any) -> BaseChatModel:
    """Costruisce ChatOllama per modelli locali."""
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        num_ctx=settings.llm_num_ctx,
        num_predict=settings.llm_max_tokens,
        timeout=settings.llm_timeout,
    )

def _build_openai(settings: Any) -> BaseChatModel:
    """Costruisce ChatOpenAI per modelli OpenAI."""
    from langchain_openai import ChatOpenAI
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY mancante nel .env")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout,
        streaming=settings.llm_streaming,
    )

def _build_google(settings: Any) -> BaseChatModel:
    """Costruisce ChatGoogleGenerativeAI per modelli Gemini."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise ImportError(
            "Installa langchain-google-genai per usare Google come provider: "
            "pip install langchain-google-genai"
        )
    if not settings.google_api_key:
        raise ValueError("GOOGLE_API_KEY mancante nel .env")
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.google_api_key,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_tokens,
    )

def get_llm_for_tenant(
    tenant_settings: dict | None = None,
) -> BaseChatModel:
    """
    Versione che permette override per-tenant delle impostazioni LLM.
    Utile se tenant enterprise vogliono usare il proprio modello/API key.
    Args:
        tenant_settings: dict con override opzionali, es.
                         {"provider": "openai", "model": "gpt-4.1", "api_key": "..."}
    Returns:
        LLM configurato per quel tenant, oppure LLM globale se no override.
    """
    if not tenant_settings:
        return get_llm()
    settings = get_settings()
    provider = tenant_settings.get("provider", settings.llm_provider).lower()
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=tenant_settings.get("model", settings.llm_model),
            api_key=tenant_settings.get("api_key", settings.openai_api_key),
            temperature=tenant_settings.get("temperature", settings.llm_temperature),
            max_tokens=settings.llm_max_tokens,
            streaming=settings.llm_streaming,
        )
    # Per altri provider usa il default globale
    return get_llm()

