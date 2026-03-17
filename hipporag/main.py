"""
Cloud Code Team - HippoRAG Service
FastAPI microservice for Knowledge Graph-based retrieval
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from neo4j import GraphDatabase
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hipporag")

app = FastAPI(title="HippoRAG Service", version="1.0.0")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "22e58741703f24f1913550c9a8a51c99")
HOP_DEPTH = int(os.getenv("HIPPORAG_HOP_DEPTH", "3"))

driver = None

class AddKnowledgeRequest(BaseModel):
    subject: str
    predicate: str
    obj: str
    source: Optional[str] = None
    metadata: Optional[dict] = None

class QueryRequest(BaseModel):
    query: str
    hop_depth: Optional[int] = None
    limit: Optional[int] = 10

class HealthResponse(BaseModel):
    status: str
    neo4j_connected: bool
    node_count: int
    relationship_count: int

@app.on_event("startup")
async def startup():
    global driver
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        with driver.session() as session:
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.name)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.type)")
        logger.info("Connected to Neo4j")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")

@app.on_event("shutdown")
async def shutdown():
    if driver:
        driver.close()

@app.get("/health", response_model=HealthResponse)
async def health():
    if not driver:
        return HealthResponse(status="error", neo4j_connected=False, node_count=0, relationship_count=0)
    try:
        with driver.session() as session:
            nodes = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
        return HealthResponse(status="healthy", neo4j_connected=True, node_count=nodes, relationship_count=rels)
    except Exception as e:
        return HealthResponse(status=f"error: {str(e)}", neo4j_connected=False, node_count=0, relationship_count=0)

@app.post("/knowledge/add")
async def add_knowledge(req: AddKnowledgeRequest):
    if not driver:
        raise HTTPException(500, "Neo4j not connected")
    try:
        with driver.session() as session:
            query = """
            MERGE (s:Entity {name: $subject})
            MERGE (o:Entity {name: $obj})
            MERGE (s)-[r:RELATES {type: $predicate}]->(o)
            SET r.source = $source, r.updated_at = datetime()
            RETURN s.name, type(r), o.name
            """
            result = session.run(query, subject=req.subject, obj=req.obj,
                               predicate=req.predicate, source=req.source)
            record = result.single()
            return {"status": "added", "triple": [record[0], record[1], record[2]]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/knowledge/query")
async def query_knowledge(req: QueryRequest):
    if not driver:
        raise HTTPException(500, "Neo4j not connected")
    depth = min(req.hop_depth or HOP_DEPTH, 3)
    try:
        with driver.session() as session:
            # Split query into terms (min 3 chars); search nodes matching ANY term
            terms = [t.strip() for t in req.query.split() if len(t.strip()) >= 3]
            if not terms:
                terms = [req.query]

            find_q = "MATCH (start) WHERE toLower(start.name) CONTAINS toLower($term) RETURN start LIMIT $lim"
            seen_ids = set()
            start_nodes = []
            for term in terms:
                for row in session.run(find_q, term=term, lim=req.limit):
                    eid = row["start"].element_id
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        start_nodes.append(row)

            if not start_nodes:
                return {"results": [], "query": req.query, "hop_depth": depth}

            records = []
            for sn in start_nodes:
                sid = sn["start"].element_id
                rel_q = "MATCH (s)-[r]-(n) WHERE elementId(s) = $sid RETURN s, r, n LIMIT 20"
                rels = list(session.run(rel_q, sid=sid))
                nodes_map = {}
                relationships = []
                for rec in rels:
                    s = rec["s"]
                    n = rec["n"]
                    r = rec["r"]
                    sl = list(s.labels)
                    nl = list(n.labels)
                    nodes_map[s.element_id] = {"name": s.get("name", "?"), "type": sl[0] if sl else "Entity"}
                    nodes_map[n.element_id] = {"name": n.get("name", "?"), "type": nl[0] if nl else "Entity"}
                    relationships.append({"from": s.get("name", "?"), "type": r.type, "to": n.get("name", "?")})
                if relationships:
                    records.append({"nodes": list(nodes_map.values()), "relationships": relationships})

            return {"results": records, "query": req.query, "hop_depth": depth}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/knowledge/bulk")
async def bulk_add(triples: List[AddKnowledgeRequest]):
    results = []
    for t in triples:
        try:
            r = await add_knowledge(t)
            results.append(r)
        except Exception as e:
            results.append({"status": "error", "error": str(e)})
    return {
        "added": len([r for r in results if r.get("status") == "added"]),
        "errors": len([r for r in results if r.get("status") == "error"])
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
