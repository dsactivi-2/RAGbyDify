# Cloud Code Team

KI-Multi-Agent-System basierend auf Dify v1.13.0 (Self-Hosted) mit 12 spezialisierten Agents, koordiniert ueber einen FastAPI Orchestrator v3.0.

## 3-Tier Open Source Model Stack

Alle LLM-Modelle laufen ueber **Ollama Cloud** (0 GB lokal). Ollama v0.17.7 laeuft lokal als systemd Service.
Embedding (qwen3-embedding:latest, 4.36 GB) laeuft **lokal** auf dem Server.
Docker-Container erreichen Ollama ueber docker0 Bridge IP 172.17.0.1:11434.

| Tier | Modell | Agents | Spezialisierung |
|------|--------|--------|-----------------|
| **Tier 1 - Code** | MiniMax-M2.5 | Architect, Coder, DevOps, Tester | Code-Generierung, Architektur |
| **Tier 2 - Multilingual** | GLM-4.7 | Planner, Docs, Worker, Reviewer, Security, Debug, Coach | Planung, Reviews, Dokumentation |
| **Tier 3 - Guenstig** | DeepSeek V3.2 | Memory | Kontextgedaechtnis |
| **Embedding** | Qwen3-Embedding-8B | -- | KB Retrieval (4096 Dim., lokal) |

## Architektur

- **Plattform:** Dify v1.13.0 Self-Hosted auf Hetzner CCX33 (8 vCPU, 32 GB RAM)
- **Domain:** difyv2.activi.io (Caddy v2 SSL + HSTS)
- **Orchestrator:** FastAPI v3.0 Streaming (Port 8000, systemd)
- **RAG Middleware:** KB + HippoRAG + Memory + Anti-Halluzination Enrichment
- **Knowledge Graph:** Neo4j 5.26.22 + HippoRAG (Port 8001, systemd)
- **Memory:** Mem0 Cloud API + Core Memory SQLite
- **Vektoren:** Qdrant (Dify Docker)
- **Embedding:** Qwen3-Embedding-8B (lokal Ollama, 4.36 GB)
- **Telegram Bot:** A.AI Coach v3 (aktiv, systemd)

## 12 Agents

| Nr | Agent | Tier | Modell | Temp |
|----|-------|------|--------|------|
| 1 | Architect | Tier 1 | minimax-m2.5:cloud | 0.3 |
| 2 | Coder | Tier 1 | minimax-m2.5:cloud | 0.2 |
| 3 | DevOps | Tier 1 | minimax-m2.5:cloud | 0.3 |
| 4 | Tester | Tier 1 | minimax-m2.5:cloud | 0.2 |
| 5 | Planner | Tier 2 | glm-4.7:cloud | 0.4 |
| 6 | Docs | Tier 2 | glm-4.7:cloud | 0.4 |
| 7 | Worker | Tier 2 | glm-4.7:cloud | 0.5 |
| 8 | Reviewer | Tier 2 | glm-4.7:cloud | 0.3 |
| 9 | Security | Tier 2 | glm-4.7:cloud | 0.2 |
| 10 | Debug | Tier 2 | glm-4.7:cloud | 0.3 |
| 11 | Coach | Tier 2 | glm-4.7:cloud | 0.5 |
| 12 | Memory | Tier 3 | deepseek-v3.2:cloud | 0.1 |

## Chatflow-Architektur

Jeder Agent folgt diesem Flow:
1. **Start** - Eingabe empfangen
2. **Parallel:** Mem0 Retrieve + Knowledge Base Retrieval
3. **RAG Middleware:** KB + HippoRAG + User Memory + Anti-Halluzination Enrichment
4. **LLM** Anti-Halluzination Node (tier-spezifisches Modell)
5. **Answer** + Mem0 Save (parallel)

## API Endpoints

### Core

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /health | System-Status (Agents, Version) |
| POST | /task | Einzelner Agent-Aufruf |
| POST | /chain | Agent-Kette (sequentiell) |
| POST | /route | Auto-Routing per Keyword-Match |

### Konfiguration

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /config/agents | Alle Agent-Konfigurationen |
| GET | /config/agent/{name} | Einzelne Agent-Config |
| GET | /hooks | Liste aller 17 Hook-Endpoints |

### Memory

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET/PUT/DELETE | /memory/system | System-Variablen |
| GET/PUT | /memory/agent/{agent} | Agent-Memories |
| GET | /memory/context | Vollstaendiger Kontext |

### Self-Learning

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| POST | /feedback | Feedback verarbeiten |
| GET | /learning/stats | Lern-Statistiken |

### Knowledge Graph

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /hipporag/health | HippoRAG Status |
| POST | /hipporag/query | KG Query |
| GET | /rag/health | RAG + Memory Health |

### 17 Hooks (POST)

/save, /recall, /status, /learn, /format, /review, /test, /deploy, /explain, /refactor, /doc, /plan, /debug, /optimize, /security, /summarize, /fix

## Projektstruktur

    /opt/cloud-code/
    |-- orchestrator/
    |   |-- main.py               # FastAPI Orchestrator v3.0 (697 Zeilen)
    |   +-- rag_middleware.py      # RAG + Memory Middleware (symlink)
    |-- hipporag/
    |   +-- main.py               # HippoRAG Service (Neo4j)
    |-- kb-docs/
    |   |-- projektbeschreibung.md
    |   |-- tech-stack.md
    |   +-- workflows-und-prozesse.md
    |-- plugins/
    |   +-- cloud-code-orchestrator/  # Dify Plugin v3.0.0
    |-- data/
    |   |-- user_state.json        # Telegram Bot User-State
    |   +-- memories/              # Pro-User Memory Files
    |-- telegram_bot.py            # A.AI Coach Telegram Bot v3
    |-- rag_middleware.py           # RAG Middleware (Original)
    |-- rag_client.py              # RAG Client Library
    |-- extract_entities.py        # Entity-Extraktion fuer KG
    |-- dspy_config.py             # DSPy Konfiguration
    |-- eval_benchmark.json        # Evaluations-Benchmark
    |-- locustfile.py              # Load Testing (Locust)
    |-- backup.sh                  # Taegliches Backup Script
    |-- 04-verify-system.sh        # System-Verifikation
    |-- core_memory.db             # Core Memory (SQLite)
    |-- recall_memory.db           # Recall Memory (sqlite-vec)
    +-- .gitignore

## Setup

Server: Hetzner CCX33, Ubuntu 22.04, Docker + Dify v1.13.0 + Ollama v0.17.7 Cloud + Neo4j 5.26.22 + Caddy v2

## GitHub

Repository: https://github.com/dsactivi-2/RAGbyDify

---
**Version:** 3.0.0 | **Lizenz:** Privat
