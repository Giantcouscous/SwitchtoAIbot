"""
SwitchToAI — Weekly Check-In Bot
=================================
Personality: Frank Slootman directness. Execution-obsessed. No fluff.
Mode: Conversational debrief — asks follow-up questions, pushes back,
      then delivers a sharp verdict with ticked checklist and next moves.

Flow:
  Tuesday 09:00 → bot sends text prompt
  You reply (voice note or text) → bot transcribes + asks follow-up
  3 exchanges → bot closes the debrief with full analysis
  Progress saved to Supabase (persistent across Railway restarts)

Outside debrief:
  Voice note or text "add X to week N" → adds task to Supabase milestones
"""

import os

import json
import logging
import asyncio
import re
from datetime import date

from anthropic import Anthropic
from openai import OpenAI
from supabase import create_client, Client
from telegram import Update, Bot
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
print("SUPABASE_URL repr:", repr(SUPABASE_URL)), flush=True)
print("HAS SUPABASE KEY:", bool(SUPABASE_KEY)), flush=True)
print("HAS TELEGRAM_BOT_TOKEN:", bool(os.getenv("TELEGRAM_BOT_TOKEN")), flush=True)
print("HAS TELEGRAM_CHAT_ID:", bool(os.getenv("TELEGRAM_CHAT_ID")), flush=True)
# ─── CONFIG ──────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
SUPABASE_URL       = os.environ["SUPABASE_URL"]
SUPABASE_KEY       = os.environ["SUPABASE_KEY"]


CHECKIN_HOUR   = 9
CHECKIN_MINUTE = 0
CHECKIN_DAY    = "tue"
TIMEZONE       = "Europe/London"
MAX_EXCHANGES  = 3

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ─── CLIENTS ─────────────────────────────────────────────────────────────────

claude   = Anthropic(api_key=ANTHROPIC_API_KEY)
whisper  = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── MILESTONES FALLBACK ─────────────────────────────────────────────────────

MILESTONES_FALLBACK = {
    1: {
        "title": "Foundation & Digital Presence",
        "tasks": [
            "Point switchtoai.ai domain to Cloudflare Pages or Netlify",
            "Deploy the landing page HTML",
            "Set up Tally.so form with 5 fields, connected to email",
            "Replace placeholder form on site with live Tally embed",
            "Set up hello@switchtoai.ai via Cloudflare Email Routing",
            "Set up transcription tool connected to Google Calendar",
            "Download and customise Gamma assessment template with SwitchToAI branding",
            "Draft intake question bank (15-20 questions)",
            "Set up Notion CRM: Name, Company, Industry, Status, Notes, Next Action",
        ]
    },
    2: {
        "title": "Build Question Bank & Claude Workflow",
        "tasks": [
            "Run a mock assessment on yourself and record with Fathom",
            "Run the Fathom transcript through Claude with the full prompt",
            "Review output quality and iterate prompt 3-5 times",
            "Refine prompt until report output is consistently good",
            "Upload Claude output to Gamma template and confirm clean formatting",
            "Create industry-specific question variants for estate agents, mortgage brokers, solicitors",
            "Write outreach email script for free assessment invitations",
            "Identify 5 network contacts who are business owners for free audits",
        ]
    },
    3: {
        "title": "First Free Assessments & Business Model Refinement",
        "tasks": [
            "Reach out to all 5 identified contacts offering free assessment",
            "Book and complete 2-3 free assessments",
            "Run each session on Zoom with built-in transcription (30-45 mins)",
            "Deliver each report within 48 hours",
            "Book and run 30-min follow-up call for each assessment",
            "Collect honest feedback from each client",
            "Collect at least 2 written testimonials",
            "Document all questions asked during follow-ups",
            "Set up Google Analytics 4 on switchtoai.ai and all industry pages",
            "Verify analytics is tracking form submissions and page views correctly",
            "Rewrite business plan reflecting updated model and target market",
            "Redesign homepage form — short entry: name, company, pain point only",
            "Build tool recommendation logic — pain point input triggers relevant off-the-shelf tool suggestion",
            "Add call booking option (Calendly) after tool recommendation for full assessment",
            "Test end-to-end new form flow before going live",
        ]
    },
    4: {
        "title": "Refine & Prepare to Charge",
        "tasks": [
            "Incorporate all Week 3 feedback into template, question bank, Claude prompt",
            "Add testimonials to landing page",
            "Define upsell menu with ONE primary upsell: Zapier automation at £1,500",
            "Practise the upsell conversation script",
            "Set up Calendly with Assessment Call and Follow-Up Call meeting types",
            "Add Calendly link to Tally form confirmation email",
            "Run 1 more free assessment with upsell conversation attempt",
            "Set price at £1,250 for first paying clients",
        ]
    },
    5: {
        "title": "First Paying Client",
        "tasks": [
            "Host local AI meetup OR approach 3-5 local businesses in person",
            "Attempt in-person approach at estate agent or mortgage broker offices",
            "Deliver the door-knocking opening line to at least 3 businesses",
            "Post a LinkedIn insight from one of the free assessments",
            "Follow up with all website form submissions",
            "Deliver first paid assessment at £1,250",
            "Present upsell opportunity with written one-page proposal",
        ]
    },
    6: {
        "title": "Scale Outreach & Land First Upsell",
        "tasks": [
            "Raise price to £1,500 per assessment",
            "Run 2-3 paid assessments this week",
            "Follow up on all Week 5 upsell conversations with written proposals",
            "Close first upsell project at £1,500+",
            "Implement referral ask after every positive follow-up call",
            "Set up Mailchimp and start building email list",
            "Send first email to list with AI insight or tip",
            "Review Notion CRM and follow up on all cold leads",
        ]
    },
    7: {
        "title": "Review, Double Down & Plan Month 2",
        "tasks": [
            "Run full numbers review: assessments, revenue, conversion rates",
            "Identify best lead source and plan to double down",
            "Identify process bottlenecks and optimise Claude prompts",
            "Set Month 2 targets: 4 paid assessments + 1 upsell = £5,500+",
            "Decide on primary upsell specialisation",
            "Decide whether to build Retell AI voice agent",
            "Post anonymised case study on LinkedIn with specific numbers",
            "Set recurring weekly habit: 3 outreach Monday + follow-ups Friday",
        ]
    },
}

