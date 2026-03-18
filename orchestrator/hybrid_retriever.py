"""
Cloud Code Team - Hybrid Retriever (LlamaIndex)
================================================
Combines Vector-Search (Qdrant) + Graph-Search (Neo4j) + BGE Reranker
into a single retrieve() call. Drop-in upgrade for rag_middleware.py.

Architecture:
  Query → [Vector-Retriever (Qdrant)] ─┐
          [Graph-Retriever (Neo4j)]  ───┤→ Merge → BGE Reranker → Top-K
          [Mem0 Memory Search]       ───┘

Usage:
    from hybrid_retriever import HybridRetriever

    retriever = HybridRetriever()
    results = await retriever.retrieve("Wie funktioniert der Orchestrator?", agent="coder")
"""

import os
import sys
import asyncio
import logging
from typing import List, Optional, Dict, Any

# Fix: Prevent local 'workflows/' folder from shadowing llama-index-workflows package.
# Remove CWD from sys.path during LlamaIndex imports, then restore.
_cwd = os.path.dirname(os.path.abspath(__file__))
_path_modified = False
if _cwd in sys.path:
    sys.path.remove(_cwd)
    _path_modified = True

import httpx

# Restore CWD to sys.path for local workflow imports
if _path_modified and _cwd not in sys.path:
    sys.path.insert(0, _cwd)

logger = logging.getLogger("HybridRetriever")

# ──────── Configuration ────────
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "16333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "mem0_memories")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "22e58741703f24f1913550c9a8a51c99")

HIPPORAG_URL = os.getenv("HIPPORAG_URL", "http://localhost:8001/knowledge/query")
MEM0_URL = os.getenv("MEM0_URL", "http://localhost:8002")
SHARED_USER_ID = "cloud-code-team"

# Retrieval settings
VECTOR_TOP_K = int(os.getenv("VECTOR_TOP_K", "10"))
GRAPH_TOP_K = int(os.getenv("GRAPH_TOP_K", "5"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "5"))
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.3"))  # Min cosine score for vector/mem0 hits (graph sources exempt)
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")  # NOTE: dead code — Qdrant uses bge-m3 via Ollama directly

# ──────── Lazy-loaded components ────────
_qdrant_client = None
_vector_store = None
_neo4j_store = None
_reranker = None
_embed_model = None
_initialized = False


def _init_components():
    """Lazy-init all LlamaIndex components (heavy imports, run once)."""
    global _qdrant_client, _vector_store, _neo4j_store, _reranker, _embed_model, _initialized

    if _initialized:
        return

    logger.info("Initializing Hybrid Retriever components...")

    # Temporarily remove CWD to avoid workflows/ namespace collision
    _local = os.path.dirname(os.path.abspath(__file__))
    _removed = False
    if _local in sys.path:
        sys.path.remove(_local)
        _removed = True

    # 1. Qdrant
    try:
        from qdrant_client import QdrantClient
        from llama_index.vector_stores.qdrant import QdrantVectorStore

        _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=10)
        _vector_store = QdrantVectorStore(
            client=_qdrant_client,
            collection_name=QDRANT_COLLECTION,
        )
        logger.info(f"Qdrant connected: {QDRANT_HOST}:{QDRANT_PORT}/{QDRANT_COLLECTION}")
    except Exception as e:
        logger.error(f"Qdrant init failed: {e}")
        _vector_store = None

    # 2. Neo4j
    try:
        from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

        _neo4j_store = Neo4jPropertyGraphStore(
            username=NEO4J_USER,
            password=NEO4J_PASSWORD,
            url=NEO4J_URI,
        )
        logger.info(f"Neo4j connected: {NEO4J_URI}")
    except Exception as e:
        logger.error(f"Neo4j init failed: {e}")
        _neo4j_store = None

    # 3. BGE Reranker
    try:
        from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

        _reranker = FlagEmbeddingReranker(
            model=RERANKER_MODEL,
            top_n=RERANK_TOP_N,
        )
        logger.info(f"BGE Reranker loaded: {RERANKER_MODEL}")
    except Exception as e:
        logger.error(f"Reranker init failed: {e}")
        _reranker = None

    # 4. FastEmbed
    try:
        from llama_index.embeddings.fastembed import FastEmbedEmbedding

        _embed_model = FastEmbedEmbedding(model_name=EMBED_MODEL)
        logger.info(f"FastEmbed loaded: {EMBED_MODEL}")
    except Exception as e:
        logger.error(f"FastEmbed init failed: {e}")
        _embed_model = None

    # Restore path
    if _removed and _local not in sys.path:
        sys.path.insert(0, _local)

    _initialized = True
    logger.info("Hybrid Retriever initialized.")


