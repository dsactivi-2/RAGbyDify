#\!/bin/bash
# Cloud Code Team - Backup Script with Verification
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/cloud-code/backups"
LOG="/opt/cloud-code/backups/backup.log"

echo "[$TIMESTAMP] Backup started" >> "$LOG"

# 1. Dify volumes
cd /opt/dify/docker
docker compose exec -T db_postgres pg_dump -U postgres dify | gzip > "$BACKUP_DIR/dify_db_$TIMESTAMP.sql.gz" 2>> "$LOG"

# 2. Neo4j
docker exec neo4j neo4j-admin database dump neo4j --to-path=/tmp/ 2>> "$LOG" || true
docker cp neo4j:/tmp/neo4j.dump "$BACKUP_DIR/neo4j_$TIMESTAMP.dump" 2>> "$LOG" || true

# 3. sqlite-vec recall DB
cp /opt/cloud-code/recall_memory.db "$BACKUP_DIR/recall_memory_$TIMESTAMP.db" 2>> "$LOG"

# 4. Dify .env
cp /opt/dify/docker/.env "$BACKUP_DIR/dify_env_$TIMESTAMP.bak" 2>> "$LOG"

# 5. Orchestrator + HippoRAG code
tar czf "$BACKUP_DIR/services_$TIMESTAMP.tar.gz" /opt/cloud-code/orchestrator/ /opt/cloud-code/hipporag/ 2>> "$LOG"

# Verification
ERRORS=0
for f in "$BACKUP_DIR/dify_db_$TIMESTAMP.sql.gz" "$BACKUP_DIR/recall_memory_$TIMESTAMP.db" "$BACKUP_DIR/dify_env_$TIMESTAMP.bak" "$BACKUP_DIR/services_$TIMESTAMP.tar.gz"; do
    if [ \! -f "$f" ] || [ \! -s "$f" ]; then
        echo "[$TIMESTAMP] FAIL: $f missing or empty" >> "$LOG"
        ERRORS=$((ERRORS+1))
    fi
done

# Cleanup old backups (keep 7 days)
find "$BACKUP_DIR" -name "*.gz" -o -name "*.dump" -o -name "*.db" -o -name "*.bak" | while read f; do
    age=$(( ($(date +%s) - $(stat -c %Y "$f")) / 86400 ))
    if [ "$age" -gt 7 ]; then
        rm -f "$f"
        echo "[$TIMESTAMP] Cleaned: $f" >> "$LOG"
    fi
done

TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
echo "[$TIMESTAMP] Backup finished. Errors: $ERRORS, Total size: $TOTAL_SIZE" >> "$LOG"

if [ "$ERRORS" -gt 0 ]; then
    exit 1
fi
