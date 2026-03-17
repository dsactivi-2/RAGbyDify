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

# ──────── Hybrid Retriever (LlamaIndex upgrade) ────────
USE_HYBRID_RETRIEVER = os.getenv("USE_HYBRID_RETRIEVER", "true").lower() == "true"
_hybrid_retriever = None

async def _get_hybrid_context(query: str, agent: str = None) -> str:
    global _hybrid_retriever
    if not USE_HYBRID_RETRIEVER:
        return ""
    try:
        if _hybrid_retriever is None:
            from hybrid_retriever import HybridRetriever
            _hybrid_retriever = HybridRetriever()
        results = await _hybrid_retriever.retrieve(query, agent=agent)
        if results:
            return _hybrid_retriever.format_context(results)
    except Exception as e:
        logger.warning(f"Hybrid retriever failed, falling back to legacy: {e}")
    return ""


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
# ──────── Memory Scope Configuration ────────
# SHARED memory: project-level facts accessible to ALL agents
SHARED_USER_ID = "cloud-code-team"
# PRIVATE memory: per-agent facts (user_id = "cct-{agent}")
# Access Policy:
#   READ:  own (cct-{agent}) + shared (cloud-code-team) — merged, labeled
#   WRITE: own (cct-{agent}) only — shared writes require explicit /memories/team endpoint


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




# ──────── Mem0 Dual-Search (Own + Shared) ────────

async def fetch_mem0_context(query: str, user_id: str, agent=None) -> str:
    """
    Dual-search: queries BOTH the agent-specific memory AND shared team memory.
    Results are labeled with their source scope for transparency.

    Memory Hierarchy:
      1. Own agent memory (cct-{agent}) -- highest priority
      2. Shared team memory (cloud-code-team) -- project context
    """
    own_id = f"cct-{agent}" if agent else user_id

    async def _search_mem0(client, uid, label):
        try:
            resp = await client.post(
                "http://localhost:8002/v1/memories/search/",
                json={"query": query, "user_id": uid, "limit": 5},
                timeout=10.0
            )
            if resp.status_code == 200:
                data = resp.json()
                # Mem0 search returns {"results": {"results": [...]}} - double nested
                entries = data
                if isinstance(entries, dict):
                    inner = entries.get("results", entries)
                    if isinstance(inner, dict):
                        inner = inner.get("results", [])
                    entries = inner
                if isinstance(entries, list):
                    return [(e.get("memory", ""), e.get("score", 0), label) for e in entries if isinstance(e, dict) and e.get("memory")]
        except Exception as e:
            logger.warning(f"Mem0 search failed for {uid}: {e}")
        return []

    results_own = []
    results_shared = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            own_task = asyncio.create_task(_search_mem0(client, own_id, f"OWN:{own_id}"))
            shared_task = asyncio.create_task(_search_mem0(client, SHARED_USER_ID, f"SHARED:{SHARED_USER_ID}"))
            results_own = await own_task
            results_shared = await shared_task
    except Exception as e:
        logger.warning(f"Mem0 dual-search error: {e}")

    all_results = results_own + results_shared
    if not all_results:
        return ""

    seen = set()
    unique = []
    for memory, score, label in all_results:
        mem_key = memory.strip().lower()[:100]
        if mem_key not in seen:
            seen.add(mem_key)
            unique.append(f"[{label}] {memory}")

    return "\n".join(unique[:10])

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
    Uses classify_intent to skip unnecessary RAG sources (T-SYS03 optimization).
    """
    # ──────── Intent Classification (T-SYS03 Fix) ────────
    # Determines which RAG sources are actually needed — skips all for trivial queries
    intent = await classify_intent(query)
    needs_rag = any([intent["kb"], intent["hipporag"], intent["mem0"], intent["core"]])

    if not needs_rag:
        logger.info(
            f"Intent [SKIP]: trivial query, no RAG needed "
            f"(classifier={intent.get('classifier')}, agent={agent or 'unknown'})"
        )
        if not include_anti_hallucination:
            return query
        return query + "\n\n" + ANTI_HALLUCINATION_HEADER

    # ──────── Hybrid Retriever (primary) ────────
    hybrid_context = ""
    if USE_HYBRID_RETRIEVER and (intent["kb"] or intent["hipporag"]):
        hybrid_context = await _get_hybrid_context(query, agent)

    # ──────── Legacy fallback if hybrid is off or returned nothing ────────
    kb_context = ""
    hippo_context = ""
    mem0_context = ""
    if not hybrid_context:
        tasks = []
        if intent["kb"]:
            kb_task = asyncio.create_task(fetch_kb(query))
            tasks.append(("kb", kb_task))
        if intent["hipporag"]:
            hippo_task = asyncio.create_task(fetch_hipporag(query))
            tasks.append(("hippo", hippo_task))
        if intent["mem0"]:
            mem0_task = asyncio.create_task(fetch_mem0_context(query, user_id, agent))
            tasks.append(("mem0", mem0_task))

        for name, task in tasks:
            result = await task
            if name == "kb":
                kb_context = result
            elif name == "hippo":
                hippo_context = result
            elif name == "mem0":
                mem0_context = result

    # Synchronous: Legacy User Memory + Core Memory (only if intent.core)
    user_mem = get_user_memory_context(user_id) if intent["core"] else ""
    core_mem = get_core_memory_context(agent) if intent["core"] else ""

    # Build enriched query
    has_context = any([hybrid_context, kb_context, hippo_context, user_mem, core_mem, mem0_context])

    if not has_context and not include_anti_hallucination:
        return query

    parts = [query, ""]

    if include_anti_hallucination:
        parts.append(ANTI_HALLUCINATION_HEADER)

    # Hybrid context (merged + reranked) takes priority
    if hybrid_context:
        parts.append(f"[HYBRID CONTEXT - Vector + Graph + Memory (reranked)]\n{hybrid_context}\n")

    # Legacy sources as fallback
    if user_mem:
        parts.append(f"[USER MEMORY - Dinge die sich der User gemerkt hat]\n{user_mem}\n")
    if mem0_context:
        parts.append(f"[MEM0 MEMORY - Eigene + Team-Erinnerungen]\n{mem0_context}\n")
    if core_mem:
        parts.append(f"[CORE MEMORY - System-Variablen]\n{core_mem}\n")
    if kb_context:
        parts.append(f"[KB CONTEXT - Knowledge Base Dokumente]\n{kb_context}\n")
    if hippo_context:
        parts.append(f"[HIPPORAG CONTEXT - Knowledge Graph]\n{hippo_context}\n")

    if has_context:
        parts.append("[END CONTEXT]")

    mode = "HYBRID" if hybrid_context else "LEGACY"
    logger.info(
        f"RAG enrichment [{mode}] for {agent or 'unknown'}: "
        f"intent={intent.get('classifier')}, "
        f"HYBRID={bool(hybrid_context)}, KB={bool(kb_context)}, HIPPO={bool(hippo_context)}, "
        f"MEM0={bool(mem0_context)}, LEGACY_MEM={bool(user_mem)}, CORE={bool(core_mem)}"
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


# ──────── Intent Classifier (T-SYS03 Fix) ────────
# Gibt dem Orchestrator eine KI, die VORHER entscheidet welche Quellen noetig sind.
# Spart 5-40s pro Request bei trivialen Anfragen.

import re as _re

INTENT_CLASSIFIER_MODEL = "llama3.2:3b"  # local, reliable, no cloud dependency
INTENT_CLASSIFIER_TIMEOUT = 8  # max 8s, danach fallback auf "alles abfragen"
OLLAMA_URL = os.getenv("OLLAMA_CLOUD_URL", "http://localhost:11434")

INTENT_PROMPT = """Du bist ein Query-Classifier. Analysiere die User-Frage und entscheide welche Wissensquellen gebraucht werden.

