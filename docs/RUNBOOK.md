# Cloud Code Team - Autonomes Runbook

Arbeitsanweisung fuer Claude Code / Codex als operativer Agent.

**Ziel:** Dieses Runbook so abarbeiten, dass am Ende alle P1-Aufgaben erledigt sind und das System produktionsbereit laeuft.

---

## 1. Betriebsmodus und Guardrails

- **Kanonischer Startweg:** Nur `systemctl restart cloud-code-orchestrator` verwenden
- **Backup vor jeder Aenderung:** `bash backup.sh` ausfuehren und Pfad dokumentieren
- **Keine Blind-Fixes:** Kernlogik (main.py, rag_middleware.py) nur bei reproduzierbarem Fehler aendern
- **Nach jeder Aenderung:** Syntax-Check + Health-Check + Test (siehe Schritt E)
- **Git-Disziplin:** Jede Aenderung committen mit Ursache, Datei, Fix, Testergebnis

---

## 2. Arbeitsablauf

### Schritt A: Status lesen

```bash
# Systemd Services pruefen
systemctl status cloud-code-orchestrator
systemctl status cloud-code-hipporag
systemctl status cloud-code-telegram

# Aktuelle Logs
journalctl -u cloud-code-orchestrator --since "1 hour ago" --no-pager | tail -50
```

### Schritt B: Health pruefen

```bash
# Orchestrator
curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# RAG + Memory
curl -s http://127.0.0.1:8000/rag/health | python3 -m json.tool

# HippoRAG
curl -s http://127.0.0.1:8001/health | python3 -m json.tool

# Agent-Config (IST-Zustand pruefen)
curl -s http://127.0.0.1:8000/config/agents | python3 -m json.tool
```

**Erwartung:** Alle Endpoints antworten mit Status 200.
**Bei Fehler:** Logs pruefen (Schritt A), dann gezielt reparieren.

### Schritt C: Einen Agent testen

```bash
# Worker-Agent mit einfacher Frage testen
curl -s -X POST http://127.0.0.1:8000/task \
  -H "Content-Type: application/json" \
  -d '{"agent": "worker", "query": "Was ist das Cloud Code Team?", "user": "test"}' \
  | python3 -m json.tool

# Auto-Routing testen
curl -s -X POST http://127.0.0.1:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query": "Erstelle einen Deployment-Plan", "user": "test"}' \
  | python3 -m json.tool
```

**Erwartung:** `answer` ist nicht leer, `conversation_id` vorhanden.
**Bei leerer Antwort:** OpenRouter-Bug (T02) — Streaming-Workaround pruefen.

### Schritt D: P1-Aufgaben abarbeiten

Reihenfolge einhalten:

**D1: API-Keys externalisieren (T01)**
```bash
cd /opt/cloud-code

# 1. Alle hardcodierten Keys finden
grep -rn "TELEGRAM_TOKEN\|MEM0_API_KEY\|DIFY_API_KEY" *.py orchestrator/*.py

# 2. Keys in .env verschieben (NICHT committen!)
# 3. Code aendern: os.getenv("KEY_NAME") OHNE Default-Wert
# 4. Testen: Service neu starten, Health pruefen
```

**D2: IST-Zustand dokumentieren (T04)**
```bash
# Pruefen welche Modelle Dify tatsaechlich nutzt
curl -s http://127.0.0.1:8000/config/agents | python3 -c "
import sys, json
data = json.load(sys.stdin)
for agent, cfg in data.get('agents', {}).items():
    print(f'{agent}: {cfg.get(\"model\", \"?\")} ({cfg.get(\"tier\", \"?\")})')
"
```

**D3: DIFY_KB_KEY setzen (T03)**
```bash
# In Dify Admin: Settings > API Keys > Dataset API Key kopieren
# In .env eintragen: DIFY_KB_KEY=<echter-key>
# Testen:
curl -s http://127.0.0.1:8000/rag/health | python3 -m json.tool
# kb sollte true sein
```

