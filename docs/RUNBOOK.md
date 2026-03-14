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
