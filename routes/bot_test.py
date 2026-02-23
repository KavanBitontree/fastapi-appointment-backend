# routes/bot_test.py  (DEV ONLY — remove before production)
from fastapi import APIRouter, Depends, Security, HTTPException
from pydantic import BaseModel
from typing import Optional
import httpx

from core.security_schemes import bearer_scheme
from middlewares.auth import roles_required
from core.enums import UserRole

router = APIRouter(
    prefix="/bot/test",
    tags=["n8n Bot — Dev Testing"],
    dependencies=[Security(bearer_scheme)],
)

N8N_BASE = "http://localhost:5678/webhook-test"

class AgentTestRequest(BaseModel):
    message: str
    patient_name: Optional[str] = "Test Patient"
    thread_id: Optional[str] = "test_thread_1"

@router.post("/appointment-agent", summary="[DEV] Directly invoke appointment agent sub-workflow")
async def test_appointment_agent(
    body: AgentTestRequest,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
):
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{N8N_BASE}/test-appointment-agent",
            json={
                "message": body.message,
                "user_id": current_user["user_id"],
                "patient_id": current_user.get("patient_id", 1),
                "patient_name": body.patient_name,
                "thread_id": body.thread_id,
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"n8n returned {r.status_code}: {r.text}")
    return r.json()