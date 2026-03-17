"""
Cloud Code Team — Doctor Agent (Self-Healing & Monitoring)
===========================================================
Workflow-Modul für den Orchestrator.

Funktionen:
1. DIAGNOSE: Prüft alle Agents, Services, Container, Mem0, HippoRAG
2. SELF-HEALING: Automatische Reparatur bei erkannten Problemen
3. WATCHDOG: Hintergrund-Loop der alle 5 Min prüft
4. ABRUF: /doctor/status, /doctor/diagnose, /doctor/heal

Erkannte Probleme und Auto-Fixes:
- Agent antwortet nicht → Retry mit Fallback, Logging
- Mem0 unhealthy → Container-Restart via Docker API
- HippoRAG down → Service-Restart
- Dify API timeout → erhöhter Timeout + Retry
- Service nicht erreichbar → Neustart-Versuch
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import httpx
import asyncio
import json
import time
import logging
import subprocess
import os
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger("doctor-agent")
router = APIRouter(prefix="/doctor", tags=["Doctor Agent"])

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════

DIFY_API_URL = os.getenv("DIFY_API_URL", "https://difyv2.activi.io/v1")
MEM0_URL = os.getenv("MEM0_URL", "http://localhost:8002")
HIPPORAG_URL = os.getenv("HIPPORAG_URL", "http://localhost:8001")
ORCHESTRATOR_URL = "http://localhost:8000"

# Healing-Aktionen die der Doctor ausführen darf
ALLOWED_HEAL_ACTIONS = [
    "restart_mem0",
    "restart_hipporag",
    "retry_agent",
    "clear_agent_cache",
    "restart_orchestrator",
]

# ══════════════════════════════════════════
# STATE MANAGEMENT
# ══════════════════════════════════════════

class AgentHealth:
    """Trackt den Gesundheitszustand eines einzelnen Agents"""
    def __init__(self, name: str):
        self.name = name
        self.consecutive_failures = 0
        self.last_success: Optional[float] = None
        self.last_failure: Optional[float] = None
        self.last_error: Optional[str] = None
        self.total_calls = 0
        self.total_failures = 0
        self.avg_response_time = 0.0
        self.is_healthy = True
        self.healing_attempts = 0
        self.last_heal: Optional[float] = None

    def record_success(self, response_time: float):
        self.consecutive_failures = 0
        self.last_success = time.time()
        self.total_calls += 1
        self.is_healthy = True
        # Rolling average
        if self.avg_response_time == 0:
            self.avg_response_time = response_time
        else:
            self.avg_response_time = self.avg_response_time * 0.8 + response_time * 0.2

    def record_failure(self, error: str):
        self.consecutive_failures += 1
        self.last_failure = time.time()
        self.last_error = error
        self.total_calls += 1
        self.total_failures += 1
        if self.consecutive_failures >= 3:
            self.is_healthy = False

    def to_dict(self):
        return {
            "name": self.name,
            "is_healthy": self.is_healthy,
            "consecutive_failures": self.consecutive_failures,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "success_rate": round((1 - self.total_failures / max(self.total_calls, 1)) * 100, 1),
            "avg_response_time_s": round(self.avg_response_time, 2),
            "last_success": datetime.fromtimestamp(self.last_success).isoformat() if self.last_success else None,
            "last_failure": datetime.fromtimestamp(self.last_failure).isoformat() if self.last_failure else None,
            "last_error": self.last_error,
            "healing_attempts": self.healing_attempts,
        }


class ServiceHealth:
    """Trackt Service-Status (Mem0, HippoRAG, Dify, etc.)"""
    def __init__(self, name: str, url: str, health_path: str = "/health"):
        self.name = name
        self.url = url
        self.health_path = health_path
        self.is_healthy = True
        self.consecutive_failures = 0
        self.last_check: Optional[float] = None
        self.last_error: Optional[str] = None
        self.response_time: float = 0.0
        self.healing_in_progress = False

    def to_dict(self):
        return {
            "name": self.name,
            "url": self.url,
            "is_healthy": self.is_healthy,
            "consecutive_failures": self.consecutive_failures,
            "last_check": datetime.fromtimestamp(self.last_check).isoformat() if self.last_check else None,
            "last_error": self.last_error,
            "response_time_s": round(self.response_time, 3),
            "healing_in_progress": self.healing_in_progress,
        }


class DoctorState:
    """Globaler State des Doctor Agents"""
    def __init__(self):
        self.agents: Dict[str, AgentHealth] = {}
        self.services: Dict[str, ServiceHealth] = {}
        self.heal_log: List[Dict] = []  # Letzte 100 Heal-Aktionen
        self.watchdog_running = False
        self.watchdog_interval = 300  # 5 Minuten
        self.last_full_check: Optional[float] = None
        self.auto_heal_enabled = True

        # Services initialisieren
        self.services["mem0"] = ServiceHealth("Mem0", MEM0_URL, "/health")
        self.services["hipporag"] = ServiceHealth("HippoRAG", HIPPORAG_URL, "/health")
        self.services["dify"] = ServiceHealth("Dify", "http://localhost:3080", "/console/api/setup")
        self.services["qdrant_mem0"] = ServiceHealth("Qdrant-Mem0", "http://localhost:16333", "/collections")
        self.services["neo4j"] = ServiceHealth("Neo4j", "http://localhost:7474", "/")
        self.services["ollama"] = ServiceHealth("Ollama", "http://localhost:11434", "/api/tags")

    def get_agent(self, name: str) -> AgentHealth:
        if name not in self.agents:
            self.agents[name] = AgentHealth(name)
        return self.agents[name]

    def log_heal(self, action: str, target: str, success: bool, detail: str = ""):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "target": target,
            "success": success,
            "detail": detail,
        }
        self.heal_log.append(entry)
        if len(self.heal_log) > 100:
            self.heal_log = self.heal_log[-100:]
        logger.info(f"HEAL: {action} → {target} | {'OK' if success else 'FAILED'} | {detail}")


# Global State
state = DoctorState()

# ══════════════════════════════════════════
# DIAGNOSE FUNKTIONEN
# ══════════════════════════════════════════

async def check_service(svc: ServiceHealth) -> bool:
    """Einzelnen Service prüfen"""
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{svc.url}{svc.health_path}")
            elapsed = time.time() - start
            svc.response_time = elapsed
            svc.last_check = time.time()

            if resp.status_code in (200, 301, 302, 307):
                svc.is_healthy = True
                svc.consecutive_failures = 0
                svc.last_error = None
                return True
            else:
                svc.consecutive_failures += 1
                svc.last_error = f"HTTP {resp.status_code}"
                if svc.consecutive_failures >= 2:
                    svc.is_healthy = False
                return False
    except Exception as e:
        svc.last_check = time.time()
        svc.consecutive_failures += 1
        svc.last_error = str(e)[:200]
        svc.response_time = 0
        if svc.consecutive_failures >= 2:
            svc.is_healthy = False
        return False


async def check_agent_health(agent_name: str, api_key: str) -> bool:
    """Einzelnen Agent mit Ping-Query testen"""
    agent = state.get_agent(agent_name)
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{DIFY_API_URL}/chat-messages",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "inputs": {},
                    "query": "ping",
                    "response_mode": "blocking",
                    "user": "doctor-agent",
                },
            )
            elapsed = time.time() - start

            if resp.status_code == 200:
                agent.record_success(elapsed)
                return True
            else:
                agent.record_failure(f"HTTP {resp.status_code}: {resp.text[:100]}")
                return False
    except Exception as e:
        elapsed = time.time() - start
        agent.record_failure(str(e)[:200])
        return False


async def full_diagnose() -> Dict:
    """Komplette System-Diagnose"""
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "services": {},
        "agents": {},
        "problems": [],
        "recommendations": [],
    }

    # 1. Services parallel prüfen
    service_tasks = {name: check_service(svc) for name, svc in state.services.items()}
    service_results = {}
    for name, task in service_tasks.items():
        service_results[name] = await task

    for name, svc in state.services.items():
        results["services"][name] = svc.to_dict()
        if not svc.is_healthy:
            results["problems"].append({
                "type": "service_down",
                "target": name,
                "error": svc.last_error,
                "severity": "critical" if name in ("mem0", "dify") else "warning",
            })

    # 2. Agent-Status aus gespeichertem State
    for name, agent in state.agents.items():
        results["agents"][name] = agent.to_dict()
        if not agent.is_healthy:
            results["problems"].append({
                "type": "agent_unhealthy",
                "target": name,
                "error": agent.last_error,
                "consecutive_failures": agent.consecutive_failures,
                "severity": "high",
            })

    # 3. Spezial-Checks
    # Mem0 GET hängt? (bekanntes Problem)
    if state.services["mem0"].is_healthy:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(f"{MEM0_URL}/v1/memories/?user_id=doctor-test")
                if resp.status_code != 200:
                    results["problems"].append({
                        "type": "mem0_get_blocked",
                        "target": "mem0",
                        "error": "GET /memories hängt — Container unhealthy",
                        "severity": "critical",
                    })
        except:
            results["problems"].append({
                "type": "mem0_get_blocked",
                "target": "mem0",
                "error": "GET /memories Timeout — Container braucht Restart",
                "severity": "critical",
            })

    # 4. Recommendations basierend auf Problemen
    for problem in results["problems"]:
        if problem["type"] == "service_down" and problem["target"] == "mem0":
            results["recommendations"].append({
                "action": "restart_mem0",
                "reason": "Mem0 nicht erreichbar oder unhealthy",
                "auto_heal": True,
            })
        elif problem["type"] == "mem0_get_blocked":
            results["recommendations"].append({
                "action": "restart_mem0",
                "reason": "Mem0 GET blockiert — kein Auto-Restart (kann durch langsame LLM-Ops kommen)",
                "auto_heal": False,  # Deaktiviert: llama3.2:3b benoetigt 30s, timeout war False-Positive
            })
        elif problem["type"] == "service_down" and problem["target"] == "hipporag":
            results["recommendations"].append({
                "action": "restart_hipporag",
                "reason": "HippoRAG Service nicht erreichbar",
                "auto_heal": True,
            })
        elif problem["type"] == "agent_unhealthy":
            results["recommendations"].append({
                "action": "retry_agent",
                "target": problem["target"],
                "reason": f"Agent {problem['target']} hat {problem['consecutive_failures']} aufeinanderfolgende Fehler",
                "auto_heal": True,
            })

    state.last_full_check = time.time()
    return results


# ══════════════════════════════════════════
# HEALING FUNKTIONEN
# ══════════════════════════════════════════

async def heal_mem0() -> bool:
    """Mem0 Container neustarten"""
    svc = state.services["mem0"]
    if svc.healing_in_progress:
        return False
    svc.healing_in_progress = True
    try:
        result = subprocess.run(
            ["docker", "restart", "cct-mem0"],
            capture_output=True, text=True, timeout=30,
        )
        success = result.returncode == 0
        state.log_heal("restart_mem0", "cct-mem0", success, result.stdout + result.stderr)
        # Dossier-Eintrag fuer alle betroffenen Agents
        try:
            for a in state.agents:
                asyncio.create_task(update_dossier(a, "SYSTEM", "Mem0 Container neugestartet — Heilung " + ("erfolgreich" if success else "fehlgeschlagen")))
        except: pass
        if success:
            # Warte bis Container hochfährt
            await asyncio.sleep(10)
            await check_service(svc)
        return success
    except Exception as e:
        state.log_heal("restart_mem0", "cct-mem0", False, str(e))
        return False
    finally:
        svc.healing_in_progress = False


async def heal_hipporag() -> bool:
    """HippoRAG Service neustarten"""
    svc = state.services["hipporag"]
    if svc.healing_in_progress:
        return False
    svc.healing_in_progress = True
    try:
        result = subprocess.run(
            ["systemctl", "restart", "hipporag"],
            capture_output=True, text=True, timeout=30,
        )
        success = result.returncode == 0
        state.log_heal("restart_hipporag", "hipporag", success, result.stdout + result.stderr)
        if success:
            await asyncio.sleep(5)
            await check_service(svc)
        return success
    except Exception as e:
        state.log_heal("restart_hipporag", "hipporag", False, str(e))
        return False
    finally:
        svc.healing_in_progress = False


async def heal_agent(agent_name: str) -> bool:
    """Agent-spezifische Heilung: Cache leeren, Retry"""
    agent = state.get_agent(agent_name)
    agent.healing_attempts += 1
    agent.last_heal = time.time()

    # Versuch 1: Mem0 Cache für Agent leeren (falls Mem0 das Problem ist)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Ping Mem0 für diesen Agent
            resp = await client.post(
                f"{MEM0_URL}/v1/memories/search/",
                json={"query": "test", "user_id": f"cct-{agent_name}", "limit": 1},
            )
            mem0_ok = resp.status_code == 200
    except:
        mem0_ok = False

    if not mem0_ok:
        state.log_heal("retry_agent", agent_name, False, "Mem0 nicht erreichbar, Agent kann nicht heilen ohne Memory")
        return False

    # Versuch 2: Agent direkt testen
    try:
        resp_data = await _call_agent_fn(agent_name, "Doctor-Check: Bist du funktionsfähig?", "doctor-agent")
        if resp_data and resp_data.get("answer"):
            agent.record_success(0)
            state.log_heal("retry_agent", agent_name, True, f"Agent antwortet wieder: {resp_data['answer'][:50]}")
            asyncio.create_task(update_dossier(agent_name, "HEILUNG", "Agent antwortet wieder nach Retry"))
            return True
    except Exception as e:
        state.log_heal("retry_agent", agent_name, False, str(e)[:200])
        asyncio.create_task(update_dossier(agent_name, "AUSFALL", "Heilungsversuch fehlgeschlagen: " + str(e)[:100]))

    return False


async def auto_heal(diagnose_result: Dict) -> Dict:
    """Automatische Heilung basierend auf Diagnose"""
    if not state.auto_heal_enabled:
        return {"status": "disabled", "message": "Auto-Heal ist deaktiviert"}

    healed = []
    failed = []

    for rec in diagnose_result.get("recommendations", []):
        if not rec.get("auto_heal"):
            continue

        action = rec["action"]
        target = rec.get("target", action)

        if action == "restart_mem0":
            success = await heal_mem0()
        elif action == "restart_hipporag":
            success = await heal_hipporag()
        elif action == "retry_agent":
            success = await heal_agent(target)
        else:
            continue

        if success:
            healed.append({"action": action, "target": target})
        else:
            failed.append({"action": action, "target": target})

    return {
        "healed": healed,
        "failed": failed,
        "total_healed": len(healed),
        "total_failed": len(failed),
    }


# ══════════════════════════════════════════
# WATCHDOG (Hintergrund-Loop)
# ══════════════════════════════════════════

async def watchdog_loop():
    """Hintergrund-Task: Prüft alle 5 Min den System-Status"""
    logger.info("🩺 Doctor Watchdog gestartet (Intervall: %ds)", state.watchdog_interval)
    state.watchdog_running = True

    while state.watchdog_running:
        try:
            # Diagnose
            result = await full_diagnose()
            problems = result.get("problems", [])

            if problems:
                critical = [p for p in problems if p.get("severity") == "critical"]
                logger.warning("🩺 Watchdog: %d Probleme gefunden (%d kritisch)", len(problems), len(critical))

                # Dossier-Eintraege fuer betroffene Agents
                for p in problems:
                    if p.get("type") == "agent_unhealthy":
                        asyncio.create_task(update_dossier(p["target"], "WARNUNG", "Watchdog hat Problem erkannt: " + str(p.get("error", ""))[:80]))

                # Auto-Heal bei kritischen Problemen
                if critical and state.auto_heal_enabled:
                    heal_result = await auto_heal(result)
                    logger.info("🩺 Auto-Heal: %d geheilt, %d fehlgeschlagen",
                                heal_result["total_healed"], heal_result["total_failed"])
            else:
                logger.info("🩺 Watchdog: Alle Systeme OK")

        except Exception as e:
            logger.error("🩺 Watchdog Error: %s", e)

        await asyncio.sleep(state.watchdog_interval)


# Agent-Caller (wird vom Orchestrator injiziert)
_call_agent_fn = None

def set_agent_caller(fn):
    global _call_agent_fn
    _call_agent_fn = fn


# ══════════════════════════════════════════
# API ENDPUNKTE
# ══════════════════════════════════════════

class HealRequest(BaseModel):
    action: str
    target: Optional[str] = None
    force: bool = False


@router.get("/status")
async def doctor_status():
    """Gesamtstatus aller Agents und Services"""
    services_status = {}
    for name, svc in state.services.items():
        services_status[name] = svc.to_dict()

    agents_status = {}
    for name, agent in state.agents.items():
        agents_status[name] = agent.to_dict()

    healthy_services = sum(1 for s in state.services.values() if s.is_healthy)
    healthy_agents = sum(1 for a in state.agents.values() if a.is_healthy)
    total_services = len(state.services)
    total_agents = len(state.agents)

    overall = "healthy"
    if healthy_services < total_services or healthy_agents < total_agents:
        overall = "degraded"
    critical_services = ["mem0", "dify"]
    if any(not state.services[s].is_healthy for s in critical_services if s in state.services):
        overall = "critical"

    return {
        "status": overall,
        "services": services_status,
        "services_healthy": f"{healthy_services}/{total_services}",
        "agents": agents_status,
        "agents_healthy": f"{healthy_agents}/{total_agents}",
        "watchdog_running": state.watchdog_running,
        "auto_heal_enabled": state.auto_heal_enabled,
        "last_full_check": datetime.fromtimestamp(state.last_full_check).isoformat() if state.last_full_check else None,
        "recent_heals": state.heal_log[-10:],
    }


@router.get("/diagnose")
async def diagnose_endpoint():
    """Vollständige System-Diagnose durchführen"""
    return await full_diagnose()


@router.post("/heal")
async def heal_endpoint(req: HealRequest):
    """Manuelle Healing-Aktion auslösen"""
    if req.action not in ALLOWED_HEAL_ACTIONS:
        raise HTTPException(400, f"Unbekannte Aktion: {req.action}. Erlaubt: {ALLOWED_HEAL_ACTIONS}")

    if req.action == "restart_mem0":
        success = await heal_mem0()
    elif req.action == "restart_hipporag":
        success = await heal_hipporag()
    elif req.action == "retry_agent":
        if not req.target:
            raise HTTPException(400, "target ist Pflichtfeld für retry_agent")
        success = await heal_agent(req.target)
    else:
        raise HTTPException(400, f"Aktion {req.action} noch nicht implementiert")

    return {
        "action": req.action,
        "target": req.target,
        "success": success,
        "heal_log": state.heal_log[-5:],
    }


@router.post("/heal/auto")
async def auto_heal_endpoint():
    """Automatische Diagnose + Healing in einem Schritt"""
    diagnose = await full_diagnose()
    heal_result = await auto_heal(diagnose)
    return {
        "diagnose": diagnose,
        "healing": heal_result,
    }


@router.get("/heal/log")
async def heal_log():
    """Letzte 100 Heal-Aktionen"""
    return {"log": state.heal_log, "count": len(state.heal_log)}


@router.post("/watchdog/start")
async def start_watchdog(interval: int = 300):
    """Watchdog starten"""
    if state.watchdog_running:
        return {"status": "already_running", "interval": state.watchdog_interval}
    state.watchdog_interval = interval
    asyncio.create_task(watchdog_loop())
    return {"status": "started", "interval": interval}


@router.post("/watchdog/stop")
async def stop_watchdog():
    """Watchdog stoppen"""
    state.watchdog_running = False
    return {"status": "stopped"}


@router.put("/config")
async def update_config(auto_heal: Optional[bool] = None, watchdog_interval: Optional[int] = None):
    """Doctor-Konfiguration ändern"""
    if auto_heal is not None:
        state.auto_heal_enabled = auto_heal
    if watchdog_interval is not None:
        state.watchdog_interval = max(60, watchdog_interval)
    return {
        "auto_heal_enabled": state.auto_heal_enabled,
        "watchdog_interval": state.watchdog_interval,
    }


# ══════════════════════════════════════════
# SELF-HEALING MIDDLEWARE
# Wird in den Orchestrator's /task Endpoint eingehängt
# ══════════════════════════════════════════

async def self_healing_call(original_fn, api_key: str, query: str, user: str,
                             conversation_id: str = "", inputs=None, agent: str = "worker",
                             max_retries: int = 2):
    """
    Wrapper um den Agent-Call mit Self-Healing:
    1. Versuch: Normal aufrufen
    2. Bei Fehler: Agent-Gesundheit tracken
    3. Bei 2+ Fehlern: Auto-Diagnose + Heal
    4. Retry nach Healing
    """
    agent_health = state.get_agent(agent)
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            start = time.time()
            result = await original_fn(api_key, query, user, conversation_id, inputs)
            elapsed = time.time() - start

            # Erfolg tracken
            agent_health.record_success(elapsed)

            # Bei Erfolg nach Retry: Dossier-Eintrag
            if attempt > 0:
                asyncio.create_task(update_dossier(agent, "HEILUNG", f"Agent antwortet nach {attempt} Retries (Antwortzeit: {elapsed:.1f}s)"))

            # Leere Antwort = auch ein Problem
            if not result.get("answer"):
                agent_health.record_failure("Leere Antwort vom Agent")
                if attempt < max_retries:
                    logger.warning(f"🩺 Agent {agent}: Leere Antwort, Retry {attempt + 1}/{max_retries}")
                    await asyncio.sleep(2)
                    continue
            return result

        except Exception as e:
            elapsed = time.time() - start
            last_error = str(e)
            agent_health.record_failure(last_error)
            logger.warning(f"🩺 Agent {agent}: Fehler (Versuch {attempt + 1}): {last_error[:100]}")

            if attempt < max_retries:
                # Kurze Pause vor Retry
                await asyncio.sleep(3 * (attempt + 1))

                # Bei wiederholtem Fehler: Diagnose starten
                if agent_health.consecutive_failures >= 2:
                    logger.info(f"🩺 Auto-Diagnose für Agent {agent} gestartet")
                    # Service-Checks parallel
                    await check_service(state.services.get("mem0", ServiceHealth("mem0", MEM0_URL)))
                    await check_service(state.services.get("dify", ServiceHealth("dify", "http://localhost:3080")))

                    # Mem0 kaputt? Heilen!
                    mem0_svc = state.services.get("mem0")
                    if mem0_svc and not mem0_svc.is_healthy:
                        logger.info("🩺 Mem0 unhealthy erkannt, starte Healing...")
                        await heal_mem0()

    # Alle Retries fehlgeschlagen
    logger.error(f"🩺 Agent {agent}: Alle {max_retries + 1} Versuche fehlgeschlagen. Letzter Fehler: {last_error}")
    asyncio.create_task(update_dossier(agent, "AUSFALL", f"Alle {max_retries + 1} Versuche fehlgeschlagen. Fehler: {last_error[:100]}"))
    raise Exception(f"Agent {agent} nicht erreichbar nach {max_retries + 1} Versuchen: {last_error}")


# ══════════════════════════════════════════
# STARTUP HOOK
# ══════════════════════════════════════════

_startup_done = False

async def doctor_startup():
    """Wird beim Orchestrator-Start aufgerufen"""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True

    logger.info("🩺 Doctor Agent initialisiert")

    # Initial-Diagnose (non-blocking)
    try:
        result = await full_diagnose()
        problems = result.get("problems", [])
        if problems:
            logger.warning(f"🩺 Startup-Diagnose: {len(problems)} Probleme gefunden")
            for p in problems:
                logger.warning(f"  → [{p['severity']}] {p['type']}: {p.get('target')} — {p.get('error', '')[:80]}")
        else:
            logger.info("🩺 Startup-Diagnose: Alle Systeme OK")
    except Exception as e:
        logger.error(f"🩺 Startup-Diagnose fehlgeschlagen: {e}")

    # Watchdog starten
    asyncio.create_task(watchdog_loop())
    logger.info("🩺 Watchdog gestartet (Intervall: %ds, Auto-Heal: %s)",
                state.watchdog_interval, state.auto_heal_enabled)


# ══════════════════════════════════════════════════════════════
# KRANKENDOSSIER — Persistente Mem0-Memory pro Agent
# Jeder Agent bekommt ein "medizinisches Dossier" das der Doctor
# in Mem0 speichert: Ausfälle, Heilungen, Performance-Trends,
# bekannte Probleme, letzte Diagnosen.
# ══════════════════════════════════════════════════════════════

DOCTOR_MEM0_USER = "cct-doctor"  # Eigener Mem0-Namespace für den Doctor

async def _mem0_save(text: str, user_id: str = DOCTOR_MEM0_USER) -> bool:
    """Speichert einen Eintrag in Mem0 unter dem Doctor-Namespace"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{MEM0_URL}/v1/memories/",
                json={
                    "messages": [{"role": "user", "content": text}],
                    "user_id": user_id,
                },
            )
            if resp.status_code in (200, 201):
                logger.info(f"🩺 Dossier gespeichert: {text[:60]}...")
                return True
            logger.warning(f"🩺 Dossier save fehlgeschlagen: HTTP {resp.status_code}")
            return False
    except Exception as e:
        logger.warning(f"🩺 Dossier save Fehler: {e}")
        return False


