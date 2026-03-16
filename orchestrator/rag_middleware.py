"""
Cloud Code Team - Standard RAG + Memory Middleware
===================================================
Central module that enriches EVERY agent query with:
1. KB Context (Dify Knowledge Base - semantic search)
2. HippoRAG Context (Knowledge Graph - relationships)
3. User Memory (persistent per-user facts)
4. Core Memory (system variables, agent memories)
5. Anti-Hallucination instructions

Used by: Orchestrator, Telegram Bot, Electron App, any future client.

Usage:
    from rag_middleware import enrich_for_agent

    enriched_query = await enrich_for_agent(
        query="Wie erstelle ich einen Workflow?",
        user_id="telegram-12345",
        agent="architect"
    )
"""
import os
import json
import asyncio
import logging
import time
import sqlite3
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("RAGMiddleware")

# ──────── Configuration ────────
DIFY_API_URL = os.getenv("DIFY_API_URL", "http://localhost:3080/v1")
DIFY_KB_ID = os.getenv("DIFY_KB_ID", "")
DIFY_KB_KEY = os.getenv("DIFY_KB_KEY", "")
HIPPORAG_URL = os.getenv("HIPPORAG_URL", "http://localhost:8001/knowledge/query")
TIMEOUT = int(os.getenv("RAG_TIMEOUT", "10"))
KB_TOP_K = int(os.getenv("RAG_KB_TOP_K", "5"))
HIPPO_TOP_K = int(os.getenv("RAG_HIPPO_TOP_K", "5"))

# Persistent storage
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", "/opt/cloud-code/data"))
MEMORY_DIR = DATA_DIR / "memories"
CORE_MEMORY_DB = os.getenv("CORE_MEMORY_DB", "/opt/cloud-code/core_memory.db")

# ──────── KB Retrieval ────────