### Schritt E: Nach jeder Aenderung testen

```bash
# Syntax-Check aller Python-Dateien
python3 -m py_compile orchestrator/main.py
python3 -m py_compile rag_middleware.py
python3 -m py_compile telegram_bot.py

# Service neu starten
systemctl restart cloud-code-orchestrator

# Health pruefen (10 Sekunden warten fuer Startup)
sleep 3 && curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# RAG pruefen
curl -s http://127.0.0.1:8000/rag/health | python3 -m json.tool

# Einen Agent testen
curl -s -X POST http://127.0.0.1:8000/task \
  -H "Content-Type: application/json" \
  -d '{"agent": "worker", "query": "Antworte mit OK", "user": "test"}' \
  | python3 -m json.tool
```

### Schritt F: Ergebnis dokumentieren

Nach jedem Fix eine Zeile in folgendem Format:

```
FIX: [Datei] [Was] [Warum] [Test-Ergebnis] [Restrisiko]
```

Beispiel:
```
FIX: telegram_bot.py | API-Keys externalisiert | Security (T01) | Health OK, Bot antwortet | Git-History noch unsauber (T15)
```

---

## 3. Prioritaetenmatrix

| Prio | Bereich | Status | Aktion bei Problem |
|------|---------|--------|-------------------|
| P1 | /health | Muss 200 sein | Logs + ENV pruefen |
| P1 | /task (worker) | Muss Antwort liefern | Dify API Key + Streaming pruefen |
| P1 | API-Keys im Code | Muss raus | T01 abarbeiten |
| P2 | /rag/health | KB + HippoRAG true | DIFY_KB_KEY + Neo4j pruefen |
| P2 | Telegram Bot | Muss antworten | systemd Status + Logs |
| P3 | /feedback | Mem0 Speicherung | API-Key + Netzwerk pruefen |
| P3 | Load Testing | Ungetestet | locustfile.py ausfuehren |

---

## 4. Capability-Matrix

| Bereich | Status | Nachweis | Bei Regression |
|---------|--------|---------|----------------|
| Orchestrator API | Erwartet: Gruen | /health = 200 | uvicorn Logs + Port 8000 |
| Agent Routing | Erwartet: Gruen | /route liefert Antwort | AGENT_KEYS ENV pruefen |
| RAG Middleware | Erwartet: Gruen | /rag/health alle true | KB-Key, HippoRAG, SQLite |
| Knowledge Graph | Erwartet: Gruen | /hipporag/health OK | Neo4j Container + Port 8001 |
| Telegram Bot | Erwartet: Gruen | Bot antwortet auf /start | TELEGRAM_TOKEN + Dify Key |
| Core Memory | Erwartet: Gruen | /memory/system liefert Daten | SQLite DB Pfad pruefen |
| Self-Learning | Erwartet: Gelb | /feedback speichert | Mem0 API Key + Cloud |

---

## 5. Dateien die NICHT geaendert werden duerfen (ohne Review)

- `orchestrator/main.py` — Kern des Systems, 698 Zeilen
- `rag_middleware.py` — RAG-Pipeline, von allen Clients genutzt
- `plugins/cloud-code-orchestrator/manifest.yaml` — Dify Plugin Definition

---

## 6. Autonome Checkliste vor Go-Live

- [ ] Backup vorhanden und Pfad dokumentiert
- [ ] Nur ein aktiver Orchestrator-Prozess (Port 8000)
- [ ] Alle API-Keys in .env, keine im Code
- [ ] Syntax-Check gruen fuer alle .py Dateien
- [ ] /health = 200
- [ ] /rag/health: kb=true, hipporag=true, core_memory=true
- [ ] /task mit worker Agent liefert Antwort
- [ ] /route liefert Antwort mit routing_reason
- [ ] Telegram Bot antwortet auf /start
- [ ] Git-Status sauber, alle Aenderungen committed

---

## 7. Notfall-Rollback

