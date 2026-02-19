"""
Doctor Search Tools — Agentic Version

Fix: All tools return non-empty strings to satisfy Groq's tool result validation.
"""

from langchain_core.tools import tool
from sqlalchemy.orm import Session
from typing import Optional
import json


def make_doctor_tools(db: Session) -> list:

    @tool
    def search_doctor_by_name(name: str) -> str:
        """
        Search doctors by partial name (case-insensitive).
        Args: name (str) — partial or full name, no 'Dr.' prefix
        Returns: JSON string of matches (id, name, speciality, opd_fees, address), or message if none found.
        """
        from langGraph_service.tools.doctor_tools import search_doctors_by_name
        results = search_doctors_by_name(db, name, limit=10)
        if not results:
            return f"No doctors found matching '{name}'."
        return json.dumps(results)

    @tool
    def search_doctor_by_speciality(speciality: str) -> str:
        """
        Search doctors by speciality (case-insensitive).
        Common mappings: 'heart' -> Cardiologist, 'skin' -> Dermatologist,
        'child' -> Paediatrician, 'bone' -> Orthopaedic, 'eye' -> Ophthalmologist.
        Args: speciality (str)
        Returns: JSON string of matches, or message if none found.
        """
        from langGraph_service.tools.doctor_tools import search_doctors_by_speciality
        results = search_doctors_by_speciality(db, speciality, limit=10)
        if not results:
            return f"No doctors found for speciality '{speciality}'."
        return json.dumps(results)

    @tool
    def list_all_specialities() -> str:
        """
        Get all available medical specialities in the system.
        Returns: comma-separated string of specialities.
        """
        from langGraph_service.tools.doctor_tools import get_all_specialities
        results = get_all_specialities(db)
        if not results:
            return "No specialities found in the system."
        return ", ".join(results)

    @tool
    def list_all_doctors(limit: int = 10, skip: int = 0) -> str:
        """
        Get a paginated list of all doctors.
        Args: limit (int, default 10, max 20), skip (int, default 0)
        Returns: JSON string with total (int) and doctors (list).
        """
        from langGraph_service.tools.doctor_tools import get_all_doctors
        result = get_all_doctors(db, limit=min(limit, 20), skip=skip)
        if not result.get("doctors"):
            return "No doctors found in the system."
        return json.dumps(result)

    @tool
    def get_doctor_by_id(doctor_id: int) -> str:
        """
        Get full details for a specific doctor by ID.
        Args: doctor_id (int)
        Returns: JSON string with doctor details, or message if not found.
        """
        from langGraph_service.tools.doctor_tools import get_doctor_by_id
        result = get_doctor_by_id(db, doctor_id)
        if not result:
            return f"No doctor found with ID {doctor_id}."
        return json.dumps(result)

    return [
        search_doctor_by_name,
        search_doctor_by_speciality,
        list_all_specialities,
        list_all_doctors,
        get_doctor_by_id,
    ]