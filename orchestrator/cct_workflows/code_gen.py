"""
Workflow ④ Code Generation
===========================
Multi-Step Code-Pipeline:
1. Coder generiert Code
2. Syntax-Check (Python AST / JS Parse / Regex)
3. Optional: Tester generiert Tests
4. Optional: Reviewer prueft Qualitaet
5. Finaler Output mit Confidence-Score
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
import asyncio
import logging
import time
import re
import ast
import json

logger = logging.getLogger("workflow.code_gen")
router = APIRouter(prefix="/workflow", tags=["Workflow-CodeGen"])

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
# SYNTAX CHECKER (Lokal, ohne LLM)
# ══════════════════════════════════════════

def _extract_code_blocks(text: str) -> List[Dict]:
    """Extrahiert Code-Bloecke aus Markdown-formatiertem Text."""
    blocks = []
    pattern = r"```(\w*)\n(.*?)```"
    for match in re.finditer(pattern, text, re.DOTALL):
        lang = match.group(1).lower() or "unknown"
        code = match.group(2).strip()
        blocks.append({"language": lang, "code": code, "start": match.start(), "end": match.end()})
    # Falls kein Markdown-Block: ganzen Text als Code behandeln
    if not blocks and text.strip():
        # Heuristik: wenn import/def/class vorkommt, ist es Python
        if any(kw in text for kw in ["import ", "def ", "class ", "from "]):
            blocks.append({"language": "python", "code": text.strip(), "start": 0, "end": len(text)})
    return blocks

def _check_python_syntax(code: str) -> Dict:
    """Prueft Python-Syntax via AST-Parsing."""
    try:
        tree = ast.parse(code)
        # Zaehle Strukturen
        classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        functions = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        imports = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
        return {
            "valid": True,
            "language": "python",
            "classes": classes,
            "functions": functions,
            "imports": imports,
            "lines": len(code.splitlines()),
            "error": None,
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "language": "python",
            "error": f"Zeile {e.lineno}: {e.msg}",
            "error_line": e.lineno,
            "error_offset": e.offset,
        }

def _check_json_syntax(code: str) -> Dict:
    """Prueft JSON-Syntax."""
    try:
        data = json.loads(code)
        return {"valid": True, "language": "json", "type": type(data).__name__, "error": None}
    except json.JSONDecodeError as e:
        return {"valid": False, "language": "json", "error": f"Zeile {e.lineno}: {e.msg}"}

def _check_js_basic(code: str) -> Dict:
    """Basic JS/TS Syntax-Check (Klammer-Balance, Keywords)."""
    # Klammer-Balance
    opens = code.count("(") + code.count("{") + code.count("[")
    closes = code.count(")") + code.count("}") + code.count("]")
    balanced = opens == closes
    # Haeufige Fehler
    issues = []
    if not balanced:
        issues.append(f"Klammer-Imbalance: {opens} offen vs {closes} geschlossen")
    if "var " in code:
        issues.append("Warnung: 'var' statt 'const/let' verwendet")
    return {
        "valid": balanced and len(issues) <= 1,
        "language": "javascript",
        "balanced": balanced,
        "issues": issues,
        "error": "; ".join(issues) if issues else None,
    }

def check_syntax(code: str, language: str = "python") -> Dict:
    """Universeller Syntax-Checker."""
    if language in ("python", "py"):
        return _check_python_syntax(code)
    elif language in ("json", "jsonl"):
        return _check_json_syntax(code)
    elif language in ("javascript", "js", "typescript", "ts", "jsx", "tsx"):
        return _check_js_basic(code)
    else:
        return {"valid": True, "language": language, "error": None, "note": "Kein Checker fuer diese Sprache"}


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class CodeGenRequest(BaseModel):
    query: str
    language: str = "python"
    include_tests: bool = True
    include_review: bool = False
    include_docs: bool = False
    max_retries: int = 2          # Syntax-Fix Versuche
    user: str = "orchestrator"

class CodeGenResponse(BaseModel):
    workflow: str = "code_generation"
    query: str
    language: str
    code: str
    syntax_valid: bool
    syntax_details: Dict
    tests: Optional[str] = None
    review: Optional[str] = None
    documentation: Optional[str] = None
    retries_needed: int = 0
    duration_seconds: float
    confidence: float             # 0.0-1.0 basierend auf Syntax + Review


# ══════════════════════════════════════════
# MAIN ENDPOINT
# ══════════════════════════════════════════

@router.post("/code", response_model=CodeGenResponse)
async def generate_code(req: CodeGenRequest):
    """Generiert Code mit Syntax-Validierung und optionalem Review."""
    start = time.time()
    retries = 0
    code_text = ""
    syntax_result = {}

    # Step 1: Code generieren
    gen_prompt = f"Generiere {req.language}-Code fuer folgende Anforderung. Gib NUR den Code aus, in einem Markdown-Codeblock:\n\n{req.query}"
    gen_result = await _call("coder", gen_prompt, req.user)
    code_text = gen_result.get("answer", "")

    # Step 2: Code-Bloecke extrahieren und Syntax pruefen
    blocks = _extract_code_blocks(code_text)
    if blocks:
        main_block = blocks[0]
        syntax_result = check_syntax(main_block["code"], main_block.get("language", req.language))
    else:
        syntax_result = {"valid": False, "language": req.language, "error": "Kein Code-Block gefunden"}

    # Step 3: Retry bei Syntax-Fehler
    while not syntax_result.get("valid") and retries < req.max_retries:
        retries += 1
        fix_prompt = (
            f"Der vorherige Code hat einen Syntax-Fehler: {syntax_result.get('error', 'unbekannt')}\n\n"
            f"Bitte korrigiere den Fehler und gib den vollstaendigen, korrekten {req.language}-Code aus:\n\n{code_text}"
        )
        fix_result = await _call("coder", fix_prompt, req.user)
        code_text = fix_result.get("answer", "")
        blocks = _extract_code_blocks(code_text)
        if blocks:
            syntax_result = check_syntax(blocks[0]["code"], blocks[0].get("language", req.language))
        else:
            syntax_result = {"valid": False, "language": req.language, "error": "Kein Code-Block nach Fix"}

    # Step 4: Optional Tests generieren
    tests_text = None
    if req.include_tests and syntax_result.get("valid"):
        test_prompt = f"Erstelle umfassende Unit-Tests ({req.language}) fuer diesen Code:\n\n{code_text}"
        test_result = await _call("tester", test_prompt, req.user)
        tests_text = test_result.get("answer", "")

    # Step 5: Optional Review
    review_text = None
    if req.include_review:
        review_prompt = f"Reviewe diesen {req.language}-Code auf Best Practices, Security, Performance:\n\n{code_text}"
        if tests_text:
            review_prompt += f"\n\nTests:\n{tests_text}"
        review_result = await _call("reviewer", review_prompt, req.user)
        review_text = review_result.get("answer", "")

    # Step 6: Optional Docs
    docs_text = None
    if req.include_docs and syntax_result.get("valid"):
        docs_prompt = f"Erstelle technische Dokumentation (Docstrings, Usage-Examples) fuer:\n\n{code_text}"
        docs_result = await _call("docs", docs_prompt, req.user)
        docs_text = docs_result.get("answer", "")

    # Confidence berechnen
    confidence = 0.0
    if syntax_result.get("valid"):
        confidence += 0.5
    if retries == 0 and syntax_result.get("valid"):
        confidence += 0.2  # Erster Versuch korrekt
    if tests_text and len(tests_text) > 100:
        confidence += 0.15
    if review_text and "fehler" not in review_text.lower() and "problem" not in review_text.lower():
        confidence += 0.15
    confidence = min(confidence, 1.0)

    return CodeGenResponse(
        query=req.query,
        language=req.language,
        code=code_text,
        syntax_valid=syntax_result.get("valid", False),
        syntax_details=syntax_result,
        tests=tests_text,
        review=review_text,
        documentation=docs_text,
        retries_needed=retries,
        duration_seconds=round(time.time() - start, 2),
        confidence=confidence,
    )


# ══════════════════════════════════════════
# STANDALONE SYNTAX CHECK
# ══════════════════════════════════════════

class SyntaxCheckRequest(BaseModel):
    code: str
    language: str = "python"

@router.post("/syntax-check")
async def syntax_check_endpoint(req: SyntaxCheckRequest):
    """Standalone Syntax-Check ohne Code-Generierung."""
    result = check_syntax(req.code, req.language)
    return {"workflow": "syntax_check", **result}
