from fastapi import APIRouter, Depends, HTTPException, Security, Query
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from typing import Optional, List

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.doctor import Doctor
from schemas.doctor_analytics import (
    # Revenue Schemas
    DailyRevenue,
    WeeklyRevenue,
    MonthlyRevenue,
    RevenueAnalyticsResponse,
    # Appointment Status Schemas
    AppointmentStatusCount,
    AppointmentStatusBreakdown,
    AppointmentStatusAnalyticsResponse,
    # Leave Schemas
    LeaveDay,
    LeaveAnalyticsResponse,
    # Slot Preference Schemas
    SlotPreference,
    SlotPreferenceAnalyticsResponse,
    # Dashboard Schemas
    QuickStats,
    DashboardOverviewResponse,
    # Query Parameter Schemas
    DateRangeParams,
    MonthYearParams
)
from services.doctor_analytics_service import (
    get_daily_revenue,
    get_weekly_revenue,
    get_monthly_revenue,
    get_appointment_status_breakdown,
    get_leave_analytics,
    get_slot_preferences,
    get_quick_stats,
    get_week_bounds,
    get_month_bounds
)

router = APIRouter(
    prefix="/doctor/analytics",
    tags=["Doctor Analytics"],
    dependencies=[Security(bearer_scheme)]
)


# ==================== DASHBOARD OVERVIEW ====================

