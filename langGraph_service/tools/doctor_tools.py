"""
Doctor search tools for LangGraph chatbot.
Direct DB operations using SQLAlchemy.
"""

from sqlalchemy.orm import Session
from typing import List, Dict, Optional
from math import radians, cos, sin, asin, sqrt


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two coordinates in km (Haversine formula)."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def search_doctors_by_name(db: Session, name: str, limit: int = 10) -> List[Dict]:
    """Search doctors by name (case-insensitive partial match)."""
    from models.doctor import Doctor

    doctors = db.query(Doctor).filter(Doctor.name.ilike(f"%{name}%")).limit(limit).all()
    return [_doctor_to_dict(d) for d in doctors]


def search_doctors_by_speciality(db: Session, speciality: str, limit: int = 10) -> List[Dict]:
    """Search doctors by speciality (case-insensitive partial match)."""
    from models.doctor import Doctor

    doctors = db.query(Doctor).filter(Doctor.speciality.ilike(f"%{speciality}%")).limit(limit).all()
    return [_doctor_to_dict(d) for d in doctors]


def get_all_doctors(db: Session, limit: int = 10, skip: int = 0) -> Dict:
    """Get paginated list of all doctors."""
    from models.doctor import Doctor

    total = db.query(Doctor).count()
    doctors = db.query(Doctor).order_by(Doctor.name).offset(skip).limit(limit).all()
    return {"total": total, "doctors": [_doctor_to_dict(d) for d in doctors]}


def get_all_specialities(db: Session) -> List[str]:
    """Get list of unique specialities from all doctors."""
    from models.doctor import Doctor

    specialities = db.query(Doctor.speciality).distinct().order_by(Doctor.speciality).all()
    return [s[0] for s in specialities]


def find_nearby_doctors(
    db: Session,
    patient_lat: float,
    patient_lon: float,
    max_distance_km: float = 10.0,
    speciality: Optional[str] = None,
    limit: int = 10
) -> List[Dict]:
    """Find doctors within max_distance_km of patient location."""
    from models.doctor import Doctor

    query = db.query(Doctor)
    if speciality:
        query = query.filter(Doctor.speciality.ilike(f"%{speciality}%"))

    all_doctors = query.all()
    result = []
    for doctor in all_doctors:
        if doctor.latitude is None or doctor.longitude is None:
            continue
        dist = haversine_distance(patient_lat, patient_lon, doctor.latitude, doctor.longitude)
        if dist <= max_distance_km:
            d = _doctor_to_dict(doctor)
            d["distance_km"] = round(dist, 2)
            result.append(d)

    result.sort(key=lambda x: x["distance_km"])
    return result[:limit]


def get_doctor_by_id(db: Session, doctor_id: int) -> Optional[Dict]:
    """Get doctor details by ID."""
    from models.doctor import Doctor

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        return None
    return _doctor_to_dict(doctor)


def _doctor_to_dict(doctor) -> Dict:
    return {
        "id": doctor.id,
        "name": doctor.name,
        "speciality": doctor.speciality,
        "opd_fees": float(doctor.opd_fees),
        "address": doctor.address or "N/A",
        "latitude": doctor.latitude,
        "longitude": doctor.longitude,
    }