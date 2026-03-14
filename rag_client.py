"""
Cloud Code Team - Standard RAG Client
========================================
Reusable module for ALL agents to access the full RAG construct:
- Dify Knowledge Base (semantic search)
- HippoRAG Knowledge Graph (Neo4j-backed)

Usage:
    from rag_client import RAGClient

    rag = RAGClient()
    context = await rag.enrich("What is the workflow architecture?")
    # context is a string with [KB CONTEXT] and [HIPPORAG CONTEXT] sections

    # Or get raw results:
    kb = await rag.fetch_kb("query")
    hippo = await rag.fetch_hipporag("query")

Environment Variables (all optional, defaults work on server):
    DIFY_API_URL     - Dify API base URL (default: http://localhost:3080/v1)
    DIFY_KB_ID       - Knowledge Base dataset ID
    DIFY_KB_KEY      - Dataset API token
    HIPPORAG_URL     - HippoRAG endpoint URL
    RAG_TIMEOUT      - HTTP timeout in seconds (default: 10)
    RAG_KB_TOP_K     - KB results count (default: 5)
    RAG_HIPPO_TOP_K  - HippoRAG results count (default: 5)
"""
import os
import json
import asyncio
import logging
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger("RAGClient")

# Defaults — all secrets MUST come from environment variables
DEFAULT_DIFY_API_URL = "http://localhost:3080/v1"
DEFAULT_DIFY_KB_ID = os.getenv("DIFY_KB_ID", "")
DEFAULT_DIFY_KB_KEY = os.getenv("DIFY_KB_KEY", "")
DEFAULT_HIPPORAG_URL = "http://localhost:8001/knowledge/query"
DEFAULT_TIMEOUT = 10
DEFAULT_KB_TOP_K = 5
DEFAULT_HIPPO_TOP_K = 5


