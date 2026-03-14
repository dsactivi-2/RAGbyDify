# RAG-App Uebernahme-Planung fuer Cloud-Code-Team

Datum: 14.03.2026
Quelle: 4 analysierte Dokumente aus ~/rag_app (rag_app_report_v4.md, rag_app_scan_v4.py, claude_codex_runbook_rag_app.docx, rag_app_report_v4.json)

---

## 8 Uebernahme-Punkte

### Ue1: Document Lifecycle API-Design (Phase 9, Tasks 93-97)

**Quelle:** rag_app app/verify.py + app/server.py
**Konzept:** State-Machine fuer Dokument-Lebenszyklen:
staged -> promoted -> deprecated/superseded, mit reject als Sackgasse.
7 API-Routen: /stage/add, promote, reject, meta, deprecate, supersede, lifecycle.
**Aktion:** API-Design als Vorlage fuer Phase 9 MCP-Server nutzen, Code neu schreiben auf eigenem Stack.

### Ue2: Semantic Cache Pattern (Phase 5, neuer Task)

**Quelle:** rag_app app/cache.py (lookup_semantic_cache, store_semantic_cache)
**Konzept:** Bei aehnlichen wiederholten Fragen gecachte Antwort liefern statt LLM erneut aufzurufen. TTL-basiert.
**Aktion:** Neuer Task in Phase 5. Cache-Backend: Qdrant oder Redis.

### Ue3: Unified Search / Dual-Source Retrieval (Phase 6, neuer Task)

**Quelle:** rag_app app/unified_retriever.py (search_postgres_history, search_redis_knowledge, unified_search)
**Konzept:** Zwei Datenquellen parallel abfragen, Ergebnisse zusammenfuehren, deduplizieren, ranken.
**Aktion:** Neuer Task in Phase 6. Angepasst auf Qdrant (Vektoren) + Neo4j (Graph).

### Ue4: Query-mit-Lifecycle-Check (Phase 9, neuer Task Nr. 108)

**Quelle:** rag_app app/query.py (_exact_verify_meta)
**Konzept:** Vor Auslieferung einer Antwort pruefen ob das Quelldokument noch gueltig ist (nicht deprecated/rejected/superseded).
**Aktion:** Neuer Task in Phase 9, abhaengig von Ue1 (Lifecycle muss zuerst stehen).

### Ue5: Pydantic Request Models (Phase 9, Task 91)

**Quelle:** rag_app app/server.py (10 Pydantic-Klassen)
**Konzept:** Jeder API-Endpunkt hat ein eigenes Pydantic-Modell mit Validierung = sauberer API-Contract.
**Aktion:** Als Vorlage fuer MCP-Server Request/Response-Definitionen in Task 91.

### Ue6: Prioritaetenmatrix + Capability-Matrix (Phase 9, Task 98)

**Quelle:** claude_codex_runbook_rag_app.docx
**Konzept:** P1/P2/P3-Einteilung mit Status-Matrix (Bereich -> Gruen/Gelb -> Aktion).
**Aktion:** Als Template fuer Quality-Gate Agent in Phase 9.

### Ue7: Plan-vs-Code Verifikation (Phase 9, Task 98)

**Quelle:** rag_app_scan_v4.py (PHASE_RULES, Belegt/Vermutet/Nicht-belegbar)
**Konzept:** Automatisch pruefen ob dokumentierte Features im Code existieren.
**Aktion:** Konzept in Quality-Gate Agent einbauen. Code nicht uebernehmen (zu spezifisch).

### Ue8: Multi-LLM Routing-Logik (Phase 4, eventuell)

**Quelle:** rag_app .env (3 verschiedene LLM-Provider: Nebius, MiniMax, generisch)
**Konzept:** Automatisches Routing zwischen Modellen je nach Anfrage-Komplexitaet.
**Aktion:** Routing-Code in rag_app untersuchen. Nur uebernehmen wenn es echtes Auto-Routing gibt.

---

## Impact auf Projektphasen

| Phase | Aenderung | Was |
|-------|-----------|-----|
| Phase 4 | Eventuell | Ue8: Auto-Routing Task |
| Phase 5 | Neuer Task | Ue2: Semantic Cache Layer |
| Phase 6 | Neuer Task | Ue3: Unified Retriever |
| Phase 9 | Neuer Task | Ue4: Lifecycle-aware Query Filter (Nr. 108) |
| Phase 9 | Passt in existierende Tasks | Ue1, Ue5, Ue6, Ue7 |

Keine bestehenden Tasks muessen umgebaut werden. Nur 2-3 neue Tasks kommen dazu.
