"""
Nearby Doctors Handler Node
The frontend (AarogyaAssistant.tsx) now handles the browser geolocation permission flow
and always sends lat/lon in the request body when a nearby query is detected.
This node can therefore assume coordinates are present; if not, it means the user
denied permission and the frontend already showed an error — we just show a fallback.
"""

from typing import Literal
from pydantic import BaseModel, Field
from langgraph.types import Command
from sqlalchemy.orm import Session
import re

from langGraph_service.schemas.state import ChatbotState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.doctor_tools import find_nearby_doctors, get_all_specialities


class NearbyDoctorDecision(BaseModel):
    action: Literal["search_nearby", "no_location"]
    reasoning: str
    extracted_speciality: str | None = None
    max_distance_km: float = Field(default=10.0)


async def nearby_doctor_handler(
    state: ChatbotState,
    db: Session,
) -> Command[Literal["response_handler"]]:
    """
    Find nearby doctors using coordinates passed by the frontend.

    Flow:
    - Frontend detects nearby-doctor keywords → triggers browser geolocation
    - On permission grant, frontend sends lat/lon in the API request body
    - process_message() merges them into state as patient_lat / patient_lon
    - This node reads them and queries the DB
    """

    # ── Read state ────────────────────────────────────────────────────────────
    patient_name     = state.get("patient_name", "Patient")
    current_message  = state.get("current_message", "")
    state_speciality = state.get("speciality")
    active_lat       = state.get("patient_lat")
    active_lon       = state.get("patient_lon")

    # Also try to parse coordinates typed inline, e.g. "28.6139, 77.2090"
    if not active_lat or not active_lon:
        coord_match = re.search(r'(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)', current_message)
        if coord_match:
            try:
                active_lat = float(coord_match.group(1))
                active_lon = float(coord_match.group(2))
            except ValueError:
                pass

    # ── No coordinates available ──────────────────────────────────────────────
    # This branch only runs if the frontend somehow didn't send coords.
    if not active_lat or not active_lon:
        response = (
            "📍 I need your location to find nearby doctors.\n\n"
            "Please try again — your browser will ask for location permission."
        )
        suggestions = ["Find doctors near me", "Find cardiologist", "Show all doctors"]
        return Command(
            update={"response": response, "suggestions": suggestions, "current_step": "no_location"},
            goto="response_handler",
        )

    # ── LLM: extract speciality / distance preference ─────────────────────────
    structured_llm = llm.with_structured_output(NearbyDoctorDecision)

    prompt = f"""
Patient: {patient_name}
Message: "{current_message}"
Speciality already in state: {state_speciality or "None"}
Coordinates available: yes ({active_lat}, {active_lon})

Decide:
- action: always "search_nearby" since we have coordinates
- extracted_speciality: if user mentioned a speciality ("nearby cardiologist", "dentist near me")
- max_distance_km: default 10, lower if user says "within 5 km", higher if "within 20 km"
"""

    decision: NearbyDoctorDecision = structured_llm.invoke(prompt)
    speciality = decision.extracted_speciality or state_speciality
    max_dist = decision.max_distance_km or 10.0

    # ── DB query ──────────────────────────────────────────────────────────────
    doctors = find_nearby_doctors(
        db=db,
        patient_lat=active_lat,
        patient_lon=active_lon,
        max_distance_km=max_dist,
        speciality=speciality,
        limit=10,
    )

    # ── No results ────────────────────────────────────────────────────────────
    if not doctors:
        spec_note = f" **{speciality}**" if speciality else ""
        expanded = int(max_dist * 2)
        response = (
            f"😔 No{spec_note} doctors found within **{max_dist} km** of your location.\n\n"
            f"Would you like to expand the search to **{expanded} km**, "
            "or search by specialization without a distance limit?"
        )
        suggestions = [
            f"Find{' ' + speciality if speciality else ''} doctors within {expanded} km",
            "Find cardiologist",
            "Show all doctors",
        ]
        return Command(
            update={
                "response": response,
                "suggestions": suggestions,
                "patient_lat": active_lat,
                "patient_lon": active_lon,
                "current_step": "no_nearby_doctors",
            },
            goto="response_handler",
        )

    # ── Results ───────────────────────────────────────────────────────────────
    spec_header = f" **{speciality}**" if speciality else ""
    response = (
        f"📍 Found **{len(doctors)}{spec_header} doctor(s)** near you "
        f"(within {max_dist} km):\n\n"
    )
    for i, d in enumerate(doctors, 1):
        response += f"{i}. **Dr. {d['name']}** — {d['speciality']}\n"
        response += f"   💰 ₹{d['opd_fees']} | 📏 {d['distance_km']} km away | 📍 {d['address']}\n\n"
    response += "Would you like to see available slots for any of these doctors?"

    suggestions = [f"Show slots for Dr. {d['name']}" for d in doctors[:3]]
    suggestions.append("Find a different specialization")

    return Command(
        update={
            "response": response,
            "suggestions": suggestions,
            "doctors_list": doctors,
            "patient_lat": active_lat,
            "patient_lon": active_lon,
            "current_step": "nearby_doctors_shown",
        },
        goto="response_handler",
    )