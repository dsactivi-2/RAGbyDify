#!/bin/bash
# Cloud Code Team — Fehlende Pakete installieren
# Alles wird GLOBAL installiert (kein venv auf diesem Server)

set -e

echo "╔═══════════════════════════════════════════╗"
echo "║  Paket-Installation — Cloud Code Team     ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# --- 1. Chainlit (Chat UI mit File Upload) ---
echo "━━━ 1. Chainlit ━━━"
if pip3 show chainlit > /dev/null 2>&1; then
    echo "  ✅ chainlit bereits installiert ($(pip3 show chainlit | grep Version | awk '{print $2}'))"
else
    echo "  Installing chainlit..."
    pip3 install chainlit --break-system-packages
    echo "  ✅ chainlit installiert"
fi

# --- 2. httpx (async HTTP client fuer Mem0) ---
echo ""
echo "━━━ 2. httpx ━━━"
if pip3 show httpx > /dev/null 2>&1; then
    echo "  ✅ httpx bereits installiert"
else
    pip3 install httpx --break-system-packages
    echo "  ✅ httpx installiert"
fi

# --- 3. cypher-shell (Neo4j CLI) ---
echo ""
echo "━━━ 3. cypher-shell ━━━"
if which cypher-shell > /dev/null 2>&1; then
    echo "  ✅ cypher-shell bereits installiert"
else
    echo "  Hinweis: cypher-shell ist im Docker-Container verfuegbar:"
    echo "    docker exec neo4j cypher-shell -u neo4j -p '22e58741703f24f1913550c9a8a51c99' 'MATCH (n) RETURN count(n);'"
    echo ""
    echo "  Fuer lokale Installation (optional):"
    echo "    wget https://dist.neo4j.org/cypher-shell/cypher-shell-5.26.22.zip"
    echo "    unzip cypher-shell-5.26.22.zip -d /opt/"
    echo "    ln -s /opt/cypher-shell/cypher-shell /usr/local/bin/cypher-shell"
fi

# --- 4. Langfuse (bereits installiert, Version pruefen) ---
echo ""
echo "━━━ 4. Langfuse ━━━"
if pip3 show langfuse > /dev/null 2>&1; then
    echo "  ✅ langfuse bereits installiert ($(pip3 show langfuse | grep Version | awk '{print $2}'))"
else
    pip3 install langfuse --break-system-packages
    echo "  ✅ langfuse installiert"
fi

# --- 5. BGE Reranker Model Download (beim ersten Aufruf) ---
echo ""
echo "━━━ 5. BGE-Reranker Model Check ━━━"
python3 -c "
from FlagEmbedding import FlagReranker
print('  ✅ FlagEmbedding + BGE-Reranker verfuegbar')
print('  Modell wird beim ersten Aufruf automatisch heruntergeladen (~1.1 GB)')
" 2>/dev/null || echo "  ⚠️ FlagEmbedding Import-Fehler — pip install FlagEmbedding --break-system-packages"

# --- 6. Zusammenfassung ---
echo ""
echo "━━━ Zusammenfassung ━━━"
echo ""
echo "Paket                                          | Status"
echo "------------------------------------------------|--------"
for PKG in chainlit httpx langfuse FlagEmbedding sentence-transformers \
           llama-index llama-index-vector-stores-qdrant qdrant-client \
           mem0ai neo4j fastembed ragas dspy cachetools ollama; do
    VER=$(pip3 show "$PKG" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    if [ -n "$VER" ]; then
        printf "  %-46s | ✅ %s\n" "$PKG" "$VER"
    else
        printf "  %-46s | ❌ FEHLT\n" "$PKG"
    fi
done

echo ""
echo "━━━ Disk Usage nach Installation ━━━"
df -h / | awk 'NR==2{print "  " $3 " belegt, " $4 " frei (" $5 " used)"}'
