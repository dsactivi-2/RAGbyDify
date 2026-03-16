"""
Workflow ⑧ Security Scan
=========================
Automatisierte Sicherheitsanalyse:
1. Statische Analyse (Regex-basiert, lokal)
2. LLM Security Review (Security-Agent)
3. Bewertung nach OWASP Top 10
4. Fix-Empfehlungen mit Prioritaet
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import logging
import time
import re

logger = logging.getLogger("workflow.security")
router = APIRouter(prefix="/workflow", tags=["Workflow-Security"])

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
# STATIC ANALYSIS PATTERNS
# ══════════════════════════════════════════

SECURITY_PATTERNS = {
    "sql_injection": {
        "patterns": [
            r'f".*SELECT.*\{',  r"f'.*SELECT.*\{",
            r'".*SELECT.*" *\+',  r"'.*SELECT.*' *\+",
            r'cursor\.execute\(.*%s', r'\.format\(.*SELECT',
        ],
        "severity": "critical",
        "owasp": "A03:2021 Injection",
        "description": "Moegliche SQL-Injection: Benutzereingaben direkt in SQL",
    },
    "xss": {
        "patterns": [
            r'innerHTML\s*=', r'document\.write\(',
            r'\$\(.*\)\.html\(', r'dangerouslySetInnerHTML',
        ],
        "severity": "high",
        "owasp": "A03:2021 Injection (XSS)",
        "description": "Moegliches Cross-Site Scripting",
    },
    "hardcoded_secrets": {
        "patterns": [
            r'(password|passwd|pwd|secret|token|api_key|apikey)\s*=\s*["\'][^"\']+(\w{8,})',
            r'Bearer\s+[A-Za-z0-9\-_.]+',
            r'(sk-|pk-|m0-|ghp_|gho_)\w{20,}',
        ],
        "severity": "critical",
        "owasp": "A07:2021 Auth Failures",
        "description": "Hardcoded Secrets oder API-Keys im Code",
    },
    "insecure_deserialize": {
        "patterns": [
            r'pickle\.loads?\(', r'yaml\.load\((?!.*Loader)',
            r'eval\(', r'exec\(',
            r'subprocess\.call\(.*shell=True',
        ],
        "severity": "critical",
        "owasp": "A08:2021 Integrity Failures",
        "description": "Unsichere Deserialisierung oder Code-Ausfuehrung",
    },
    "missing_auth": {
        "patterns": [
            r'@app\.(get|post|put|delete)\((?!.*auth)(?!.*login)(?!.*health)',
        ],
        "severity": "medium",
        "owasp": "A01:2021 Broken Access Control",
        "description": "Endpoint ohne erkennbare Authentifizierung",
    },
    "path_traversal": {
        "patterns": [
            r'open\(.*\+.*\)', r'os\.path\.join\(.*request',
            r'send_file\(.*\+',
        ],
        "severity": "high",
        "owasp": "A01:2021 Broken Access Control",
        "description": "Moegliche Path Traversal Schwachstelle",
    },
    "insecure_random": {
        "patterns": [
            r'import random(?!\s*#\s*secure)', r'random\.randint',
            r'Math\.random\(\)',
        ],
        "severity": "low",
        "owasp": "A02:2021 Crypto Failures",
        "description": "Nicht-kryptographischer Zufallsgenerator (nutze secrets/os.urandom)",
    },
    "debug_mode": {
        "patterns": [
            r'DEBUG\s*=\s*True', r'debug=True',
            r'app\.run\(.*debug=True',
        ],
        "severity": "medium",
        "owasp": "A05:2021 Security Misconfiguration",
        "description": "Debug-Modus in Produktion",
    },
}

def _static_scan(code: str) -> List[Dict]:
    """Fuehrt statische Regex-Analyse durch."""
    findings = []
    lines = code.splitlines()
    for vuln_type, config in SECURITY_PATTERNS.items():
        for pattern in config["patterns"]:
            try:
                for i, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        findings.append({
                            "type": vuln_type,
                            "severity": config["severity"],
                            "owasp": config["owasp"],
                            "description": config["description"],
                            "line": i,
                            "code": line.strip()[:200],
                            "pattern": pattern,
                        })
            except re.error:
                continue
    # Deduplizierung (gleiche Zeile, gleicher Typ)
    seen = set()
    unique = []
    for f in findings:
        key = (f["type"], f["line"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return sorted(unique, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x["severity"], 4))


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class SecurityScanRequest(BaseModel):
    code: str
    language: str = "python"
    include_llm_review: bool = True
    include_fixes: bool = True
    user: str = "orchestrator"

class SecurityScanResponse(BaseModel):
    workflow: str = "security_scan"
    static_findings: List[Dict]
    static_summary: Dict
    llm_review: Optional[str] = None
    fix_recommendations: Optional[str] = None
    overall_risk: str
    owasp_categories: List[str]
    duration_seconds: float


# ══════════════════════════════════════════
# MAIN ENDPOINT
# ══════════════════════════════════════════

@router.post("/security", response_model=SecurityScanResponse)
async def security_scan(req: SecurityScanRequest):
    """Vollstaendiger Security-Scan: Statisch + LLM."""
    start = time.time()

    # Phase 1: Statische Analyse
    findings = _static_scan(req.code)
    severity_count = {}
    for f in findings:
        severity_count[f["severity"]] = severity_count.get(f["severity"], 0) + 1

    static_summary = {
        "total_findings": len(findings),
        "critical": severity_count.get("critical", 0),
        "high": severity_count.get("high", 0),
        "medium": severity_count.get("medium", 0),
        "low": severity_count.get("low", 0),
    }

    # Phase 2: LLM Security Review
    llm_review = None
    if req.include_llm_review:
        findings_summary = ""
        if findings:
            findings_summary = "\nStatische Analyse fand:\n" + "\n".join(
                f"- [{f['severity'].upper()}] {f['type']}: Zeile {f['line']} — {f['description']}"
                for f in findings[:10]
            )

        review_prompt = (
            f"Fuehre ein tiefes Security-Review durch fuer diesen {req.language}-Code.\n"
            f"Pruefe OWASP Top 10, Authentication, Authorization, Input Validation, "
            f"Error Handling, Logging, Crypto.\n"
            f"{findings_summary}\n\nCode:\n{req.code}"
        )
        review_result = await _call("security", review_prompt, req.user)
        llm_review = review_result.get("answer", "")

    # Phase 3: Fix-Empfehlungen
    fixes = None
    if req.include_fixes and findings:
        critical_findings = [f for f in findings if f["severity"] in ("critical", "high")][:5]
        if critical_findings:
            fix_prompt = (
                "Erstelle konkrete Fix-Vorschlaege mit Code fuer diese Sicherheitsprobleme:\n\n"
                + "\n".join(
                    f"{i+1}. [{f['severity'].upper()}] {f['type']} (Zeile {f['line']}): {f['description']}\n   Code: {f['code']}"
                    for i, f in enumerate(critical_findings)
                )
                + f"\n\nOriginaler Code:\n{req.code}"
            )
            fix_result = await _call("security", fix_prompt, req.user)
            fixes = fix_result.get("answer", "")

    # Risk Assessment
    if static_summary["critical"] > 0:
        risk = "KRITISCH"
    elif static_summary["high"] > 0:
        risk = "HOCH"
    elif static_summary["medium"] > 0:
        risk = "MITTEL"
    elif static_summary["low"] > 0:
        risk = "NIEDRIG"
    else:
        risk = "SICHER"

    owasp_cats = list(set(f["owasp"] for f in findings))

    return SecurityScanResponse(
        static_findings=findings,
        static_summary=static_summary,
        llm_review=llm_review,
        fix_recommendations=fixes,
        overall_risk=risk,
        owasp_categories=owasp_cats,
        duration_seconds=round(time.time() - start, 2),
    )


# ══════════════════════════════════════════
# QUICK SCAN (nur statisch, kein LLM)
# ══════════════════════════════════════════

@router.post("/security/quick")
async def quick_scan(code: str):
    """Schneller statischer Security-Scan ohne LLM."""
    findings = _static_scan(code)
    return {
        "workflow": "quick_security_scan",
        "findings": findings,
        "total": len(findings),
        "risk": "KRITISCH" if any(f["severity"] == "critical" for f in findings)
               else "HOCH" if any(f["severity"] == "high" for f in findings)
               else "OK",
    }
