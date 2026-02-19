"""
visualize.py — LangGraph Native Graph Visualizer
==================================================
Fixed version: uses add_conditional_edges() from supervisor to all workers
so the full topology is visible in draw_mermaid_png().

HOW TO RUN:
  python langGraph_service/visualize.py

OUTPUT FILES:
  aarogya_graph_simple.mmd / .png  — top-level view
  aarogya_graph_xray.mmd  / .png  — xray view (all ReAct internals + tool nodes)

For PNG support:
  pip install playwright && playwright install chromium
"""

import sys
from pathlib import Path
from typing import Annotated, List, Optional, TypedDict

try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import create_react_agent
    from langgraph.types import Command
    from langchain_core.tools import tool
    from langchain_core.messages import BaseMessage, AIMessage
    from langchain_core.prompts import ChatPromptTemplate
except ImportError as e:
    print(f"[visualize] Missing dependency: {e}")
    print("Install: pip install langgraph langchain langchain-core")
    sys.exit(1)


# ── Stub LLM ───────────────────────────────────────────────────────────────────
def _make_stub_llm():
    try:
        from langchain_groq import ChatGroq
        return ChatGroq(model="llama3-70b-8192", api_key="viz-stub")
    except Exception:
        pass
    try:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o-mini", api_key="viz-stub")
    except Exception:
        pass
    print("[visualize] Install langchain-groq or langchain-openai for the stub LLM.")
    sys.exit(1)

LLM = _make_stub_llm()


# ── Shared state ───────────────────────────────────────────────────────────────
class AgenticState(TypedDict, total=False):
    messages:             Annotated[List[BaseMessage], add_messages]
    user_id:              int
    patient_id:           int
    patient_name:         str
    current_message:      str
    route_to:             Optional[str]
    supervisor_reasoning: Optional[str]
    patient_lat:          Optional[float]
    patient_lon:          Optional[float]
    response:             Optional[str]
    suggestions:          Optional[List[str]]


# ── Stub tools — real names, no DB logic ──────────────────────────────────────

# Appointment
@tool
def get_current_date() -> str:
    """Get today's date in IST as YYYY-MM-DD."""
    return ""

@tool
def get_current_datetime() -> str:
    """Get current IST datetime string."""
    return ""

@tool
def check_can_book_on_date(date: str) -> dict:
    """Check if the patient can book on this date (25-hr rule + one-per-day). Args: date – YYYY-MM-DD."""
    return {}

@tool
def search_doctor_by_name(name: str) -> list:
    """Search doctors by name (partial match). Args: name."""
    return []

@tool
def get_free_slots(doctor_id: int, date: str) -> dict:
    """Get free appointment slots for a doctor on a date. Args: doctor_id, date – YYYY-MM-DD."""
    return {}

@tool
def book_slot(slot_id: int) -> dict:
    """Book a slot after explicit patient confirmation. Args: slot_id."""
    return {}

@tool
def get_my_appointments(status_filter: Optional[str] = None) -> list:
    """Get patient appointment history. Args: status_filter (optional)."""
    return []

# Doctor
@tool
def search_doctor_by_speciality(speciality: str) -> list:
    """Search doctors by medical speciality. Args: speciality."""
    return []

@tool
def list_all_specialities() -> list:
    """List all available medical specialities."""
    return []

@tool
def list_all_doctors(limit: int = 10, skip: int = 0) -> dict:
    """List all doctors paginated. Args: limit, skip."""
    return {}

@tool
def get_doctor_by_id(doctor_id: int) -> dict:
    """Get doctor details by ID. Args: doctor_id."""
    return {}

# Nearby
@tool
def find_nearby_doctors(
    patient_lat: float,
    patient_lon: float,
    max_distance_km: float = 10.0,
    speciality: Optional[str] = None,
) -> list:
    """Find doctors within radius of patient location. Args: patient_lat, patient_lon, max_distance_km, speciality."""
    return []

# Profile
@tool
def get_patient_profile() -> dict:
    """Get patient profile: name, DOB, age, email."""
    return {}

@tool
def update_patient_name(new_name: str) -> dict:
    """Update patient display name. Args: new_name."""
    return {}

@tool
def update_patient_dob(new_dob: str) -> dict:
    """Update patient date of birth. Args: new_dob – YYYY-MM-DD."""
    return {}


