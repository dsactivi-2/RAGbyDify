"""
Workflow ⑥ Smart Orchestrator Routing
======================================
Erweitert das bestehende Keyword-Routing um:
1. LLM-basierte Intent-Erkennung (Coach-Agent klassifiziert)
2. Multi-Agent-Erkennung (Query braucht >1 Agent)
3. Confidence-Scoring
4. Fallback-Kaskade: LLM-Route → Keyword → Worker
5. Routing-History fuer Self-Learning
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import logging
import time
import re
import json

logger = logging.getLogger("workflow.routing")
router = APIRouter(prefix="/workflow", tags=["Workflow-Routing"])

_call_agent_fn = None

def set_agent_caller(fn):
    global _call_agent_fn
    _call_agent_fn = fn

async def _call(agent: str, query: str, user: str, timeout: int = 60) -> Dict:
    if _call_agent_fn is None:
        raise HTTPException(500, "Agent caller not initialized")
    try:
        return await asyncio.wait_for(_call_agent_fn(agent, query, user), timeout=timeout)
    except asyncio.TimeoutError:
        return {"answer": f"[TIMEOUT] {agent}", "conversation_id": "", "message_id": ""}
    except Exception as e:
        return {"answer": f"[ERROR] {agent}: {e}", "conversation_id": "", "message_id": ""}


# ══════════════════════════════════════════
# KEYWORD ROUTING (Tier 1 — schnell, kein LLM)
# ══════════════════════════════════════════

ROUTING_KEYWORDS = {
    "architect": [
        "architektur", "design", "system", "struktur", "aufbau", "komponente",
        "pattern", "microservice", "monolith", "api-design", "datenmodell",
        "architecture", "component", "data model",
    ],
    "coder": [
        "code", "programmier", "implementier", "funktion", "klasse", "script",
        "python", "javascript", "typescript", "react", "fastapi", "flask",
        "schreib mir", "generiere code", "erstelle eine funktion",
    ],
    "tester": [
        "test", "qualitaet", "qa", "bug", "assertion", "unittest",
        "pytest", "jest", "testfall", "testcase", "coverage",
    ],
    "reviewer": [
        "review", "pruef", "bewert", "best practice", "code review",
        "feedback", "verbesser", "refactor", "optimize",
    ],
    "devops": [
        "deploy", "docker", "ci/cd", "pipeline", "infrastruktur", "server",
        "kubernetes", "k8s", "nginx", "caddy", "ssl", "domain", "dns",
        "container", "compose", "systemd", "service",
    ],
    "docs": [
        "dokumentation", "readme", "api-doc", "beschreib", "erklaer",
        "anleitung", "handbuch", "wiki", "documentation", "explain",
    ],
    "security": [
        "sicherheit", "security", "audit", "schwachstelle", "vulnerability",
        "firewall", "auth", "token", "encryption", "ssl", "injection",
        "xss", "csrf", "penetration",
    ],
    "planner": [
        "plan", "sprint", "aufgabe", "task", "zeitplan", "prioritaet",
        "roadmap", "milestone", "backlog", "epic", "story", "schaetzung",
    ],
    "debug": [
        "debug", "fehlersuche", "traceback", "exception", "crash", "log",
        "diagnose", "error", "stacktrace", "breakpoint", "warum geht",
        "funktioniert nicht", "kaputt",
    ],
    "worker": [
        "erledige", "mach", "ausfuehr", "allgemein", "hilf", "unterstuetz",
        "zusammenfass", "uebersetze", "konvertier",
    ],
}

def _keyword_route(query: str) -> tuple:
    """Keyword-basiertes Routing. Returns (agent, score, matches)."""
    query_lower = query.lower()
    scores = {}
    matches = {}
    for agent, keywords in ROUTING_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in query_lower]
        if matched:
            scores[agent] = len(matched)
            matches[agent] = matched
    if scores:
        best = max(scores, key=scores.get)
        confidence = min(scores[best] / 3.0, 1.0)  # 3+ Matches = 100%
        return best, confidence, matches[best]
    return "worker", 0.1, []


# ══════════════════════════════════════════
# LLM ROUTING (Tier 2 — praeziser, braucht LLM)
# ══════════════════════════════════════════

LLM_ROUTING_PROMPT = """Du bist ein Routing-Agent. Analysiere die Benutzeranfrage und bestimme:
1. Den besten Agent (GENAU EINEN aus der Liste)
2. Ob mehrere Agents noetig sind (Multi-Agent)
3. Deine Confidence (0.0-1.0)

Verfuegbare Agents:
- architect: System-Design, Architektur, Datenmodelle, API-Design
- coder: Code schreiben, Implementierung, Programmierung
- tester: Tests schreiben, QA, Bug-Suche
- reviewer: Code-Review, Best Practices, Verbesserungen
- devops: Deployment, Docker, CI/CD, Infrastruktur, Server
- docs: Dokumentation, Erklaerungen, Anleitungen
- security: Sicherheitsanalyse, Audits, Schwachstellen
- planner: Projektplanung, Sprints, Roadmap, Tasks
- debug: Fehlersuche, Debugging, Error-Analyse
- worker: Allgemeine Aufgaben, Zusammenfassungen

