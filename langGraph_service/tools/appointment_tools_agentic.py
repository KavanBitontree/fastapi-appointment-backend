"""
Appointment Tools — Agentic Version
All tools use the @tool decorator so the LLM can see their schemas and call
them autonomously inside a ReAct agent loop.

Tools are created via a factory function make_appointment_tools(db, patient_id)
that closes over the SQLAlchemy session and patient identity so those
never appear as LLM-callable parameters.
"""

from langchain_core.tools import tool
from sqlalchemy.orm import Session
from typing import Optional


def make_appointment_tools(db: Session, patient_id: int) -> list:
    """
    Factory: returns a list of @tool functions with db and patient_id
    baked in via closure. Call once per request in the agent factory.
    """

    @tool
    def check_can_book_on_date(date: str) -> dict:
        """
        Check whether the patient is allowed to book an appointment on a specific date.
        Enforces three rules:
          1. Date must not be in the past.
          2. Date must be at least 25 hours from now (gives doctor 24 hrs to approve).
          3. Patient must not already have an active appointment on that date.

        ALWAYS call this before get_free_slots to avoid showing unavailable dates.

        Args:
            date: Target date in YYYY-MM-DD format (e.g. '2026-03-15').

        Returns:
            dict with keys:
              can_book (bool): True if booking is allowed.
              reason (str | None): Human-readable explanation if can_book is False.
              existing (dict | None): Existing appointment details if one already exists.
        """
        from datetime import date as dt_date
        from langGraph_service.tools.appointment_tools import check_patient_can_book_on_date
        return check_patient_can_book_on_date(db, patient_id, dt_date.fromisoformat(date))

    @tool
    def search_doctor_by_name(name: str) -> list:
        """
        Search for doctors whose name contains the given string (case-insensitive).
        Use this to resolve a doctor name the patient mentioned into a doctor_id
        before calling get_free_slots.

        Args:
            name: Full or partial doctor name WITHOUT the 'Dr.' prefix.
                  Examples: 'Sharma', 'Rajeev Shukla', 'anderson'

        Returns:
            List of dicts, each with: id, name, speciality, opd_fees, address.
            Returns empty list if no match found.
        """
        from langGraph_service.tools.doctor_tools import search_doctors_by_name
        return search_doctors_by_name(db, name, limit=5)

    @tool
    def get_free_slots(doctor_id: int, date: str) -> dict:
        """
        Get all FREE appointment slots for a specific doctor on a specific date.
        Call check_can_book_on_date first to confirm the date is bookable.
        If you only have the doctor's name (not ID), call search_doctor_by_name first.

        Args:
            doctor_id: Integer doctor ID from search_doctor_by_name result.
            date: Date in YYYY-MM-DD format (e.g. '2026-03-15').

        Returns:
            dict with keys:
              doctor_found (bool)
              doctor_id, doctor_name, speciality, opd_fees, address
              slots (list): each slot has id, date, start_time, end_time, status
              total (int): total number of free slots
        """
        from datetime import date as dt_date
        from langGraph_service.tools.appointment_tools import get_free_slots_for_doctor_on_date
        return get_free_slots_for_doctor_on_date(db, doctor_id, dt_date.fromisoformat(date))

    @tool
    def book_slot(slot_id: int) -> dict:
        """
        Book a specific appointment slot for the patient.
        Only call this AFTER the patient has explicitly confirmed which slot they want.
        Do NOT call this without patient confirmation.

        The appointment is sent to the doctor as a REQUEST — the doctor has 24 hours
        to approve it. The patient is notified once approved.

        Args:
            slot_id: Integer slot ID from the get_free_slots result.

        Returns:
            dict with keys:
              success (bool)
              appointment_id (int)
              doctor_name (str)
              slot_date (str): YYYY-MM-DD
              slot_time (str): 'HH:MM:SS - HH:MM:SS'
              status (str): 'REQUESTED'
              approval_deadline (str): IST datetime by which doctor must approve
              error (str): present only if success is False
        """
        import asyncio
        import traceback
        from langGraph_service.tools.appointment_tools import request_appointment_via_bot

        def _run_async_in_thread():
            """Helper to run async function in a new thread with its own event loop."""
            return asyncio.run(request_appointment_via_bot(db, patient_id, slot_id))

        try:
            # Check if we're in an async context
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context - use ThreadPoolExecutor with proper event loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(_run_async_in_thread)
                    result = future.result()
            except RuntimeError:
                # No running loop - we can use asyncio.run directly
                result = asyncio.run(request_appointment_via_bot(db, patient_id, slot_id))
            
            # Log the result for debugging
            if not result.get("success"):
                print(f"[book_slot] Booking failed for slot_id={slot_id}, patient_id={patient_id}: {result.get('error')}")
            return result
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            print(f"[book_slot] Exception during booking: {error_msg}")
            print(traceback.format_exc())
            return {"success": False, "error": error_msg}

    @tool
    def get_my_appointments(status_filter: Optional[str] = None) -> list:
        """
        Retrieve the patient's appointment history.
        Use this when the patient asks 'check my appointments', 'show my appointments',
        'appointment status', 'upcoming appointments', or any similar phrase.

        Args:
            status_filter: Optional filter. One of: REQUESTED, APPROVED, PAID, CANCELLED.
                           Pass None to get all appointments (default).

        Returns:
            List of dicts, each with:
              id, status, doctor_name, speciality, slot_date, slot_time, opd_fees, created_at
        """
        from langGraph_service.tools.appointment_tools import get_patient_appointments
        return get_patient_appointments(db, patient_id, status_filter, limit=10)

    return [
        check_can_book_on_date,
        search_doctor_by_name,
        get_free_slots,
        book_slot,
        get_my_appointments,
    ]