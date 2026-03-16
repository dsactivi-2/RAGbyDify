# Cloud Code Team - Technischer Stack

Stand: 16.03.2026

## Server-Infrastruktur
- Hetzner CCX33: 8 vCPU Dedicated, 32 GB RAM, 240 GB SSD
- IP: 178.104.51.123
- OS: Ubuntu 22.04 LTS
- Firewall: UFW + DOCKER-USER iptables Chain (15 DROP-Regeln)
- Intrusion Detection: fail2ban aktiv

## Ollama (v0.17.7)
Laeuft LOKAL auf dem Server als systemd Service (ollama.service, enabled/active).
Bindet auf 0.0.0.0:11434. Docker-Container erreichen Ollama ueber docker0 Bridge IP 172.17.0.1:11434.
Ollama Cloud API Key konfiguriert in /etc/systemd/system/ollama.service (Environment Variable).

### Cloud-Modelle (0 GB lokal, via Ollama Cloud geroutet)
| Modell | Tier | Agents | Benchmark-Latenz |
|--------|------|--------|-----------------|
| qwen3-coder-next:cloud | Tier 1 Code | Coder, DevOps, Tester | ~0.7s |
| deepseek-v3.2:cloud | Tier 2 Reasoning | Architect, Security, Reviewer, Debug | ~2.2s |
| minimax-m2.5:cloud | Tier 3 General | Coach, Planner, Docs, Worker | ~1.3s |
| minimax-m2.5:cloud | Tier 4 Memory | Memory | ~1.3s |
| glm-4.7:cloud | Verfuegbar (Reserve) | - | ~4s |
| glm-5:cloud | Verfuegbar (Reserve) | - | nicht getestet |

### Lokale Modelle (auf dem Server gespeichert)
| Modell | Groesse | Zweck |
|--------|---------|-------|
| qwen3-embedding:latest | 4.7 GB | Primaeres Embedding fuer KB + Mem0 (4096 Dim.) |
| qwen3-embedding:0.6b | 639 MB | Alternatives kleines Embedding |
| nomic-embed-text:latest | 274 MB | Alternatives Embedding (768 Dim., fuer kuenftiges Speed-Upgrade) |

### DeepSeek v3.2 Quirk
DeepSeek v3.2 liefert Antwortinhalt im `thinking` Feld statt im `response` Feld.
Fix in main.py: `answer = data.get("response", "") or data.get("thinking", "")`

## Docker Services (17 Container)
| Container | Status | Ports | Zweck |
|-----------|--------|-------|-------|
| docker-api-1 | Running | 5001/tcp | Dify API |
| docker-worker-1 | Running | 5001/tcp | Dify Worker |
| docker-worker_beat-1 | Running | 5001/tcp | Dify Beat |
| docker-web-1 | Running | 3000/tcp | Dify Frontend |
| docker-db_postgres-1 | Running (healthy) | 5432/tcp | Dify PostgreSQL |
| docker-redis-1 | Running (healthy) | 6379/tcp | Dify Redis |
| docker-qdrant-1 | Running | 6333-6334/tcp (intern) | Dify Qdrant |
| docker-sandbox-1 | Running (healthy) | - | Dify Sandbox |
| docker-nginx-1 | Running | 3080→80, 3443→443 | Dify Nginx |
| docker-ssrf_proxy-1 | Running | 3128/tcp | SSRF Proxy |
| docker-plugin_daemon-1 | Running | 5003→5003 | Dify Plugin Daemon |
| cct-mem0 | Running (healthy) | 8002→8002 | Mem0 Lokal Server |
| cct-mem0-qdrant | Running (healthy) | 16333→6333, 16334→6334 | Mem0 Qdrant |
| cct-agent-watcher | Running | - | Agent Health Monitor |
| neo4j | Running | 127.0.0.1:7474→7474, 127.0.0.1:7687→7687 | Knowledge Graph |
| mem0_ui | Running | 3000→3000 | Mem0 Dashboard |
| openmemory-mem0_store-1 | Running | 26333→6333 | OpenMemory Qdrant |

## Reverse Proxy
- Caddy v2 mit automatischem SSL (caddy.service, enabled/active)
- HSTS + Security-Headers konfiguriert
- Domain: difyv2.activi.io via Cloudflare DNS

## systemd Services
| Service | Status | Port | Beschreibung |
|---------|--------|------|-------------|
| ollama.service | enabled/active | 11434 | Ollama LLM/Embedding + Cloud API Key |
| orchestrator.service | enabled/active | 8000 | FastAPI Orchestrator v3.0 (EnvironmentFile=.env) |
| hipporag.service | enabled/active | 8001 | HippoRAG Knowledge Graph Service |
| neo4j.service | enabled/inactive* | 7474, 7687 | Neo4j Docker Container (systemd) |
| caddy.service | enabled/active | 80, 443 | Reverse Proxy mit SSL |
| aai-coach-telegram.service | enabled/active | - | A.AI Coach Telegram Bot v3 |

*neo4j.service ist enabled und startet beim naechsten Reboot automatisch. Aktuell laeuft Neo4j noch via docker-compose.

### orchestrator.service Details
- Nutzt EnvironmentFile=/opt/cloud-code/orchestrator/.env (alle 20 Keys)
- ExecStart: /usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
- Restart=on-failure, RestartSec=5

### hipporag.service Details
- Environment direkt im Service: NEO4J_URI, NEO4J_PASSWORD, HIPPORAG_HOP_DEPTH
- ExecStart: /usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001

### neo4j.service Details
- Docker-basiert: docker run --rm --name neo4j mit APOC Plugin
- Volumes: /opt/cloud-code/neo4j/data + /logs
- Memory: heap 1g-2g

