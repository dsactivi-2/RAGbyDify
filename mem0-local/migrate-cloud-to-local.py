#!/usr/bin/env python3
"""
Cloud Code Team — Mem0 Cloud → Lokal Migration
================================================
Exportiert alle Memories von api.mem0.ai und importiert sie in den lokalen Mem0 Server.
"""

import requests
import json
import time
import sys
from datetime import datetime

# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────

CLOUD_API_KEY = "m0-a7p49M4dMCTc1vQrm7yWZUiKHfQRylEIgy1OzHoG"
CLOUD_ORG_ID = "org_VgoITua21r2UQsW1Gc0IPLrbvUfduoVEOILnrCti"
CLOUD_PROJECT_ID = "proj_1A9iikWOMqTE4gHBn0ciMRIRM1puUd4oTf1egX8v"
CLOUD_URL = "https://api.mem0.ai"

LOCAL_URL = "http://localhost:8002"

# Alle bekannten Entities aus deinem Mem0 Dashboard
ENTITIES = [
    "cct-architect", "cct-coder", "cct-tester", "cct-reviewer",
    "cct-devops", "cct-docs", "cct-security", "cct-planner",
    "cct-debug", "cct-worker", "cloud-code-team", "playground"
]

# ──────────────────────────────────────────
# EXPORT VON CLOUD
# ──────────────────────────────────────────

def export_from_cloud():
    """Alle Memories aus Mem0 Cloud exportieren"""
    print("=" * 60)
    print("PHASE 1: Export aus Mem0 Cloud")
    print("=" * 60)

    headers = {
        "Authorization": f"Token {CLOUD_API_KEY}",
        "Content-Type": "application/json",
    }

    all_memories = []

    for entity in ENTITIES:
        print(f"\n📥 Exportiere Entity: {entity}")
        try:
            r = requests.get(
                f"{CLOUD_URL}/v1/memories/",
                headers=headers,
                params={
                    "user_id": entity,
                    "org_id": CLOUD_ORG_ID,
                    "project_id": CLOUD_PROJECT_ID,
                }
            )
            if r.status_code == 200:
                memories = r.json().get("results", r.json() if isinstance(r.json(), list) else [])
                print(f"   ✅ {len(memories)} Memories gefunden")
                for mem in memories:
                    mem["_source_entity"] = entity
                all_memories.extend(memories)
            else:
                print(f"   ⚠️ Status {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        time.sleep(0.5)  # Rate limiting

    # Backup als JSON
    backup_file = f"mem0-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(backup_file, "w") as f:
        json.dump(all_memories, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Backup gespeichert: {backup_file}")
    print(f"📊 Total: {len(all_memories)} Memories aus {len(ENTITIES)} Entities")

    return all_memories


# ──────────────────────────────────────────
# IMPORT IN LOKAL
# ──────────────────────────────────────────

def import_to_local(memories):
    """Memories in lokalen Mem0 Server importieren"""
    print("\n" + "=" * 60)
    print("PHASE 2: Import in lokalen Mem0 Server")
    print("=" * 60)

    # Healthcheck
    try:
        r = requests.get(f"{LOCAL_URL}/health")
        if r.status_code != 200:
            print("❌ Lokaler Mem0 Server nicht erreichbar!")
            sys.exit(1)
        print(f"✅ Lokaler Server erreichbar: {r.json()}")
    except Exception as e:
        print(f"❌ Kann lokalen Server nicht erreichen: {e}")
        sys.exit(1)

    success = 0
    failed = 0

    for i, mem in enumerate(memories):
        source_entity = mem.get("_source_entity", "unknown")
        content = mem.get("memory", mem.get("data", mem.get("content", "")))

        if not content:
            print(f"   ⏭️ [{i+1}/{len(memories)}] Leere Memory, übersprungen")
            continue

        # Neue Mapping: alle auf shared user_id, alte Entity wird agent_id
        payload = {
            "messages": content,
            "user_id": "cloud-code-team",  # SHARED
            "agent_id": source_entity,      # Alte Entity → Agent-ID
            "metadata": {
                "migrated_from": "mem0-cloud",
                "original_entity": source_entity,
                "migrated_at": datetime.utcnow().isoformat(),
                "original_id": mem.get("id", ""),
            }
        }

        try:
            r = requests.post(f"{LOCAL_URL}/v1/memories/", json=payload)
            if r.status_code == 200:
                success += 1
                if (i + 1) % 10 == 0:
                    print(f"   ✅ [{i+1}/{len(memories)}] Importiert ({source_entity})")
            else:
                failed += 1
                print(f"   ⚠️ [{i+1}/{len(memories)}] Fehler: {r.status_code}")
        except Exception as e:
            failed += 1
            print(f"   ❌ [{i+1}/{len(memories)}] Error: {e}")

        time.sleep(0.2)  # Nicht überlasten

    print(f"\n{'=' * 60}")
    print(f"MIGRATION ABGESCHLOSSEN")
    print(f"{'=' * 60}")
    print(f"✅ Erfolgreich: {success}")
    print(f"❌ Fehlgeschlagen: {failed}")
    print(f"📊 Total: {len(memories)}")


# ──────────────────────────────────────────
# VERIFY
# ──────────────────────────────────────────

def verify():
    """Migration verifizieren"""
    print(f"\n{'=' * 60}")
    print(f"PHASE 3: Verifikation")
    print(f"{'=' * 60}")

    try:
        r = requests.get(f"{LOCAL_URL}/v1/stats/")
        stats = r.json()
        print(f"\n📊 Lokaler Mem0 Server Status:")
        print(f"   Total Memories:  {stats.get('total_memories', '?')}")
        print(f"   Unique Users:    {stats.get('unique_users', '?')}")
        print(f"   Unique Agents:   {stats.get('unique_agents', '?')}")
        print(f"\n   By Agent:")
        for agent, count in stats.get("by_agent", {}).items():
            print(f"     {agent}: {count}")
    except Exception as e:
        print(f"❌ Verifikation fehlgeschlagen: {e}")


# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--import-only":
        # Nur Import aus bestehendem Backup
        backup = sys.argv[2] if len(sys.argv) > 2 else None
        if backup:
            with open(backup) as f:
                memories = json.load(f)
            import_to_local(memories)
            verify()
        else:
            print("Usage: python migrate.py --import-only <backup-file.json>")
    elif len(sys.argv) > 1 and sys.argv[1] == "--verify":
        verify()
    else:
        # Vollständige Migration
        memories = export_from_cloud()
        import_to_local(memories)
        verify()
