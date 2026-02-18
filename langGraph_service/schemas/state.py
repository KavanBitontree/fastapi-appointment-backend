"""
LangGraph Shared State
Uses TypedDict (not Pydantic BaseModel) so LangGraph can properly merge
partial state updates across conversation turns via its reducer mechanism.

FIX — INVALID_CONCURRENT_GRAPH_UPDATE on current_step:
  When classify_intent uses Command(goto=handler), both nodes run in the same
  LangGraph super-step. If both write to current_step, LangGraph crashes with
  INVALID_CONCURRENT_GRAPH_UPDATE because TypedDict keys are single-writer by default.

  Solution: Annotate current_step with a reducer function (_keep_last).
  This tells LangGraph HOW to merge concurrent writes instead of crashing.
  _keep_last simply takes the newest value — whichever node wrote last wins.

  This is the correct, idiomatic LangGraph fix. No node files need changing.
"""

from typing import Annotated, Optional, List, Dict, Any, TypedDict
from pydantic import BaseModel, Field


def _keep_last(old: Any, new: Any) -> Any:
    """
    Reducer for fields that may be written by multiple nodes in the same super-step.
    Takes the newest value. 'new' is None only if a node explicitly sets it to None,
    in which case we preserve the old value to avoid losing context.
    """
    if new is None:
        return old
    return new


class IntentClassification(BaseModel):
    """Structured output from the classifier node."""
    intent: str = Field(
        description="One of: appointment, doctor_search, nearby_doctors, profile, greeting, help, out_of_scope"
    )
    confidence: float = Field(default=0.8)
    entities: Optional[Dict[str, Any]] = Field(default=None)
    summary: str = Field(default="")
    reasoning: str = Field(default="")


class ChatbotState(TypedDict, total=False):
    """
    Shared state for the LangGraph chatbot.

    WHY TypedDict instead of Pydantic BaseModel?
    - LangGraph merges state updates between nodes using dict-style partial updates.
    - With BaseModel, ainvoke() replaces the whole state, losing context from prior turns.
    - With TypedDict, only the keys explicitly returned by a node are updated; the rest
      carry over from the previous checkpoint automatically.

    This means available_slots, doctor_id, date etc. set in turn N
    are still available when the user follows up in turn N+1 ("Book slot 1").

    WHY Annotated on current_step (and response/suggestions)?
    - classify_intent and the destination handler both run in the same super-step
      when Command(goto=...) is used.
    - Both nodes write current_step → LangGraph crashes without a reducer.
    - Annotated[type, _keep_last] registers a merge function so concurrent writes
      are resolved by taking the newest value instead of raising an error.
    """

    # ── Identity (required on first message, persisted via checkpointer) ─────
    user_id: int
    patient_id: int
    patient_name: str

    # ── Current turn ──────────────────────────────────────────────────────────
    current_message: str
    # response and suggestions are also annotated because response_handler
    # writes them after another handler already wrote them in some code paths.
    response: Annotated[Optional[str], _keep_last]
    suggestions: Annotated[Optional[List[str]], _keep_last]

    # ── Classification (set by classifier each turn) ──────────────────────────
    classification: Optional[IntentClassification]

    # ── Extracted entities ────────────────────────────────────────────────────
    # These PERSIST across turns — "Book slot 1" can still see the date/doctor
    # that was set in the previous "Show slots for Dr. X on Y" turn.
    date: Optional[str]           # YYYY-MM-DD
    time: Optional[str]           # HH:MM 24hr
    speciality: Optional[str]
    doctor_name: Optional[str]
    doctor_id: Optional[int]

    # ── Patient location ──────────────────────────────────────────────────────
    patient_lat: Optional[float]
    patient_lon: Optional[float]

    # ── Conversation step tracking ─────────────────────────────────────────────
    # Annotated with _keep_last — both classifier and handler write this field
    # in the same super-step, which would crash without a reducer.
    current_step: Annotated[Optional[str], _keep_last]

    # ── Payload caches (persist so follow-up messages can reference them) ─────
    available_slots: Optional[List[Dict[str, Any]]]   # Slots shown in previous turn
    doctors_list: Optional[List[Dict[str, Any]]]
    profile_data: Optional[Dict[str, Any]]

    # ── Error tracking ────────────────────────────────────────────────────────
    error: Optional[str]