async def _mem0_search(query: str, user_id: str = DOCTOR_MEM0_USER, limit: int = 10) -> list:
    """Durchsucht das Doctor-Memory nach relevanten Einträgen"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{MEM0_URL}/v1/memories/search/",
                json={
                    "query": query,
                    "user_id": user_id,
                    "limit": limit,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data) if isinstance(data, dict) else data
                return results if isinstance(results, list) else []
            return []
    except Exception as e:
        logger.warning(f"🩺 Dossier search Fehler: {e}")
        return []


async def _mem0_get_all(user_id: str = DOCTOR_MEM0_USER) -> list:
    """Holt alle Memories eines User-IDs"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{MEM0_URL}/v1/memories/?user_id={user_id}")
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data) if isinstance(data, dict) else data
                return results if isinstance(results, list) else []
            return []
    except Exception as e:
        logger.warning(f"🩺 Dossier get_all Fehler: {e}")
        return []


async def update_dossier(agent_name: str, event_type: str, details: str):
    """
    Schreibt einen Eintrag ins Krankendossier eines Agents.

    Event-Typen:
    - AUSFALL: Agent hat nicht geantwortet
    - HEILUNG: Agent wurde erfolgreich repariert
    - WARNUNG: Performance-Degradation erkannt
    - DIAGNOSE: Regelmäßiger Check-Ergebnis
    - SYSTEM: Service-Problem das den Agent betrifft
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Mem0 braucht konversationelles Format (nicht Log-Syntax)
    # damit die LLM-Extraktion die Fakten als erinnerungswürdig erkennt
    event_templates = {
        "AUSFALL": f"Der {agent_name}-Agent ist am {timestamp} ausgefallen. Details: {details}",
        "HEILUNG": f"Der {agent_name}-Agent wurde am {timestamp} erfolgreich geheilt. Maßnahme: {details}",
        "WARNUNG": f"Warnung für den {agent_name}-Agent am {timestamp}: {details}",
        "DIAGNOSE": f"Diagnose-Ergebnis für den {agent_name}-Agent am {timestamp}: {details}",
        "SYSTEM": f"System-Problem betrifft den {agent_name}-Agent am {timestamp}: {details}",
        "NOTIZ": f"Notiz zum {agent_name}-Agent am {timestamp}: {details}",
    }
    entry = event_templates.get(event_type, f"Der {agent_name}-Agent: {event_type} am {timestamp}. {details}")

    # In Mem0 speichern unter doctor-{agent} Namespace
    dossier_user = f"doctor-{agent_name}"
    await _mem0_save(f"Merke dir: {entry}", user_id=dossier_user)

    # Auch ins zentrale Doctor-Memory (konversationell)
    central_entry = f"Merke dir: {entry}"
    await _mem0_save(central_entry, user_id=DOCTOR_MEM0_USER)

    # JSON-Fallback: Dossier IMMER lokal speichern (Mem0 kann verwerfen)
    try:
        from pathlib import Path as _P
        import json as _json
        _ddir = _P("/opt/cloud-code/data/dossiers")
        _ddir.mkdir(parents=True, exist_ok=True)
        _dfile = _ddir / f"{agent_name}.json"
        _existing = []
        if _dfile.exists():
            _existing = _json.loads(_dfile.read_text())
        _existing.append({"ts": timestamp, "event": event_type, "detail": details, "entry": entry})
        _dfile.write_text(_json.dumps(_existing, indent=2, ensure_ascii=False))
    except Exception as _e:
        logger.warning(f"Dossier JSON-Fallback Fehler: {_e}")


async def get_dossier(agent_name: str) -> dict:
    """Holt das komplette Krankendossier eines Agents"""
    dossier_user = f"doctor-{agent_name}"

    # Alle Dossier-Einträge: Mem0 + JSON-Fallback zusammenführen
    entries = await _mem0_get_all(user_id=dossier_user)

    # JSON-Fallback-Einträge laden
    try:
        from pathlib import Path as _P
        import json as _json
        _dfile = _P(f"/opt/cloud-code/data/dossiers/{agent_name}.json")
        if _dfile.exists():
            json_entries = _json.loads(_dfile.read_text())
            # Merge: JSON-Einträge die nicht in Mem0 sind hinzufügen
            mem0_texts = {e.get("memory", e.get("text", ""))[:50] for e in entries}
            for je in json_entries:
                if je.get("entry", "")[:50] not in mem0_texts:
                    entries.append({
                        "memory": je.get("entry", je.get("detail", "")),
                        "created_at": je.get("ts", "unknown"),
                        "source": "json-fallback",
                    })
    except Exception:
        pass

    # Agent-Health aus State
    agent_health = state.get_agent(agent_name) if agent_name in state.agents else None

    return {
        "agent": agent_name,
        "dossier_entries": len(entries),
        "entries": [
            {
                "memory": e.get("memory", e.get("text", str(e))),
                "created_at": e.get("created_at", "unknown"),
            }
            for e in entries
        ] if entries else [],
        "current_health": agent_health.to_dict() if agent_health else {"status": "nie getestet"},
        "mem0_user_id": dossier_user,
    }


async def get_all_dossiers() -> dict:
    """Holt alle Krankendossiers (Übersicht)"""
    agents = ["architect", "coder", "tester", "reviewer", "devops",
              "docs", "security", "planner", "debug", "worker", "coach"]

    dossiers = {}
    for agent in agents:
        dossier_user = f"doctor-{agent}"
        entries = await _mem0_get_all(user_id=dossier_user)
        agent_health = state.agents.get(agent)

        dossiers[agent] = {
            "entries": len(entries),
            "is_healthy": agent_health.is_healthy if agent_health else None,
            "total_calls": agent_health.total_calls if agent_health else 0,
            "total_failures": agent_health.total_failures if agent_health else 0,
            "last_event": entries[0].get("memory", "—") if entries else "Kein Eintrag",
        }

    # Zentrale Doctor-Memories
    doctor_memories = await _mem0_get_all(user_id=DOCTOR_MEM0_USER)

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "dossiers": dossiers,
        "doctor_central_memories": len(doctor_memories),
        "total_dossier_entries": sum(d["entries"] for d in dossiers.values()),
    }


# ── Dossier API-Endpunkte ──

@router.get("/dossier/{agent_name}")
async def get_agent_dossier(agent_name: str):
    """Krankendossier eines einzelnen Agents abrufen"""
    return await get_dossier(agent_name)


@router.get("/dossiers")
async def get_all_agent_dossiers():
    """Alle Krankendossiers (Übersicht)"""
    return await get_all_dossiers()


@router.post("/dossier/{agent_name}/note")
async def add_dossier_note(agent_name: str, note: str, event_type: str = "NOTIZ"):
    """Manuellen Eintrag ins Dossier hinzufügen"""
    await update_dossier(agent_name, event_type, note)
    return {"status": "ok", "agent": agent_name, "event_type": event_type, "note": note}


@router.get("/memory")
async def get_doctor_memory():
    """Komplettes Doctor-Memory (zentral)"""
    memories = await _mem0_get_all(user_id=DOCTOR_MEM0_USER)
    return {
        "user_id": DOCTOR_MEM0_USER,
        "total": len(memories),
        "memories": [
            {
                "text": m.get("memory", m.get("text", str(m))),
                "created_at": m.get("created_at", "unknown"),
            }
            for m in memories
        ],
    }
