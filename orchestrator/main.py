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
from dotenv import load_dotenv
load_dotenv()  # Load .env file

# ──────── Langfuse LLM Tracing (v4 API) ────────
try:
    from langfuse import Langfuse
    import uuid as _uuid
    import datetime as _dt
    _langfuse = Langfuse()
    _langfuse_ok = _langfuse.auth_check()
    if _langfuse_ok:
        import atexit
        atexit.register(_langfuse.flush)
except Exception as _lf_err:
    _langfuse = None
    _langfuse_ok = False

def _lf_trace(name, agent="", user_id="orchestrator", inp=None, out=None, model="", metadata=None):
    """Send trace + generation to Langfuse via v4 ingestion API."""
    if not _langfuse_ok:
        return
    try:
        trace_id = str(_uuid.uuid4())
        obs_id = str(_uuid.uuid4())
        now = _dt.datetime.utcnow().isoformat() + "Z"
        batch = [
            {
                "id": str(_uuid.uuid4()),
                "type": "trace-create",
                "timestamp": now,
                "body": {
                    "id": trace_id,
                    "name": name,
                    "userId": user_id,
                    "metadata": metadata or {"agent": agent},
                    "input": inp if isinstance(inp, dict) else {"query": str(inp or "")[:500]},
                    "output": out if isinstance(out, dict) else {"answer": str(out or "")[:500]},
                }
            },
            {
                "id": str(_uuid.uuid4()),
                "type": "generation-create",
                "timestamp": now,
                "body": {
                    "id": obs_id,
                    "traceId": trace_id,
                    "name": f"llm-{agent or name}",
                    "model": model,
                    "input": inp if isinstance(inp, dict) else {"query": str(inp or "")[:500]},
                    "output": out if isinstance(out, dict) else {"answer": str(out or "")[:500]},
                    "metadata": metadata or {"agent": agent},
                }
            }
        ]
        _langfuse.api.ingestion.batch(batch=batch)
    except Exception as e:
        logger.warning(f"Langfuse trace failed: {e}")

from rag_middleware import enrich_for_agent, auto_learn, health_check as rag_health

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")
# ──────── AUDIT-LOG: Telegram Error Alerts (Phase 0) ────────
import asyncio as _audit_asyncio

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8718856271:AAHKkOplIj0bgZ3sGa15cLfEbzoSMzpHj4o")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8212488253")

