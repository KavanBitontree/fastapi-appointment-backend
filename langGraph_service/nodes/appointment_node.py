"""
Appointment Handler Node
All state access uses dict syntax (state["key"] / state.get("key"))
because ChatbotState is a TypedDict (plain dict at runtime).
"""

from typing import Literal
from datetime import datetime, timedelta, date as dt_date
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field
from langgraph.types import Command
from sqlalchemy.orm import Session
import re

from langGraph_service.schemas.state import ChatbotState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.datetime_tools import (
    get_current_ist_date, get_current_ist_time, format_date_friendly,
    is_date_in_past, parse_day_name, get_next_weekday,
)
from langGraph_service.tools.appointment_tools import (
    get_patient_appointments,
    check_patient_can_book_on_date,
    get_free_slots_for_doctor_on_date,
    get_slots_near_preferred_time,
    request_appointment_via_bot,
)
from langGraph_service.tools.doctor_tools import search_doctors_by_name

IST = ZoneInfo("Asia/Kolkata")


class AppointmentDecision(BaseModel):
    action: Literal[
        "show_appointments",
        "explain_today_rule",
        "need_date",
        "need_doctor",
        "get_slots",
        "confirm_book",
        "ask_which_monday",
        "ask_which_date_for_time",
    ]
    reasoning: str
    extracted_date: str | None = None
    extracted_doctor_name: str | None = None
    preferred_time: str | None = None
    response_hint: str | None = None


