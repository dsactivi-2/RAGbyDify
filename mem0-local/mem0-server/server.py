#!/usr/bin/env python3
"""
Cloud Code Team — Lokaler Mem0 API Server
==========================================
Drop-in Ersatz für api.mem0.ai
Gleiche API-Endpunkte, gleiche Responses — aber alles lokal.
Nutzt Qdrant (Vector), Neo4j (Graph), Ollama (LLM + Embedding)
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from mem0 import Memory

# ──────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────

def safe_get_all(**kwargs) -> list:
    """Wrapper für memory.get_all() — fängt 'unhashable type: slice' Bug ab.
    Fallback: leere Liste + Warnung statt 500er."""
    try:
        result = memory.get_all(**kwargs)
        # mem0 gibt manchmal dict mit "results" key zurück
        if isinstance(result, dict):
            return result.get("results", [])
        if isinstance(result, list):
            return result
        return list(result) if result else []
    except TypeError as e:
        if "unhashable type" in str(e):
            logger.warning("get_all() hit known slice bug — returning empty list. Filter: %s", kwargs)
            return []
        raise


# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────

LOG_LEVEL = os.getenv("MEM0_LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mem0-local")

MEM0_CONFIG = {
    "version": "v1.1",

    "llm": {
        "provider": os.getenv("LLM_PROVIDER", "ollama"),
        "config": {
            "model": os.getenv("LLM_MODEL", "glm-4.7:cloud"),
            "ollama_base_url": os.getenv("LLM_BASE_URL", "http://host.docker.internal:11434"),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.1")),
            "max_tokens": 4096,
        }
    },

    "embedder": {
        "provider": os.getenv("EMBEDDER_PROVIDER", "ollama"),
        "config": {
            "model": os.getenv("EMBEDDER_MODEL", "qwen3-embedding:latest"),
            "ollama_base_url": os.getenv("EMBEDDER_BASE_URL", "http://host.docker.internal:11434"),
            "embedding_dims": int(os.getenv("EMBEDDER_EMBEDDING_DIMS", "1536")),
        }
    },

    "vector_store": {
        "provider": os.getenv("VECTOR_STORE_PROVIDER", "qdrant"),
        "config": {
            "url": os.getenv("QDRANT_URL", "http://qdrant:6333"),
            "collection_name": os.getenv("QDRANT_COLLECTION", "mem0_memories"),
            "embedding_model_dims": int(os.getenv("EMBEDDER_EMBEDDING_DIMS", "1536")),
        }
    },

}

# Conditionally add graph_store (disabled if GRAPH_STORE_PROVIDER=none or empty)
_graph_provider = os.getenv("GRAPH_STORE_PROVIDER", "neo4j")
if _graph_provider and _graph_provider.lower() not in ("none", "disabled", ""):
    MEM0_CONFIG["graph_store"] = {
        "provider": _graph_provider,
        "config": {
            "url": os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            "username": os.getenv("NEO4J_USER", "neo4j"),
            "password": os.getenv("NEO4J_PASSWORD", "22e58741703f24f1913550c9a8a51c99"),
        }
    }

# ──────────────────────────────────────────
# MEMORY INSTANCE
# ──────────────────────────────────────────

memory: Optional[Memory] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Memory on startup"""
    global memory
    logger.info("Initializing Mem0 with config: %s", json.dumps({
        k: {kk: "..." if "password" in kk or "key" in kk else vv
            for kk, vv in v.get("config", {}).items()}
        for k, v in MEM0_CONFIG.items() if isinstance(v, dict) and "config" in v
    }, indent=2))

    try:
        memory = Memory.from_config(MEM0_CONFIG)
        logger.info("✅ Mem0 Memory initialized successfully")
        logger.info("   Vector Store: %s @ %s", MEM0_CONFIG["vector_store"]["provider"],
                     MEM0_CONFIG["vector_store"]["config"]["url"])
        if "graph_store" in MEM0_CONFIG:
            logger.info("   Graph Store:  %s @ %s", MEM0_CONFIG["graph_store"]["provider"],
                         MEM0_CONFIG["graph_store"]["config"]["url"])
        else:
            logger.info("   Graph Store:  disabled")
        logger.info("   LLM:          %s (%s)", MEM0_CONFIG["llm"]["config"]["model"],
                     MEM0_CONFIG["llm"]["provider"])
        logger.info("   Embedder:     %s (%s)", MEM0_CONFIG["embedder"]["config"]["model"],
                     MEM0_CONFIG["embedder"]["provider"])
    except Exception as e:
        logger.error("❌ Failed to initialize Mem0: %s", str(e))
        raise

    yield

    logger.info("Shutting down Mem0 server")


