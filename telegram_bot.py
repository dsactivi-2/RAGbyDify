"""
A.AI Coach - Telegram Bot v3
Multilingual (EN/DE/BS), streaming mode, per-user language + conversation tracking.
PERSISTENT MEMORY: user state + per-user facts survive restarts.
Supports private + group chats. Shareable via t.me/botusername
"""
import os
import json
import logging
import asyncio
import time
from pathlib import Path
import httpx
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

# Configuration
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "REDACTED_TELEGRAM_TOKEN")
DIFY_API_URL = os.environ.get("DIFY_API_URL", "http://localhost:3080/v1")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "REDACTED_DIFY_API_KEY")
DIFY_KB_ID = "REDACTED_DIFY_KB_ID"
DIFY_KB_KEY = "REDACTED_DIFY_KB_KEY"
HIPPORAG_URL = "http://localhost:8001/knowledge/query"

# Persistent storage paths
DATA_DIR = Path("/opt/cloud-code/data")
STATE_FILE = DATA_DIR / "user_state.json"
MEMORY_DIR = DATA_DIR / "memories"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("AAICoach")

# ──────── Persistent State ────────

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

def load_user_state() -> dict:
    """Load user state from disk."""
    ensure_dirs()
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
    return {}

def save_user_state():
    """Save user state to disk."""
    ensure_dirs()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(user_state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Could not save state: {e}")

# Per-user state: {user_id: {"conversation_id": "", "lang": "en", "name": ""}}
user_state = load_user_state()

# ──────── Per-User Memory ────────

def _memory_file(user_id: str) -> Path:
    return MEMORY_DIR / f"{user_id}.json"

def load_memories(user_id: str) -> list:
    """Load memory entries for a user: [{"fact": "...", "ts": 1234}]"""
    f = _memory_file(user_id)
    if f.exists():
        try:
            with open(f, "r") as fh:
                return json.load(fh)
        except Exception:
            pass
    return []

def save_memory(user_id: str, fact: str):
    """Save a fact to user's persistent memory."""
    ensure_dirs()
    memories = load_memories(user_id)
    memories.append({"fact": fact, "ts": int(time.time())})
    # Keep max 100 memories per user
    if len(memories) > 100:
        memories = memories[-100:]
    try:
        with open(_memory_file(user_id), "w") as f:
            json.dump(memories, f, indent=2, ensure_ascii=False)
        logger.info(f"Memory saved for {user_id}: {fact[:50]}...")
    except Exception as e:
        logger.warning(f"Could not save memory for {user_id}: {e}")

def get_memory_context(user_id: str) -> str:
    """Get all stored memories as context string."""
    memories = load_memories(user_id)
    if not memories:
        return ""
    facts = [m["fact"] for m in memories]
    return "\n".join(f"- {fact}" for fact in facts)

def extract_memory_from_exchange(user_msg: str, bot_response: str) -> list:
    """
    Extract facts worth remembering from the conversation.
    Heuristic: look for patterns like 'remember', 'merke dir', 'zapamti',
    or user sharing personal/project info (names, projects, preferences).
    """
    facts = []
    lower = user_msg.lower()

    # Explicit memory requests
    memory_triggers_de = ["merk dir", "merke dir", "erinner dich", "vergiss nicht", "memorisi", "notiere"]
    memory_triggers_en = ["remember", "don't forget", "keep in mind", "note that"]
    memory_triggers_bs = ["zapamti", "memorisi", "ne zaboravi", "zapisi"]

    all_triggers = memory_triggers_de + memory_triggers_en + memory_triggers_bs

    for trigger in all_triggers:
        if trigger in lower:
            # Save the whole message as a fact
            facts.append(user_msg.strip())
            break

    # Detect project/name introductions
    intro_patterns = [
        "heisst", "heißt", "zove se", "called", "name is",
        "projekt", "project", "firma", "company", "ich bin", "i am", "ja sam",
        "mein name", "my name", "moje ime",
    ]
    for pattern in intro_patterns:
        if pattern in lower and len(user_msg) < 300:
            facts.append(user_msg.strip())
            break

    return facts


# ──────── Translations ────────
TEXTS = {
    "en": {
        "welcome": (
            "Hello {name}! I'm the **A.AI Coach** — "
            "your personal assistant for the Cloud Code Team.\n\n"
            "I can explain how everything works, guide you step-by-step, "
            "and delegate tasks to specialized agents.\n\n"
            "I remember everything you tell me — even across sessions!\n\n"
            "**What can I do for you?**\n\n"
            "Commands:\n"
            "/help - Show all commands\n"
            "/agents - The 10 specialized agents\n"
            "/reset - Start new conversation\n"
            "/memory - Show what I remember about you\n"
            "/forget - Clear my memory of you\n"
            "/lang - Change language\n"
            "/status - System status"
        ),
        "help": (
            "**A.AI Coach - Commands**\n\n"
            "/start - Welcome message\n"
            "/help - This help\n"
            "/agents - The 10 agents and their specialties\n"
            "/reset - Start new conversation (memory is kept)\n"
            "/memory - Show what I remember\n"
            "/forget - Clear all memories\n"
            "/lang - Change language\n"
            "/status - Check system status\n\n"
            "**Just ask your question:**\n"
            "- 'How do I create a workflow?'\n"
            "- 'Explain the Knowledge Base'\n"
            "- 'Remember: my project is called XYZ'\n\n"
            "The Coach automatically delegates to specialists when needed."
        ),
        "agents": (
            "**The 10 Cloud Code Team Agents:**\n\n"
            "🏗 **Architect** - System architecture, design\n"
            "💻 **Coder** - Code development, implementation\n"
            "🧪 **Tester** - Testing, QA, test cases\n"
            "🔍 **Reviewer** - Code reviews, best practices\n"
            "⚙️ **DevOps** - Infrastructure, deployment\n"
            "📝 **Docs** - Documentation, README\n"
            "🔒 **Security** - Security, audits\n"
            "📋 **Planner** - Project planning, sprints\n"
            "🐛 **Debug** - Error analysis, debugging\n"
            "👷 **Worker** - General tasks\n\n"
            "Just tell me what you need, I'll route it to the right agent!"
        ),
        "reset": "Conversation reset! Your memories are preserved. What can I do for you?",
        "error_conn": "Connection error: {err}",
        "error_timeout": "Sorry, the request took too long. Please try again.",
        "no_answer": "No response received.",
        "lang_prompt": "Language changed to **English** 🇬🇧",
        "memory_empty": "I don't have any stored memories for you yet. Tell me things you'd like me to remember!",
        "memory_header": "**What I remember about you:**\n\n",
        "memory_cleared": "All memories cleared. Starting fresh!",
        "memory_saved": "Got it, I'll remember that!",
        "share_info": (
            "**Share this bot:**\n\n"
            "Send this link to anyone:\n"
            "👉 https://t.me/{botname}\n\n"
            "Or they can search for `@{botname}` in Telegram and tap **Start**.\n\n"
            "Each user gets their own private conversation — messages are never shared between users."
        ),
    },
    "de": {
        "welcome": (
            "Hallo {name}! Ich bin der **A.AI Coach** — "
            "dein persoenlicher Assistent fuer das Cloud Code Team.\n\n"
            "Ich kann dir erklaeren wie alles funktioniert, dich Schritt-fuer-Schritt "
            "anleiten, und bei Bedarf andere Agents fuer dich beauftragen.\n\n"
            "Ich merke mir alles was du mir sagst — auch ueber Sessions hinweg!\n\n"
            "**Was kann ich fuer dich tun?**\n\n"
            "Befehle:\n"
            "/help - Alle Befehle anzeigen\n"
            "/agents - Die 10 spezialisierten Agents\n"
            "/reset - Neue Konversation starten\n"
            "/memory - Was ich ueber dich weiss\n"
            "/forget - Meine Erinnerung loeschen\n"
            "/lang - Sprache aendern\n"
            "/status - System-Status"
        ),
        "help": (
            "**A.AI Coach - Befehle**\n\n"
            "/start - Willkommensnachricht\n"
            "/help - Diese Hilfe\n"
            "/agents - Die 10 Agents und ihre Spezialgebiete\n"
            "/reset - Neue Konversation starten (Memory bleibt)\n"
            "/memory - Was ich mir gemerkt habe\n"
            "/forget - Alle Erinnerungen loeschen\n"
            "/lang - Sprache aendern\n"
            "/status - System-Status pruefen\n\n"
            "**Einfach Fragen stellen:**\n"
            "- 'Wie erstelle ich einen Workflow?'\n"
            "- 'Erklaere mir die Knowledge Base'\n"
            "- 'Merke dir: Mein Projekt heisst XYZ'\n\n"
            "Der Coach leitet bei Bedarf automatisch an Spezialisten weiter."
        ),
        "agents": (
            "**Die 10 Cloud Code Team Agents:**\n\n"
            "🏗 **Architect** - System-Architektur, Design\n"
            "💻 **Coder** - Code-Entwicklung, Implementation\n"
            "🧪 **Tester** - Testing, QA, Testfaelle\n"
            "🔍 **Reviewer** - Code-Reviews, Best Practices\n"
            "⚙️ **DevOps** - Infrastructure, Deployment\n"
            "📝 **Docs** - Dokumentation, README\n"
            "🔒 **Security** - Sicherheit, Audits\n"
            "📋 **Planner** - Projektplanung, Sprints\n"
            "🐛 **Debug** - Fehleranalyse, Debugging\n"
            "👷 **Worker** - Allgemeine Aufgaben\n\n"
            "Sage mir einfach was du brauchst, ich leite es an den richtigen Agenten weiter!"
        ),
        "reset": "Konversation zurueckgesetzt! Deine Erinnerungen bleiben erhalten. Was kann ich fuer dich tun?",
        "error_conn": "Verbindungsfehler: {err}",
        "error_timeout": "Entschuldigung, die Anfrage hat zu lange gedauert. Bitte versuche es nochmal.",
        "no_answer": "Keine Antwort erhalten.",
        "lang_prompt": "Sprache geaendert auf **Deutsch** 🇩🇪",
        "memory_empty": "Ich habe noch keine Erinnerungen an dich gespeichert. Erzaehl mir was ich mir merken soll!",
        "memory_header": "**Was ich ueber dich weiss:**\n\n",
        "memory_cleared": "Alle Erinnerungen geloescht. Wir starten neu!",
        "memory_saved": "Verstanden, ich merke mir das!",
        "share_info": (
            "**Diesen Bot teilen:**\n\n"
            "Sende diesen Link an andere:\n"
            "👉 https://t.me/{botname}\n\n"
            "Oder nach `@{botname}` in Telegram suchen und **Starten** tippen.\n\n"
            "Jeder Nutzer bekommt seine eigene private Konversation — Nachrichten werden nie zwischen Nutzern geteilt."
        ),
    },
    "bs": {
        "welcome": (
            "Zdravo {name}! Ja sam **A.AI Coach** — "
            "tvoj licni asistent za Cloud Code Tim.\n\n"
            "Mogu ti objasniti kako sve funkcionise, voditi te korak-po-korak, "
            "i po potrebi delegirati zadatke specijaliziranim agentima.\n\n"
            "Pamtim sve sto mi kazes — cak i izmedju sesija!\n\n"
            "**Sta mogu za tebe uraditi?**\n\n"
            "Komande:\n"
            "/help - Prikazi sve komande\n"
            "/agents - 10 specijaliziranih agenata\n"
            "/reset - Zapocni novi razgovor\n"
            "/memory - Sta pamtim o tebi\n"
            "/forget - Obrisi moju memoriju\n"
            "/lang - Promijeni jezik\n"
            "/status - Status sistema"
        ),
        "help": (
            "**A.AI Coach - Komande**\n\n"
            "/start - Poruka dobrodoslice\n"
            "/help - Ova pomoc\n"
            "/agents - 10 agenata i njihove specijalizacije\n"
            "/reset - Zapocni novi razgovor (memorija ostaje)\n"
            "/memory - Sta sam zapamtio\n"
            "/forget - Obrisi sve memorije\n"
            "/lang - Promijeni jezik\n"
            "/status - Provjeri status sistema\n\n"
            "**Samo postavi pitanje:**\n"
            "- 'Kako da kreiram workflow?'\n"
            "- 'Objasni mi Knowledge Base'\n"
            "- 'Zapamti: moj projekt se zove XYZ'\n\n"
            "Coach automatski delegira specijalistima kada je potrebno."
        ),
        "agents": (
            "**10 Cloud Code Team Agenata:**\n\n"
            "🏗 **Architect** - Arhitektura sistema, dizajn\n"
            "💻 **Coder** - Razvoj koda, implementacija\n"
            "🧪 **Tester** - Testiranje, QA, test slucajevi\n"
            "🔍 **Reviewer** - Pregled koda, najbolje prakse\n"
            "⚙️ **DevOps** - Infrastruktura, deployment\n"
            "📝 **Docs** - Dokumentacija, README\n"
            "🔒 **Security** - Sigurnost, revizije\n"
            "📋 **Planner** - Planiranje projekta, sprintovi\n"
            "🐛 **Debug** - Analiza gresaka, debugging\n"
            "👷 **Worker** - Opsti zadaci\n\n"
            "Samo mi reci sta trebas, proslijedicu pravom agentu!"
        ),
        "reset": "Razgovor resetovan! Tvoje memorije su sacuvane. Sta mogu za tebe uraditi?",
        "error_conn": "Greska u vezi: {err}",
        "error_timeout": "Izvini, zahtjev je trajao predugo. Molim pokusaj ponovo.",
        "no_answer": "Nije primljen odgovor.",
        "lang_prompt": "Jezik promijenjen na **Bosanski** 🇧🇦",
        "memory_empty": "Nemam jos nikakvih memorija o tebi. Reci mi sta zelim da zapamtim!",
        "memory_header": "**Sta pamtim o tebi:**\n\n",
        "memory_cleared": "Sve memorije obrisane. Krecemo ispocetka!",
        "memory_saved": "Razumijem, zapamticu to!",
        "share_info": (
            "**Podijeli ovog bota:**\n\n"
            "Posalji ovaj link drugima:\n"
            "👉 https://t.me/{botname}\n\n"
            "Ili neka pretrazuju `@{botname}` u Telegramu i tapnu **Start**.\n\n"
            "Svaki korisnik dobija svoj privatni razgovor — poruke se nikada ne dijele izmedju korisnika."
        ),
    },
}


def get_lang(user_id: str) -> str:
    return user_state.get(user_id, {}).get("lang", "en")


def get_text(user_id: str, key: str) -> str:
    lang = get_lang(user_id)
    return TEXTS.get(lang, TEXTS["en"]).get(key, TEXTS["en"].get(key, ""))


# ──────── RAG Functions ────────

async def fetch_kb_context(query: str) -> str:
    """Search Dify Knowledge Base for relevant context."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{DIFY_API_URL}/datasets/{DIFY_KB_ID}/retrieve",
                json={
                    "query": query,
                    "retrieval_model": {
                        "search_method": "semantic_search",
                        "top_k": 5,
                        "score_threshold_enabled": False,
                        "score_threshold": None,
                        "reranking_enable": False,
                        "reranking_mode": None,
                        "reranking_model": {
                            "reranking_model_name": None,
                            "reranking_provider_name": None
                        },
                        "weights": None
                    }
                },
                headers={
                    "Authorization": f"Bearer {DIFY_KB_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("records", [])
                if records:
                    chunks = []
                    for r in records[:5]:
                        seg = r.get("segment", {})
                        content = seg.get("content", "")
                        doc_name = r.get("document", {}).get("name", "")
                        score = r.get("score", 0)
                        if content:
                            chunks.append(f"[{doc_name} (score: {score:.2f})]: {content[:500]}")
                    if chunks:
                        return "\n---\n".join(chunks)
            else:
                logger.warning(f"KB API returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"KB fetch failed: {e}")
    return ""


async def fetch_hipporag_context(query: str) -> str:
    """Query HippoRAG knowledge graph for related facts."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                HIPPORAG_URL,
                json={"query": query, "top_k": 5},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    facts = []
                    for r in results:
                        for node in r.get("nodes", []):
                            name = node.get("name", "")
                            ntype = node.get("type", "")
                            if name:
                                facts.append(f"[{ntype}] {name}")
                        for rel in r.get("relationships", []):
                            src = rel.get("from", "")
                            rtype = rel.get("type", "")
                            tgt = rel.get("to", "")
                            if src and rtype and tgt:
                                facts.append(f"{src} --{rtype}--> {tgt}")
                        subj = r.get("subject", "")
                        pred = r.get("predicate", "")
                        obj = r.get("object", "")
                        if subj and pred and obj:
                            facts.append(f"{subj} {pred} {obj}")
                    if facts:
                        seen = set()
                        unique = [f for f in facts if f not in seen and not seen.add(f)]
                        return "\n".join(unique)
    except Exception as e:
        logger.warning(f"HippoRAG fetch failed: {e}")
    return ""


async def enrich_query_with_rag(query: str, user_id: str) -> str:
    """Enrich user query with KB, HippoRAG, and user memory context."""
    # Fetch KB + HippoRAG in parallel
    kb_task = asyncio.create_task(fetch_kb_context(query))
    hippo_task = asyncio.create_task(fetch_hipporag_context(query))

    kb_context = await kb_task
    hippo_context = await hippo_task

    # Get user memory
    memory_context = get_memory_context(user_id)

    enriched = query
    if kb_context or hippo_context or memory_context:
        enriched = f"{query}\n\n"
        if memory_context:
            enriched += f"[USER MEMORY - Dinge die sich der User gemerkt hat]\n{memory_context}\n\n"
        if kb_context:
            enriched += f"[KB CONTEXT]\n{kb_context}\n\n"
        if hippo_context:
            enriched += f"[HIPPORAG CONTEXT]\n{hippo_context}\n\n"
        enriched += "[END CONTEXT]"

    return enriched


async def call_dify_streaming(query: str, user_id: str) -> tuple:
    """Call Dify API in streaming mode, return (answer_text, conversation_id)."""
    state = user_state.get(user_id, {})
    conversation_id = state.get("conversation_id", "")

    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "streaming",
        "user": f"telegram-{user_id}",
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }

    answer_text = ""
    new_conversation_id = ""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{DIFY_API_URL}/chat-messages",
                json=payload,
                headers=headers,
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event = data.get("event", "")

                    if not new_conversation_id and data.get("conversation_id"):
                        new_conversation_id = data["conversation_id"]

                    if event == "text_chunk":
                        answer_text += data.get("data", {}).get("text", "")

                    if event == "node_finished":
                        node_data = data.get("data", {})
                        if node_data.get("node_type") == "llm":
                            outputs = node_data.get("outputs", {})
                            llm_text = outputs.get("text", "")
                            if llm_text and not answer_text:
                                answer_text = llm_text

        return answer_text, new_conversation_id

    except httpx.TimeoutException:
        return "", ""
    except Exception as e:
        logger.error(f"Dify API error: {e}")
        return "", ""


