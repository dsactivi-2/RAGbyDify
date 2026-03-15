"""
Workflow ⑦ Debug Pipeline
==========================
Strukturierte Fehleranalyse in 4 Phasen:
1. Error-Parsing: Extrahiert Fehlertyp, Stacktrace, betroffene Dateien
2. Diagnose: Debug-Agent analysiert Root Cause
3. Fix-Vorschlag: Coder-Agent generiert Loesung
4. Validierung: Tester prueft ob Fix korrekt
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import logging
import time
import re

logger = logging.getLogger("workflow.debug")
router = APIRouter(prefix="/workflow", tags=["Workflow-Debug"])

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
# ERROR PARSER (lokal, kein LLM)
# ══════════════════════════════════════════

def _parse_error(error_text: str) -> Dict:
    """Extrahiert strukturierte Infos aus Fehlermeldungen."""
    result = {
        "error_type": "unknown",
        "message": "",
        "file": None,
        "line": None,
        "language": "unknown",
        "stacktrace": [],
        "severity": "medium",
    }

    # Python Traceback
    py_tb = re.findall(r'File "(.+?)", line (\d+)', error_text)
    if py_tb:
        result["language"] = "python"
        result["stacktrace"] = [{"file": f, "line": int(l)} for f, l in py_tb]
        result["file"] = py_tb[-1][0]
        result["line"] = int(py_tb[-1][1])

    # Python Exception Type
    py_err = re.search(r'(\w+Error|\w+Exception|\w+Warning):\s*(.+)', error_text)
    if py_err:
        result["error_type"] = py_err.group(1)
        result["message"] = py_err.group(2).strip()
        result["language"] = "python"

    # JavaScript Error
    js_err = re.search(r'(TypeError|ReferenceError|SyntaxError|RangeError):\s*(.+)', error_text)
    if js_err and result["language"] == "unknown":
        result["error_type"] = js_err.group(1)
        result["message"] = js_err.group(2).strip()
        result["language"] = "javascript"

    # Docker / System errors
    if any(kw in error_text.lower() for kw in ["container", "docker", "oom", "killed"]):
        result["severity"] = "high"
    if any(kw in error_text.lower() for kw in ["segfault", "core dump", "fatal"]):
        result["severity"] = "critical"

    # Fallback message
    if not result["message"]:
        lines = error_text.strip().splitlines()
        result["message"] = lines[-1] if lines else error_text[:200]

    return result


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class DebugRequest(BaseModel):
    error: str                    # Fehlermeldung / Stacktrace
    context: Optional[str] = None # Code-Kontext, was wurde versucht
    code: Optional[str] = None    # Betroffener Code
    include_fix: bool = True
    include_validation: bool = True
    user: str = "orchestrator"

class DebugResponse(BaseModel):
    workflow: str = "debug_pipeline"
    parsed_error: Dict
    diagnosis: str
    root_cause: str
    fix_suggestion: Optional[str] = None
    validation: Optional[str] = None
    severity: str
    confidence: float
    duration_seconds: float


# ══════════════════════════════════════════
# MAIN ENDPOINT
# ══════════════════════════════════════════

@router.post("/debug", response_model=DebugResponse)
async def debug_error(req: DebugRequest):
    """4-Phasen Debug Pipeline: Parse → Diagnose → Fix → Validierung."""
    start = time.time()

    # Phase 1: Error Parsing (lokal)
    parsed = _parse_error(req.error)

    # Phase 2: Diagnose (Debug-Agent)
    diag_prompt = (
        f"Analysiere diesen Fehler und finde die Root Cause:\n\n"
        f"Fehlertyp: {parsed['error_type']}\n"
        f"Nachricht: {parsed['message']}\n"
        f"Sprache: {parsed['language']}\n"
        f"Datei: {parsed.get('file', 'unbekannt')}\n"
        f"Zeile: {parsed.get('line', 'unbekannt')}\n\n"
        f"Vollstaendiger Fehler:\n{req.error}\n"
    )
    if req.context:
        diag_prompt += f"\nKontext: {req.context}\n"
    if req.code:
        diag_prompt += f"\nBetroffener Code:\n{req.code}\n"

    diag_prompt += (
        "\nAntworte strukturiert:\n"
        "1. ROOT CAUSE: (eine klare Zeile)\n"
        "2. ERKLAERUNG: (warum passiert das?)\n"
        "3. BETROFFENE STELLEN: (welche Zeilen/Funktionen)\n"
    )

    diag_result = await _call("debug", diag_prompt, req.user)
    diagnosis = diag_result.get("answer", "")

    # Root Cause extrahieren
    root_cause_match = re.search(r'ROOT CAUSE[:\s]*(.+?)(?:\n|$)', diagnosis, re.IGNORECASE)
    root_cause = root_cause_match.group(1).strip() if root_cause_match else diagnosis[:200]

    # Phase 3: Fix-Vorschlag (Coder-Agent)
    fix = None
    if req.include_fix:
        fix_prompt = (
            f"Behebe diesen Fehler. Root Cause: {root_cause}\n\n"
            f"Fehler: {req.error}\n"
        )
        if req.code:
            fix_prompt += f"\nOriginaler Code:\n{req.code}\n"
        fix_prompt += "\nGib den korrigierten Code als vollstaendigen Codeblock."

        fix_result = await _call("coder", fix_prompt, req.user)
        fix = fix_result.get("answer", "")

    # Phase 4: Validierung (Tester-Agent)
    validation = None
    if req.include_validation and fix:
        val_prompt = (
            f"Validiere ob dieser Fix korrekt ist:\n\n"
            f"Urspruenglicher Fehler: {parsed['error_type']}: {parsed['message']}\n"
            f"Root Cause: {root_cause}\n"
            f"Vorgeschlagener Fix:\n{fix}\n\n"
            "Pruefe: Behebt der Fix das Problem? Fuehrt er neue Probleme ein? "
            "Antworte mit: VALIDE / TEILWEISE / INVALIDE und Begruendung."
        )
        val_result = await _call("tester", val_prompt, req.user)
        validation = val_result.get("answer", "")

    # Confidence berechnen
    confidence = 0.3
    if parsed["error_type"] != "unknown":
        confidence += 0.2
    if fix and len(fix) > 50:
        confidence += 0.2
    if validation and "valide" in validation.lower() and "invalide" not in validation.lower():
        confidence += 0.3
    confidence = min(confidence, 1.0)

    return DebugResponse(
        parsed_error=parsed,
        diagnosis=diagnosis,
        root_cause=root_cause,
        fix_suggestion=fix,
        validation=validation,
        severity=parsed["severity"],
        confidence=round(confidence, 2),
        duration_seconds=round(time.time() - start, 2),
    )


# ══════════════════════════════════════════
# QUICK DEBUG (single-pass)
# ══════════════════════════════════════════

@router.post("/debug/quick")
async def quick_debug(error: str, user: str = "orchestrator"):
    """Schnelle Fehleranalyse — ein Agent-Aufruf."""
    start = time.time()
    parsed = _parse_error(error)
    prompt = f"Analysiere und behebe diesen Fehler kurz und praegnant:\n\n{error}"
    result = await _call("debug", prompt, user)
    return {
        "workflow": "quick_debug",
        "parsed_error": parsed,
        "analysis_and_fix": result.get("answer", ""),
        "duration_seconds": round(time.time() - start, 2),
    }
