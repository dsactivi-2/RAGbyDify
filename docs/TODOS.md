# Cloud Code Team - Offene Aufgaben

Stand: 16.03.2026

## Legende
- **P1** = Kritisch, blockiert Betrieb
- **P2** = Wichtig, vor naechstem Release
- **P3** = Nice-to-have, Haertung

---

## ERLEDIGT (Session 4b — 16.03.2026)

### Ollama Cloud Migration + 4-Tier Routing
- [x] Ollama Cloud API Key konfiguriert (ollama.service Environment)
- [x] 5 Cloud-Modelle verfuegbar: deepseek-v3.2, minimax-m2.5, glm-4.7, glm-5, qwen3-coder-next
- [x] 4-Tier AGENT_MODEL_CONFIG implementiert (Tier 1-4 basierend auf Benchmarks)
- [x] _call_llm_direct() mit Ollama Cloud first, OpenRouter Fallback
- [x] /llm/direct und /llm/health Endpoints
- [x] DeepSeek v3.2 Quirk gefixt (thinking → response Feld)

### Dify Agent Keys Extraktion
- [x] Alle 12 Agent API-Keys aus Dify PostgreSQL extrahiert
- [x] .env Datei erstellt mit allen Keys (22 Eintraege)
- [x] dotenv Laden in main.py integriert

### Langfuse v4 Tracing
- [x] Langfuse SDK installiert und konfiguriert
- [x] _lf_trace() Helper mit v4 api.ingestion.batch() API
- [x] Traces fuer LLM Direct + Dify Agent Calls
- [x] /langfuse/health Endpoint
- [x] Auth-Check bei Startup, atexit flush

### Namespace Fix
- [x] workflows/ umbenannt zu cct_workflows/ (Namespace-Kollision mit llama-index-workflows)
- [x] Import in main.py aktualisiert: from cct_workflows.doctor_agent import ...

### Dify Default LLM
- [x] Default LLM von glm-4.7:cloud auf minimax-m2.5:cloud umgestellt
- [x] LLM-Call von ~100-115s auf ~6-16s beschleunigt (16x schneller)

### Security Hardening
- [x] DOCKER-USER iptables Chain: 15 DROP-Regeln (13 Ports blockiert)
- [x] Regeln persistiert (/etc/iptables.rules + if-pre-up.d/iptables-restore)
- [x] UFW Regeln erweitert

### HippoRAG
- [x] HippoRAG manuell gestartet (war down)
- [x] 44 Nodes, 57 Relationships in Neo4j

### systemd Services (T-SYS01 ERLEDIGT)
- [x] orchestrator.service repariert mit EnvironmentFile=/opt/cloud-code/orchestrator/.env
- [x] hipporag.service repariert und aktiv via systemd
- [x] neo4j.service erstellt (Docker-basiert, enabled fuer Reboot)
- [x] Alle 3 Services von manuellen nohup-Prozessen auf systemd umgestellt
- [x] orchestrator.service: enabled/active (PID via systemd)
- [x] hipporag.service: enabled/active (PID via systemd)

### Utility Scripts
- [x] 01-scan-sdks.sh erstellt (SDK Scanner)
- [x] 02-setup-neo4j-systemd.sh erstellt (Neo4j systemd Setup)
- [x] 03-chainlit-hybrid-test.py erstellt (Chainlit Hybrid Retrieval)
- [x] 04-install-missing.sh erstellt (Missing Package Installer)

### SDK Installation
- [x] Chainlit 2.10.0 installiert
- [x] 57+ AI-Pakete global installiert (inkl. LlamaIndex 0.14.16, 23 Subpakete)

### Dokumentation
- [x] README.md komplett neu geschrieben (4-Tier, Langfuse, .env, cct_workflows, systemd)
- [x] tech-stack.md aktualisiert (systemd active, 15 iptables rules, SDKs)
- [x] projektbeschreibung.md aktualisiert (systemd, Chainlit, SDKs)
- [x] workflows-und-prozesse.md aktualisiert (systemd active, Probleme korrigiert)
- [x] RUNBOOK.md komplett neu geschrieben (systemd Restart, Utility Scripts)
- [x] TODOS.md aktualisiert (T-SYS01 erledigt)

---

## ERLEDIGT (Fruehere Sessions)

### Phase 0: Error-Handling + Audit-Log + Memory-Guard
- [x] Retry-Mechanismus (max 2 Versuche) in _call_agent_with_full_rag()
- [x] Audit-Log mit Telegram Alerts bei ERROR
- [x] Memory-Save Guard (nur bei erfolgreicher Antwort)

### Mem0 Cloud → Lokal Migration
- [x] 9 Vektoren in Qdrant, Dify Plugin + Middleware umgestellt

### Agent-Watcher + Telegram Bot
- [x] Agent-Watcher aktiv, Telegram Bot konfiguriert

### 9 Workflow-Module
- [x] 22/22 Endpoints live und getestet

### SDK Installation (frueher)
- [x] 8 SDKs auf Server: fastembed, qdrant-client, mem0ai, ragas, cachetools, 3x llama-index-readers

### Knowledge Graph Aktivierung
- [x] Graph=true auf Server + lokal (Claude Desktop MCP)
- [x] Entity + Relation + Contradiction Detection aktiv

### Memory Own+Shared Trennung
- [x] 5 neue API-Endpoints (/memories/own, /team, /dual, /policy, /shared)
- [x] Write-Isolation: Self-Learning nur in cct-{agent}
- [x] Dual-Search in RAG Middleware

---

## P1 - Kritisch

