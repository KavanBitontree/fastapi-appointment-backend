"""
Task Decomposer Node — Parallel Task Handling
==============================================

Analyzes user input to detect multiple independent tasks and routes them
to appropriate workers in parallel or sequence.

Example multi-task queries:
  - "Book 10 AM slot for Dr Rajeev on 19th March and update my name to Kavan Gajera"
  - "Find cardiologist near me and show my appointments"
  - "Update my DOB to 15 May 1990 and book slot with Dr Sharma"
"""

from typing import Annotated, List, Literal
from typing_extensions import TypedDict
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command

from langGraph_service.schemas.state import AgenticState
from langGraph_service.config.llm_init import llm


TaskType = Literal[
    "appointment",
    "doctor_search",
    "nearby_search",
    "profile_update",
    "greeting",
    "help",
    "out_of_scope",
]


class Task(TypedDict):
    type: Annotated[TaskType, ..., "Type of task"]
    description: Annotated[str, ..., "What the user wants to do"]
    priority: Annotated[int, ..., "Execution priority (1=highest)"]


class TaskDecomposition(TypedDict):
    tasks: Annotated[List[Task], ..., "List of identified tasks"]
    is_multi_task: Annotated[bool, ..., "True if multiple independent tasks detected"]
    reasoning: Annotated[str, ..., "Brief explanation of decomposition"]


TASK_DECOMPOSER_PROMPT = """You are a task analyzer for a healthcare assistant.

Analyze the user's message and identify ALL distinct tasks they want to accomplish.

## Task Types
- appointment: Book/view/manage appointments, check slots
- doctor_search: Find doctor by name or specialization
- nearby_search: Find doctors near user's location
- profile_update: Update name, DOB, or view profile
- greeting: Pure greeting with no other intent
- help: Questions about capabilities
- out_of_scope: Non-healthcare topics

## Rules
1. Identify EACH distinct task separately
2. Set is_multi_task=true if 2+ independent tasks found
3. Assign priority: profile updates first (1), then searches (2), then bookings (3)
4. If tasks depend on each other, they're ONE task (e.g., "find doctor and book" = appointment)
5. "and" or "also" often indicates multiple tasks

## Examples

Input: "Book 10 AM slot for Dr Rajeev on 19th March and update my name to Kavan Gajera"
Output: {
  "tasks": [
    {"type": "profile_update", "description": "Update name to Kavan Gajera", "priority": 1},
    {"type": "appointment", "description": "Book 10 AM slot for Dr Rajeev on 19th March", "priority": 2}
  ],
  "is_multi_task": true,
  "reasoning": "Two independent tasks: profile update and appointment booking"
}

Input: "Find cardiologist and book appointment"
Output: {
  "tasks": [
    {"type": "appointment", "description": "Find cardiologist and book appointment", "priority": 1}
  ],
  "is_multi_task": false,
  "reasoning": "Single task - booking depends on finding doctor"
}

Input: "Show my appointments and update my DOB to 15 May 1990"
Output: {
  "tasks": [
    {"type": "profile_update", "description": "Update DOB to 15 May 1990", "priority": 1},
    {"type": "appointment", "description": "Show my appointments", "priority": 2}
  ],
  "is_multi_task": true,
  "reasoning": "Two independent tasks: profile update and viewing appointments"
}

Input: "Hello"
Output: {
  "tasks": [
    {"type": "greeting", "description": "Greeting", "priority": 1}
  ],
  "is_multi_task": false,
  "reasoning": "Simple greeting"
}

Analyze the user's message and return the task decomposition."""


def make_task_decomposer(llm_instance=None):
    _llm = llm_instance or llm
    _decomposer_llm = _llm.with_structured_output(TaskDecomposition)

    def task_decomposer_node(state: AgenticState) -> dict:
        """
        Analyzes user input to detect multiple tasks.
        Sets multi_task_queue in state if parallel execution needed.
        """
        messages = state.get("messages") or []
        if not messages:
            return {}

        last_msg = messages[-1]
        if not isinstance(last_msg, HumanMessage):
            return {}

        user_text = getattr(last_msg, "content", "") or ""
        patient_name = state.get("patient_name", "Patient")

        # Call LLM to decompose tasks
        decomposition_input = [
            {"role": "system", "content": TASK_DECOMPOSER_PROMPT},
            {"role": "user", "content": f"Patient: {patient_name}\n\nMessage: {user_text}"},
        ]

        try:
            result: TaskDecomposition = _decomposer_llm.invoke(decomposition_input)
            
            print(f"[task_decomposer] Detected {len(result['tasks'])} task(s)")
            print(f"[task_decomposer] Multi-task: {result['is_multi_task']}")
            for task in result['tasks']:
                print(f"  - {task['type']}: {task['description']} (priority: {task['priority']})")

            # Store decomposition in state
            return {
                "task_decomposition": result,
                "multi_task_mode": result["is_multi_task"],
            }

        except Exception as e:
            print(f"[task_decomposer] Error: {e}")
            # Fallback: treat as single task
            return {
                "multi_task_mode": False,
            }

    return task_decomposer_node


def map_task_to_worker(task_type: TaskType) -> str:
    """Map task type to worker node name."""
    mapping = {
        "appointment": "appointment_node",
        "doctor_search": "doctor_node",
        "nearby_search": "nearby_node",
        "profile_update": "profile_node",
        "greeting": "FINISH",
        "help": "FINISH",
        "out_of_scope": "FINISH",
    }
    return mapping.get(task_type, "FINISH")
