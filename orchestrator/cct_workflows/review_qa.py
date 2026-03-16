"""
Workflow ⑤ Review + QA
======================
Automatisierte Code-Review und QA-Pipeline:
1. Reviewer: Prueft Code auf Best Practices, Security, Performance
2. Tester: Generiert Tests basierend auf dem Review
3. Scoring: Bewertet Code-Qualitaet mit detailliertem Report
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
import asyncio
import logging
import time
import re

logger = logging.getLogger("workflow.review_qa")
router = APIRouter(prefix="/workflow", tags=["Workflow-ReviewQA"])

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
# REVIEW CATEGORIES
# ══════════════════════════════════════════

REVIEW_CATEGORIES = {
    "security": {
        "prompt": "Analysiere diesen Code NUR auf Sicherheitsprobleme: SQL-Injection, XSS, CSRF, unsichere Deserialisierung, Hardcoded Secrets, fehlende Input-Validierung.\nBewerte: KRITISCH / HOCH / MITTEL / NIEDRIG / SICHER\n\n{code}",
        "weight": 0.3,
    },
    "performance": {
        "prompt": "Analysiere diesen Code NUR auf Performance: N+1 Queries, unnoetige Loops, fehlende Indizes, Memory Leaks, grosse Payloads, fehlende Caching.\nBewerte: KRITISCH / HOCH / MITTEL / NIEDRIG / OPTIMAL\n\n{code}",
        "weight": 0.2,
    },
    "best_practices": {
        "prompt": "Pruefe diesen Code auf Best Practices: SOLID-Prinzipien, DRY, Naming, Error Handling, Logging, Type Hints, Documentation.\nBewerte: SCHLECHT / MITTEL / GUT / SEHR GUT\n\n{code}",
        "weight": 0.2,
    },
    "maintainability": {
        "prompt": "Bewerte die Wartbarkeit: Komplexitaet, Modularitaet, Testbarkeit, Abhaengigkeiten, Konfigurierbarkeit.\nBewerte: SCHLECHT / MITTEL / GUT / SEHR GUT\n\n{code}",
        "weight": 0.15,
    },
    "correctness": {
        "prompt": "Pruefe die Korrektheit: Edge Cases, Off-by-One Errors, Race Conditions, Null-Checks, Error States.\nBewerte: FEHLERHAFT / FRAGWUERDIG / KORREKT / ROBUST\n\n{code}",
        "weight": 0.15,
    },
}


# ══════════════════════════════════════════
# SCORE EXTRACTION
# ══════════════════════════════════════════

SCORE_MAP = {
    "kritisch": 0.0, "fehlerhaft": 0.1, "schlecht": 0.2,
    "hoch": 0.3, "fragwuerdig": 0.35,
    "mittel": 0.5,
    "niedrig": 0.7, "gut": 0.7, "korrekt": 0.75,
    "sicher": 0.9, "optimal": 0.9, "sehr gut": 0.9, "robust": 0.95,
}

def _extract_score(text: str) -> float:
    """Extrahiert Score aus Review-Text."""
    text_lower = text.lower()
    for keyword, score in sorted(SCORE_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if keyword in text_lower:
            return score
    return 0.5  # Default mittel


# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class ReviewRequest(BaseModel):
    code: str
    language: str = "python"
    categories: Optional[List[str]] = None  # None = alle
    include_tests: bool = True
    include_fix_suggestions: bool = True
    user: str = "orchestrator"

class QuickReviewRequest(BaseModel):
    code: str
    user: str = "orchestrator"

class ReviewResponse(BaseModel):
    workflow: str = "review_qa"
    language: str
    overall_score: float
    category_scores: Dict[str, float]
    reviews: Dict[str, str]
    tests: Optional[str] = None
    fix_suggestions: Optional[str] = None
    summary: str
    duration_seconds: float


# ══════════════════════════════════════════
# FULL REVIEW ENDPOINT
# ══════════════════════════════════════════

@router.post("/review", response_model=ReviewResponse)
async def full_review(req: ReviewRequest):
    """Vollstaendiges Code-Review mit kategorisierter Bewertung."""
    start = time.time()
    categories = req.categories or list(REVIEW_CATEGORIES.keys())

    # Parallel: Alle Review-Kategorien gleichzeitig
    review_tasks = {}
    for cat in categories:
        if cat in REVIEW_CATEGORIES:
            prompt = REVIEW_CATEGORIES[cat]["prompt"].replace("{code}", req.code)
            review_tasks[cat] = _call("reviewer", prompt, req.user)

    # Ausfuehren
    results = {}
    if review_tasks:
        gathered = await asyncio.gather(*review_tasks.values())
        for cat, result in zip(review_tasks.keys(), gathered):
            results[cat] = result.get("answer", "")

    # Scores extrahieren
    category_scores = {}
    for cat, review_text in results.items():
        category_scores[cat] = _extract_score(review_text)

    # Gewichteter Gesamtscore
    total_weight = sum(REVIEW_CATEGORIES[c]["weight"] for c in category_scores if c in REVIEW_CATEGORIES)
    if total_weight > 0:
        overall_score = sum(
            category_scores[c] * REVIEW_CATEGORIES[c]["weight"]
            for c in category_scores if c in REVIEW_CATEGORIES
        ) / total_weight
    else:
        overall_score = 0.5

    # Optional: Tests generieren
    tests = None
    if req.include_tests:
        worst_cats = sorted(category_scores.items(), key=lambda x: x[1])[:2]
        focus_areas = ", ".join(c[0] for c in worst_cats)
        test_prompt = (
            f"Erstelle {req.language} Unit-Tests fuer diesen Code. "
            f"Fokussiere besonders auf: {focus_areas}\n\n{req.code}"
        )
        test_result = await _call("tester", test_prompt, req.user)
        tests = test_result.get("answer", "")

    # Optional: Fix-Vorschlaege
    fix_suggestions = None
    if req.include_fix_suggestions:
        problems = []
        for cat, score in category_scores.items():
            if score < 0.6:
                problems.append(f"{cat}: Score {score:.1f} — {results.get(cat, '')[:200]}")
        if problems:
            fix_prompt = (
                f"Fuer folgenden Code wurden diese Probleme gefunden:\n\n"
                + "\n".join(problems)
                + f"\n\nCode:\n{req.code}\n\n"
                f"Gib konkrete Fix-Vorschlaege mit Code-Beispielen."
            )
            fix_result = await _call("coder", fix_prompt, req.user)
            fix_suggestions = fix_result.get("answer", "")

    # Summary
    if overall_score >= 0.8:
        summary = f"Code-Qualitaet: SEHR GUT ({overall_score:.0%}). Alle Kategorien bestanden."
    elif overall_score >= 0.6:
        summary = f"Code-Qualitaet: GUT ({overall_score:.0%}). Kleinere Verbesserungen moeglich."
    elif overall_score >= 0.4:
        summary = f"Code-Qualitaet: MITTEL ({overall_score:.0%}). Mehrere Bereiche benoetigen Aufmerksamkeit."
    else:
        summary = f"Code-Qualitaet: KRITISCH ({overall_score:.0%}). Dringende Ueberarbeitung noetig."

    weak_areas = [c for c, s in category_scores.items() if s < 0.5]
    if weak_areas:
        summary += f" Schwachstellen: {', '.join(weak_areas)}."

    return ReviewResponse(
        language=req.language,
        overall_score=round(overall_score, 2),
        category_scores={k: round(v, 2) for k, v in category_scores.items()},
        reviews=results,
        tests=tests,
        fix_suggestions=fix_suggestions,
        summary=summary,
        duration_seconds=round(time.time() - start, 2),
    )


# ══════════════════════════════════════════
# QUICK REVIEW (single-pass, schneller)
# ══════════════════════════════════════════

@router.post("/review/quick")
async def quick_review(req: QuickReviewRequest):
    """Schnelles Single-Pass Review — ein Aufruf, alle Kategorien."""
    start = time.time()
    prompt = (
        "Reviewe diesen Code kurz und praegnant. Bewerte:\n"
        "1. Security (0-10)\n2. Performance (0-10)\n3. Best Practices (0-10)\n"
        "4. Wartbarkeit (0-10)\n5. Korrektheit (0-10)\n"
        "6. Gesamt-Empfehlung: MERGE / UEBERARBEITEN / ABLEHNEN\n\n"
        f"{req.code}"
    )
    result = await _call("reviewer", prompt, req.user)
    return {
        "workflow": "quick_review",
        "review": result.get("answer", ""),
        "duration_seconds": round(time.time() - start, 2),
    }


# ══════════════════════════════════════════
# DIFF REVIEW (fuer PRs / Code-Aenderungen)
# ══════════════════════════════════════════

class DiffReviewRequest(BaseModel):
    diff: str
    context: Optional[str] = None  # Optionaler Kontext (PR Beschreibung, Ticket)
    user: str = "orchestrator"

@router.post("/review/diff")
async def review_diff(req: DiffReviewRequest):
    """Reviewt ein Diff (z.B. aus einem PR)."""
    start = time.time()

    prompt = (
        "Reviewe diesen Code-Diff. Fokussiere auf:\n"
        "- Neue Bugs oder Regressionen\n"
        "- Security-Probleme in geaenderten Zeilen\n"
        "- Fehlende Tests fuer neue Logik\n"
        "- Breaking Changes\n\n"
    )
    if req.context:
        prompt += f"Kontext: {req.context}\n\n"
    prompt += f"Diff:\n{req.diff}"

    # Parallel: Reviewer + Security
    reviewer_task = _call("reviewer", prompt, req.user)
    security_prompt = f"Pruefe dieses Diff NUR auf Sicherheitsprobleme:\n\n{req.diff}"
    security_task = _call("security", security_prompt, req.user)

    reviewer_result, security_result = await asyncio.gather(reviewer_task, security_task)

    return {
        "workflow": "diff_review",
        "code_review": reviewer_result.get("answer", ""),
        "security_review": security_result.get("answer", ""),
        "duration_seconds": round(time.time() - start, 2),
    }