# ─── MILESTONES ──────────────────────────────────────────────────────────────

def load_milestones() -> dict:
    try:
        res = supabase.table("bot_milestones").select("*").order("week").execute()
        if res.data:
            milestones = {}
            for row in res.data:
                milestones[row["week"]] = {
                    "title": row["title"],
                    "tasks": row["tasks"] if isinstance(row["tasks"], list) else json.loads(row["tasks"])
                }
            log.info(f"Loaded {len(milestones)} weeks from Supabase milestones")
            return milestones
    except Exception as e:
        log.warning(f"Could not load milestones from Supabase, using fallback: {e}")
    return MILESTONES_FALLBACK

def get_milestones() -> dict:
    if not hasattr(get_milestones, "_cache"):
        get_milestones._cache = load_milestones()
    return get_milestones._cache

def invalidate_milestones_cache():
    if hasattr(get_milestones, "_cache"):
        del get_milestones._cache

def add_task_to_week(week: int, task: str) -> bool:
    try:
        res = supabase.table("bot_milestones").select("tasks").eq("week", week).execute()
        if not res.data:
            log.error(f"Week {week} not found in bot_milestones")
            return False
        current_tasks = res.data[0]["tasks"]
        if isinstance(current_tasks, str):
            current_tasks = json.loads(current_tasks)
        current_tasks.append(task)
        supabase.table("bot_milestones").update({"tasks": current_tasks}).eq("week", week).execute()
        invalidate_milestones_cache()
        log.info(f"Added task to Week {week}: {task}")
        return True
    except Exception as e:
        log.error(f"add_task_to_week error: {e}")
        return False

# ─── SYSTEM PROMPTS ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are JARVIS — the AI advisor for SwitchToAI, a UK-based AI consulting business targeting estate agents, mortgage brokers, and solicitors.

Your personality is a precise blend:
- VOICE & TONE: JARVIS from Iron Man. Measured. Composed. Slightly formal but never stiff. Dry wit when appropriate. Never cheerful, never sycophantic. Economy of words.
- ADVISORY STYLE: Frank Slootman. Blunt. Execution-obsessed. Zero tolerance for excuses or vagueness. You do not celebrate effort — you measure outcomes. You push hard on "what specifically did you do" not "how did you feel about the week". When something is good, you acknowledge it briefly and move on. When something is missing, you call it out directly.
- COMBINED: Think JARVIS running diagnostics on a business. Clinical, sharp, occasionally wry, always pushing toward execution.

