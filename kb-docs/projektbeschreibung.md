# Cloud Code Team - Projektbeschreibung

Stand: 16.03.2026

## Ueberblick
Das Cloud Code Team ist ein KI-Multi-Agent-System basierend auf Dify v1.13.0 (Self-Hosted).
Es besteht aus 11 spezialisierten Agents + 1 Memory Agent (12 gesamt), die ueber einen FastAPI Orchestrator (v3.0) koordiniert werden.

## Architektur
- **Plattform:** Dify v1.13.0 Self-Hosted auf Hetzner CCX33
- **Server:** 8 vCPU Dedicated, 32 GB RAM, 240 GB SSD, Ubuntu 22.04
- **IP:** 178.104.51.123
- **Domain:** difyv2.activi.io (Caddy v2 SSL + HSTS)
- **LLM-Strategie:** 4-Tier Open Source Model Stack (alle via Ollama Cloud)
- **Ollama:** v0.17.7 (lokal als systemd Service, Cloud API Key konfiguriert)
- **Memory:** Mem0 Lokal (Port 8002, Docker, Graph=true)
- **Orchestrator:** FastAPI v3.0 (Port 8000, 1317 Zeilen main.py, systemd Service)
- **RAG Middleware:** KB + HippoRAG + Mem0 + Anti-Halluzination
- **Knowledge Graph:** Neo4j 5.26.22 + HippoRAG (Port 8001, systemd Service)
- **Vektoren:** Qdrant (Dify Docker + cct-mem0-qdrant Port 16333)
- **Tracing:** Langfuse v4 (cloud.langfuse.com)
- **Embedding:** Qwen3-Embedding (4096 Dim., LOKAL auf Ollama)
- **Telegram Bot:** A.AI Coach v3 (systemd Service)
- **Chainlit:** v2.10.0 (installiert fuer Hybrid Retrieval Testing)

## 4-Tier Open Source Model Stack (Ollama Cloud)

Alle LLM-Modelle laufen via Ollama Cloud (0 GB lokal, geroutet ueber Ollama API Key).
OpenRouter steht als Fallback-Infrastruktur bereit (API-Key noch nicht gesetzt).

### Tier 1 - Code (qwen3-coder-next:cloud, ~0.7s)
Spezialisiert auf Code-Generierung und technische Aufgaben.
| Agent | Temperatur |
|-------|------------|
| Coder | 0.2 |
| DevOps | 0.3 |
| Tester | 0.2 |

### Tier 2 - Reasoning (deepseek-v3.2:cloud, ~2.2s)
Spezialisiert auf Analyse, Architektur und Sicherheit.
| Agent | Temperatur |
|-------|------------|
| Architect | 0.3 |
| Security | 0.2 |
| Reviewer | 0.3 |
| Debug | 0.3 |

### Tier 3 - General (minimax-m2.5:cloud, ~1.3s)
Schnellstes Modell fuer allgemeine Aufgaben und Kommunikation.
| Agent | Temperatur |
|-------|------------|
| Coach | 0.5 |
| Planner | 0.4 |
| Docs | 0.4 |
| Worker | 0.5 |

### Tier 4 - Memory (minimax-m2.5:cloud, ~1.3s)
Optimiert fuer Memory-Operationen mit minimaler Kreativitaet.
| Agent | Temperatur |
|-------|------------|
| Memory | 0.1 |

## 12 Agents
1. **Coder** - Code-Entwicklung, Implementation (Tier 1)
2. **DevOps** - Infrastructure, CI/CD, Deployment (Tier 1)
3. **Tester** - Testing, QA, Testfaelle (Tier 1)
4. **Architect** - System-Architektur, Design-Entscheidungen (Tier 2)
5. **Security** - Sicherheit, Audits, Haertung (Tier 2)
6. **Reviewer** - Code-Reviews, Best Practices (Tier 2)
7. **Debug** - Debugging, Fehleranalyse (Tier 2)
8. **Coach** - Coaching, Mentoring, Teamfuehrung (Tier 3)
9. **Planner** - Projektplanung, Sprint-Management (Tier 3)
10. **Docs** - Dokumentation, README, API-Docs (Tier 3)
11. **Worker** - Allgemeine Aufgaben, Support (Tier 3)
12. **Memory** - Kontextgedaechtnis, Erinnerungen (Tier 4)

## RAG Middleware
Jede Agent-Anfrage wird angereichert mit:
1. **KB Context** - Dify Knowledge Base (semantische Suche, Top-K=5)
2. **HippoRAG Context** - Knowledge Graph Beziehungen (Neo4j, Top-K=5)
3. **Mem0 Dual-Search** - Eigene Memories [OWN:cct-{agent}] + Shared [SHARED:cloud-code-team]
4. **Core Memory** - System-Variablen und Agent-Memories (SQLite)
5. **Anti-Halluzination** - Automatische Regelinjection

## Chatflow-Architektur (Dify v2)
Jeder Agent folgt diesem Chatflow:
1. Start → Eingabe empfangen
2. Memory abrufen (Mem0 Tool Call, ~12-15s)
3. KB durchsuchen (Knowledge Retrieval, ~0.3s)
4. LLM Anti-Halluzination (minimax-m2.5:cloud als Default, ~6-16s)
5. Antwort (Answer Node)
6. Memory speichern (Mem0 Tool Call, ~30s)

**Bekannter Bug:** Dify v1.13 Answer-Node Template {{#llm-main.text#}} wird nicht aufgeloest.
Workaround: Orchestrator nutzt Streaming + extrahiert LLM-Output aus node_finished Events.

**Performance-Bottleneck:** Mem0 Tool Calls (Memory abrufen + speichern) verbrauchen ~45s der Gesamtzeit.
LLM-Call selbst ist schnell (6-16s mit minimax-m2.5:cloud).

## systemd Services (Reboot-sicher)
Alle kritischen Services sind als systemd Services konfiguriert und enabled:
- orchestrator.service (active, EnvironmentFile=.env)
- hipporag.service (active)
- neo4j.service (enabled, startet bei Reboot)
- ollama.service (active)
- caddy.service (active)
- aai-coach-telegram.service (active)

## Langfuse Tracing
Alle LLM-Aufrufe (direkt via Ollama Cloud und via Dify) werden in Langfuse v4 getraced.
Dashboard: cloud.langfuse.com

## Anti-Halluzinations-System
Alle Agents folgen 5 Kernregeln:
1. WAHRHEITSPFLICHT: Nur KB, Memory oder User-Info nutzen
2. EHRLICHKEIT: Bei Unwissen zugeben
3. KEINE FALSCHEN BEHAUPTUNGEN
4. QUELLENANGABEN: [KB], [MEM], [USER]
5. KONFIDENZ: [SICHER], [WAHRSCHEINLICH], [UNSICHER]

## Dify Konfiguration
- **Default LLM:** minimax-m2.5:cloud (via Ollama, umgestellt 16.03.2026)
- **Default Embedding:** qwen3-embedding:latest (via Ollama, lokal)
- **Provider:** Ollama (primaer), OpenRouter (Fallback-Infrastruktur), OpenAI (TTS/STT)

## Installierte SDKs
57+ AI-Pakete global installiert inkl. LlamaIndex 0.14.16 (23 Subpakete), LangChain 1.2.12, Chainlit 2.10.0, Mem0 1.0.5, Langfuse 4.0.0, FastEmbed, FlagEmbedding, Sentence-Transformers.
