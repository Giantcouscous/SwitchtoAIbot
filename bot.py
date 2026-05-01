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
  Progress saved to progress.json for cumulative context

Setup: See SETUP.md
"""

import os
import json
import logging
import asyncio
from datetime import date
from pathlib import Path

from anthropic import Anthropic
from openai import OpenAI
from telegram import Update, Bot
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ─── CONFIG ──────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]

CHECKIN_HOUR   = 9
CHECKIN_MINUTE = 0
CHECKIN_DAY    = "Tue"
TIMEZONE       = "Europe/London"

# How many back-and-forth exchanges before the final verdict
MAX_EXCHANGES  = 3

PROGRESS_FILE    = Path("progress.json")
CONV_STATE_FILE  = Path("conversation_state.json")
VOICE_INPUT_PATH = "/tmp/user_voice.ogg"

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ─── CLIENTS ─────────────────────────────────────────────────────────────────

claude  = Anthropic(api_key=ANTHROPIC_API_KEY)
whisper = OpenAI(api_key=OPENAI_API_KEY)

# ─── 7-WEEK CHECKLIST ────────────────────────────────────────────────────────

MILESTONES = {
    1: {
        "title": "Foundation & Digital Presence",
        "tasks": [
            "Point switchtoai.ai domain to Cloudflare Pages or Netlify",
            "Deploy the landing page HTML",
            "Set up Tally.so form with 5 fields, connected to email",
            "Replace placeholder form on site with live Tally embed",
            "Set up ahmed@switchtoai.ai on Zoho Mail free plan",
            "Set up Fathom.ai free account, connected to Google Calendar",
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
        "title": "First Free Assessments",
        "tasks": [
            "Reach out to all 5 identified contacts offering free assessment",
            "Book and complete 2-3 free assessments",
            "Run each session on Zoom with Fathom recording (30-45 mins)",
            "Deliver each report within 48 hours",
            "Book and run 30-min follow-up call for each assessment",
            "Collect honest feedback from each client",
            "Collect at least 2 written testimonials",
            "Document all questions asked during follow-ups",
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
            "Set price at £500 for first paying clients",
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
            "Deliver first paid assessment at £500",
            "Present upsell opportunity with written one-page proposal",
        ]
    },
    6: {
        "title": "Scale Outreach & Land First Upsell",
        "tasks": [
            "Raise price to £1,000 per assessment",
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
            "Decide whether to build Retell AI agent",
            "Post anonymised case study on LinkedIn with specific numbers",
            "Set recurring weekly habit: 3 outreach Monday + follow-ups Friday",
        ]
    },
}

# ─── SYSTEM PROMPT ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are JARVIS — the AI advisor for SwitchToAI, a UK-based AI consulting business targeting estate agents, mortgage brokers, and solicitors.

Your personality is a precise blend:
- & TONE: JARVIS from Iron Man. Measured. Composed. Slightly formal but never stiff. Dry wit when appropriate. Never cheerful, never sycophantic. Economy of words.
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
7. Occasional dry humour is permitted. Warmth is not.
8. When producing voice-ready text: no markdown, no bullet points, no symbols. Plain spoken sentences only."""

# ─── CONVERSATION STATE ───────────────────────────────────────────────────────

def load_conv() -> dict:
    if CONV_STATE_FILE.exists():
        return json.loads(CONV_STATE_FILE.read_text())
    return {"active": False, "exchanges": [], "exchange_count": 0, "week": 1}

def save_conv(state: dict):
    CONV_STATE_FILE.write_text(json.dumps(state, indent=2))

def clear_conv():
    save_conv({"active": False, "exchanges": [], "exchange_count": 0, "week": 1})

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {}

def save_progress(data: dict):
    PROGRESS_FILE.write_text(json.dumps(data, indent=2))

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

# ─── CLAUDE CONVERSATION ─────────────────────────────────────────────────────

def build_context(week: int, exchanges: list, progress: dict) -> list:
    """Build the full message history for Claude."""
    checklist = MILESTONES[week]
    tasks_str = "\n".join(f"- {t}" for t in checklist["tasks"])

    history_str = ""
    for w in range(1, week):
        wk = str(w)
        if wk in progress.get("weeks", {}):
            e = progress["weeks"][wk]
            history_str += f"\nWeek {w} ({MILESTONES[w]['title']}): {e['ticked_count']}/{e['total_tasks']} tasks completed."
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
    """Get JARVIS's next conversational response."""
    messages = build_context(week, exchanges, progress)
    response = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text

def get_final_verdict(week: int, exchanges: list, progress: dict) -> str:
    """Get the final structured verdict as a text report."""
    messages = build_context(week, exchanges, progress)

    checklist_tasks = "\n".join(f"- {t}" for t in MILESTONES[week]["tasks"])
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
    """Parse ticked/missed from verdict and save."""
    ticked, missed = [], []
    tasks = MILESTONES[week]["tasks"]
    report_lower = text_report.lower()

    for task in tasks:
        # Simple heuristic: if the task words appear near a tick emoji
        task_words = task.lower().split()[:4]
        key = " ".join(task_words)
        if "✅" in text_report and key in report_lower:
            ticked.append(task)
        elif "⬜" in text_report and key in report_lower:
            missed.append(task)

    # Fallback count from report
    ticked_count = text_report.count("✅")
    missed_count = text_report.count("⬜")

    if "weeks" not in progress:
        progress["weeks"] = {}

    progress["weeks"][str(week)] = {
        "date": date.today().isoformat(),
        "ticked": ticked,
        "missed": missed,
        "ticked_count": ticked_count,
        "total_tasks": len(tasks),
        "missed_count": missed_count,
    }
    save_progress(progress)
    return progress