async def appointment_handler(
    state: ChatbotState,
    db: Session,
) -> Command[Literal["response_handler"]]:

    now_ist = get_current_ist_time()
    today = get_current_ist_date()
    tomorrow = today + timedelta(days=1)

    # ── Read state with dict syntax ───────────────────────────────────────────
    patient_name    = state.get("patient_name", "Patient")
    patient_id      = state["patient_id"]
    current_message = state.get("current_message", "")
    state_date      = state.get("date")
    state_time      = state.get("time")
    state_doctor_name = state.get("doctor_name")
    state_doctor_id   = state.get("doctor_id")
    state_speciality  = state.get("speciality")
    state_step        = state.get("current_step")
    state_slots       = state.get("available_slots") or []
    has_prior_slots   = len(state_slots) > 0

    # ── Pre-LLM guard: short-circuit when state already has resolved context ────
    # The classifier already resolved weekday names ("This Sunday", "Next Friday")
    # to YYYY-MM-DD and stored in state["date"]. If we naively pass the raw message
    # to the LLM it re-evaluates "This Sunday" and returns need_date because it
    # can't resolve it without the weekday→date tables the classifier has.
    #
    # Short-circuit rules (checked BEFORE calling LLM):
    #   prior_slots + booking phrase  → confirm_book
    #   date + doctor_id              → get_slots
    #   date only (no doctor info)    → need_doctor
    #   no date                       → let LLM decide
    pre_action: str | None = None

    msg_lower = current_message.lower()

    # ── Escape hatches: these ALWAYS go to LLM regardless of state context ────
    # "check my appointments" / "my appointments" must never hit get_slots
    appointment_view_phrases = [
        "check my appointment", "my appointment", "show my appointment",
        "view my appointment", "appointment status", "appointment history",
        "my history", "past appointment", "previous appointment",
        "booked appointment", "upcoming appointment", "scheduled appointment",
        "give me my appointment", "show appointment", "list appointment",
    ]
    if any(p in msg_lower for p in appointment_view_phrases):
        # Force LLM path AND pre-set action directly to skip LLM entirely
        # This is the safest path — never let stale state hijack view-appointments intent
        decision = AppointmentDecision(
            action="show_appointments",
            reasoning="User explicitly asked to view appointment history",
        )
        appointments = get_patient_appointments(db, patient_id)
        if not appointments:
            response = "📋 You don't have any appointments yet.\n\nWould you like to book one?"
            suggestions = ["Find cardiologist slots", "Show available doctors", "Help"]
        else:
            response = f"📋 **Your Appointments ({len(appointments)}):**\n\n"
            for apt in appointments:
                from datetime import date as _dt
                try:
                    d = _dt.fromisoformat(str(apt['slot_date']))
                    friendly_date = d.strftime("%d %B %Y")
                except Exception:
                    friendly_date = str(apt['slot_date'])
                t = str(apt['slot_time']).split(":")
                friendly_time = f"{t[0]}:{t[1]}" if len(t) >= 2 else str(apt['slot_time'])
                response += f"**Dr. {apt['doctor_name']}** ({apt['speciality']})\n"
                response += f"📅 {friendly_date} | ⏰ {friendly_time}\n"
                response += f"📊 Status: **{apt['status']}** | 💰 ₹{apt['opd_fees']}\n\n"
            suggestions = ["Book another appointment", "Find available slots", "Search doctors"]
        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "appointments_shown"},
            goto="response_handler",
        )

    # "another appointment" / "new appointment" / "different doctor" → clear
    # stale doctor/date context so we don't re-use the previous booking's doctor
    new_booking_phrases = ["another appointment", "new appointment", "different doctor", "another doctor", "someone else", "morning slot", "evening slot", "afternoon slot"]
    is_new_booking = any(p in msg_lower for p in new_booking_phrases)

    if pre_action is None and not is_new_booking:
        if has_prior_slots and state_doctor_id and state_date:
            booking_phrases = ["book", "yes", "confirm", "first", "second", "third", "slot", "take"]
            if any(p in msg_lower for p in booking_phrases):
                pre_action = "confirm_book"

    if pre_action is None and not is_new_booking and state_date and (state_doctor_id or state_doctor_name):
        pre_action = "get_slots"

    if pre_action is None and not is_new_booking and state_date and not state_doctor_id and not state_doctor_name and not state_speciality:
        pre_action = "need_doctor"

    if pre_action is not None:
        # Build stub decision — rest of handler code path is unchanged
        decision = AppointmentDecision(
            action=pre_action,
            reasoning=f"Pre-resolved from state: date={state_date}, doctor_id={state_doctor_id}",
            extracted_date=state_date,
            extracted_doctor_name=state_doctor_name,
        )
    else:
        # ── LLM decision (only when state doesn't have enough to short-circuit) ───
        structured_llm = llm.with_structured_output(AppointmentDecision)

        slot_context = ""
        if has_prior_slots:
            slot_context = (
                f"PRIOR SLOTS SHOWN ({len(state_slots)} slots, doctor_id={state_doctor_id}, date={state_date}):\n"
                + "\n".join(f"  Slot {i+1}: {s.get('start_time')} – {s.get('end_time')} (ID {s.get('id')})"
                            for i, s in enumerate(state_slots))
                + "\n"
            )

        decision_prompt = f"""
Analyze this appointment message and pick the next action.

Patient: {patient_name}
Message: "{current_message}"

{slot_context}
CONTEXT:
  Now (IST)   = {now_ist.strftime("%d %B %Y, %I:%M %p")}
  Today       = {today.isoformat()} ({today.strftime("%A")})
  Tomorrow    = {tomorrow.isoformat()}
  date        = {state_date or "None"}
  time        = {state_time or "None"}
  doctor_name = {state_doctor_name or "None"}
  doctor_id   = {state_doctor_id or "None"}
  speciality  = {state_speciality or "None"}
  step        = {state_step or "None"}

ACTIONS:
  show_appointments       - User wants to see their existing appointments ("check my appointments", "my appointments", "show appointments", "appointment status")
  explain_today_rule      - User said "today" → explain 25hr advance rule
  need_date               - No date given AND date is None in CONTEXT above
  need_doctor             - Date given but no doctor/speciality
  get_slots               - Have date + doctor → fetch slots
  confirm_book            - User picked a slot ("book slot 1", "book it", "yes", "first slot")
  ask_which_monday        - User said ambiguous day name AND date is None in CONTEXT
  ask_which_date_for_time - User said only a time AND date is None in CONTEXT

CRITICAL RULES:
1. "check my appointments" / "my appointments" / "show appointments" → ALWAYS show_appointments. Never explain_today_rule for these.
2. If date is NOT None in CONTEXT → NEVER return need_date or ask_which_monday.
3. If date is NOT None AND doctor_id/name is NOT None → return get_slots.
4. If date is NOT None AND doctor is None → return need_doctor.
5. If prior slots shown AND user says book/yes/first/slot N → confirm_book.
6. "another appointment" / "book again" / "new appointment" → need_date (ignore stale date/doctor in context).

Extract extracted_date (YYYY-MM-DD), extracted_doctor_name, preferred_time (HH:MM).
"""
        decision: AppointmentDecision = structured_llm.invoke(decision_prompt)

    # ── 1. SHOW APPOINTMENTS ──────────────────────────────────────────────────
    if decision.action == "show_appointments":
        appointments = get_patient_appointments(db, patient_id)
        if not appointments:
            response = "📋 You don't have any appointments yet.\n\nWould you like to book one?"
            suggestions = ["Find cardiologist slots", "Show available doctors", "Help"]
        else:
            response = f"📋 Your recent appointments ({len(appointments)}):\n\n"
            for apt in appointments:
                response += f"🗓️ {apt['slot_date']} | {apt['slot_time']}\n"
                response += f"👨‍⚕️ Dr. {apt['doctor_name']} ({apt['speciality']})\n"
                response += f"📊 Status: {apt['status']} | 💰 ₹{apt['opd_fees']}\n\n"
            suggestions = ["Book another appointment", "Find available slots", "Search doctors"]

        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "appointments_shown"},
            goto="response_handler",
        )

    # ── 2. EXPLAIN TODAY RULE ─────────────────────────────────────────────────
    elif decision.action == "explain_today_rule":
        response = (
            f"🕐 Current IST Time: {now_ist.strftime('%d %B %Y, %I:%M %p IST')}\n\n"
            "⚠️ Appointments require at least **25 hours advance notice**.\n"
            "This gives the doctor 24 hours to review and approve before the appointment.\n\n"
            f"✅ You can book from **{format_date_friendly(tomorrow)}** onwards.\n\n"
            "Would you like to see available slots for tomorrow?"
        )
        suggestions = [
            f"Show slots for {format_date_friendly(tomorrow)}",
            "Find cardiologist",
            "Search for doctors",
        ]
        return Command(
            update={"response": response, "suggestions": suggestions, "date": tomorrow.isoformat(), "current_step": "today_explained"},
            goto="response_handler",
        )

    # ── 3. ASK WHICH DAY ─────────────────────────────────────────────────────
    elif decision.action == "ask_which_monday":
        detected_day = parse_day_name(current_message) or "Monday"
        next1 = get_next_weekday(detected_day)
        next2 = next1 + timedelta(days=7)
        next3 = next2 + timedelta(days=7)
        response = (
            f"📅 Which {detected_day} are you referring to?\n\n"
            f"1️⃣ {format_date_friendly(next1)} (This {detected_day})\n"
            f"2️⃣ {format_date_friendly(next2)} (Next {detected_day})\n"
            f"3️⃣ {format_date_friendly(next3)}\n\n"
            f"Please reply with the date, e.g. **{next1.isoformat()}**"
        )
        suggestions = [
            f"Book for {format_date_friendly(next1)}",
            f"Book for {format_date_friendly(next2)}",
            "Cancel",
        ]
        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "asking_which_day"},
            goto="response_handler",
        )

    # ── 4. ASK DATE FOR TIME-ONLY REQUEST ────────────────────────────────────
    elif decision.action == "ask_which_date_for_time":
        time_pref = state_time or decision.preferred_time or "the time you mentioned"
        response = (
            f"⏰ You mentioned **{time_pref}** — sounds good!\n\n"
            "Could you also tell me which **date** you'd like?\n\n"
            f"Example: *'Tomorrow at {time_pref}'* or *'{format_date_friendly(tomorrow)} at {time_pref}'*"
        )
        suggestions = [f"Tomorrow at {time_pref}", "Search for doctors first"]
        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "asking_date_for_time"},
            goto="response_handler",
        )

    # ── 5. NEED DATE ──────────────────────────────────────────────────────────
    elif decision.action == "need_date":
        response = (
            "📅 I'd love to help you book an appointment!\n\n"
            "Please tell me which **date** you'd like:\n"
            f"- 'Tomorrow' ({format_date_friendly(tomorrow)})\n"
            "- A specific date like '25 December' or '2025-03-10'\n"
            "- Or a day like 'Next Friday'\n\n"
            "Example: *'Show me cardiologist slots for tomorrow'*"
        )
        suggestions = [
            f"Show slots for tomorrow ({format_date_friendly(tomorrow)})",
            "Find cardiologist",
            "Show available doctors",
        ]
        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "need_date"},
            goto="response_handler",
        )

    # ── 6. NEED DOCTOR ────────────────────────────────────────────────────────
    elif decision.action == "need_doctor":
        date_str = decision.extracted_date or state_date
        date_obj = dt_date.fromisoformat(date_str) if date_str else tomorrow

        availability = check_patient_can_book_on_date(db, patient_id, date_obj)
        if not availability["can_book"]:
            response = f"❌ {availability['reason']}"
            if availability.get("existing"):
                apt = availability["existing"]
                response += f"\n\n📋 Existing: Dr. {apt['doctor_name']} | {apt['slot_time']}"
            suggestions = [
                f"Book for {format_date_friendly(date_obj + timedelta(days=1))}",
                "Check my appointments",
            ]
            return Command(update={"response": response, "suggestions": suggestions}, goto="response_handler")

        response = (
            f"📅 Great! Looking for slots on **{format_date_friendly(date_obj)}**.\n\n"
            "Which doctor or specialization are you looking for?\n\n"
            "Examples: 'Find cardiologist' · 'Dr. Rajeev Shukla' · 'Show all doctors'"
        )
        suggestions = ["Find cardiologist", "Find dermatologist", "Show all doctors"]
        return Command(
            update={"response": response, "suggestions": suggestions, "date": date_obj.isoformat(), "current_step": "need_doctor"},
            goto="response_handler",
        )

    # ── 7. GET SLOTS ──────────────────────────────────────────────────────────
    elif decision.action == "get_slots":
        date_str = decision.extracted_date or state_date
        doctor_name = decision.extracted_doctor_name or state_doctor_name
        doctor_id = state_doctor_id

        if not date_str:
            return Command(
                update={"response": "Please provide the date for the appointment.", "suggestions": ["Tomorrow", "Next week"], "current_step": "need_date"},
                goto="response_handler",
            )

        date_obj = dt_date.fromisoformat(date_str)

        if is_date_in_past(date_obj):
            response = f"⚠️ {format_date_friendly(date_obj)} is in the past. Please choose a future date."
            return Command(
                update={"response": response, "suggestions": [f"Show slots for {format_date_friendly(tomorrow)}"]},
                goto="response_handler",
            )

        availability = check_patient_can_book_on_date(db, patient_id, date_obj)
        if not availability["can_book"]:
            response = f"❌ {availability['reason']}"
            if availability.get("existing"):
                apt = availability["existing"]
                response += f"\n\n📋 Existing: Dr. {apt['doctor_name']} | {apt['slot_time']}"
            suggestions = [
                f"Book for {format_date_friendly(date_obj + timedelta(days=1))}",
                "Check my appointments",
            ]
            return Command(update={"response": response, "suggestions": suggestions}, goto="response_handler")

        if not doctor_id and doctor_name:
            matches = search_doctors_by_name(db, doctor_name, limit=5)
            if not matches:
                response = f"😔 No doctor found matching **'{doctor_name}'**.\n\nTry searching by specialization."
                return Command(
                    update={"response": response, "suggestions": ["Find cardiologist", "Show all doctors"]},
                    goto="response_handler",
                )
            doctor_id = matches[0]["id"]

        if not doctor_id:
            return Command(
                update={"response": "Please tell me which doctor or specialization you'd like.", "suggestions": ["Find cardiologist", "Show all doctors"], "date": date_str},
                goto="response_handler",
            )

        slot_result = get_free_slots_for_doctor_on_date(db, doctor_id, date_obj)
        if not slot_result["doctor_found"]:
            return Command(update={"response": "❌ Doctor not found.", "suggestions": ["Show all doctors"]}, goto="response_handler")

        all_slots = slot_result["slots"]

        # Apply time preference
        preferred_time = decision.preferred_time or state_time
        display_slots = all_slots
        time_note = ""
        if preferred_time and all_slots:
            try:
                parts = preferred_time.split(":")
                pref_h, pref_m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                filtered = get_slots_near_preferred_time(all_slots, pref_h, pref_m, tolerance_hours=2)
                if filtered:
                    display_slots = filtered[:5]
                    time_note = f"\n📌 Showing slots nearest to your preferred time ({preferred_time}).\n"
                else:
                    time_note = f"\n⚠️ No slots near {preferred_time}. Showing all available slots.\n"
            except Exception:
                pass

        if not all_slots:
            response = (
                f"😔 No available slots for **Dr. {slot_result['doctor_name']}** "
                f"on **{format_date_friendly(date_obj)}**.\n\nPlease try another date."
            )
            suggestions = [
                f"Show slots for {format_date_friendly(date_obj + timedelta(days=1))}",
                "Find another doctor",
            ]
            return Command(
                update={"response": response, "suggestions": suggestions, "current_step": "no_slots"},
                goto="response_handler",
            )

        shown = display_slots[:5]

        # Format times cleanly — strip seconds from HH:MM:SS → HH:MM
        def fmt_time(t: str) -> str:
            parts = str(t).split(":")
            return f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else str(t)

        response = (
            f"✅ **Dr. {slot_result['doctor_name']}** ({slot_result['speciality']})\n\n"
            f"📅 **Date:** {format_date_friendly(date_obj)}\n"
            f"💰 **Fee:** ₹{slot_result['opd_fees']}\n"
            f"📍 {slot_result['address']}\n"
        )
        if time_note:
            response += f"{time_note}\n"
        response += f"\n**Available Slots** ({len(all_slots)} total — showing up to 5):\n\n"

        for i, slot in enumerate(shown, 1):
            start = fmt_time(slot['start_time'])
            end   = fmt_time(slot['end_time'])
            response += f"{i}. {start} – {end}\n"

        response += (
            "\nTo book, say **'Book slot 1'** or **'Book the 10:00 slot'**\n"
            "_Sent to doctor for approval — valid for 24 hrs_"
        )

        suggestions = [f"Book slot {i+1}" for i in range(min(3, len(shown)))]
        suggestions.append("Find another doctor")

        return Command(
            update={
                "response": response,
                "suggestions": suggestions,
                "available_slots": shown,
                "doctor_id": doctor_id,
                "date": date_str,
                "current_step": "slots_shown",
            },
            goto="response_handler",
        )

    # ── 8. CONFIRM BOOK ───────────────────────────────────────────────────────
    elif decision.action == "confirm_book":
        available_slots = state_slots

        if not available_slots:
            response = (
                "❓ I don't see any slots loaded. Let's find them first!\n\n"
                "Please tell me the doctor and date you'd like."
            )
            return Command(
                update={"response": response, "suggestions": ["Show slots for tomorrow", "Find cardiologist"]},
                goto="response_handler",
            )

        # ── Parse any time mentioned in the message (e.g. "4:00 PM", "16:00") ──
        def parse_time_from_message(text: str) -> str | None:
            """Extract and convert time from message to HH:MM 24hr format."""
            import re as _re
            # Match "4:00 PM", "4 PM", "16:00", "4:30PM"
            m = _re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', text.lower())
            if not m:
                return None
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            meridiem = m.group(3)
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            return f"{hour:02d}:{minute:02d}"

        requested_time = parse_time_from_message(current_message) or state_time

        slot_to_book = None
        msg_lower = current_message.lower()

        # "slot 1", "slot 2" — explicit number takes highest priority
        slot_num_match = re.search(r'slot\s*(\d+)', msg_lower)
        if slot_num_match:
            idx = int(slot_num_match.group(1)) - 1
            if 0 <= idx < len(available_slots):
                slot_to_book = available_slots[idx]

        # Ordinal words — "first", "second", "1st" etc
        if not slot_to_book:
            ordinals = {"first": 0, "second": 1, "third": 2, "1st": 0, "2nd": 1, "3rd": 2}
            for word, idx in ordinals.items():
                if word in msg_lower and idx < len(available_slots):
                    slot_to_book = available_slots[idx]
                    break

        # Match by requested time against shown slots
        if not slot_to_book and requested_time:
            req_h, req_m = map(int, requested_time.split(":"))
            for s in available_slots:
                parts = str(s.get("start_time", "")).split(":")
                if len(parts) >= 2 and int(parts[0]) == req_h and int(parts[1]) == req_m:
                    slot_to_book = s
                    break

        # If a time was requested but NOT found in the shown slots,
        # immediately fetch and show slots near that time — don't make user ask again.
        if slot_to_book is None and requested_time and not slot_num_match:
            req_h, req_m = map(int, requested_time.split(":"))
            ampm = "AM" if req_h < 12 else "PM"
            display_h = req_h if req_h <= 12 else req_h - 12
            display_h = 12 if display_h == 0 else display_h
            time_str = f"{display_h}:{req_m:02d} {ampm}"

            # Re-fetch ALL free slots for the same doctor+date, filter near requested time
            if state_doctor_id and state_date:
                try:
                    recheck_date = dt_date.fromisoformat(state_date)
                    slot_result2 = get_free_slots_for_doctor_on_date(db, state_doctor_id, recheck_date)
                    all_slots2 = slot_result2.get("slots", [])
                    near_slots = get_slots_near_preferred_time(all_slots2, req_h, req_m, tolerance_hours=2)

                    def fmt_t(t: str) -> str:
                        p = str(t).split(":")
                        return f"{p[0]}:{p[1]}" if len(p) >= 2 else str(t)

                    def slot_start_minutes(s) -> int:
                        """Convert slot start_time to total minutes for sorting."""
                        p = str(s.get("start_time", "0:0")).split(":")
                        return int(p[0]) * 60 + int(p[1]) if len(p) >= 2 else 0

                    def slot_distance(s) -> int:
                        """Absolute distance in minutes from requested time."""
                        return abs(slot_start_minutes(s) - (req_h * 60 + req_m))

                    if near_slots:
                        # Sort: exact match first, then by proximity, then chronologically
                        req_total = req_h * 60 + req_m
                        near_slots.sort(key=lambda s: (
                            0 if slot_start_minutes(s) == req_total else 1,  # exact first
                            slot_distance(s),                                  # nearest next
                            slot_start_minutes(s),                             # then chrono
                        ))
                        shown2 = near_slots[:5]
                        is_exact = slot_start_minutes(shown2[0]) == req_total
                        if is_exact:
                            response = f"✅ Found the **{time_str}** slot!\n\n"
                        else:
                            response = f"⏰ No exact **{time_str}** slot — here are the closest available:\n\n"
                        for i, s in enumerate(shown2, 1):
                            response += f"{i}. {fmt_t(s['start_time'])} – {fmt_t(s['end_time'])}\n"
                        response += "\nSay **'Book slot 1'** to confirm."
                        suggestions = [f"Book slot {i+1}" for i in range(min(3, len(shown2)))]
                        suggestions.append("Show all slots")
                        return Command(
                            update={
                                "response": response,
                                "suggestions": suggestions,
                                "available_slots": shown2,
                                "time": requested_time,
                                "current_step": "slots_shown_near_time",
                            },
                            goto="response_handler",
                        )
                    else:
                        response = (
                            f"😔 No slots available near **{time_str}** for this doctor on this date.\n\n"
                            "Would you like to see all available slots?"
                        )
                        return Command(
                            update={
                                "response": response,
                                "suggestions": ["Show all slots", "Try another date", "Find another doctor"],
                                "time": requested_time,
                                "current_step": "no_slots_near_time",
                            },
                            goto="response_handler",
                        )
                except Exception:
                    pass  # fall through to default slot if re-fetch fails

            # Fallback if no doctor_id in state
            response = (
                f"⏰ I don't see a **{time_str}** slot in the options shown.\n"
                "Please say 'Book slot 1' (or another number) to choose from the list above."
            )
            return Command(
                update={
                    "response": response,
                    "suggestions": ["Book slot 1", "Book slot 2", "Book slot 3"],
                    "current_step": "time_not_found",
                },
                goto="response_handler",
            )

        # Final fallback — default to first slot only if no time was requested
        if not slot_to_book:
            slot_to_book = available_slots[0]

        slot_id = slot_to_book.get("id")
        if not slot_id:
            return Command(
                update={"response": "❌ Could not determine which slot to book. Please say 'Book slot 1'.", "suggestions": ["Book slot 1", "Book slot 2"]},
                goto="response_handler",
            )

        result = await request_appointment_via_bot(db, patient_id, slot_id)

        if result["success"]:
            # Format date: 2026-03-02 → 02 March 2026
            from datetime import date as _dt
            raw_date = result["slot_date"]
            try:
                parsed = _dt.fromisoformat(str(raw_date))
                friendly_date = parsed.strftime("%d %B %Y")
            except Exception:
                friendly_date = str(raw_date)

            # Format time: 13:30:00 → 13:30
            raw_time = str(result["slot_time"])
            parts = raw_time.split(":")
            friendly_time = f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else raw_time

            response = (
                "🎉 **Appointment Requested Successfully!**\n\n"
                f"👨‍⚕️ **Doctor** : Dr. {result['doctor_name']}\n"
                f"📅 **Date** : {friendly_date}\n"
                f"⏰ **Time** : {friendly_time}\n"
                f"📊 **Status** : {result['status']}\n"
                f"⏳ **Approval Deadline** : {result['approval_deadline']}\n\n"
                "The doctor has **24 hours** to approve your request.\n"
                "You\'ll be notified once approved!"
            )
            suggestions = ["Check my appointments", "Book another appointment"]
        else:
            error = result.get("error", "Unknown error")
            response = f"❌ Booking failed: {error}"
            if result.get("existing"):
                apt = result["existing"]
                response += f"\n\n📋 You already have: Dr. {apt['doctor_name']} | {apt['slot_time']}"
            suggestions = ["Try another slot", "Try another date", "Check my appointments"]

        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "booked"},
            goto="response_handler",
        )

    # ── FALLBACK ──────────────────────────────────────────────────────────────
    else:
        response = (
            "📅 I can help you book an appointment!\n\n"
            f"Example: *'Show cardiologist slots for {format_date_friendly(tomorrow)}'*"
        )
        suggestions = [f"Show slots for {format_date_friendly(tomorrow)}", "Find cardiologist", "Help"]
        return Command(update={"response": response, "suggestions": suggestions}, goto="response_handler")