async def _send_telegram_alert(message: str):
    """Send error/audit alert to Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message[:4000],
            "parse_mode": "HTML",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as tg_err:
        logger.warning(f"Telegram alert failed: {tg_err}")

def _audit_log(level: str, agent: str, message: str, query: str = ""):
    """Log an audit event and send critical errors to Telegram."""
    log_entry = f"[AUDIT-{level}] Agent={agent} | {message}"
    if level == "ERROR":
        logger.error(log_entry)
        # Send async Telegram alert for errors
        tg_msg = (
            f"<b>FEHLER im Cloud Code Team</b>\n"
            f"<b>Agent:</b> {agent}\n"
            f"<b>Fehler:</b> {message[:500]}\n"
            f"<b>Query:</b> {query[:200]}"
        )
        try:
            loop = _audit_asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_send_telegram_alert(tg_msg))
            else:
                loop.run_until_complete(_send_telegram_alert(tg_msg))
        except RuntimeError:
            _audit_asyncio.run(_send_telegram_alert(tg_msg))
    elif level == "WARN":
        logger.warning(log_entry)
    else:
        logger.info(log_entry)



app = FastAPI(title="Cloud Code Team Orchestrator", version="3.0.0")

# Config
DIFY_API_URL = os.getenv("DIFY_API_URL", "https://difyv2.activi.io/v1")
AGENT_KEYS: Dict[str, str] = {}

# Agent roles
AGENT_ROLES = [
    "architect", "coder", "tester", "reviewer", "devops",
    "docs", "security", "planner", "debug", "worker", "coach"
]


# === 4-TIER MODEL CONFIGURATION (optimiert nach Benchmark 2026-03-16) ===
# Tier 1 (Code):      Qwen3-Coder-Next  - schnellstes Code-Modell (3s vs 15s MiniMax)
# Tier 2 (Reasoning): DeepSeek-V3.2     - 671B MoE, tiefstes Reasoning/Thinking
# Tier 3 (General):   MiniMax-M2.5      - schnell + solide fuer allgemeine Aufgaben
# Tier 4 (Memory):    MiniMax-M2.5      - schnellste Antwort fuer einfache Memory-Ops
#
# Fallback: OpenRouter (wenn Ollama Cloud ausfaellt)
OLLAMA_CLOUD_URL = os.getenv("OLLAMA_CLOUD_URL", "http://localhost:11434")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Mapping: Ollama Cloud Model -> OpenRouter Fallback Model
FALLBACK_MODELS = {
    "qwen3-coder-next":  "qwen/qwen-2.5-coder-32b-instruct",
    "deepseek-v3.2":     "deepseek/deepseek-chat",
    "minimax-m2.5":      "deepseek/deepseek-chat",
    "glm-4.7":           "deepseek/deepseek-chat",
}

AGENT_MODEL_CONFIG = {
    # Tier 1: Code-Agents -> Qwen3-Coder-Next (3x schneller, spezialisiert auf Code)
    "coder":      {"model": "qwen3-coder-next",  "tier": "tier1-code",      "temperature": 0.2, "provider": "ollama-cloud"},
    "devops":     {"model": "qwen3-coder-next",  "tier": "tier1-code",      "temperature": 0.3, "provider": "ollama-cloud"},
    "tester":     {"model": "qwen3-coder-next",  "tier": "tier1-code",      "temperature": 0.2, "provider": "ollama-cloud"},
    # Tier 2: Reasoning-Agents -> DeepSeek-V3.2 (671B, tiefes Thinking)
    "architect":  {"model": "deepseek-v3.2",     "tier": "tier2-reasoning", "temperature": 0.3, "provider": "ollama-cloud"},
    "security":   {"model": "deepseek-v3.2",     "tier": "tier2-reasoning", "temperature": 0.2, "provider": "ollama-cloud"},
    "reviewer":   {"model": "deepseek-v3.2",     "tier": "tier2-reasoning", "temperature": 0.3, "provider": "ollama-cloud"},
    "debug":      {"model": "deepseek-v3.2",     "tier": "tier2-reasoning", "temperature": 0.3, "provider": "ollama-cloud"},
    # Tier 3: General-Agents -> MiniMax-M2.5 (schnell + solide)
    "coach":      {"model": "minimax-m2.5",      "tier": "tier3-general",   "temperature": 0.5, "provider": "ollama-cloud"},
    "planner":    {"model": "minimax-m2.5",      "tier": "tier3-general",   "temperature": 0.4, "provider": "ollama-cloud"},
    "docs":       {"model": "minimax-m2.5",      "tier": "tier3-general",   "temperature": 0.4, "provider": "ollama-cloud"},
    "worker":     {"model": "minimax-m2.5",      "tier": "tier3-general",   "temperature": 0.5, "provider": "ollama-cloud"},
    # Tier 4: Memory -> MiniMax-M2.5 (schnellste Antwort, einfache Aufgabe)
    "memory":     {"model": "minimax-m2.5",      "tier": "tier4-memory",    "temperature": 0.1, "provider": "ollama-cloud"},
}

EMBEDDING_CONFIG = {
    "model": "qwen3-embedding-8b",
    "provider": "ollama-local",
    "dimensions": 4096,
}


def _parse_mem0_response(data):
    """Parse Mem0 API response handling double-nested results."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        inner = data.get("results", data)
        if isinstance(inner, dict):
            inner = inner.get("results", [])
        if isinstance(inner, list):
            return inner
    return []

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


# ---- DIRECT LLM CALL: Ollama Cloud + OpenRouter Fallback ----
async def _call_llm_direct(prompt: str, agent: str = "worker", system: str = "") -> str:
    """Call LLM directly. Ollama Cloud first, OpenRouter fallback."""
    config = AGENT_MODEL_CONFIG.get(agent, AGENT_MODEL_CONFIG["worker"])
    model = config["model"]
    temperature = config["temperature"]

    # --- Attempt 1: Ollama Cloud ---
    try:
        payload = {
            "model": f"{model}:cloud",
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature}
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{OLLAMA_CLOUD_URL}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("response", "") or data.get("thinking", "")
            if answer.strip():
                logger.info(f"[LLM-DIRECT] Ollama OK | agent={agent} model={model}:cloud")
                # Langfuse trace (v4)
                _lf_trace(f"llm-direct-{agent}", agent=agent, inp=prompt[:500], out=answer[:500], model=f"{model}:cloud", metadata={"agent": agent, "provider": "ollama-cloud", "eval_count": data.get("eval_count", 0)})
                return answer.strip()
            logger.warning(f"[LLM-DIRECT] Ollama empty response for {agent}")
    except Exception as e:
        logger.warning(f"[LLM-DIRECT] Ollama failed for {agent}: {e}")

    # --- Attempt 2: OpenRouter Fallback ---
    if not OPENROUTER_API_KEY:
        logger.error(f"[LLM-DIRECT] No OpenRouter API key - fallback unavailable")
        return ""
    fallback_model = FALLBACK_MODELS.get(model, "deepseek/deepseek-chat")
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://cloud-code-team.activi.io",
                    "X-Title": "Cloud Code Team",
                },
                json={"model": fallback_model, "messages": messages, "temperature": temperature},
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if answer.strip():
                logger.info(f"[LLM-DIRECT] OpenRouter OK | agent={agent} fallback={fallback_model}")
                return answer.strip()
    except Exception as e:
        logger.error(f"[LLM-DIRECT] OpenRouter also failed: {e}")
        _audit_log("ERROR", agent, f"Both Ollama+OpenRouter failed: {e}", prompt[:200])
    return ""


