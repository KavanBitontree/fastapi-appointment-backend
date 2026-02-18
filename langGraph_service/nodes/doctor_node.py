"""
Doctor Search Handler Node
All state access uses dict syntax (state["key"] / state.get("key"))
because ChatbotState is a TypedDict (plain dict at runtime).
"""

from typing import Literal
from pydantic import BaseModel, Field
from langgraph.types import Command
from sqlalchemy.orm import Session

from langGraph_service.schemas.state import ChatbotState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.doctor_tools import (
    search_doctors_by_name,
    search_doctors_by_speciality,
    get_all_doctors,
    get_all_specialities,
)


class DoctorSearchDecision(BaseModel):
    action: Literal["search_by_name", "search_by_speciality", "list_specialities", "show_all"]
    reasoning: str
    extracted_name: str | None = None
    extracted_speciality: str | None = None


async def doctor_handler(
    state: ChatbotState,
    db: Session,
) -> Command[Literal["response_handler", "appointment_handler"]]:

    # ── Read state with dict syntax ───────────────────────────────────────────
    patient_name    = state.get("patient_name", "Patient")
    current_message = state.get("current_message", "")
    state_doctor_name = state.get("doctor_name")
    state_speciality  = state.get("speciality")
    state_date        = state.get("date")
    user_id           = state["user_id"]
    has_date          = bool(state_date)
    all_specs_till_now = get_all_specialities(db)

    structured_llm = llm.with_structured_output(DoctorSearchDecision)

    prompt = f"""
Analyze this doctor search request:

Patient: {patient_name}
Message: "{current_message}"
Already extracted:
  doctor_name = {state_doctor_name or "None"}
  speciality  = {state_speciality or "None"}
  date        = {state_date or "None"}

ACTIONS:
1. search_by_name       - Doctor name mentioned
2. search_by_speciality - Speciality mentioned
3. list_specialities    - User wants to see all specializations available
4. show_all             - General "show all doctors" request

Extract doctor name (without Dr. prefix) or speciality.
Prefer already-extracted values from context above.

Speciality should be from {", ".join(all_specs_till_now[:10])}
Please use **correct spellings** for specialities to ensure accurate DB search results.

Common conversions:
"heart doctor" → Cardiologist, "skin doctor" → Dermatologist,
"child doctor" → Paediatrician, "bone doctor" → Orthopaedic,
"eye doctor" → Ophthalmologist
"""

    decision: DoctorSearchDecision = structured_llm.invoke(prompt)

    # ── Search by name ────────────────────────────────────────────────────────
    if decision.action == "search_by_name":
        name = decision.extracted_name or state_doctor_name
        if not name:
            return Command(
                update={"response": "Please provide the doctor's name.", "suggestions": ["Find cardiologist", "Show all doctors"]},
                goto="response_handler",
            )

        doctors = search_doctors_by_name(db, name)
        if not doctors:
            response = f"😔 No doctor found matching **'{name}'**.\n\nTry searching by specialization."
            return Command(
                update={"response": response, "suggestions": ["Find cardiologist", "Show all doctors", "List all specializations"]},
                goto="response_handler",
            )

        if len(doctors) == 1:
            d = doctors[0]
            response = (
                f"✅ Found **Dr. {d['name']}**!\n\n"
                f"🔬 Speciality : {d['speciality']}\n"
                f"💰 Fees       : ₹{d['opd_fees']}\n"
                f"📍 Address    : {d['address']}\n\n"
                "Would you like to see available slots?"
            )
            suggestions = [f"Show slots for Dr. {d['name']}", "Find another doctor"]
            update = {
                "response": response, "suggestions": suggestions,
                "doctor_id": d["id"], "doctor_name": d["name"], "doctors_list": doctors,
            }
            if has_date:
                update["current_step"] = "doctor_found"
                return Command(update=update, goto="appointment_handler")
            return Command(update=update, goto="response_handler")

        response = f"👨‍⚕️ Found **{len(doctors)} doctors** matching '{name}':\n\n"
        for i, d in enumerate(doctors[:5], 1):
            response += f"{i}. **Dr. {d['name']}** — {d['speciality']} | 💰 ₹{d['opd_fees']}\n"
            response += f"   📍 {d['address']}\n\n"
        response += "Which doctor would you like to book with?"
        suggestions = [f"Show slots for Dr. {d['name']}" for d in doctors[:3]]
        return Command(
            update={"response": response, "suggestions": suggestions, "doctors_list": doctors[:5]},
            goto="response_handler",
        )

    # ── Search by speciality ──────────────────────────────────────────────────
    elif decision.action == "search_by_speciality":
        speciality = decision.extracted_speciality or state_speciality
        if not speciality:
            return Command(
                update={"response": "Which specialization are you looking for?", "suggestions": ["Cardiologist", "Dermatologist", "List all"]},
                goto="response_handler",
            )

        doctors = search_doctors_by_speciality(db, speciality)
        if not doctors:
            all_specs = all_specs_till_now
            response = f"😔 No doctors found for **'{speciality}'**.\n\n"
            if all_specs:
                response += "Available specializations:\n" + "\n".join(f"• {s}" for s in all_specs[:10])
            return Command(
                update={"response": response, "suggestions": ["Show all doctors", "List all specializations"]},
                goto="response_handler",
            )

        response = f"👨‍⚕️ Found **{len(doctors)} {speciality} doctor(s)**:\n\n"
        for i, d in enumerate(doctors[:5], 1):
            response += f"{i}. **Dr. {d['name']}** — {d['speciality']}\n"
            response += f"   💰 ₹{d['opd_fees']} | 📍 {d['address']}\n\n"
        response += "Would you like to see slots for any of these doctors?"

        suggestions = [f"Show slots for Dr. {d['name']}" for d in doctors[:3]]
        update = {
            "response": response, "suggestions": suggestions,
            "doctors_list": doctors[:5], "speciality": speciality,
        }
        if has_date and doctors:
            update["doctor_id"] = doctors[0]["id"]
            update["doctor_name"] = doctors[0]["name"]
            update["current_step"] = "doctor_found_by_speciality"
            return Command(update=update, goto="appointment_handler")
        return Command(update=update, goto="response_handler")

    # ── List specialities ─────────────────────────────────────────────────────
    elif decision.action == "list_specialities":
        specs = get_all_specialities(db)
        if not specs:
            return Command(
                update={"response": "No specializations found right now.", "suggestions": ["Show all doctors"]},
                goto="response_handler",
            )
        response = "🏥 **Available Specializations:**\n\n"
        response += "\n".join(f"• {s}" for s in specs)
        response += "\n\nWhich specialization are you interested in?"
        suggestions = [f"Find {s}" for s in specs[:4]]
        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "specialities_shown"},
            goto="response_handler",
        )

    # ── Show all ──────────────────────────────────────────────────────────────
    else:
        result = get_all_doctors(db, limit=10)
        doctors = result["doctors"]
        if not doctors:
            return Command(update={"response": "No doctors found in the system.", "suggestions": ["Try again later"]}, goto="response_handler")

        response = f"👨‍⚕️ **{result['total']} Doctors Available** (showing first {len(doctors)}):\n\n"
        for i, d in enumerate(doctors, 1):
            response += f"{i}. **Dr. {d['name']}** — {d['speciality']}\n"
            response += f"   💰 ₹{d['opd_fees']} | 📍 {d['address']}\n\n"
        response += "Search by specialization or pick a doctor to see slots."

        suggestions = ["Find cardiologist", "List all specializations", f"Show slots for Dr. {doctors[0]['name']}"]
        return Command(
            update={"response": response, "suggestions": suggestions, "doctors_list": doctors, "current_step": "all_doctors_shown"},
            goto="response_handler",
        )