Antworte NUR mit einem JSON-Objekt, NICHTS anderes. Kein Text, keine Erklaerung.

Quellen:
- kb: Projekt-Dokumentation (tech-stack, workflows, runbook, projektbeschreibung)
- hipporag: Beziehungen zwischen Konzepten (welcher Agent nutzt welches Modell, wie haengen Komponenten zusammen)
- mem0: Persoenliche Erinnerungen, Praeferenzen, Entscheidungen, was der User frueher gesagt hat
- core: System-Variablen (Projektname, Sprache, Version, Konfiguration)

Regeln:
- Gruesse, Smalltalk, einfache Ja/Nein → alles false
- Fragen ueber das Projekt, Architektur, Code → kb=true, hipporag=true
- Fragen ueber Praeferenzen, Entscheidungen, "was habe ich gesagt" → mem0=true
- Fragen ueber Beziehungen ("wer nutzt was", "wie haengt X mit Y zusammen") → hipporag=true
- Fragen ueber Konfiguration, Einstellungen → core=true
- Im Zweifel lieber true als false (besser zu viel Kontext als zu wenig)

User-Frage: {query}

JSON:"""

# Cache: gleiche Frage-Typen nicht doppelt klassifizieren
_intent_cache = {}
_CACHE_MAX = 200


def _normalize_for_cache(query: str) -> str:
    """Normalize query for cache lookup (lowercase, strip, first 100 chars)."""
    return query.strip().lower()[:100]


async def classify_intent(query: str) -> dict:
    """
    Classify user query to determine which RAG sources are needed.
    Returns: {"kb": bool, "hipporag": bool, "mem0": bool, "core": bool, "classifier": "llm"|"fast"|"fallback"}
    
    Fast-path: trivial queries (greetings, short messages) skip LLM entirely.
    LLM-path: minimax-m2.5 classifies in ~200-500ms.
    Fallback: if LLM fails or times out, return all=True (safe default).
    """
    # ── Fast-path: Greeting / Trivial Detection (0ms) ──
    lower = query.strip().lower()
    
    # Very short messages (< 15 chars) are almost always greetings/smalltalk
    if len(lower) < 20:
        greetings = ["hallo", "hi", "hey", "moin", "servus", "selam", "yo", "na",
                     "guten morgen", "guten tag", "guten abend", "good morning",
                     "hello", "danke", "thanks", "ok", "ja", "nein", "no", "yes",
                     "gut", "passt", "alles klar", "klar", "verstanden", "cool",
                     "sag ", "antworte", "super", "prima", "wie gehts", "wie geht"]
        for g in greetings:
            if lower.startswith(g) or lower == g:
                logger.info(f"Intent [FAST]: greeting detected -> all false")
                return {"kb": False, "hipporag": False, "mem0": False, "core": False, "classifier": "fast"}
    
    # ── Cache check ──
    cache_key = _normalize_for_cache(query)
    if cache_key in _intent_cache:
        cached = _intent_cache[cache_key]
        logger.info(f"Intent [CACHE]: {cached}")
        return {**cached, "classifier": "cache"}
    
    # ── Keyword-based fast classification (0ms, catches obvious cases) ──
    fast_result = _fast_classify(lower)
    if fast_result:
        logger.info(f"Intent [KEYWORD]: {fast_result}")
        _cache_intent(cache_key, fast_result)
        return {**fast_result, "classifier": "keyword"}
    
    # ── LLM Classification (~200-500ms) ──
    try:
        prompt = INTENT_PROMPT.replace("{query}", query[:500])
        
        async with httpx.AsyncClient(timeout=float(INTENT_CLASSIFIER_TIMEOUT)) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": INTENT_CLASSIFIER_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 120}
                }
            )
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip()
                parsed = _parse_intent_json(raw)
                if parsed:
                    logger.info(f"Intent [LLM]: {parsed} (raw: {raw[:80]})")
                    _cache_intent(cache_key, parsed)
                    return {**parsed, "classifier": "llm"}
                else:
                    logger.warning(f"Intent [LLM]: parse failed: {raw[:120]}")
    except Exception as e:
        logger.warning(f"Intent [LLM]: timeout/error ({e})")
    
    # ── Fallback: alles abfragen (sicher) ──
    logger.info(f"Intent [FALLBACK]: all true")
    return {"kb": True, "hipporag": True, "mem0": True, "core": True, "classifier": "fallback"}


def _fast_classify(lower: str) -> Optional[dict]:
    """Keyword-based fast classification. Returns None if unsure."""
    # Memory/Preference questions
    mem_kw = ["erinnerst", "merke", "merk dir", "was habe ich", "was hab ich",
              "praeferenz", "preference", "entscheidung", "decision", "letzte session",
              "was wollte ich", "was war", "frueher", "gesagt", "remember"]
    if any(kw in lower for kw in mem_kw):
        return {"kb": False, "hipporag": False, "mem0": True, "core": False}
    
    # Relationship questions -> HippoRAG
    rel_kw = ["zusammenhang", "beziehung", "verbind", "nutzt", "verwendet",
              "haengt zusammen", "abhaengig", "relationship", "connected"]
    if any(kw in lower for kw in rel_kw):
        return {"kb": True, "hipporag": True, "mem0": False, "core": False}
    
    # Project/Architecture questions -> KB + HippoRAG
    arch_kw = ["architektur", "architecture", "orchestrator", "agent", "dify",
               "mem0", "hipporag", "neo4j", "qdrant", "ollama", "port",
               "docker", "service", "endpoint", "api", "stack", "workflow",
               "deployment", "server", "config"]
    if any(kw in lower for kw in arch_kw):
        return {"kb": True, "hipporag": True, "mem0": False, "core": True}
    
    # Code questions -> KB
    code_kw = ["code", "function", "funktion", "fehler", "error", "bug", "fix",
               "implementier", "schreib", "erstell", "build", "deploy"]
    if any(kw in lower for kw in code_kw):
        return {"kb": True, "hipporag": False, "mem0": False, "core": False}
    
    # Config questions -> Core
    config_kw = ["einstellung", "setting", "konfiguration", "variable", "env",
                 "parameter", "version", "sprache", "language"]
    if any(kw in lower for kw in config_kw):
        return {"kb": False, "hipporag": False, "mem0": False, "core": True}
    
    return None  # unsure -> use LLM


def _parse_intent_json(raw: str) -> Optional[dict]:
    """Parse LLM response as JSON. Handles markdown code blocks and messy output."""
    # Strip markdown code blocks
    raw = raw.strip()
    if raw.startswith("```"):
        raw = _re.sub(r'^```(?:json)?\s*', '', raw)
        raw = _re.sub(r'\s*```$', '', raw)
    
    # Find JSON object
    match = _re.search(r'\{[^}]+\}', raw)
    if not match:
        return None
    
    try:
        data = json.loads(match.group())
        result = {
            "kb": bool(data.get("kb", True)),
            "hipporag": bool(data.get("hipporag", True)),
            "mem0": bool(data.get("mem0", True)),
            "core": bool(data.get("core", True)),
        }
        return result
    except (json.JSONDecodeError, TypeError):
        return None


def _cache_intent(key: str, result: dict):
    """Cache intent result with LRU eviction."""
    global _intent_cache
    if len(_intent_cache) >= _CACHE_MAX:
        # Remove oldest entry
        oldest = next(iter(_intent_cache))
        del _intent_cache[oldest]
    _intent_cache[key] = result
