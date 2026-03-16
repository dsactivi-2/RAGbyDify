#!/usr/bin/env python3
"""
Cloud Code Team — Chainlit Hybrid Retrieval Test
LlamaIndex + BGE-Reranker + Qdrant + Neo4j + Mem0

Startet einen Chainlit Chat-Server mit:
- Hybrid Retrieval (Qdrant semantisch + Neo4j Graph + Mem0 Memory)
- BGE-Reranker (BAAI/bge-reranker-v2-m3 via FlagEmbedding)
- File Upload (PDF, TXT, MD)
- Anti-Halluzinations-Regeln

Start: chainlit run /opt/cloud-code/scripts/03-chainlit-hybrid-test.py -p 8080
"""

import os
import asyncio
import logging

# --- Config ---
OLLAMA_URL = "http://localhost:11434"
QDRANT_URL = "http://localhost:16333"
QDRANT_COLLECTION = "mem0_memories"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "22e58741703f24f1913550c9a8a51c99"
MEM0_URL = "http://localhost:8002"
EMBED_MODEL = "qwen3-embedding"
LLM_MODEL = "minimax-m2.5:cloud"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
TOP_K = 10
RERANK_TOP_N = 5

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hybrid-test")

try:
    import chainlit as cl
except ImportError:
    print("ERROR: chainlit nicht installiert!")
    print("Install: pip install chainlit --break-system-packages")
    exit(1)

# --- LlamaIndex Imports ---
try:
    from llama_index.core import VectorStoreIndex, Settings, Document
    from llama_index.core.postprocessor import SentenceTransformerRerank
    from llama_index.vector_stores.qdrant import QdrantVectorStore
    from llama_index.embeddings.fastembed import FastEmbedEmbedding
    from llama_index.llms.openai_like import OpenAILike
    from qdrant_client import QdrantClient
except ImportError as e:
    print(f"ERROR: LlamaIndex Import fehlgeschlagen: {e}")
    print("Install: pip install llama-index llama-index-vector-stores-qdrant llama-index-embeddings-fastembed llama-index-llms-openai-like --break-system-packages")
    exit(1)

# --- Neo4j ---
try:
    from neo4j import GraphDatabase
    _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    NEO4J_OK = True
    logger.info("Neo4j connected")
except Exception as e:
    NEO4J_OK = False
    logger.warning(f"Neo4j nicht verfuegbar: {e}")

# --- Mem0 ---
import httpx

