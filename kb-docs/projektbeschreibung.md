# Cloud Code Team - Projektbeschreibung

## Überblick
Das Cloud Code Team ist ein KI-Multi-Agent-System basierend auf Dify v1.13.0 (Self-Hosted).
Es besteht aus 11 spezialisierten Agents + 1 Memory Agent (12 gesamt), die über einen FastAPI Orchestrator (v3.0) koordiniert werden.

## Architektur
- **Plattform:** Dify v1.13.0 Self-Hosted auf Hetzner CCX33
- **Server:** 8 vCPU Dedicated, 32 GB RAM, 240 GB SSD, Ubuntu 22.04
- **IP:** 178.104.51.123
- **Domain:** difyv2.activi.io (Caddy v2 SSL + HSTS)
- **LLM-Strategie:** 3-Tier Open Source Model Stack (alle via Ollama Cloud)
- **Ollama:** v0.17.7 (lokal als systemd Service auf 0.0.0.0:11434)
- **Memory:** Mem0 Plugin v0.0.2 (Cloud API)
- **Orchestrator:** FastAPI v3.0 Streaming-Modus (Port 8000, systemd)
- **RAG Middleware:** Zentrales Modul für KB + HippoRAG + Memory + Anti-Halluzination
- **Knowledge Graph:** Neo4j 5.26.22 Community Edition + HippoRAG (Port 8001, systemd)
- **Vektoren:** Qdrant (in Dify Docker)
- **Cache:** Redis (in Dify Docker)
- **Recall:** sqlite-vec (/opt/cloud-code/recall_memory.db)
- **Core Memory:** SQLite (/opt/cloud-code/core_memory.db)
- **Embedding:** Qwen3-Embedding-8B (4096 Dimensionen, LOKAL auf Ollama, 4.36 GB)
- **Telegram Bot:** A.AI Coach v3 (aktiv, systemd Service aai-coach-telegram.service)

## Ollama Architektur (Wichtig!)
Ollama v0.17.7 läuft LOKAL auf dem Server als systemd Service.
- **LLM-Modelle (Cloud):** minimax-m2.5:cloud, glm-4.7:cloud, deepseek-v3.2:cloud → 0 GB lokal, routing via Ollama Cloud
- **Embedding (Lokal):** qwen3-embedding:latest → 4.36 GB lokal auf dem Server
- **Weitere lokale Modelle:** qwen3-embedding:0.6b (639 MB), nomic-embed-text:latest (274 MB)
- **Docker-Zugang:** Container erreichen Ollama über docker0 Bridge IP 172.17.0.1:11434

## 3-Tier Open Source Model Stack

### Tier 1 - Code (MiniMax-M2.5)
Spezialisiert auf Code-Generierung, Architektur und technische Aufgaben.
| Agent | Modell | Temperatur |
|-------|--------|------------|
| Architect | minimax-m2.5:cloud | 0.3 |
| Coder | minimax-m2.5:cloud | 0.2 |
| DevOps | minimax-m2.5:cloud | 0.3 |
| Tester | minimax-m2.5:cloud | 0.2 |

### Tier 2 - Multilingual (GLM-4.7)
Spezialisiert auf mehrsprachige Kommunikation, Planung und Reviews.
| Agent | Modell | Temperatur |
|-------|--------|------------|
| Planner | glm-4.7:cloud | 0.4 |
| Docs | glm-4.7:cloud | 0.4 |
| Worker | glm-4.7:cloud | 0.5 |
| Reviewer | glm-4.7:cloud | 0.3 |
| Security | glm-4.7:cloud | 0.2 |
| Debug | glm-4.7:cloud | 0.3 |
| Coach | glm-4.7:cloud | 0.5 |

### Tier 3 - Günstig (DeepSeek V3.2)
Optimiert für Memory-Operationen mit minimaler Kreativität.
| Agent | Modell | Temperatur |
|-------|--------|------------|
| Memory | deepseek-v3.2:cloud | 0.1 |

