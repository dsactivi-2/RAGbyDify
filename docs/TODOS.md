# Cloud Code Team - Offene Aufgaben

Stand: 15.03.2026

## Legende

- **P1** = Kritisch, blockiert Betrieb
- **P2** = Wichtig, vor naechstem Release
- **P3** = Nice-to-have, Haertung
- ✅ = Erledigt (Datum)

---

## Erledigt (2026-03-15)

### ✅ Mem0 Cloud → Lokal Migration
- Migration abgeschlossen: 7/9 Memories erfolgreich importiert
- 9 Vektoren in Qdrant (4096d, qwen3-embedding), 4 Agent-Entities
- Dify Plugin URL umgestellt: `api.mem0.ai` → `http://cct-mem0:8002`
- Deep-RAG Middleware umgestellt: `MEM0_API_URL` → `http://localhost:8002`
- Commits: `e5b70a6`, `ffb6172`, `f8167ce`, `925063a`

### ✅ Agent-Watcher Dify Login Fix
- Base64-Passwort-Encoding fuer Dify v1.13
- Infinite-Recursion in `get_apps()` behoben
- Redis Rate-Limit gecleart, Passwort in DB zurueckgesetzt
- Commit: `6b859b7`

### ✅ Mem0 Server Bugfixes
- `safe_get_all()` Workaround fuer `unhashable type: slice` Bug
- Stats/Entities/List-Endpoints repariert
- Commit: `ffb6172`

### ✅ 9 Workflow-Module deployed + verifiziert
- 22/22 Endpoints live und getestet (chain, smart-route, code, review, debug, security, docs, plan, deep-rag + Sub-Endpoints)
- Commits: vorherige Session (②-⑩)

### ✅ Telegram Bot konfiguriert
- Chat ID Arman (8747456067) gesetzt
- Agent-Watcher sendet Benachrichtigungen
- Testnachricht erfolgreich zugestellt
- Commit: `925063a`

### ✅ Deep-RAG health alle 3 Quellen gruen
- `MEM0_API_URL` auf `http://localhost:8002` umgestellt
- API Key Check entfernt (lokal braucht keinen)
- deep-rag/health: kb=true, mem0=true, hipporag=true
- Commit: `925063a`

### ✅ Dokumentation aktualisiert
- RUNBOOK.md Sektion 8: Mem0 Stack Operations
- TODOS.md: T23 OpenMemory Dashboard
- MEMORY.md: Cloud Code Team Projekt komplett
- config.yaml: Mem0 mode=local, URLs aktualisiert
- Commit: `b2d2d57`

---

## P1 - Kritisch

### T01: Hardcodierte API-Keys aus Code entfernen
- **Datei:** `telegram_bot.py` Zeile 21-22 (TELEGRAM_TOKEN, DIFY_API_KEY)
- **Datei:** `orchestrator/main.py` Zeile 394-396 (MEM0_API_KEY, MEM0_ORG_ID, MEM0_PROJECT_ID)
- **Risiko:** Keys sind im Git-Verlauf. Nach Fix: Keys rotieren.
- **Fix:** Alle Keys in `.env` verschieben, `os.getenv()` ohne Default-Wert nutzen
- **Hinweis:** Mem0 API Key (Cloud) wird nicht mehr benoetigt (lokal aktiv), aber andere Keys bleiben kritisch

### T02: OpenRouter-Bug untersuchen
- **Problem:** GPT-4o ueber OpenRouter liefert bei einigen Agents `null`-Antworten
- **Ursache:** Vermutlich Dify v1.13 Answer-Node Template-Bug in Kombination mit OpenRouter
- **Workaround existiert:** Streaming-Mode extrahiert LLM-Output aus `node_finished` Events
- **Aktion:** Testen ob der Bug mit Dify v1.14+ behoben ist

### T03: DIFY_KB_KEY korrekt setzen
- **Datei:** `rag_middleware.py` Zeile 38
- **Problem:** Default-Wert `REDACTED_DIFY_KB_KEY` ist ein Platzhalter
- **Aktion:** Echten Dataset-API-Key aus Dify Admin holen und in `.env` setzen
- **Hinweis:** KB-Key `dataset-WG3ca69737ZxjHdi4GFHEG28` existiert in config.yaml — ggf. bereits gesetzt?

