# Cloud Code Team - Projektbeschreibung

## Überblick
Das Cloud Code Team ist ein KI-Multi-Agent-System basierend auf Dify v1.13 (Self-Hosted).
Es besteht aus 10 spezialisierten Agents + 1 Memory Agent, die über einen FastAPI Orchestrator (v3.0) koordiniert werden.

## Architektur
- **Plattform:** Dify v1.13.0 Self-Hosted auf Hetzner CCX33
- **Server:** 8 vCPU Dedicated, 32 GB RAM, Ubuntu 22.04
- **Domain:** difyv2.activi.io (Caddy SSL + HSTS)
- **LLM-Strategie:** 3-Tier Open Source Model Stack (alle via Ollama Cloud)
- **Memory:** Mem0 Plugin v0.0.2 (Cloud API)
- **Orchestrator:** FastAPI v3.0 Streaming-Modus (Port 8000)
- **Knowledge Graph:** Neo4j 5 + HippoRAG (Port 8001)
- **Vektoren:** Qdrant (in Dify Docker)
- **Cache:** Redis (in Dify Docker)
- **Recall:** sqlite-vec (/opt/cloud-code/recall_memory.db)
- **Embedding:** Qwen3-Embedding-8B (4096 Dimensionen, lokal via Ollama)

## 3-Tier Open Source Model Stack
Alle Modelle laufen über Ollama Cloud (docker0 bridge 172.17.0.1:11434).

### Tier 1 - Code (MiniMax-M2.5)
Spezialisiert auf Code-Generierung, Architektur und technische Aufgaben.
| Agent | Modell | Temperatur | Num Predict |
|-------|--------|------------|-------------|
| Architect | minimax-m2.5:cloud | 0.3 | 8192 |
| Coder | minimax-m2.5:cloud | 0.2 | 8192 |
| DevOps | minimax-m2.5:cloud | 0.3 | 8192 |
| Tester | minimax-m2.5:cloud | 0.2 | 8192 |

### Tier 2 - Multilingual (GLM-4.7)
Spezialisiert auf mehrsprachige Kommunikation, Planung und Reviews.
| Agent | Modell | Temperatur | Num Predict |
|-------|--------|------------|-------------|
| Planner | glm-4.7:cloud | 0.4 | 8192 |
| Docs | glm-4.7:cloud | 0.4 | 8192 |
| Worker | glm-4.7:cloud | 0.5 | 8192 |
| Reviewer | glm-4.7:cloud | 0.3 | 8192 |
| Security | glm-4.7:cloud | 0.2 | 8192 |
| Debug | glm-4.7:cloud | 0.3 | 8192 |

### Tier 3 - Günstig (DeepSeek V3.2)
Optimiert für Memory-Operationen mit minimaler Kreativität.
| Agent | Modell | Temperatur | Num Predict |
|-------|--------|------------|-------------|
| Memory | deepseek-v3.2:cloud | 0.1 | 8192 |

## 11 Agents
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
11. **Memory** - Kontextgedächtnis, Erinnerungen (Tier 3)

## Anti-Halluzinations-System
Alle Agents folgen 5 Kernregeln:
1. WAHRHEITSPFLICHT: Nur KB, Memory oder User-Info nutzen
2. EHRLICHKEIT: Bei Unwissen zugeben
3. KEINE FALSCHEN BEHAUPTUNGEN
4. QUELLENANGABEN: [KB], [MEM], [USER]
5. KONFIDENZ: [SICHER], [WAHRSCHEINLICH], [UNSICHER]
