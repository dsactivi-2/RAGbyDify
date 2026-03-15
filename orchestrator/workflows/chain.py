"""
Workflow ② Multi-Step Chain
===========================
Erweiterte Agent-Ketten mit:
- Sequentieller Ausfuehrung (Ergebnis A → Eingabe B)
- Paralleler Ausfuehrung (mehrere Agents gleichzeitig, Ergebnisse gemergt)
- Konditionaler Weiterleitung (If-Else basierend auf LLM-Output)
- Vordefinierte Chain-Templates (Architect+Planner, Coder+Tester+Reviewer, etc.)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
import asyncio
import logging
import json
import time

logger = logging.getLogger("workflow.chain")
router = APIRouter(prefix="/workflow", tags=["Workflow-Chain"])


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class ChainStep(BaseModel):
    agent: str
    prompt_template: Optional[str] = None  # {query} und {prev_result} als Platzhalter
    timeout: int = 120

class ParallelGroup(BaseModel):
    agents: List[str]
    merge_strategy: Literal["concat", "best", "structured"] = "concat"
    prompt_template: Optional[str] = None

class ChainRequest(BaseModel):
    query: str
    steps: List[ChainStep]
    user: str = "orchestrator"
    save_memory: bool = True

class ParallelRequest(BaseModel):
    query: str
    group: ParallelGroup
    user: str = "orchestrator"

class TemplateRequest(BaseModel):
    query: str
    template: str  # Name des Templates
    user: str = "orchestrator"

class ConditionalStep(BaseModel):
    agent: str
    condition_keyword: str  # Wenn Keyword im Ergebnis → naechsten Step ausfuehren
    prompt_template: Optional[str] = None

class ConditionalChainRequest(BaseModel):
    query: str
    steps: List[ConditionalStep]
    fallback_agent: str = "worker"
    user: str = "orchestrator"


# ══════════════════════════════════════════
# CHAIN TEMPLATES (vordefinierte Ablaeufe)
# ══════════════════════════════════════════

CHAIN_TEMPLATES = {
    "architecture_review": {
        "description": "Architect entwirft → Reviewer prueft → Planner erstellt Umsetzungsplan",
        "steps": [
            {"agent": "architect", "prompt_template": "Entwirf eine Architektur fuer: {query}"},
            {"agent": "reviewer", "prompt_template": "Pruefe diese Architektur auf Best Practices und Schwachstellen:\n\n{prev_result}"},
            {"agent": "planner", "prompt_template": "Erstelle einen Umsetzungsplan basierend auf dieser Architektur und dem Review:\n\nArchitektur + Review:\n{prev_result}"},
        ]
    },
    "code_complete": {
        "description": "Coder schreibt → Tester testet → Reviewer reviewed → Docs dokumentiert",
        "steps": [
            {"agent": "coder", "prompt_template": "Implementiere: {query}"},
            {"agent": "tester", "prompt_template": "Erstelle umfassende Tests fuer diesen Code:\n\n{prev_result}"},
            {"agent": "reviewer", "prompt_template": "Reviewe Code und Tests auf Qualitaet, Security, Performance:\n\n{prev_result}"},
            {"agent": "docs", "prompt_template": "Erstelle technische Dokumentation fuer:\n\n{prev_result}"},
        ]
    },
    "security_audit": {
        "description": "Security analysiert → Debug prueft → DevOps erstellt Fixes",
        "steps": [
            {"agent": "security", "prompt_template": "Fuehre ein Security-Audit durch fuer: {query}"},
            {"agent": "debug", "prompt_template": "Analysiere die gefundenen Sicherheitsprobleme und priorisiere:\n\n{prev_result}"},
            {"agent": "devops", "prompt_template": "Erstelle einen Patch-Plan mit konkreten Fixes fuer:\n\n{prev_result}"},
        ]
    },
    "feature_planning": {
        "description": "Planner plant → Architect designed → Coder schaetzt Aufwand",
        "steps": [
            {"agent": "planner", "prompt_template": "Plane das Feature: {query}"},
            {"agent": "architect", "prompt_template": "Entwirf die technische Architektur fuer diesen Plan:\n\n{prev_result}"},
            {"agent": "coder", "prompt_template": "Schaetze den Implementierungsaufwand und erstelle ein Code-Skeleton:\n\n{prev_result}"},
        ]
    },
    "deploy_pipeline": {
        "description": "DevOps plant → Security prueft → Tester validiert",
        "steps": [
            {"agent": "devops", "prompt_template": "Erstelle einen Deployment-Plan fuer: {query}"},
            {"agent": "security", "prompt_template": "Pruefe diesen Deployment-Plan auf Sicherheitsrisiken:\n\n{prev_result}"},
            {"agent": "tester", "prompt_template": "Erstelle Pre-Deployment-Tests und Smoke-Tests fuer:\n\n{prev_result}"},
        ]
    },
}


# ══════════════════════════════════════════
# HELPER: Agent aufrufen (nutzt den globalen Orchestrator)
# ══════════════════════════════════════════

_call_agent_fn = None  # Wird von main.py gesetzt

def set_agent_caller(fn):
    """Setzt die Agent-Aufruf-Funktion (aus main.py injiziert)."""
    global _call_agent_fn
    _call_agent_fn = fn

async def _call_agent(agent: str, query: str, user: str, timeout: int = 120) -> Dict:
    """Ruft einen Agent auf mit Timeout."""
    if _call_agent_fn is None:
        raise HTTPException(500, "Agent caller not initialized")
    try:
        return await asyncio.wait_for(
            _call_agent_fn(agent, query, user),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        return {"answer": f"[TIMEOUT] Agent {agent} hat nicht innerhalb von {timeout}s geantwortet.",
                "conversation_id": "", "message_id": "", "sources": None}
    except Exception as e:
        return {"answer": f"[ERROR] Agent {agent}: {str(e)}",
                "conversation_id": "", "message_id": "", "sources": None}


# ══════════════════════════════════════════
# ENDPOINT: Sequentielle Chain
# ══════════════════════════════════════════

@router.post("/chain")
async def run_chain(req: ChainRequest):
    """Fuehrt Agents sequentiell aus. Ergebnis von Step N wird Eingabe fuer Step N+1."""
    results = []
    prev_result = ""
    start = time.time()

    for i, step in enumerate(req.steps):
        # Query zusammenbauen
        if step.prompt_template:
            query = step.prompt_template.replace("{query}", req.query).replace("{prev_result}", prev_result)
        elif prev_result:
            query = f"{req.query}\n\nKontext aus vorherigem Schritt:\n{prev_result}"
        else:
            query = req.query

        result = await _call_agent(step.agent, query, req.user, step.timeout)
        prev_result = result.get("answer", "")
        results.append({
            "step": i + 1,
            "agent": step.agent,
            "answer": prev_result,
            "conversation_id": result.get("conversation_id", ""),
        })

    return {
        "workflow": "multi_step_chain",
        "total_steps": len(results),
        "duration_seconds": round(time.time() - start, 2),
        "final_answer": prev_result,
        "steps": results,
    }


# ══════════════════════════════════════════
# ENDPOINT: Parallele Ausfuehrung
# ══════════════════════════════════════════

@router.post("/parallel")
async def run_parallel(req: ParallelRequest):
    """Fuehrt mehrere Agents gleichzeitig aus und mergt Ergebnisse."""
    start = time.time()

    query = req.group.prompt_template.replace("{query}", req.query) if req.group.prompt_template else req.query

    # Parallel ausfuehren
    tasks = [_call_agent(agent, query, req.user) for agent in req.group.agents]
    results = await asyncio.gather(*tasks)

    agent_results = []
    for agent, result in zip(req.group.agents, results):
        agent_results.append({
            "agent": agent,
            "answer": result.get("answer", ""),
            "conversation_id": result.get("conversation_id", ""),
        })

    # Merge-Strategie
    if req.group.merge_strategy == "concat":
        merged = "\n\n".join(
            f"=== {r['agent'].upper()} ===\n{r['answer']}"
            for r in agent_results if r["answer"]
        )
    elif req.group.merge_strategy == "best":
        # Laengste Antwort = "beste" (heuristisch)
        merged = max((r["answer"] for r in agent_results), key=len, default="")
    elif req.group.merge_strategy == "structured":
        merged = json.dumps({r["agent"]: r["answer"] for r in agent_results}, ensure_ascii=False, indent=2)
    else:
        merged = agent_results[0]["answer"] if agent_results else ""

    return {
        "workflow": "parallel_execution",
        "agents": req.group.agents,
        "merge_strategy": req.group.merge_strategy,
        "duration_seconds": round(time.time() - start, 2),
        "merged_answer": merged,
        "individual_results": agent_results,
    }


# ══════════════════════════════════════════
# ENDPOINT: Konditionale Chain
# ══════════════════════════════════════════

@router.post("/conditional")
async def run_conditional_chain(req: ConditionalChainRequest):
    """Fuehrt Steps nur aus wenn Bedingung erfuellt (Keyword im vorherigen Ergebnis)."""
    results = []
    prev_result = ""
    start = time.time()

    for i, step in enumerate(req.steps):
        # Erster Step wird immer ausgefuehrt
        if i > 0 and step.condition_keyword.lower() not in prev_result.lower():
            results.append({
                "step": i + 1,
                "agent": step.agent,
                "answer": "[SKIPPED] Bedingung nicht erfuellt",
                "condition": step.condition_keyword,
                "matched": False,
            })
            continue

        query = step.prompt_template.replace("{query}", req.query).replace("{prev_result}", prev_result) if step.prompt_template else f"{req.query}\n\n{prev_result}"
        result = await _call_agent(step.agent, query, req.user)
        prev_result = result.get("answer", "")
        results.append({
            "step": i + 1,
            "agent": step.agent,
            "answer": prev_result,
            "condition": step.condition_keyword,
            "matched": True,
        })

    # Falls kein Step getriggert: Fallback
    if not any(r.get("matched") for r in results[1:]) and len(results) > 1:
        fallback = await _call_agent(req.fallback_agent, req.query, req.user)
        results.append({
            "step": len(results) + 1,
            "agent": req.fallback_agent,
            "answer": fallback.get("answer", ""),
            "condition": "FALLBACK",
            "matched": True,
        })
        prev_result = fallback.get("answer", "")

    return {
        "workflow": "conditional_chain",
        "total_steps": len(results),
        "executed_steps": sum(1 for r in results if r.get("matched")),
        "duration_seconds": round(time.time() - start, 2),
        "final_answer": prev_result,
        "steps": results,
    }


# ══════════════════════════════════════════
# ENDPOINT: Template-basierte Chain
# ══════════════════════════════════════════

@router.post("/template/{template_name}")
async def run_template_chain(template_name: str, req: TemplateRequest):
    """Fuehrt eine vordefinierte Chain-Vorlage aus."""
    if template_name not in CHAIN_TEMPLATES:
        raise HTTPException(404, f"Template '{template_name}' nicht gefunden. Verfuegbar: {list(CHAIN_TEMPLATES.keys())}")

    template = CHAIN_TEMPLATES[template_name]
    steps = [ChainStep(**s) for s in template["steps"]]
    chain_req = ChainRequest(query=req.query, steps=steps, user=req.user)
    result = await run_chain(chain_req)
    result["template"] = template_name
    result["template_description"] = template["description"]
    return result

@router.get("/templates")
async def list_templates():
    """Listet alle verfuegbaren Chain-Templates."""
    return {
        "templates": {
            name: {"description": t["description"], "steps": len(t["steps"]),
                   "agents": [s["agent"] for s in t["steps"]]}
            for name, t in CHAIN_TEMPLATES.items()
        }
    }
