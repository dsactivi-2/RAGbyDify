# Cloud Code Team - Workflows und Prozesse

## Agent-Routing
Der Orchestrator v3.0 bietet mehrere Routing-Methoden:

### Direkter Aufruf
POST /task mit {"agent": "architect", "query": "..."} → Spezifischer Agent

### Agent-Kette
POST /chain mit {"agents": ["planner", "architect", "coder"], "query": "..."} → Sequentielle Kette, Output wird an nächsten Agent weitergereicht

### Auto-Routing
POST /route mit {"query": "..."} → Keyword-Matching routet automatisch zum besten Agent:
- architect: architektur, design, system, struktur, aufbau, komponente, pattern
- coder: code, programmier, implementier, funktion, klasse, script, python, javascript
- tester: test, qualität, qa, bug, fehler, assertion, unittest
- reviewer: review, prüf, bewert, best practice, code review, feedback
- devops: deploy, docker, ci/cd, pipeline, infrastruktur, server, kubernetes
- docs: dokumentation, readme, api-doc, beschreib, erkläre, anleitung
- security: sicherheit, security, audit, schwachstelle, vulnerability, firewall
- planner: plan, sprint, aufgabe, task, zeitplan, priorität, roadmap
- debug: debug, fehlersuche, traceback, exception, crash, log, diagnose
- worker: erledige, mach, ausführ, allgemein, hilf, unterstütz
Fallback bei keinem Match: worker

### Konfiguration
GET /config/agents → Alle Agent-Konfigurationen inkl. Modell, Tier, Temperatur, Provider
GET /config/agent/{name} → Einzelne Agent-Konfiguration

## Chatflow-Architektur (v2)
Jeder der 12 Agents folgt diesem Chatflow in Dify:
1. Start → Eingabe empfangen
2. Parallel: Mem0 Retrieve + Knowledge Base Retrieval (Cloud Code Team KB)
3. LLM Anti-Halluzination Node mit tier-spezifischem Modell:
   - Tier 1 Code-Agents (Architect, Coder, DevOps, Tester): minimax-m2.5:cloud
   - Tier 2 Multilingual-Agents (Planner, Docs, Worker, Reviewer, Security, Debug, Coach): glm-4.7:cloud
   - Tier 3 Memory-Agent: deepseek-v3.2:cloud
4. Answer Node + Mem0 Save (parallel)

## Dify Parameter-Konfiguration (Ollama Cloud)
Bei Ollama Cloud Modellen in Dify müssen Parameter über Checkboxen aktiviert werden:
- Temperature: Per Checkbox aktiviert (blau = aktiv, grau = inaktiv)
- Num Predict: Auf 8192 gesetzt und per Checkbox aktiviert (alle Agents)
- Andere Parameter (Top P, Top K, etc.): Nicht aktiviert, Ollama-Defaults gelten

## RAG Middleware Enrichment Flow
Jede Agent-Anfrage durchläuft die RAG Middleware (rag_middleware.py):
1. **KB Retrieval** - Semantische Suche in Dify Knowledge Base (Top-K=5, Timeout=10s)
2. **HippoRAG Query** - Knowledge Graph Beziehungen aus Neo4j (Top-K=5)
3. **User Memory** - Persistente Fakten pro User laden
4. **Core Memory** - System-Variablen und Agent-spezifische Memories
5. **Anti-Halluzination** - Regelset wird in den Prompt injiziert
6. **Auto-Learn** - Neue Fakten aus User-Nachrichten automatisch speichern
Ergebnis: Angereicherter Query wird an Dify Chatflow gesendet

## 17 Hook-Endpoints
Vorkonfigurierte Workflows mit Prompt-Templates:
| Hook | Agent | Prompt-Template |
|------|-------|----------------|
| /save | worker | Speichere folgende Information in deinem Memory: {query} |
| /recall | worker | Rufe aus deinem Memory ab: {query} |
| /status | planner | Gib einen aktuellen Statusbericht: {query} |
| /learn | worker | Lerne aus folgendem Feedback und speichere es: {query} |
| /format | docs | Formatiere folgenden Text professionell: {query} |
| /review | reviewer | Reviewe folgenden Code oder Text: {query} |
| /test | tester | Erstelle Testfaelle fuer: {query} |
| /deploy | devops | Erstelle einen Deployment-Plan fuer: {query} |
| /explain | docs | Erklaere verstaendlich: {query} |
| /refactor | coder | Refactore folgenden Code: {query} |
| /doc | docs | Erstelle Dokumentation fuer: {query} |
| /plan | planner | Erstelle einen Plan fuer: {query} |
| /debug | debug | Analysiere folgenden Fehler: {query} |
| /optimize | coder | Optimiere folgenden Code: {query} |
| /security | security | Fuehre eine Sicherheitsanalyse durch: {query} |
| /summarize | docs | Fasse zusammen: {query} |
| /fix | debug | Finde und behebe den Fehler in: {query} |

## Self-Learning Pipeline
1. POST /feedback → Feedback (positiv/negativ) wird gesendet
2. Positiv: Wird als Verstärkung in Mem0 gespeichert (Namespace: cct-{agent})
3. Negativ: Wird als Fehler-Learning gespeichert (Namespace: cct-errors) mit "NICHT WIEDERHOLEN"
4. GET /learning/stats → Zeigt Anzahl Error-Memories und Pipeline-Status

## Bekannter Bug: Dify v1.13 Answer-Node
- Template {{#llm-main.text#}} wird NICHT aufgelöst
- Workaround: Orchestrator v3.0 nutzt Streaming + extrahiert LLM-Output aus node_finished Events
- Betrifft: Alle advanced-chat Chatflows

## Memory-Workflow
- Mem0 Retrieve: Vor LLM-Aufruf werden relevante Memories abgerufen
- Mem0 Save: Nach LLM-Antwort werden neue Erkenntnisse gespeichert
- Namespace-Trennung pro Agent (cct-architect, cct-coder, etc.)
- Core Memory: Persistente System-Config und Agent-Memories in SQLite
- Memory Endpoints: GET/PUT/DELETE /memory/system, GET/PUT /memory/agent, GET /memory/context

## Telegram Bot Workflow
1. User sendet Nachricht an A.AI Coach Bot
2. Bot erkennt Sprache (EN/DE/BS) und lädt User-State
3. RAG Middleware reichert Query an (KB + HippoRAG + Memory + Anti-Halluzination)
4. Dify Coach Chatflow wird aufgerufen (Streaming)
5. Antwort wird formatiert und an User gesendet
6. User-State und neue Fakten werden persistiert

## Backup Workflow
- Täglich um 03:00 via Cron
- Sichert: Dify DB, Neo4j, recall_memory.db, .env, Code
- Retention: 7 Tage, ältere Backups werden automatisch gelöscht
- Verifikation: Prüft ob alle Backup-Dateien existieren und nicht leer sind

## Sicherheit
- UFW Firewall: nur Ports 22, 80, 443
- fail2ban gegen Brute-Force
- Neo4j nur auf localhost (nicht extern erreichbar, 127.0.0.1:7474/7687)
- Caddy mit HSTS und Security-Headers
- Ollama auf 0.0.0.0:11434 (kein externer Zugang durch UFW)