## 12 Agents
1. **Architect** - System-Architektur, Design-Entscheidungen (Tier 1)
2. **Coder** - Code-Entwicklung, Implementation (Tier 1)
3. **Tester** - Testing, QA, Testfälle (Tier 1)
4. **DevOps** - Infrastructure, CI/CD, Deployment (Tier 1)
5. **Reviewer** - Code-Reviews, Best Practices (Tier 2)
6. **Docs** - Dokumentation, README, API-Docs (Tier 2)
7. **Security** - Sicherheit, Audits, Härtung (Tier 2)
8. **Planner** - Projektplanung, Sprint-Management (Tier 2)
9. **Debug** - Debugging, Fehleranalyse (Tier 2)
10. **Worker** - Allgemeine Aufgaben, Support (Tier 2)
11. **Coach** - Coaching, Mentoring, Teamführung (Tier 2)
12. **Memory** - Kontextgedächtnis, Erinnerungen (Tier 3)

## RAG Middleware (rag_middleware.py)
Zentrales Modul das JEDE Agent-Anfrage anreichert mit:
1. **KB Context** - Dify Knowledge Base (semantische Suche, Top-K=5)
2. **HippoRAG Context** - Knowledge Graph Beziehungen (Neo4j, Top-K=5)
3. **User Memory** - Persistente Pro-User Fakten (JSON-Dateien)
4. **Core Memory** - System-Variablen und Agent-Memories (SQLite)
5. **Anti-Halluzination** - Automatische Regelinjection
Wird von Orchestrator, Telegram Bot und zukünftigen Clients genutzt.

## 17 Hook-Endpoints
Der Orchestrator bietet 17 vorkonfigurierte Hook-Endpoints:
save, recall, status, learn, format, review, test, deploy, explain, refactor, doc, plan, debug, optimize, security, summarize, fix
Jeder Hook routet automatisch zum passenden Agent mit vordefinierten Prompt-Templates.

## Self-Learning Pipeline
- POST /feedback - Positives/negatives Feedback wird in Mem0 gespeichert
- GET /learning/stats - Statistiken über gelernte Fehler und Verbesserungen
- Namespace cct-errors für fehlerhafte Antworten (Anti-Wiederhol-Mechanismus)

## Auto-Routing
POST /route analysiert die Anfrage per Keyword-Matching und routet automatisch zum besten Agent.
10 Keyword-Sets (Deutsch) für: architect, coder, tester, reviewer, devops, docs, security, planner, debug, worker.
Fallback: worker Agent.

## Telegram Bot (A.AI Coach v3)
- Multilingual: EN/DE/BS mit per-User Spracheinstellung
- Streaming-Modus mit Dify Chatflow Integration
- Persistentes Memory: User-State + Pro-User Fakten überleben Restarts
- Unterstützt Private + Gruppen-Chats
- systemd Service: aai-coach-telegram.service (aktiv)
- Nutzt Coach Agent API-Key und RAG Middleware

## Anti-Halluzinations-System
Alle Agents folgen 5 Kernregeln:
1. WAHRHEITSPFLICHT: Nur KB, Memory oder User-Info nutzen
2. EHRLICHKEIT: Bei Unwissen zugeben
3. KEINE FALSCHEN BEHAUPTUNGEN
4. QUELLENANGABEN: [KB], [MEM], [USER]
5. KONFIDENZ: [SICHER], [WAHRSCHEINLICH], [UNSICHER]

## Dify Konfiguration
- **Default LLM:** glm-4.7:cloud (via Ollama)
- **Default Embedding:** qwen3-embedding:latest (via Ollama, lokal)
- **Provider:** Ollama (primär), OpenRouter (Fallback, 95 Modelle), OpenAI (Fallback)
- **Chatflow-Parameter:** Num Predict 8192 (per Checkbox aktiviert in Dify UI)
- **Bekannter Bug:** Dify v1.13 Answer-Node Template-Resolution → Workaround: Streaming-Modus
