"""
Response Handler Node (END node)
Handles: greeting, help, out-of-scope, and pass-through responses from other nodes.
All state access uses dict syntax (state["key"] / state.get("key"))
because ChatbotState is a TypedDict (plain dict at runtime).
"""

from typing import Literal
from langgraph.types import Command
from langgraph.graph import END

from langGraph_service.schemas.state import ChatbotState


def response_handler(state: ChatbotState) -> Command[Literal["__end__"]]:
    """
    Final node — if response already set by another node, just end.
    Otherwise generate greeting / help / out-of-scope response.
    """

    # ── Read state with dict syntax ───────────────────────────────────────────
    response     = state.get("response")
    classification = state.get("classification")
    patient_name = state.get("patient_name", "there")

    # If a prior node already set the response, just terminate
    if response:
        return Command(update={"current_step": "done"}, goto=END)

    intent = classification.intent if classification else "unknown"

    # ── Greeting ──────────────────────────────────────────────────────────────
    if intent == "greeting":
        response = (
            f"👋 Hello **{patient_name}**!\n\n"
            "I'm **Aarogya Assistant (AA)**, your healthcare companion.\n\n"
            "Here's what I can help you with:\n"
            "🔍 Find doctors by specialization\n"
            "📍 Find doctors near your location\n"
            "📅 Book & manage appointments\n"
            "⏰ Check available slots\n"
            "👤 View & update your profile\n\n"
            "How can I assist you today?"
        )
        suggestions = [
            "Find available slots for tomorrow",
            "Search for cardiologist",
            "Find doctors near me",
            "View my profile",
        ]

    # ── Help ──────────────────────────────────────────────────────────────────
    elif intent == "help":
        response = (
            "🤖 **Aarogya Assistant — Help Guide**\n\n"
            "**📅 APPOINTMENTS:**\n"
            "• 'Show slots for tomorrow'\n"
            "• 'Book appointment with Dr. Smith for 25 March'\n"
            "• 'Check my appointments'\n\n"
            "**🔍 FIND DOCTORS:**\n"
            "• 'Find cardiologist'\n"
            "• 'Search for Dr. Rajeev Shukla'\n"
            "• 'List all specializations'\n\n"
            "**📍 NEARBY DOCTORS:**\n"
            "• 'Find doctors near me'\n"
            "• 'Nearby cardiologist'\n\n"
            "**👤 PROFILE:**\n"
            "• 'View my profile'\n"
            "• 'Update my name to John Doe'\n"
            "• 'Change my DOB to 15 May 1990'\n\n"
            "Just ask me naturally and I'll help!"
        )
        suggestions = [
            "Find available slots",
            "Search doctors",
            "Find doctors near me",
            "View my profile",
        ]

    # ── Out of scope ──────────────────────────────────────────────────────────
    elif intent == "out_of_scope":
        response = (
            "🏥 I'm specialized in **healthcare appointment management**.\n\n"
            "I'm not able to help with that specific query, but I can assist with:\n"
            "• Finding & booking doctor appointments\n"
            "• Searching for doctors by specialization or location\n"
            "• Checking your appointment status\n"
            "• Updating your profile\n\n"
            "Is there anything health-related I can help you with?"
        )
        suggestions = [
            "Find available slots",
            "Search for doctors",
            "Check my appointments",
            "Help",
        ]

    # ── Fallback ──────────────────────────────────────────────────────────────
    else:
        response = (
            "🏥 I'm here to help with healthcare appointments!\n\n"
            "You can ask me to:\n"
            "• Find or book doctor appointments\n"
            "• Search for specialists\n"
            "• Find nearby doctors\n"
            "• Manage your profile\n\n"
            "What would you like to do?"
        )
        suggestions = ["Find available slots", "Search doctors", "Find doctors near me", "Help"]

    return Command(
        update={"response": response, "suggestions": suggestions, "current_step": "done"},
        goto=END,
    )