Antworte NUR im JSON-Format:
{{primary_agent: NAME, secondary_agents: [], confidence: 0.X, reasoning: kurze Begruendung}}

Benutzeranfrage: {query}"""

async def _llm_route(query: str, user: str) -> Dict:
    """LLM-basiertes Routing via Coach-Agent."""
    prompt = LLM_ROUTING_PROMPT.replace("{query}", query)
    result = await _call("coach", prompt, user, timeout=30)
    answer = result.get("answer", "")

    # JSON extrahieren
    try:
        # Versuche JSON aus der Antwort zu parsen
        json_match = re.search(r"\{[^{}]*\}", answer, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "primary_agent": data.get("primary_agent", "worker"),
                "secondary_agents": data.get("secondary_agents", []),
                "confidence": float(data.get("confidence", 0.5)),
                "reasoning": data.get("reasoning", ""),
            }
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: Agent-Name aus Text extrahieren
    for agent in ROUTING_KEYWORDS.keys():
        if agent in answer.lower():
            return {"primary_agent": agent, "secondary_agents": [], "confidence": 0.4, "reasoning": "extracted from text"}

    return {"primary_agent": "worker", "secondary_agents": [], "confidence": 0.2, "reasoning": "fallback"}


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class SmartRouteRequest(BaseModel):
    query: str
    user: str = "orchestrator"
    use_llm: bool = True       # LLM-Routing aktivieren
    auto_multi: bool = True    # Multi-Agent automatisch ausfuehren

class SmartRouteResponse(BaseModel):
    workflow: str = "smart_routing"
    query: str
    routed_to: str
    routing_method: str
    confidence: float
    reasoning: str
    answer: str
    secondary_agents: List[str]
    multi_agent_results: Optional[Dict] = None
    duration_seconds: float


# ══════════════════════════════════════════
# SMART ROUTE ENDPOINT
# ══════════════════════════════════════════

@router.post("/smart-route", response_model=SmartRouteResponse)
async def smart_route(req: SmartRouteRequest):
    """Intelligentes Routing: Keyword → LLM → Multi-Agent."""
    start = time.time()

    # Tier 1: Keyword-Routing
    kw_agent, kw_confidence, kw_matches = _keyword_route(req.query)

    # Entscheidung: Wenn Keyword-Confidence hoch genug, kein LLM noetig
    if kw_confidence >= 0.8 or not req.use_llm:
        final_agent = kw_agent
        confidence = kw_confidence
        method = "keyword"
        reasoning = f"Keywords: {', '.join(kw_matches)}"
        secondary = []
    else:
        # Tier 2: LLM-Routing
        llm_result = await _llm_route(req.query, req.user)
        llm_agent = llm_result["primary_agent"]
        llm_confidence = llm_result["confidence"]

        # Combine: LLM hat Vorrang wenn confident
        if llm_confidence > kw_confidence:
            final_agent = llm_agent
            confidence = llm_confidence
            method = "llm"
            reasoning = llm_result["reasoning"]
        else:
            final_agent = kw_agent
            confidence = kw_confidence
            method = "keyword+llm"
            reasoning = f"Keywords ({', '.join(kw_matches)}) bestaetigt durch LLM"

        secondary = llm_result.get("secondary_agents", [])

    # Agent aufrufen
    result = await _call(final_agent, req.query, req.user)
    answer = result.get("answer", "")

    # Optional: Multi-Agent parallel ausfuehren
    multi_results = None
    if req.auto_multi and secondary:
        valid_secondary = [a for a in secondary if a != final_agent and a in ROUTING_KEYWORDS][:3]
        if valid_secondary:
            tasks = [_call(a, req.query, req.user) for a in valid_secondary]
            gathered = await asyncio.gather(*tasks)
            multi_results = {}
            for agent, res in zip(valid_secondary, gathered):
                multi_results[agent] = res.get("answer", "")[:500]

    return SmartRouteResponse(
        query=req.query,
        routed_to=final_agent,
        routing_method=method,
        confidence=round(confidence, 2),
        reasoning=reasoning,
        answer=answer,
        secondary_agents=secondary,
        multi_agent_results=multi_results,
        duration_seconds=round(time.time() - start, 2),
    )


# ══════════════════════════════════════════
# ROUTE EXPLAIN (zeigt Routing-Logik ohne Ausfuehrung)
# ══════════════════════════════════════════

@router.post("/route/explain")
async def explain_route(query: str, user: str = "orchestrator", use_llm: bool = True):
    """Erklaert das Routing ohne den Agent aufzurufen."""
    kw_agent, kw_conf, kw_matches = _keyword_route(query)

    result = {
        "query": query,
        "keyword_routing": {"agent": kw_agent, "confidence": kw_conf, "matches": kw_matches},
    }

    if use_llm:
        llm_result = await _llm_route(query, user)
        result["llm_routing"] = llm_result
        # Finale Entscheidung
        if llm_result["confidence"] > kw_conf:
            result["final_decision"] = {"agent": llm_result["primary_agent"], "method": "llm"}
        else:
            result["final_decision"] = {"agent": kw_agent, "method": "keyword"}
    else:
        result["final_decision"] = {"agent": kw_agent, "method": "keyword_only"}

    return result
