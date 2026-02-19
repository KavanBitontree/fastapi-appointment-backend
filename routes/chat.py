"""
Chat API Routes — Aarogya Assistant (AA)
Patients interact with the LangGraph-powered chatbot here.

Architecture: Supervisor-Worker (Blog Pattern)
  - Supervisor routes to specialist agents
  - Each agent runs a full ReAct loop (LLM decides which tools to call)
  - Agents return control to supervisor after completing their task
  - Supervisor chains agents or finishes
"""

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.patient import Patient

from langGraph_service.graph import process_message, get_conversation_history, clear_user_context

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["Aarogya Assistant (AA)"],
    dependencies=[Security(bearer_scheme)],
)


class ChatMessage(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    # Optional: patient shares location for 'nearby doctors' feature
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    suggestions: Optional[list[str]] = None


@router.post("/", response_model=ChatResponse)
async def chat_with_assistant(
    chat_message: ChatMessage,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
):
    """
    🤖 Aarogya Assistant (AA) — Main chat endpoint.

    **Architecture: Supervisor-Worker Pattern**

    The supervisor routes your message to the correct specialist agent:
    - 📅 **Appointment Agent** — Book, view, cancel appointments; check slot availability
    - 🔍 **Doctor Agent** — Search doctors by name or specialization
    - 📍 **Nearby Agent** — Find doctors near your location (send latitude & longitude)
    - 👤 **Profile Agent** — View and update your patient profile

    Each agent runs a full ReAct loop: the LLM autonomously decides which tools
    to call, reads the results, and continues until it has a complete answer.
    The supervisor then decides if another agent is needed or the query is done.

    **Nearby doctors:**
    Pass `latitude` and `longitude` in the request body to enable location-based search.
    """

    patient = db.query(Patient).filter(Patient.user_id == current_user["user_id"]).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    logger.info(
        f"[Chat] user={current_user['user_id']} patient={patient.id} "
        f"msg={chat_message.message[:80]!r}"
    )

    result = await process_message(
        user_id=current_user["user_id"],
        patient_id=patient.id,
        patient_name=patient.name,
        message=chat_message.message,
        db=db,
        patient_lat=chat_message.latitude,
        patient_lon=chat_message.longitude,
    )

    return ChatResponse(
        response=result["response"],
        conversation_id=result["conversation_id"],
        suggestions=result.get("suggestions"),
    )


@router.get("/suggestions")
async def get_chat_suggestions(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
):
    """Get suggested starter queries for the chat UI."""
    return {
        "suggestions": [
            "Find available slots for tomorrow",
            "Show me cardiologist doctors",
            "Find doctors near me",
            "Check my appointment status",
            "Book appointment with Dr. Sharma",
            "Find dermatologist near me",
            "View my profile",
            "Update my name",
        ]
    }


@router.post("/clear-context")
async def clear_chat_context(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
):
    """
    Clear conversation context for the current user.
    Call this on logout or when starting fresh.
    """
    await clear_user_context(current_user["user_id"])
    return {
        "message": "Conversation context cleared successfully",
        "user_id": current_user["user_id"],
    }


@router.get("/history")
async def get_chat_history(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
):
    """
    Get conversation history for the current user.
    Uses LangGraph AsyncSQLite checkpointer.
    Returns all human messages and agent responses in chronological order.
    """
    try:
        history = await get_conversation_history(current_user["user_id"])
        return {
            "history": history,
            "user_id": current_user["user_id"],
            "thread_id": f"user_{current_user['user_id']}",
        }
    except Exception as e:
        logger.error(f"[Chat] Error fetching history for user {current_user['user_id']}: {e}")
        return {
            "history": [],
            "user_id": current_user["user_id"],
            "error": str(e),
        }