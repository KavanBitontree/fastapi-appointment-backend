"""
Nearby Doctor Tools — Agentic Version

Fix: All tools return non-empty strings/dicts to satisfy Groq's tool result
validation (role:tool content must be a non-empty string or array).
"""

from langchain_core.tools import tool
from sqlalchemy.orm import Session
from typing import Optional


def make_nearby_tools(db: Session) -> list:

    @tool
    def find_nearby_doctors(
        patient_lat: float,
        patient_lon: float,
        max_distance_km: float = 10.0,
        speciality: Optional[str] = None,
    ) -> str:
        """
        Find doctors within a radius of the patient's location.
        Args: patient_lat (float), patient_lon (float), max_distance_km (float, default 10), speciality (str or None)
        Returns: JSON string of doctor list (id, name, speciality, opd_fees, address, distance_km), sorted by distance.
        """
        import json
        from langGraph_service.tools.doctor_tools import find_nearby_doctors as _find
        results = _find(
            db=db,
            patient_lat=patient_lat,
            patient_lon=patient_lon,
            max_distance_km=max_distance_km,
            speciality=speciality,
            limit=10,
        )
        if not results:
            return f"No doctors found within {max_distance_km} km."
        return json.dumps(results)

    @tool
    def list_all_specialities() -> str:
        """
        Get all available medical specialities.
        Returns: comma-separated string of specialities, or a message if none found.
        """
        from langGraph_service.tools.doctor_tools import get_all_specialities
        results = get_all_specialities(db)
        if not results:
            return "No specialities found in the system."
        return ", ".join(results)

    return [find_nearby_doctors, list_all_specialities]