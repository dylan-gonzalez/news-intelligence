# News & Intelligence Platform 

A personal, high-signal intelligence platform designed to replace addictive social feeds with structured, chronological primary sources across **Tech, Finance, Health, and Politics**.

Todo:
* incoroporate neo4j, elasticsearch


## Architecture: Hybrid Operational + Knowledge Graph

```
[ Sources: RBA, SEC EDGAR, HN, arXiv, etc. ]
                   │
                   ▼ (collector.py)
   ┌────────────────────────────────┐
   │ PostgreSQL / SQLite (Primary)  │ ──► Fast Morning Edition / Headlines Feed
   │ - Full operational history     │
   │ - Deduplication & B-Tree index │
   └────────────────────────────────┘
                   │
                   ▼ (Asynchronous Entity Sync)
   ┌────────────────────────────────┐
   │ Neo4j Knowledge Graph (Brain)  │ ──► Deep Investigation / Entity Traversal
   │ - Multi-hop connection search  │
   │ - Cross-domain correlation     │
   └────────────────────────────────┘
```

## Quick Start (Run Ingestion Now)

The collector runs with Python 3 (standard library only, zero external pip dependencies needed for the SQLite driver):

```powershell
& "C:\Users\dylcg\AppData\Local\Python\bin\python.exe" collector.py
```

## Project Structure
* `schema.sql`: Full production PostgreSQL DDL schema with UUIDs, indexes, JSONB payloads, and partial indexing for background Neo4j synchronization.
* `collector.py`: Pluggable ingestion engine with live adapters for:
  * **RBA** (Reserve Bank of Australia RSS media releases)
  * **SEC EDGAR** (Official US corporate disclosures / 8-K / 10-Q)
  * **Hacker News** (Firebase REST API top stories stream)
  * **arXiv** (Computer Science & AI Atom feed)
* `news_platform.db`: SQLite database created automatically by `collector.py` for immediate local development.
