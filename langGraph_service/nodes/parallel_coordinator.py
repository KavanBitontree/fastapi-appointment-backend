"""
Parallel Task Coordinator
==========================

Manages execution of multiple independent tasks by routing them sequentially
but tracking progress and combining results.

Note: True parallel execution would require Send() API from LangGraph,
but sequential execution with proper state management achieves similar UX.
"""

from typing import List
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from langGraph_service.schemas.state import AgenticState
from langGraph_service.nodes.task_decomposer import map_task_to_worker


def make_parallel_coordinator():
    """
    Coordinates execution of multiple tasks.
    Routes to next pending task or combines results if all complete.
    """

    def parallel_coordinator_node(state: AgenticState) -> Command:
        """
        Check if we're in multi-task mode and route accordingly.
        """
        multi_task_mode = state.get("multi_task_mode", False)
        
        if not multi_task_mode:
            # Single task mode - pass through to supervisor
            return Command(update={}, goto="supervisor")

        task_decomposition = state.get("task_decomposition")
        if not task_decomposition:
            return Command(update={}, goto="supervisor")

        tasks = task_decomposition.get("tasks", [])
        completed_tasks = state.get("completed_tasks", [])
        messages = state.get("messages", [])

        # Sort tasks by priority
        sorted_tasks = sorted(tasks, key=lambda t: t["priority"])
        
        # Find next pending task
        next_task = None
        for task in sorted_tasks:
            if task["description"] not in completed_tasks:
                next_task = task
                break

        if next_task is None:
            # All tasks complete - combine results and finish
            print("[parallel_coordinator] All tasks completed, combining results")
            
            # Extract responses from completed tasks
            task_responses = []
            for i, task in enumerate(sorted_tasks):
                # Find the AI response after this task
                # This is a simplified approach - in production you'd track responses more carefully
                task_responses.append(f"✓ {task['description']}")
            
            combined_response = (
                "**All tasks completed!**\n\n" +
                "\n".join(task_responses) +
                "\n\nIs there anything else I can help you with?"
            )
            
            return Command(
                update={
                    "response": combined_response,
                    "route_to": "FINISH",
                    "multi_task_mode": False,
                    "completed_tasks": [],
                    "task_decomposition": None,
                    "messages": messages + [AIMessage(content=combined_response, name="parallel_coordinator")],
                },
                goto="__end__",
            )

        # Route to next task's worker
        worker = map_task_to_worker(next_task["type"])
        
        print(f"[parallel_coordinator] Routing to {worker} for: {next_task['description']}")
        
        # Create a focused message for this specific task
        task_message = HumanMessage(content=next_task["description"])
        
        return Command(
            update={
                "current_task": next_task,
                "messages": messages + [task_message],
            },
            goto=worker,
        )

    return parallel_coordinator_node


def make_task_completion_tracker():
    """
    Tracks when a worker completes a task in multi-task mode.
    """

    def task_completion_tracker_node(state: AgenticState) -> Command:
        """
        After a worker completes, mark task as done and return to coordinator.
        """
        multi_task_mode = state.get("multi_task_mode", False)
        
        if not multi_task_mode:
            # Single task mode - go to supervisor
            return Command(update={}, goto="supervisor")

        current_task = state.get("current_task")
        if not current_task:
            return Command(update={}, goto="parallel_coordinator")

        completed_tasks = state.get("completed_tasks", [])
        completed_tasks.append(current_task["description"])
        
        print(f"[task_completion] Completed: {current_task['description']}")
        
        return Command(
            update={
                "completed_tasks": completed_tasks,
                "current_task": None,
            },
            goto="parallel_coordinator",
        )

    return task_completion_tracker_node
