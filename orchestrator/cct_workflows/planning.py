"""
Workflow ⑩ Planning + Roadmap
==============================
Strukturierte Projektplanung:
1. Planner: Erstellt Plan/Sprint/Roadmap
2. Architect: Bewertet technische Machbarkeit
3. Coder: Schaetzt Aufwand
4. Output: Strukturierter Plan mit Schaetzungen
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
import asyncio
import logging
import time
import json

logger = logging.getLogger("workflow.planning")
router = APIRouter(prefix="/workflow", tags=["Workflow-Planning"])

_call_agent_fn = None

def set_agent_caller(fn):
    global _call_agent_fn
    _call_agent_fn = fn

async def _call(agent: str, query: str, user: str, timeout: int = 120) -> Dict:
    if _call_agent_fn is None:
        raise HTTPException(500, "Agent caller not initialized")
    try:
        return await asyncio.wait_for(_call_agent_fn(agent, query, user), timeout=timeout)
    except asyncio.TimeoutError:
        return {"answer": f"[TIMEOUT] {agent}", "conversation_id": "", "message_id": ""}
    except Exception as e:
        return {"answer": f"[ERROR] {agent}: {e}", "conversation_id": "", "message_id": ""}


# ══════════════════════════════════════════
# PLANNING TEMPLATES
# ══════════════════════════════════════════

PLANNING_PROMPTS = {
    "sprint": (
        "Erstelle einen Sprint-Plan (2 Wochen). Strukturiere in:\n"
        "1. Sprint-Ziel (1 Satz)\n"
        "2. User Stories (als 'Als [Rolle] moechte ich [Funktion] um [Nutzen]')\n"
        "3. Tasks pro Story (mit Schaetzung in Stunden)\n"
        "4. Akzeptanzkriterien\n"
        "5. Risiken und Abhaengigkeiten\n\n"
    ),
    "roadmap": (
        "Erstelle eine Produkt-Roadmap fuer die naechsten 3 Monate. Strukturiere in:\n"
        "1. Vision / Gesamtziel\n"
        "2. Monat 1: Features + Milestones\n"
        "3. Monat 2: Features + Milestones\n"
        "4. Monat 3: Features + Milestones\n"
        "5. Abhaengigkeiten und Risiken\n"
        "6. Erfolgskriterien / KPIs\n\n"
    ),
    "feature": (
        "Erstelle eine Feature-Spezifikation. Strukturiere in:\n"
        "1. Problem Statement\n"
        "2. Proposed Solution\n"
        "3. User Stories\n"
        "4. Technische Anforderungen\n"
        "5. Akzeptanzkriterien\n"
        "6. Out of Scope\n"
        "7. Aufwandsschaetzung (S/M/L/XL)\n\n"
    ),
    "epic": (
        "Erstelle ein Epic mit Sub-Tasks. Strukturiere in:\n"
        "1. Epic-Beschreibung\n"
        "2. Business Value\n"
        "3. Sub-Stories (je mit Akzeptanzkriterien)\n"
        "4. Technische Aufgaben\n"
        "5. Priorisierung (MoSCoW: Must/Should/Could/Won't)\n"
        "6. Abhaengigkeiten\n\n"
    ),
    "retrospective": (
        "Erstelle eine Sprint-Retrospektive. Strukturiere in:\n"
        "1. Was lief gut? (Keep)\n"
        "2. Was lief schlecht? (Stop)\n"
        "3. Was koennen wir verbessern? (Start)\n"
        "4. Action Items (konkret, mit Owner)\n\n"
    ),
}


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class PlanRequest(BaseModel):
    query: str
    plan_type: Literal["sprint", "roadmap", "feature", "epic", "retrospective"] = "feature"
    include_technical_review: bool = True
    include_estimation: bool = True
    user: str = "orchestrator"

class PlanResponse(BaseModel):
    workflow: str = "planning"
    plan_type: str
    plan: str
    technical_review: Optional[str] = None
    estimation: Optional[str] = None
    summary: str
    duration_seconds: float

class QuickTaskRequest(BaseModel):
    description: str
    priority: Optional[str] = None
    user: str = "orchestrator"


# ══════════════════════════════════════════
# MAIN ENDPOINT
# ══════════════════════════════════════════

@router.post("/plan", response_model=PlanResponse)
async def create_plan(req: PlanRequest):
    """Erstellt einen strukturierten Plan mit optionaler technischer Bewertung."""
    start = time.time()

    # Phase 1: Planner erstellt Plan
    prompt = PLANNING_PROMPTS.get(req.plan_type, PLANNING_PROMPTS["feature"])
    prompt += f"Anforderung:\n{req.query}"

    plan_result = await _call("planner", prompt, req.user)
    plan = plan_result.get("answer", "")

    # Phase 2: Architect bewertet technische Machbarkeit
    tech_review = None
    if req.include_technical_review:
        review_prompt = (
            "Bewerte die technische Machbarkeit dieses Plans. Pruefe:\n"
            "1. Technische Komplexitaet (1-10)\n"
            "2. Architektur-Kompatibilitaet\n"
            "3. Technische Risiken\n"
            "4. Empfohlene Technologien\n"
            "5. Machbar in der geschaetzten Zeit? (JA/NEIN/BEDINGT)\n\n"
            f"Plan:\n{plan}"
        )
        review_result = await _call("architect", review_prompt, req.user)
        tech_review = review_result.get("answer", "")

    # Phase 3: Coder schaetzt Aufwand
    estimation = None
    if req.include_estimation:
        est_prompt = (
            "Schaetze den Implementierungsaufwand. Gib fuer jeden Task an:\n"
            "- Geschaetzte Stunden\n"
            "- Benoetigte Skills\n"
            "- Gesamt-Aufwand in Personentagen\n"
            "- T-Shirt-Size (S/M/L/XL)\n\n"
            f"Plan:\n{plan}"
        )
        est_result = await _call("coder", est_prompt, req.user)
        estimation = est_result.get("answer", "")

    # Summary
    summary = f"{req.plan_type.upper()}-Plan erstellt"
    if tech_review:
        if "NEIN" in tech_review.upper() or "nicht machbar" in tech_review.lower():
            summary += " — Technisch NICHT machbar laut Architect"
        elif "BEDINGT" in tech_review.upper():
            summary += " — Technisch BEDINGT machbar"
        else:
            summary += " — Technisch machbar"

    return PlanResponse(
        plan_type=req.plan_type,
        plan=plan,
        technical_review=tech_review,
        estimation=estimation,
        summary=summary,
        duration_seconds=round(time.time() - start, 2),
    )


# ══════════════════════════════════════════
# QUICK TASK BREAKDOWN
# ══════════════════════════════════════════

@router.post("/plan/tasks")
async def quick_task_breakdown(req: QuickTaskRequest):
    """Schnelles Task-Breakdown — zerlegt eine Aufgabe in Sub-Tasks."""
    start = time.time()
    prompt = (
        f"Zerlege diese Aufgabe in 3-7 konkrete Sub-Tasks.\n"
        f"Jeder Task: Titel, Beschreibung (1 Satz), Schaetzung (S/M/L).\n"
    )
    if req.priority:
        prompt += f"Prioritaet: {req.priority}\n"
    prompt += f"\nAufgabe: {req.description}"

    result = await _call("planner", prompt, req.user)
    return {
        "workflow": "task_breakdown",
        "tasks": result.get("answer", ""),
        "duration_seconds": round(time.time() - start, 2),
    }


# ══════════════════════════════════════════
# PRIORITIZATION
# ══════════════════════════════════════════

class PrioritizeRequest(BaseModel):
    items: List[str]
    criteria: Optional[str] = None
    user: str = "orchestrator"

@router.post("/plan/prioritize")
async def prioritize_items(req: PrioritizeRequest):
    """Priorisiert eine Liste von Items nach Impact/Effort."""
    items_text = "\n".join(f"{i+1}. {item}" for i, item in enumerate(req.items))
    prompt = (
        "Priorisiere diese Items nach Impact und Effort (Eisenhower + MoSCoW).\n"
        "Gib fuer jedes Item an: Prioritaet (P0-P3), Impact (1-10), Effort (1-10), "
        "Empfehlung (SOFORT / NAECHSTER SPRINT / SPAETER / NICHT MACHEN).\n"
    )
    if req.criteria:
        prompt += f"Zusaetzliche Kriterien: {req.criteria}\n"
    prompt += f"\nItems:\n{items_text}"

    result = await _call("planner", prompt, req.user)
    return {
        "workflow": "prioritization",
        "prioritized": result.get("answer", ""),
        "item_count": len(req.items),
    }
