"""
Supervisor Node — Supervisor-Worker Pattern
============================================

Key fixes vs original:
  1. Messages are seeded as HumanMessage in input_state (graph.py) BEFORE
     supervisor runs — so messages list is never empty on first turn.
  2. Removed "first turn == 1 message → inline" special case that caused
     ALL first-turn queries (including real medical ones) to return a greeting.
  3. Out-of-scope messages (bikes, food, etc.) now get a proper rejection
     response instead of a greeting.
  4. add_conditional_edges support via make_supervisor_router() so graph PNG
     shows all supervisor→worker edges statically.
  5. Workers tag their AIMessage with name= so supervisor can detect
     "worker just responded" correctly.
"""

from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command
from langgraph.graph import END

from langGraph_service.schemas.state import AgenticState
from langGraph_service.config.llm_init import llm


_NextLiteral = Literal[
    "appointment_node",
    "doctor_node",
    "nearby_node",
    "profile_node",
    "FINISH",
]

_WorkerOrEnd = Literal[
    "appointment_node",
    "doctor_node",
    "nearby_node",
    "profile_node",
    "__end__",
]

WORKER_DESCRIPTIONS = {
    "appointment_node": (
        "Specialist for booking appointments, checking slot availability, "
        "viewing existing appointments, and handling the 25-hour advance rule."
    ),
    "doctor_node": (
        "Specialist for searching doctors by name or medical speciality, "
        "listing all doctors, and listing available specialities."
    ),
    "nearby_node": (
        "Specialist for finding doctors near the patient's current location "
        "using GPS coordinates. Use when patient asks 'doctors near me' or "
        "'nearby <speciality>'."
    ),
    "profile_node": (
        "Specialist for viewing and updating the patient's profile: "
        "name and date of birth."
    ),
}

WORKER_INFO = "\n\n".join(
    f"WORKER: {name}\nDESCRIPTION: {desc}"
    for name, desc in WORKER_DESCRIPTIONS.items()
) + (
    "\n\nWORKER: FINISH\n"
    "DESCRIPTION: Use ONLY for (a) pure greetings like 'hello'/'hi' with NO other intent, "
    "(b) capability/help questions, (c) completely out-of-scope topics unrelated to "
    "healthcare (e.g. bikes, food, travel, weather), OR (d) a worker already fully "
    "answered the query."
)

SUPERVISOR_SYSTEM_PROMPT = (
    "You are a supervisor managing a team of specialized healthcare assistant agents.\n\n"
    "## YOUR WORKERS\n"
    f"{WORKER_INFO}\n\n"
    "## ROUTING RULES — follow in order\n\n"
    "1. Pure greeting ONLY ('hello', 'hi', 'hey', 'namaste') with no other intent → FINISH\n"
    "2. Help / capability question → FINISH\n"
    "3. Completely off-topic (bikes, recipes, weather, sports, etc.) → FINISH\n"
    "4. Appointment booking / view slots / check my appointments → appointment_node\n"
    "5. Search/find doctor by name or speciality / list doctors → doctor_node\n"
    "6. 'near me' / 'nearby' / location-based doctor search → nearby_node\n"
    "7. View profile / update name / update date of birth → profile_node\n"
    "8. Worker just responded AND query is fully answered → FINISH\n\n"
    "## CRITICAL — never mis-route these\n"
    "These phrases ALL have medical intent and must NEVER go to FINISH on first pass:\n"
    "  'book appointment', 'book a slot', 'show slots', 'available slots',\n"
    "  'find cardiologist', 'find doctor', 'view my appointments', 'check appointments',\n"
    "  'doctors near me', 'nearby doctor', 'update my name', 'view my profile',\n"
    "  'book another appointment' (suggestion clicked by user)\n\n"
    "When in doubt between FINISH and a worker → always pick the worker.\n\n"
    "Respond with the worker name or FINISH, plus one-sentence reasoning."
)


class Router(TypedDict):
    next: Annotated[
        _NextLiteral,
        ...,
        "Worker to route to, or FINISH.",
    ]
    reasoning: Annotated[str, ..., "One-sentence reasoning."]


