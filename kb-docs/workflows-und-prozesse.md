# Cloud Code Team - Workflows und Prozesse

Stand: 16.03.2026

## Agent-Routing
Der Orchestrator v3.0 bietet mehrere Routing-Methoden:

### Direkter Aufruf
POST /task mit {"agent": "architect", "query": "..."} → Spezifischer Agent

### Agent-Kette
POST /chain mit {"agents": ["planner", "architect", "coder"], "query": "..."} → Sequentielle Kette, Output wird an naechsten Agent weitergereicht

### Auto-Routing
POST /route mit {"query": "..."} → Keyword-Matching routet automatisch zum besten Agent:
- architect: architektur, design, system, struktur, aufbau, komponente, pattern
- coder: code, programmier, implementier, funktion, klasse, script, python, javascript
- tester: test, qualitaet, qa, bug, fehler, assertion, unittest
- reviewer: review, pruef, bewert, best practice, code review, feedback
- devops: deploy, docker, ci/cd, pipeline, infrastruktur, server, kubernetes
- docs: dokumentation, readme, api-doc, beschreib, erklaere, anleitung
- security: sicherheit, security, audit, schwachstelle, vulnerability, firewall
- planner: plan, sprint, aufgabe, task, zeitplan, prioritaet, roadmap
- debug: debug, fehlersuche, traceback, exception, crash, log, diagnose
- worker: erledige, mach, ausfuehr, allgemein, hilf, unterstuetz
Fallback bei keinem Match: worker

### LLM Direct Aufruf (ohne Dify)
POST /llm/direct mit {"model": "deepseek-v3.2", "prompt": "...", "temperature": 0.3}
→ Direkter Ollama Cloud Aufruf, bei Fehler automatisch OpenRouter Fallback

### Konfiguration
GET /config/agents → Alle Agent-Konfigurationen inkl. Modell, Tier, Temperatur, Provider
GET /config/agent/{name} → Einzelne Agent-Konfiguration
GET /llm/health → Ollama Cloud Status + Liste verfuegbarer Modelle

## 4-Tier Model Routing (Orchestrator)

Der Orchestrator hat eine eigene Model-Zuweisung (AGENT_MODEL_CONFIG) fuer direkte LLM-Calls:

| Tier | Modell | Agents | Temp. |
|------|--------|--------|-------|
| Tier 1 Code | qwen3-coder-next | Coder, DevOps, Tester | 0.2-0.3 |
| Tier 2 Reasoning | deepseek-v3.2 | Architect, Security, Reviewer, Debug | 0.2-0.3 |
| Tier 3 General | minimax-m2.5 | Coach, Planner, Docs, Worker | 0.4-0.5 |
| Tier 4 Memory | minimax-m2.5 | Memory | 0.1 |

Bei Dify-Aufrufen (POST /task) nutzt Dify sein eigenes Default-Modell (minimax-m2.5:cloud).

## Chatflow-Architektur (Dify v2)
Jeder der 12 Agents folgt diesem Chatflow in Dify:
1. Start → Eingabe empfangen (~1s)
2. Memory abrufen (Mem0 Tool Call, ~12-15s)
3. KB durchsuchen (Knowledge Retrieval, ~0.3s)
4. LLM Anti-Halluzination Node mit minimax-m2.5:cloud (~6-16s)
5. Antwort (Answer Node, ~0.07s)
6. Memory speichern (Mem0 Tool Call, ~30s)

**Gesamtzeit:** ~47-59s pro Call (davon ~45s fuer Mem0-Operationen)
**LLM-only:** ~6-16s (minimax-m2.5:cloud, vorher ~100-115s mit glm-4.7:cloud)

## RAG Middleware Enrichment Flow
Jede Agent-Anfrage durchlaeuft die RAG Middleware:
1. **KB Retrieval** - Semantische Suche in Dify Knowledge Base (Top-K=5, Timeout=10s)
2. **HippoRAG Query** - Knowledge Graph Beziehungen aus Neo4j (Top-K=5)
3. **Mem0 Dual-Search** - Eigene Memories [OWN:cct-{agent}] + Shared [SHARED:cloud-code-team]
4. **Core Memory** - System-Variablen und Agent-spezifische Memories
5. **Anti-Halluzination** - Regelset wird in den Prompt injiziert
6. **Auto-Learn** - Neue Fakten aus User-Nachrichten automatisch speichern

## Memory Own+Shared Trennung

### Access Policy (OWN_PLUS_SHARED v1.0)
- READ: Jeder Agent liest EIGENE (cct-{agent}) + SHARED (cloud-code-team) Memories
- WRITE: Jeder Agent schreibt NUR in EIGENEN Scope (cct-{agent})
- SHARED: Nur via POST /memories/team mit source_agent Attribution

