# Cloud Code Team - Offene Aufgaben

Stand: 17.03.2026 (Session 6)

## Legende
- **P0** = Notfall, Datenverlust
- **P1** = Kritisch, blockiert Betrieb
- **P2** = Wichtig, vor naechstem Release
- **P3** = Nice-to-have, Haertung

---

## P0 - NOTFALL (Session 7: alle behoben ✅)

### T-SYS05: Mem0 Datenverlust — 0 von 81 Memories (NEU Session 6)
- **Problem:** mem0_memories Qdrant Collection hat 0 Punkte. Vorher 81 Memories.
- **Entdeckt:** 17.03.2026, Live-Abfrage bestaetigt: `points_count: 0`
- **Collection Config:** Existiert noch mit 4096d Cosine, aber alle Vektoren weg
- **Moegliche Ursache:** Mem0 Container Restart + Embedding-Modell-Wechsel (Session 5: glm-4.7 → minimax-m2.5) hat evtl. Re-Index getriggert der fehlschlug
- **Auswirkung:** Kein Agent hat Memory. Self-Learning, Cross-Read, Dual-Write — alles leer.
- **Aktion:**
  1. Qdrant Snapshots pruefen (`/collections/mem0_memories/snapshots`)
  2. JSON-Fallback Dossiers pruefen (`/opt/cloud-code/orchestrator/dossiers/`)
  3. Backup vom 16.03 pruefen (`/opt/cloud-code/backups/`)
  4. Wenn Backup vorhanden: Qdrant Snapshot wiederherstellen
  5. Wenn kein Backup: Memories aus JSON-Dossiers + Logs rekonstruieren

### T-SYS06: HippoRAG API gibt 0 Hits zurueck (NEU Session 6)
- **Problem:** REST API auf :8001 gibt 0 Ergebnisse, aber Neo4j Cypher findet 15 Treffer
- **Health:** HippoRAG meldet "healthy" mit 44 Nodes, 57 Relationships
- **Auswirkung:** RAG Middleware bekommt keine HippoRAG-Daten trotz vorhandener Graph-Daten
- **Aktion:** HippoRAG API-Layer debuggen — Embedding oder Query-Transformation pruefen

---

## P1 - Kritisch

### ~~T-SYS03~~: RAG-Bottleneck — ERLEDIGT (Session 7)
- **Status:** ✅ DONE — Intent Classifier in enrich_for_agent() integriert
- **Fix:** classify_intent() wird jetzt aufgerufen; triviale Anfragen (Greetings, Smalltalk) skippen ALLE RAG-Quellen (0ms)
- **Commit:** 83859d5 (2026-03-17)

