#!/bin/bash
# Cloud Code Team — SDK Scanner
# Findet alle venvs UND prueft globale + Docker-Pakete

echo "╔═══════════════════════════════════════════╗"
echo "║  SDK Scanner — Cloud Code Team            ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

PATTERN='llama|qdrant|mem0|neo4j|ragas|fastembed|langfuse|chainlit|bge|rerank|FlagEmbed|sentence.transform|dspy|cachetools|ollama'

echo "━━━ 1. Globale Python-Pakete ━━━"
pip3 list 2>/dev/null | grep -Ei "$PATTERN" | sort
echo ""

echo "━━━ 2. Virtuelle Umgebungen (venv/virtualenv) ━━━"
VENVS=$(find /opt /home /root -name "pyvenv.cfg" -o -name "activate" 2>/dev/null | grep -v __pycache__)
if [ -z "$VENVS" ]; then
    echo "  Keine venvs gefunden — alle SDKs sind global installiert."
else
    for VENV_FILE in $VENVS; do
        VENV_DIR=$(dirname "$(dirname "$VENV_FILE")")
        echo "  --- $VENV_DIR ---"
        "$VENV_DIR/bin/pip" list 2>/dev/null | grep -Ei "$PATTERN" | sort || echo "    (pip nicht verfuegbar)"
    done
fi
echo ""

echo "━━━ 3. Docker-Container mit relevanten Paketen ━━━"
for CONTAINER in $(docker ps --format '{{.Names}}'); do
    PKGS=$(docker exec "$CONTAINER" pip list 2>/dev/null | grep -Ei "$PATTERN")
    if [ -n "$PKGS" ]; then
        echo "  --- $CONTAINER ---"
        echo "$PKGS" | sed 's/^/    /'
    fi
done
echo ""

echo "━━━ 4. Zusammenfassung ━━━"
GLOBAL_COUNT=$(pip3 list 2>/dev/null | grep -Eic "$PATTERN")
echo "  Globale relevante Pakete: $GLOBAL_COUNT"
echo "  Python-Version: $(python3 --version 2>&1)"
echo "  pip-Version: $(pip3 --version 2>&1 | head -c 40)"
