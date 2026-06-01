# app/db/sqlserver.py
# TenantDB: gestione connessioni SQL Server con schema switching.
# Ogni request imposta lo schema del tenant sulla connessione.
from __future__ import annotations
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import AsyncGenerator, Generator
from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

@lru_cache(maxsize=1)
def get_sync_engine():
    """Engine SQLAlchemy sincrono — usato nei worker Celery."""
    from app.core.settings import get_settings
    settings = get_settings()
    engine = create_engine(
        settings.sqlserver_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,        # verifica connessione prima di usarla
        pool_recycle=3600,         # ricicla connessioni ogni ora
        echo=settings.app_debug,   # log SQL queries in debug mode
    )
    logger.info("Engine SQL Server sincrono creato")
    return engine

@lru_cache(maxsize=1)
def get_async_engine():
    """
    Engine SQLAlchemy asincrono — usato nelle route FastAPI.
    Usa aioodbc come driver async per SQL Server.
    """
    from app.core.settings import get_settings
    settings = get_settings()
    # URL async: sostituisce mssql+pyodbc con mssql+aioodbc
    async_url = settings.sqlserver_url.replace(
        "mssql+pyodbc", "mssql+aioodbc"
    )
    engine = create_async_engine(
        async_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.app_debug,
    )
    logger.info("Engine SQL Server asincrono creato")
    return engine

class TenantDB:
    """
    Gestisce sessioni SQL Server con schema switching per tenant.
    Il pattern è:
    1. Ottieni sessione con get_session(tenant_slug)
    2. SQLAlchemy esegue "USE RAGChat; SET SCHEMA tenant_acme"
    3. Tutte le query successive trovano le tabelle del tenant corretto
    4. La sessione viene chiusa automaticamente (context manager)
    Uso (sincrono — nei worker Celery):
        with tenant_db.get_session("acme") as session:
            session.execute(text("SELECT * FROM documents"))
    Uso (asincrono — nelle route FastAPI):
        async with tenant_db.aget_session("acme") as session:
            await session.execute(text("SELECT * FROM documents"))
    """
    def __init__(self):
        self._sync_factory = sessionmaker(
            bind=get_sync_engine(),
            autocommit=False,
            autoflush=False,
        )
        self._async_factory = async_sessionmaker(
            bind=get_async_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    @contextmanager
    def get_session(self, tenant_slug: str) -> Generator[Session, None, None]:
        """
        Context manager sincrono per sessioni tenant.
        Imposta lo schema SQL Server all'inizio e fa rollback in caso di errore.
        """
        session = self._sync_factory()
        try:
            self._set_schema_sync(session, tenant_slug)
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def aget_session(
        self, tenant_slug: str
    ) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager asincrono per sessioni tenant.
        Usato nelle route FastAPI per non bloccare l'event loop.
        """
        async with self._async_factory() as session:
            try:
                await self._set_schema_async(session, tenant_slug)
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def _set_schema_sync(self, session: Session, tenant_slug: str) -> None:
        """
        Imposta lo schema del tenant sulla sessione SQL Server.
        In SQL Server non esiste SET search_path come in Postgres —
        usiamo ALTER USER per impostare il default schema della sessione.
        """
        schema_name = _slug_to_schema(tenant_slug)
        # Verifica che lo schema esista prima di impostarlo
        result = session.execute(
            text("SELECT 1 FROM sys.schemas WHERE name = :schema"),
            {"schema": schema_name}
        ).fetchone()
        if not result:
            raise ValueError(
                f"Schema tenant '{schema_name}' non trovato. "
                f"Eseguire sp_provision_tenant prima."
            )
        # Imposta schema di default per questa connessione
        session.execute(
            text(f"ALTER USER SA WITH DEFAULT_SCHEMA = [{schema_name}]")
        )
        session.execute(text("COMMIT"))

    async def _set_schema_async(
        self, session: AsyncSession, tenant_slug: str
    ) -> None:
        """Versione async di _set_schema_sync."""
        schema_name = _slug_to_schema(tenant_slug)
        result = await session.execute(
            text("SELECT 1 FROM sys.schemas WHERE name = :schema"),
            {"schema": schema_name}
        )
        if not result.fetchone():
            raise ValueError(
                f"Schema tenant '{schema_name}' non trovato."
            )
        await session.execute(
            text(f"ALTER USER SA WITH DEFAULT_SCHEMA = [{schema_name}]")
        )

    async def provision_tenant(
        self,
        slug: str,
        display_name: str,
        plan: str = "starter",
    ) -> None:
        """
        Chiama la stored procedure sp_provision_tenant su SQL Server.
        Crea schema + tabelle per un nuovo tenant.
        Idempotente — chiamabile più volte senza errori.
        """
        async with self._async_factory() as session:
            try:
                await session.execute(
                    text("""
                        EXEC shared.sp_provision_tenant
                            @slug = :slug,
                            @display_name = :display_name,
                            @plan = :plan
                    """),
                    {"slug": slug, "display_name": display_name, "plan": plan}
                )
                await session.commit()
                logger.info(
                    "Tenant provisionato",
                    slug=slug,
                    schema=_slug_to_schema(slug),
                )
            except Exception as e:
                await session.rollback()
                logger.error(f"Errore provisioning tenant {slug}: {e}")
                raise

    @staticmethod
    async def ping() -> bool:
        """Verifica connessione SQL Server. Usato in /health."""
        try:
            engine = get_async_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"SQL Server ping fallito: {e}")
            return False

def _slug_to_schema(slug: str) -> str:
    """
    Converte slug tenant nel nome dello schema SQL Server.
    "acme-corp" → "tenant_acme_corp"
    """
    return "tenant_" + slug.replace("-", "_").lower()

# Singleton globale — importato da deps.py e dai worker Celery
tenant_db = TenantDB()