@router.get("/dashboard", response_model=DashboardOverviewResponse)
def get_dashboard_overview(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get complete dashboard overview with quick statistics.
    Perfect for the main dashboard page.
    
    Returns:
    - Doctor profile info
    - Quick stats (appointments, revenue for today/week/month/all-time)
    - Pending approvals and upcoming appointments
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    quick_stats = get_quick_stats(db, doctor.id)

    return DashboardOverviewResponse(
        doctor_id=doctor.id,
        doctor_name=doctor.name,
        speciality=doctor.speciality,
        opd_fees=doctor.opd_fees,
        quick_stats=quick_stats
    )


@router.get("/dashboard/quick-stats", response_model=QuickStats)
def get_dashboard_quick_stats(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get only quick statistics without doctor profile info.
    Useful for refreshing stats without full dashboard reload.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    return get_quick_stats(db, doctor.id)


# ==================== REVENUE ANALYTICS - DAILY ====================

@router.get("/revenue/daily", response_model=List[DailyRevenue])
def get_revenue_daily_list(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Number of days to fetch (if dates not provided)"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get daily revenue breakdown as a list.
    
    Query Parameters:
    - start_date: Start date (optional)
    - end_date: End date (optional)
    - days: Number of days to fetch if dates not provided (default: 30)
    
    Returns: List of daily revenue records
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if not start_date or not end_date:
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)

    return get_daily_revenue(db, doctor.id, start_date, end_date)


@router.get("/revenue/daily/summary", response_model=RevenueAnalyticsResponse)
def get_revenue_daily_summary(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Number of days to fetch (if dates not provided)"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get daily revenue breakdown wrapped in analytics response.
    Useful when you need the data in the same format as weekly/monthly.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if not start_date or not end_date:
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)

    daily = get_daily_revenue(db, doctor.id, start_date, end_date)

    return RevenueAnalyticsResponse(daily=daily)


# ==================== REVENUE ANALYTICS - WEEKLY ====================

@router.get("/revenue/weekly", response_model=List[WeeklyRevenue])
def get_revenue_weekly_list(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    weeks: int = Query(4, ge=1, le=52, description="Number of weeks to fetch (if dates not provided)"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get weekly revenue breakdown with daily breakdown.
    
    Each week includes:
    - Week start and end dates
    - Total revenue for the week
    - Completed appointments count
    - Daily breakdown within the week
    
    Default: Last 4 weeks if no dates provided.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if not start_date or not end_date:
        end_date = date.today()
        start_date = end_date - timedelta(weeks=weeks)

    return get_weekly_revenue(db, doctor.id, start_date, end_date)


@router.get("/revenue/weekly/summary", response_model=RevenueAnalyticsResponse)
def get_revenue_weekly_summary(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    weeks: int = Query(4, ge=1, le=52, description="Number of weeks to fetch (if dates not provided)"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get weekly revenue breakdown wrapped in analytics response.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if not start_date or not end_date:
        end_date = date.today()
        start_date = end_date - timedelta(weeks=weeks)

    weekly = get_weekly_revenue(db, doctor.id, start_date, end_date)

    return RevenueAnalyticsResponse(weekly=weekly)


# ==================== REVENUE ANALYTICS - MONTHLY ====================

@router.get("/revenue/monthly", response_model=List[MonthlyRevenue])
def get_revenue_monthly_list(
    year: Optional[int] = Query(None, ge=2020, le=2100, description="Year"),
    months: int = Query(6, ge=1, le=12, description="Number of months to fetch"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get monthly revenue breakdown with weekly breakdown.
    
    Each month includes:
    - Month and year
    - Total revenue for the month
    - Completed appointments count
    - Weekly breakdown within the month (with daily breakdown in each week)
    
    Default: Last 6 months of current year.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if not year:
        year = date.today().year

    current_month = date.today().month
    month_list = [(current_month - i - 1) % 12 + 1 for i in range(months)]
    month_list.reverse()

    return get_monthly_revenue(db, doctor.id, year, month_list)


@router.get("/revenue/monthly/summary", response_model=RevenueAnalyticsResponse)
def get_revenue_monthly_summary(
    year: Optional[int] = Query(None, ge=2020, le=2100, description="Year"),
    months: int = Query(6, ge=1, le=12, description="Number of months to fetch"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get monthly revenue breakdown wrapped in analytics response.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if not year:
        year = date.today().year

    current_month = date.today().month
    month_list = [(current_month - i - 1) % 12 + 1 for i in range(months)]
    month_list.reverse()

    monthly = get_monthly_revenue(db, doctor.id, year, month_list)

    return RevenueAnalyticsResponse(monthly=monthly)


# ==================== REVENUE ANALYTICS - COMBINED ====================

@router.get("/revenue/all", response_model=RevenueAnalyticsResponse)
def get_revenue_all_timeframes(
    daily_days: int = Query(30, ge=1, le=365, description="Days for daily breakdown"),
    weekly_weeks: int = Query(4, ge=1, le=52, description="Weeks for weekly breakdown"),
    monthly_months: int = Query(6, ge=1, le=12, description="Months for monthly breakdown"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get revenue analytics for ALL timeframes in one call.
    
    Returns:
    - Daily breakdown (default: last 30 days)
    - Weekly breakdown (default: last 4 weeks)
    - Monthly breakdown (default: last 6 months)
    
    Perfect for rendering complete revenue dashboard.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    today = date.today()

    # Daily
    daily_start = today - timedelta(days=daily_days - 1)
    daily = get_daily_revenue(db, doctor.id, daily_start, today)

    # Weekly
    weekly_start = today - timedelta(weeks=weekly_weeks)
    weekly = get_weekly_revenue(db, doctor.id, weekly_start, today)

    # Monthly
    year = today.year
    current_month = today.month
    month_list = [(current_month - i - 1) % 12 + 1 for i in range(monthly_months)]
    month_list.reverse()
    monthly = get_monthly_revenue(db, doctor.id, year, month_list)

    return RevenueAnalyticsResponse(
        daily=daily,
        weekly=weekly,
        monthly=monthly
    )


# ==================== APPOINTMENT STATUS ANALYTICS ====================

@router.get("/appointments/status/all", response_model=AppointmentStatusAnalyticsResponse)
def get_appointment_status_all_periods(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get appointment status breakdown for ALL time periods.
    
    Returns breakdown for:
    - All time
    - This month
    - This week
    - Today
    
    Each period includes counts and percentages for:
    - REQUESTED, APPROVED, REJECTED, PAID, COMPLETED, CANCELLED
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    today = date.today()
    week_start, week_end = get_week_bounds(today)
    month_start, month_end = get_month_bounds(today.year, today.month)

    all_time = get_appointment_status_breakdown(db, doctor.id)
    this_month = get_appointment_status_breakdown(db, doctor.id, month_start, month_end)
    this_week = get_appointment_status_breakdown(db, doctor.id, week_start, week_end)
    this_today = get_appointment_status_breakdown(db, doctor.id, today, today)

    return AppointmentStatusAnalyticsResponse(
        all_time=all_time,
        this_month=this_month,
        this_week=this_week,
        today=this_today
    )


@router.get("/appointments/status/breakdown", response_model=AppointmentStatusBreakdown)
def get_appointment_status_custom_period(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get appointment status breakdown for a CUSTOM date range.
    
    If no dates provided, returns all-time breakdown.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    return get_appointment_status_breakdown(db, doctor.id, start_date, end_date)


@router.get("/appointments/status/today", response_model=AppointmentStatusBreakdown)
def get_appointment_status_today(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get appointment status breakdown for TODAY only.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    today = date.today()
    return get_appointment_status_breakdown(db, doctor.id, today, today)


@router.get("/appointments/status/this-week", response_model=AppointmentStatusBreakdown)
def get_appointment_status_this_week(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get appointment status breakdown for THIS WEEK (Monday to Sunday).
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    week_start, week_end = get_week_bounds(date.today())
    return get_appointment_status_breakdown(db, doctor.id, week_start, week_end)


@router.get("/appointments/status/this-month", response_model=AppointmentStatusBreakdown)
def get_appointment_status_this_month(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get appointment status breakdown for THIS MONTH.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    today = date.today()
    month_start, month_end = get_month_bounds(today.year, today.month)
    return get_appointment_status_breakdown(db, doctor.id, month_start, month_end)


# ==================== LEAVE ANALYTICS ====================

@router.get("/leave/month", response_model=LeaveAnalyticsResponse)
def get_leave_stats_for_month(
    month: Optional[int] = Query(None, ge=1, le=12, description="Month (1-12)"),
    year: Optional[int] = Query(None, ge=2020, le=2100, description="Year"),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get leave/availability analytics for a SPECIFIC MONTH.
    
    Returns:
    - Total days in month
    - Working days count
    - Leave days count
    - Leave percentage
    - List of all leave dates
    
    Default: Current month if not specified.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if not month:
        month = date.today().month
    if not year:
        year = date.today().year

    leave_data = get_leave_analytics(db, doctor.id, month, year)

    return LeaveAnalyticsResponse(**leave_data)


@router.get("/leave/current-month", response_model=LeaveAnalyticsResponse)
def get_leave_stats_current_month(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get leave analytics for the CURRENT MONTH.
    Shortcut endpoint for current month stats.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    today = date.today()
    leave_data = get_leave_analytics(db, doctor.id, today.month, today.year)

    return LeaveAnalyticsResponse(**leave_data)


# ==================== SLOT PREFERENCE ANALYTICS ====================

@router.get("/slots/preferences/all", response_model=SlotPreferenceAnalyticsResponse)
def get_all_slot_preferences(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get complete time slot preference analytics.
    
    Based on ALL completed appointments, shows:
    - Which time slots are most popular
    - Which time slots are least popular
    - Booking count and percentage for each slot
    - Total slots per day based on doctor's minimum slot duration
    
    Helps doctor understand patient preferences and optimize scheduling.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    slot_data = get_slot_preferences(db, doctor.id)

    if not slot_data:
        raise HTTPException(status_code=404, detail="No slot data available")

    return SlotPreferenceAnalyticsResponse(**slot_data)


@router.get("/slots/preferences/list", response_model=List[SlotPreference])
def get_slot_preferences_list(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get ONLY the list of slot preferences without summary data.
    Useful for charts and graphs.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    slot_data = get_slot_preferences(db, doctor.id)

    if not slot_data:
        raise HTTPException(status_code=404, detail="No slot data available")

    return slot_data['preferences']


@router.get("/slots/preferences/most-popular", response_model=SlotPreference)
def get_most_popular_slot(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get ONLY the most popular time slot.
    Quick endpoint for highlighting peak booking time.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    slot_data = get_slot_preferences(db, doctor.id)

    if not slot_data or not slot_data['most_popular_slot']:
        raise HTTPException(status_code=404, detail="No slot data available")

    return slot_data['most_popular_slot']


@router.get("/slots/preferences/least-popular", response_model=SlotPreference)
def get_least_popular_slot(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get ONLY the least popular time slot.
    Useful for identifying time slots that might need promotion.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    slot_data = get_slot_preferences(db, doctor.id)

    if not slot_data or not slot_data['least_popular_slot']:
        raise HTTPException(status_code=404, detail="No slot data available")

    return slot_data['least_popular_slot']