def make_supervisor(llm_instance=None):
    _llm = llm_instance or llm
    _router_llm = _llm.with_structured_output(Router)

    def supervisor_node(state: AgenticState) -> Command[_WorkerOrEnd]:
        messages = list(state.get("messages") or [])
        patient_name = state.get("patient_name", "Patient")
        current_message = state.get("current_message", "")
        # Reset output fields at start of each turn (graph.py no longer does this
        # in input_state to avoid clobbering values mid-graph).
        # These will be set correctly by whichever path we take below.

        # Safety fallback: if messages empty (shouldn't happen after graph.py fix)
        if not messages and current_message:
            messages = [HumanMessage(content=current_message)]

        if not messages:
            return Command(
                update={"route_to": "FINISH", "response": "How can I help you?"},
                goto=END,
            )

        last_msg = messages[-1]
        last_content = getattr(last_msg, "content", "") or ""

        # Detect if last message came from a worker agent
        worker_just_responded = (
            isinstance(last_msg, AIMessage)
            and getattr(last_msg, "name", None) in WORKER_DESCRIPTIONS
        )

        # ── FAST PATH A: pending slot → always go to appointment_node ─────────
        # "Yes" with no context gets misrouted by the LLM router (e.g. to profile).
        # State carries pending_slot_id so we skip the router entirely.
        pending_slot_id = state.get("pending_slot_id")
        if pending_slot_id and isinstance(last_msg, HumanMessage):
            return Command(
                update={
                    "messages": messages,
                    "route_to": "appointment_node",
                    "supervisor_reasoning": "Pending slot — bypassing LLM router, going to appointment_node.",
                },
                goto="appointment_node",
            )

        # ── FAST PATH B: worker just responded → FINISH ───────────────────────
        if worker_just_responded:
            return Command(
                update={
                    "messages": messages,
                    "route_to": "FINISH",
                    "supervisor_reasoning": "Worker just responded — routing to FINISH directly.",
                    "response": last_content,
                    "suggestions": _extract_suggestions(last_content),
                },
                goto=END,
            )


        routing_messages = [
            {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Patient: {patient_name}\n"
                    f"Worker just responded: {worker_just_responded}\n\n"
                    f"Latest message:\n{last_content}"
                ),
            },
        ]

        response: Router = _router_llm.invoke(routing_messages)
        next_worker = response["next"]
        reasoning = response["reasoning"]

        # FINISH path
        if next_worker == "FINISH":
            if worker_just_responded:
                final_response = last_content
                extra_messages = []
            else:
                final_response = _generate_inline_response(last_content, patient_name)
                extra_messages = [AIMessage(content=final_response, name="supervisor")]

            return Command(
                update={
                    "messages": messages + extra_messages,
                    "route_to": "FINISH",
                    "supervisor_reasoning": reasoning,
                    "response": final_response,
                    "suggestions": _extract_suggestions(final_response, last_content),
                },
                goto=END,
            )

        # Route to worker
        return Command(
            update={
                "messages": messages,
                "route_to": next_worker,
                "supervisor_reasoning": reasoning,
            },
            goto=next_worker,
        )

    return supervisor_node


def make_supervisor_router():
    """
    Plain routing function for add_conditional_edges() so the graph PNG
    shows supervisor→worker edges statically.
    """
    def router(state: AgenticState) -> _WorkerOrEnd:
        route = state.get("route_to") or "FINISH"
        if route == "FINISH":
            return "__end__"
        return route  # type: ignore[return-value]
    return router


def _generate_inline_response(user_message: str, patient_name: str) -> str:
    msg_lower = user_message.lower()

    if any(w in msg_lower for w in ["hello", "hi", "hey", "namaste", "hola"]):
        return (
            f"Hello **{patient_name}**!\n\n"
            "I'm **Aarogya Assistant**, your healthcare companion. Here's what I can do:\n\n"
            "• Find doctors by specialization\n"
            "• Find doctors near your location\n"
            "• Book & manage appointments\n"
            "• View & update your profile\n\n"
            "How can I assist you today?"
        )

    if any(w in msg_lower for w in ["help", "what can you", "features", "capabilities"]):
        return (
            "**Aarogya Assistant — What I Can Do**\n\n"
            "**Appointments:**\n"
            "• 'Show slots for tomorrow'\n"
            "• 'Book appointment with Dr. Sharma for 25 March'\n"
            "• 'Check my appointments'\n\n"
            "**Find Doctors:**\n"
            "• 'Find cardiologist'\n"
            "• 'Search for Dr. Rajeev Shukla'\n"
            "• 'List all specializations'\n\n"
            "**Nearby Doctors:**\n"
            "• 'Find doctors near me'\n"
            "• 'Nearby cardiologist'\n\n"
            "**Profile:**\n"
            "• 'View my profile'\n"
            "• 'Update my name to John Doe'\n"
            "• 'Change my DOB to 15 May 1990'\n\n"
            "Just ask naturally and I'll help!"
        )

    # Out-of-scope (bikes, weather, food, etc.)
    return (
        "I'm specialized in healthcare services and can't help with that.\n\n"
        "Here's what I **can** help you with:\n"
        "• Find and book doctor appointments\n"
        "• Search for doctors by specialization or location\n"
        "• Check your appointment status\n"
        "• Update your profile\n\n"
        "Is there anything health-related I can assist you with?"
    )


def _get_default_suggestions() -> list:
    return [
        "Find available slots for tomorrow",
        "Search for cardiologist",
        "Find doctors near me",
        "View my profile",
    ]


def _extract_suggestions(response_text: str, original_query: str = "") -> list:
    text_lower = response_text.lower()
    if "slot" in text_lower or "appointment" in text_lower:
        return ["Book another appointment", "Check my appointments", "Find another doctor"]
    if "doctor" in text_lower or "speciality" in text_lower or "specialization" in text_lower:
        return ["Show slots for tomorrow", "Find another doctor", "Find doctors near me"]
    if "profile" in text_lower or "name" in text_lower or "dob" in text_lower:
        return ["Update my name", "Update date of birth", "Book an appointment"]
    return _get_default_suggestions()