APPOINTMENT_TOOLS = [
    get_current_date, get_current_datetime, check_can_book_on_date,
    search_doctor_by_name, get_free_slots, book_slot, get_my_appointments,
]
DOCTOR_TOOLS  = [search_doctor_by_name, search_doctor_by_speciality,
                 list_all_specialities, list_all_doctors, get_doctor_by_id]
NEARBY_TOOLS  = [find_nearby_doctors, list_all_specialities]
PROFILE_TOOLS = [get_patient_profile, update_patient_name, update_patient_dob]


# ── Build stub agents ──────────────────────────────────────────────────────────
def _agent(tools, system):
    return create_react_agent(model=LLM, tools=tools, prompt=system)

appointment_agent = _agent(APPOINTMENT_TOOLS, "Appointment specialist.")
doctor_agent      = _agent(DOCTOR_TOOLS,      "Doctor search specialist.")
nearby_agent      = _agent(NEARBY_TOOLS,      "Nearby doctor specialist.")
profile_agent     = _agent(PROFILE_TOOLS,     "Profile management specialist.")


# ── Stub node wrappers ─────────────────────────────────────────────────────────
def supervisor_node(state: AgenticState):
    """Supervisor: route to worker or END."""
    return Command(
        update={"route_to": "__end__"},
        goto=END,
    )

def _router(state: AgenticState) -> str:
    """Conditional edge router — reads state['route_to']."""
    return state.get("route_to", "__end__") or "__end__"

def _wrap(agent, name):
    def node(state: AgenticState):
        result = agent.invoke({"messages": state.get("messages") or []})
        return Command(
            update={"messages": [AIMessage(
                content=result["messages"][-1].content, name=name
            )]},
            goto="supervisor",
        )
    node.__name__ = name
    return node

appointment_node = _wrap(appointment_agent, "appointment_node")
doctor_node      = _wrap(doctor_agent,      "doctor_node")
nearby_node      = _wrap(nearby_agent,      "nearby_node")
profile_node     = _wrap(profile_agent,     "profile_node")


# ── Build graph ────────────────────────────────────────────────────────────────
def build_graph():
    wf = StateGraph(AgenticState)

    wf.add_node("supervisor",       supervisor_node)
    wf.add_node("appointment_node", appointment_node)
    wf.add_node("doctor_node",      doctor_node)
    wf.add_node("nearby_node",      nearby_node)
    wf.add_node("profile_node",     profile_node)

    # Entry
    wf.add_edge(START, "supervisor")

    # ── KEY FIX: add_conditional_edges makes supervisor→worker edges visible ──
    wf.add_conditional_edges(
        "supervisor",
        _router,
        {
            "appointment_node": "appointment_node",
            "doctor_node":      "doctor_node",
            "nearby_node":      "nearby_node",
            "profile_node":     "profile_node",
            "__end__":          END,
        },
    )

    # Workers cycle back to supervisor
    for w in ["appointment_node", "doctor_node", "nearby_node", "profile_node"]:
        wf.add_edge(w, "supervisor")

    return wf.compile()


# ── Render ─────────────────────────────────────────────────────────────────────
def render(output_dir: str = "."):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("[visualize] Building graph topology...")
    app = build_graph()

    simple_graph = app.get_graph()
    xray_graph   = app.get_graph(xray=True)

    # Mermaid DSL
    for name, g in [("simple", simple_graph), ("xray", xray_graph)]:
        mmd = g.draw_mermaid()
        path = out / f"aarogya_graph_{name}.mmd"
        path.write_text(mmd)
        print(f"\n{'='*64}")
        print(f"MERMAID ({name.upper()}) -> {path}")
        print(f"{'='*64}")
        print(mmd)

    # PNG via playwright
    png_ok = False
    for name, g in [("simple", simple_graph), ("xray", xray_graph)]:
        try:
            png_bytes = g.draw_mermaid_png()
            path = out / f"aarogya_graph_{name}.png"
            path.write_bytes(png_bytes)
            print(f"[visualize] PNG saved -> {path}")
            png_ok = True
        except Exception as e:
            print(f"[visualize] PNG ({name}) failed: {e}")

    if not png_ok:
        print("\nPNG generation requires playwright:")
        print("  pip install playwright && playwright install chromium")
        print("Alternatively paste the .mmd files at: https://mermaid.live")

    print("\n[visualize] ASCII graph (simple):")
    try:
        simple_graph.print_ascii()
    except Exception:
        print("  (not available in this langgraph version)")

    print(f"\n[visualize] Done. Output in: {out.resolve()}")


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else ".")