async def _check_ollama_health() -> dict:
    """Check Ollama Cloud connectivity."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OLLAMA_CLOUD_URL}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            cloud_models = [m for m in models if ":cloud" in m]
            return {"status": "ok", "cloud_models": cloud_models, "total": len(models)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


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
        # Langfuse trace (v4)
        config = AGENT_MODEL_CONFIG.get(req.agent, {})
        _lf_trace(f"dify-{req.agent}", agent=req.agent, user_id=req.user, inp=req.query[:500], out=result["answer"][:500] if result.get("answer") else "", model=config.get("model","unknown"), metadata={"agent": req.agent, "tier": config.get("tier",""), "provider": "dify", "kb_hits": result.get("sources",{}).get("kb_hits",0) if isinstance(result.get("sources"),dict) else 0})
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


# ---- LLM DIRECT ENDPOINTS ----
class DirectLLMRequest(BaseModel):
    prompt: str
    agent: str = "worker"
    system: str = ""

@app.post("/llm/direct")
async def llm_direct(req: DirectLLMRequest):
    """Call LLM directly (bypasses Dify). Ollama Cloud + OpenRouter fallback."""
    answer = await _call_llm_direct(req.prompt, req.agent, req.system)
    if not answer:
        raise HTTPException(503, "Both Ollama Cloud and OpenRouter failed")
    config = AGENT_MODEL_CONFIG.get(req.agent, AGENT_MODEL_CONFIG["worker"])
    return {"agent": req.agent, "model": config["model"], "provider": "ollama-cloud+openrouter", "answer": answer}

@app.get("/llm/health")
async def llm_health():
    """Check LLM provider health."""
    ollama = await _check_ollama_health()
    return {
        "ollama": ollama,
        "openrouter_configured": bool(OPENROUTER_API_KEY),
        "fallback_models": FALLBACK_MODELS,
        "tiers": {k: {"model": v["model"], "tier": v["tier"]} for k, v in AGENT_MODEL_CONFIG.items()},
    }


@app.get("/langfuse/health")
async def langfuse_health():
    """Check Langfuse tracing status."""
    return {
        "enabled": _langfuse_ok,
        "base_url": os.getenv("LANGFUSE_BASE_URL", "not set"),
        "public_key_set": bool(os.getenv("LANGFUSE_PUBLIC_KEY", "")),
        "secret_key_set": bool(os.getenv("LANGFUSE_SECRET_KEY", "")),
    }

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
            "tier1-code": {"model": "qwen3-coder-next", "agents": [a for a, c in AGENT_MODEL_CONFIG.items() if c["tier"] == "tier1-code"]},
            "tier2-reasoning": {"model": "deepseek-v3.2", "agents": [a for a, c in AGENT_MODEL_CONFIG.items() if c["tier"] == "tier2-reasoning"]},
            "tier3-general": {"model": "minimax-m2.5", "agents": [a for a, c in AGENT_MODEL_CONFIG.items() if c["tier"] == "tier3-general"]},
            "tier4-memory": {"model": "minimax-m2.5", "agents": [a for a, c in AGENT_MODEL_CONFIG.items() if c["tier"] == "tier4-memory"]},
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
    """Enhanced agent call with FULL RAG+Memory middleware + Error-Handling + Audit-Log.
    Phase 0: Error-Handling (#1), Audit-Log (#2), Memory-Save guard (#3).
    """
    # Inject model config into inputs for Dify workflow awareness
    model_config = AGENT_MODEL_CONFIG.get(agent, {})
    if inputs is None:
        inputs = {}
    inputs["_agent_model"] = model_config.get("model", "unknown")
    inputs["_agent_tier"] = model_config.get("tier", "unknown")
    inputs["_agent_temperature"] = str(model_config.get("temperature", 0.5))

    # Enrich query with RAG context
    enriched_query = await enrich_for_agent(
        query=query,
        user_id=user,
        agent=agent,
        include_anti_hallucination=True,
    )
    logger.info(f"RAG Middleware: enriched {len(query)} -> {len(enriched_query)} chars for {agent}")

    # ── PHASE 0 (#1): ERROR-HANDLING mit Retry ──
    MAX_RETRIES = 2
    last_error = None
    result = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = await _original_call_agent(api_key, enriched_query, user, conversation_id, inputs, agent)
            answer = result.get("answer", "").strip()

            # Check: LLM-Antwort leer oder zu kurz?
            if not answer or len(answer) < 5:
                _audit_log("WARN", agent, f"Leere LLM-Antwort (Versuch {attempt}/{MAX_RETRIES})", query[:200])
                if attempt < MAX_RETRIES:
                    logger.info(f"Retry {attempt}/{MAX_RETRIES} fuer Agent {agent} (leere Antwort)")
                    continue  # Retry
                else:
                    # Alle Retries erschoepft
                    _audit_log("ERROR", agent,
                        f"LLM-Antwort LEER nach {MAX_RETRIES} Versuchen. "
                        f"Modell: {model_config.get('model', 'unknown')}, "
                        f"Query-Laenge: {len(query)} chars",
                        query[:200])
                    result["answer"] = (
                        f"[FEHLER] Agent '{agent}' konnte keine Antwort generieren. "
                        f"Bitte versuche es erneut oder formuliere die Frage um."
                    )
                    result["_error"] = True
            else:
                # Erfolgreiche Antwort
                _audit_log("INFO", agent, f"Erfolgreiche Antwort ({len(answer)} chars)")
                break

        except Exception as call_err:
            last_error = call_err
            _audit_log("ERROR", agent,
                f"Exception bei Agent-Call (Versuch {attempt}/{MAX_RETRIES}): {str(call_err)[:300]}",
                query[:200])
            if attempt < MAX_RETRIES:
                logger.info(f"Retry {attempt}/{MAX_RETRIES} fuer Agent {agent} nach Exception")
                continue
            else:
                raise  # Re-raise nach letztem Versuch

    # ── PHASE 0 (#3): Memory-Save NUR bei erfolgreicher LLM-Antwort ──
    answer = result.get("answer", "").strip() if result else ""
    is_error = result.get("_error", False) if result else True

    if not is_error and answer and len(answer) > 20:
        # auto_learn: Fakten aus der User-Query extrahieren
        try:
            auto_learn(user_id=user, user_message=query)
        except Exception as al_err:
            logger.warning(f"auto_learn failed for {agent}: {al_err}")

        # Self-Learning: Agent-Antwort in EIGENEN Scope speichern (NICHT shared!)
        # Memory-Policy: Agents schreiben NUR in cct-{agent}, NIEMALS in cloud-code-team
        try:
            summary = f"Agent {agent} wurde gefragt: {query[:200]}. Antwort-Laenge: {len(answer)} Zeichen."
            from rag_middleware import save_user_memory
            save_user_memory(f"cct-{agent}", summary)
            logger.info(f"Self-Learning: saved to OWN scope cct-{agent}")
        except Exception as sl_err:
            logger.warning(f"Self-Learning failed for {agent}: {sl_err}")
    else:
        logger.info(f"Memory-Save UEBERSPRUNGEN fuer {agent} (Antwort leer oder Fehler)")

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







# ======================================================================
# MEMORY SEPARATION: OWN vs SHARED (TEAM) ENDPOINTS
# Policy: Agents READ own+shared, WRITE only own
# Shared writes only via explicit /memories/team POST
# ======================================================================

SHARED_MEMORY_USER_ID = "cloud-code-team"

@app.get("/memories/own/{agent}")
async def get_own_memories(agent: str, query: str = ""):
    import httpx
    user_id = f"cct-{agent}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            if query:
                resp = await client.post("http://localhost:8002/v1/memories/search/",
                    json={"query": query, "user_id": user_id, "limit": 10})
            else:
                resp = await client.get("http://localhost:8002/v1/memories/",
                    params={"user_id": user_id})
            if resp.status_code == 200:
                data = resp.json()
                entries = _parse_mem0_response(data)
                count = len(entries) if isinstance(entries, list) else 0
                return {"agent": agent, "scope": "OWN", "user_id": user_id, "count": count, "memories": entries}
        except Exception as e:
            return {"agent": agent, "scope": "OWN", "error": str(e)}

@app.get("/memories/team")
async def get_team_memories(query: str = "", limit: int = 20):
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            if query:
                resp = await client.post("http://localhost:8002/v1/memories/search/",
                    json={"query": query, "user_id": SHARED_MEMORY_USER_ID, "limit": limit})
            else:
                resp = await client.get("http://localhost:8002/v1/memories/",
                    params={"user_id": SHARED_MEMORY_USER_ID})
            if resp.status_code == 200:
                data = resp.json()
                entries = _parse_mem0_response(data)
                count = len(entries) if isinstance(entries, list) else 0
                return {"scope": "SHARED", "user_id": SHARED_MEMORY_USER_ID, "count": count, "memories": entries}
        except Exception as e:
            return {"scope": "SHARED", "error": str(e)}

class TeamMemoryRequest(BaseModel):
    content: str
    source_agent: str = "orchestrator"

@app.post("/memories/team")
async def save_team_memory(req: TeamMemoryRequest):
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post("http://localhost:8002/v1/memories/",
                json={"messages": [{"role": "user", "content": f"[Team-Fakt von {req.source_agent}] {req.content}"}],
                       "user_id": SHARED_MEMORY_USER_ID})
            if resp.status_code == 200:
                data = resp.json()
                count = len(data.get("results", []))
                logger.info(f"Team memory saved by {req.source_agent}: {count} entries")
                return {"status": "saved", "scope": "SHARED", "entries_created": count, "source": req.source_agent}
            else:
                return {"status": "error", "http_code": resp.status_code}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

@app.get("/memories/dual/{agent}")
async def get_dual_memories(agent: str, query: str = ""):
    import httpx
    import asyncio
    own_id = f"cct-{agent}"
    async def _fetch(client, uid, scope):
        try:
            if query:
                resp = await client.post("http://localhost:8002/v1/memories/search/",
                    json={"query": query, "user_id": uid, "limit": 5})
            else:
                resp = await client.get("http://localhost:8002/v1/memories/",
                    params={"user_id": uid})
            if resp.status_code == 200:
                data = resp.json()
                entries = _parse_mem0_response(data)
                if isinstance(entries, list):
                    for e in entries:
                        if isinstance(e, dict):
                            e["_scope"] = scope
                            e["_source_user_id"] = uid
                    return entries
        except Exception:
            pass
        return []
    async with httpx.AsyncClient(timeout=15.0) as client:
        own_entries, shared_entries = await asyncio.gather(
            _fetch(client, own_id, "OWN"), _fetch(client, SHARED_MEMORY_USER_ID, "SHARED"))
    return {
        "agent": agent,
        "own": {"user_id": own_id, "count": len(own_entries), "memories": own_entries},
        "shared": {"user_id": SHARED_MEMORY_USER_ID, "count": len(shared_entries), "memories": shared_entries},
        "total": len(own_entries) + len(shared_entries)
    }

@app.get("/memories/policy")
async def memory_policy():
    return {
        "policy": "OWN_PLUS_SHARED", "version": "1.0",
        "rules": {
            "read": "Each agent reads OWN (cct-{agent}) + SHARED (cloud-code-team) memories",
            "write": "Each agent writes ONLY to OWN (cct-{agent}) scope",
            "shared_write": "Only via POST /memories/team with source_agent attribution",
            "user_ids": {"shared": SHARED_MEMORY_USER_ID, "pattern": "cct-{agent_name}",
                "examples": ["cct-coder", "cct-worker", "cct-architect", "cct-reviewer", "cct-doctor"]}
        },
        "endpoints": {
            "GET /memories/own/{agent}": "Read agent private memories only",
            "GET /memories/team": "Read shared team memories",
            "POST /memories/team": "Write to shared team memory (controlled)",
            "GET /memories/dual/{agent}": "Read merged own+shared",
            "GET /memories/shared": "Legacy: read across ALL agent scopes",
            "GET /memories/policy": "This endpoint"
        }
    }



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
                entries = _parse_mem0_response(data)
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
    from cct_workflows.doctor_agent import (
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
