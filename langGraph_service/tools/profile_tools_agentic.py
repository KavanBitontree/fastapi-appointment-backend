"""
Profile Tools — Agentic Version

Fix: All tools return non-empty dicts/strings to satisfy Groq's tool result validation.
"""

from langchain_core.tools import tool
from sqlalchemy.orm import Session


def make_profile_tools(db: Session, patient_id: int, user_id: int) -> list:

    @tool
    def get_patient_profile() -> str:
        """
        Retrieve the current patient's full profile (name, DOB, age, email).
        Returns: JSON string of profile dict, or error message if not found.
        """
        import json
        from langGraph_service.tools.profile_tools import get_patient_profile as _get
        result = _get(db, patient_id, user_id)
        if not result:
            return "Patient profile not found."
        return json.dumps(result)

    @tool
    def update_patient_name(new_name: str) -> str:
        """
        Update the patient's display name. Only call when patient explicitly provides a new name.
        Args: new_name (str) — minimum 2 characters
        Returns: JSON string with success (bool), updated_name (str), or error (str).
        """
        import json
        from langGraph_service.tools.profile_tools import update_patient_name as _update
        result = _update(db, patient_id, new_name)
        return json.dumps(result)

    @tool
    def update_patient_dob(new_dob: str) -> str:
        """
        Update the patient's date of birth. Only call when patient explicitly provides a date.
        Args: new_dob (str) — YYYY-MM-DD format, must be in the past
        Returns: JSON string with success (bool), updated_dob, age, or error.
        """
        import json
        from datetime import date as dt_date
        from langGraph_service.tools.profile_tools import update_patient_dob as _update
        try:
            dob = dt_date.fromisoformat(new_dob)
        except ValueError:
            return json.dumps({"success": False, "error": f"Invalid date format: '{new_dob}'. Use YYYY-MM-DD."})
        result = _update(db, patient_id, dob)
        return json.dumps(result)

    return [get_patient_profile, update_patient_name, update_patient_dob]