Example exchanges:
User: "I've been working on the website but it's not quite ready"
You: "Not quite ready isn't a status. Is it live or isn't it? What specifically is blocking deployment?"

User: "I reached out to a few people"
You: "How many. Did they respond."

User: "I did the mock assessment and it went well"
You: "Define well. Did the Claude output require iteration? How many prompts before the report was usable?"

Rules:
1. NEVER use filler phrases: "Great!", "Awesome!", "That's fantastic", "Well done", "I understand"
2. NEVER be vague. Ask for specifics when the user is vague.
3. Keep responses SHORT during the conversation phase — 2-4 sentences maximum per exchange
4. Only give the full analysis verdict when explicitly told to (FINAL_VERDICT instruction)
5. During conversation: ask ONE focused follow-up question per exchange
6. You have memory of previous weeks — reference them when relevant
7. Occasional dry humour is permitted. Warmth is not."""

TASK_DETECTION_PROMPT = """You analyse text or a voice note transcript to detect if the user wants to add a task to their weekly plan.

If it IS a task addition request, extract:
1. The week number (1-7)
2. The clean task text (concise action item, starts with a verb, max 15 words)

Return ONLY valid JSON — no markdown, no explanation, nothing else.

Format if IS a task:
{"is_task": true, "week": 3, "task": "Follow up with Guillaume about testimonial"}

Format if NOT a task:
{"is_task": false}