# ──────── Retrieval Functions ────────

async def _search_qdrant_direct(query: str, top_k: int = VECTOR_TOP_K) -> List[Dict[str, Any]]:
    """Search Qdrant directly using the client (faster than LlamaIndex index)."""
    _init_components()
    if not _qdrant_client or not _embed_model:
        return []

    try:
        # Embed query
        query_vector = _embed_model.get_text_embedding(query)

        # Search — collection uses 1024-dim (bge-m3:latest). Use Ollama bge-m3 for embedding.
        # Use Ollama for embedding to match the collection's dimensionality.
        import httpx as hx
        async with hx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "http://localhost:11434/api/embeddings",
                json={"model": "bge-m3:latest", "prompt": query},
            )
            if resp.status_code == 200:
                query_vector = resp.json().get("embedding", [])
            else:
                logger.warning("Ollama embedding failed, skipping Qdrant search")
                return []

        # Search Qdrant (compatible with both old and new client API)
        hits = []
        try:
            # New API (qdrant-client >= 1.12)
            from qdrant_client.models import models as qmodels
            results = _qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
            points = results.points if hasattr(results, 'points') else results
        except (AttributeError, TypeError):
            # Old API fallback
            results = _qdrant_client.search(
                collection_name=QDRANT_COLLECTION,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )
            points = results

        for r in points:
            payload = r.payload or {}
            hits.append({
                "text": payload.get("data", payload.get("memory", "")),
                "score": r.score if hasattr(r, 'score') else 0.5,
                "source": "qdrant-vector",
                "user_id": payload.get("user_id", ""),
                "metadata": payload,
            })
        logger.info(f"Qdrant search: {len(hits)} hits for '{query[:50]}'")
        return hits

    except Exception as e:
        logger.warning(f"Qdrant search failed: {e}")
        return []


