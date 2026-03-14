# Cloud Code Team

KI-Multi-Agent-System basierend auf Dify v1.13 (Self-Hosted) mit 12 spezialisierten Agents, koordiniert über einen FastAPI Orchestrator v3.0.

## 3-Tier Open Source Model Stack

Alle Modelle laufen über **Ollama Cloud** (docker0 bridge 172.17.0.1:11434).

| Tier | Modell | Agents | Spezialisierung |
|------|--------|--------|-----------------|
| **Tier 1 - Code** | MiniMax-M2.5 | Architect, Coder, DevOps, Tester | Code-Generierung, Architektur |
| **Tier 2 - Multilingual** | GLM-4.7 | Planner, Docs, Worker, Reviewer, Security, Debug, Coach | Planung, Reviews, Dokumentation |
| **Tier 3 - Günstig** | DeepSeek V3.2 | Memory | Kontextgedächtnis |
| **Embedding** | Qwen3-Embedding-8B | — | KB Retrieval (4096 Dim., lokal) |

## Architektur

- **Plattform:** Dify v1.13.0 Self-Hosted auf Hetzner CCX33 (8 vCPU, 32 GB RAM)
- **Domain:** difyv2.activi.io (Caddy SSL + HSTS)
- **Orchestrator:** FastAPI v3.0 Streaming (Port 8000)
- **Knowledge Graph:** Neo4j 5 + HippoRAG (Port 8001)
- **Memory:** Mem0 Cloud API + Core Memory SQLite
- **Vektoren:** Qdrant (Dify Docker)
- **Embedding:** Qwen3-Embedding-8B (lokal Ollama)

## 12 Agents

| # | Agent | Tier | Modell | Temp |
|---|-------|------|--------|------|
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
1. **Start** → Eingabe empfangen
2. **Parallel:** Mem0 Retrieve + Knowledge Base Retrieval
3. **LLM** Anti-Halluzination Node (tier-spezifisches Modell)
4. **Answer** + Mem0 Save (parallel)

## API Endpoints

```
GET  /health              → System-Status
POST /task                → Einzelner Agent-Aufruf
POST /chain               → Agent-Kette
GET  /config/agents       → Agent-Konfigurationen
POST /route               → Auto-Routing
POST /memory/*            → Memory-Operationen
POST /hipporag/*          → Knowledge Graph
```

## Projektstruktur

```
/opt/cloud-code/
├── orchestrator/main.py      # FastAPI Orchestrator v3.0
├── kb-docs/                  # Knowledge Base Dokumente
│   ├── projektbeschreibung.md
│   ├── tech-stack.md
│   └── workflows-und-prozesse.md
├── plugins/                  # Dify Plugin
│   └── cloud-code-orchestrator/
├── telegram_bot.py           # Telegram Bot
├── rag_client.py             # RAG Client
├── rag_middleware.py         # RAG Middleware
├── hipporag/main.py          # HippoRAG Service
├── core_memory.db            # Core Memory (SQLite)
└── recall_memory.db          # Recall Memory (sqlite-vec)
```

## Setup

Server: Hetzner CCX33, Ubuntu 22.04, Docker + Dify + Ollama Cloud + Neo4j + Caddy

---
**Version:** 3.0.0 | **Lizenz:** Privat