Examples:
"add to week 3 follow up with Guillaume about his testimonial" → {"is_task": true, "week": 3, "task": "Follow up with Guillaume about testimonial"}
"add set up Google Analytics to week 3" → {"is_task": true, "week": 3, "task": "Set up Google Analytics"}
"week 2 add task test the Claude prompt" → {"is_task": true, "week": 2, "task": "Test the Claude prompt output quality"}
"yeah I managed to get the website live" → {"is_task": false}
"I haven't done the CRM yet" → {"is_task": false}"""

# ─── SUPABASE ────────────────────────────────────────────────────────────────

def _db_get(table: str, key: str) -> dict:
    try:
        res = supabase.table(table).select("value").eq("key", key).execute()
        if res.data:
            return res.data[0]["value"]
    except Exception as e:
        log.error(f"Supabase get error ({table}/{key}): {e}")
    return {}

def _db_set(table: str, key: str, value: dict):
    try:
        supabase.table(table).upsert({"key": key, "value": value}).execute()
    except Exception as e:
        log.error(f"Supabase set error ({table}/{key}): {e}")

def load_conv() -> dict:
    try:
        data = _db_get("bot_conv", "state")
        if data and isinstance(data, dict) and "active" in data:
            return data
    except Exception as e:
        log.error(f"load_conv error: {e}")
    return {"active": False, "exchanges": [], "exchange_count": 0, "week": 1}

def save_conv(state: dict):
    _db_set("bot_conv", "state", state)

def clear_conv():
    save_conv({"active": False, "exchanges": [], "exchange_count": 0, "week": 1})

def load_progress() -> dict:
    try:
        data = _db_get("bot_progress", "progress")
        if data and isinstance(data, dict):
            return data
    except Exception as e:
        log.error(f"load_progress error: {e}")
    return {}

def save_progress(data: dict):
    _db_set("bot_progress", "progress", data)

def current_week() -> int:
    p = load_progress()
    if "start_date" not in p:
        return 1
    start = date.fromisoformat(p["start_date"])
    delta = (date.today() - start).days
    return min(max(1, delta // 7 + 1), 7)

# ─── WHISPER ────────────────────────────────────────────────────────────────

async def transcribe_voice(file_path: str) -> str:
    log.info("Transcribing with Whisper...")
    with open(file_path, "rb") as f:
        result = whisper.audio.transcriptions.create(
            model="whisper-1", file=f, language="en"
        )
    return result.text

# ─── TASK DETECTION ──────────────────────────────────────────────────────────

def detect_task_addition(text: str) -> dict:
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=150,
            system=TASK_DETECTION_PROMPT,
            messages=[{"role": "user", "content": text}]
        )
        raw = response.content[0].text.strip()
        # Strip any accidental markdown
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"detect_task_addition error: {e}")
        return {"is_task": False}

async def handle_task_addition(text: str, update: Update):
    """Shared logic for adding a task from voice or text."""
    detection = detect_task_addition(text)
    log.info(f"Task detection result: {detection}")

    if detection.get("is_task") and detection.get("week") and detection.get("task"):
        week = int(detection["week"])
        task = detection["task"]
        milestones = get_milestones()

        if week not in milestones:
            await update.message.reply_text(
                f"_Week {week} doesn't exist. Valid weeks are 1-7._",
                parse_mode="Markdown"
            )
            return True

        success = add_task_to_week(week, task)
        if success:
            await update.message.reply_text(
                f"✅ *Added to Week {week}*\n\n_{task}_",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "_Failed to add task. Try again._",
                parse_mode="Markdown"
            )
        return True

    return False  # Not a task addition

# ─── CLAUDE CONVERSATION ─────────────────────────────────────────────────────

def build_context(week: int, exchanges: list, progress: dict) -> list:
    milestones = get_milestones()
    checklist = milestones.get(week, {"title": f"Week {week}", "tasks": []})
    tasks_str = "\n".join(f"- {t}" for t in checklist["tasks"])

    history_str = ""
    for w in range(1, week):
        wk = str(w)
        if wk in progress.get("weeks", {}):
            e = progress["weeks"][wk]
            week_title = milestones.get(w, {}).get("title", f"Week {w}")
            history_str += f"\nWeek {w} ({week_title}): {e['ticked_count']}/{e['total_tasks']} tasks completed."
            if e.get("missed"):
                history_str += f" Outstanding: {', '.join(e['missed'][:3])}"

    context_msg = (
        f"CONTEXT: Week {week} of 7 — {checklist['title']}\n\n"
        f"THIS WEEK'S CHECKLIST:\n{tasks_str}\n"
        f"{f'PREVIOUS WEEKS HISTORY:{history_str}' if history_str else ''}\n\n"
        "Begin the debrief. Ask for their update."
    )

    messages = [{"role": "user", "content": context_msg}]
    messages.extend(exchanges)
    return messages

def get_conversation_reply(week: int, exchanges: list, progress: dict) -> str:
    messages = build_context(week, exchanges, progress)
    response = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text

def get_final_verdict(week: int, exchanges: list, progress: dict) -> str:
    milestones = get_milestones()
    messages = build_context(week, exchanges, progress)
    checklist_tasks = "\n".join(f"- {t}" for t in milestones.get(week, {}).get("tasks", []))

    messages.append({
        "role": "user",
        "content": (
            "FINAL_VERDICT: Based on everything discussed, produce a full debrief report.\n\n"
            "Format for Telegram (use emoji):\n\n"
            "✅ COMPLETED THIS WEEK\n"
            "[tick each completed task with ✅]\n\n"
            "⬜ STILL OUTSTANDING\n"
            "[list each incomplete task with ⬜]\n\n"
            "📊 WHERE YOU STAND\n"
            "[2-3 sentences. Honest. No fluff.]\n\n"
            "🎯 YOUR NEXT MOVES\n"
            "[3-5 numbered actions. Specific. No generalities.]\n\n"
            "⚡ WEEK RATING\n"
            "[X/10 — one sentence justification. Be direct.]\n\n"
            "💡 ONE LINE\n"
            "[The single sharpest thing you can say about this week.]\n\n"
            f"Checklist for reference:\n{checklist_tasks}"
        )
    })

    response = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text

def save_week_progress(week: int, text_report: str, progress: dict) -> dict:
    milestones = get_milestones()
    ticked, missed = [], []
    tasks = milestones.get(week, {}).get("tasks", [])
    report_lower = text_report.lower()

    for task in tasks:
        task_words = task.lower().split()[:4]
        key = " ".join(task_words)
        if "✅" in text_report and key in report_lower:
            ticked.append(task)
        elif "⬜" in text_report and key in report_lower:
            missed.append(task)

    if "weeks" not in progress:
        progress["weeks"] = {}

    progress["weeks"][str(week)] = {
        "date": date.today().isoformat(),
        "ticked": ticked,
        "missed": missed,
        "ticked_count": text_report.count("✅"),
        "total_tasks": len(tasks),
        "missed_count": text_report.count("⬜"),
    }
    save_progress(progress)
    return progress

# ─── CONVERSATION HANDLER ────────────────────────────────────────────────────

async def process_user_input(user_text: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    conv = load_conv()
    progress = load_progress()

    if not conv["active"]:
        await update.message.reply_text(
            "_No active debrief. Send /checkin to start your weekly review._\n"
            "_Or say \"add [task] to week [N]\" to add a task._",
            parse_mode="Markdown"
        )
        return

    week = conv["week"]
    milestones = get_milestones()

    conv["exchanges"].append({"role": "user", "content": user_text})
    conv["exchange_count"] += 1

    if conv["exchange_count"] >= MAX_EXCHANGES:
        await update.message.reply_text("_Compiling your debrief..._", parse_mode="Markdown")
        text_report = get_final_verdict(week, conv["exchanges"], progress)
        header = f"📋 *Week {week} Debrief — {milestones.get(week, {}).get('title', '')}*\n\n"
        await update.message.reply_text(header + text_report, parse_mode="Markdown")
        save_week_progress(week, text_report, progress)
        clear_conv()
    else:
        reply = get_conversation_reply(week, conv["exchanges"], progress)
        conv["exchanges"].append({"role": "assistant", "content": reply})
        save_conv(conv)
        await update.message.reply_text(reply, parse_mode="Markdown")

# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return

    log.info("Voice note received")
    await update.message.reply_text("_Transcribing..._", parse_mode="Markdown")

    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)
        file_path = f"/tmp/voice_{voice.file_id}.ogg"
        await voice_file.download_to_drive(custom_path=file_path)
        log.info("Download complete")

        transcript = await transcribe_voice(file_path)
        log.info(f"Transcript: {transcript[:100]}...")

        conv = load_conv()
        if conv["active"]:
            await process_user_input(transcript, update, context)
        else:
            handled = await handle_task_addition(transcript, update)
            if not handled:
                await update.message.reply_text(
                    "_No active debrief. Send /checkin to start._\n"
                    "_Or say \"add [task] to week [N]\" to add a task._",
                    parse_mode="Markdown"
                )

    except Exception as e:
        log.error(f"Voice error: {type(e).__name__}: {e}")
        await update.message.reply_text(
            f"_Error: {type(e).__name__}: {str(e)}_",
            parse_mode="Markdown"
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return

    text = update.message.text.strip()
    conv = load_conv()

    if conv["active"]:
        await process_user_input(text, update, context)
    else:
        handled = await handle_task_addition(text, update)
        if not handled:
            await update.message.reply_text(
                "_No active debrief. Send /checkin to start._\n"
                "_Or say \"add [task] to week [N]\" to add a task._",
                parse_mode="Markdown"
            )

async def send_checkin_prompt(bot: Bot):
    week = current_week()
    milestones = get_milestones()
    title = milestones.get(week, {}).get("title", f"Week {week}")

    save_conv({"active": True, "exchanges": [], "exchange_count": 0, "week": week})

    progress = load_progress()
    weeks_done = len(progress.get("weeks", {}))

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            f"📅 *Week {week} Debrief — {title}*\n"
            f"_{weeks_done} week{'s' if weeks_done != 1 else ''} on record._\n\n"
            f"Week {week}. {title}. "
            "Walk me through the week. What moved, what didn't. Be specific.\n\n"
            f"Send a voice note or type. {MAX_EXCHANGES} exchanges, then the full verdict."
        ),
        parse_mode="Markdown"
    )
    log.info(f"Week {week} debrief started")

# ─── COMMANDS ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = load_progress()
    if "start_date" not in p:
        p["start_date"] = date.today().isoformat()
        save_progress(p)
        msg = (
            "✅ *SwitchToAI Check-In Bot initialised.*\n\n"
            f"Start date: *{p['start_date']}*\n"
            "Weekly debrief: every Tuesday at 09:00 London time.\n\n"
            f"After {MAX_EXCHANGES} exchanges you get the full verdict.\n\n"
            "*/checkin* — start a manual debrief\n"
            "*/status* — progress bars\n"
            "*/progress* — full history\n"
            "*/showtasks 3* — show tasks for a week\n"
            "*/cancel* — end current debrief\n\n"
            "_Outside a debrief: say or type \"add [task] to week [N]\"_"
        )
    else:
        msg = f"Already running. Week {current_week()}. Use /checkin to debrief now."
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return
    await send_checkin_prompt(context.bot)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_conv()
    await update.message.reply_text("_Debrief cancelled._", parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = load_progress()
    week = current_week()
    lines = [f"📊 *Status — Week {week} of 7*\n"]
    for w in range(1, week + 1):
        wk = str(w)
        if wk in p.get("weeks", {}):
            done  = p["weeks"][wk]["ticked_count"]
            total = p["weeks"][wk]["total_tasks"]
            bar   = "█" * done + "░" * (total - done)
            lines.append(f"Week {w}: {bar} {done}/{total}")
        else:
            lines.append(f"Week {w}: No debrief on record")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = load_progress()
    milestones = get_milestones()
    weeks_data = p.get("weeks", {})
    if not weeks_data:
        await update.message.reply_text("No debriefs on record yet.")
        return
    lines = ["📚 *Full Debrief History*\n"]
    for w in sorted(weeks_data.keys(), key=int):
        e = weeks_data[w]
        title = milestones.get(int(w), {}).get("title", f"Week {w}")
        lines.append(f"*Week {w} — {title}*")
        lines.append(f"Date: {e.get('date', '—')}  |  {e['ticked_count']}/{e['total_tasks']} tasks")
        if e.get("missed"):
            preview = ', '.join(e['missed'][:2])
            lines.append(f"Outstanding: {preview}{'...' if len(e['missed']) > 2 else ''}")
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_showtasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info(f"CMD_SHOWTASKS TRIGGERED — chat: {update.effective_chat.id} — text: {update.message.text}")
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return

    log.info(f"cmd_showtasks called — args: {context.args} — text: {update.message.text}")

    # Parse week number — try context.args first, then parse from message text
    week_num = None

    if context.args:
        for arg in context.args:
            if arg.isdigit():
                week_num = int(arg)
                break

    if not week_num:
        # Fallback: extract number from raw message text e.g. "/showtasks 3"
        match = re.search(r'\d+', update.message.text)
        if match:
            week_num = int(match.group())

    milestones = get_milestones()

    if not week_num:
        # No number — show all weeks summary
        lines = ["📋 *All Weeks*\n"]
        for w in sorted(milestones.keys()):
            data = milestones[w]
            lines.append(f"*Week {w}* — {data['title']} ({len(data['tasks'])} tasks)")
        lines.append("\n_Use /showtasks 3 to see a specific week_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    if week_num not in milestones:
        await update.message.reply_text(
            f"_Week {week_num} not found. Valid weeks: 1-7._",
            parse_mode="Markdown"
        )
        return

    data = milestones[week_num]
    lines = [f"📋 *Week {week_num} — {data['title']}*\n"]
    for i, task in enumerate(data["tasks"], 1):
        lines.append(f"{i}. {task}")
    lines.append(f"\n_{len(data['tasks'])} tasks total_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ─── MAIN ────────────────────────────────────────────────────────────────────

async def main():
    # Kill any existing bot session before starting
    temp_bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await temp_bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(3)

    await asyncio.sleep(8)
    log.info("JARVIS initialising...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands must be registered before the text catch-all
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("checkin",   cmd_checkin))
    app.add_handler(CommandHandler("cancel",    cmd_cancel))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("progress",  cmd_progress))
    app.add_handler(CommandHandler("showtasks", cmd_showtasks))


    # Media and text — text handler uses ~filters.COMMAND to avoid intercepting commands
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_checkin_prompt,
        CronTrigger(day_of_week=CHECKIN_DAY, hour=CHECKIN_HOUR, minute=CHECKIN_MINUTE),
        args=[app.bot],
        id="weekly_debrief"
    )
    scheduler.start()
    log.info(f"Scheduled: every {CHECKIN_DAY.capitalize()} at {CHECKIN_HOUR:02d}:{CHECKIN_MINUTE:02d} {TIMEZONE}")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
    )

    log.info("JARVIS online.")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")
    finally:
        scheduler.shutdown()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