### T-SYS04: Dify Answer-Node Template-Bug
- **Problem:** {{#llm-main.text#}} wird nicht aufgeloest
- **Workaround:** Streaming + node_finished Event Extraktion im Orchestrator
- **Dauerhafte Loesung:** Dify v1.14+ testen oder Answer-Node Config aendern

### ~~T-SYS07~~: Orchestrator 1 Worker — ERLEDIGT (Session 7)
- **Status:** ✅ DONE — 4 gunicorn + UvicornWorker
- **Fix:** uvicorn --workers 1 → gunicorn -w 4 -k uvicorn.workers.UvicornWorker
- **Timeout:** 120s (Dify), graceful-timeout 30s
- **Commit:** eeb80c2 (2026-03-17)`systemctl restart orchestrator`

---

## P2 - Wichtig

### T05: Telegram Bot Live-Test
- **Status:** Bot als systemd Service aktiv, Agent-Watcher sendet Alerts
- **Aktion:** Vollstaendiger E2E-Test

### T07: Knowledge Base befuellen
- **Ordner:** kb-docs/ (aktuell 3 Dateien)
- **Aktion:** Weitere Projekt-Dokumentation in Dify KB hochladen

### T08: Mem0 Single-Worker Problem
- **Problem:** Mem0 haengt bei langen Ollama-Calls
- **Fix:** uvicorn workers=2 ODER async-Verarbeitung

### T09: Backup-Script testen + Mem0 Volumes aufnehmen

### T23: OpenMemory Dashboard deployen (mem0_ui laeuft bereits auf Port 3000)

### T-DOC01: MEMORY.md (i-know-all Skill) auf Session 5+6 Stand bringen (NEU)
- **Problem:** Referenziert noch glm-4.7, 80 Memories, kein OpenRouter
- **Aktion:** Session 5+6 Entscheidungen, Fixes, neue Issues eintragen

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
### T27: qwen3-embedding:0.6b noch auf Server (sollte geloescht sein, 639MB) (NEU)

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

## ERLEDIGT

### Session 6 (17.03.2026)
- [x] 5 HTML-Architektur-Dokumente erstellt (RAG-Architektur, Komponentenregister, Agent-Memory-Matrix, Memory-Architektur, Memory-Konstrukt Letta-Style)
- [x] Alle 19 Komponenten mit IDs dokumentiert (N01-N19)
- [x] Intent Classifier Code geschrieben und in rag_middleware.py angehaengt (nicht verdrahtet)
- [x] Architektur-Entscheidung: Option D (Agentic RAG) statt Option A (Intent Classifier)
- [x] Recherche: Anthropic Routing Pattern, Claude Agent SDK, Agentic RAG Patterns

### Session 5 (17.03.2026)
- [x] T-SYS02: OpenRouter API-Key gesetzt, Fallback aktiv
- [x] T-P201: Mem0 LLM von glm-4.7:cloud auf minimax-m2.5:cloud
- [x] cct-mem0 CPU von 11.3% auf 0.63% reduziert
- [x] Neo4j RAM von 1.6GB auf 562MB (Heap 256m-512m, PageCache 256m)
- [x] DIFY_KB_ID + DIFY_KB_KEY in .env gesetzt (RAG KB Health Fix)
- [x] mem0_test_graph Qdrant Collection geloescht
- [x] T01: telegram_bot.py Keys bereits os.environ.get()
- [x] Alle 6 Server-Docs LIVE-verifiziert
- [x] 12 Supermemory Eintraege gespeichert

### Session 4b (16.03.2026)
- [x] Ollama Cloud Migration + 4-Tier Routing (5 Cloud-Modelle)
- [x] 12 Dify Agent API-Keys aus PostgreSQL extrahiert, .env erstellt
- [x] Langfuse v4 Tracing implementiert
- [x] Namespace Fix (workflows/ → cct_workflows/)
- [x] Dify Default LLM auf minimax-m2.5:cloud (16x schneller)
- [x] Security Hardening: 15 iptables DROP-Regeln
- [x] systemd Services: orchestrator, hipporag, neo4j
- [x] 4 Utility Scripts erstellt
- [x] Chainlit 2.10.0 + 57 AI-Pakete installiert
- [x] 6 Dokumentationen komplett neu geschrieben

### Fruehere Sessions
- [x] Phase 0: Error-Handling (Retry), Audit-Log (Telegram), Memory-Save Guard
- [x] Dual-Write Pattern (Mem0 + JSON)
- [x] Doctor Agent Self-Healing Layer
- [x] Mem0 Cloud → Lokal Migration (9 Vektoren)
- [x] Agent-Watcher + Telegram Bot
- [x] 22/22 Workflow-Endpoints
- [x] Knowledge Graph aktiviert (44 Nodes, 57 Rels)
- [x] Memory Own+Shared Trennung (5 API-Endpoints)
- [x] Core Memory (38 sys_vars + 48 agent_memory)
- [x] Self-Learning (auto_learn bei jedem /task)
- [x] Cross-Read (/memories/shared, /memories/{agent})
- [x] 8 SDKs installiert (fastembed, qdrant-client, mem0ai, ragas, cachetools, 3x llama-index-readers)
- [x] mem0-mcp-selfhosted fuer Claude Desktop/Code
- [x] SSH-Tunnel Script + LaunchAgent Autostart
- [x] OpenMemory Dashboard deployed

---

## Zusammenfassung

| Prioritaet | Offen | Erledigt | Beschreibung |
|-----------|-------|----------|-------------|
| P0 | 0 | 2 | Notfall behoben (Mem0 re-geseedet, HippoRAG Term-Split Fix) |
| P1 | 1 | 6 | T-SYS04 (Answer-Node Dify Bug, Workaround aktiv) |
| P2 | 6 | 1 | Vor naechstem Release |
| P3 | 10 | 0 | Haertung |
| PRIO 1 Memory | 3.5 | 0.5 | Memory Upgrade U1-U4 |
| Phase 9 | 5 | 0 | Neue Features |
| Erledigt | - | 55+ | Sessions 1-6 |
