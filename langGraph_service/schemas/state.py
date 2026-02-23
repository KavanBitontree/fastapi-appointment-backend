"""
LangGraph Shared State — Agentic Architecture
Uses messages list as the primary communication backbone (LangChain standard).
add_messages reducer appends new messages instead of replacing the whole list,
so every node in the graph sees the full conversation history.

Identity fields (user_id, patient_id, patient_name) are set once per session
and persisted by the AsyncSqliteSaver checkpointer across turns.

route_to is set by the supervisor and read by the graph's conditional edge
to decide which specialist agent to invoke.

MESSAGE TRIMMING: Configured to keep last 20 messages (10 turns) to prevent
token overflow and maintain reasonable context window.
"""

from typing import Annotated, Optional, List, TypedDict
from langchain_core.messages import BaseMessage, trim_messages
from langgraph.graph.message import add_messages


# Configure message trimming to keep last 20 messages (10 user + 10 assistant turns)
# This prevents token overflow while maintaining sufficient context
MESSAGE_HISTORY_LIMIT = 20  # Adjust this value as needed (10, 20, 30, etc.)


def trim_message_history(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Trim message history to keep only recent messages.
    Keeps the last MESSAGE_HISTORY_LIMIT messages.
    """
    if len(messages) <= MESSAGE_HISTORY_LIMIT:
        return messages
    return messages[-MESSAGE_HISTORY_LIMIT:]


class AgenticState(TypedDict, total=False):

    # ── Conversation history ───────────────────────────────────────────────────
    # add_messages is LangGraph's built-in reducer: new messages are APPENDED,
    # not replaced. This gives every agent full conversation context.
    messages: Annotated[List[BaseMessage], add_messages]

    # ── Patient identity (set once, persisted by checkpointer) ───────────────
    user_id: int
    patient_id: int
    patient_name: str

    # ── Current turn raw input ────────────────────────────────────────────────
    current_message: str

    # ── Supervisor routing ────────────────────────────────────────────────────
    # Supervisor sets this; conditional edge reads it to pick the next agent.
    route_to: Optional[str]   # "appointment" | "doctor" | "nearby" | "profile" | "FINISH"
    supervisor_reasoning: Optional[str]

    # ── Location (for nearby-doctor queries) ─────────────────────────────────
    patient_lat: Optional[float]
    patient_lon: Optional[float]

    # ── Appointment booking cache (avoids re-running slot discovery on confirmation) ──
    # Set by appointment_node when slots are presented; cleared after booking.
    pending_slot_id: Optional[int]          # slot_id the user is about to confirm
    pending_doctor_name: Optional[str]      # for confirmation message
    pending_slot_date: Optional[str]        # YYYY-MM-DD
    pending_slot_time: Optional[str]        # "HH:MM - HH:MM"

    # ── Final API response fields (populated by response_formatter) ───────────
    response: Optional[str]
    suggestions: Optional[List[str]]