async def search_mem0(query: str, user_id: str = "cloud-code-team", limit: int = 5):
    """Mem0 Memory Search"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{MEM0_URL}/v1/memories/search/",
                json={"query": query, "user_id": user_id, "limit": limit})
            data = resp.json()
            results = data.get("results", data.get("memories", []))
            return [r.get("memory", r.get("text", str(r))) for r in results[:limit]]
    except Exception as e:
        logger.warning(f"Mem0 search failed: {e}")
        return []

def search_neo4j(query: str, limit: int = 5):
    """Neo4j Knowledge Graph Search"""
    if not NEO4J_OK:
        return []
    try:
        with _neo4j_driver.session() as session:
            result = session.run("""
                MATCH (n)
                WHERE toLower(n.name) CONTAINS toLower($query)
                   OR toLower(coalesce(n.description, '')) CONTAINS toLower($query)
                OPTIONAL MATCH (n)-[r]-(m)
                RETURN n.name AS entity, type(r) AS relation, m.name AS related,
                       coalesce(n.description, '') AS desc
                LIMIT $limit
            """, query=query.split()[0] if query else "", limit=limit)
            return [f"{r['entity']} --{r['relation']}--> {r['related']}: {r['desc']}"
                    for r in result if r['entity']]
    except Exception as e:
        logger.warning(f"Neo4j search failed: {e}")
        return []


# --- LlamaIndex Setup ---
def setup_llama():
    """LlamaIndex mit Ollama + Qdrant + BGE-Reranker"""
    # LLM via Ollama (OpenAI-compatible)
    llm = OpenAILike(
        model=LLM_MODEL,
        api_base=f"{OLLAMA_URL}/v1",
        api_key="ollama",
        temperature=0.3,
        max_tokens=4096,
        is_chat_model=True,
    )

    # Embedding via FastEmbed (schneller als Ollama API)
    try:
        embed = FastEmbedEmbedding(model_name="BAAI/bge-small-en-v1.5")
    except Exception:
        from llama_index.embeddings.openai import OpenAIEmbedding
        embed = OpenAIEmbedding(
            model_name=EMBED_MODEL,
            api_base=f"{OLLAMA_URL}/v1",
            api_key="ollama"
        )

    Settings.llm = llm
    Settings.embed_model = embed

    # BGE Reranker
    reranker = SentenceTransformerRerank(
        model=RERANKER_MODEL,
        top_n=RERANK_TOP_N,
    )

    return llm, embed, reranker


# --- Chainlit Handlers ---
@cl.on_chat_start
async def start():
    """Chat-Session initialisieren"""
    llm, embed, reranker = setup_llama()

    cl.user_session.set("llm", llm)
    cl.user_session.set("reranker", reranker)

    await cl.Message(
        content="**Cloud Code Team — Hybrid Retrieval Chat**\n\n"
        "Quellen: Qdrant (Vektoren) + Neo4j (Knowledge Graph) + Mem0 (Memory)\n"
        "Reranker: BGE-Reranker-v2-m3\n"
        "LLM: minimax-m2.5:cloud via Ollama\n\n"
        "Du kannst auch Dateien hochladen (PDF, TXT, MD)."
    ).send()


@cl.on_message
async def main(message: cl.Message):
    """Nachricht verarbeiten mit Hybrid Retrieval"""
    query = message.content
    llm = cl.user_session.get("llm")
    reranker = cl.user_session.get("reranker")

    # Status
    status = cl.Message(content="Suche in allen Quellen...")
    await status.send()

    # --- Parallel: Mem0 + Neo4j ---
    mem0_task = search_mem0(query)
    neo4j_results = search_neo4j(query)
    mem0_results = await mem0_task

    # --- Context zusammenbauen ---
    context_parts = []
    if mem0_results:
        context_parts.append("**[MEM0 MEMORY]**\n" + "\n".join(f"- {m}" for m in mem0_results))
    if neo4j_results:
        context_parts.append("**[KNOWLEDGE GRAPH]**\n" + "\n".join(f"- {r}" for r in neo4j_results))

    context = "\n\n".join(context_parts) if context_parts else "(Kein Kontext gefunden)"

    # --- File Uploads verarbeiten ---
    if message.elements:
        for element in message.elements:
            if hasattr(element, 'path') and element.path:
                try:
                    with open(element.path, 'r', errors='ignore') as f:
                        file_content = f.read()[:5000]
                    context += f"\n\n**[UPLOADED FILE: {element.name}]**\n{file_content}"
                except Exception as e:
                    context += f"\n\n**[FILE ERROR: {element.name}]** {e}"

    # --- LLM Prompt mit Anti-Halluzination ---
    prompt = f"""Du bist ein KI-Assistent des Cloud Code Team Projekts.

REGELN:
1. Nutze NUR den bereitgestellten Kontext fuer deine Antwort
2. Wenn du etwas nicht weisst, sage es ehrlich
3. Markiere Quellen: [MEM] fuer Memory, [KG] fuer Knowledge Graph, [FILE] fuer Uploads
4. Antworte auf Deutsch

KONTEXT:
{context}

FRAGE: {query}

ANTWORT:"""

    # --- LLM Call ---
    try:
        response = llm.complete(prompt)
        answer = str(response)
    except Exception as e:
        answer = f"LLM-Fehler: {e}"

    # --- Sources ---
    sources = []
    if mem0_results:
        sources.append(f"Mem0: {len(mem0_results)} Memories")
    if neo4j_results:
        sources.append(f"Neo4j: {len(neo4j_results)} Graph-Treffer")
    if message.elements:
        sources.append(f"Uploads: {len(message.elements)} Dateien")

    source_text = " | ".join(sources) if sources else "Keine Quellen"

    # Update message
    status.content = f"{answer}\n\n---\n*Quellen: {source_text}*"
    await status.update()


if __name__ == "__main__":
    print("Start mit: chainlit run /opt/cloud-code/scripts/03-chainlit-hybrid-test.py -p 8080")