class RAGClient:
    """Standard RAG client for all Cloud Code Team agents."""

    def __init__(
        self,
        dify_api_url: Optional[str] = None,
        dify_kb_id: Optional[str] = None,
        dify_kb_key: Optional[str] = None,
        hipporag_url: Optional[str] = None,
        timeout: Optional[int] = None,
        kb_top_k: Optional[int] = None,
        hippo_top_k: Optional[int] = None,
    ):
        self.dify_api_url = dify_api_url or os.environ.get("DIFY_API_URL", DEFAULT_DIFY_API_URL)
        self.dify_kb_id = dify_kb_id or os.environ.get("DIFY_KB_ID", DEFAULT_DIFY_KB_ID)
        self.dify_kb_key = dify_kb_key or os.environ.get("DIFY_KB_KEY", DEFAULT_DIFY_KB_KEY)
        self.hipporag_url = hipporag_url or os.environ.get("HIPPORAG_URL", DEFAULT_HIPPORAG_URL)
        self.timeout = timeout or int(os.environ.get("RAG_TIMEOUT", DEFAULT_TIMEOUT))
        self.kb_top_k = kb_top_k or int(os.environ.get("RAG_KB_TOP_K", DEFAULT_KB_TOP_K))
        self.hippo_top_k = hippo_top_k or int(os.environ.get("RAG_HIPPO_TOP_K", DEFAULT_HIPPO_TOP_K))

    async def fetch_kb(self, query: str) -> str:
        """Search Dify Knowledge Base. Returns formatted context string or empty."""
        if not httpx:
            logger.warning("httpx not installed, KB fetch skipped")
            return ""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.dify_api_url}/datasets/{self.dify_kb_id}/retrieve",
                    json={
                        "query": query,
                        "retrieval_model": {
                            "search_method": "semantic_search",
                            "top_k": self.kb_top_k,
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
                        "Authorization": f"Bearer {self.dify_kb_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    records = data.get("records", [])
                    if records:
                        chunks = []
                        for rec in records[: self.kb_top_k]:
                            seg = rec.get("segment", {})
                            content = seg.get("content", "")
                            doc_name = rec.get("document", {}).get("name", "unknown")
                            score = rec.get("score", 0)
                            if content:
                                chunks.append(f"[{doc_name} | score={score:.2f}]\n{content}")
                        if chunks:
                            return "\n\n".join(chunks)
                else:
                    logger.warning(f"KB API returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"KB fetch failed: {e}")
        return ""

    async def fetch_hipporag(self, query: str) -> str:
        """Query HippoRAG knowledge graph. Returns formatted facts or empty."""
        if not httpx:
            logger.warning("httpx not installed, HippoRAG fetch skipped")
            return ""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.hipporag_url,
                    json={"query": query, "top_k": self.hippo_top_k},
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if results:
                        facts = []
                        for r in results:
                            # Handle nodes
                            nodes = r.get("nodes", [])
                            for node in nodes:
                                name = node.get("name", "")
                                ntype = node.get("type", "")
                                if name:
                                    facts.append(f"[{ntype}] {name}")

                            # Handle relationships (from/type/to format)
                            rels = r.get("relationships", [])
                            for rel in rels:
                                src = rel.get("from", "")
                                rtype = rel.get("type", "")
                                tgt = rel.get("to", "")
                                if src and rtype and tgt:
                                    facts.append(f"{src} --{rtype}--> {tgt}")

                            # Fallback: subject/predicate/object format
                            subj = r.get("subject", "")
                            pred = r.get("predicate", "")
                            obj = r.get("object", "")
                            if subj and pred and obj:
                                facts.append(f"{subj} {pred} {obj}")

                        if facts:
                            # Deduplicate while preserving order
                            seen = set()
                            unique = []
                            for f in facts:
                                if f not in seen:
                                    seen.add(f)
                                    unique.append(f)
                            return "\n".join(unique)
                else:
                    logger.warning(f"HippoRAG returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"HippoRAG fetch failed: {e}")
        return ""

    async def enrich(self, query: str) -> str:
        """
        Enrich a user query with full RAG context.
        Fetches KB and HippoRAG in parallel, returns enriched query string.
        """
        kb_task = asyncio.create_task(self.fetch_kb(query))
        hippo_task = asyncio.create_task(self.fetch_hipporag(query))

        kb_context = await kb_task
        hippo_context = await hippo_task

        logger.info(f"RAG enrichment: KB={bool(kb_context)}, HIPPO={bool(hippo_context)}")

        if not kb_context and not hippo_context:
            return query

        enriched = f"{query}\n\n"
        if kb_context:
            enriched += f"[KB CONTEXT]\n{kb_context}\n\n"
        if hippo_context:
            enriched += f"[HIPPORAG CONTEXT]\n{hippo_context}\n\n"
        enriched += "[END CONTEXT]"

        return enriched

    def enrich_sync(self, query: str) -> str:
        """Synchronous wrapper for enrich(). Use in non-async code."""
        return asyncio.run(self.enrich(query))

    async def health_check(self) -> dict:
        """Check if KB and HippoRAG services are reachable."""
        status = {"kb": False, "hipporag": False}
        if not httpx:
            return status
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                try:
                    resp = await client.post(
                        f"{self.dify_api_url}/datasets/{self.dify_kb_id}/retrieve",
                        json={"query": "health", "retrieval_model": {
                            "search_method": "semantic_search", "top_k": 1,
                            "score_threshold_enabled": False, "score_threshold": None,
                            "reranking_enable": False, "reranking_mode": None,
                            "reranking_model": {"reranking_model_name": None, "reranking_provider_name": None},
                            "weights": None
                        }},
                        headers={"Authorization": f"Bearer {self.dify_kb_key}", "Content-Type": "application/json"},
                    )
                    status["kb"] = resp.status_code == 200
                except Exception:
                    pass

                try:
                    resp = await client.post(
                        self.hipporag_url,
                        json={"query": "health", "top_k": 1},
                        headers={"Content-Type": "application/json"},
                    )
                    status["hipporag"] = resp.status_code == 200
                except Exception:
                    pass
        except Exception:
            pass
        return status


# ──────── Convenience: 1-click usage ────────

_default_client: Optional[RAGClient] = None

def get_rag_client(**kwargs) -> RAGClient:
    """Get or create the default RAG client singleton."""
    global _default_client
    if _default_client is None:
        _default_client = RAGClient(**kwargs)
    return _default_client

async def enrich_query(query: str) -> str:
    """1-click: Enrich a query with full RAG context."""
    return await get_rag_client().enrich(query)

async def rag_health() -> dict:
    """1-click: Check RAG services health."""
    return await get_rag_client().health_check()