```bash
# Letzes Backup wiederherstellen
cd /opt/cloud-code
ls -la backups/  # Letztes Backup finden

# Service stoppen
systemctl stop cloud-code-orchestrator

# Dateien zurueckkopieren
cp backups/YYYY-MM-DD/orchestrator/main.py orchestrator/main.py
cp backups/YYYY-MM-DD/rag_middleware.py rag_middleware.py

# Service starten
systemctl start cloud-code-orchestrator

# Health pruefen
sleep 3 && curl -s http://127.0.0.1:8000/health
```


---

## 8. Mem0 Stack Operations

### 8.1 Mem0 Health pruefen

```bash
# Mem0 Server
curl -s http://localhost:8002/health | python3 -m json.tool

# Mem0 Stats
curl -s http://localhost:8002/v1/stats/ | python3 -m json.tool

# Mem0 Qdrant (separater Container\!)
curl -s http://localhost:16333/collections | python3 -m json.tool

# Deep-RAG (alle 3 Quellen)
curl -s http://localhost:8000/workflow/deep-rag/health | python3 -m json.tool
```

**Erwartung:** Alle healthy, deep-rag: kb=true, mem0=true, hipporag=true

### 8.2 Mem0 Container verwalten

```bash
cd /opt/cloud-code/mem0-local

# Status
docker compose -f docker-compose.mem0.yml ps

# Neustart (einzeln)
docker restart cct-mem0          # Mem0 Server
docker restart cct-mem0-qdrant   # Qdrant v1.12
docker restart cct-agent-watcher # Agent Watcher

# Logs
docker logs cct-mem0 --tail 50
docker logs cct-agent-watcher --tail 20

# Komplett neu deployen
docker compose -f docker-compose.mem0.yml up -d --build
```

**ACHTUNG:** Mem0 haengt gelegentlich bei langen Ollama-Calls (Single Worker).
Bei Timeout → `docker restart cct-mem0` loest das Problem.

### 8.3 Mem0 Memory suchen/verwalten

```bash
# Suche
curl -s -X POST http://localhost:8002/v1/memories/search/ \
  -H "Content-Type: application/json" \
  -d query:Denis | python3 -m json.tool

# Alle Memories auflisten
curl -s "http://localhost:8002/v1/memories/?user_id=cloud-code-team" | python3 -m json.tool

# Entities
curl -s http://localhost:8002/v1/entities/ | python3 -m json.tool
```

### 8.4 Agent-Watcher pruefen

```bash
# Logs (Login + Agent Detection)
docker logs cct-agent-watcher --tail 20 2>&1

# Erwartung: "Dify login successful" + "Healthcheck OK — 23 agents, Mem0 ✅"
# Telegram Bot Test:
curl -s "https://api.telegram.org/bot8718856271:AAHKkOplIj0bgZ3sGa15cLfEbzoSMzpHj4o/sendMessage" \
  -d "chat_id=8747456067&text=Runbook Test"
```

### 8.5 OpenMemory Dashboard (T23 — geplant)

Self-hosted UI als Ersatz fuer app.mem0.ai Dashboard.

```bash
# Nach Deployment:
# Frontend: http://localhost:3030
# Verbindungen: Mem0 API (8002), Qdrant (16333), Neo4j (7687)

cd /opt/cloud-code/mem0-local
docker compose -f docker-compose.mem0.yml ps  # openmemory-ui sollte Up sein
curl -s http://localhost:3030/health           # Dashboard Health
```

**Schritte zum Deployen (wenn T23 umgesetzt wird):**
1. OpenMemory aus `mem0ai/mem0` Repo clonen
2. Service in `docker-compose.mem0.yml` ergaenzen
3. Frontend ENV: `MEM0_API_URL=http://cct-mem0:8002`
4. Port 3030 mappen
5. `docker compose -f docker-compose.mem0.yml up -d`
✅ Sektion 8 in RUNBOOK.md eingetragen cat
✅ Sektion 8 in RUNBOOK.md eingetragen cat
