"""
Workflow ⑨ Auto-Documentation
==============================
Automatische Dokumentationsgenerierung:
1. Code-Analyse: Extrahiert Struktur (Klassen, Funktionen, Endpoints)
2. Docs-Agent: Generiert Dokumentation
3. Output-Formate: Markdown, Docstrings, API-Docs, README
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
import asyncio
import logging
import time
import re
import ast

logger = logging.getLogger("workflow.auto_doc")
router = APIRouter(prefix="/workflow", tags=["Workflow-AutoDoc"])

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
# CODE STRUCTURE EXTRACTOR
# ══════════════════════════════════════════

def _extract_python_structure(code: str) -> Dict:
    """Extrahiert Python-Code-Struktur via AST."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"error": "Syntax Error — kann nicht geparst werden"}

    structure = {"classes": [], "functions": [], "imports": [], "constants": [], "endpoints": []}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            structure["classes"].append({
                "name": node.name,
                "line": node.lineno,
                "methods": methods,
                "docstring": ast.get_docstring(node) or "",
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Nur Top-Level Funktionen (nicht Methoden)
            if not any(isinstance(p, ast.ClassDef) for p in ast.walk(tree)):
                args = [a.arg for a in node.args.args if a.arg != "self"]
                structure["functions"].append({
                    "name": node.name,
                    "line": node.lineno,
                    "args": args,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "docstring": ast.get_docstring(node) or "",
                })
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                structure["imports"].append(f"from {node.module} import {', '.join(a.name for a in node.names)}")
            else:
                structure["imports"].append(f"import {', '.join(a.name for a in node.names)}")

    # FastAPI Endpoints erkennen
    endpoint_pattern = r'@(?:app|router)\.(get|post|put|delete|patch)\(["\'](.+?)["\']'
    for match in re.finditer(endpoint_pattern, code):
        structure["endpoints"].append({"method": match.group(1).upper(), "path": match.group(2)})

    return structure


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class AutoDocRequest(BaseModel):
    code: str
    language: str = "python"
    doc_type: Literal["readme", "api", "docstrings", "technical", "user_guide"] = "technical"
    project_name: Optional[str] = None
    additional_context: Optional[str] = None
    user: str = "orchestrator"

class AutoDocResponse(BaseModel):
    workflow: str = "auto_documentation"
    doc_type: str
    code_structure: Dict
    documentation: str
    duration_seconds: float


# ══════════════════════════════════════════
# MAIN ENDPOINT
# ══════════════════════════════════════════

DOC_PROMPTS = {
    "readme": (
        "Erstelle eine vollstaendige README.md fuer dieses Projekt. Beinhalte: "
        "Titel, Beschreibung, Features, Installation, Usage, API-Endpoints (falls vorhanden), "
        "Konfiguration, Architektur-Ueberblick, Contributing.\n\n"
    ),
    "api": (
        "Erstelle eine API-Dokumentation im OpenAPI-Stil. Fuer jeden Endpoint: "
        "Method, Path, Beschreibung, Request-Body (mit Beispiel), Response (mit Beispiel), "
        "Fehler-Codes, Authentifizierung.\n\n"
    ),
    "docstrings": (
        "Ergaenze den Code mit vollstaendigen Docstrings (Google-Style). "
        "Jede Funktion/Klasse/Methode bekommt: Beschreibung, Args, Returns, Raises, Example.\n\n"
    ),
    "technical": (
        "Erstelle technische Dokumentation: Architektur, Datenfluss, "
        "Abhaengigkeiten, Konfiguration, Deployment, Fehlerbehandlung, Performance.\n\n"
    ),
    "user_guide": (
        "Erstelle ein Benutzerhandbuch: Einfuehrung, Erste Schritte, "
        "Hauptfunktionen (mit Beispielen), FAQ, Troubleshooting.\n\n"
    ),
}

@router.post("/docs", response_model=AutoDocResponse)
async def auto_document(req: AutoDocRequest):
    """Generiert automatisch Dokumentation aus Code."""
    start = time.time()

    # Code-Struktur analysieren
    if req.language == "python":
        structure = _extract_python_structure(req.code)
    else:
        structure = {"note": f"Strukturanalyse fuer {req.language} nur via LLM"}

    # Prompt zusammenbauen
    prompt = DOC_PROMPTS.get(req.doc_type, DOC_PROMPTS["technical"])
    if req.project_name:
        prompt += f"Projektname: {req.project_name}\n"
    if req.additional_context:
        prompt += f"Zusaetzlicher Kontext: {req.additional_context}\n"

    # Strukturinfo mitgeben
    if isinstance(structure, dict) and not structure.get("error"):
        struct_info = []
        for cls in structure.get("classes", []):
            struct_info.append(f"Klasse: {cls['name']} (Methoden: {', '.join(cls['methods'])})")
        for fn in structure.get("functions", []):
            struct_info.append(f"Funktion: {fn['name']}({', '.join(fn['args'])}){' [async]' if fn['async'] else ''}")
        for ep in structure.get("endpoints", []):
            struct_info.append(f"Endpoint: {ep['method']} {ep['path']}")
        if struct_info:
            prompt += "\nErkannte Struktur:\n" + "\n".join(f"- {s}" for s in struct_info) + "\n"

    prompt += f"\nCode:\n{req.code}"

    # Docs-Agent aufrufen
    result = await _call("docs", prompt, req.user)
    documentation = result.get("answer", "")

    return AutoDocResponse(
        doc_type=req.doc_type,
        code_structure=structure,
        documentation=documentation,
        duration_seconds=round(time.time() - start, 2),
    )


# ══════════════════════════════════════════
# CHANGELOG GENERATOR
# ══════════════════════════════════════════

class ChangelogRequest(BaseModel):
    changes: str  # Diff, Commit-Messages, oder Beschreibung
    version: Optional[str] = None
    user: str = "orchestrator"

@router.post("/docs/changelog")
async def generate_changelog(req: ChangelogRequest):
    """Generiert einen Changelog-Eintrag aus Aenderungen."""
    prompt = (
        f"Erstelle einen professionellen CHANGELOG-Eintrag.\n"
        f"Version: {req.version or 'NEXT'}\n"
        f"Kategorisiere in: Added, Changed, Fixed, Removed, Security.\n\n"
        f"Aenderungen:\n{req.changes}"
    )
    result = await _call("docs", prompt, req.user)
    return {"workflow": "changelog", "changelog": result.get("answer", ""), "version": req.version}
