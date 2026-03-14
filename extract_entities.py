from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "22e58741703f24f1913550c9a8a51c99"

ENTITIES = [
    ("Hetzner CCX33", "Server", {"vcpu": 8, "ram": "32GB", "ssd": "240GB", "ip": "178.104.51.123"}),
    ("Ubuntu 22.04", "OS", {}),
    ("Docker", "Platform", {"containers": 12}),
    ("Caddy", "ReverseProxy", {"ssl": True, "hsts": True}),
    ("UFW", "Firewall", {"ports": "22,80,443"}),
    ("fail2ban", "Security", {}),
    ("Cloudflare", "DNS", {"domain": "difyv2.activi.io"}),
    ("Dify", "Platform", {"version": "1.13.0"}),
    ("FastAPI Orchestrator", "Service", {"version": "2.0.0", "port": 8000}),
    ("HippoRAG", "Service", {"port": 8001}),
    ("Neo4j", "Database", {"version": "5"}),
    ("Redis", "Cache", {}),
    ("Qdrant", "VectorDB", {}),
    ("PostgreSQL", "Database", {}),
    ("Celery", "TaskQueue", {"workers": 1}),
    ("OpenAI gpt-4o", "LLM", {}),
    ("Mem0", "MemorySystem", {"version": "0.0.2"}),
    ("sqlite-vec", "RecallDB", {}),
    ("Architect Agent", "Agent", {"namespace": "cct-architect"}),
    ("Coder Agent", "Agent", {"namespace": "cct-coder"}),
    ("Tester Agent", "Agent", {"namespace": "cct-tester"}),
    ("Reviewer Agent", "Agent", {"namespace": "cct-reviewer"}),
    ("DevOps Agent", "Agent", {"namespace": "cct-devops"}),
    ("Docs Agent", "Agent", {"namespace": "cct-docs"}),
    ("Security Agent", "Agent", {"namespace": "cct-security"}),
    ("Planner Agent", "Agent", {"namespace": "cct-planner"}),
    ("Debug Agent", "Agent", {"namespace": "cct-debug"}),
    ("Worker Agent", "Agent", {"namespace": "cct-worker"}),
    ("Cloud Code Team KB", "KnowledgeBase", {}),
    ("Anti-Halluzination", "Concept", {"rules": 5}),
    ("Streaming Workaround", "Concept", {}),
    ("Keyword-Routing", "Concept", {}),
    ("Chain-Execution", "Concept", {}),
    ("Phase 1 MVP", "Phase", {"score": "83%"}),
    ("Phase 2 Memory", "Phase", {"score": "83%"}),
    ("Phase 3 Multi-Agent", "Phase", {"score": "100%"}),
    ("Phase 4 Knowledge Graph", "Phase", {"score": "67%"}),
    ("Phase 5 Automation", "Phase", {"score": "40%"}),
    ("Phase 6 Production", "Phase", {"score": "17%"}),
    ("projektbeschreibung.md", "Document", {}),
    ("tech-stack.md", "Document", {}),
    ("workflows-und-prozesse.md", "Document", {}),
    ("Dify Answer-Node Bug", "Bug", {"status": "workaround"}),
    ("CELERY_BROKER_URL Bug", "Bug", {"status": "fixed"}),
]