# ──────────────────────────────────────────
# FASTAPI APP
# ──────────────────────────────────────────

app = FastAPI(
    title="Cloud Code Team — Mem0 Local API",
    description="Lokaler Drop-in Ersatz für api.mem0.ai mit Graph Memory",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────

class AddMemoryRequest(BaseModel):
    messages: List[dict] | str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[dict] = None
    output_format: Optional[str] = "v1.1"

class SearchMemoryRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    limit: Optional[int] = 10
    output_format: Optional[str] = "v1.1"

class UpdateMemoryRequest(BaseModel):
    data: str

class MemoryResponse(BaseModel):
    results: list
    relations: Optional[list] = None

# ──────────────────────────────────────────
# API ENDPOINTS (kompatibel mit mem0.ai API)
# ──────────────────────────────────────────

@app.get("/health")
async def health():
    """Healthcheck Endpoint"""
    return {
        "status": "healthy",
        "service": "mem0-local",
        "timestamp": datetime.utcnow().isoformat(),
        "vector_store": "qdrant",
        "graph_store": "neo4j",
        "llm": MEM0_CONFIG["llm"]["config"]["model"],
    }


@app.get("/v1/memories/")
async def list_memories(
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 100,
):
    """Alle Memories auflisten (gefiltert)"""
    try:
        kwargs = {}
        if user_id:
            kwargs["user_id"] = user_id
        if agent_id:
            kwargs["agent_id"] = agent_id
        if run_id:
            kwargs["run_id"] = run_id

        results = safe_get_all(**kwargs)
        logger.info("Listed %d memories for %s", len(results), kwargs)
        return {"results": results[:limit]}
    except Exception as e:
        logger.error("Error listing memories: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/memories/")
async def add_memory(req: AddMemoryRequest):
    """Memory hinzufügen (Hauptendpoint für Dify Plugin)"""
    try:
        # Messages normalisieren
        if isinstance(req.messages, str):
            messages = [{"role": "user", "content": req.messages}]
        else:
            messages = req.messages

        kwargs = {"messages": messages}
        if req.user_id:
            kwargs["user_id"] = req.user_id
        if req.agent_id:
            kwargs["agent_id"] = req.agent_id
        if req.run_id:
            kwargs["run_id"] = req.run_id
        if req.metadata:
            kwargs["metadata"] = req.metadata

        result = memory.add(**kwargs)
        logger.info("✅ Memory added: user=%s agent=%s | %d memories extracted",
                     req.user_id, req.agent_id, len(result.get("results", [])))
        return result
    except Exception as e:
        logger.error("❌ Error adding memory: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/memories/search/")
async def search_memories(req: SearchMemoryRequest):
    """Memory suchen (Hauptendpoint für Dify Plugin)"""
    try:
        kwargs = {"query": req.query}
        if req.user_id:
            kwargs["user_id"] = req.user_id
        if req.agent_id:
            kwargs["agent_id"] = req.agent_id
        if req.run_id:
            kwargs["run_id"] = req.run_id
        if req.limit:
            kwargs["limit"] = req.limit

        results = memory.search(**kwargs)
        logger.info("🔍 Memory search: query='%s' user=%s agent=%s → %d results",
                     req.query[:50], req.user_id, req.agent_id, len(results))
        return {"results": results}
    except Exception as e:
        logger.error("❌ Error searching memory: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/memories/{memory_id}/")
async def get_memory(memory_id: str):
    """Einzelne Memory abrufen"""
    try:
        result = memory.get(memory_id)
        if not result:
            raise HTTPException(status_code=404, detail="Memory not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting memory %s: %s", memory_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/v1/memories/{memory_id}/")
async def update_memory(memory_id: str, req: UpdateMemoryRequest):
    """Memory aktualisieren"""
    try:
        result = memory.update(memory_id, data=req.data)
        logger.info("✏️ Memory updated: %s", memory_id)
        return result
    except Exception as e:
        logger.error("Error updating memory %s: %s", memory_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/v1/memories/{memory_id}/")
async def delete_memory(memory_id: str):
    """Memory löschen"""
    try:
        memory.delete(memory_id)
        logger.info("🗑️ Memory deleted: %s", memory_id)
        return {"status": "deleted", "memory_id": memory_id}
    except Exception as e:
        logger.error("Error deleting memory %s: %s", memory_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/v1/memories/")
async def delete_all_memories(user_id: Optional[str] = None, agent_id: Optional[str] = None):
    """Alle Memories löschen (gefiltert)"""
    try:
        kwargs = {}
        if user_id:
            kwargs["user_id"] = user_id
        if agent_id:
            kwargs["agent_id"] = agent_id

        memory.delete_all(**kwargs)
        logger.info("🗑️ All memories deleted for %s", kwargs)
        return {"status": "deleted", "filters": kwargs}
    except Exception as e:
        logger.error("Error deleting memories: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/memories/history/{memory_id}/")
async def get_memory_history(memory_id: str):
    """Memory-Änderungshistorie"""
    try:
        result = memory.history(memory_id)
        return {"results": result}
    except Exception as e:
        logger.error("Error getting history for %s: %s", memory_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/entities/")
async def list_entities(
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
):
    """Entities auflisten (wie Mem0 Dashboard)"""
    try:
        kwargs = {}
        if user_id:
            kwargs["user_id"] = user_id
        if agent_id:
            kwargs["agent_id"] = agent_id
        if run_id:
            kwargs["run_id"] = run_id
        # Default to shared user if no filter given
        if not kwargs:
            kwargs["user_id"] = "cloud-code-team"
        all_memories = safe_get_all(**kwargs)
        entities = {}
        for mem in all_memories:
            uid = mem.get("user_id", "unknown")
            aid = mem.get("agent_id", "")
            key = f"{uid}:{aid}" if aid else uid
            if key not in entities:
                entities[key] = {
                    "user_id": uid,
                    "agent_id": aid,
                    "memory_count": 0,
                    "last_updated": mem.get("updated_at", ""),
                }
            entities[key]["memory_count"] += 1

        return {"results": list(entities.values())}
    except Exception as e:
        logger.error("Error listing entities: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────
# GRAPH MEMORY ENDPOINTS (Pro-Feature, lokal gratis!)
# ──────────────────────────────────────────

@app.get("/v1/graph/")
async def get_graph(user_id: Optional[str] = None):
    """Graph Memory Relationen abrufen"""
    try:
        # Graph-basierte Suche über Neo4j
        kwargs = {}
        if user_id:
            kwargs["user_id"] = user_id

        all_mems = safe_get_all(**kwargs)
        # Relationen werden automatisch von mem0 in Neo4j gespeichert
        return {
            "nodes": len(all_mems),
            "memories": all_mems,
            "graph_store": "neo4j",
            "status": "active"
        }
    except Exception as e:
        logger.error("Error getting graph: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────
# STATS & MONITORING
# ──────────────────────────────────────────

@app.get("/v1/stats/")
async def get_stats(user_id: Optional[str] = "cloud-code-team"):
    """Statistiken für Dashboard"""
    try:
        kwargs = {}
        if user_id:
            kwargs["user_id"] = user_id
        all_memories = safe_get_all(**kwargs)

        # Pro Entity zählen
        by_user = {}
        by_agent = {}
        for mem in all_memories:
            uid = mem.get("user_id", "unknown")
            aid = mem.get("agent_id", "unknown")
            by_user[uid] = by_user.get(uid, 0) + 1
            by_agent[aid] = by_agent.get(aid, 0) + 1

        return {
            "total_memories": len(all_memories),
            "unique_users": len(by_user),
            "unique_agents": len(by_agent),
            "by_user": by_user,
            "by_agent": by_agent,
            "graph_store": "neo4j (active)",
            "vector_store": "qdrant (active)",
        }
    except Exception as e:
        logger.error("Error getting stats: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────
# RUN
# ──────────────────────────────────────────

if __name__ == "__main__":
    host = os.getenv("MEM0_HOST", "0.0.0.0")
    port = int(os.getenv("MEM0_PORT", "8002"))
    logger.info("🚀 Starting Mem0 Local API Server on %s:%d", host, port)
    uvicorn.run("server:app", host=host, port=port, log_level=LOG_LEVEL.lower(), workers=2)
