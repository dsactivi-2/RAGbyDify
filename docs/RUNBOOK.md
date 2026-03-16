# Cloud Code Team - Autonomes Runbook

Arbeitsanweisung fuer Claude Code / Codex als operativer Agent.
**Stand:** 2026-03-16 — 4-Tier Ollama Cloud, Langfuse Tracing, Mem0 Lokal, 12 Agents, systemd Services

---

## 1. Server-Zugang

```bash
ssh -i ~/.ssh/cloud-code-team root@178.104.51.123
```

---

## 2. Betriebsmodus und Guardrails

- **Orchestrator:** systemd Service (orchestrator.service, enabled/active)
- **HippoRAG:** systemd Service (hipporag.service, enabled/active)
- **Neo4j:** systemd Service (neo4j.service, enabled, startet bei Reboot; aktuell via docker-compose)
- **Ollama:** systemd Service (ollama.service, enabled/active)
- **Caddy:** systemd Service (caddy.service, enabled/active)
- **Telegram Bot:** systemd Service (aai-coach-telegram.service, enabled/active)
- **Backup vor jeder Aenderung:** `bash /opt/cloud-code/backup.sh`
- **Keine Blind-Fixes:** Kernlogik (main.py) nur bei reproduzierbarem Fehler aendern
- **Git-Disziplin:** Jede Aenderung committen

---

## 3. Status pruefen

### Schritt A: systemd Services

```bash
# Alle Services auf einmal
for s in ollama orchestrator hipporag neo4j caddy aai-coach-telegram; do
  echo -n "$s: "; systemctl is-active $s 2>/dev/null || echo 'not found'
done

# Detailstatus
systemctl status orchestrator --no-pager -l
systemctl status hipporag --no-pager -l
```

### Schritt B: Docker Container (17 erwartet)

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | head -20
docker ps -q | wc -l
```

### Schritt C: Health Endpoints

```bash
# Orchestrator
curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# LLM Cloud Status + Modelle
curl -s http://127.0.0.1:8000/llm/health | python3 -m json.tool

# Langfuse Tracing
curl -s http://127.0.0.1:8000/langfuse/health | python3 -m json.tool

# HippoRAG
curl -s http://127.0.0.1:8001/health | python3 -m json.tool

# Mem0 Lokal
curl -s http://localhost:8002/health | python3 -m json.tool

# Agent-Config (4-Tier Zuweisung)
curl -s http://127.0.0.1:8000/config/agents | python3 -m json.tool
```

**Erwartung:** Alle Endpoints HTTP 200.

### Schritt D: Funktionstest

```bash
# LLM Direct (Ollama Cloud)
curl -s -X POST http://127.0.0.1:8000/llm/direct \
  -H "Content-Type: application/json" \
  -d '{"model": "minimax-m2.5", "prompt": "Sage OK", "temperature": 0.1}' \
  | python3 -m json.tool

# Agent via Dify
curl -s -X POST http://127.0.0.1:8000/task \
  -H "Content-Type: application/json" \
  -d '{"agent": "worker", "query": "Antworte mit OK", "user": "test"}' \
  | python3 -m json.tool

# Auto-Routing
curl -s -X POST http://127.0.0.1:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query": "Erstelle einen Deployment-Plan", "user": "test"}' \
  | python3 -m json.tool
```

---

## 4. Neustart-Prozeduren

### Orchestrator (systemd)

```bash
systemctl restart orchestrator
sleep 3 && systemctl status orchestrator --no-pager
curl -s http://127.0.0.1:8000/health
```

### HippoRAG (systemd)

```bash
systemctl restart hipporag
sleep 3 && systemctl status hipporag --no-pager
curl -s http://127.0.0.1:8001/health
```

### Neo4j

```bash
# Aktuell via Docker:
docker restart neo4j
sleep 5 && docker exec neo4j cypher-shell -u neo4j -p 22e58741703f24f1913550c9a8a51c99 'RETURN 1'

# Nach Reboot via systemd:
systemctl restart neo4j
```

### Ollama

```bash
systemctl restart ollama
sleep 2 && curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])), 'models')"
```

### Mem0

```bash
docker restart cct-mem0
sleep 3 && curl -s http://localhost:8002/health
```

### Dify API

```bash
docker restart docker-api-1
sleep 5 && curl -s -o /dev/null -w "%{http_code}" https://difyv2.activi.io/v1/
```

### Telegram Bot

```bash
systemctl restart aai-coach-telegram
sleep 2 && systemctl status aai-coach-telegram --no-pager
```

### Manueller Fallback (falls systemd nicht funktioniert)

```bash
# Orchestrator manuell
pkill -f 'uvicorn.*main:app.*8000'
cd /opt/cloud-code/orchestrator
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/orchestrator.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8000/health

# HippoRAG manuell
pkill -f 'hipporag.*8001'
cd /opt/cloud-code/hipporag
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 > /tmp/hipporag.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8001/health
```

---

## 5. Environment-Konfiguration

Alle Secrets liegen in `/opt/cloud-code/orchestrator/.env` (20 Eintraege):
- 12x AGENT_{ROLE}_KEY (Dify Agent API-Keys)
- DIFY_API_URL
- OLLAMA_CLOUD_URL
- OPENROUTER_API_KEY (leer = Fallback deaktiviert)
- TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
- LANGFUSE_SECRET_KEY + LANGFUSE_PUBLIC_KEY + LANGFUSE_BASE_URL

Ollama Cloud API Key liegt in: `/etc/systemd/system/ollama.service` (Environment Variable)

orchestrator.service nutzt: `EnvironmentFile=/opt/cloud-code/orchestrator/.env`

---

## 6. Dify Datenbank

Dify nutzt PostgreSQL in Docker. Nuetzliche Abfragen:

```bash
# Default-Modell pruefen
docker exec docker-db_postgres-1 psql -U postgres -d dify \
  -c "SELECT model_name, model_type FROM tenant_default_models;"

