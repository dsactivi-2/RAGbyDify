#!/bin/bash
# Cloud Code Team — Neo4j als systemd-Service einrichten
# Neo4j laeuft als Docker-Container, dieser Service stellt sicher
# dass er bei Reboot automatisch startet und ueberwacht wird.

set -e

echo "╔═══════════════════════════════════════════╗"
echo "║  Neo4j systemd Service Setup              ║"
echo "╚═══════════════════════════════════════════╝"

# Pruefen ob Neo4j Docker-Container existiert
if ! docker inspect neo4j > /dev/null 2>&1; then
    echo "❌ Docker-Container 'neo4j' nicht gefunden!"
    exit 1
fi

# Aktuelle Container-Config extrahieren
IMAGE=$(docker inspect neo4j --format '{{.Config.Image}}')
BINDS=$(docker inspect neo4j --format '{{json .HostConfig.Binds}}')
echo "Image: $IMAGE"
echo "Volumes: $BINDS"

# systemd Service erstellen
cat > /etc/systemd/system/neo4j.service <<'SVCEOF'
[Unit]
Description=Cloud Code Team Neo4j Knowledge Graph (Docker)
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=on-failure
RestartSec=10

# Container stoppen falls laeuft, dann starten
ExecStartPre=-/usr/bin/docker stop neo4j
ExecStartPre=-/usr/bin/docker rm neo4j

ExecStart=/usr/bin/docker run --rm --name neo4j \
  -p 127.0.0.1:7474:7474 \
  -p 127.0.0.1:7687:7687 \
  -v /opt/cloud-code/neo4j/data:/data \
  -v /opt/cloud-code/neo4j/logs:/logs \
  -e NEO4J_AUTH=neo4j/22e58741703f24f1913550c9a8a51c99 \
  -e NEO4J_server_memory_heap_initial__size=1g \
  -e NEO4J_server_memory_heap_max__size=2g \
  -e NEO4J_dbms_security_procedures_unrestricted=apoc.* \
  neo4j:5-community

ExecStop=/usr/bin/docker stop neo4j

[Install]
WantedBy=multi-user.target
SVCEOF

# Service registrieren
systemctl daemon-reload
systemctl enable neo4j.service

echo ""
echo "✅ neo4j.service erstellt und enabled"
echo ""
echo "HINWEIS: Neo4j laeuft aktuell als Docker-Container."
echo "Um auf systemd umzustellen:"
echo "  1. docker stop neo4j && docker rm neo4j"
echo "  2. systemctl start neo4j"
echo "  3. systemctl status neo4j"
echo ""
echo "Oder einfach beim naechsten Reboot — der Service startet automatisch."
