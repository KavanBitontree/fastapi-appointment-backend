"""
Chat API Routes — Aarogya Assistant (AA)
Patients interact with the n8n-powered chatbot here.

Architecture: Supervisor-Worker (n8n Workflow)
  - POST /chat      → forwards to n8n webhook (supervisor + all agents)
  - GET  /history   → still served from LangGraph AsyncSQLite checkpointer
  - POST /clear-context → still clears LangGraph checkpointer
  - GET  /suggestions   → static list, no change
"""

from fastapi import APIRouter, Depends, HTTPException, Security, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging
import httpx

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.patient import Patient

from langGraph_service.graph import get_conversation_history, clear_user_context

logger = logging.getLogger(__name__)

# ── n8n webhook config ────────────────────────────────────────────────────────
N8N_WEBHOOK_URL = "http://localhost:5678/webhook-test/aarogya-chat"
N8N_TIMEOUT_SECONDS = 120.0

router = APIRouter(
    prefix="/chat",
    tags=["Aarogya Assistant (AA)"],
    dependencies=[Security(bearer_scheme)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    suggestions: Optional[list[str]] = None


# ── POST /chat  →  n8n ────────────────────────────────────────────────────────

@router.post("/", response_model=ChatResponse)
async def chat_with_assistant(
    request: Request,
    chat_message: ChatMessage,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
):
    """
    🤖 Aarogya Assistant (AA) — Main chat endpoint.

    **Architecture: Supervisor-Worker Pattern (n8n)**

    Forwards the patient message to the n8n webhook which runs the full
    supervisor-worker pipeline:
    - 📅 **Appointment Agent** — Book, view appointments; check slot availability
    - 🔍 **Doctor Agent** — Search doctors by name or specialization
    - 📍 **Nearby Agent** — Find doctors near your location (send latitude & longitude)
    - 👤 **Profile Agent** — View and update your patient profile

    **Nearby doctors:**
    Pass `latitude` and `longitude` in the request body to enable location-based search.
    """

    patient = db.query(Patient).filter(Patient.user_id == current_user["user_id"]).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    # ── Extract raw JWT from Authorization header ─────────────────────────────
    # The token is already validated by roles_required() above.
    # We extract it again here to forward it to n8n so sub-workflow
    # tool nodes can authenticate against the bot API routes.
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.removeprefix("Bearer ").strip()

    logger.info(
        f"[Chat→n8n] user={current_user['user_id']} patient={patient.id} "
        f"msg={chat_message.message[:80]!r}"
    )

    # ── Build n8n payload ─────────────────────────────────────────────────────
    payload: dict = {
        "message":      chat_message.message,
        "user_id":      current_user["user_id"],
        "patient_id":   patient.id,
        "patient_name": patient.name,
        "thread_id":    f"user_{current_user['user_id']}",
        "access_token": access_token,
    }
    if chat_message.latitude is not None:
        payload["latitude"] = chat_message.latitude
    if chat_message.longitude is not None:
        payload["longitude"] = chat_message.longitude

    # ── Call n8n webhook ──────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=N8N_TIMEOUT_SECONDS) as client:
            r = await client.post(N8N_WEBHOOK_URL, json=payload)
            r.raise_for_status()
            data = r.json()

    except httpx.TimeoutException:
        logger.error(f"[Chat→n8n] Timeout for user={current_user['user_id']}")
        raise HTTPException(
            status_code=504,
            detail="The assistant took too long to respond. Please try again.",
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[Chat→n8n] HTTP {e.response.status_code} for user={current_user['user_id']}: "
            f"{e.response.text[:200]}"
        )
        raise HTTPException(
            status_code=502,
            detail="Assistant service returned an error. Please try again.",
        )
    except httpx.RequestError as e:
        logger.error(f"[Chat→n8n] Connection error for user={current_user['user_id']}: {e}")
        raise HTTPException(
            status_code=503,
            detail="Could not reach the assistant service. Please try again shortly.",
        )

    # ── Normalise n8n response ────────────────────────────────────────────────
    if isinstance(data, list):
        data = data[0] if data else {}

    response_text = (
        data.get("response")
        or data.get("output")
        or data.get("text")
        or "I'm sorry, I couldn't process that. Please try again."
    )
    suggestions = data.get("suggestions") or []
    conversation_id = data.get("conversation_id") or f"conv_{current_user['user_id']}"

    logger.info(
        f"[Chat→n8n] OK user={current_user['user_id']} "
        f"agent={data.get('agent','?')} resp={response_text[:60]!r}"
    )

    return ChatResponse(
        response=response_text,
        conversation_id=conversation_id,
        suggestions=suggestions,
    )


# ── GET /suggestions ──────────────────────────────────────────────────────────

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


# ── POST /clear-context ───────────────────────────────────────────────────────

@router.post("/clear-context")
async def clear_chat_context(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
):
    """Clear conversation context for the current user."""
    await clear_user_context(current_user["user_id"])
    return {
        "message": "Conversation context cleared successfully",
        "user_id": current_user["user_id"],
    }


# ── GET /history ──────────────────────────────────────────────────────────────

@router.get("/history")
async def get_chat_history(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
):
    """
    Get conversation history for the current user.
    Reads from the LangGraph AsyncSQLite checkpointer.
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