"""
LangGraph Service for Aarogya Assistant (AA)

This package implements an intelligent chatbot for healthcare appointment booking
using a graph-based conversation flow.

Architecture:
- State: Shared conversation state across nodes
- Nodes: Processing units for different intents (appointment, doctor search, profile)
- Tools: Utility functions for database operations and date/time handling
- Memory: Conversation history management per user
- Graph: Main orchestrator that routes messages through nodes

Usage:
    from langGraph_service.graph import process_message, clear_user_context
    
    result = await process_message(
        user_id=user_id,
        patient_id=patient_id,
        patient_name=patient_name,
        message=user_message,
        db=db_session
    )
"""

__version__ = "1.0.0"
