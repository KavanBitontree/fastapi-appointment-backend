"""
LangGraph Main Graph
Orchestrates the chatbot conversation flow with full multi-turn context awareness.

CONTEXT AWARENESS DESIGN:
- State is TypedDict, so LangGraph merges partial updates (only changed keys overwritten).
- Before each ainvoke(), we load the latest checkpoint and merge persisted fields
  (available_slots, doctor_id, date, etc.) into the new message's input.
- This means "Book slot 1" in turn N+1 can see the slots shown in turn N.
- thread_id = user_{user_id} for per-user session isolation.
- AsyncSqliteSaver is fully async — always use aget_state_history, never get_state_history.

GRAPH FLOW:
  START
    │
    ▼
  classify_intent ──(conditional)──► appointment_handler ─┐
                                  ► doctor_handler        ─┤──► response_handler ──► END
                                  ► nearby_doctor_handler ─┤         ▲
                                  ► profile_handler       ─┘         │
                                  ► response_handler ────────────────┘
                                    (greeting/help/out_of_scope)

  RUNTIME JUMPS (via Command, shown as dashed in PNG):
    doctor_handler ──────────────────────────────────────► appointment_handler
    (when doctor found + date already in context)
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import RetryPolicy
from sqlalchemy.orm import Session
from functools import partial
import aiosqlite
from pathlib import Path
import traceback

from langGraph_service.schemas.state import ChatbotState
from langGraph_service.nodes.classifier_node import classify_intent
from langGraph_service.nodes.appointment_node import appointment_handler
from langGraph_service.nodes.doctor_node import doctor_handler
from langGraph_service.nodes.nearby_doctor_node import nearby_doctor_handler
from langGraph_service.nodes.profile_node import profile_handler
from langGraph_service.nodes.response_node import response_handler


# ── Checkpointer singleton ────────────────────────────────────────────────────

_checkpointer_instance: AsyncSqliteSaver | None = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """Lazily create and return the shared AsyncSQLite checkpointer."""
    global _checkpointer_instance
    if _checkpointer_instance is None:
        db_path = Path(__file__).parent.parent / "chat_checkpoints.db"
        conn = await aiosqlite.connect(str(db_path))
        _checkpointer_instance = AsyncSqliteSaver(conn)
    return _checkpointer_instance


# ── Intent router (conditional edge) ─────────────────────────────────────────

def _route_intent(state: ChatbotState) -> str:
    """
    Reads classification set by classify_intent and returns the next node name.
    greeting / help / out_of_scope skip domain handlers and go straight to response_handler.
    """
    classification = state.get("classification")
    intent = classification.intent if classification else "out_of_scope"

    return {
        "appointment":    "appointment_handler",
        "doctor_search":  "doctor_handler",
        "nearby_doctors": "nearby_doctor_handler",
        "profile":        "profile_handler",
        "greeting":       "response_handler",
        "help":           "response_handler",
        "out_of_scope":   "response_handler",
    }.get(intent, "response_handler")


# ── Graph builder ─────────────────────────────────────────────────────────────

def _build_app(db: Session, checkpointer: AsyncSqliteSaver):
    """
    Build and compile the StateGraph with all nodes bound to the DB session.

    Edge structure:
      START → classify_intent
      classify_intent →(conditional)→ [appointment_handler | doctor_handler |
                                        nearby_doctor_handler | profile_handler |
                                        response_handler]
      [all domain handlers] → response_handler   (declared for graph viz/LangSmith)
      response_handler → END

    Runtime jumps (Command-based, shown as dashed edges in PNG):
      doctor_handler → appointment_handler  (when doctor found + date in context)
    """
    workflow = StateGraph(ChatbotState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node(
        "appointment_handler",
        partial(appointment_handler, db=db),
        retry=RetryPolicy(max_attempts=3),
    )
    workflow.add_node(
        "doctor_handler",
        partial(doctor_handler, db=db),
        retry=RetryPolicy(max_attempts=3),
    )
    workflow.add_node(
        "nearby_doctor_handler",
        partial(nearby_doctor_handler, db=db),
        retry=RetryPolicy(max_attempts=3),
    )
    workflow.add_node(
        "profile_handler",
        partial(profile_handler, db=db),
        retry=RetryPolicy(max_attempts=3),
    )
    workflow.add_node("response_handler", response_handler)

    # ── Edges ─────────────────────────────────────────────────────────────────

    # Entry point
    workflow.add_edge(START, "classify_intent")

    # Conditional routing from classifier → correct handler
    workflow.add_conditional_edges(
        "classify_intent",
        _route_intent,
        {
            "appointment_handler":   "appointment_handler",
            "doctor_handler":        "doctor_handler",
            "nearby_doctor_handler": "nearby_doctor_handler",
            "profile_handler":       "profile_handler",
            "response_handler":      "response_handler",  # greeting / help / out_of_scope
        },
    )

    # All domain handlers → response_handler
    # NOTE: nodes use Command(goto="response_handler") internally which takes precedence,
    # but declaring edges here keeps the graph structure accurate for LangSmith + PNG.
    for handler in [
        "appointment_handler",
        "doctor_handler",
        "nearby_doctor_handler",
        "profile_handler",
    ]:
        workflow.add_edge(handler, "response_handler")

    # Terminal edge
    workflow.add_edge("response_handler", END)

    return workflow.compile(checkpointer=checkpointer)


# ── Context loader ────────────────────────────────────────────────────────────

# Fields that should persist across turns so follow-up messages have full context.
# e.g. "Book slot 1" needs to see available_slots and doctor_id from the prior turn.
_PERSISTENT_FIELDS = (
    "doctor_id",
    "doctor_name",
    "date",
    "time",
    "speciality",
    "available_slots",
    "doctors_list",
    "patient_lat",
    "patient_lon",
    "current_step",
)


async def _load_previous_context(app, config: dict) -> dict:
    """
    Load the most recent checkpoint for this thread and extract persistent fields.
    Returns a dict of fields to merge into the new turn's input state.
    """
    try:
        prev_state = await app.aget_state(config)
        if prev_state and prev_state.values:
            values = prev_state.values
            return {
                k: values[k]
                for k in _PERSISTENT_FIELDS
                if k in values and values[k] is not None
            }
    except Exception as e:
        print(f"[LangGraph] Could not load previous context: {e}")
    return {}


# ── Public API ────────────────────────────────────────────────────────────────

async def process_message(
    user_id: int,
    patient_id: int,
    patient_name: str,
    message: str,
    db: Session,
    patient_lat: float | None = None,
    patient_lon: float | None = None,
) -> dict:
    """
    Process a patient message through the LangGraph pipeline.

    Context awareness:
    - Loads persisted state from the previous turn (via checkpointer).
    - Merges doctor_id, date, available_slots etc. so follow-up messages
      like 'Book slot 1' work without the user repeating themselves.

    Args:
        user_id      : User ID — used as thread_id for session isolation.
        patient_id   : Patient DB ID.
        patient_name : Patient display name.
        message      : The user's raw message text.
        db           : SQLAlchemy session (injected per-request by FastAPI).
        patient_lat  : Optional latitude for nearby-doctor queries.
        patient_lon  : Optional longitude for nearby-doctor queries.

    Returns:
        dict: { response, suggestions, conversation_id }
    """
    checkpointer = await get_checkpointer()
    app = _build_app(db, checkpointer)

    config = {
        "configurable": {"thread_id": f"user_{user_id}"},
        "run_name": f"chatbot | user_{user_id} | {patient_name}",
        "tags": ["chatbot", "healthcare"],
        "metadata": {
            "user_id": user_id,
            "patient_id": patient_id,
            "patient_name": patient_name,
        },
    }

    # ── Load previous context ─────────────────────────────────────────────────
    previous_context = await _load_previous_context(app, config)

    # Build this turn's input state.
    # Start with previous context, then overlay current-turn values.
    input_state: ChatbotState = {
        # Identity (always required)
        "user_id": user_id,
        "patient_id": patient_id,
        "patient_name": patient_name,

        # Current turn — clear response/suggestions/classification each turn
        "current_message": message,
        "response": None,
        "suggestions": None,
        "classification": None,
        "error": None,

        # Merge in persisted fields from last turn
        **previous_context,
    }

    # Override location if freshly provided this turn
    if patient_lat is not None:
        input_state["patient_lat"] = patient_lat
    if patient_lon is not None:
        input_state["patient_lon"] = patient_lon

    try:
        result = await app.ainvoke(input_state, config=config)
        return {
            "response": result.get("response", "I'm sorry, I couldn't process that. Please try again."),
            "suggestions": result.get("suggestions", []),
            "conversation_id": f"conv_{user_id}",
        }

    except Exception as e:
        print(f"[LangGraph] Error in process_message:\n{traceback.format_exc()}")
        return {
            "response": (
                "Something went wrong on my end. Please try rephrasing your question.\n\n"
                f"Error: {str(e)}"
            ),
            "suggestions": ["Try again", "Find available slots", "Search doctors", "Help"],
            "conversation_id": f"conv_{user_id}",
        }


async def get_conversation_history(user_id: int) -> list:
    """
    Retrieve conversation history for a user from the AsyncSQLite checkpointer.

    Uses aget_state_history (async generator) — never the sync get_state_history,
    which raises InvalidStateError with AsyncSqliteSaver from the main event loop thread.
    """
    try:
        workflow = StateGraph(ChatbotState)
        workflow.add_node("_noop", lambda state: {})
        workflow.add_edge(START, "_noop")

        checkpointer = await get_checkpointer()
        app = workflow.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": f"user_{user_id}"}}

        # ✅ Async generator — required with AsyncSqliteSaver
        state_history = []
        async for checkpoint in app.aget_state_history(config):
            state_history.append(checkpoint)

        history = []
        for checkpoint in reversed(state_history):
            values = checkpoint.values

            if values.get("current_message"):
                history.append({
                    "role": "user",
                    "content": values["current_message"],
                    "timestamp": checkpoint.metadata.get("created_at", ""),
                })

            if values.get("response"):
                history.append({
                    "role": "assistant",
                    "content": values["response"],
                    "timestamp": checkpoint.metadata.get("created_at", ""),
                    "suggestions": values.get("suggestions", []),
                })

        return history

    except Exception as e:
        print(f"[LangGraph] Error fetching history: {e}")
        print(traceback.format_exc())
        return []


async def clear_user_context(user_id: int) -> None:
    """
    Delete all checkpointed state for a user (call on logout).
    """
    try:
        checkpointer = await get_checkpointer()
        thread_id = f"user_{user_id}"

        if hasattr(checkpointer, "adelete_thread"):
            await checkpointer.adelete_thread(thread_id)
        elif hasattr(checkpointer, "conn"):
            await checkpointer.conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
            )
            await checkpointer.conn.execute(
                "DELETE FROM checkpoint_writes WHERE thread_id = ?", (thread_id,)
            )
            await checkpointer.conn.commit()

        print(f"[LangGraph] Cleared context for {thread_id}")

    except Exception as e:
        print(f"[LangGraph] Error clearing context for user_{user_id}: {e}")