# ─── CORE CONVERSATION HANDLER ───────────────────────────────────────────────

async def process_user_input(user_text: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle one turn of the conversation."""
    chat_id = str(update.effective_chat.id)
    conv = load_conv()
    progress = load_progress()

    if not conv["active"]:
        # Not in a debrief — ignore or prompt them to use /checkin
        await update.message.reply_text(
            "_No active debrief. Send /checkin to start your weekly review._",
            parse_mode="Markdown"
        )
        return

    week = conv["week"]

    # Add user turn to exchanges
    conv["exchanges"].append({"role": "user", "content": user_text})
    conv["exchange_count"] += 1

    if conv["exchange_count"] >= MAX_EXCHANGES:
        # Final verdict time
        await update.message.reply_text("_Compiling your debrief..._", parse_mode="Markdown")
        text_report = get_final_verdict(week, conv["exchanges"], progress)

        header = f"📋 *Week {week} Debrief — {MILESTONES[week]['title']}*\n\n"
        await update.message.reply_text(header + text_report, parse_mode="Markdown")

        # Save progress and clear conversation
        save_week_progress(week, text_report, progress)
        clear_conv()

    else:
        # Continue conversation
        reply = get_conversation_reply(week, conv["exchanges"], progress)

        # Add assistant turn to exchanges and save
        conv["exchanges"].append({"role": "assistant", "content": reply})
        save_conv(conv)

        await update.message.reply_text(reply, parse_mode="Markdown")

# ─── TELEGRAM HANDLERS ───────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return

    await update.message.reply_text("_Transcribing..._", parse_mode="Markdown")

    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)
        file_path = f"/tmp/voice_{voice.file_id}.ogg"
        await voice_file.download_to_drive(custom_path=file_path)

        transcript = await transcribe_voice(file_path)
        log.info(f"Transcript: {transcript[:100]}...")
        await process_user_input(transcript, update, context)

    except Exception as e:
        log.error(f"Voice handling error: {e}")
        await update.message.reply_text(
            f"_Failed: {str(e)}_",
            parse_mode="Markdown"
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return
    if update.message.text.startswith("/"):
        return
    await process_user_input(update.message.text, update, context)

async def send_checkin_prompt(bot: Bot):
    """Fires on Tuesday 09:00 — starts the debrief."""
    week = current_week()
    title = MILESTONES[week]["title"]

    # Initialise conversation state
    save_conv({
        "active": True,
        "exchanges": [],
        "exchange_count": 0,
        "week": week
    })

    progress = load_progress()
    weeks_done = len(progress.get("weeks", {}))

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            f"📅 *Week {week} Debrief — {title}*\n"
            f"_{weeks_done} week{'s' if weeks_done != 1 else ''} on record._\n\n"
            f"Week {week}. {title}. "
            "Walk me through the week. What moved, what didn't. Be specific.\n\n"
            f"Send a note or type. {MAX_EXCHANGES} exchanges, then the full verdict."
        ),
        parse_mode="Markdown"
    )
    log.info(f"Week {week} debrief started")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = load_progress()
    if "start_date" not in p:
        p["start_date"] = date.today().isoformat()
        save_progress(p)
        msg = (
            "✅ *SwitchToAI Check-In Bot initialised.*\n\n"
            f"Start date: *{p['start_date']}*\n"
            "Weekly debrief: every Tuesday at 09:00 London time.\n\n"
            "I ask questions. You answer by note or text. "
            f"After {MAX_EXCHANGES} exchanges you get the full verdict.\n\n"
            "*/checkin* — start a manual debrief now\n"
            "*/status* — current week and progress bars\n"
            "*/progress* — full history\n"
            "*/cancel* — end current debrief"
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
    weeks_data = p.get("weeks", {})
    if not weeks_data:
        await update.message.reply_text("No debriefs on record yet.")
        return
    lines = ["📚 *Full Debrief History*\n"]
    for w in sorted(weeks_data.keys(), key=int):
        e = weeks_data[w]
        lines.append(f"*Week {w} — {MILESTONES[int(w)]['title']}*")
        lines.append(f"Date: {e.get('date', '—')}  |  {e['ticked_count']}/{e['total_tasks']} tasks")
        if e.get("missed"):
            preview = ', '.join(e['missed'][:2])
            lines.append(f"Outstanding: {preview}{'...' if len(e['missed']) > 2 else ''}")
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ─── MAIN ────────────────────────────────────────────────────────────────────

async def main():
    log.info("JARVIS initialising...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("checkin",  cmd_checkin))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("progress", cmd_progress))
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
    await app.updater.start_polling(drop_pending_updates=True)

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
