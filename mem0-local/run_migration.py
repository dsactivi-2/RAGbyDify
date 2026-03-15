#!/usr/bin/env python3
import requests, json, time
from datetime import datetime

CLOUD_API_KEY = "m0-a7p49M4dMCTc1vQrm7yWZUiKHfQRylEIgy1OzHoG"
CLOUD_ORG_ID = "org_VgoITua21r2UQsW1Gc0IPLrbvUfduoVEOILnrCti"
CLOUD_PROJECT_ID = "proj_1A9iikWOMqTE4gHBn0ciMRIRM1puUd4oTf1egX8v"
CLOUD_URL = "https://api.mem0.ai"
LOCAL_URL = "http://localhost:8002"

headers = {"Authorization": f"Token {CLOUD_API_KEY}", "Content-Type": "application/json"}
entities = ["cct-architect", "cct-coder", "cct-tester", "cct-reviewer", "cct-devops", "cct-docs", "cct-security", "cct-planner", "cct-debug", "cct-worker", "cloud-code-team", "playground"]

all_memories = []
for entity in entities:
    r = requests.get(f"{CLOUD_URL}/v1/memories/", headers=headers, params={
        "user_id": entity, "org_id": CLOUD_ORG_ID, "project_id": CLOUD_PROJECT_ID,
    })
    data = r.json()
    memories = data if isinstance(data, list) else data.get("results", [])
    for mem in memories:
        mem["_source_entity"] = entity
    all_memories.extend(memories)
    if memories:
        print(f"Export: {entity}: {len(memories)} memories", flush=True)
    time.sleep(0.3)

print(f"Total: {len(all_memories)}", flush=True)

success = 0
for i, mem in enumerate(all_memories):
    content = mem.get("memory", mem.get("data", ""))
    if not content:
        continue
    source = mem.get("_source_entity", "unknown")
    payload = {
        "messages": content,
        "user_id": "cloud-code-team",
        "agent_id": source,
        "metadata": {"migrated_from": "mem0-cloud", "original_entity": source}
    }
    try:
        r = requests.post(f"{LOCAL_URL}/v1/memories/", json=payload, timeout=120)
        if r.status_code == 200:
            success += 1
            print(f"[{i+1}/{len(all_memories)}] OK: {content[:60]}...", flush=True)
        else:
            print(f"[{i+1}/{len(all_memories)}] FAIL: {r.text[:100]}", flush=True)
    except Exception as e:
        print(f"[{i+1}/{len(all_memories)}] ERROR: {e}", flush=True)
    time.sleep(2)

print(f"DONE: {success}/{len(all_memories)}", flush=True)
