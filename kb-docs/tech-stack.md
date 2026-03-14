# Cloud Code Team - Technischer Stack

## Server-Infrastruktur
- Hetzner CCX33: 8 vCPU Dedicated, 32 GB RAM, 240 GB SSD
- IP: 178.104.51.123
- OS: Ubuntu 22.04 LTS
- Firewall: UFW (Ports 22, 80, 443)
- Intrusion Detection: fail2ban aktiv

## Ollama (v0.17.7)
Läuft LOKAL auf dem Server als systemd Service (ollama.service, enabled).
Bindet auf 0.0.0.0:11434. Docker-Container erreichen Ollama über docker0 Bridge IP 172.17.0.1:11434.

### Lokale Modelle (auf dem Server gespeichert)
| Modell | Größe | Zweck |
|--------|-------|-------|
| qwen3-embedding:latest | 4.36 GB | Primäres Embedding für KB Retrieval (4096 Dim.) |
| qwen3-embedding:0.6b | 639 MB | Alternatives kleines Embedding |
| nomic-embed-text:latest | 274 MB | Alternatives Embedding |

### Cloud-Modelle (0 GB lokal, via Ollama Cloud geroutet)
| Modell | Größe lokal | Tier | Agents |
|--------|-------------|------|--------|
| minimax-m2.5:cloud | 0 GB | Tier 1 Code | Architect, Coder, DevOps, Tester |
| glm-4.7:cloud | 0 GB | Tier 2 Multilingual | Coach, Planner, Docs, Worker, Reviewer, Security, Debug |
| deepseek-v3.2:cloud | 0 GB | Tier 3 Günstig | Memory |

## Docker Services (11 Container aktiv)
| Container | Status | Ports |
|-----------|--------|-------|
| docker-api-1 | Running | 5001/tcp |
| docker-worker-1 | Running | 5001/tcp |
| docker-worker_beat-1 | Running | 5001/tcp |
| docker-web-1 | Running | 3000/tcp |
| docker-db_postgres-1 | Running (healthy) | 5432/tcp |
| docker-redis-1 | Running (healthy) | 6379/tcp |
| docker-qdrant-1 | Running | 6333-6334/tcp |
| docker-sandbox-1 | Running (healthy) | - |
| docker-nginx-1 | Running | 3080→80, 3443→443 |
| docker-ssrf_proxy-1 | Running | 3128/tcp |
| docker-plugin_daemon-1 | Running | 5003/tcp |

Hinweis: Weaviate ist NICHT aktiv (war als optional konfiguriert).

## Reverse Proxy
- Caddy v2 mit automatischem SSL (caddy.service, enabled)
- HSTS + Security-Headers konfiguriert
- Domain: difyv2.activi.io via Cloudflare DNS
- caddy-api.service existiert aber ist deaktiviert

## systemd Services
| Service | Status | Port | Beschreibung |
|---------|--------|------|-------------|
| orchestrator.service | enabled/active | 8000 | FastAPI Orchestrator v3.0 |
| hipporag.service | enabled/active | 8001 | HippoRAG Knowledge Graph Service |
| ollama.service | enabled/active | 11434 | Ollama LLM/Embedding Service |
| caddy.service | enabled/active | 80, 443 | Reverse Proxy mit SSL |
| aai-coach-telegram.service | enabled/active | - | A.AI Coach Telegram Bot v3 |
| neo4j (Docker) | running | 7474, 7687 (localhost) | Knowledge Graph DB |

## Orchestrator v3.0 (main.py, 697 Zeilen)
- FastAPI + Uvicorn auf Port 8000
- Streaming-Modus (Workaround für Dify Answer-Node Bug)
- systemd Service mit Auto-Restart
- AGENT_MODEL_CONFIG: 3-Tier Zuordnung für 12 Agents
- EMBEDDING_CONFIG: qwen3-embedding-8b, provider: ollama-local, 4096 Dim.
- 17 Hook-Endpoints mit vordefinierten Prompt-Templates
- Self-Learning Pipeline (/feedback, /learning/stats)
- Auto-Routing (/route) mit Keyword-Matching
- Core Memory System (SQLite)
- HippoRAG Integration (Knowledge Graph Enrichment)
- RAG Middleware Integration (enrich_for_agent + auto_learn)
- API Endpoints: /health, /task, /chain, /config/agents, /config/agent/{name}, /route, /hooks, /{hook_name}, /feedback, /learning/stats, /memory/system, /memory/agent/{agent}, /memory/context, /hipporag/health, /hipporag/query, /rag/health

