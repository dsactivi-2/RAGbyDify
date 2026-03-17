# Cloud Code Team

KI-Multi-Agent-System basierend auf Dify v1.13.0 (Self-Hosted) mit 12 spezialisierten Agents, koordiniert ueber einen FastAPI Orchestrator v3.0.

## Aktueller Stand (16.03.2026)

| Komponente | Status |
|---|---|
| **LLM-Routing** | 4-Tier via Ollama Cloud (kein Anthropic/OpenAI noetig) |
| **Dify Default LLM** | minimax-m2.5:cloud (umgestellt von glm-4.7:cloud) |
| **Langfuse Tracing** | Aktiv (cloud.langfuse.com) |
| **OpenRouter Fallback** | Infrastruktur gebaut, API-Key noch leer |
| **Security** | UFW + DOCKER-USER iptables Hardening |
| **systemd Services** | orchestrator, hipporag, neo4j, ollama, caddy — alle enabled |

## 4-Tier Open Source Model Stack (Ollama Cloud)

| Tier | Modell | Latenz | Agents |
|------|--------|--------|--------|
| Tier 1 Code | qwen3-coder-next:cloud | ~0.7s | Coder, DevOps, Tester |
| Tier 2 Reasoning | deepseek-v3.2:cloud | ~2.2s | Architect, Security, Reviewer, Debug |
| Tier 3 General | minimax-m2.5:cloud | ~1.3s | Coach, Planner, Docs, Worker |
| Tier 4 Memory | minimax-m2.5:cloud | ~1.3s | Memory |

**Embedding:** qwen3-embedding:latest (4096 Dim., lokal auf Ollama, 4.7 GB)

## Phasen-Status

| Phase | Beschreibung | Status |
|-------|-------------|--------|
| Phase 0 | Error-Handling + Audit-Log + Memory-Guard | 100% |
| Phase 1 | Grundinfrastruktur (Dify, Docker, Caddy) | 100% |
| Phase 2 | 12 Agents + Orchestrator | 100% |
| Phase 3 | RAG Middleware + Anti-Halluzination | 100% |
| Phase 4 | LLM Integration + 4-Tier Routing | 95% (OpenRouter-Key fehlt) |
| Phase 5 | RAG Query + Retrieval | 71% |
| Phase 6 | Knowledge Graph + Multi-Source | 75% |
| Phase 7 | Orchestrator Erweiterung | 70% |
| Phase 8 | Telegram Bot + API | 90% |
| Phase 9 | Docu-Blueprint-System | 0% (geplant) |

## Architektur

- **Server:** Hetzner CCX33 (8 vCPU, 32 GB RAM) — 178.104.51.123
- **Domain:** difyv2.activi.io (Caddy v2 SSL + HSTS)
- **Orchestrator:** FastAPI v3.0 (Port 8000, 1317 Zeilen main.py, systemd)
- **LLM:** Ollama v0.17.7 Cloud (5 Cloud-Modelle + 2 lokale Embedding-Modelle)
- **Ollama API Key:** Konfiguriert in ollama.service Environment
- **RAG Middleware:** KB + HippoRAG + Mem0 + Anti-Halluzination Enrichment
- **Knowledge Graph:** Neo4j 5.26.22 + HippoRAG (Port 8001, systemd)
- **Memory:** Mem0 Lokal (Port 8002) + Core Memory (SQLite) + Per-User Memory (JSON)
- **Vektoren:** Qdrant (Dify Docker + cct-mem0-qdrant auf Port 16333)
- **Tracing:** Langfuse v4 (cloud.langfuse.com)
- **Telegram Bot:** A.AI Coach v3 (systemd Service)
- **Chainlit:** v2.10.0 (installiert fuer Hybrid Retrieval Testing)

## 12 Agents

| Nr | Agent | Aufgabe | Modell | Tier |
|----|-------|---------|--------|------|
| 1 | Coder | Code-Generierung | qwen3-coder-next:cloud | Tier 1 |
| 2 | DevOps | Deployment, Infrastruktur | qwen3-coder-next:cloud | Tier 1 |
| 3 | Tester | Tests, QA | qwen3-coder-next:cloud | Tier 1 |
| 4 | Architect | System-Design, Architektur | deepseek-v3.2:cloud | Tier 2 |
| 5 | Security | Sicherheitsanalyse | deepseek-v3.2:cloud | Tier 2 |
| 6 | Reviewer | Code Reviews | deepseek-v3.2:cloud | Tier 2 |
| 7 | Debug | Fehlersuche | deepseek-v3.2:cloud | Tier 2 |
| 8 | Coach | Telegram Bot Coach | minimax-m2.5:cloud | Tier 3 |
| 9 | Planner | Planung, Sprints | minimax-m2.5:cloud | Tier 3 |
| 10 | Docs | Dokumentation | minimax-m2.5:cloud | Tier 3 |
| 11 | Worker | Allgemeine Aufgaben | minimax-m2.5:cloud | Tier 3 |
| 12 | Memory | Kontextgedaechtnis | minimax-m2.5:cloud | Tier 4 |

## API Endpoints

### Core
| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /health | System-Status |
| POST | /task | Einzelner Agent-Aufruf |
| POST | /chain | Agent-Kette (sequentiell) |
| POST | /route | Auto-Routing per Keyword-Match |

### LLM Direct (Ollama Cloud + OpenRouter Fallback)
| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| POST | /llm/direct | Direkter LLM-Aufruf (Ollama Cloud, Fallback OpenRouter) |
| GET | /llm/health | Ollama Cloud Status + verfuegbare Modelle |

