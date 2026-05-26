-- RAG ENTERPRISE LEGAL ,SQL Server init script
-- Eseguito automaticamente da Docker al primo avvio
-- Strategia: schema-per-tenant dentro un unico database RAGChat

USE master;  --db di sistema, da cui creiamo il nostro db RAGChat
GO  --separatore batch code

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'RAGChat')
BEGIN
    CREATE DATABASE RAGChat
    COLLATE Latin1_General_100_CI_AS_SC_UTF8;   --encoding del db, CI=case insensitive AS=accent sensitive (distingue "è" da "e")  SC=supplementary characters (emoji e caratteri rari) UTF8=supporto completo unicode
END
GO

USE RAGChat;
GO

-- SCHEMA CONDIVISO  (metadati piattaforma, NON dati tenant)

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'shared')
    EXEC('CREATE SCHEMA shared');
GO

-- Registro di tutti i tenant attivi
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'tenants'
)
CREATE TABLE shared.tenants (
    id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),  --NEWSEQUENTIALID() è UUID/GUID univoco MA sequenziale
    slug            NVARCHAR(100)       NOT NULL,   -- "acme-corp" diventa → schema tenant_acme_corp
    display_name    NVARCHAR(255)       NOT NULL,
    plan            NVARCHAR(50)        NOT NULL DEFAULT 'starter',  -- starter | pro | enterprise
    is_active       BIT                 NOT NULL DEFAULT 1,
    max_docs        INT                 NOT NULL DEFAULT 500,
    max_users       INT                 NOT NULL DEFAULT 10,
    max_tokens_day  BIGINT              NOT NULL DEFAULT 100000,  --🔥RATE LIMIT TOKEN X DAY!!
    settings        NVARCHAR(MAX)       NULL,       -- JSON: feature flags, custom prompts, ecc.
    created_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),  --return data e ora corrente del server SQL in formato UTC
    updated_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
    CONSTRAINT PK_tenants PRIMARY KEY (id),
    CONSTRAINT UQ_tenants_slug UNIQUE (slug),
    CONSTRAINT CK_tenants_plan CHECK (plan IN ('starter','pro','enterprise'))
);
GO

-- Audit log globale (GDPR, compliance legale)
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'tenants'
)
CREATE TABLE shared.audit_log (  --FONDAMENTALE in contesti enterprise, con questa puoi ricostruire info chi ha fatto cosa, quando, dove, con che dati ect quest tab puo contenere recrods che ricostruiscono query rag - llm call - document ingestion - security
    id          BIGINT IDENTITY(1,1)    NOT NULL,
    tenant_id   UNIQUEIDENTIFIER        NOT NULL,
    user_id     UNIQUEIDENTIFIER        NULL,
    action      NVARCHAR(100)           NOT NULL,  --e.g. 'doc.upload' | 'chat.query' | 'user.login'
    resource    NVARCHAR(500)           NULL,
    ip_address  NVARCHAR(45)            NULL,
    user_agent  NVARCHAR(500)           NULL,
    metadata    NVARCHAR(MAX)           NULL,       -- JSON
    created_at  DATETIME2               NOT NULL DEFAULT GETUTCDATE(),
    CONSTRAINT PK_audit_log PRIMARY KEY (id),
    CONSTRAINT FK_audit_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO

CREATE INDEX IX_audit_tenant_date ON shared.audit_log (tenant_id, created_at DESC);  --index per iterare velocemente i records quando utente fa una search
GO

-- Utilizzo token per billing e rate limiting
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'tenants'
)
CREATE TABLE shared.usage_stats (
    id              BIGINT IDENTITY(1,1) NOT NULL,
    tenant_id       UNIQUEIDENTIFIER     NOT NULL,
    stat_date       DATE                 NOT NULL,
    tokens_in       BIGINT               NOT NULL DEFAULT 0,
    tokens_out      BIGINT               NOT NULL DEFAULT 0,
    queries_count   INT                  NOT NULL DEFAULT 0,
    docs_ingested   INT                  NOT NULL DEFAULT 0,
    CONSTRAINT PK_usage PRIMARY KEY (id),
    CONSTRAINT UQ_usage_tenant_date UNIQUE (tenant_id, stat_date),
    CONSTRAINT FK_usage_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO

-- API keys (per integrazione esterna di un tenant)
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'tenants'
)
CREATE TABLE shared.api_keys (
    id          UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),  --UUID/GUID univoco MA sequenziale
    tenant_id   UNIQUEIDENTIFIER    NOT NULL,
    key_hash    NVARCHAR(64)        NOT NULL,   -- SHA-256 della key, mai in chiaro
    name        NVARCHAR(255)       NOT NULL,
    scopes      NVARCHAR(500)       NOT NULL DEFAULT 'read,write',
    is_active   BIT                 NOT NULL DEFAULT 1,
    last_used   DATETIME2           NULL,
    expires_at  DATETIME2           NULL,
    created_at  DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
    CONSTRAINT PK_api_keys PRIMARY KEY (id),
    CONSTRAINT UQ_api_keys_hash UNIQUE (key_hash),
    CONSTRAINT FK_api_keys_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO


-- STORED PROCEDURE: provisioning dinamico di un tenant
-- Chiamata da Python (tenant_db.provision_tenant) al signup

CREATE OR ALTER PROCEDURE shared.sp_provision_tenant
    @slug           NVARCHAR(100),
    @display_name   NVARCHAR(255),
    @plan           NVARCHAR(50) = 'starter'
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @schema_name NVARCHAR(200) = 'tenant_' + REPLACE(@slug, '-', '_');
    DECLARE @sql NVARCHAR(MAX);

    -- 1. Crea schema
    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = @schema_name)
    BEGIN
        SET @sql = 'CREATE SCHEMA [' + @schema_name + ']';
        EXEC sp_executesql @sql;
    END

    -- 2. Inserisci record in shared.tenants
    IF NOT EXISTS (SELECT 1 FROM shared.tenants WHERE slug = @slug)
    BEGIN
        INSERT INTO shared.tenants (slug, display_name, plan)
        VALUES (@slug, @display_name, @plan);
    END

    -- 3. Crea tabelle tenant (DDL dinamico)

    -- users
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''users''
    )
    CREATE TABLE [' + @schema_name + '].users (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        email           NVARCHAR(255)       NOT NULL,
        full_name       NVARCHAR(255)       NULL,
        role            NVARCHAR(50)        NOT NULL DEFAULT ''user'',
        password_hash   NVARCHAR(255)       NULL,
        is_active       BIT                 NOT NULL DEFAULT 1,
        last_login      DATETIME2           NULL,
        settings        NVARCHAR(MAX)       NULL,
        created_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [PK_' + @schema_name + '_users] PRIMARY KEY (id),
        CONSTRAINT [UQ_' + @schema_name + '_users_email] UNIQUE (email),
        CONSTRAINT [CK_' + @schema_name + '_users_role] CHECK (role IN (''admin'',''user'',''viewer''))
    )';
    EXEC sp_executesql @sql;

    -- collections (cartelle logiche di documenti)
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''collections''
    )
    CREATE TABLE [' + @schema_name + '].collections (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        name            NVARCHAR(255)       NOT NULL,
        description     NVARCHAR(1000)      NULL,
        qdrant_name     NVARCHAR(300)       NOT NULL,  -- nome collection su Qdrant
        is_active       BIT                 NOT NULL DEFAULT 1,
        metadata        NVARCHAR(MAX)       NULL,
        created_by      UNIQUEIDENTIFIER    NULL,
        created_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [PK_' + @schema_name + '_collections] PRIMARY KEY (id),
        CONSTRAINT [UQ_' + @schema_name + '_qdrant_name] UNIQUE (qdrant_name)
    )';
    EXEC sp_executesql @sql;

    -- documents
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''documents''
    )
    CREATE TABLE [' + @schema_name + '].documents (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        collection_id   UNIQUEIDENTIFIER    NULL,
        filename        NVARCHAR(500)       NOT NULL,
        original_name   NVARCHAR(500)       NOT NULL,
        file_hash       NVARCHAR(64)        NOT NULL,   -- SHA-256, deduplicazione
        file_size       BIGINT              NOT NULL DEFAULT 0,
        mime_type       NVARCHAR(100)       NULL,
        storage_path    NVARCHAR(1000)      NULL,       -- path su object storage
        status          NVARCHAR(50)        NOT NULL DEFAULT ''pending'',
        chunk_count     INT                 NULL,
        page_count      INT                 NULL,
        language        NVARCHAR(10)        NULL DEFAULT ''it'',
        metadata        NVARCHAR(MAX)       NULL,
        uploaded_by     UNIQUEIDENTIFIER    NULL,
        created_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        updated_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [PK_' + @schema_name + '_documents] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_doc_status] CHECK (
            status IN (''pending'',''processing'',''ready'',''error'',''deleted'')
        )
    )';
    EXEC sp_executesql @sql;

    -- index su file_hash per deduplicazione veloce
    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = ''IX_' + @schema_name + '_doc_hash'')
        CREATE INDEX [IX_' + @schema_name + '_doc_hash]
        ON [' + @schema_name + '].documents (file_hash)';
    EXEC sp_executesql @sql;

    -- ingestion_jobs
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''ingestion_jobs''
    )
    CREATE TABLE [' + @schema_name + '].ingestion_jobs (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        document_id     UNIQUEIDENTIFIER    NOT NULL,
        celery_task_id  NVARCHAR(255)       NULL,
        status          NVARCHAR(50)        NOT NULL DEFAULT ''queued'',
        progress_pct    TINYINT             NOT NULL DEFAULT 0,
        error_msg       NVARCHAR(MAX)       NULL,
        retry_count     TINYINT             NOT NULL DEFAULT 0,
        started_at      DATETIME2           NULL,
        finished_at     DATETIME2           NULL,
        created_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [PK_' + @schema_name + '_jobs] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_job_status] CHECK (
            status IN (''queued'',''running'',''done'',''failed'',''cancelled'')
        )
    )';
    EXEC sp_executesql @sql;

    -- conversations
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''conversations''
    )
    CREATE TABLE [' + @schema_name + '].conversations (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        user_id         UNIQUEIDENTIFIER    NOT NULL,
        collection_id   UNIQUEIDENTIFIER    NULL,       -- NULL = cross-collection
        title           NVARCHAR(500)       NULL,
        mode            NVARCHAR(50)        NOT NULL DEFAULT ''rag'',  -- rag | agent | sql
        is_archived     BIT                 NOT NULL DEFAULT 0,
        metadata        NVARCHAR(MAX)       NULL,
        created_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        updated_at      DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [PK_' + @schema_name + '_convs] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    -- messages
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''messages''
    )
    CREATE TABLE [' + @schema_name + '].messages (
        id                  BIGINT IDENTITY(1,1)    NOT NULL,
        conversation_id     UNIQUEIDENTIFIER        NOT NULL,
        role                NVARCHAR(20)            NOT NULL,   -- user | assistant | system
        content             NVARCHAR(MAX)           NOT NULL,
        sources             NVARCHAR(MAX)           NULL,   -- JSON: [{chunk_id, score, snippet}]
        tokens_in           INT                     NULL,
        tokens_out          INT                     NULL,
        latency_ms          INT                     NULL,
        model_used          NVARCHAR(100)           NULL,
        hallucination_score FLOAT                   NULL,   -- da ragas
        created_at          DATETIME2               NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [PK_' + @schema_name + '_msgs] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_msg_role] CHECK (role IN (''user'',''assistant'',''system''))
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = ''IX_' + @schema_name + '_msgs_conv'')
        CREATE INDEX [IX_' + @schema_name + '_msgs_conv]
        ON [' + @schema_name + '].messages (conversation_id, created_at)';
    EXEC sp_executesql @sql;

    -- feedback (thumbs up/down, rating per RAGAS evaluation loop)
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''message_feedback''
    )
    CREATE TABLE [' + @schema_name + '].message_feedback (
        id          BIGINT IDENTITY(1,1) NOT NULL,
        message_id  BIGINT               NOT NULL,
        user_id     UNIQUEIDENTIFIER     NOT NULL,
        rating      TINYINT              NOT NULL,   -- 1=thumbs_up, 0=thumbs_down
        comment     NVARCHAR(1000)       NULL,
        created_at  DATETIME2            NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [PK_' + @schema_name + '_feedback] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    PRINT 'Tenant provisioned: ' + @schema_name;
END
GO


-- TENANT DI ESEMPIO: utile per dev/testing locale
EXEC shared.sp_provision_tenant
    @slug         = 'demo-corp',
    @display_name = 'Demo Corporation',
    @plan         = 'pro';
GO

PRINT 'init.sql completato.';
GO