# Default-Modell aendern (Beispiel: minimax-m2.5:cloud)
docker exec docker-db_postgres-1 psql -U postgres -d dify \
  -c "UPDATE tenant_default_models SET model_name = 'minimax-m2.5:cloud' WHERE model_type = 'llm';"

# Danach Dify API neu starten:
docker restart docker-api-1
```

---

## 7. Sicherheit

### UFW
```bash
ufw status
```

### DOCKER-USER iptables Chain
Docker umgeht UFW. Schutz via DOCKER-USER Chain:
```bash
iptables -L DOCKER-USER -n -v
```

15 DROP-Regeln aktiv. Persistiert in:
- `/etc/iptables.rules`
- `/etc/network/if-pre-up.d/iptables-restore`

Blockierte Ports (extern): 3000, 3080, 5003, 5432, 7474, 7687, 8000, 8001, 8765, 11434, 16333, 16334, 26333

---

## 8. Mem0 Stack Operations

### Health pruefen
```bash
curl -s http://localhost:8002/health | python3 -m json.tool
curl -s http://localhost:16333/collections | python3 -m json.tool
```

### Container verwalten
```bash
docker restart cct-mem0          # Mem0 Server
docker restart cct-mem0-qdrant   # Qdrant v1.12
docker restart cct-agent-watcher # Agent Watcher
docker logs cct-mem0 --tail 50
```

### Memory suchen
```bash
curl -s -X POST http://localhost:8002/v1/memories/search/ \
  -H "Content-Type: application/json" \
  -d '{"query": "Denis", "user_id": "cloud-code-team"}' | python3 -m json.tool
```

---

## 9. Langfuse Tracing

- Dashboard: https://cloud.langfuse.com
- Health: `curl -s http://127.0.0.1:8000/langfuse/health`
- Traces werden fuer LLM-Direct und Dify-Agent Calls geschrieben
- SDK: Langfuse v4 (api.ingestion.batch(), NICHT trace()/observe())

---

## 10. Bekannte Probleme

| Problem | Workaround | Status |
|---------|-----------|--------|
| Dify Answer-Node {{#llm-main.text#}} | Streaming + node_finished Extraktion | Dauerhaft |
| Mem0 Tool Calls ~45s pro Dify-Call | Optimierung pending | Offen |
| OpenRouter Fallback leer | API-Key in .env setzen | Offen |
| Mem0 nutzt glm-4.7 statt minimax | Config auf minimax-m2.5 umstellen | Offen |
| Mem0 haengt bei langen Calls | `docker restart cct-mem0` | Bekannt |

---

## 11. Notfall-Rollback

```bash
cd /opt/cloud-code
ls -la backups/

# Orchestrator Rollback
cp backups/YYYY-MM-DD/orchestrator/main.py orchestrator/main.py
systemctl restart orchestrator
sleep 3 && curl -s http://127.0.0.1:8000/health

# Mem0 Stack Rollback
cd /opt/cloud-code/mem0-local
docker compose -f docker-compose.mem0.yml down
docker compose -f docker-compose.mem0.yml up -d
```

---

## 12. SSH-Tunnel (fuer lokale Entwicklung)

```bash
# Script auf Mac:
~/.ssh/start-mem0-tunnel.sh start|stop|status

# Tunnelt:
# 16333 → Qdrant (mem0_memories)
# 11434 → Ollama (Embeddings + LLM)
# 7687  → Neo4j (Knowledge Graph)
```

---

## 13. Utility Scripts

| Script | Zweck |
|--------|-------|
| /opt/cloud-code/scripts/01-scan-sdks.sh | Scannt pip, venvs und Docker nach AI SDKs |
| /opt/cloud-code/scripts/02-setup-neo4j-systemd.sh | Neo4j systemd Service Setup |
| /opt/cloud-code/scripts/03-chainlit-hybrid-test.py | Chainlit Chat UI mit Hybrid Retrieval |
| /opt/cloud-code/scripts/04-install-missing.sh | Fehlende Pakete installieren |
| /opt/cloud-code/backup.sh | Taegliches Backup (Cron 03:00) |

---

## 14. Wichtige Dateien

| Datei | Zweck | Zeilen |
|-------|-------|--------|
| /opt/cloud-code/orchestrator/main.py | Orchestrator Kern | 1317 |
| /opt/cloud-code/orchestrator/.env | Alle Secrets | 20 Eintraege |
| /opt/cloud-code/orchestrator/cct_workflows/ | 10 Workflow-Module | div. |
| /opt/cloud-code/hipporag/main.py | HippoRAG Service | div. |
| /opt/cloud-code/rag_middleware.py | RAG Middleware | div. |
| /opt/cloud-code/telegram_bot.py | Telegram Bot | div. |
| /etc/systemd/system/orchestrator.service | Orchestrator systemd (EnvironmentFile) | ~15 |
| /etc/systemd/system/hipporag.service | HippoRAG systemd | ~15 |
| /etc/systemd/system/neo4j.service | Neo4j Docker systemd | ~25 |
| /etc/systemd/system/ollama.service | Ollama + Cloud API Key | div. |
| /etc/iptables.rules | Docker Security Rules | div. |
