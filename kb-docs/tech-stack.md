# Cloud Code Team - Technischer Stack

## Server-Infrastruktur
- Hetzner CCX33: 8 vCPU Dedicated, 32 GB RAM, 240 GB SSD
- IP: 178.104.51.123
- OS: Ubuntu 22.04 LTS
- Firewall: UFW (Ports 22, 80, 443)
- Intrusion Detection: fail2ban aktiv

## Docker Services (12 Container)
- Dify API, Worker, Web, Sandbox
- PostgreSQL (Dify DB)
- Redis (Cache + Celery Broker)
- Qdrant (Vector Store)
- Weaviate (optional)
- Nginx (internal)
- Celery Worker (1 Worker)

## Reverse Proxy
- Caddy v2 mit automatischem SSL
- HSTS + Security-Headers konfiguriert
- Domain: difyv2.activi.io via Cloudflare DNS

## LLM-Modelle (3-Tier Open Source Stack via Ollama Cloud)
Alle Modelle laufen über Ollama Cloud auf dem Server (0.0.0.0:11434).
Docker-Container erreichen Ollama über docker0 Bridge IP 172.17.0.1:11434.

### Tier 1 - Code: MiniMax-M2.5
- Agents: Architect (0.3), Coder (0.2), DevOps (0.3), Tester (0.2)
- Spezialisierung: Code-Generierung, Architektur, technische Aufgaben

### Tier 2 - Multilingual: GLM-4.7
- Agents: Planner (0.4), Docs (0.4), Worker (0.5), Reviewer (0.3), Security (0.2), Debug (0.3), Coach (0.5)
- Spezialisierung: Mehrsprachig, Planung, Reviews, Dokumentation

### Tier 3 - Günstig: DeepSeek V3.2
- Agents: Memory (0.1)
- Spezialisierung: Memory-Operationen, Kontextgedächtnis

### Embedding: Qwen3-Embedding-8B
- Lokal installiert via Ollama
- 4096 Dimensionen
- Für Knowledge Base Retrieval in Dify

## Orchestrator v3.0
- FastAPI + Uvicorn auf Port 8000
- Streaming-Modus (Workaround für Dify Answer-Node Bug)
- systemd Service mit Auto-Restart
- AGENT_MODEL_CONFIG: 3-Tier Zuordnung
- Endpoints: /health, /task, /chain, /config/agents, /route, /memory/*, /hipporag/*

## Knowledge Graph
- Neo4j 5 Community Edition (localhost-only)
- APOC Plugin installiert
- HippoRAG Microservice auf Port 8001 (systemd)

## Memory System
- Mem0 Cloud API (v0.0.2 Plugin in Dify)
- 11 Agent-Namespaces: cct-architect, cct-coder, etc.
- Cross-Session Memory funktioniert
- Core Memory DB: /opt/cloud-code/core_memory.db (SQLite)

## Dify Model Provider
- **Ollama:** minimax-m2.5:cloud, glm-4.7:cloud, deepseek-v3.2:cloud, qwen3-embedding:latest
- **OpenRouter:** 95 vordefinierte Modelle (Fallback, aktiv)
- **OpenAI:** API Key konfiguriert (Fallback)

## Backup
- Tägliches Backup um 03:00 via Cron
- Script: /opt/cloud-code/backup.sh
