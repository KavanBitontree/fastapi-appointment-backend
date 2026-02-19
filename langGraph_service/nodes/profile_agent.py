"""
Profile Agent Node
Uses create_react_agent from langgraph.prebuilt (NOT langchain.agents.create_agent).
"""

from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent   # ← CORRECT import
from langgraph.types import Command
from sqlalchemy.orm import Session

from langGraph_service.schemas.state import AgenticState
from langGraph_service.config.llm_init import llm
from langGraph_service.tools.profile_tools_agentic import make_profile_tools


PROFILE_SYSTEM_PROMPT = """You are a specialist profile management assistant for Aarogya Healthcare.
Your job is to help patients view and update their personal profile information.

## Your Tools
- get_patient_profile: Fetch the patient's current profile (name, DOB, age, email).
- update_patient_name: Update the patient's display name.
- update_patient_dob: Update the patient's date of birth (YYYY-MM-DD format required).

## Rules for Viewing Profile
When patient says 'view profile', 'my profile', 'show my info' -> call get_patient_profile.
Format the result clearly:
    Your Profile
    Name  : [name]
    DOB   : [dob]
    Age   : [age] years
    Email : [email]

## Rules for Updating Name
- Only call update_patient_name if the patient EXPLICITLY provides a new name.
- Extract name from: 'Update my name to Rahul Sharma' -> new_name='Rahul Sharma'
- If patient says 'update my name' without a name, ask: "What would you like to update your name to?"
- Minimum 2 characters required.

## Rules for Updating Date of Birth
- Only call update_patient_dob if the patient EXPLICITLY provides a date.
- Convert to YYYY-MM-DD before calling:
    '15 May 1990'  -> '1990-05-15'
    '15/05/1990'   -> '1990-05-15'
    'May 15, 1990' -> '1990-05-15'
- If no date provided, ask: "What is your date of birth? (e.g. 15 May 1990)"
- DOB must be in the past.

## After Updates
Confirm success and show the updated value.
"""


def make_profile_agent(
    db: Session,
    patient_id: int,
    user_id: int,
    patient_name: str,
    max_iterations: int = 4,
):
    tools = make_profile_tools(db, patient_id, user_id)

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=PROFILE_SYSTEM_PROMPT,
    )

    def profile_node(state: AgenticState) -> Command:
        messages = state.get("messages") or []
        result = agent.invoke({"messages": messages})

        input_count = len(messages)
        new_messages = result["messages"][input_count:]

        # Tag the final AI message with this agent's name so the supervisor
        # can detect "worker just responded"
        tagged = []
        for msg in new_messages:
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                tagged.append(AIMessage(content=msg.content, name="profile_node"))
            else:
                tagged.append(msg)

        return Command(
            update={"messages": tagged},
            goto="supervisor",
        )

    return profile_node