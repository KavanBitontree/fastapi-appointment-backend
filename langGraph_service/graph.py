"""
LangGraph Main Graph — Supervisor-Worker Pattern
=================================================

Key fixes vs original:
  1. add_conditional_edges() from supervisor → all workers + END.
     This makes the full graph topology visible in PNG/Mermaid visualization.
     Runtime routing is still driven by Command(goto=...) inside each node —
     the conditional_edges declaration is the *static* counterpart that
     LangGraph uses for graph drawing and validation.

  2. Worker nodes no longer declare add_edge(worker, "supervisor") because
     those edges are also driven by Command(goto="supervisor") at runtime.
     We keep them as explicit edges so the PNG shows the cycle.

  3. create_react_agent is imported from langgraph.prebuilt (not langchain.agents).

LOOP PROTECTION (two independent limits):
─────────────────────────────────────────
1. recursion_limit (in ainvoke config) — total node-execution cap.
   Set to 50. GraphRecursionError is caught and returned cleanly.

2. max_iterations (in create_react_agent) — per-agent LLM↔tool loop cap.
   appointment=10, others=4-6. Fires before recursion_limit for single-agent loops.
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from sqlalchemy.orm import Session
from pathlib import Path
import aiosqlite
import traceback

from langGraph_service.schemas.state import AgenticState, MESSAGE_HISTORY_LIMIT
from langGraph_service.nodes.supervisor import make_supervisor, make_supervisor_router
from langGraph_service.nodes.appointment_agent import make_appointment_agent
from langGraph_service.nodes.doctor_agent import make_doctor_agent
from langGraph_service.nodes.nearby_agent import make_nearby_agent
from langGraph_service.nodes.profile_agent import make_profile_agent
from langGraph_service.config.llm_init import llm


# ── Loop protection constants ──────────────────────────────────────────────────

GRAPH_RECURSION_LIMIT          = 50
APPOINTMENT_AGENT_MAX_ITERATIONS = 10
DOCTOR_AGENT_MAX_ITERATIONS      = 6
NEARBY_AGENT_MAX_ITERATIONS      = 4
PROFILE_AGENT_MAX_ITERATIONS     = 4


# ── Message trimming node ──────────────────────────────────────────────────────

def trim_messages_node(state: AgenticState) -> dict:
    """
    Trim message history to prevent token overflow.
    Keeps only the last MESSAGE_HISTORY_LIMIT messages.
    """
    messages = state.get("messages", [])
    if len(messages) > MESSAGE_HISTORY_LIMIT:
        trimmed = messages[-MESSAGE_HISTORY_LIMIT:]
        print(f"[trim_messages] Trimmed {len(messages)} → {len(trimmed)} messages")
        return {"messages": trimmed}
    return {}


# ── Checkpointer singleton ─────────────────────────────────────────────────────

_checkpointer_instance: AsyncSqliteSaver | None = None


async def get_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer_instance
    if _checkpointer_instance is None:
        db_path = Path(__file__).parent.parent / "chat_checkpoints.db"
        conn = await aiosqlite.connect(str(db_path))
        _checkpointer_instance = AsyncSqliteSaver(conn)
    return _checkpointer_instance


# ── Graph builder ──────────────────────────────────────────────────────────────

def _build_app(
    db: Session,
    patient_id: int,
    user_id: int,
    patient_name: str,
    checkpointer: AsyncSqliteSaver,
):
    """
    Build and compile the supervisor-worker StateGraph.

    Graph edges (static declarations for visualization + validation):
      START → supervisor
      supervisor →(conditional)→ appointment_node | doctor_node |
                                  nearby_node | profile_node | END
      appointment_node → supervisor   (cycle back)
      doctor_node      → supervisor
      nearby_node      → supervisor
      profile_node     → supervisor

    Runtime routing inside each node uses Command(goto=...) — the conditional
    edge from supervisor and the explicit back-edges together make the full
    topology visible in graph.draw_mermaid_png().
    """
    workflow = StateGraph(AgenticState)

    # ── Create node functions ──────────────────────────────────────────────────
    supervisor_node  = make_supervisor(llm)
    appointment_node = make_appointment_agent(
        db, patient_id, patient_name,
        max_iterations=APPOINTMENT_AGENT_MAX_ITERATIONS,
    )
    doctor_node = make_doctor_agent(
        db, patient_name,
        max_iterations=DOCTOR_AGENT_MAX_ITERATIONS,
    )
    nearby_node = make_nearby_agent(
        db, patient_name,
        max_iterations=NEARBY_AGENT_MAX_ITERATIONS,
    )
    profile_node = make_profile_agent(
        db, patient_id, user_id, patient_name,
        max_iterations=PROFILE_AGENT_MAX_ITERATIONS,
    )

    # ── Register nodes ─────────────────────────────────────────────────────────
    workflow.add_node("trim_messages",    trim_messages_node)
    workflow.add_node("supervisor",       supervisor_node)
    workflow.add_node("appointment_node", appointment_node)
    workflow.add_node("doctor_node",      doctor_node)
    workflow.add_node("nearby_node",      nearby_node)
    workflow.add_node("profile_node",     profile_node)

    # ── Entry point (trim messages first, then supervisor) ────────────────────
    workflow.add_edge(START, "trim_messages")
    workflow.add_edge("trim_messages", "supervisor")

    # ── Supervisor → workers (conditional — makes edges visible in graph PNG) ──
    # The router function reads state["route_to"] which supervisor_node sets
    # before returning Command(goto=...). Both mechanisms must agree.
    supervisor_router = make_supervisor_router()
    workflow.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "appointment_node": "appointment_node",
            "doctor_node":      "doctor_node",
            "nearby_node":      "nearby_node",
            "profile_node":     "profile_node",
            "__end__":          END,
        },
    )

    # ── Workers → supervisor (cycle — visible in graph PNG) ───────────────────
    for worker in ["appointment_node", "doctor_node", "nearby_node", "profile_node"]:
        workflow.add_edge(worker, "supervisor")

    return workflow.compile(checkpointer=checkpointer)


# ── Public API ─────────────────────────────────────────────────────────────────

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
    Process a patient message through the supervisor-worker pipeline.
    """
    checkpointer = await get_checkpointer()
    app = _build_app(db, patient_id, user_id, patient_name, checkpointer)

    config = {
        "configurable": {"thread_id": f"user_{user_id}"},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
        "run_name": f"aarogya | user_{user_id} | {patient_name}",
        "tags": ["aarogya", "healthcare", "supervisor-worker"],
        "metadata": {
            "user_id": user_id,
            "patient_id": patient_id,
            "patient_name": patient_name,
        },
    }

    from langchain_core.messages import HumanMessage as _HumanMessage
    input_state: AgenticState = {
        "user_id": user_id,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "current_message": message,
        # Seed messages with the user turn so the checkpointer persists it
        # and the supervisor never sees an empty message list.
        "messages": [_HumanMessage(content=message)],
        # Do NOT set response/suggestions to None here — that would clobber
        # values written by supervisor since there is no reducer for these fields.
        # They are reset by the supervisor node itself at the start of each turn.
        "route_to": None,
        "supervisor_reasoning": None,
    }

    if patient_lat is not None:
        input_state["patient_lat"] = patient_lat
    if patient_lon is not None:
        input_state["patient_lon"] = patient_lon

    try:
        result = await app.ainvoke(input_state, config=config)
        return {
            "response": result.get("response") or _extract_response_from_messages(result),
            "suggestions": result.get("suggestions") or [],
            "conversation_id": f"conv_{user_id}",
        }

    except GraphRecursionError:
        print(
            f"[LangGraph] GraphRecursionError: recursion_limit={GRAPH_RECURSION_LIMIT} "
            f"exceeded for user_{user_id}. Message: {message[:80]!r}"
        )
        return {
            "response": (
                "I got stuck in a loop trying to process your request. "
                "This can happen with very complex multi-step queries.\n\n"
                "Please try breaking your request into smaller steps:\n"
                "1. First find the doctor: 'Find cardiologist'\n"
                "2. Then book: 'Book slot with Dr. [name] for [date]'"
            ),
            "suggestions": [
                "Find cardiologist",
                "Show my appointments",
                "Find doctors near me",
                "Help",
            ],
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


def _extract_response_from_messages(result: dict) -> str:
    """Fallback: extract the last meaningful AIMessage from the messages list."""
    messages = result.get("messages") or []
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.content:
            if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                return msg.content
    return "I'm sorry, I couldn't process that. Please try again."


# ── Conversation history ───────────────────────────────────────────────────────

async def get_conversation_history(user_id: int) -> list:
    try:
        workflow = StateGraph(AgenticState)
        workflow.add_node("_noop", lambda state: {})
        workflow.add_edge(START, "_noop")

        checkpointer = await get_checkpointer()
        app = workflow.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": f"user_{user_id}"}}

        state_history = []
        async for checkpoint in app.aget_state_history(config):
            state_history.append(checkpoint)

        history = []
        for checkpoint in reversed(state_history):
            values = checkpoint.values
            messages = values.get("messages") or []

            for msg in messages:
                from langchain_core.messages import HumanMessage, AIMessage
                if isinstance(msg, HumanMessage) and msg.content:
                    history.append({
                        "role": "user",
                        "content": msg.content,
                        "timestamp": checkpoint.metadata.get("created_at", ""),
                    })
                elif isinstance(msg, AIMessage) and msg.content:
                    if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                        history.append({
                            "role": "assistant",
                            "content": msg.content,
                            "agent": getattr(msg, "name", "assistant"),
                            "timestamp": checkpoint.metadata.get("created_at", ""),
                        })

        return history

    except Exception as e:
        print(f"[LangGraph] Error fetching history: {e}")
        print(traceback.format_exc())
        return []


async def clear_user_context(user_id: int) -> None:
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