## Orchestrator v3.0 (main.py, 1317 Zeilen)
- FastAPI + Uvicorn auf Port 8000
- .env Datei mit allen Secrets (/opt/cloud-code/orchestrator/.env, 20 Eintraege)
- dotenv Laden: `from dotenv import load_dotenv; load_dotenv()`
- 4-Tier AGENT_MODEL_CONFIG (Ollama Cloud)
- OpenRouter Fallback (FALLBACK_MODELS Mapping)
- _call_llm_direct(): Ollama Cloud first, OpenRouter second
- Langfuse v4 Tracing (_lf_trace() via api.ingestion.batch())
- Streaming-Modus (Workaround fuer Dify Answer-Node Bug)
- 17 Hook-Endpoints mit Prompt-Templates
- Self-Learning Pipeline (/feedback, /learning/stats)
- Auto-Routing (/route) mit Keyword-Matching
- Core Memory System (SQLite)
- HippoRAG Integration
- RAG Middleware Integration
- Memory Own+Shared Trennung

## RAG Middleware (rag_middleware.py + hybrid_retriever.py)
- Zentrales Modul fuer ALLE Agent-Anfragen
- KB Retrieval: Dify Knowledge Base (semantisch, Top-K=5)
- HippoRAG: Knowledge Graph Beziehungen (Top-K=5)
- Mem0: Dual-Search (OWN cct-{agent} + SHARED cloud-code-team)
- Core Memory: System-Variablen + Agent-Memories (SQLite)
- Anti-Halluzination: Automatische Regelinjection

## Knowledge Graph
- Neo4j 5.26.22 Community Edition (Docker, localhost-only)
- HippoRAG Microservice auf Port 8001 (systemd)
- 44 Graph-Nodes, 57 Relationships
- Endpoints: /health, /knowledge/add, /knowledge/query, /knowledge/bulk

## Memory System
- **Mem0 Lokal** (Port 8002, Docker: cct-mem0)
  - Vector Store: cct-mem0-qdrant (Port 16333)
  - Graph Store: Neo4j (Port 7687)
  - LLM: glm-4.7:cloud (fuer Entity/Relation Extraction) — TODO: auf minimax-m2.5 umstellen
  - Collection: mem0_memories (80+ Vektoren, 4096 Dim.)
  - Knowledge Graph: Graph=true (Entity + Relation + Contradiction Detection)
  - Namespaces pro Agent: cct-architect, cct-coder, etc.
  - Shared Namespace: cloud-code-team
- **Core Memory DB:** /opt/cloud-code/core_memory.db (SQLite)
- **Recall Memory:** /opt/cloud-code/recall_memory.db (sqlite-vec)
- **User State:** /opt/cloud-code/data/user_state.json (Telegram Bot)

## Langfuse Tracing
- Version: Langfuse v4 (SDK langfuse 4.0.0)
- Backend: cloud.langfuse.com
- Integration: _lf_trace() in main.py via api.ingestion.batch()
- Traced: LLM Direct Calls + Dify Agent Calls
- Auth: auth_check() bei Startup
- Keys in .env (LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL)

## Dify Model Provider (Global Defaults)
- **Default LLM:** minimax-m2.5:cloud (Ollama) — umgestellt am 16.03.2026 von glm-4.7:cloud
- **Default Embedding:** qwen3-embedding:latest (Ollama, lokal)
- **TTS:** gpt-4o-mini-tts (OpenAI)
- **Speech2Text:** gpt-4o-mini-transcribe (OpenAI)
- Registrierte Modelle: minimax-m2.5:cloud, deepseek-v3.2:cloud, glm-4.7:cloud

## Installierte AI-SDKs (global via pip3, 57+ Pakete)
Highlights: llama-index 0.14.16 (23 Subpakete), langchain 1.2.12, langfuse 4.0.0, mem0ai 1.0.5, chainlit 2.10.0, openai 2.26.0, anthropic 0.85.0, fastembed 0.7.4, FlagEmbedding 1.3.5, sentence-transformers 5.3.0, qdrant-client 1.17.1, neo4j 5.28.3, ollama 0.6.1, httpx 0.27.2, fastapi 0.135.1, pydantic 2.12.5, python-telegram-bot 22.6, uvicorn 0.41.0

Keine venvs fuer Hauptanwendungen — alles global installiert.
Dify Plugins haben eigene isolierte venvs in /opt/dify/docker/volumes/plugin_daemon/.

## Sicherheit
- UFW Firewall aktiv (22, 80, 443 erlaubt + Docker-interne Routen)
- DOCKER-USER iptables Chain: 15 DROP-Regeln blockieren externe Zugriffe auf Ports 3000, 3080, 5003, 5432, 7474, 7687, 8000, 8001, 8765, 11434, 16333, 16334, 26333
- Regeln persistiert via /etc/iptables.rules + /etc/network/if-pre-up.d/iptables-restore
- Neo4j nur localhost
- Caddy mit HSTS
- fail2ban aktiv

## Backup
- Taegliches Backup um 03:00 via Cron (/opt/cloud-code/backup.sh)
- Retention: 7 Tage

## GitHub Repository
- URL: https://github.com/dsactivi-2/RAGbyDify
- Auth: SSH Key (ed25519)
- Branch: main

## Qdrant Collections (cct-mem0-qdrant, Port 16333)
| Collection | Dimension | Points | Zweck |
|-----------|-----------|--------|-------|
| mem0_memories | 4096 (Cosine) | 81 | Haupt-Memory (cct-mem0 Server) |
| mem0_mcp_selfhosted | 4096 (Cosine) | 0 | Mem0 MCP (Claude Desktop/Code) |
| mem0_test_graph | - | - | Test Collection |
| mem0migrations | - | - | Migration Tracking |
