"""
Nearby Doctor Agent Node
Uses create_react_agent from langgraph.prebuilt.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent   # ← CORRECT import
from langgraph.types import Command
from sqlalchemy.orm import Session

from langGraph_service.schemas.state import AgenticState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.nearby_tools_agentic import make_nearby_tools


NEARBY_SYSTEM_PROMPT = """You are a specialist location-based doctor search assistant for Aarogya Healthcare.
Your job is to find doctors near the patient's current location.

## Your Tools
- find_nearby_doctors: Search doctors within a radius using lat/lon coordinates.
- list_all_specialities: Use if patient asks to filter by speciality but is unsure of spelling.

## How to Use Coordinates
The patient's coordinates are provided in the conversation as:
  "[SYSTEM CONTEXT] Patient coordinates: LAT, LON"
Extract these values and pass them to find_nearby_doctors.

## Search Strategy
1. Extract lat/lon from the conversation context message.
2. Extract speciality if mentioned (e.g. 'nearby cardiologist' -> speciality='Cardiologist').
3. Call find_nearby_doctors with default max_distance_km=10.
4. If no results, call again with max_distance_km=20 and inform the patient.
5. If still no results, call again with max_distance_km=50.

## Speciality Conversions
  'heart doctor'  -> 'Cardiologist'
  'skin doctor'   -> 'Dermatologist'
  'child doctor'  -> 'Paediatrician'
  'bone doctor'   -> 'Orthopaedic'
  'eye doctor'    -> 'Ophthalmologist'

## Response Format (IMPORTANT)
Use clean numbered lists (NO markdown tables):

Found [N] doctors near you (within [X] km):

1. Dr. [Name] - [Speciality]
   Fees: ₹[fees] | [distance] km away
   Address: [address]

2. Dr. [Name] - [Speciality]
   Fees: ₹[fees] | [distance] km away
   Address: [address]

After showing results ask: "Would you like to see available slots for any of these doctors?"

DO NOT use markdown tables like | Name | Distance |

## If No Coordinates Available
Respond: "I need your location to find nearby doctors. Please enable location access
in your browser and try again."
"""


def make_nearby_agent(
    db: Session,
    patient_name: str,
    max_iterations: int = 4,
):
    tools = make_nearby_tools(db)

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=NEARBY_SYSTEM_PROMPT,
    )

    def nearby_node(state: AgenticState) -> Command:
        messages = list(state.get("messages") or [])
        patient_lat = state.get("patient_lat")
        patient_lon = state.get("patient_lon")

        # Inject coordinates as a context message so the LLM can read them
        if patient_lat is not None and patient_lon is not None:
            coord_message = HumanMessage(
                content=f"[SYSTEM CONTEXT] Patient coordinates: {patient_lat}, {patient_lon}"
            )
            messages = [coord_message] + messages

        result = agent.invoke({"messages": messages})

        input_count = len(messages)
        new_messages = result["messages"][input_count:]

        tagged = []
        for msg in new_messages:
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                tagged.append(AIMessage(content=msg.content, name="nearby_node"))
            else:
                tagged.append(msg)

        return Command(
            update={"messages": tagged},
            goto="supervisor",
        )

    return nearby_node