### Memory Endpoints
| Method | Endpoint | Beschreibung |
|--------|----------|-------------|
| GET | /memories/own/{agent} | Nur eigene Agent-Memories |
| GET | /memories/team | Shared Team-Memories |
| POST | /memories/team | Neues Team-Memory (kontrolliert) |
| GET | /memories/dual/{agent} | Merged: eigene + shared mit _scope |
| GET | /memories/policy | Aktuelle Policy anzeigen |

## 17 Hook-Endpoints
Vorkonfigurierte Workflows mit Prompt-Templates:
| Hook | Agent | Prompt-Template |
|------|-------|----------------|
| /save | worker | Speichere folgende Information: {query} |
| /recall | worker | Rufe aus deinem Memory ab: {query} |
| /status | planner | Gib einen aktuellen Statusbericht: {query} |
| /learn | worker | Lerne aus folgendem Feedback: {query} |
| /format | docs | Formatiere folgenden Text: {query} |
| /review | reviewer | Reviewe folgenden Code/Text: {query} |
| /test | tester | Erstelle Testfaelle fuer: {query} |
| /deploy | devops | Erstelle einen Deployment-Plan: {query} |
| /explain | docs | Erklaere verstaendlich: {query} |
| /refactor | coder | Refactore folgenden Code: {query} |
| /doc | docs | Erstelle Dokumentation fuer: {query} |
| /plan | planner | Erstelle einen Plan fuer: {query} |
| /debug | debug | Analysiere folgenden Fehler: {query} |
| /optimize | coder | Optimiere folgenden Code: {query} |
| /security | security | Fuehre eine Sicherheitsanalyse durch: {query} |
| /summarize | docs | Fasse zusammen: {query} |
| /fix | debug | Finde und behebe den Fehler: {query} |

## Self-Learning Pipeline
1. POST /feedback → Feedback (positiv/negativ) wird gesendet
2. Positiv: Verstaerkung in Mem0 (Namespace: cct-{agent})
3. Negativ: Fehler-Learning (Namespace: cct-errors) mit "NICHT WIEDERHOLEN"
4. Guard: Speichert NUR bei erfolgreicher Antwort (len > 20, kein _error Flag)
5. GET /learning/stats → Statistiken

## Error-Handling (Phase 0)
- Retry-Mechanismus: Max 2 Versuche bei leerer LLM-Antwort (<5 chars)
- Audit-Log: _audit_log(level, agent, message, query) fuer INFO/WARN/ERROR
- Telegram Alerts: Automatische Nachricht an Denis (Chat ID 8212488253) bei ERROR

## Langfuse Tracing
- Alle LLM-Direct-Calls werden getraced (_lf_trace in _call_llm_direct)
- Alle Dify-Agent-Calls werden getraced (_lf_trace in run_task/task endpoint)
- Trace-Daten: name, agent, model, input, output, metadata
- Dashboard: cloud.langfuse.com

## OpenRouter Fallback
Bei Ollama Cloud Ausfall wird automatisch auf OpenRouter umgeschaltet:
- qwen3-coder-next → qwen/qwen-2.5-coder-32b-instruct
- deepseek-v3.2 → deepseek/deepseek-chat
- minimax-m2.5 → deepseek/deepseek-chat
- glm-4.7 → deepseek/deepseek-chat
**Status:** Infrastruktur gebaut, OPENROUTER_API_KEY noch leer.

## systemd Services (Reboot-sicher)
Alle kritischen Dienste laufen als systemd Services:
| Service | Status | Methode |
|---------|--------|---------|
| orchestrator.service | enabled/active | EnvironmentFile=.env, uvicorn |
| hipporag.service | enabled/active | Environment direkt, uvicorn |
| neo4j.service | enabled/inactive* | Docker run, startet bei Reboot |
| ollama.service | enabled/active | System-Binary |
| caddy.service | enabled/active | System-Binary |
| aai-coach-telegram.service | enabled/active | Python Script |

*Neo4j laeuft aktuell via docker-compose. systemd uebernimmt beim naechsten Reboot.

## Bekannte Probleme
1. **Dify Answer-Node Bug:** Template {{#llm-main.text#}} wird nicht aufgeloest. Workaround: Streaming-Modus.
2. **Mem0 Bottleneck:** Memory-Operationen (abrufen + speichern) dauern ~45s pro Call. LLM ist schnell, Mem0 ist langsam.
3. **OpenRouter Fallback:** API-Key noch leer, Fallback daher nicht funktionsfaehig.
4. **Mem0 LLM:** Nutzt noch glm-4.7:cloud statt minimax-m2.5:cloud fuer Entity Extraction.

## Backup Workflow
- Taeglich um 03:00 via Cron
- Sichert: Dify DB, Neo4j, recall_memory.db, .env, Code
- Retention: 7 Tage