async def _search_neo4j_graph(query: str, top_k: int = GRAPH_TOP_K) -> List[Dict[str, Any]]:
    """Query Neo4j knowledge graph via HippoRAG endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                HIPPORAG_URL,
                json={"query": query, "top_k": top_k},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                hits = []
                for r in results:
                    content = r if isinstance(r, str) else r.get("content", r.get("text", str(r)))
                    hits.append({
                        "text": content,
                        "score": r.get("score", 0.5) if isinstance(r, dict) else 0.5,
                        "source": "neo4j-graph",
                        "metadata": r if isinstance(r, dict) else {},
                    })
                logger.info(f"HippoRAG: {len(hits)} hits for '{query[:50]}'")
                return hits
    except Exception as e:
        logger.warning(f"HippoRAG query failed: {e}")
    return []


async def _search_neo4j_cypher(query: str, top_k: int = GRAPH_TOP_K) -> List[Dict[str, Any]]:
    """Direct Cypher query for entity/relationship lookup."""
    _init_components()
    if not _neo4j_store:
        return []

    try:
        import neo4j as neo4j_mod
        driver = neo4j_mod.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

        # Extract potential entity names from query (simple keyword extraction)
        keywords = [w for w in query.split() if len(w) > 3 and w[0].isupper()]
        if not keywords:
            keywords = [w for w in query.split() if len(w) > 4][:3]

        hits = []
        with driver.session() as session:
            for kw in keywords[:3]:
                result = session.run(
                    "MATCH (n)-[r]->(m) "
                    "WHERE n.name CONTAINS $kw OR m.name CONTAINS $kw OR n.id CONTAINS $kw "
                    "RETURN n.name AS source, type(r) AS rel, m.name AS target "
                    "LIMIT $limit",
                    kw=kw, limit=top_k,
                )
                for rec in result:
                    text = f"{rec['source']} --[{rec['rel']}]--> {rec['target']}"
                    hits.append({
                        "text": text,
                        "score": 0.6,
                        "source": "neo4j-cypher",
                        "metadata": {"query_keyword": kw},
                    })
        driver.close()
        logger.info(f"Neo4j Cypher: {len(hits)} hits for '{query[:50]}'")
        return hits

    except Exception as e:
        logger.warning(f"Neo4j Cypher failed: {e}")
        return []


async def _search_mem0_graph(query: str, agent: Optional[str] = None, top_k: int = GRAPH_TOP_K) -> List[Dict[str, Any]]:
    """Query mem0's entity graph in Neo4j.

    mem0 v1.0.6 stores entities with dynamic labels (person, project, technology/*)
    NOT the classic __Entity__ label. Query all nodes with relationships.
    Example: denis --[works_on]--> cloud_code_team_projekt
    """
    try:
        import neo4j as neo4j_mod
        driver = neo4j_mod.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

        # Extract keywords (strip punctuation, length > 2)
        keywords = [w.strip(".,!?:;()[]") for w in query.split() if len(w.strip(".,!?:;()[]")) > 2][:5]
        if not keywords:
            driver.close()
            return []

        hits = []
        seen_texts = set()
        with driver.session() as session:
            for kw in keywords[:4]:
                # Query: match any node-relationship-node where name contains keyword
                # Excludes HippoRAG-specific labels (Entity, Service, Database, etc.)
                # by only matching nodes whose labels indicate mem0 dynamic types
                result = session.run(
                    """
                    MATCH (n)-[r]->(m)
                    WHERE (toLower(n.name) CONTAINS toLower($kw)
                        OR toLower(m.name) CONTAINS toLower($kw))
                    AND NOT 'Entity' IN labels(n)
                    AND NOT 'Service' IN labels(n)
                    AND NOT 'Database' IN labels(n)
                    AND NOT 'Document' IN labels(n)
                    AND NOT 'Bug' IN labels(n)
                    RETURN n.name AS source, type(r) AS rel, m.name AS target
                    LIMIT $limit
                    """,
                    kw=kw, limit=top_k,
                )
                for rec in result:
                    text = f"{rec['source']} --[{rec['rel']}]--> {rec['target']}"
                    if text not in seen_texts:
                        seen_texts.add(text)
                        hits.append({
                            "text": text,
                            "score": 0.65,
                            "source": "mem0-graph",
                            "metadata": {"keyword": kw},
                        })

        driver.close()
        logger.info(f"Mem0 Graph: {len(hits)} entity relations for '{query[:50]}'")
        return hits

    except Exception as e:
        logger.warning(f"Mem0 graph search failed: {e}")
        return []


async def _search_mem0(query: str, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Dual-search Mem0: own (cct-{agent}) + shared (cloud-code-team)."""
    own_id = f"cct-{agent}" if agent else "unknown"
    hits = []

    async def _mem0_search(user_id: str, label: str):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{MEM0_URL}/v1/memories/search/",
                    json={"query": query, "user_id": user_id, "limit": 5},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Handle double-nested response
                    entries = data
                    if isinstance(entries, dict):
                        inner = entries.get("results", entries)
                        if isinstance(inner, dict):
                            inner = inner.get("results", [])
                        entries = inner
                    if isinstance(entries, list):
                        return [
                            {
                                "text": e.get("memory", ""),
                                "score": e.get("score", 0.5),
                                "source": f"mem0-{label}",
                                "user_id": user_id,
                                "metadata": e,
                            }
                            for e in entries
                            if isinstance(e, dict) and e.get("memory")
                        ]
        except Exception as e:
            logger.warning(f"Mem0 search failed for {user_id}: {e}")
        return []

    own_results, shared_results = await asyncio.gather(
        _mem0_search(own_id, "own"),
        _mem0_search(SHARED_USER_ID, "shared"),
    )

    hits = own_results + shared_results
    logger.info(f"Mem0: {len(own_results)} own + {len(shared_results)} shared for '{query[:50]}'")
    return hits


def _rerank(query: str, hits: List[Dict[str, Any]], top_n: int = RERANK_TOP_N) -> List[Dict[str, Any]]:
    """Rerank merged results using BGE Reranker."""
    _init_components()

    if not hits:
        return []

    if not _reranker:
        # Fallback: sort by score
        logger.warning("Reranker not available, using score-based sort")
        return sorted(hits, key=lambda x: x.get("score", 0), reverse=True)[:top_n]

    try:
        from llama_index.core.schema import NodeWithScore, TextNode
        from llama_index.core import QueryBundle

        # Convert to LlamaIndex nodes
        nodes = []
        for h in hits:
            if not h.get("text"):
                continue
            node = NodeWithScore(
                node=TextNode(
                    text=h["text"],
                    metadata={"source": h.get("source", "unknown"), "original_score": h.get("score", 0)},
                ),
                score=h.get("score", 0),
            )
            nodes.append(node)

        if not nodes:
            return []

        # Rerank
        query_bundle = QueryBundle(query_str=query)
        ranked = _reranker.postprocess_nodes(nodes, query_bundle)

        # Convert back
        result = []
        for n in ranked:
            result.append({
                "text": n.node.text,
                "score": n.score,
                "source": n.node.metadata.get("source", "unknown"),
                "original_score": n.node.metadata.get("original_score", 0),
                "metadata": n.node.metadata,
            })

        logger.info(f"Reranked: {len(hits)} -> {len(result)} results")
        return result

    except Exception as e:
        logger.warning(f"Reranker failed: {e}")
        return sorted(hits, key=lambda x: x.get("score", 0), reverse=True)[:top_n]


# ──────── Main API ────────

class HybridRetriever:
    """
    Hybrid Retriever combining Vector + Graph + Memory search with reranking.

    Usage:
        retriever = HybridRetriever()
        results = await retriever.retrieve("query", agent="coder")
        context_str = retriever.format_context(results)
    """

    def __init__(self):
        # Lazy init on first retrieve()
        pass

    async def retrieve(
        self,
        query: str,
        agent: Optional[str] = None,
        include_vector: bool = True,
        include_graph: bool = True,
        include_memory: bool = True,
        include_mem0_graph: bool = True,
        rerank: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Run hybrid retrieval: vector + graph + memory + mem0-graph in parallel, then rerank.

        Returns list of dicts with keys: text, score, source, metadata
        """
        tasks = []

        if include_vector:
            tasks.append(_search_qdrant_direct(query))

        if include_graph:
            tasks.append(_search_neo4j_graph(query))
            tasks.append(_search_neo4j_cypher(query))

        if include_memory:
            tasks.append(_search_mem0(query, agent))

        if include_mem0_graph:
            tasks.append(_search_mem0_graph(query, agent))

        # Run all searches in parallel
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        merged = []
        for result in all_results:
            if isinstance(result, Exception):
                logger.warning(f"Search task failed: {result}")
                continue
            if isinstance(result, list):
                merged.extend(result)

        logger.info(
            f"Hybrid retrieve: {len(merged)} total hits "
            f"(vector={include_vector}, graph={include_graph}, memory={include_memory}, mem0_graph={include_mem0_graph})"
        )

        # Deduplicate by text content
        seen = set()
        unique = []
        for hit in merged:
            text = hit.get("text", "").strip()
            if text and text not in seen:
                seen.add(text)
                unique.append(hit)

        # Filter low-quality vector/memory results (graph sources pass through — they use fixed scores)
        _vector_sources = {"qdrant-vector", "mem0-own", "mem0-shared"}
        filtered = [h for h in unique if h.get("source", "") not in _vector_sources or h.get("score", 0) >= SCORE_THRESHOLD]
        if len(filtered) < len(unique):
            logger.info(f"Score threshold ({SCORE_THRESHOLD}): {len(unique) - len(filtered)} low-quality hits removed")
        unique = filtered

        # Rerank
        if rerank and len(unique) > 1:
            return _rerank(query, unique)

        return unique[:RERANK_TOP_N]

    def format_context(self, results: List[Dict[str, Any]]) -> str:
        """Format retrieval results as context string for LLM prompt."""
        if not results:
            return ""

        parts = []
        for i, r in enumerate(results, 1):
            source = r.get("source", "unknown")
            score = r.get("score", 0)
            text = r.get("text", "")
            parts.append(f"[{i}. {source} | score={score:.3f}]\n{text}")

        return "\n\n".join(parts)

    async def health_check(self) -> Dict[str, Any]:
        """Check status of all retrieval components."""
        _init_components()
        return {
            "qdrant": _qdrant_client is not None and _vector_store is not None,
            "neo4j": _neo4j_store is not None,
            "reranker": _reranker is not None,
            "embed_model": _embed_model is not None,
            "reranker_model": RERANKER_MODEL,
            "embed_model_name": EMBED_MODEL,
            "qdrant_collection": QDRANT_COLLECTION,
        }


# ──────── Convenience function for rag_middleware.py ────────

_retriever_instance = None

async def hybrid_retrieve(query: str, agent: Optional[str] = None) -> str:
    """
    Drop-in replacement for fetch_kb + fetch_hipporag + fetch_mem0_context.
    Returns formatted context string ready for LLM prompt injection.
    """
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = HybridRetriever()

    results = await _retriever_instance.retrieve(query, agent=agent)
    return _retriever_instance.format_context(results)


async def hybrid_health() -> Dict[str, Any]:
    """Health check for the hybrid retriever."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = HybridRetriever()
    return await _retriever_instance.health_check()