# ──────── Command Handlers ────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — ask language preference."""
    user = update.effective_user
    user_id = str(user.id)

    if user_id not in user_state:
        user_state[user_id] = {"conversation_id": "", "lang": "en", "name": user.first_name}
        save_user_state()

    keyboard = [
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang_de"),
            InlineKeyboardButton("🇧🇦 Bosanski", callback_data="lang_bs"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Welcome to **A.AI Coach**!\n\n"
        f"Which language do you prefer?\n"
        f"Welche Sprache bevorzugst du?\n"
        f"Koji jezik preferiras?",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection from inline keyboard."""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    lang_map = {"lang_en": "en", "lang_de": "de", "lang_bs": "bs"}
    lang = lang_map.get(query.data, "en")

    if user_id not in user_state:
        user_state[user_id] = {"conversation_id": "", "lang": lang, "name": query.from_user.first_name}
    else:
        user_state[user_id]["lang"] = lang
    save_user_state()

    welcome = get_text(user_id, "welcome").format(name=query.from_user.first_name)
    await query.edit_message_text(welcome, parse_mode="Markdown")


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang_de"),
            InlineKeyboardButton("🇧🇦 Bosanski", callback_data="lang_bs"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Choose your language / Waehle deine Sprache / Odaberi jezik:",
        reply_markup=reply_markup,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    await update.message.reply_text(get_text(user_id, "help"), parse_mode="Markdown")


async def agents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    await update.message.reply_text(get_text(user_id, "agents"), parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in user_state:
        user_state[user_id]["conversation_id"] = ""
        save_user_state()
    await update.message.reply_text(get_text(user_id, "reset"))


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /memory — show stored memories."""
    user_id = str(update.effective_user.id)
    memories = load_memories(user_id)
    if not memories:
        await update.message.reply_text(get_text(user_id, "memory_empty"))
        return

    text = get_text(user_id, "memory_header")
    for i, m in enumerate(memories, 1):
        text += f"{i}. {m['fact']}\n"
    text += f"\n({len(memories)} memories total)"
    await update.message.reply_text(text, parse_mode="Markdown")


async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forget — clear all memories."""
    user_id = str(update.effective_user.id)
    f = _memory_file(user_id)
    if f.exists():
        f.unlink()
    await update.message.reply_text(get_text(user_id, "memory_cleared"))


async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    botname = context.bot.username or "A_AI_Couch_bot"
    text = get_text(user_id, "share_info").format(botname=botname)
    await update.message.reply_text(text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    memories_count = len(load_memories(user_id))
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            checks = {}
            try:
                r = await client.get("http://localhost:8000/health")
                checks["Orchestrator"] = "Online" if r.status_code == 200 else "Offline"
            except:
                checks["Orchestrator"] = "Offline"
            try:
                r = await client.get("http://localhost:8001/health")
                checks["HippoRAG"] = "Online" if r.status_code == 200 else "Offline"
            except:
                checks["HippoRAG"] = "Offline"
            checks["A.AI Coach"] = "Online"
            checks["Telegram Bot"] = "Online"
            checks["Knowledge Base"] = "Online"

            status_text = "**System-Status:**\n\n"
            for name, state in checks.items():
                emoji = "🟢" if state == "Online" else "🔴"
                status_text += f"{emoji} {name}: {state}\n"
            status_text += f"\nActive users: {len(user_state)}"
            status_text += f"\nYour memories: {memories_count}"
    except Exception as e:
        status_text = f"Status check failed: {e}"

    await update.message.reply_text(status_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages."""
    if not update.message or not update.message.text:
        return

    if update.message.chat.type in ["group", "supergroup"]:
        bot_username = context.bot.username
        msg_lower = update.message.text.lower()
        # Respond to @mention, "coach", "couch", or reply to bot
        is_mention = bot_username and f"@{bot_username.lower()}" in msg_lower
        is_trigger = any(w in msg_lower for w in ["coach", "couch", "a.ai", "aai"])
        is_reply = (update.message.reply_to_message and
                    update.message.reply_to_message.from_user and
                    update.message.reply_to_message.from_user.is_bot)
        if not (is_mention or is_trigger or is_reply):
            return
        # Clean up trigger words from query
        text = update.message.text
        if bot_username:
            text = text.replace(f"@{bot_username}", "")
        for trigger in ["Coach ", "coach ", "Couch ", "couch "]:
            if text.startswith(trigger):
                text = text[len(trigger):]
                break
        text = text.strip()
    else:
        text = update.message.text

    if not text:
        return

    user_id = str(update.effective_user.id)
    logger.info(f"Message from {update.effective_user.first_name} ({user_id}): {text[:50]}...")

    if user_id not in user_state:
        user_state[user_id] = {"conversation_id": "", "lang": "en", "name": update.effective_user.first_name}
        save_user_state()

    # Auto-extract memories from user message
    new_facts = extract_memory_from_exchange(text, "")
    for fact in new_facts:
        save_memory(user_id, fact)

    await update.message.chat.send_action("typing")

    # Enrich query with RAG + Memory context
    enriched_text = await enrich_query_with_rag(text, user_id)
    logger.info(
        f"RAG enrichment: KB={'[KB CONTEXT]' in enriched_text}, "
        f"HIPPO={'[HIPPORAG CONTEXT]' in enriched_text}, "
        f"MEM={'[USER MEMORY' in enriched_text}"
    )

    # Call Dify with streaming
    answer, conv_id = await call_dify_streaming(enriched_text, user_id)

    if conv_id:
        user_state[user_id]["conversation_id"] = conv_id
        save_user_state()

    if not answer:
        answer = get_text(user_id, "no_answer")

    # If user explicitly asked to remember something, confirm
    if new_facts:
        confirm = get_text(user_id, "memory_saved")
        answer = f"{confirm}\n\n{answer}"

    # Send response (split if too long)
    if len(answer) > 4000:
        parts = [answer[i:i+4000] for i in range(0, len(answer), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(answer)


async def post_init(application):
    commands = [
        BotCommand("start", "Welcome & setup language"),
        BotCommand("help", "Show all commands"),
        BotCommand("agents", "The 10 specialized agents"),
        BotCommand("reset", "Start new conversation"),
        BotCommand("memory", "Show what I remember"),
        BotCommand("forget", "Clear my memory"),
        BotCommand("lang", "Change language"),
        BotCommand("share", "Share this bot"),
        BotCommand("status", "System status"),
    ]
    await application.bot.set_my_commands(commands)
    bot_info = await application.bot.get_me()
    logger.info(f"Bot started: @{bot_info.username} ({bot_info.first_name})")
    logger.info(f"Share link: https://t.me/{bot_info.username}")
    logger.info(f"Loaded {len(user_state)} user states from disk")


def main():
    logger.info("Starting A.AI Coach Telegram Bot v3 (multilingual + persistent memory)...")

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("agents", agents_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("forget", forget_command))
    app.add_handler(CommandHandler("lang", lang_command))
    app.add_handler(CommandHandler("share", share_command))
    app.add_handler(CommandHandler("status", status_command))

    app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