### T-SYS02: OpenRouter API-Key setzen
- **Problem:** OPENROUTER_API_KEY in .env ist leer
- **Auswirkung:** Bei Ollama Cloud Ausfall kein Fallback moeglich
- **Aktion:** Key bei openrouter.ai generieren, in .env eintragen

### T-SYS03: Mem0 Dify-Bottleneck optimieren
- **Problem:** Mem0 Tool Calls im Dify Chatflow dauern ~45s (12-15s abrufen + 30s speichern)
- **Auswirkung:** Gesamte Dify-Antwortzeit ~47-59s trotz schnellem LLM (6-16s)
- **Optionen:**
  1. Memory speichern async machen (Antwort sofort, Speichern im Hintergrund) → -30s
  2. Memory nur bei bestimmten Agents (Coder/Tester brauchen kein Langzeitgedaechtnis)
  3. Memory auf Orchestrator-Ebene (statt Dify Tool-Call)

### T-SYS04: Dify Answer-Node Template-Bug
- **Problem:** {{#llm-main.text#}} wird nicht aufgeloest
- **Workaround:** Streaming + node_finished Event Extraktion im Orchestrator
- **Dauerhafte Loesung:** Dify v1.14+ testen oder Answer-Node Config aendern

### T01: Hardcodierte API-Keys aus Code entfernen
- **Datei:** telegram_bot.py (TELEGRAM_TOKEN, DIFY_API_KEY)
- **Risiko:** Keys im Git-Verlauf. Nach Fix: Keys rotieren.

---

## P2 - Wichtig

### T-P201: Mem0 LLM aktualisieren
- **Problem:** Mem0 Server (:8002) nutzt noch glm-4.7:cloud als LLM fuer Entity Extraction
- **Aktion:** Mem0 Config auf minimax-m2.5:cloud umstellen (schneller)

### T05: Telegram Bot Live-Test
- **Status:** Bot als systemd Service aktiv, Agent-Watcher sendet Alerts
- **Aktion:** Vollstaendiger E2E-Test

### T07: Knowledge Base befuellen
- **Ordner:** kb-docs/ (aktuell 3 Dateien, jetzt aktualisiert)
- **Aktion:** Weitere Projekt-Dokumentation in Dify KB hochladen

### T08: Mem0 Single-Worker Problem
- **Problem:** Mem0 haengt bei langen Ollama-Calls
- **Fix:** uvicorn workers=2 ODER async-Verarbeitung

### T09: Backup-Script testen + Mem0 Volumes aufnehmen

### T23: OpenMemory Dashboard deployen (mem0_ui laeuft bereits auf Port 3000)

---

## P3 - Haertung

### T10: broad exceptions in rag_middleware.py und telegram_bot.py reduzieren
### T11: Load Testing mit Locust
### T13: Entity-Extraktion automatisieren (extract_entities.py in Pipeline)
### T15: Git-Verlauf bereinigen (API-Keys in frueheren Commits)
### T16: Logging vereinheitlichen
### T17: Rollback-Mechanismus (automatisch bei fehlgeschlagenem Deploy)
### T24: Mem0 get_all() Bug richtig fixen (qdrant-client Slice-Bug)
### T25: Telegram Gruppe als Alert-Ziel evaluieren
### T26: config.yaml Inkonsistenzen bereinigen

---

## PRIO 1: Memory System Upgrade (Supermemory-Niveau)

### U1: SPEED — Semantic Search 60s -> <500ms
- Embedding-Wechsel: qwen3-embedding (4096d) → nomic-embed-text (768d)
- Neue Qdrant Collection: mem0_v2 (768d)
- Parallele Agent-Queries: asyncio.gather()
- Embedding-Cache: LRU, 5min TTL, max 500
- SDKs bereit: fastembed, AsyncQdrantClient

### U2: AUTO-DECAY — Veraltete Memories vergessen (teilweise erledigt)
- [x] Contradiction Detection (Graph=true, Mem0 v1.0.5)
- [x] Entity/Relation Extraction (3 LLM-Calls pro Memory)
- [ ] Decay-Score + Cron (Payload, Formel, naechtlicher Sweep)
- [ ] Telegram-Report nach Sweep

### U3: CONNECTORS — GitHub/Notion/Gmail Sync
- POST /ingest Endpoint
- LlamaIndex Readers installiert (llama-index-readers-github, -google, -notion)

### U4: BENCHMARKS — Memory-Qualitaet messen
- 50 Eval-Paare, Recall@5, MRR, Latenz
- ragas SDK installiert

---

## Phase 9 - Docu-Blueprint-System (geplant)

### T18: MCP-Server aufsetzen
### T19: Document Lifecycle API
### T20: Semantic Cache Layer
### T21: Unified Retriever
### T22: Lifecycle-aware Query Filter

---

## Zusammenfassung

| Prioritaet | Offen | Erledigt | Beschreibung |
|-----------|-------|----------|-------------|
| P1 | 4 | 1 | Kritisch (OpenRouter, Mem0-Bottleneck, Answer-Node, Keys) |
| P2 | 5 | 0 | Vor naechstem Release |
| P3 | 9 | 0 | Haertung |
| PRIO 1 Memory | 3.5 | 0.5 | Memory Upgrade U1-U4 |
| Phase 9 | 5 | 0 | Neue Features |
| Erledigt S4b | - | 30+ | Ollama Cloud, 4-Tier, Langfuse, Security, systemd, Scripts, Docs |
| Erledigt frueher | - | 25+ | Mem0 Migration, Workflows, SDKs, Graph, etc. |