### Memory (Own + Shared Trennung)
| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /memories/own/{agent} | Nur eigene Agent-Memories (cct-{agent}) |
| GET | /memories/team | Shared Team-Memories (cloud-code-team) |
| POST | /memories/team | Neues Team-Memory schreiben |
| GET | /memories/dual/{agent} | Merged: eigene + shared mit _scope Label |
| GET | /memories/policy | Aktuelle Memory-Access-Policy |
| GET | /memories/shared | Legacy: alle Agent-Scopes |
| GET/PUT/DELETE | /memory/system | System-Variablen (Core Memory) |
| GET/PUT | /memory/agent/{agent} | Agent-spezifische Memories |
| GET | /memory/context | Vollstaendiger Kontext |

### RAG + Knowledge Graph
| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /rag/health | RAG + Memory Health Check |
| GET | /hipporag/health | HippoRAG Status |
| POST | /hipporag/query | Knowledge Graph Query |

### Tracing + Monitoring
| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /langfuse/health | Langfuse Tracing Status |
| POST | /feedback | Feedback verarbeiten |
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
|   |-- main.py               # FastAPI Orchestrator v3.0 (1317 Zeilen)
|   |-- .env                   # Alle Keys (20 Eintraege)
|   +-- cct_workflows/         # Workflow-Module (umbenannt von workflows/)
|       |-- auto_doc.py, chain.py, code_gen.py, debug_pipeline.py
|       |-- deep_rag.py, doctor_agent.py, planning.py
|       +-- review_qa.py, routing.py, security_scan.py
|-- hipporag/
|   +-- main.py               # HippoRAG Service (Neo4j, systemd)
|-- mem0-local/
|   |-- docker-compose.mem0.yml
|   |-- mem0-server/           # Mem0 Lokal Server (Port 8002)
|   +-- agent-watcher/         # Dify Agent Health Monitor
|-- kb-docs/
|   |-- projektbeschreibung.md
|   |-- tech-stack.md
|   +-- workflows-und-prozesse.md
|-- scripts/
|   |-- 01-scan-sdks.sh        # SDK Scanner (pip, venvs, Docker)
|   |-- 02-setup-neo4j-systemd.sh  # Neo4j systemd Setup
|   |-- 03-chainlit-hybrid-test.py  # Chainlit Hybrid Retrieval Test
|   +-- 04-install-missing.sh  # Missing Package Installer
|-- plugins/
|   +-- cloud-code-orchestrator/  # Dify Plugin v3.0.0
|-- docs/
|   |-- TODOS.md              # Alle offenen Aufgaben
|   |-- RUNBOOK.md            # Autonomes Runbook
|   +-- UEBERNAHME.md         # rag_app Uebernahme-Planung
|-- telegram_bot.py            # A.AI Coach Telegram Bot v3
|-- rag_middleware.py           # RAG Middleware (Original)
|-- backup.sh                  # Taegliches Backup Script
+-- .github/workflows/ci.yml  # GitHub Actions CI
|-- extract_entities.py      # Entity-Extraktion fuer Neo4j
|-- locustfile.py             # Load Testing
|-- rag_client.py             # RAG Client Library
|-- 04-verify-system.sh       # System-Verifikation
```

## systemd Services

| Service | Status | Port | Beschreibung |
|---------|--------|------|-------------|
| ollama.service | enabled/active | 11434 | Ollama LLM + Cloud API Key |
| orchestrator.service | enabled/active | 8000 | FastAPI Orchestrator (EnvironmentFile) |
| hipporag.service | enabled/active | 8001 | HippoRAG Knowledge Graph |
| neo4j.service | enabled/inactive* | 7474, 7687 | Neo4j Docker (startet bei Reboot) |
| caddy.service | enabled/active | 80, 443 | Reverse Proxy mit SSL |
| aai-coach-telegram.service | enabled/active | - | Telegram Bot |

*neo4j.service ist enabled aber aktuell inactive, da Neo4j noch via docker-compose laeuft. Beim naechsten Reboot uebernimmt systemd.

## Environment-Konfiguration

Alle Secrets in `/opt/cloud-code/orchestrator/.env` (20 Eintraege):
- 12 Dify Agent API-Keys (AGENT_{ROLE}_KEY)
- DIFY_API_URL
- OLLAMA_CLOUD_URL
- OPENROUTER_API_KEY (leer)
- TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
- LANGFUSE_SECRET_KEY + LANGFUSE_PUBLIC_KEY + LANGFUSE_BASE_URL

## Sicherheit

- UFW Firewall aktiv (SSH, HTTP, HTTPS erlaubt)
- DOCKER-USER iptables Chain: 15 DROP-Regeln blockieren externe Zugriffe
- Persistiert via /etc/iptables.rules + if-pre-up.d Script
- Neo4j nur localhost (127.0.0.1)
- Caddy mit HSTS + Security Headers
- fail2ban aktiv

## Installierte AI-SDKs (global, 57+ Pakete)

Highlights: llama-index 0.14.16 (23 Subpackages), langchain 1.2.12, langfuse 4.0.0, mem0ai 1.0.5, chainlit 2.10.0, openai 2.26.0, anthropic 0.85.0, fastembed 0.7.4, FlagEmbedding 1.3.5, sentence-transformers 5.3.0, qdrant-client 1.17.1, neo4j 5.28.3

---
**Version:** 3.0.0 | **Stand:** 16.03.2026 | **Repository:** https://github.com/dsactivi-2/RAGbyDify
