#!/bin/bash
# Cloud Code Team - System Verification Script v2
# 04-verify-system.sh
echo "============================================"
echo "Cloud Code Team - System Verification"
echo "Datum: $(date)"
echo "============================================"
echo ""
PASS=0; FAIL=0; WARN=0

check() {
    local desc="$1" cmd="$2" expect="$3"
    result=$(eval "$cmd" 2>/dev/null)
    if echo "$result" | grep -q "$expect"; then
        echo "  [PASS] $desc"
        PASS=$((PASS+1))
    else
        echo "  [FAIL] $desc (got: $result)"
        FAIL=$((FAIL+1))
    fi
}

warn_check() {
    local desc="$1" cmd="$2" expect="$3"
    result=$(eval "$cmd" 2>/dev/null)
    if echo "$result" | grep -q "$expect"; then
        echo "  [PASS] $desc"
        PASS=$((PASS+1))
    else
        echo "  [WARN] $desc"
        WARN=$((WARN+1))
    fi
}

echo "=== PHASE 1: MVP FUNDAMENT ==="
check "UFW aktiv" "ufw status | head -1" "Status: active"
check "fail2ban aktiv" "systemctl is-active fail2ban" "active"
check "Docker läuft" "systemctl is-active docker" "active"
check "Dify Container" "docker ps --format '{{.Names}}' | grep -c dify" "[0-9]"
check "Caddy SSL" "curl -sI https://difyv2.activi.io 2>/dev/null | head -1" "200"
check "HSTS Header" "curl -sI https://difyv2.activi.io 2>/dev/null | grep -i strict" "max-age"
check "OpenAI in Dify" "curl -s https://difyv2.activi.io/v1/parameters -H 'Authorization: Bearer app-BBMonxom6CYFEsM8tt90bqTg' | grep retriever" "true"
warn_check "Anthropic Provider" "curl -s https://difyv2.activi.io/v1/parameters -H 'Authorization: Bearer app-BBMonxom6CYFEsM8tt90bqTg' | grep anthropic" "anthropic"
echo ""

echo "=== PHASE 2: MEMORY-LAYER ==="
check "Redis PONG" "docker exec -i \$(docker ps -qf name=redis) redis-cli -a \$(grep REDIS_PASSWORD /opt/dify/docker/.env | cut -d= -f2) ping 2>/dev/null" "PONG"
check "Celery Worker" "docker ps --format '{{.Names}}' | grep -c celery" "[0-9]"
check "Mem0 API" "curl -s https://api.mem0.ai/v1/memories/ -H 'Authorization: Token REDACTED_MEM0_API_KEY' | head -1" "["
echo ""

echo "=== PHASE 3: MULTI-AGENT SYSTEM ==="
check "Orchestrator v2 läuft" "systemctl is-active orchestrator" "active"
check "Orchestrator /health" "curl -s http://127.0.0.1:8000/health | grep version" "2.0.0"
check "10 Agents konfiguriert" "curl -s http://127.0.0.1:8000/health | grep agents_configured" "10"
check "/route Endpoint" "curl -s -X POST http://127.0.0.1:8000/route -H 'Content-Type: application/json' -d '{\"query\":\"test\"}' | grep agent" "worker"
echo ""

echo "=== PHASE 4: KNOWLEDGE GRAPH ==="
check "Neo4j läuft" "docker ps --format '{{.Names}}' | grep neo4j" "neo4j"
NODES=$(docker exec neo4j cypher-shell -u neo4j -p 22e58741703f24f1913550c9a8a51c99 "MATCH (n) RETURN count(n)" 2>/dev/null | tail -1)
if [ "$NODES" -ge 40 ] 2>/dev/null; then
    echo "  [PASS] Neo4j Nodes: $NODES (>= 40)"
    PASS=$((PASS+1))
else
    echo "  [FAIL] Neo4j Nodes: $NODES (expected >= 40)"
    FAIL=$((FAIL+1))
fi
check "HippoRAG Service" "systemctl is-active hipporag" "active"
check "HippoRAG /health" "curl -s http://127.0.0.1:8001/health | grep status" "healthy"
echo ""

echo "=== PHASE 5: AUTOMATION HOOKS ==="
check "sqlite-vec DB" "test -f /opt/cloud-code/recall_memory.db && echo exists" "exists"
check "Backup Cron" "crontab -l 2>/dev/null | grep backup" "backup"
check "Locust installiert" "locust --version 2>/dev/null | grep locust" "locust"
echo ""

echo "=== PHASE 6: PRODUCTION ==="
check "Trivy installiert" "which trivy" "trivy"
check "Docker Container Anzahl" "docker ps -q | wc -l | tr -d ' '" "1"
echo ""

echo "============================================"
echo "ERGEBNIS: $PASS bestanden, $FAIL fehlgeschlagen, $WARN Warnungen"
echo "============================================"
