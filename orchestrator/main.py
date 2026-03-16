"""
Cloud Code Team - Multi-Agent Orchestrator v3
FastAPI service that coordinates Dify Chatflow agents via streaming API
Workaround: Extracts LLM output from streaming node_finished events
(bypasses Dify v1.13 Answer-Node template resolution bug)
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
import os
import json
import logging
from rag_middleware import enrich_for_agent, auto_learn, health_check as rag_health

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

app = FastAPI(title="Cloud Code Team Orchestrator", version="3.0.0")

# Config
DIFY_API_URL = os.getenv("DIFY_API_URL", "https://difyv2.activi.io/v1")
AGENT_KEYS: Dict[str, str] = {}

# Agent roles
AGENT_ROLES = [
    "architect", "coder", "tester", "reviewer", "devops",
    "docs", "security", "planner", "debug", "worker", "coach"
]


# === 3-TIER MODEL CONFIGURATION (per Agent) ===
# Tier 1 (Code): MiniMax-M2.5 - architect, coder, devops, tester
# Tier 2 (Multilingual): GLM-4.7 - coach, planner, docs, worker, reviewer, security, debug
# Tier 3 (Guenstig): DeepSeek V3.2 - memory
AGENT_MODEL_CONFIG = {
    "architect":  {"model": "minimax-m2.5",  "tier": "tier1-code",         "temperature": 0.3, "provider": "ollama-cloud"},
    "coder":      {"model": "minimax-m2.5",  "tier": "tier1-code",         "temperature": 0.2, "provider": "ollama-cloud"},
    "devops":     {"model": "minimax-m2.5",  "tier": "tier1-code",         "temperature": 0.3, "provider": "ollama-cloud"},
    "tester":     {"model": "minimax-m2.5",  "tier": "tier1-code",         "temperature": 0.2, "provider": "ollama-cloud"},
    "planner":    {"model": "glm-4.7",      "tier": "tier2-multilingual",  "temperature": 0.4, "provider": "ollama-cloud"},
    "docs":       {"model": "glm-4.7",      "tier": "tier2-multilingual",  "temperature": 0.4, "provider": "ollama-cloud"},
    "reviewer":   {"model": "glm-4.7",      "tier": "tier2-multilingual",  "temperature": 0.3, "provider": "ollama-cloud"},
    "security":   {"model": "glm-4.7",      "tier": "tier2-multilingual",  "temperature": 0.2, "provider": "ollama-cloud"},
    "worker":     {"model": "glm-4.7",      "tier": "tier2-multilingual",  "temperature": 0.5, "provider": "ollama-cloud"},
    "debug":      {"model": "glm-4.7",      "tier": "tier2-multilingual",  "temperature": 0.3, "provider": "ollama-cloud"},
    "coach":      {"model": "glm-4.7",      "tier": "tier2-multilingual",  "temperature": 0.5, "provider": "ollama-cloud"},
    "memory":     {"model": "deepseek-v3.2",  "tier": "tier3-guenstig",      "temperature": 0.1, "provider": "ollama-cloud"},
}

EMBEDDING_CONFIG = {
    "model": "qwen3-embedding-8b",
    "provider": "ollama-local",
    "dimensions": 4096,
}

class TaskRequest(BaseModel):
    agent: str
    query: str
    user: str = "orchestrator"
    conversation_id: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None

class TaskResponse(BaseModel):
    agent: str
    answer: str
    conversation_id: str
    message_id: str
    sources: Optional[Dict[str, Any]] = None

class HealthResponse(BaseModel):
    status: str
    agents_configured: int
    agents_list: list
    version: str

@app.get("/health", response_model=HealthResponse)
async def health():
    configured = {k: v for k, v in AGENT_KEYS.items() if v}
    return HealthResponse(
        status="healthy",
        agents_configured=len(configured),
        agents_list=list(configured.keys()),
        version="3.0.0"
    )

async def _call_agent_streaming(api_key: str, query: str, user: str,
                                 conversation_id: str = "",
                                 inputs: Optional[Dict] = None, agent: str = "worker") -> Dict:
    """
    Call a Dify Chatflow agent using streaming mode and extract the LLM output
    from node_finished events. This bypasses the Answer-Node template bug.
    """
    llm_text = ""
    mem0_text = ""
    kb_results = []
    conv_id = ""
    msg_id = ""
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream(
            "POST",
            f"{DIFY_API_URL}/chat-messages",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "inputs": inputs or {},
                "query": query,
                "response_mode": "streaming",
                "conversation_id": conversation_id or "",
                "user": user
            }
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                    evt_type = event.get("event", "")
                    
                    # Capture conversation and message IDs
                    if not conv_id and event.get("conversation_id"):
                        conv_id = event["conversation_id"]
                    if not msg_id and event.get("message_id"):
                        msg_id = event["message_id"]
                    
                    if evt_type == "node_finished":
                        node_data = event.get("data", {})
                        node_type = node_data.get("node_type", "")
                        outputs = node_data.get("outputs", {})
                        
                        # Extract LLM text (the actual answer)
                        if node_type == "llm":
                            llm_text = outputs.get("text", "")
                        
                        # Extract Memory recall results
                        elif node_type == "tool" and "mem0" in node_data.get("title", "").lower():
                            if "abrufen" in node_data.get("title", "").lower() or "retrieve" in node_data.get("title", "").lower():
                                mem0_text = outputs.get("text", "")
                        
                        # Extract KB results
                        elif node_type == "knowledge-retrieval":
                            kb_results = outputs.get("result", [])
                    
                    elif evt_type == "error":
                        error_msg = event.get("message", "Unknown error")
                        raise Exception(f"Workflow error: {error_msg}")
                        
                except json.JSONDecodeError:
                    continue
    
    return {
        "answer": llm_text,
        "conversation_id": conv_id,
        "message_id": msg_id,
        "sources": {
            "memory": mem0_text[:500] if mem0_text else None,
            "kb_hits": len(kb_results),
        }
    }

@app.post("/task", response_model=TaskResponse)
async def run_task(req: TaskRequest):
    if req.agent not in AGENT_KEYS:
        raise HTTPException(404, f"Agent {req.agent} not found. Available: {list(AGENT_KEYS.keys())}")
    
    api_key = AGENT_KEYS[req.agent]
    if not api_key:
        raise HTTPException(400, f"Agent {req.agent} has no API key configured")
    
    try:
        result = await _call_agent_streaming(
            api_key=api_key,
            query=req.query,
            user=req.user,
            conversation_id=req.conversation_id or "",
            inputs=req.inputs,
            agent=req.agent
        )
        return TaskResponse(
            agent=req.agent,
            answer=result["answer"],
            conversation_id=result["conversation_id"],
            message_id=result["message_id"],
            sources=result.get("sources")
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Dify API error: {e.response.text[:500]}")
    except Exception as e:
        logger.error(f"Error calling agent {req.agent}: {str(e)}")
        raise HTTPException(500, f"Error calling agent {req.agent}: {str(e)}")

@app.post("/chain")
async def run_chain(agents: list[str], query: str, user: str = "orchestrator"):
    """Run a chain of agents sequentially, passing output to next agent"""
    results = []
    current_query = query
    for agent in agents:
        req = TaskRequest(agent=agent, query=current_query, user=user)
        result = await run_task(req)
        results.append(result.dict())
        current_query = result.answer
    return {"results": results}

@app.on_event("startup")
async def load_agent_keys():
    """Load agent API keys from environment"""
    for role in AGENT_ROLES:
        env_key = f"AGENT_{role.upper()}_KEY"
        AGENT_KEYS[role] = os.getenv(env_key, "")
    configured = sum(1 for v in AGENT_KEYS.values() if v)
    logger.info(f"Orchestrator v3 started. {configured}/{len(AGENT_ROLES)} agents configured.")
    logger.info("Using streaming mode to bypass Dify v1.13 Answer-Node bug.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

# === CONFIGURATION ENDPOINTS (for Monitoring-Agent) ===

@app.get("/config/agents")
async def get_agent_config():
    """Get complete agent model configuration (used by Monitoring-Agent)"""
    configured_agents = {k: v for k, v in AGENT_KEYS.items() if v}
    config = {}
    for agent in configured_agents:
        model_info = AGENT_MODEL_CONFIG.get(agent, {"model": "unknown", "tier": "unknown", "temperature": 0.5, "provider": "unknown"})
        config[agent] = {
            "model": model_info["model"],
            "tier": model_info["tier"],
            "temperature": model_info["temperature"],
            "provider": model_info["provider"],
            "api_key_configured": bool(AGENT_KEYS.get(agent)),
        }
    return {
        "agents": config,
        "embedding": EMBEDDING_CONFIG,
        "strategy": "3-tier-per-agent",
        "version": "3.0.0",
        "tier_summary": {
            "tier1-code": {"model": "minimax-m2.5", "agents": [a for a, c in AGENT_MODEL_CONFIG.items() if c["tier"] == "tier1-code"]},
            "tier2-multilingual": {"model": "glm-4.7", "agents": [a for a, c in AGENT_MODEL_CONFIG.items() if c["tier"] == "tier2-multilingual"]},
            "tier3-guenstig": {"model": "deepseek-v3.2", "agents": [a for a, c in AGENT_MODEL_CONFIG.items() if c["tier"] == "tier3-guenstig"]},
        }
    }

@app.get("/config/agent/{agent_name}")
async def get_single_agent_config(agent_name: str):
    """Get config for a single agent"""
    if agent_name not in AGENT_MODEL_CONFIG:
        raise HTTPException(404, f"Agent {agent_name} not found. Available: {list(AGENT_MODEL_CONFIG.keys())}")
    config = AGENT_MODEL_CONFIG[agent_name]
    return {
        "agent": agent_name,
        "model": config["model"],
        "tier": config["tier"],
        "temperature": config["temperature"],
        "provider": config["provider"],
        "api_key_configured": bool(AGENT_KEYS.get(agent_name)),
    }

# === AUTO-ROUTING ENDPOINT ===
ROUTING_KEYWORDS = {
    "architect": ["architektur", "design", "system", "struktur", "aufbau", "komponente", "pattern"],
    "coder": ["code", "programmier", "implementier", "funktion", "klasse", "script", "python", "javascript"],
    "tester": ["test", "qualität", "qa", "bug", "fehler", "assertion", "unittest"],
    "reviewer": ["review", "prüf", "bewert", "best practice", "code review", "feedback"],
    "devops": ["deploy", "docker", "ci/cd", "pipeline", "infrastruktur", "server", "kubernetes"],
    "docs": ["dokumentation", "readme", "api-doc", "beschreib", "erkläre", "anleitung"],
    "security": ["sicherheit", "security", "audit", "schwachstelle", "vulnerability", "firewall"],
    "planner": ["plan", "sprint", "aufgabe", "task", "zeitplan", "priorität", "roadmap"],
    "debug": ["debug", "fehlersuche", "traceback", "exception", "crash", "log", "diagnose"],
    "worker": ["erledige", "mach", "ausführ", "allgemein", "hilf", "unterstütz"]
}

def route_query(query: str) -> str:
    """Route a query to the best agent based on keyword matching"""
    query_lower = query.lower()
    scores = {}
    for agent, keywords in ROUTING_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[agent] = score
    if scores:
        return max(scores, key=scores.get)
    return "worker"  # Default fallback

class RouteRequest(BaseModel):
    query: str
    user: str = "orchestrator"

class RouteResponse(BaseModel):
    agent: str
    answer: str
    conversation_id: str
    message_id: str
    routing_reason: str
    sources: Optional[Dict[str, Any]] = None

@app.post("/route", response_model=RouteResponse)
async def auto_route(req: RouteRequest):
    """Auto-route a query to the best matching agent"""
    best_agent = route_query(req.query)
    task_req = TaskRequest(agent=best_agent, query=req.query, user=req.user)
    result = await run_task(task_req)
    return RouteResponse(
        agent=best_agent,
        answer=result.answer,
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        routing_reason=f"Keyword-match → {best_agent}",
        sources=result.sources
    )
# === 17 HOOK-WORKFLOW ENDPOINTS ===
# Each hook maps to a specific agent with a pre-configured prompt template

HOOK_CONFIGS = {
    "save": {"agent": "worker", "template": "Speichere folgende Information in deinem Memory: {query}"},
    "recall": {"agent": "worker", "template": "Rufe aus deinem Memory ab: {query}"},
    "status": {"agent": "planner", "template": "Gib einen aktuellen Statusbericht: {query}"},
    "learn": {"agent": "worker", "template": "Lerne aus folgendem Feedback und speichere es: {query}"},
    "format": {"agent": "docs", "template": "Formatiere folgenden Text professionell: {query}"},
    "review": {"agent": "reviewer", "template": "Reviewe folgenden Code oder Text: {query}"},
    "test": {"agent": "tester", "template": "Erstelle Testfaelle fuer: {query}"},
    "deploy": {"agent": "devops", "template": "Erstelle einen Deployment-Plan fuer: {query}"},
    "explain": {"agent": "docs", "template": "Erklaere verstaendlich: {query}"},
    "refactor": {"agent": "coder", "template": "Refactore folgenden Code: {query}"},
    "doc": {"agent": "docs", "template": "Erstelle Dokumentation fuer: {query}"},
    "plan": {"agent": "planner", "template": "Erstelle einen Plan fuer: {query}"},
    "debug": {"agent": "debug", "template": "Analysiere folgenden Fehler: {query}"},
    "optimize": {"agent": "coder", "template": "Optimiere folgenden Code: {query}"},
    "security": {"agent": "security", "template": "Fuehre eine Sicherheitsanalyse durch: {query}"},
    "summarize": {"agent": "docs", "template": "Fasse zusammen: {query}"},
    "fix": {"agent": "debug", "template": "Finde und behebe den Fehler in: {query}"},
}

class HookRequest(BaseModel):
    query: str
    user: str = "orchestrator"

class HookResponse(BaseModel):
    hook: str
    agent: str
    answer: str
    conversation_id: str
    message_id: str

@app.get("/hooks")
async def list_hooks():
    """List all available hook endpoints"""
    return {
        "hooks": list(HOOK_CONFIGS.keys()),
        "count": len(HOOK_CONFIGS),
        "usage": "POST /{hook_name} with {query: 'your question'}"
    }

# Create endpoints dynamically for each hook
for hook_name, config in HOOK_CONFIGS.items():
    def make_handler(h_name, h_config):
        async def handler(req: HookRequest):
            query = h_config["template"].format(query=req.query)
            task_req = TaskRequest(agent=h_config["agent"], query=query, user=req.user)
            result = await run_task(task_req)
            return HookResponse(
                hook=h_name,
                agent=h_config["agent"],
                answer=result.answer,
                conversation_id=result.conversation_id,
                message_id=result.message_id
            )
        handler.__name__ = f"hook_{h_name}"
        return handler
    
    app.post(f"/{hook_name}", response_model=HookResponse)(make_handler(hook_name, config))
# === SELF-LEARNING PIPELINE ===

class FeedbackRequest(BaseModel):
    conversation_id: str
    agent: str
    rating: str  # "positive" or "negative"
    feedback: Optional[str] = None
    query: Optional[str] = None

class FeedbackResponse(BaseModel):
    status: str
    action: str
    memory_saved: bool

@app.post("/feedback", response_model=FeedbackResponse)
async def process_feedback(req: FeedbackRequest):
    """Process user feedback for self-learning"""
    import httpx
    
    MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")
    MEM0_ORG_ID = os.getenv("MEM0_ORG_ID", "")
    MEM0_PROJECT_ID = os.getenv("MEM0_PROJECT_ID", "")

    if False:  # Local Mem0 braucht keine Keys
        return FeedbackResponse(status="error", action="missing_env", memory_saved=False)

    if req.rating == "positive":
        memory_text = f"[POSITIVE FEEDBACK] Agent {req.agent}: Antwort war hilfreich."
        if req.feedback:
            memory_text += f" Grund: {req.feedback}"
        namespace = f"cct-{req.agent}"
        action = "positive_reinforcement"
    else:
        memory_text = f"[ERROR LEARNING] Agent {req.agent}: Antwort war NICHT hilfreich."
        if req.feedback:
            memory_text += f" Fehler: {req.feedback}"
        memory_text += " NICHT WIEDERHOLEN."
        namespace = "cct-errors"
        action = "error_learning"
    
    # Save to Mem0
    memory_saved = False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://localhost:8002/v1/memories/",
                headers={
                    # Auth nicht noetig fuer lokales Mem0
                    "Content-Type": "application/json"
                },
                json={
                    "messages": [{"role": "user", "content": memory_text}],
                    "user_id": namespace,
                    # org_id nicht noetig fuer lokales Mem0
                    # project_id nicht noetig fuer lokales Mem0
                }
            )
            if resp.status_code in (200, 201):
                memory_saved = True
                logger.info(f"Self-learning: {action} for {req.agent}")
    except Exception as e:
        logger.error(f"Self-learning memory save failed: {e}")
    
    return FeedbackResponse(
        status="processed",
        action=action,
        memory_saved=memory_saved
    )

@app.get("/learning/stats")
async def learning_stats():
    """Get self-learning statistics"""
    import httpx
    
    MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")

    stats = {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "http://localhost:8002/v1/memories/",
                # Lokales Mem0 braucht keine Auth
                params={"user_id": "cct-errors"}
            )
            if resp.status_code == 200:
                errors = resp.json()
                stats["error_memories"] = len(errors) if isinstance(errors, list) else 0
    except:
        stats["error_memories"] = "unavailable"
    
    stats["agents"] = list(AGENT_KEYS.keys())
    stats["pipeline"] = "active"
    stats["endpoints"] = ["/feedback", "/learning/stats"]
    return stats


# === CORE MEMORY / SYSTEM-VARIABLEN ===
import sqlite3
from datetime import datetime

CORE_MEMORY_DB = os.getenv("CORE_MEMORY_DB", "/opt/cloud-code/core_memory.db")

def _init_core_memory():
    conn = sqlite3.connect(CORE_MEMORY_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS system_vars (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        category TEXT DEFAULT 'system',
        updated_at TEXT DEFAULT (datetime('now')),
        updated_by TEXT DEFAULT 'system'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(agent, key)
    )""")
    # Seed default system vars if empty
    cursor = conn.execute("SELECT COUNT(*) FROM system_vars")
    if cursor.fetchone()[0] == 0:
        defaults = [
            ("project_name", "Cloud Code Team", "project"),
            ("project_version", "3.0.0", "project"),
            ("llm_model", "3-tier-open-source", "config"),
            ("embedding_model", "qwen3-embedding-8b", "config"),
            ("anti_hallucination", "active", "config"),
            ("max_confidence_without_source", "0.6", "rules"),
            ("require_sources", "true", "rules"),
            ("language", "de", "config"),
        ]
        conn.executemany(
            "INSERT INTO system_vars (key, value, category) VALUES (?, ?, ?)",
            defaults
        )
    conn.commit()
    conn.close()