### T04: IST vs SOLL Code synchronisieren
- **Problem:** `orchestrator/main.py` AGENT_MODEL_CONFIG zeigt SOLL (GLM-4.7, DeepSeek V3.2) aber Server laeuft mit IST (GPT-4o, MiniMax-M2.5)
- **Aktion:** Entweder Code auf IST korrigieren ODER Migration auf Open-Source-Stack durchfuehren
- **Entscheidung noetig:** Bleibt ihr bei GPT-4o oder migriert ihr?

---

## P2 - Wichtig

### T05: Telegram Bot Live-Test
- **Status:** Bot ist als systemd Service aktiv, Agent-Watcher sendet Alerts
- **Aktion:** Vollstaendiger E2E-Test: /start, /lang, Frage stellen, Memory pruefen
- **Erwartung:** Bot antwortet in gewaehlter Sprache mit RAG-angereichertem Kontext
- **Neu:** Denis Chat ID noch hinzufuegen (Denis muss `@A_AI_Couch_bot` anschreiben)

### T06: HippoRAG Health pruefen
- **Status:** deep-rag/health zeigt hipporag=true ✅
- **Endpoint:** GET /hipporag/health
- **Noch zu tun:** Pruefen ob Knowledge Graph ausreichend befuellt ist

### T07: Knowledge Base befuellen
- **Ordner:** `kb-docs/` (aktuell 3 Dateien)
- **Aktion:** Weitere Projekt-Dokumentation in die Dify KB hochladen
- **Ziel:** Agent-Antworten werden praeziser durch mehr Kontext

### T08: ~~Mem0 Cloud Verbindung pruefen~~ → Mem0 Lokal Haertung
- **Aktualisiert:** Cloud ist abgeloest, lokal ist aktiv
- **Aktion:** Mem0 Single-Worker Problem fixen (haengt bei langen Ollama-Calls)
- **Fix-Optionen:** uvicorn workers=2 ODER async-Verarbeitung der LLM-Calls
- **Workaround:** `docker restart cct-mem0` bei Timeout

### T09: Backup-Script testen
- **Datei:** `backup.sh`
- **Aktion:** Manuell ausfuehren, pruefen ob Backup vollstaendig ist
- **Erwartung:** Dify-Daten, SQLite DBs, Configs, Mem0 Qdrant-Daten werden gesichert
- **Neu:** Mem0 Volumes (mem0_qdrant_data) ins Backup aufnehmen

### T10: broad exceptions reduzieren
- **Dateien:** `rag_middleware.py` (5x bare except), `telegram_bot.py` (mehrere)
- **Aktion:** Spezifische Exception-Typen statt `except:` oder `except Exception`
- **Prioritaet:** Besonders in `health_check()` und `fetch_kb()`

### T23: OpenMemory Dashboard deployen (Self-Hosted Mem0 UI)
- **Quelle:** `mem0ai/mem0` GitHub Repo → OpenMemory Subprojekt
- **Stack:** React Frontend + MCP Backend, Docker-basiert
- **Ziel:** Ersatz fuer app.mem0.ai Cloud Dashboard (proprietaer, nicht self-hostbar)
- **Anbindung:**
  - Mem0 Server: `http://cct-mem0:8002` (bestehend, docker_default Netzwerk)
  - Qdrant: `http://cct-mem0-qdrant:6333` (Port 16333 extern)
  - Neo4j Graph: `bolt://neo4j:7687` (bestehend, DB: neo4j)
- **Features:**
  - Memory-Liste mit Entities, Content, Categories
  - Entities-Uebersicht (User + Agent Zuordnung)
  - Graph Memory Visualisierung (Neo4j Daten)
  - Stats: Total Memories, Requests, Add/Retrieval Events
