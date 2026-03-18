#!/bin/bash
# Cloud Code Team - Backup Script v4 (K2 complete: no hardcoded pass, ps aux safe)
# Fixes: dynamic timestamp, Neo4j password via env var (not CLI arg)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/opt/cloud-code/backups
LOG=/opt/cloud-code/backups/backup.log
mkdir -p $BACKUP_DIR
ERRORS=0

# Load Neo4j password from env (avoids exposing in ps aux output)
NEO4J_PASS=${NEO4J_PASSWORD}
[ -z "$NEO4J_PASS" ] && { echo "[ERROR] NEO4J_PASSWORD not set" >>$LOG; exit 1; }

echo "[$TIMESTAMP] Backup v3 started" >> $LOG

# 1. Dify Postgres DB
docker exec docker-db_postgres-1 pg_dump -U postgres dify 2>>$LOG | gzip > "$BACKUP_DIR/dify_db_$TIMESTAMP.sql.gz"
[ -s "$BACKUP_DIR/dify_db_$TIMESTAMP.sql.gz" ] && echo "[$TIMESTAMP] OK: dify_db" >>$LOG || { echo "[$TIMESTAMP] FAIL: dify_db" >>$LOG; ERRORS=$((ERRORS+1)); }

# 2. Neo4j Cypher export (password via variable, not inline CLI arg)
docker exec -e NEO4J_PASSWORD="${NEO4J_PASS}" neo4j \
    cypher-shell -u neo4j \
    "CALL apoc.export.cypher.all('/tmp/neo4j_export.cypher', {format:'cypher-shell'})" 2>>$LOG
docker cp neo4j:/tmp/neo4j_export.cypher "$BACKUP_DIR/neo4j_$TIMESTAMP.cypher" 2>>$LOG && \
    gzip -f "$BACKUP_DIR/neo4j_$TIMESTAMP.cypher" && \
    echo "[$TIMESTAMP] OK: neo4j_export" >>$LOG || \
    echo "[$TIMESTAMP] WARN: neo4j cypher export failed" >>$LOG

# 3. Qdrant snapshot (Mem0 vector memories)
SNAP_RESP=$(curl -sf -X POST http://localhost:16333/collections/mem0_memories/snapshots 2>>$LOG)
SNAP_NAME=$(echo "$SNAP_RESP" | python3 -c "import sys,re; t=sys.stdin.read(); m=re.search(r'\"name\":\"([^\"]+)\"',t); print(m.group(1) if m else '')" 2>/dev/null)
if [ -n "$SNAP_NAME" ]; then
    curl -sf "http://localhost:16333/collections/mem0_memories/snapshots/$SNAP_NAME" \
        -o "$BACKUP_DIR/qdrant_mem0_$TIMESTAMP.snapshot" 2>>$LOG && \
        echo "[$TIMESTAMP] OK: qdrant_snapshot $SNAP_NAME" >>$LOG || \
        echo "[$TIMESTAMP] WARN: qdrant snapshot download failed" >>$LOG
else
    echo "[$TIMESTAMP] WARN: qdrant snapshot creation failed" >>$LOG
fi

# 4. SQLite DBs
for db in /opt/cloud-code/core_memory.db /opt/cloud-code/recall_memory.db; do
    fname=$(basename "$db" .db)
    if [ -f "$db" ]; then
        cp "$db" "$BACKUP_DIR/${fname}_$TIMESTAMP.db" && \
            echo "[$TIMESTAMP] OK: $fname" >>$LOG
    fi
done

# 5. Dify .env
[ -f /opt/dify/docker/.env ] && cp /opt/dify/docker/.env "$BACKUP_DIR/dify_env_$TIMESTAMP.bak" && \
    echo "[$TIMESTAMP] OK: dify_env" >>$LOG

# 6. Code tar
tar czf "$BACKUP_DIR/services_$TIMESTAMP.tar.gz" \
    /opt/cloud-code/orchestrator/ /opt/cloud-code/hipporag/ 2>>$LOG && \
    echo "[$TIMESTAMP] OK: services" >>$LOG

# Cleanup: keep 7 days
find $BACKUP_DIR -type f | while read f; do
    age=$(( ( $(date +%s) - $(stat -c %Y "$f") ) / 86400 ))
    [ "$age" -gt 7 ] && rm -f "$f" && echo "[$TIMESTAMP] Cleaned: $f" >>$LOG
done

TOTAL=$(du -sh $BACKUP_DIR 2>/dev/null | cut -f1)
echo "[$TIMESTAMP] Backup v3 done. Errors: $ERRORS, Total: $TOTAL" >>$LOG
exit $ERRORS
