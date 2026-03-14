# Cloud Code Team - Workflows und Prozesse

## Agent-Routing
Der Orchestrator v3.0 routet Anfragen an spezialisierte Agents:
- POST /task mit {"agent": "architect", "query": "..."} → Architect Agent
- POST /chain mit {"agents": ["planner", "architect", "coder"], "query": "..."} → Kette
- GET /config/agents → Zeigt alle Agent-Konfigurationen inkl. Modell und Tier

## Chatflow-Architektur (v2)
Jeder der 11 Agents folgt diesem Chatflow:
1. Start → Eingabe empfangen
2. Parallel: Mem0 Retrieve + Knowledge Base Retrieval (Cloud Code Team KB)
3. LLM Anti-Halluzination Node mit tier-spezifischem Modell:
   - Tier 1 Code-Agents (Architect, Coder, DevOps, Tester): **minimax-m2.5:cloud**
   - Tier 2 Multilingual-Agents (Planner, Docs, Worker, Reviewer, Security, Debug): **glm-4.7:cloud**
   - Tier 3 Memory-Agent: **deepseek-v3.2:cloud**
4. Answer Node + Mem0 Save (parallel)

## Dify Parameter-Konfiguration (Ollama Cloud)
Bei Ollama Cloud Modellen in Dify müssen Parameter über Checkboxen aktiviert werden:
- Temperature: Per Checkbox aktiviert (blau = aktiv, grau = inaktiv)
- Num Predict: Auf 8192 gesetzt und per Checkbox aktiviert (alle Agents)
- Andere Parameter (Top P, Top K, etc.): Nicht aktiviert, Ollama-Defaults gelten

## Bekannter Bug: Dify v1.13 Answer-Node
- Template {{#llm-main.text#}} wird NICHT aufgelöst
- Workaround: Orchestrator v3.0 nutzt Streaming + extrahiert LLM-Output aus node_finished Events

## Memory-Workflow
- Mem0 Retrieve: Vor LLM-Aufruf werden relevante Memories abgerufen
- Mem0 Save: Nach LLM-Antwort werden neue Erkenntnisse gespeichert
- Namespace-Trennung pro Agent (cct-architect, cct-coder, etc.)

## Sicherheit
- UFW Firewall: nur Ports 22, 80, 443
- fail2ban gegen Brute-Force
- Neo4j nur auf localhost (nicht extern erreichbar)
- Caddy mit HSTS und Security-Headers
- Trivy Security-Scan durchgeführt
