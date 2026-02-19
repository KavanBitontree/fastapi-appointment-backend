"""
Appointment Agent Node

Flow for fully-specified requests ("Book Dr Om on 20th March at 10AM"):
  1. One LLM call to extract: doctor_name, date, time_of_day (structured JSON)
  2. Python runs all tools directly: search → validate → fetch slots → filter
  3. Response formatted in Python — no further LLM calls
  4. "Yes/confirm" turn: zero LLM calls (direct DB write)

Fallback to full ReAct agent for complex/ambiguous requests.
"""

import re
import json
from datetime import datetime, timedelta, date as dt_date
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from sqlalchemy.orm import Session

from langGraph_service.schemas.state import AgenticState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.appointment_tools_agentic import make_appointment_tools

IST = ZoneInfo("Asia/Kolkata")

_CONFIRM_PATTERNS = re.compile(
    r"\b(yes|yess|yeah|yep|confirm|book\s*it|book\s*slot|go\s*ahead|proceed|ok|okay|sure|do\s*it)\b",
    re.IGNORECASE,
)

_BUCKET_BOUNDS = {
    "morning":   (6,  12),
    "afternoon": (12, 17),
    "evening":   (17, 22),
}


def _get_ist_context():
    now = datetime.now(IST)
    return now, now.date().isoformat(), now.strftime("%d %B %Y, %I:%M %p IST")


def _filter_slots_by_bucket(slots: list, bucket: str) -> list:
    start_h, end_h = _BUCKET_BOUNDS.get(bucket, (0, 24))
    return [s for s in slots if start_h <= int(str(s["start_time"]).split(":")[0]) < end_h]


def _find_closest_slot(slots: list, preferred_hour: int) -> dict | None:
    if not slots:
        return None
    def diff(s):
        parts = str(s["start_time"]).split(":")
        return abs(int(parts[0]) * 60 + int(parts[1]) - preferred_hour * 60)
    return min(slots, key=diff)


def _format_slot_time(s: dict) -> str:
    def fmt(t):
        h, m = int(str(t).split(":")[0]), int(str(t).split(":")[1])
        period = "AM" if h < 12 else "PM"
        dh = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
        return f"{dh}:{m:02d} {period}"
    return f"{fmt(s['start_time'])} – {fmt(s['end_time'])}"


def _extract_entities_via_llm(conversation_context: str, today_iso: str, now_friendly: str) -> dict:
    """
    Single LLM call to extract structured booking intent from conversation context.
    Returns dict with keys: doctor_name, date (YYYY-MM-DD), time_of_day, preferred_hour (int or null)
    All values can be null if not mentioned.
    
    Args:
        conversation_context: Recent conversation history (may span multiple messages)
        today_iso: Today's date in YYYY-MM-DD format
        now_friendly: Current time in friendly format
    """
    extraction_prompt = f"""Extract booking details from the conversation. Today is {today_iso} ({now_friendly}).

The conversation may span multiple messages. Look for information across ALL messages provided.

Return ONLY a JSON object with these keys:
- "doctor_name": string or null — doctor's name without 'Dr.' prefix. Extract only the name, not surrounding words.
- "date": string (YYYY-MM-DD) or null — resolve relative dates using today={today_iso}
- "time_of_day": one of "morning"/"afternoon"/"evening" or null — infer from any time mention
- "preferred_hour": integer (24h) or null — if a specific hour is mentioned (e.g. "10AM" → 10, "3PM" → 15)

Examples:
- "3 PM" → preferred_hour: 15, time_of_day: "afternoon"
- "10 AM" → preferred_hour: 10, time_of_day: "morning"
- "morning" → time_of_day: "morning", preferred_hour: null
- "tomorrow" → date: (calculate tomorrow from today)
- "22nd Feb" → date: "2026-02-22" (assuming year is 2026)

Conversation:
{conversation_context}

JSON only, no explanation:"""

    try:
        response = llm.invoke([
            SystemMessage(content="You are a precise entity extractor. Return only valid JSON."),
            HumanMessage(content=extraction_prompt),
        ])
        raw = response.content.strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
        extracted = json.loads(raw)
        
        # Log for debugging
        print(f"[entity_extraction] Input: {conversation_context[:100]}...")
        print(f"[entity_extraction] Extracted: {extracted}")
        
        return extracted
    except Exception as e:
        print(f"[entity_extraction] Error: {e}")
        return {"doctor_name": None, "date": None, "time_of_day": None, "preferred_hour": None}