class SystemVarRequest(BaseModel):
    key: str
    value: str
    category: Optional[str] = "system"

class AgentMemoryRequest(BaseModel):
    agent: str
    key: str
    value: str

@app.get("/memory/system")
async def get_system_vars(category: Optional[str] = None):
    """Get all system variables, optionally filtered by category"""
    conn = sqlite3.connect(CORE_MEMORY_DB)
    if category:
        rows = conn.execute(
            "SELECT key, value, category, updated_at FROM system_vars WHERE category = ?",
            (category,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT key, value, category, updated_at FROM system_vars"
        ).fetchall()
    conn.close()
    return {"vars": {r[0]: {"value": r[1], "category": r[2], "updated_at": r[3]} for r in rows}}

@app.get("/memory/system/{key}")
async def get_system_var(key: str):
    """Get a single system variable"""
    conn = sqlite3.connect(CORE_MEMORY_DB)
    row = conn.execute(
        "SELECT value, category, updated_at FROM system_vars WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"System variable '{key}' not found")
    return {"key": key, "value": row[0], "category": row[1], "updated_at": row[2]}

@app.put("/memory/system")
async def set_system_var(req: SystemVarRequest):
    """Set or update a system variable"""
    conn = sqlite3.connect(CORE_MEMORY_DB)
    conn.execute(
        "INSERT OR REPLACE INTO system_vars (key, value, category, updated_at) VALUES (?, ?, ?, datetime('now'))",
        (req.key, req.value, req.category)
    )
    conn.commit()
    conn.close()
    logger.info(f"Core Memory: set {req.key} = {req.value}")
    return {"status": "ok", "key": req.key, "value": req.value}

@app.delete("/memory/system/{key}")
async def delete_system_var(key: str):
    """Delete a system variable"""
    conn = sqlite3.connect(CORE_MEMORY_DB)
    conn.execute("DELETE FROM system_vars WHERE key = ?", (key,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "key": key}

@app.get("/memory/agent/{agent}")
async def get_agent_memory(agent: str):
    """Get all memory entries for a specific agent"""
    conn = sqlite3.connect(CORE_MEMORY_DB)
    rows = conn.execute(
        "SELECT key, value, created_at FROM agent_memory WHERE agent = ?", (agent,)
    ).fetchall()
    conn.close()
    return {"agent": agent, "memory": {r[0]: {"value": r[1], "created_at": r[2]} for r in rows}}

@app.put("/memory/agent")
async def set_agent_memory(req: AgentMemoryRequest):
    """Set or update an agent-specific memory entry"""
    conn = sqlite3.connect(CORE_MEMORY_DB)
    conn.execute(
        "INSERT OR REPLACE INTO agent_memory (agent, key, value, created_at) VALUES (?, ?, ?, datetime('now'))",
        (req.agent, req.key, req.value)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "agent": req.agent, "key": req.key}

@app.get("/memory/context")
async def get_full_context():
    """Get combined system vars + all agent memories (for injection into prompts)"""
    conn = sqlite3.connect(CORE_MEMORY_DB)
    sys_vars = conn.execute("SELECT key, value, category FROM system_vars").fetchall()
    agent_mem = conn.execute("SELECT agent, key, value FROM agent_memory").fetchall()
    conn.close()
    context = {
        "system": {r[0]: r[1] for r in sys_vars},
        "agents": {}
    }
    for agent, key, value in agent_mem:
        if agent not in context["agents"]:
            context["agents"][agent] = {}
        context["agents"][agent][key] = value
    return context

# Init core memory on startup
_original_load_keys = load_agent_keys
async def _load_keys_and_memory():
    await _original_load_keys()
    _init_core_memory()
    logger.info("Core Memory initialized.")

app.router.on_startup.clear()
app.add_event_handler("startup", _load_keys_and_memory)


# === HIPPORAG INTEGRATION ===
HIPPORAG_URL = os.getenv("HIPPORAG_URL", "http://127.0.0.1:8001")

async def _query_hipporag(query: str, hop_depth: int = 3, limit: int = 5) -> str:
    """Query HippoRAG for knowledge graph context"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{HIPPORAG_URL}/knowledge/query",
                json={"query": query, "hop_depth": hop_depth, "limit": limit}
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    return ""
                # Format KG context for LLM
                kg_lines = []
                for r in results:
                    for rel in r.get("relationships", []):
                        kg_lines.append(f"  {rel.get('from','')} --[{rel.get('type','')}]--> {rel.get('to','')}")
                if kg_lines:
                    return "Knowledge-Graph Kontext:\n" + "\n".join(kg_lines[:20])
            return ""
    except Exception as e:
        logger.warning(f"HippoRAG query failed: {e}")
        return ""

# Patch _call_agent_streaming to enrich with HippoRAG
_original_call_agent = _call_agent_streaming

async def _call_agent_with_full_rag(api_key, query, user,
                                     conversation_id="",
                                     inputs=None,
                                     agent="worker"):
    """Enhanced agent call with FULL RAG+Memory middleware + model config for ALL agents."""
    # Inject model config into inputs for Dify workflow awareness
    model_config = AGENT_MODEL_CONFIG.get(agent, {})
    if inputs is None:
        inputs = {}
    inputs["_agent_model"] = model_config.get("model", "unknown")
    inputs["_agent_tier"] = model_config.get("tier", "unknown")
    inputs["_agent_temperature"] = str(model_config.get("temperature", 0.5))
    enriched_query = await enrich_for_agent(
        query=query,
        user_id=user,
        agent=agent,
        include_anti_hallucination=True,
    )
    auto_learn(user_id=user, user_message=query)
    logger.info(f"RAG Middleware: enriched {len(query)} -> {len(enriched_query)} chars for {agent}")
    result = await _original_call_agent(api_key, enriched_query, user, conversation_id, inputs, agent)

    # === SELF-LEARNING: Agent-Antwort automatisch in Memory speichern ===
    try:
        answer = result.get("answer", "")
        if answer and len(answer) > 20:
            # Kompakte Zusammenfassung fuer Memory
            summary = f"Agent {agent} wurde gefragt: {query[:200]}. Antwort-Laenge: {len(answer)} Zeichen."
            from rag_middleware import save_user_memory
            save_user_memory(f"cct-{agent}", summary)
            logger.info(f"Self-Learning: saved interaction for cct-{agent}")
    except Exception as sl_err:
        logger.warning(f"Self-Learning failed for {agent}: {sl_err}")

    return result

_call_agent_streaming = _call_agent_with_full_rag

# Add HippoRAG-specific endpoints
@app.get("/hipporag/health")
async def hipporag_health():
    """Check HippoRAG connectivity"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{HIPPORAG_URL}/health")
            return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/hipporag/query")
async def hipporag_query(query: str, hop_depth: int = 3, limit: int = 5):
    """Proxy HippoRAG query through orchestrator"""
    result = await _query_hipporag(query, hop_depth, limit)
    return {"kg_context": result, "query": query}


@app.get("/rag/health")
async def rag_health_endpoint():
    """Check all RAG + Memory components"""
    return await rag_health()


# ══════════════════════════════════════════════════════════════
# WORKFLOW MODULE LOADER
# Laedt alle Workflow-Module aus orchestrator/workflows/
# Jedes Modul exportiert einen FastAPI APIRouter
# ══════════════════════════════════════════════════════════════

import importlib
import sys
import os as _os

# Helper: Agent aufrufen (wird in Workflow-Module injiziert)
async def _orchestrator_call_agent(agent: str, query: str, user: str) -> Dict:
    """Wrapper fuer Workflow-Module: ruft einen Agent ueber den Orchestrator auf."""
    api_key = AGENT_KEYS.get(agent)
    if not api_key:
        return {"answer": f"[ERROR] Agent {agent} nicht konfiguriert", "conversation_id": "", "message_id": "", "sources": None}
    return await _call_agent_streaming(api_key=api_key, query=query, user=user, agent=agent)

# Workflow-Module laden
_workflow_dir = _os.path.join(_os.path.dirname(__file__), "workflows")
if _os.path.isdir(_workflow_dir):
    sys.path.insert(0, _os.path.dirname(__file__))
    _loaded = []
    for _fname in sorted(_os.listdir(_workflow_dir)):
        if _fname.endswith(".py") and _fname != "__init__.py":
            _mod_name = _fname[:-3]
            try:
                _mod = importlib.import_module(f"workflows.{_mod_name}")
                # Injiziere Agent-Caller
                if hasattr(_mod, "set_agent_caller"):
                    _mod.set_agent_caller(_orchestrator_call_agent)
                # Registriere Router
                if hasattr(_mod, "router"):
                    app.include_router(_mod.router)
                    _loaded.append(_mod_name)
                    logger.info(f"Workflow geladen: {_mod_name}")
            except Exception as _e:
                logger.error(f"Workflow {_mod_name} konnte nicht geladen werden: {_e}")
    logger.info(f"Workflow-Module: {len(_loaded)} geladen ({', '.join(_loaded)})")


@app.get("/memories/shared")
async def shared_memories(query: str = "", limit: int = 10):
    """Read memories across ALL agents (shared namespace) — parallel fetch"""
    import httpx
    import asyncio
    agent_ids = [f"cct-{a}" for a in AGENT_KEYS.keys()]

    async def fetch_agent(client, uid):
        try:
            if query:
                resp = await client.post(
                    "http://localhost:8002/v1/memories/search/",
                    json={"query": query, "user_id": uid, "limit": 3}
                )
            else:
                resp = await client.get(
                    "http://localhost:8002/v1/memories/",
                    params={"user_id": uid}
                )
            if resp.status_code == 200:
                data = resp.json()
                entries = data.get("results", data) if isinstance(data, dict) else data
                if isinstance(entries, list):
                    for e in entries:
                        if isinstance(e, dict):
                            e["_source_agent"] = uid
                    return entries
        except Exception:
            pass
        return []

    async with httpx.AsyncClient(timeout=60.0) as client:
        results = await asyncio.gather(*[fetch_agent(client, uid) for uid in agent_ids])

    all_memories = []
    for entries in results:
        all_memories.extend(entries)
    all_memories = all_memories[:limit]
    return {"memories": all_memories, "total": len(all_memories), "agents_queried": len(agent_ids)}


@app.get("/memories/{agent}")
async def agent_memories(agent: str, query: str = ""):
    """Read memories for a specific agent"""
    import httpx
    user_id = f"cct-{agent}"
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            if query:
                resp = await client.post(
                    "http://localhost:8002/v1/memories/search/",
                    json={"query": query, "user_id": user_id, "limit": 10}
                )
            else:
                resp = await client.get(
                    "http://localhost:8002/v1/memories/",
                    params={"user_id": user_id}
                )
            if resp.status_code == 200:
                data = resp.json()
                return {"agent": agent, "user_id": user_id, "memories": data}
        except Exception as e:
            return {"agent": agent, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# DOCTOR AGENT — SELF-HEALING INTEGRATION
# Wraps alle Agent-Calls mit automatischem Retry + Healing
# ══════════════════════════════════════════════════════════════

try:
    from workflows.doctor_agent import (
        state as doctor_state,
        self_healing_call,
        doctor_startup,
    )

    # Self-Healing um den Agent-Call wrappen
    _pre_healing_call = _call_agent_streaming

    async def _self_healing_agent_call(api_key, query, user,
                                        conversation_id="",
                                        inputs=None,
                                        agent="worker"):
        """Agent-Call mit automatischem Self-Healing bei Fehlern."""
        return await self_healing_call(
            original_fn=_pre_healing_call,
            api_key=api_key,
            query=query,
            user=user,
            conversation_id=conversation_id,
            inputs=inputs,
            agent=agent,
            max_retries=2,
        )

    _call_agent_streaming = _self_healing_agent_call
    logger.info("Self-Healing aktiviert fuer alle Agent-Calls")

    # Doctor Startup Hook (Watchdog starten)
    _prev_startup_fn = None
    if app.router.on_startup:
        _prev_startup_fn = app.router.on_startup[-1]

    async def _startup_with_doctor():
        if _prev_startup_fn:
            await _prev_startup_fn()
        await doctor_startup()

    app.router.on_startup.clear()
    app.add_event_handler("startup", _startup_with_doctor)
    logger.info("Doctor Agent Startup-Hook registriert")

except ImportError as _ie:
    logger.warning("Doctor Agent nicht verfuegbar: %s", _ie)
except Exception as _de:
    logger.error("Doctor Agent Fehler: %s", _de)
