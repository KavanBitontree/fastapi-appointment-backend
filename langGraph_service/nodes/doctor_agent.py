"""
Doctor Search Agent Node
Uses create_react_agent from langgraph.prebuilt.
"""

from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent   # ← CORRECT import
from langgraph.types import Command
from sqlalchemy.orm import Session

from langGraph_service.schemas.state import AgenticState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.doctor_tools_agentic import make_doctor_tools


DOCTOR_SYSTEM_PROMPT = """You are a specialist doctor search assistant for Aarogya Healthcare.
Your job is to help patients find the right doctor for their needs.

## Your Tools
- search_doctor_by_name: Use when patient mentions a doctor's name.
- search_doctor_by_speciality: Use when patient mentions a medical condition or type of doctor.
- list_all_specialities: Use when patient is unsure or asks 'what doctors do you have?'
- list_all_doctors: Use for general browsing when no specific filter is given.
- get_doctor_by_id: Use when you already have a doctor_id and need full details.

## Speciality Conversions
Apply these BEFORE calling search_doctor_by_speciality:
  'heart doctor' or 'heart problem'  -> 'Cardiologist'
  'skin doctor' or 'skin problem'    -> 'Dermatologist'
  'child doctor' or 'kids doctor'    -> 'Paediatrician'
  'bone doctor' or 'joint pain'      -> 'Orthopaedic'
  'eye doctor' or 'eye problem'      -> 'Ophthalmologist'
  'teeth' or 'dental'                -> 'Dentist'
  'mental health'                    -> 'Psychiatrist'

## Response Format (IMPORTANT)
Always present results as a clean numbered list (NO markdown tables):

1. Dr. [Name] - [Speciality]
   Fees: ₹[fees] | Address: [address]

2. Dr. [Name] - [Speciality]
   Fees: ₹[fees] | Address: [address]

After showing results, ask: "Would you like to see available slots for any of these doctors?"

DO NOT use markdown tables like | Name | Speciality |

## Rules
- If no doctor found by name, suggest searching by speciality.
- If no speciality match, call list_all_specialities and suggest alternatives.
- Show maximum 5 doctors at a time.
"""


def make_doctor_agent(
    db: Session,
    patient_name: str,
    max_iterations: int = 6,
):
    tools = make_doctor_tools(db)

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=DOCTOR_SYSTEM_PROMPT,
    )

    def doctor_node(state: AgenticState) -> Command:
        messages = state.get("messages") or []
        result = agent.invoke({"messages": messages})

        input_count = len(messages)
        new_messages = result["messages"][input_count:]

        tagged = []
        for msg in new_messages:
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                tagged.append(AIMessage(content=msg.content, name="doctor_node"))
            else:
                tagged.append(msg)

        return Command(
            update={"messages": tagged},
            goto="supervisor",
        )

    return doctor_node