def get_appointment_system_prompt(patient_name: str, today_iso: str, now_friendly: str) -> str:
    return f"""You are a specialist appointment assistant for Aarogya Healthcare.

Patient Name: {patient_name}
Today's Date: {today_iso}
Current Time: {now_friendly}

Do NOT call any date tool — values are already provided above.

## Tools
- check_can_book_on_date: Validate date before fetching slots.
- find_doctor_by_name: Get doctor_id from name.
- get_slots_by_time_of_day: Fetch slots filtered by morning/afternoon/evening.
- book_slot: Book only after explicit patient confirmation.
- get_my_appointments: Show appointment history.

## Flow
1. If doctor/date/time missing, ask for all missing info in ONE message.
2. find_doctor_by_name → check_can_book_on_date → get_slots_by_time_of_day.
3. Show filtered slots numbered, ask patient to pick.
4. After patient picks, include PENDING_SLOT_ID: <slot_id> and confirm.

## Rules
- 25-hour advance rule from {now_friendly}. One appointment per day.
- Never book without confirmation. Never show all slots — always filter by time bucket.

## FORMATTING RULES (CRITICAL)
When showing slots to the patient:
- DO NOT use markdown tables (| # | Time |)
- Use simple numbered list format instead
- Format: "1. 11:00 AM – 11:15 AM"
- Keep it clean and readable

GOOD formatting example:
"Here are available morning slots on 17 March 2026 with Dr Kunj Vasoya:

1. 11:00 AM – 11:15 AM
2. 11:15 AM – 11:30 AM
3. 11:30 AM – 11:45 AM
4. 11:45 AM – 12:00 PM

Which slot would you like? Just reply with the number (e.g., 1)."

BAD formatting (DO NOT USE):
| # | Time |
|---|------|
| 1 | 11:00 – 11:15 |
"""


def _extract_pending_slot_id(text: str):
    m = re.search(r"PENDING_SLOT_ID:\s*(\d+)", text)
    return int(m.group(1)) if m else None


def _strip_pending_hint(text: str) -> str:
    return re.sub(r"\nPENDING_SLOT_ID:\s*\d+\n?", "", text).strip()


