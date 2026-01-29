from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional

from deps import get_db
from models.doctor import Doctor
from models.user import User
from middlewares.auth import auth_required, roles_required
from core.enums import UserRole
from schemas.doctor import DoctorRead

router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.get("/", response_model=List[DoctorRead])
@auth_required
@roles_required(UserRole.PATIENT)
def get_all_doctors(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of records to return"),
    sort_by: str = Query("name", description="Field to sort by (name, speciality, opd_fees)"),
    sort_order: str = Query("asc", description="Sort order (asc or desc)"),
    search_name: Optional[str] = Query(None, description="Search by doctor name"),
    search_address: Optional[str] = Query(None, description="Search by doctor address"),
    filter_speciality: Optional[str] = Query(None, description="Filter by speciality")
):
    """
    Get all doctors with filtering, searching, and sorting capabilities
    Only accessible by patients
    """
    query = db.query(Doctor).join(User)

    # Apply filters
    if filter_speciality:
        query = query.filter(Doctor.speciality.ilike(f"%{filter_speciality}%"))

    # Apply searches
    if search_name:
        query = query.filter(Doctor.name.ilike(f"%{search_name}%"))

    if search_address:
        query = query.filter(Doctor.address.ilike(f"%{search_address}%"))

    # Apply sorting
    if sort_by == "name":
        if sort_order == "desc":
            query = query.order_by(Doctor.name.desc())
        else:
            query = query.order_by(Doctor.name.asc())
    elif sort_by == "speciality":
        if sort_order == "desc":
            query = query.order_by(Doctor.speciality.desc())
        else:
            query = query.order_by(Doctor.speciality.asc())
    elif sort_by == "opd_fees":
        if sort_order == "desc":
            query = query.order_by(Doctor.opd_fees.desc())
        else:
            query = query.order_by(Doctor.opd_fees.asc())

    # Apply pagination
    doctors = query.offset(skip).limit(limit).all()
    
    return doctors


@router.get("/{doctor_id}", response_model=DoctorRead)
@auth_required
@roles_required(UserRole.PATIENT)
def get_doctor_by_id(
    doctor_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a single doctor by ID
    Only accessible by patients
    """
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    return doctor