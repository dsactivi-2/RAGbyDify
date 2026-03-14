# Cloud Code Team - Offene Aufgaben

Stand: 14.03.2026

## Legende

- **P1** = Kritisch, blockiert Betrieb
- **P2** = Wichtig, vor naechstem Release
- **P3** = Nice-to-have, Haertung

---

## P1 - Kritisch

### T01: Hardcodierte API-Keys aus Code entfernen
- **Datei:** `telegram_bot.py` Zeile 21-22 (TELEGRAM_TOKEN, DIFY_API_KEY)
- **Datei:** `orchestrator/main.py` Zeile 394-396 (MEM0_API_KEY, MEM0_ORG_ID, MEM0_PROJECT_ID)
- **Risiko:** Keys sind im Git-Verlauf. Nach Fix: Keys rotieren.
- **Fix:** Alle Keys in `.env` verschieben, `os.getenv()` ohne Default-Wert nutzen

### T02: OpenRouter-Bug untersuchen
- **Problem:** GPT-4o ueber OpenRouter liefert bei einigen Agents `null`-Antworten
- **Ursache:** Vermutlich Dify v1.13 Answer-Node Template-Bug in Kombination mit OpenRouter
- **Workaround existiert:** Streaming-Mode extrahiert LLM-Output aus `node_finished` Events
- **Aktion:** Testen ob der Bug mit Dify v1.14+ behoben ist

### T03: DIFY_KB_KEY korrekt setzen
- **Datei:** `rag_middleware.py` Zeile 38
- **Problem:** Default-Wert `REDACTED_DIFY_KB_KEY` ist ein Platzhalter
- **Aktion:** Echten Dataset-API-Key aus Dify Admin holen und in `.env` setzen

### T04: IST vs SOLL Code synchronisieren
- **Problem:** `orchestrator/main.py` AGENT_MODEL_CONFIG zeigt SOLL (GLM-4.7, DeepSeek V3.2) aber Server laeuft mit IST (GPT-4o, MiniMax-M2.5)
- **Aktion:** Entweder Code auf IST korrigieren ODER Migration auf Open-Source-Stack durchfuehren
- **Entscheidung noetig:** Bleibt ihr bei GPT-4o oder migriert ihr?

---

## P2 - Wichtig

### T05: Telegram Bot Live-Test
- **Status:** Bot ist als systemd Service aktiv
- **Aktion:** Vollstaendiger E2E-Test: /start, /lang, Frage stellen, Memory pruefen
- **Erwartung:** Bot antwortet in gewaehlter Sprache mit RAG-angereichertem Kontext

### T06: HippoRAG Health pruefen
- **Endpoint:** GET /hipporag/health
- **Aktion:** Pruefen ob Neo4j laeuft und der Knowledge Graph Daten enthaelt
- **Bei Fehler:** Neo4j Container Status pruefen, Ports 7474/7687

### T07: Knowledge Base befuellen
- **Ordner:** `kb-docs/` (aktuell 3 Dateien)
- **Aktion:** Weitere Projekt-Dokumentation in die Dify KB hochladen
- **Ziel:** Agent-Antworten werden praeziser durch mehr Kontext

### T08: Mem0 Cloud Verbindung pruefen
- **Endpoint:** POST /feedback
- **Aktion:** Positives + negatives Feedback senden, pruefen ob Mem0 speichert
- **Fallback:** Bei Ausfall auf lokales Memory (SQLite) umstellen

### T09: Backup-Script testen
- **Datei:** `backup.sh`
- **Aktion:** Manuell ausfuehren, pruefen ob Backup vollstaendig ist
- **Erwartung:** Dify-Daten, SQLite DBs, Configs werden gesichert

### T10: broad exceptions reduzieren
- **Dateien:** `rag_middleware.py` (5x bare except), `telegram_bot.py` (mehrere)
- **Aktion:** Spezifische Exception-Typen statt `except:` oder `except Exception`
- **Prioritaet:** Besonders in `health_check()` und `fetch_kb()`

---

## P3 - Haertung

### T11: Load Testing mit Locust
- **Datei:** `locustfile.py`
- **Aktion:** Locust ausfuehren, Orchestrator unter Last testen
- **Ziel:** Wie viele parallele Anfragen haelt der Server aus?

### T12: DSPy Evaluation erweitern
- **Dateien:** `dspy_config.py`, `eval_benchmark.json`
- **Aktion:** Benchmark-Fragen ausfuehren, Antwortqualitaet messen
- **Ziel:** Baseline fuer Antwortqualitaet vor/nach Aenderungen

### T13: Entity-Extraktion automatisieren
- **Datei:** `extract_entities.py`
- **Aktion:** In Pipeline einbauen — bei neuen KB-Docs automatisch Entities nach Neo4j

### T14: Dify Plugin v3 testen
- **Ordner:** `plugins/cloud-code-orchestrator/`
- **Aktion:** Plugin in Dify installieren, pruefen ob Tools funktionieren
- **Tools:** ask_agent, get_memory, set_memory, query_knowledge

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

---

## Phase 9 - Docu-Blueprint-System (geplant)

### T18: MCP-Server fuer Phase 9 aufsetzen
- **Referenz:** Projektplan Task Nr. 91
- **Aktion:** MCP-Server-Skeleton erstellen, API-Design definieren

### T19: Document Lifecycle API implementieren
- **Referenz:** Projektplan Task Nr. 93, Uebernahme-Punkt Ue1
- **Vorlage:** rag_app verify.py (stage/promote/reject/deprecate/supersede)
- **Aktion:** Lifecycle-Routen in MCP-Server integrieren

### T20: Semantic Cache Layer
- **Referenz:** Uebernahme-Punkt Ue2 (aus rag_app cache.py)
- **Phase:** 5 (RAG Query)
- **Aktion:** Cache fuer wiederholte aehnliche Anfragen

### T21: Unified Retriever fuer Qdrant + Neo4j
- **Referenz:** Uebernahme-Punkt Ue3 (aus rag_app unified_retriever.py)
- **Phase:** 6 (Knowledge Graph)
- **Aktion:** Parallele Abfrage beider Backends mit Ergebnis-Merge

### T22: Lifecycle-aware Query Filter
- **Referenz:** Uebernahme-Punkt Ue4 (aus rag_app query.py _exact_verify_meta)
- **Phase:** 9
- **Aktion:** Deprecated/rejected Dokumente aus RAG-Ergebnissen ausfiltern

---

## Zusammenfassung

| Prioritaet | Offen | Beschreibung |
|-----------|-------|-------------|
| P1 | 4 | Kritisch (Security, Bugs) |
| P2 | 6 | Vor naechstem Release |
| P3 | 7 | Haertung |
| Phase 9 | 5 | Neue Features |
| **Gesamt** | **22** | |