def make_appointment_agent(db: Session, patient_id: int, patient_name: str, max_iterations: int = 10):
    tools = make_appointment_tools(db, patient_id)

    from langGraph_service.tools.appointment_tools import (
        request_appointment_via_bot,
        get_free_slots_for_doctor_on_date,
        check_patient_can_book_on_date,
    )
    from langGraph_service.tools.doctor_tools import search_doctors_by_name
    import asyncio, concurrent.futures

    def _book_slot_direct(slot_id: int) -> dict:
        """Helper to book a slot, handling async execution properly."""
        def _run_async_in_thread():
            return asyncio.run(request_appointment_via_bot(db, patient_id, slot_id))
        
        try:
            # Check if we're in an async context
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context - use ThreadPoolExecutor
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(_run_async_in_thread).result()
            except RuntimeError:
                # No running loop - use asyncio.run directly
                return asyncio.run(request_appointment_via_bot(db, patient_id, slot_id))
        except Exception as e:
            import traceback
            print(f"[_book_slot_direct] Exception: {type(e).__name__}: {str(e)}")
            print(traceback.format_exc())
            return {"success": False, "error": str(e)}

    def appointment_node(state: AgenticState) -> Command:
        messages = state.get("messages") or []
        pending_slot_id = state.get("pending_slot_id")
        now, today_iso, now_friendly = _get_ist_context()

        # ── FAST PATH 1: confirmation — zero LLM calls ────────────────────────
        if pending_slot_id and messages:
            last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
            user_text = getattr(last_human, "content", "") if last_human else ""
            if _CONFIRM_PATTERNS.search(user_text):
                result = _book_slot_direct(pending_slot_id)
                if result.get("success"):
                    text = (
                        f"✅ Appointment booked!\n\n"
                        f"**Doctor:** Dr. {result['doctor_name']}\n"
                        f"**Date:** {result['slot_date']}\n"
                        f"**Time:** {result['slot_time']}\n"
                        f"**Status:** {result['status']}\n"
                        f"**Approval deadline:** {result['approval_deadline']}\n\n"
                        f"The doctor has 24 hours to approve. You'll be notified once confirmed."
                    )
                else:
                    error_detail = result.get('error', 'Unknown error')
                    # Provide more specific guidance based on error type
                    if 'not available' in error_detail.lower() or 'status:' in error_detail.lower():
                        text = f"⚠️ That slot was just taken by someone else. Would you like to see other available slots?"
                    elif 'not found' in error_detail.lower():
                        text = f"⚠️ The slot is no longer available. Would you like to see current available slots?"
                    elif 'already have' in error_detail.lower() or 'one appointment per day' in error_detail.lower():
                        text = f"⚠️ {error_detail}\n\nWould you like to check your existing appointments or book for a different date?"
                    else:
                        text = f"⚠️ Booking failed: {error_detail}\n\nWould you like to try a different slot or date?"
                return Command(
                    update={
                        "messages": [AIMessage(content=text, name="appointment_node")],
                        "pending_slot_id": None,
                    },
                    goto="supervisor",
                )

        # ── FAST PATH 2: LLM entity extraction + Python tool execution ────────
        last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        user_text = getattr(last_human, "content", "") if last_human else ""

        # Check if this looks like a booking request (not history check etc.)
        is_booking_intent = any(w in user_text.lower() for w in [
            "book", "appointment", "slot", "schedule", "fix", "reserve"
        ])

        if is_booking_intent:
            # Build context from recent conversation history (last 3-5 messages)
            # to capture info spread across multiple messages
            recent_context = []
            for msg in reversed(messages[-5:]):  # Last 5 messages
                if isinstance(msg, (HumanMessage, AIMessage)):
                    content = getattr(msg, "content", "") or ""
                    if content and not getattr(msg, "tool_calls", None):
                        recent_context.append(content)
            
            # Combine recent context for entity extraction
            context_text = "\n".join(reversed(recent_context))
            
            entities = _extract_entities_via_llm(context_text, today_iso, now_friendly)
            doctor_name = entities.get("doctor_name")
            date_str = entities.get("date")
            time_of_day = entities.get("time_of_day")
            preferred_hour = entities.get("preferred_hour")

            if doctor_name and date_str and time_of_day:
                # All info present — run tools in Python
                try:
                    # 1. Find doctor
                    doctors = search_doctors_by_name(db, doctor_name, limit=5)
                    if not doctors:
                        text = f"I couldn't find a doctor matching **'{doctor_name}'**. Could you check the spelling?"
                        return Command(
                            update={"messages": [AIMessage(content=text, name="appointment_node")]},
                            goto="supervisor",
                        )
                    doctor = doctors[0]
                    doctor_id = doctor["id"]

                    # 2. Validate date
                    target_date = dt_date.fromisoformat(date_str)
                    availability = check_patient_can_book_on_date(db, patient_id, target_date)
                    if not availability["can_book"]:
                        text = f"Can't book on {target_date.strftime('%d %B %Y')}: {availability['reason']}"
                        return Command(
                            update={"messages": [AIMessage(content=text, name="appointment_node")]},
                            goto="supervisor",
                        )

                    # 3. Fetch and filter slots
                    slot_data = get_free_slots_for_doctor_on_date(db, doctor_id, target_date)
                    if not slot_data.get("doctor_found"):
                        text = "Doctor not found in the system."
                        return Command(
                            update={"messages": [AIMessage(content=text, name="appointment_node")]},
                            goto="supervisor",
                        )

                    filtered = _filter_slots_by_bucket(slot_data["slots"], time_of_day)
                    if not filtered:
                        text = (
                            f"No **{time_of_day}** slots available for Dr. {doctor['name']} "
                            f"on {target_date.strftime('%d %B %Y')}.\n"
                            f"Would you like to check morning, afternoon, or evening instead?"
                        )
                        return Command(
                            update={"messages": [AIMessage(content=text, name="appointment_node")]},
                            goto="supervisor",
                        )

                    # 4. Format response
                    friendly_date = target_date.strftime("%d %B %Y")
                    header = (
                        f"**Dr. {doctor['name']}** ({doctor['speciality']}) — ₹{doctor['opd_fees']}\n"
                        f"📅 {friendly_date} | 📍 {doctor.get('address', 'N/A')}\n"
                    )

                    closest = _find_closest_slot(filtered, preferred_hour) if preferred_hour else None
                    pending = None

                    if closest and len(filtered) > 1:
                        other = [s for s in filtered if s["id"] != closest["id"]]
                        slot_lines = [f"⭐ **Slot 1: {_format_slot_time(closest)}** ← closest to your preferred time"]
                        for i, s in enumerate(other, 2):
                            slot_lines.append(f"   Slot {i}: {_format_slot_time(s)}")
                        body = "\n".join(slot_lines)
                        footer = f"\nShall I book **Slot 1 ({_format_slot_time(closest)})**? Just say yes to confirm."
                        pending = closest["id"]
                    elif len(filtered) == 1:
                        s = filtered[0]
                        body = f"1 {time_of_day} slot available: **{_format_slot_time(s)}**"
                        footer = "\nShall I book this slot? Just say yes to confirm."
                        pending = s["id"]
                    else:
                        slot_lines = [f"{i}. {_format_slot_time(s)}" for i, s in enumerate(filtered, 1)]
                        body = f"{time_of_day.capitalize()} slots:\n" + "\n".join(slot_lines)
                        footer = "\nWhich slot would you like?"

                    text = header + "\n" + body + footer
                    update = {"messages": [AIMessage(content=text, name="appointment_node")]}
                    if pending:
                        update["pending_slot_id"] = pending
                    return Command(update=update, goto="supervisor")

                except Exception:
                    pass  # Fall through to ReAct agent

            elif is_booking_intent and (doctor_name or date_str or time_of_day):
                # Partial info — ask for missing pieces in one message (no LLM needed)
                missing = []
                if not doctor_name:
                    missing.append("the doctor's name")
                if not date_str:
                    missing.append("the preferred date")
                if not time_of_day:
                    missing.append("preferred time (morning, afternoon, or evening)")
                
                # Build context-aware message
                if len(missing) == 1:
                    text = f"I have most of the details. I just need {missing[0]} to proceed with booking."
                else:
                    text = f"To book your appointment, I need: **{', '.join(missing)}**. Could you provide these?"
                
                print(f"[appointment_agent] Partial info - missing: {missing}")
                print(f"[appointment_agent] Have: doctor={doctor_name}, date={date_str}, time={time_of_day}")
                
                return Command(
                    update={"messages": [AIMessage(content=text, name="appointment_node")]},
                    goto="supervisor",
                )

        # ── NORMAL PATH: full ReAct agent for complex/ambiguous requests ──────
        system_prompt = get_appointment_system_prompt(patient_name, today_iso, now_friendly)
        agent = create_react_agent(model=llm, tools=tools, prompt=system_prompt)
        result = agent.invoke({"messages": messages})
        new_messages = result["messages"][len(messages):]

        extracted_slot_id = None
        tagged = []
        for msg in new_messages:
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                content = (msg.content or "").strip()
                # Guard against Groq empty response bug
                if not content:
                    content = "I'm ready to help. Please provide the doctor's name, date, and preferred time of day."
                slot_hint = _extract_pending_slot_id(content)
                if slot_hint:
                    extracted_slot_id = slot_hint
                tagged.append(AIMessage(content=_strip_pending_hint(content), name="appointment_node"))
            else:
                tagged.append(msg)

        update = {"messages": tagged}
        if extracted_slot_id:
            update["pending_slot_id"] = extracted_slot_id
        return Command(update=update, goto="supervisor")

    return appointment_node