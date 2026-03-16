"""
Workflow ③ Deep RAG + Memory
=============================
Dreifach-parallele Retrieval-Pipeline:
1. Dify Knowledge Base (semantische Suche)
2. Mem0 Memory (User + Agent Memories)
3. HippoRAG Knowledge Graph (Beziehungen)

Ergebnisse werden gerankt, gemergt und als angereicherter Kontext
an den Agent uebergeben. Deutlich tiefere Recherche als Standard-Flow.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
import asyncio
import httpx
import logging
import time
import os

logger = logging.getLogger("workflow.deep_rag")
router = APIRouter(prefix="/workflow", tags=["Workflow-DeepRAG"])

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════

DIFY_API_URL = os.getenv("DIFY_API_URL", "http://localhost:3080/v1")
DIFY_KB_ID = os.getenv("DIFY_KB_ID", "260e0d73-8c6b-49ec-92df-a369affe482b")
DIFY_KB_KEY = os.getenv("DIFY_KB_KEY", "dataset-WG3ca69737ZxjHdi4GFHEG28")
HIPPORAG_URL = os.getenv("HIPPORAG_URL", "http://127.0.0.1:8001")
MEM0_API_URL = os.getenv("MEM0_LOCAL_URL", "http://localhost:8002")  # Spaeter: http://mem0:8002
MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")
MEM0_ORG_ID = os.getenv("MEM0_ORG_ID", "")
MEM0_PROJECT_ID = os.getenv("MEM0_PROJECT_ID", "")
TIMEOUT = int(os.getenv("RAG_TIMEOUT", "10"))
DEEP_KB_TOP_K = int(os.getenv("DEEP_KB_TOP_K", "10"))  # Mehr als Standard
DEEP_HIPPO_TOP_K = int(os.getenv("DEEP_HIPPO_TOP_K", "8"))
DEEP_MEM0_LIMIT = int(os.getenv("DEEP_MEM0_LIMIT", "15"))

# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class DeepRAGRequest(BaseModel):
    query: str
    agent: str = "architect"
    user: str = "orchestrator"
    user_id: str = "cloud-code-team"       # Mem0 shared user
    agent_id: Optional[str] = None          # Mem0 agent filter
    include_kb: bool = True
    include_mem0: bool = True
    include_hipporag: bool = True
    include_anti_hallucination: bool = True
    kb_top_k: int = 10
    hippo_top_k: int = 8
    mem0_limit: int = 15

class RAGSource(BaseModel):
    source: str
    content: str
    score: Optional[float] = None
    metadata: Optional[Dict] = None

class DeepRAGResponse(BaseModel):
    workflow: str = "deep_rag_memory"
    query: str
    agent: str
    answer: str
    enriched_query_length: int
    sources_used: Dict[str, bool]
    source_details: List[Dict]
    duration_seconds: float


# ══════════════════════════════════════════
# RETRIEVAL FUNCTIONS
# ══════════════════════════════════════════

async def _fetch_kb_deep(query: str, top_k: int = 10) -> List[Dict]:
    """Erweiterte KB-Suche mit mehr Ergebnissen und Score-Details."""
    results = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{DIFY_API_URL}/datasets/{DIFY_KB_ID}/retrieve",
                json={
                    "query": query,
                    "retrieval_model": {
                        "search_method": "semantic_search",
                        "top_k": top_k,
                        "score_threshold_enabled": False,
                        "score_threshold": None,
                        "reranking_enable": False,
                        "reranking_mode": None,
                        "reranking_model": {"reranking_model_name": None, "reranking_provider_name": None},
                        "weights": None,
                    },
                },
                headers={"Authorization": f"Bearer {DIFY_KB_KEY}", "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                for rec in data.get("records", [])[:top_k]:
                    seg = rec.get("segment", {})
                    content = seg.get("content", "")
                    doc_name = rec.get("document", {}).get("name", "unknown")
                    score = rec.get("score", 0)
                    if content:
                        results.append({
                            "source": "kb",
                            "document": doc_name,
                            "content": content[:800],
                            "score": score,
                        })
    except Exception as e:
        logger.warning(f"Deep KB fetch failed: {e}")
    return results


async def _fetch_mem0_deep(query: str, user_id: str, agent_id: Optional[str] = None, limit: int = 15) -> List[Dict]:
    """Mem0 Memory Search — sucht im shared Pool mit optionalem Agent-Filter."""
    results = []
    if False:  # Lokaler Mem0 braucht keinen API Key
        logger.warning("Mem0 API key not configured, skipping memory retrieval")
        return results
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            search_body = {
                "query": query,
                "user_id": user_id,
                "limit": limit,
            }
            if agent_id:
                search_body["agent_id"] = agent_id

            headers = {
                "Authorization": f"Token {MEM0_API_KEY}",
                "Content-Type": "application/json",
            }
            if MEM0_ORG_ID:
                headers["x-org-id"] = MEM0_ORG_ID
            if MEM0_PROJECT_ID:
                headers["x-project-id"] = MEM0_PROJECT_ID

            resp = await client.post(
                f"{MEM0_API_URL}/v1/memories/search/",
                json=search_body,
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                memories = data if isinstance(data, list) else data.get("results", [])
                for mem in memories[:limit]:
                    content = mem.get("memory", "") or mem.get("content", "")
                    if content:
                        results.append({
                            "source": "mem0",
                            "content": content,
                            "score": mem.get("score", 0),
                            "agent": mem.get("agent_id", "shared"),
                            "created_at": mem.get("created_at", ""),
                        })
    except Exception as e:
        logger.warning(f"Mem0 deep search failed: {e}")
    return results


async def _fetch_hipporag_deep(query: str, top_k: int = 8) -> List[Dict]:
    """Erweiterte HippoRAG-Suche mit mehr Hops und Beziehungsdetails."""
    results = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{HIPPORAG_URL}/knowledge/query",
                json={"query": query, "top_k": top_k, "hop_depth": 4},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                for r in data.get("results", []):
                    for rel in r.get("relationships", []):
                        src = rel.get("from", "")
                        rtype = rel.get("type", "")
                        tgt = rel.get("to", "")
                        if src and tgt:
                            results.append({
                                "source": "hipporag",
                                "content": f"{src} --[{rtype}]--> {tgt}",
                                "score": rel.get("weight", 0.5),
                            })
                    for node in r.get("nodes", []):
                        if node.get("description"):
                            results.append({
                                "source": "hipporag",
                                "content": f"[{node.get('type','Entity')}] {node.get('name','')}: {node.get('description','')}",
                                "score": 0.5,
                            })
    except Exception as e:
        logger.warning(f"HippoRAG deep fetch failed: {e}")
    return results


# ══════════════════════════════════════════
# MERGE + RANK
# ══════════════════════════════════════════

def _merge_and_rank(kb_results: List[Dict], mem0_results: List[Dict],
                    hippo_results: List[Dict]) -> str:
    """Merged alle Quellen, rankt nach Score, baut enriched Context."""
    all_results = []

    # Gewichtung: Mem0 > KB > HippoRAG
    for r in mem0_results:
        r["weighted_score"] = (r.get("score", 0.5) or 0.5) * 1.3  # Memory-Boost
        all_results.append(r)
    for r in kb_results:
        r["weighted_score"] = (r.get("score", 0.5) or 0.5) * 1.0
        all_results.append(r)
    for r in hippo_results:
        r["weighted_score"] = (r.get("score", 0.5) or 0.5) * 0.8
        all_results.append(r)

    # Sortieren nach gewichtetem Score
    all_results.sort(key=lambda x: x.get("weighted_score", 0), reverse=True)

    # Deduplizierung (exakte Duplikate entfernen)
    seen_content = set()
    unique_results = []
    for r in all_results:
        content_hash = r["content"][:100]
        if content_hash not in seen_content:
            seen_content.add(content_hash)
            unique_results.append(r)

    # Context zusammenbauen
    sections = {"mem0": [], "kb": [], "hipporag": []}
    for r in unique_results[:30]:  # Max 30 Ergebnisse
        sections[r["source"]].append(r["content"])

    parts = []
    if sections["mem0"]:
        parts.append("[USER MEMORY - Gespeicherte Fakten und Praeferenzen]\n" + "\n".join(f"- {c}" for c in sections["mem0"]))
    if sections["kb"]:
        parts.append("[KB CONTEXT - Knowledge Base Dokumente]\n" + "\n\n".join(sections["kb"]))
    if sections["hipporag"]:
        parts.append("[HIPPORAG CONTEXT - Knowledge Graph Beziehungen]\n" + "\n".join(sections["hipporag"]))

    return "\n\n".join(parts)


# ══════════════════════════════════════════
# ANTI-HALLUCINATION
# ══════════════════════════════════════════

DEEP_ANTI_HALLUCINATION = """== DEEP RAG REGELN (PFLICHT) ==
1. Du hast ERWEITERTEN Kontext aus 3 Quellen: Memory, Knowledge Base, Knowledge Graph
2. Priorisierung: USER MEMORY > KB CONTEXT > HIPPORAG > Allgemeinwissen
3. Zitiere die Quelle bei jeder Aussage: [KB], [MEM], [HIPPO], [WISSEN]
4. Sage was du sicher weisst, gib zu was du nicht weisst: [KEINE_AHNUNG]
5. Bewerte deine Sicherheit: [SICHER] / [WAHRSCHEINLICH] / [UNSICHER]
6. Erfinde NIEMALS Funktionen, URLs, Code oder Daten
7. Bei Widerspruechen zwischen Quellen: nenne BEIDE und markiere [KONFLIKT]
"""


# ══════════════════════════════════════════
# MAIN ENDPOINT
# ══════════════════════════════════════════

_call_agent_fn = None

def set_agent_caller(fn):
    global _call_agent_fn
    _call_agent_fn = fn

@router.post("/deep-rag", response_model=DeepRAGResponse)
async def deep_rag_query(req: DeepRAGRequest):
    """
    Dreifach-parallele RAG-Pipeline: KB + Mem0 + HippoRAG
    Ergebnisse gerankt und gemergt → angereicherter Agent-Aufruf.
    """
    start = time.time()
    agent_id = req.agent_id or f"cct-{req.agent}"

    # Paralleles Retrieval
    tasks = []
    if req.include_kb:
        tasks.append(("kb", _fetch_kb_deep(req.query, req.kb_top_k)))
    if req.include_mem0:
        tasks.append(("mem0", _fetch_mem0_deep(req.query, req.user_id, agent_id, req.mem0_limit)))
    if req.include_hipporag:
        tasks.append(("hipporag", _fetch_hipporag_deep(req.query, req.hippo_top_k)))

    # Alle parallel ausfuehren
    results = {}
    if tasks:
        gathered = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        for (name, _), result in zip(tasks, gathered):
            results[name] = result if not isinstance(result, Exception) else []

    kb_results = results.get("kb", [])
    mem0_results = results.get("mem0", [])
    hippo_results = results.get("hipporag", [])

    # Merge und Rank
    merged_context = _merge_and_rank(kb_results, mem0_results, hippo_results)

    # Enriched Query zusammenbauen
    enriched_parts = [req.query, ""]
    if req.include_anti_hallucination:
        enriched_parts.append(DEEP_ANTI_HALLUCINATION)
    if merged_context:
        enriched_parts.append(merged_context)
        enriched_parts.append("[END CONTEXT]")

    enriched_query = "\n".join(enriched_parts)

    # Agent aufrufen mit angereichertem Query
    answer = ""
    if _call_agent_fn:
        try:
            result = await _call_agent_fn(req.agent, enriched_query, req.user)
            answer = result.get("answer", "")
        except Exception as e:
            answer = f"[ERROR] Agent {req.agent}: {str(e)}"
    else:
        answer = "[ERROR] Agent caller nicht initialisiert"

    duration = round(time.time() - start, 2)

    # Source-Details sammeln
    source_details = []
    for r in (kb_results[:3] + mem0_results[:3] + hippo_results[:3]):
        source_details.append({
            "source": r["source"],
            "content_preview": r["content"][:200],
            "score": r.get("score"),
        })

    return DeepRAGResponse(
        query=req.query,
        agent=req.agent,
        answer=answer,
        enriched_query_length=len(enriched_query),
        sources_used={
            "kb": bool(kb_results),
            "mem0": bool(mem0_results),
            "hipporag": bool(hippo_results),
        },
        source_details=source_details,
        duration_seconds=duration,
    )


# ══════════════════════════════════════════
# RAG HEALTH CHECK (erweitert)
# ══════════════════════════════════════════

@router.get("/deep-rag/health")
async def deep_rag_health():
    """Prueft alle 3 RAG-Quellen einzeln."""
    status = {"kb": False, "mem0": False, "hipporag": False}

    async with httpx.AsyncClient(timeout=5) as client:
        # KB
        try:
            resp = await client.post(
                f"{DIFY_API_URL}/datasets/{DIFY_KB_ID}/retrieve",
                json={"query": "health", "retrieval_model": {
                    "search_method": "semantic_search", "top_k": 1,
                    "score_threshold_enabled": False, "score_threshold": None,
                    "reranking_enable": False, "reranking_mode": None,
                    "reranking_model": {"reranking_model_name": None, "reranking_provider_name": None},
                    "weights": None
                }},
                headers={"Authorization": f"Bearer {DIFY_KB_KEY}", "Content-Type": "application/json"},
            )
            status["kb"] = resp.status_code == 200
        except:
            pass

        # Mem0
        try:
            if True:  # Lokaler Mem0 immer pruefen
                resp = await client.get(
                    f"{MEM0_API_URL}/health",


                )
                status["mem0"] = resp.status_code in (200, 404)
        except:
            pass

        # HippoRAG
        try:
            resp = await client.get(f"{HIPPORAG_URL}/health")
            status["hipporag"] = resp.status_code == 200
        except:
            pass

    status["all_healthy"] = all(status.values())
    return status