async def fetch_kb(query: str) -> str:
    """Search Dify Knowledge Base for relevant context."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{DIFY_API_URL}/datasets/{DIFY_KB_ID}/retrieve",
                json={
                    "query": query,
                    "retrieval_model": {
                        "search_method": "semantic_search",
                        "top_k": KB_TOP_K,
                        "score_threshold_enabled": False,
                        "score_threshold": None,
                        "reranking_enable": False,
                        "reranking_mode": None,
                        "reranking_model": {
                            "reranking_model_name": None,
                            "reranking_provider_name": None,
                        },
                        "weights": None,
                    },
                },
                headers={
                    "Authorization": f"Bearer {DIFY_KB_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("records", [])
                if records:
                    chunks = []
                    for rec in records[:KB_TOP_K]:
                        seg = rec.get("segment", {})
                        content = seg.get("content", "")
                        doc_name = rec.get("document", {}).get("name", "unknown")
                        score = rec.get("score", 0)
                        if content:
                            chunks.append(f"[{doc_name} | score={score:.2f}]\n{content[:500]}")
                    if chunks:
                        return "\n\n".join(chunks)
            else:
                logger.warning(f"KB API {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"KB fetch failed: {e}")
    return ""


# ──────── HippoRAG ────────

async def fetch_hipporag(query: str) -> str:
    """Query HippoRAG knowledge graph for relationships."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                HIPPORAG_URL,
                json={"query": query, "top_k": HIPPO_TOP_K},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    facts = []
                    for r in results:
                        for node in r.get("nodes", []):
                            name = node.get("name", "")
                            ntype = node.get("type", "")
                            if name:
                                facts.append(f"[{ntype}] {name}")
                        for rel in r.get("relationships", []):
                            src = rel.get("from", "")
                            rtype = rel.get("type", "")
                            tgt = rel.get("to", "")
                            if src and rtype and tgt:
                                facts.append(f"{src} --{rtype}--> {tgt}")
                    if facts:
                        seen = set()
                        unique = [f for f in facts if f not in seen and not seen.add(f)]
                        return "\n".join(unique)
            else:
                logger.warning(f"HippoRAG {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"HippoRAG fetch failed: {e}")
    return ""


# ──────── User Memory (per-user persistent facts) ────────

def _memory_file(user_id: str) -> Path:
    return MEMORY_DIR / f"{user_id}.json"

def load_user_memories(user_id: str) -> list:
    """Load memory entries: [{"fact": "...", "ts": 123}]"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    f = _memory_file(user_id)
    if f.exists():
        try:
            with open(f, "r") as fh:
                return json.load(fh)
        except Exception:
            pass
    return []

def save_user_memory(user_id: str, fact: str):
    """Save a fact to Mem0 (vector + graph memory) AND local JSON fallback."""
    # 1. Mem0 speichern (primär)
    try:
        import httpx
        resp = httpx.post(
            "http://localhost:8002/v1/memories/",
            json={"messages": [{"role": "user", "content": f"Merke dir: {fact}"}], "user_id": user_id},
            timeout=30.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            count = len(data.get("results", []))
            logger.info(f"Mem0 memory saved for {user_id}: {count} entries extracted")
        else:
            logger.warning(f"Mem0 save HTTP {resp.status_code} for {user_id}")
    except Exception as e:
        logger.warning(f"Mem0 save failed for {user_id}: {e}")

    # 2. Lokaler JSON-Fallback (damit alte Logik weiter funktioniert)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    memories = load_user_memories(user_id)
    memories.append({"fact": fact, "ts": int(time.time())})
    if len(memories) > 100:
        memories = memories[-100:]
    try:
        with open(_memory_file(user_id), "w") as f:
            json.dump(memories, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Local memory save failed for {user_id}: {e}")

def get_user_memory_context(user_id: str) -> str:
    """Get formatted user memory string."""
    memories = load_user_memories(user_id)
    if not memories:
        return ""
    facts = [m["fact"] for m in memories[-20:]]  # Last 20 memories
    return "\n".join(f"- {fact}" for fact in facts)


# ──────── Core Memory (SQLite system vars + agent memory) ────────

def get_core_memory_context(agent: Optional[str] = None) -> str:
    """Get system vars + agent-specific memories as context string."""
    try:
        conn = sqlite3.connect(CORE_MEMORY_DB)
        sys_rows = conn.execute("SELECT key, value FROM system_vars").fetchall()
        parts = []
        if sys_rows:
            sys_text = ", ".join(f"{k}={v}" for k, v in sys_rows)
            parts.append(f"System: {sys_text}")

        if agent:
            agent_rows = conn.execute(
                "SELECT key, value FROM agent_memory WHERE agent = ?", (agent,)
            ).fetchall()
            if agent_rows:
                agent_text = ", ".join(f"{k}={v}" for k, v in agent_rows)
                parts.append(f"Agent-Memory ({agent}): {agent_text}")

        conn.close()
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"Core memory read failed: {e}")
        return ""


# ──────── Memory Extraction (auto-detect facts to remember) ────────

MEMORY_TRIGGERS = [
    # German
    "merk dir", "merke dir", "erinner dich", "vergiss nicht", "notiere",
    # English
    "remember", "don't forget", "keep in mind", "note that",
    # Bosnian
    "zapamti", "memorisi", "ne zaboravi", "zapisi",
]

INTRO_PATTERNS = [
    "heisst", "heißt", "zove se", "called", "name is",
    "projekt", "project", "firma", "company",
    "ich bin", "i am", "ja sam",
    "mein name", "my name", "moje ime",
]

def extract_facts_from_message(message: str) -> list:
    """Auto-detect facts worth remembering from user message."""
    lower = message.lower()
    facts = []

    for trigger in MEMORY_TRIGGERS:
        if trigger in lower:
            facts.append(message.strip())
            return facts  # One match is enough

    for pattern in INTRO_PATTERNS:
        if pattern in lower and len(message) < 300:
            facts.append(message.strip())
            return facts

    return facts


# ──────── Anti-Hallucination Header ────────

ANTI_HALLUCINATION_HEADER = """== ANTI-HALLUZINATION REGELN (PFLICHT) ==
1. Nutze IMMER die bereitgestellten Kontextdaten ([KB], [HIPPO], [MEMORY], [CORE])
2. Priorisierung: USER MEMORY > KB CONTEXT > HIPPORAG > CORE MEMORY > Allgemeinwissen
3. Sage was du sicher weisst, gib zu was du nicht weisst: [KEINE_AHNUNG]
4. Bewerte deine Sicherheit: [SICHER] / [UNSICHER]
5. Erfinde NIEMALS Funktionen, URLs, Code oder Daten
6. Bei Widersprüchen: nenne beide Quellen und markiere [UNSICHER]
"""


# ──────── Main Enrichment Function ────────

async def enrich_for_agent(
    query: str,
    user_id: str = "anonymous",
    agent: Optional[str] = None,
    include_anti_hallucination: bool = True,
) -> str:
    """
    Central enrichment: takes a raw user query and returns it enriched with
    all available context (KB, HippoRAG, User Memory, Core Memory, Anti-Hallucination).

    This is the ONE function every client/agent should call.
    """
    # Parallel fetch: KB + HippoRAG
    kb_task = asyncio.create_task(fetch_kb(query))
    hippo_task = asyncio.create_task(fetch_hipporag(query))

    kb_context = await kb_task
    hippo_context = await hippo_task

    # Synchronous: User Memory + Core Memory
    user_mem = get_user_memory_context(user_id)
    core_mem = get_core_memory_context(agent)

    # Build enriched query
    has_context = any([kb_context, hippo_context, user_mem, core_mem])

    if not has_context and not include_anti_hallucination:
        return query

    parts = [query, ""]

    if include_anti_hallucination:
        parts.append(ANTI_HALLUCINATION_HEADER)

    if user_mem:
        parts.append(f"[USER MEMORY - Dinge die sich der User gemerkt hat]\n{user_mem}\n")
    if core_mem:
        parts.append(f"[CORE MEMORY - System-Variablen]\n{core_mem}\n")
    if kb_context:
        parts.append(f"[KB CONTEXT - Knowledge Base Dokumente]\n{kb_context}\n")
    if hippo_context:
        parts.append(f"[HIPPORAG CONTEXT - Knowledge Graph]\n{hippo_context}\n")

    if has_context:
        parts.append("[END CONTEXT]")

    logger.info(
        f"RAG enrichment for {agent or 'unknown'}: "
        f"KB={bool(kb_context)}, HIPPO={bool(hippo_context)}, "
        f"MEM={bool(user_mem)}, CORE={bool(core_mem)}"
    )

    return "\n".join(parts)


# ──────── Auto-learn from exchange ────────

def auto_learn(user_id: str, user_message: str, bot_response: str = ""):
    """Automatically extract and save facts from user message."""
    facts = extract_facts_from_message(user_message)
    for fact in facts:
        save_user_memory(user_id, fact)
    return facts


# ──────── Health Check ────────

async def health_check() -> dict:
    """Check all RAG components."""
    status = {"kb": False, "hipporag": False, "core_memory": False, "user_memory_dir": False}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
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

            try:
                resp = await client.post(
                    HIPPORAG_URL,
                    json={"query": "health", "top_k": 1},
                    headers={"Content-Type": "application/json"},
                )
                status["hipporag"] = resp.status_code == 200
            except:
                pass
    except:
        pass

    try:
        conn = sqlite3.connect(CORE_MEMORY_DB)
        conn.execute("SELECT 1 FROM system_vars LIMIT 1")
        conn.close()
        status["core_memory"] = True
    except:
        pass

    status["user_memory_dir"] = MEMORY_DIR.exists()

    return status