## RAG Middleware (rag_middleware.py)
- Zentrales Modul für ALLE Agent-Anfragen
- KB Retrieval: Dify Knowledge Base (semantisch, Top-K=5, Timeout=10s)
- HippoRAG: Knowledge Graph Beziehungen (Top-K=5)
- User Memory: Persistente JSON-Dateien pro User
- Core Memory: System-Variablen + Agent-Memories aus SQLite
- Anti-Halluzination: Automatische Regelinjection
- Auto-Learn: Automatisches Speichern neuer Fakten aus User-Nachrichten
- KB ID: REDACTED_DIFY_KB_ID

## Knowledge Graph
- Neo4j 5.26.22 Community Edition (Docker Container, localhost-only)
- APOC Plugin installiert
- Indizes auf Entity.name und Entity.type
- HippoRAG Microservice auf Port 8001 (FastAPI, systemd)
- Endpoints: /health, /knowledge/add, /knowledge/query, /knowledge/bulk

## Memory System
- **Mem0 Cloud API** (v0.0.2 Plugin in Dify)
  - Org: REDACTED_MEM0_ORG_ID
  - Projekt: REDACTED_MEM0_PROJECT_ID
  - Namespaces pro Agent: cct-architect, cct-coder, cct-tester, cct-reviewer, cct-devops, cct-docs, cct-security, cct-planner, cct-debug, cct-worker, cct-coach
  - Error-Namespace: cct-errors (Self-Learning)
  - Cross-Session Memory funktioniert
- **Core Memory DB:** /opt/cloud-code/core_memory.db (SQLite)
  - system_vars Tabelle: Projekt-Config, Regeln
  - agent_memory Tabelle: Pro-Agent Key-Value Paare
- **Recall Memory:** /opt/cloud-code/recall_memory.db (sqlite-vec)
- **User State:** /opt/cloud-code/data/user_state.json (Telegram Bot)
- **User Memories:** /opt/cloud-code/data/memories/ (Pro-User JSON)

## Telegram Bot (A.AI Coach v3)
- telegram_bot.py (32.300 Bytes)
- Multilingual: EN/DE/BS mit per-User Spracheinstellung
- Streaming mit Dify Coach Chatflow
- Nutzt RAG Middleware (KB + HippoRAG + Memory)
- systemd Service: aai-coach-telegram.service (aktiv)
- Dify API: http://localhost:3080/v1 (intern via Nginx)
- Coach Agent API-Key: REDACTED_DIFY_API_KEY

## Dify Model Provider (Global Defaults)
- **Default LLM:** glm-4.7:cloud (Ollama)
- **Default Embedding:** qwen3-embedding:latest (Ollama, lokal)
- **TTS:** gpt-4o-mini-tts (OpenAI, kein Ollama-Equivalent)
- **Speech2Text:** gpt-4o-mini-transcribe (OpenAI, kein Ollama-Equivalent)
- Verfügbare Provider: Ollama (primär), OpenRouter (95 Modelle, Fallback), OpenAI (Fallback)

## Dify Apps (23 total)
- 12 aktive v2 Agents (advanced-chat): Architect, Coder, Tester, Reviewer, DevOps, Docs, Security, Planner, Debug, Worker, Coach, Memory
- 1 RAG App (advanced-chat): Cloud Code Team RAG
- 10 Legacy v1 Apps (chat): Alte Versionen, können gelöscht werden

## Weitere Tools und Scripts
| Datei | Zweck |
|-------|-------|
| rag_client.py | RAG Client Library |
| extract_entities.py | Entity-Extraktion für Knowledge Graph |
| locustfile.py | Load Testing (Locust) |
| dspy_config.py / dspy_config.json | DSPy Konfiguration |
| eval_benchmark.json | Evaluations-Benchmark |
| 04-verify-system.sh | System-Verifikation Script |
| backup.sh | Tägliches Backup (03:00 Cron) |

## Dify Plugin
- cloud-code-orchestrator Plugin v3.0.0
- manifest.yaml, provider/cloud_code.yaml
- Tools für Multi-Agent Orchestrierung

## Backup
- Tägliches Backup um 03:00 via Cron (/opt/cloud-code/backup.sh)
- Sichert: Dify DB (pg_dump), Neo4j, recall_memory.db, Dify .env, Orchestrator+HippoRAG Code
- Retention: 7 Tage
- Backup-Verzeichnis: /opt/cloud-code/backups/

## GitHub Repository
- URL: https://github.com/dsactivi-2/RAGbyDify
- Auth: SSH Key (ed25519)
- Branch: main