RELS = [
    ("Hetzner CCX33","RUNS","Ubuntu 22.04"),("Ubuntu 22.04","HOSTS","Docker"),
    ("Docker","RUNS","Dify"),("Docker","RUNS","Redis"),("Docker","RUNS","Qdrant"),
    ("Docker","RUNS","PostgreSQL"),("Docker","RUNS","Neo4j"),("Caddy","PROXIES","Dify"),
    ("UFW","PROTECTS","Hetzner CCX33"),("fail2ban","PROTECTS","Hetzner CCX33"),
    ("Cloudflare","ROUTES_TO","Caddy"),("Dify","USES","OpenAI gpt-4o"),
    ("Dify","USES","Mem0"),("Dify","USES","Redis"),("Dify","USES","Qdrant"),
    ("Dify","USES","PostgreSQL"),("FastAPI Orchestrator","COORDINATES","Dify"),
    ("HippoRAG","USES","Neo4j"),("Celery","USES","Redis"),
    ("Dify","HOSTS","Architect Agent"),("Dify","HOSTS","Coder Agent"),
    ("Dify","HOSTS","Tester Agent"),("Dify","HOSTS","Reviewer Agent"),
    ("Dify","HOSTS","DevOps Agent"),("Dify","HOSTS","Docs Agent"),
    ("Dify","HOSTS","Security Agent"),("Dify","HOSTS","Planner Agent"),
    ("Dify","HOSTS","Debug Agent"),("Dify","HOSTS","Worker Agent"),
    ("Architect Agent","USES","Cloud Code Team KB"),("Architect Agent","USES","Mem0"),
    ("Architect Agent","FOLLOWS","Anti-Halluzination"),
    ("Coder Agent","USES","Cloud Code Team KB"),("Coder Agent","FOLLOWS","Anti-Halluzination"),
    ("Tester Agent","FOLLOWS","Anti-Halluzination"),("Reviewer Agent","FOLLOWS","Anti-Halluzination"),
    ("DevOps Agent","FOLLOWS","Anti-Halluzination"),("Security Agent","FOLLOWS","Anti-Halluzination"),
    ("Planner Agent","FOLLOWS","Anti-Halluzination"),("Debug Agent","FOLLOWS","Anti-Halluzination"),
    ("Docs Agent","FOLLOWS","Anti-Halluzination"),("Worker Agent","FOLLOWS","Anti-Halluzination"),
    ("FastAPI Orchestrator","ROUTES_VIA","Keyword-Routing"),
    ("FastAPI Orchestrator","SUPPORTS","Chain-Execution"),
    ("FastAPI Orchestrator","USES","Streaming Workaround"),
    ("Streaming Workaround","FIXES","Dify Answer-Node Bug"),
    ("Phase 1 MVP","INCLUDES","Hetzner CCX33"),("Phase 1 MVP","INCLUDES","Dify"),
    ("Phase 2 Memory","INCLUDES","Mem0"),("Phase 2 Memory","INCLUDES","Redis"),
    ("Phase 3 Multi-Agent","INCLUDES","FastAPI Orchestrator"),
    ("Phase 4 Knowledge Graph","INCLUDES","Neo4j"),("Phase 4 Knowledge Graph","INCLUDES","HippoRAG"),
    ("Phase 5 Automation","INCLUDES","sqlite-vec"),
    ("Cloud Code Team KB","CONTAINS","projektbeschreibung.md"),
    ("Cloud Code Team KB","CONTAINS","tech-stack.md"),
    ("Cloud Code Team KB","CONTAINS","workflows-und-prozesse.md"),
]

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
with driver.session() as s:
    s.run("MATCH (n) DETACH DELETE n")
    for name, ntype, props in ENTITIES:
        props["name"] = name
        prop_parts = ", ".join([f"{k}: ${k}" for k in props])
        q = f"CREATE (n:{ntype} {{{prop_parts}}})"
        s.run(q, props)
    print(f"Created {len(ENTITIES)} entities")
    rc = 0
    for src, rt, tgt in RELS:
        r = s.run(f"MATCH (a {{name: $s}}), (b {{name: $t}}) CREATE (a)-[:{rt}]->(b) RETURN count(*) as c", s=src, t=tgt)
        if r.single()["c"] > 0: rc += 1
    print(f"Created {rc}/{len(RELS)} relationships")
    nodes = s.run("MATCH (n) RETURN count(n) as c").single()["c"]
    rels = s.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
    print(f"Graph: {nodes} nodes, {rels} relationships")
driver.close()
print("Done!")