- **Schritte:**
  1. OpenMemory Repo clonen und Architektur pruefen
  2. docker-compose.mem0.yml erweitern (neuer Service: openmemory-ui)
  3. Frontend konfigurieren: API URL auf lokalen Mem0 Server
  4. Neo4j Graph-Daten im Dashboard sichtbar machen
  5. Port festlegen (Vorschlag: 3030 oder 3001)
  6. Optional: Nginx Reverse Proxy fuer HTTPS
- **Abhaengigkeiten:** cct-mem0 (healthy), cct-mem0-qdrant (healthy), neo4j (running)
- **Runbook:** Sektion 8.5

---

## P3 - Haertung

### T11: Load Testing mit Locust
- **Datei:** `locustfile.py`
- **Aktion:** Locust ausfuehren, Orchestrator unter Last testen
- **Ziel:** Wie viele parallele Anfragen haelt der Server aus?

### T12: DSPy Evaluation erweitern
- **Dateien:** `dspy_config.py`, `eval_benchmark.json`
- **Aktion:** Benchmark-Fragen ausfuehren, Antwortqualitaet messen

### T13: Entity-Extraktion automatisieren
- **Datei:** `extract_entities.py`
- **Aktion:** In Pipeline einbauen — bei neuen KB-Docs automatisch Entities nach Neo4j

### T14: Dify Plugin v3 testen
- **Ordner:** `plugins/cloud-code-orchestrator/`
- **Aktion:** Plugin in Dify installieren, pruefen ob Tools funktionieren

### T15: Git-Verlauf bereinigen (API-Keys)
- **Problem:** Hardcodierte Keys in frueheren Commits sichtbar
- **Aktion:** `git filter-branch` oder `BFG Repo-Cleaner` nach T01
- **Danach:** ALLE betroffenen Keys rotieren

### T16: Logging vereinheitlichen
- **Problem:** Unterschiedliche Logger-Namen und Formate in den Dateien
- **Aktion:** Einheitliches Format, Log-Level konfigurierbar via ENV

### T17: Rollback-Mechanismus
- **Problem:** Kein automatischer Rollback bei fehlgeschlagenem Deploy
- **Aktion:** Rollback-Script oder systemd-Watchdog einrichten

### T24: Mem0 get_all() Bug richtig fixen
- **Problem:** `safe_get_all()` ist nur Workaround; qdrant-client 1.17 + Qdrant v1.12 hat Slice-Bug
- **Aktion:** qdrant-client Version pinnen oder scroll-Methode direkt aufrufen
- **Workaround aktiv:** `safe_get_all()` in server.py faengt TypeError ab

### T25: Telegram Gruppe als Alert-Ziel
- **Gruppe:** "D & A.AI Couch" (Chat ID: `-5101871155`)
- **Aktion:** Evaluieren ob Gruppe statt Einzelchat fuer Alerts genutzt werden soll
- **Vorteil:** Denis + Arman sehen beide die Alerts

### T26: config.yaml Inkonsistenzen bereinigen
- **Problem:** Einige Werte in config.yaml stimmen nicht mit IST ueberein:
  - `mem0.graph_database: "mem0"` → sollte `"neo4j"` sein (Community Edition)
  - `neo4j.password` → stimmt nicht mit docker-compose ueberein (`22e58741703f24f1913550c9a8a51c99`)
  - `neo4j.database: "cloudcode"` → sollte `"neo4j"` sein
  - `embedding.dimension: 1536` → Mem0 nutzt 4096 (qwen3-embedding)
- **Aktion:** config.yaml mit IST-Zustand synchronisieren

---

## Phase 9 - Docu-Blueprint-System (geplant)

### T18: MCP-Server fuer Phase 9 aufsetzen
### T19: Document Lifecycle API implementieren
### T20: Semantic Cache Layer
### T21: Unified Retriever fuer Qdrant + Neo4j
### T22: Lifecycle-aware Query Filter

---

## Zusammenfassung

| Prioritaet | Offen | Erledigt | Beschreibung |
|-----------|-------|----------|-------------|
| P1 | 4 | 0 | Kritisch (Security, Bugs) |
| P2 | 7 | 7 | Vor naechstem Release |
| P3 | 10 | 0 | Haertung |
| Phase 9 | 5 | 0 | Neue Features |
| **Gesamt** | **26** | **7** | |
