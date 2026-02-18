"""
Intent Classification Node (Supervisor / Orchestrator)
Routes user messages to the correct handler node.
Context-aware: detects follow-up messages like "Book slot 1" by reading
persisted state from the previous turn (available_slots, doctor_id, date, etc.).

FIX — INVALID_CONCURRENT_GRAPH_UPDATE on current_step:
  classify_intent must NOT set current_step in its Command update.
  Both classify_intent and the destination handler run in the same graph
  "super-step" when using Command(goto=...). Writing current_step from both
  triggers LangGraph's single-writer-per-step constraint.
  Solution: remove current_step from classify_intent's update dict entirely.
  Each handler node owns current_step for that turn.

FIX — "This Sunday" / weekday not resolved:
  Extended next_days to cover 14 days so "this Sunday" (which may be 6 days
  away) is always in the mapping. Also added explicit "this <day>" and
  "next <day>" resolution logic in the prompt so the LLM never has to guess.
"""

from typing import Literal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from langgraph.types import Command
from pydantic import BaseModel, Field

from langGraph_service.schemas.state import ChatbotState, IntentClassification
from langGraph_service.config.llm_init import llm

IST = ZoneInfo("Asia/Kolkata")


def classify_intent(
    state: ChatbotState,
) -> Command[Literal["appointment_handler", "doctor_handler", "nearby_doctor_handler", "profile_handler", "response_handler"]]:
    """
    Classify user intent and route to the appropriate handler.
    Reads previous-turn context (available_slots, doctor_id, date) from state
    so follow-up messages like 'Book slot 1' are correctly routed.
    """

    now_ist = datetime.now(IST)
    today = now_ist.date()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    # ── Build next_days mapping ───────────────────────────────────────────────
    # Cover 14 days so "this Sunday" is always resolvable regardless of current weekday.
    # "this <day>" = first occurrence within the next 7 days
    # "next <day>" = occurrence 8–14 days out
    this_week: dict[str, str] = {}   # "this monday" → date
    next_week: dict[str, str] = {}   # "next monday" → date

    for i in range(1, 15):
        d = today + timedelta(days=i)
        day_name = d.strftime("%A").lower()
        if i <= 7 and day_name not in this_week:
            this_week[day_name] = d.strftime("%Y-%m-%d")
        elif i > 7 and day_name not in next_week:
            next_week[day_name] = d.strftime("%Y-%m-%d")

    # ── Build context summary from previous turn ───────────────────────────────
    prev_slots = state.get("available_slots") or []
    prev_doctor_id = state.get("doctor_id")
    prev_doctor_name = state.get("doctor_name")
    prev_date = state.get("date")
    prev_step = state.get("current_step")

    has_prior_slots = len(prev_slots) > 0
    prior_context_summary = ""
    if has_prior_slots:
        prior_context_summary = (
            f"PRIOR TURN CONTEXT (IMPORTANT):\n"
            f"  - {len(prev_slots)} slots were shown to the user in the previous response\n"
            f"  - Doctor ID: {prev_doctor_id}, Doctor Name: {prev_doctor_name}\n"
            f"  - Date: {prev_date}\n"
            f"  - Last step: {prev_step}\n"
            f"  - Slot IDs shown: {[s.get('id') for s in prev_slots[:5]]}\n"
        )
    elif prev_doctor_id or prev_date:
        prior_context_summary = (
            f"PRIOR TURN CONTEXT:\n"
            f"  - Doctor ID: {prev_doctor_id}, Doctor Name: {prev_doctor_name}\n"
            f"  - Date: {prev_date}\n"
            f"  - Last step: {prev_step}\n"
        )

    structured_llm = llm.with_structured_output(IntentClassification)

    prompt = f"""
Analyze this patient message and classify intent + extract entities.

Patient: {state.get('patient_name', 'Patient')}
Message: "{state.get('current_message', '')}"

{prior_context_summary}

=== CURRENT IST CONTEXT ===
Today's Date : {today.strftime("%Y-%m-%d")} ({today.strftime("%A")})
Today's Time : {now_ist.strftime("%I:%M %p")}
Tomorrow     : {tomorrow.strftime("%Y-%m-%d")} ({tomorrow.strftime("%A")})
Day After    : {day_after.strftime("%Y-%m-%d")} ({day_after.strftime("%A")})

=== WEEKDAY → DATE MAPPING (use EXACTLY these values) ===
"This <day>" refers to the FIRST upcoming occurrence within 7 days:
{chr(10).join(f'  "This {k.capitalize()}" or just "{k.capitalize()}" → {v}' for k, v in this_week.items())}

"Next <day>" refers to the occurrence 8–14 days out:
{chr(10).join(f'  "Next {k.capitalize()}" → {v}' for k, v in next_week.items())}

RULE: If the user says "This Sunday" or just "Sunday", use the "This <day>" mapping.
      If the user says "Next Sunday", use the "Next <day>" mapping.
      ALWAYS return the exact YYYY-MM-DD from the tables above — never compute it yourself.

=== INTENT CLASSES ===
appointment     - Book/request slots, view appointments, follow-up booking ("book slot 1", "yes book it")
doctor_search   - Find/search doctors by name or speciality (NOT nearby/location)
nearby_doctors  - Find doctors near me / by location
profile         - View/update patient name or date of birth
greeting        - Hello, hi, hey, namaste
help            - What can you do? Features? Help?
out_of_scope    - Anything unrelated to healthcare appointments

=== CRITICAL: FOLLOW-UP DETECTION ===
If prior turn context shows slots were shown to the user, these phrases are APPOINTMENT intent:
- "book slot 1" / "book slot 2" / "book the first slot" → appointment (confirm_book)
- "book it" / "yes book" / "confirm" → appointment
- "book 10 AM" / "the 9 AM slot" → appointment
- "book the first one" / "I'll take slot 2" → appointment
DO NOT classify these as 'need_date' — the date and doctor are already in context.

=== ENTITY EXTRACTION ===
DATE (always YYYY-MM-DD):
  "today"              → {today.strftime("%Y-%m-%d")}
  "tomorrow"           → {tomorrow.strftime("%Y-%m-%d")}
  "day after tomorrow" → {day_after.strftime("%Y-%m-%d")}
  weekday names        → use the mapping tables above (MANDATORY)
  "25 Dec" / "Dec 25"  → {today.year}-12-25

TIME (HH:MM 24hr):
  "10 AM" → 10:00, "3 PM" → 15:00, "2:30 PM" → 14:30

DOCTOR NAME: strip "Dr." prefix

SPECIALITY conversions:
  "heart doctor" → Cardiologist
  "skin doctor"  → Dermatologist
  "child doctor" → Pediatrician
  "bone doctor"  → Orthopedic

Return: intent, confidence, entities (date/time/speciality/doctor_name), summary, reasoning.
"""

    classification: IntentClassification = structured_llm.invoke(prompt)

    route_map = {
        "appointment": "appointment_handler",
        "doctor_search": "doctor_handler",
        "nearby_doctors": "nearby_doctor_handler",
        "profile": "profile_handler",
        "greeting": "response_handler",
        "help": "response_handler",
        "out_of_scope": "response_handler",
    }
    goto = route_map.get(classification.intent, "response_handler")

    entities = classification.entities or {}

    # ── Build update dict ─────────────────────────────────────────────────────
    # CRITICAL: Do NOT include current_step here.
    # Both classify_intent and the destination handler node run in the same
    # LangGraph super-step when Command(goto=...) is used. Writing current_step
    # from both nodes in the same step triggers:
    #   INVALID_CONCURRENT_GRAPH_UPDATE: Can receive only one value per step.
    # Each handler owns current_step for the turn — classifier stays out of it.
    update: dict = {
        "classification": classification,
        # current_step intentionally omitted — handler node sets it
    }

    # Only update entity fields if the classifier found new values.
    # Do NOT overwrite existing context with None — preserve prior turn's doctor_id/date.
    if entities.get("date"):
        update["date"] = entities["date"]
    if entities.get("time"):
        update["time"] = entities["time"]
    if entities.get("speciality"):
        update["speciality"] = entities["speciality"]
    if entities.get("doctor_name"):
        update["doctor_name"] = entities["doctor_name"]

    # Clear response/suggestions from prior turn so we start fresh
    update["response"] = None
    update["suggestions"] = None

    return Command(update=update, goto=goto)