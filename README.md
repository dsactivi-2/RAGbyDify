# Cloud Code Team

KI-Multi-Agent-System basierend auf Dify v1.13.0 (Self-Hosted) mit 12 spezialisierten Agents, koordiniert ueber einen FastAPI Orchestrator v3.0.

## Aktueller Stand (IST vs. SOLL)

> **Wichtig:** Der Code (main.py) definiert den SOLL-Zustand mit Open-Source-Modellen.
> Der tatsaechliche IST-Zustand auf dem Server weicht ab.

| | IST (Server laeuft) | SOLL (Code-Config) |
|---|---|---|
| **Tier 1** | GPT-4o (OpenRouter) | MiniMax-M2.5 (Ollama Cloud) |
| **Tier 2** | MiniMax-M2.5 | GLM-4.7 (Ollama Cloud) |
| **Tier 3** | MiniMax-M2.5 | DeepSeek V3.2 (Ollama Cloud) |
| **Embedding** | Qwen3-Embedding-8B (lokal) | Qwen3-Embedding-8B (lokal) |

**Bekannter Bug:** OpenRouter liefert bei einigen Agents `null`-Antworten (Template-Bug in Dify v1.13).

## Phasen-Status

| Phase | Beschreibung | Status |
|-------|-------------|--------|
| Phase 1 | Grundinfrastruktur (Dify, Docker, Caddy) | 100% |
| Phase 2 | 12 Agents + Orchestrator | 100% |
| Phase 3 | RAG Middleware + Anti-Halluzination | 100% |
| Phase 4 | LLM Integration + 3-Tier Routing | 85% |
| Phase 5 | RAG Query + Retrieval | 71% |
| Phase 6 | Knowledge Graph + Multi-Source | 75% |
| Phase 7 | Orchestrator Erweiterung | 60% |
| Phase 8 | Telegram Bot + API | 90% |
| Phase 9 | Docu-Blueprint-System | 0% (geplant) |

## Architektur

- **Plattform:** Dify v1.13.0 Self-Hosted auf Hetzner CCX33 (8 vCPU, 32 GB RAM)
- **Domain:** difyv2.activi.io (Caddy v2 SSL + HSTS)
- **Orchestrator:** FastAPI v3.0 Streaming (Port 8000, systemd)
- **RAG Middleware:** KB + HippoRAG + Memory + Anti-Halluzination Enrichment
- **Knowledge Graph:** Neo4j 5.26.22 + HippoRAG (Port 8001, systemd)
- **Memory:** Core Memory (SQLite) + Per-User Memory (JSON) + Mem0 Cloud API
- **Vektoren:** Qdrant (Dify Docker)
- **Embedding:** Qwen3-Embedding-8B (lokal Ollama, 4.36 GB)
- **Telegram Bot:** A.AI Coach v3 (aktiv, systemd)

## 12 Agents

| Nr | Agent | Aufgabe | IST-Modell |
|----|-------|---------|------------|
| 1 | Architect | System-Design, Architektur | GPT-4o |
| 2 | Coder | Code-Generierung | GPT-4o |
| 3 | DevOps | Deployment, Infrastruktur | GPT-4o |
| 4 | Tester | Tests, QA | GPT-4o |
| 5 | Planner | Planung, Sprints | MiniMax-M2.5 |
| 6 | Docs | Dokumentation | MiniMax-M2.5 |
| 7 | Worker | Allgemeine Aufgaben | MiniMax-M2.5 |
| 8 | Reviewer | Code Reviews | MiniMax-M2.5 |
| 9 | Security | Sicherheitsanalyse | MiniMax-M2.5 |
| 10 | Debug | Fehlersuche | MiniMax-M2.5 |
| 11 | Coach | Telegram Bot Coach | MiniMax-M2.5 |
| 12 | Memory | Kontextgedaechtnis | MiniMax-M2.5 |

## API Endpoints

### Core

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /health | System-Status |
| POST | /task | Einzelner Agent-Aufruf |
| POST | /chain | Agent-Kette (sequentiell) |
| POST | /route | Auto-Routing per Keyword-Match |

### Memory

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET/PUT/DELETE | /memory/system | System-Variablen (Core Memory) |
| GET/PUT | /memory/agent/{agent} | Agent-spezifische Memories |
| GET | /memory/context | Vollstaendiger Kontext fuer Prompt-Injection |

### RAG + Knowledge Graph

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /rag/health | RAG + Memory Health Check |
| GET | /hipporag/health | HippoRAG Status |
| POST | /hipporag/query | Knowledge Graph Query |

### Self-Learning

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| POST | /feedback | Feedback verarbeiten (Mem0 Cloud) |
| GET | /learning/stats | Lern-Statistiken |

### 17 Hooks (POST)

/save, /recall, /status, /learn, /format, /review, /test, /deploy, /explain, /refactor, /doc, /plan, /debug, /optimize, /security, /summarize, /fix

### Konfiguration

| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /config/agents | Alle Agent-Konfigurationen + Tier-Summary |
| GET | /config/agent/{name} | Einzelne Agent-Config |
| GET | /hooks | Liste aller Hook-Endpoints |

## Projektstruktur

```
/opt/cloud-code/
|-- orchestrator/
|   |-- main.py               # FastAPI Orchestrator v3.0 (698 Zeilen)
|   +-- rag_middleware.py      # RAG + Memory Middleware (symlink)
|-- hipporag/
|   +-- main.py               # HippoRAG Service (Neo4j)
|-- kb-docs/
|   |-- projektbeschreibung.md
|   |-- tech-stack.md
|   +-- workflows-und-prozesse.md
|-- plugins/
|   +-- cloud-code-orchestrator/  # Dify Plugin v3.0.0
|-- docs/
|   |-- TODOS.md              # Alle offenen Aufgaben
|   |-- RUNBOOK.md            # Autonomes Runbook fuer Claude Code
|   +-- UEBERNAHME.md         # rag_app Uebernahme-Planung
|-- telegram_bot.py            # A.AI Coach Telegram Bot v3
|-- rag_middleware.py           # RAG Middleware (Original)
|-- rag_client.py              # RAG Client Library
|-- extract_entities.py        # Entity-Extraktion fuer KG
|-- dspy_config.py             # DSPy Konfiguration
|-- eval_benchmark.json        # Evaluations-Benchmark
|-- locustfile.py              # Load Testing (Locust)
|-- backup.sh                  # Taegliches Backup Script
|-- 04-verify-system.sh        # System-Verifikation
+-- .github/workflows/ci.yml  # GitHub Actions CI
```

## Setup

Server: Hetzner CCX33, Ubuntu 22.04, Docker + Dify v1.13.0 + Ollama v0.17.7 + Neo4j 5.26.22 + Caddy v2

## Sicherheitshinweise

- API-Keys gehoeren in `.env`, NICHT in den Code (siehe TODOS.md)
- `.env` und `*.db` sind per `.gitignore` ausgeschlossen
- Telegram Token und Mem0 Keys muessen aus dem Code entfernt werden

---
**Version:** 3.0.0 | **Lizenz:** Privat | **Repository:** https://github.com/dsactivi-2/RAGbyDify
