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

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["Aarogya Assistant (AA)"],
    dependencies=[Security(bearer_scheme)]
)


class ChatMessage(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    suggestions: Optional[list[str]] = None


@router.post("/", response_model=ChatResponse)
async def chat_with_assistant(
    chat_message: ChatMessage,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    🤖 Aarogya Assistant (AA) - Chat endpoint
    
    This endpoint handles patient queries and provides intelligent responses.
    Currently returns static responses - will be enhanced with AI later.
    
    Features:
    - Find available slots
    - Search doctors by specialization
    - Request appointments automatically
    - Answer medical queries
    - Provide appointment status updates
    """
    
    # Get patient info
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    user_message = chat_message.message.lower().strip()
    conversation_id = chat_message.conversation_id or f"conv_{current_user['user_id']}"
    
    logger.info(f"Chat message from patient {patient.id}: {user_message}")
    
    # Static responses based on keywords (will be replaced with AI)
    response_text = ""
    suggestions = []
    
    # Greeting
    if any(word in user_message for word in ["hello", "hi", "hey", "namaste"]):
        response_text = f"Hello {patient.name}! 👋 I'm Aarogya Assistant (AA), your healthcare companion. How can I help you today?"
        suggestions = [
            "Find available slots",
            "Search doctors by specialization",
            "Check my appointments",
            "Book an appointment"
        ]
    
    # Find slots
    elif any(word in user_message for word in ["slot", "available", "free", "book"]):
        response_text = "I can help you find available slots! 📅\n\nPlease tell me:\n1. Which doctor or specialization?\n2. Preferred date?\n\nFor example: 'Show me slots for cardiologist on Dec 25'"
        suggestions = [
            "Show slots for today",
            "Find cardiologist slots",
            "Available slots this week"
        ]
    
    # Find doctors
    elif any(word in user_message for word in ["doctor", "specialist", "find"]):
        response_text = "I can help you find the right doctor! 👨‍⚕️\n\nYou can search by:\n- Specialization (e.g., Cardiologist, Dermatologist)\n- Doctor name\n- Location\n\nWhat are you looking for?"
        suggestions = [
            "Find cardiologist",
            "Find dermatologist",
            "Show all doctors"
        ]
    
    # Appointment status
    elif any(word in user_message for word in ["appointment", "status", "booking"]):
        response_text = "I can check your appointment status! 📋\n\nWould you like to:\n- View upcoming appointments\n- Check pending requests\n- See appointment history"
        suggestions = [
            "Show my appointments",
            "Pending requests",
            "Appointment history"
        ]
    
    # Help
    elif any(word in user_message for word in ["help", "what can you do", "features"]):
        response_text = """I'm here to help you with:

🔍 Find Doctors - Search by specialization or name
📅 Book Appointments - Find and book available slots
📋 Track Appointments - Check status and history
💊 Medical Queries - Get basic health information
⏰ Reminders - Never miss an appointment

Just ask me anything! For example:
"Find cardiologist slots for tomorrow"
"Show my upcoming appointments"
"Book appointment with Dr. Smith"
"""
        suggestions = [
            "Find available slots",
            "Search doctors",
            "My appointments"
        ]
    
    # Default response
    else:
        response_text = f"I understand you're asking about: '{chat_message.message}'\n\nI'm still learning! 🤖 For now, I can help you with:\n\n- Finding available slots\n- Searching doctors\n- Checking appointments\n\nTry asking: 'Show me available slots' or 'Find a cardiologist'"
        suggestions = [
            "Find available slots",
            "Search doctors",
            "Show my appointments",
            "Help"
        ]
    
    return ChatResponse(
        response=response_text,
        conversation_id=conversation_id,
        suggestions=suggestions
    )


@router.get("/suggestions")
async def get_chat_suggestions(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Get suggested queries for the chat interface
    """
    return {
        "suggestions": [
            "Find available slots for today",
            "Show me cardiologist doctors",
            "Check my appointment status",
            "Book appointment with Dr. Smith",
            "Find dermatologist near me",
            "Show slots for next week",
            "Cancel my appointment",
            "Reschedule my appointment"
        ]
    }
