-- =============================================================================
-- News & Intelligence Platform - Hybrid Schema (PostgreSQL)
-- Operational Store & Staging for Neo4j Knowledge Graph
-- =============================================================================

-- Enable UUID extension if not already present
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. SOURCES TABLE
-- Tracks feeds, API endpoints, poll frequencies, and health
CREATE TABLE IF NOT EXISTS sources (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(64) NOT NULL,            -- 'tech', 'finance', 'health', 'politics'
    feed_url TEXT NOT NULL,
    feed_type VARCHAR(32) NOT NULL,           -- 'rss', 'rest_json', 'atom'
    fetch_interval_min INT DEFAULT 15,
    last_fetched_at TIMESTAMPTZ,
    last_status VARCHAR(32) DEFAULT 'OK',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. ARTICLES / STORIES TABLE
-- Fast operational store for headlines, deduplication, and read views
CREATE TABLE IF NOT EXISTS articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id VARCHAR(64) NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,                 -- Canonical deduplication key
    published_at TIMESTAMPTZ NOT NULL,
    category VARCHAR(64) NOT NULL,
    author TEXT,
    summary TEXT,
    content_raw TEXT,
    
    -- Flexible metadata for source-specific payloads:
    -- e.g. SEC: {"cik": "0000320193", "form": "8-K", "accession": "..."}
    -- e.g. HN: {"score": 342, "comments": 89, "hn_id": 42100123}
    -- e.g. arXiv: {"doi": "...", "primary_category": "cs.AI"}
    raw_payload JSONB DEFAULT '{}'::jsonb,
    
    -- Sync marker for asynchronous Neo4j knowledge graph extraction
    -- NULL = Pending graph ingestion; Timestamp = Synced
    graph_synced_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. EXTRACTED ENTITIES (RELATIONAL STAGING CACHE)
-- Entities extracted before / during sync to Neo4j
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,         -- 'COMPANY', 'PERSON', 'INSTITUTION', 'METRIC', 'TOPIC'
    canonical_id VARCHAR(255),               -- Ticker, CIK, or Wikidata ID
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_entity_name_type UNIQUE (name, entity_type)
);

-- 4. ARTICLE-ENTITY JUNCTION TABLE
CREATE TABLE IF NOT EXISTS article_entities (
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence_score FLOAT DEFAULT 1.0,
    extracted_via VARCHAR(64) DEFAULT 'rule', -- 'rule', 'regex', 'ner_model'
    PRIMARY KEY (article_id, entity_id)
);

-- 5. MACRO ECONOMIC METRICS TABLE (For RBA, Fed, Inflation tracking)
CREATE TABLE IF NOT EXISTS macro_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(128) NOT NULL,               -- e.g. 'RBA_CASH_RATE', 'AU_CPI'
    value NUMERIC(14, 4) NOT NULL,
    unit VARCHAR(32) NOT NULL,                -- 'percent', 'index', 'currency'
    effective_date DATE NOT NULL,
    source_id VARCHAR(64) REFERENCES sources(id),
    raw_payload JSONB DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_metric_name_date UNIQUE (name, effective_date)
);

-- =============================================================================
-- PERFORMANCE INDEXES (Optimized for feed delivery & async graph queues)
-- =============================================================================

-- High-speed reverse-chronological feed filtering
CREATE INDEX IF NOT EXISTS idx_articles_category_published 
ON articles (category, published_at DESC);

-- Partial index for background graph sync queue (zero overhead on synced items)
CREATE INDEX IF NOT EXISTS idx_articles_pending_graph 
ON articles (published_at DESC) 
WHERE graph_synced_at IS NULL;

-- Fast source status checks
CREATE INDEX IF NOT EXISTS idx_sources_active 
ON sources (is_active, last_fetched_at);
