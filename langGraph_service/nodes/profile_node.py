"""
Profile Handler Node
All state access uses dict syntax (state["key"] / state.get("key"))
because ChatbotState is a TypedDict (plain dict at runtime).
"""

from typing import Literal
from datetime import date as dt_date
from pydantic import BaseModel, Field
from langgraph.types import Command
from sqlalchemy.orm import Session

from langGraph_service.schemas.state import ChatbotState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.datetime_tools import parse_date_string
from langGraph_service.tools.profile_tools import (
    get_patient_profile,
    update_patient_name,
    update_patient_dob,
)


class ProfileDecision(BaseModel):
    action: Literal["view_profile", "update_name", "update_dob", "need_name", "need_dob"]
    reasoning: str
    extracted_name: str | None = None
    extracted_dob: str | None = Field(None, description="ISO date YYYY-MM-DD")


async def profile_handler(
    state: ChatbotState,
    db: Session,
) -> Command[Literal["response_handler"]]:

    # ── Read state with dict syntax ───────────────────────────────────────────
    patient_name    = state.get("patient_name", "Patient")
    patient_id      = state["patient_id"]
    user_id         = state["user_id"]
    current_message = state.get("current_message", "")

    structured_llm = llm.with_structured_output(ProfileDecision)

    prompt = f"""
Analyze this profile management request:

Patient: {patient_name}
Message: "{current_message}"

ACTIONS:
1. view_profile  - Show profile ("show profile", "my profile", "view profile", "my info")
2. update_name   - Update name AND new name is provided
3. update_dob    - Update date of birth AND date is provided
4. need_name     - Update name requested but no new name given
5. need_dob      - Update DOB requested but no date given

EXTRACTION:
- Name: text after "to", "as", "is" → e.g. "Update name to Rahul Sharma" → "Rahul Sharma"
- DOB: any date → return as YYYY-MM-DD
  "15 May 1990" → "1990-05-15", "15/05/1990" → "1990-05-15"
"""

    decision: ProfileDecision = structured_llm.invoke(prompt)

    # ── VIEW PROFILE ──────────────────────────────────────────────────────────
    if decision.action == "view_profile":
        profile = get_patient_profile(db, patient_id, user_id)
        if not profile:
            return Command(
                update={"response": "❌ Could not fetch your profile. Please try again.", "suggestions": ["Try again"]},
                goto="response_handler",
            )
        response = (
            "👤 **Your Profile**\n\n"
            f"📛 Name  : {profile['name']}\n"
            f"🎂 DOB   : {profile['dob']}\n"
            f"🎯 Age   : {profile['age']} years\n"
            f"📧 Email : {profile['email']}\n\n"
            "Would you like to update any information?"
        )
        suggestions = ["Update my name", "Update date of birth", "Book an appointment"]
        return Command(
            update={"response": response, "suggestions": suggestions, "profile_data": profile},
            goto="response_handler",
        )

    # ── UPDATE NAME ───────────────────────────────────────────────────────────
    elif decision.action == "update_name":
        new_name = decision.extracted_name
        if not new_name or len(new_name.strip()) < 2:
            return Command(
                update={
                    "response": "Please provide your new name.\n\nExample: *'Update my name to Rahul Sharma'*",
                    "suggestions": ["Cancel", "View my profile"],
                    "current_step": "need_name",
                },
                goto="response_handler",
            )
        result = update_patient_name(db, patient_id, new_name)
        if result["success"]:
            response = f"✅ Your name has been updated to **{result['updated_name']}**!\n\nIs there anything else you'd like to update?"
            suggestions = ["Update date of birth", "View my profile", "Book appointment"]
        else:
            response = f"❌ Failed to update name: {result['error']}"
            suggestions = ["Try again", "View my profile"]
        return Command(update={"response": response, "suggestions": suggestions}, goto="response_handler")

    # ── NEED NAME ─────────────────────────────────────────────────────────────
    elif decision.action == "need_name":
        return Command(
            update={
                "response": "📛 What would you like to update your name to?\n\nExample: *'Update my name to Rahul Sharma'*",
                "suggestions": ["Cancel", "View my profile"],
                "current_step": "need_name",
            },
            goto="response_handler",
        )

    # ── UPDATE DOB ────────────────────────────────────────────────────────────
    elif decision.action == "update_dob":
        date_obj = None
        if decision.extracted_dob:
            try:
                date_obj = dt_date.fromisoformat(decision.extracted_dob)
            except ValueError:
                date_obj = parse_date_string(decision.extracted_dob)
        if not date_obj:
            date_obj = parse_date_string(current_message)

        if not date_obj:
            return Command(
                update={
                    "response": (
                        "Please provide your date of birth in a recognizable format.\n\n"
                        "Examples:\n• *'Update DOB to 15 May 1990'*\n• *'My DOB is 1990-05-15'*"
                    ),
                    "suggestions": ["Cancel", "View my profile"],
                    "current_step": "need_dob",
                },
                goto="response_handler",
            )

        if date_obj >= dt_date.today():
            return Command(
                update={"response": "❌ Date of birth must be in the past.", "suggestions": ["Try again", "View my profile"]},
                goto="response_handler",
            )

        result = update_patient_dob(db, patient_id, date_obj)
        if result["success"]:
            response = (
                f"✅ Date of birth updated to **{result['updated_dob']}**\n"
                f"🎯 Your age is now **{result['age']} years**.\n\nIs there anything else?"
            )
            suggestions = ["Update my name", "View my profile", "Book appointment"]
        else:
            response = f"❌ Failed to update DOB: {result['error']}"
            suggestions = ["Try again", "View my profile"]
        return Command(update={"response": response, "suggestions": suggestions}, goto="response_handler")

    # ── NEED DOB ──────────────────────────────────────────────────────────────
    elif decision.action == "need_dob":
        return Command(
            update={
                "response": "🎂 What is your date of birth?\n\nExamples:\n• *'15 May 1990'*\n• *'1990-05-15'*\n• *'15/05/1990'*",
                "suggestions": ["Cancel", "View my profile"],
                "current_step": "need_dob",
            },
            goto="response_handler",
        )

    # ── FALLBACK ──────────────────────────────────────────────────────────────
    else:
        return Command(
            update={
                "response": (
                    "👤 **Profile Management**\n\n"
                    "I can help you:\n• **View** your profile\n• **Update your name**\n• **Update your date of birth**\n\nWhat would you like to do?"
                ),
                "suggestions": ["View my profile", "Update my name", "Update date of birth"],
            },
            goto="response_handler",
        )