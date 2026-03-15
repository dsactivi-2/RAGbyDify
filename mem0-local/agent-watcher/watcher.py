#!/usr/bin/env python3
"""
Cloud Code Team — Agent Watcher Service
=========================================
- Pollt Dify Console API alle 60s
- Erkennt neue/gelöschte/geänderte Agents
- Prüft Mem0, Error-Handling, Model Config
- Sendet Telegram Alerts
- Healthcheck alle 5 Min
"""

import requests
import json
import time
import os
import logging
import base64
from datetime import datetime

# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────

DIFY_URL = os.getenv("DIFY_URL", "http://nginx:80")
DIFY_EXTERNAL_URL = os.getenv("DIFY_EXTERNAL_URL", "https://difyv2.activi.io")
DIFY_EMAIL = os.getenv("DIFY_ADMIN_EMAIL", "ds.selmanovic@gmail.com")
DIFY_PASSWORD = os.getenv("DIFY_ADMIN_PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MEM0_URL = os.getenv("MEM0_LOCAL_URL", "http://mem0:8002")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
HC_INTERVAL = int(os.getenv("HEALTHCHECK_INTERVAL", "300"))
STATE_FILE = "/app/data/agent_state.json"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agent-watcher")

# ──────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────

def send_telegram(message):
    """Telegram Nachricht senden"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping alert")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logger.error("Telegram send failed: %s", e)


def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except:
        pass
    return {"agents": {}, "last_healthcheck": 0}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ──────────────────────────────────────────
# DIFY API
# ──────────────────────────────────────────

class DifyClient:
    def __init__(self):
        self.session = requests.Session()
        self.csrf_token = None
        self.logged_in = False

    def login(self):
        """Login bei Dify Console (Dify v1.13+ erwartet Base64-encoded Passwort)"""
        try:
            # Dify v1.13 erwartet Base64-encoded Passwort
            encoded_password = base64.b64encode(DIFY_PASSWORD.encode()).decode()
            r = self.session.post(f"{DIFY_URL}/console/api/login", json={
                "email": DIFY_EMAIL,
                "password": encoded_password,
                "remember_me": True,
            }, timeout=10)
            if r.status_code == 200:
                # CSRF Token aus Cookies extrahieren
                for cookie in self.session.cookies:
                    if cookie.name == "csrf_token":
                        self.csrf_token = cookie.value
                self.logged_in = True
                logger.info("✅ Dify login successful")
                return True
            else:
                self.logged_in = False
                logger.error("❌ Dify login failed: %s — %s", r.status_code, r.text[:200])
                return False
        except Exception as e:
            self.logged_in = False
            logger.error("❌ Dify login error: %s", e)
            return False

    def _get_headers(self):
        """Standard-Headers mit CSRF-Token"""
        headers = {}
        if self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token
        return headers

    def _ensure_logged_in(self):
        """Login falls nötig, max 1 Retry"""
        if not self.logged_in:
            return self.login()
        return True

    def get_apps(self):
        """Alle Apps/Agents auflisten"""
        if not self._ensure_logged_in():
            return []
        try:
            r = self.session.get(f"{DIFY_URL}/console/api/apps?page=1&limit=100",
                                 headers=self._get_headers(), timeout=15)
            if r.status_code == 401:
                # Token abgelaufen → einmal re-login, kein Rekursions-Loop
                self.logged_in = False
                if not self.login():
                    return []
                r = self.session.get(f"{DIFY_URL}/console/api/apps?page=1&limit=100",
                                     headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                return r.json().get("data", [])
            logger.error("Error fetching apps: HTTP %s", r.status_code)
            return []
        except Exception as e:
            logger.error("Error fetching apps: %s", e)
            return []

    def get_workflow(self, app_id):
        """Workflow eines Agents holen"""
        try:
            r = self.session.get(f"{DIFY_URL}/console/api/apps/{app_id}/workflows/draft",
                                 headers=self._get_headers(), timeout=15)
            if r.status_code == 401:
                self.logged_in = False
                if not self.login():
                    return None
                r = self.session.get(f"{DIFY_URL}/console/api/apps/{app_id}/workflows/draft",
                                     headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            logger.error("Error fetching workflow for %s: %s", app_id, e)
            return None

    def check_agent(self, app_id):
        """Agent-Workflow auf Vollständigkeit prüfen"""
        wf = self.get_workflow(app_id)
        if not wf:
            return {"error": "workflow_not_found"}

        nodes = wf.get("graph", {}).get("nodes", [])
        edges = wf.get("graph", {}).get("edges", [])

        checks = {
            "has_mem0_retrieve": False,
            "has_mem0_save": False,
            "has_error_handling": False,
            "has_error_answer": False,
            "has_kb": False,
            "model": "unknown",
            "model_provider": "unknown",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "mem0_protected": False,
        }

        if_else_id = None

        for node in nodes:
            ntype = node.get("data", {}).get("type", "")

            if ntype == "tool":
                tool_name = node.get("data", {}).get("tool_name", "")
                if "retrieve" in tool_name and "mem0" in tool_name:
                    checks["has_mem0_retrieve"] = True
                if "add" in tool_name and "mem0" in tool_name:
                    checks["has_mem0_save"] = True

            elif ntype == "if-else":
                checks["has_error_handling"] = True
                if_else_id = node.get("id")

            elif ntype == "llm":
                model_info = node.get("data", {}).get("model", {})
                checks["model"] = model_info.get("name", "unknown")
                checks["model_provider"] = model_info.get("provider", "unknown")

            elif ntype == "answer":
                title = node.get("data", {}).get("title", "").lower()
                if "error" in title or "fehler" in title:
                    checks["has_error_answer"] = True

            elif ntype == "knowledge-retrieval":
                checks["has_kb"] = True

        # Mem0 Protection Check: Save-Node darf nicht direkt am LLM hängen
        if if_else_id and checks["has_mem0_save"]:
            for edge in edges:
                if edge.get("source") == if_else_id:
                    # Save hängt am If-Else, nicht direkt am LLM
                    checks["mem0_protected"] = True
                    break

        return checks


# ──────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────

def run():
    logger.info("🚀 Agent Watcher starting...")
    logger.info("   Dify: %s", DIFY_URL)
    logger.info("   Mem0: %s", MEM0_URL)
    logger.info("   Poll: %ds | Healthcheck: %ds", POLL_INTERVAL, HC_INTERVAL)

    dify = DifyClient()
    state = load_state()
    last_hc = state.get("last_healthcheck", 0)

    send_telegram("🟢 <b>Agent Watcher gestartet</b>\nÜberwache Dify Agents...")

    while True:
        try:
            now = time.time()

            # ── Agent Poll ──
            apps = dify.get_apps()
            if apps:
                current_ids = {a["id"]: a for a in apps}
                known_ids = set(state.get("agents", {}).keys())

                # Neue Agents
                for app_id, app in current_ids.items():
                    if app_id not in known_ids:
                        checks = dify.check_agent(app_id)
                        issues = []
                        if not checks.get("has_mem0_retrieve"):
                            issues.append("❌ Mem0 Retrieve fehlt")
                        if not checks.get("has_mem0_save"):
                            issues.append("❌ Mem0 Save fehlt")
                        if not checks.get("has_error_handling"):
                            issues.append("❌ Error-Handling fehlt")
                        if not checks.get("has_error_answer"):
                            issues.append("❌ Error-Answer fehlt")
                        if not checks.get("mem0_protected"):
                            issues.append("⚠️ Mem0 nicht geschützt")

                        status = "✅ Vollständig" if not issues else f"⚠️ {len(issues)} Issues"
                        msg = (
                            f"🆕 <b>Neuer Agent erkannt!</b>\n"
                            f"📛 Name: {app.get('name', '?')}\n"
                            f"🤖 Model: {checks.get('model', '?')}\n"
                            f"📊 Status: {status}\n"
                        )
                        if issues:
                            msg += "\n<b>Probleme:</b>\n" + "\n".join(issues)
                        else:
                            msg += "\n✅ Alle Checks bestanden!"

                        send_telegram(msg)
                        logger.info("🆕 New agent: %s → %s", app.get("name"), status)

                        state.setdefault("agents", {})[app_id] = {
                            "name": app.get("name"),
                            "checks": checks,
                            "detected_at": datetime.utcnow().isoformat(),
                        }

                # Gelöschte Agents
                for aid in known_ids - set(current_ids.keys()):
                    name = state["agents"][aid].get("name", "?")
                    send_telegram(f"🗑️ <b>Agent gelöscht:</b> {name}")
                    logger.info("🗑️ Agent deleted: %s", name)
                    del state["agents"][aid]

                save_state(state)

            # ── Healthcheck ──
            if now - last_hc > HC_INTERVAL:
                healthy = 0
                unhealthy = 0
                issues = []

                # Mem0 Check
                try:
                    r = requests.get(f"{MEM0_URL}/health", timeout=5)
                    if r.status_code == 200:
                        healthy += 1
                    else:
                        unhealthy += 1
                        issues.append("Mem0 Server")
                except:
                    unhealthy += 1
                    issues.append("Mem0 Server unreachable")

                # Agent Count
                agent_count = len(state.get("agents", {}))

                if issues:
                    msg = (
                        f"🔴 <b>Healthcheck FAILED</b>\n"
                        f"Agents: {agent_count}\n"
                        f"Issues: {', '.join(issues)}"
                    )
                    send_telegram(msg)
                else:
                    logger.info("💚 Healthcheck OK — %d agents, Mem0 ✅", agent_count)

                last_hc = now
                state["last_healthcheck"] = now
                save_state(state)

        except Exception as e:
            logger.error("Watcher loop error: %s", e)
            send_telegram(f"🔴 <b>Agent Watcher Error:</b>\n{str(e)[:200]}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
