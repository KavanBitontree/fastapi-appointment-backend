from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract, case
from datetime import datetime, date, timedelta, time
from decimal import Decimal
from typing import List, Dict, Tuple
import calendar

from models.appointment import Appointment
from models.payment import Payment
from models.doctor_availability import DoctorAvailability
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor
from core.enums import AppointmentStatus, PaymentStatus, SlotStatus
from schemas.doctor_analytics import (
    DailyRevenue, WeeklyRevenue, MonthlyRevenue,
    AppointmentStatusCount, AppointmentStatusBreakdown,
    LeaveDay, SlotPreference, QuickStats
)


# ==================== HELPER FUNCTIONS ====================

def get_week_bounds(target_date: date) -> Tuple[date, date]:
    """Get Monday and Sunday of the week containing target_date"""
    days_since_monday = target_date.weekday()
    week_start = target_date - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def get_month_bounds(year: int, month: int) -> Tuple[date, date]:
    """Get first and last day of month"""
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    return first_day, last_day


def calculate_percentage(part: int, total: int) -> float:
    """Calculate percentage with division by zero protection"""
    if total == 0:
        return 0.0
    return round((part / total) * 100, 2)


# ==================== REVENUE ANALYTICS ====================

def get_daily_revenue(db: Session, doctor_id: int, start_date: date, end_date: date) -> List[DailyRevenue]:
    """Get daily revenue breakdown"""
    results = db.query(
        func.date(Payment.updated_at).label('date'),  # ✅ Use updated_at
        func.sum(Payment.amount).label('total_revenue'),
        func.count(Appointment.id).label('completed_appointments')
    ).join(
        Appointment, Appointment.id == Payment.appointment_id
    ).join(
        DoctorSlot, DoctorSlot.id == Appointment.slot_id
    ).filter(
        DoctorSlot.doctor_id == doctor_id,
        Appointment.status.in_([AppointmentStatus.PAID, AppointmentStatus.COMPLETED]),
        Payment.status == PaymentStatus.SUCCESS,
        func.date(Payment.updated_at) >= start_date,  # ✅ Filter by payment success date
        func.date(Payment.updated_at) <= end_date
    ).group_by(
        func.date(Payment.updated_at)  # ✅ Group by payment success date
    ).order_by(
        func.date(Payment.updated_at)
    ).all()

    return [
        DailyRevenue(
            date=row.date,
            total_revenue=row.total_revenue or Decimal("0.00"),
            completed_appointments=row.completed_appointments or 0
        )
        for row in results
    ]


def get_weekly_revenue(db: Session, doctor_id: int, start_date: date, end_date: date) -> List[WeeklyRevenue]:
    """Get weekly revenue breakdown with daily breakdown"""
    weekly_data = {}
    
    # Get all daily revenue in range
    daily_revenues = get_daily_revenue(db, doctor_id, start_date, end_date)
    
    # Group by week
    for daily in daily_revenues:
        week_start, week_end = get_week_bounds(daily.date)
        week_key = (week_start, week_end)
        
        if week_key not in weekly_data:
            weekly_data[week_key] = {
                'total_revenue': Decimal("0.00"),
                'completed_appointments': 0,
                'daily_breakdown': []
            }
        
        weekly_data[week_key]['total_revenue'] += daily.total_revenue
        weekly_data[week_key]['completed_appointments'] += daily.completed_appointments
        weekly_data[week_key]['daily_breakdown'].append(daily)
    
    # Convert to response objects
    return [
        WeeklyRevenue(
            week_start=week_start,
            week_end=week_end,
            total_revenue=data['total_revenue'],
            completed_appointments=data['completed_appointments'],
            daily_breakdown=sorted(data['daily_breakdown'], key=lambda x: x.date)
        )
        for (week_start, week_end), data in sorted(weekly_data.items())
    ]


def get_monthly_revenue(db: Session, doctor_id: int, year: int, months: List[int]) -> List[MonthlyRevenue]:
    """Get monthly revenue breakdown with weekly breakdown"""
    monthly_results = []
    
    for month in months:
        first_day, last_day = get_month_bounds(year, month)
        
        # Get weekly data for this month
        weekly_revenues = get_weekly_revenue(db, doctor_id, first_day, last_day)
        
        # Calculate monthly totals
        total_revenue = sum(week.total_revenue for week in weekly_revenues)
        total_appointments = sum(week.completed_appointments for week in weekly_revenues)
        
        monthly_results.append(
            MonthlyRevenue(
                month=month,
                year=year,
                total_revenue=total_revenue,
                completed_appointments=total_appointments,
                weekly_breakdown=weekly_revenues
            )
        )
    
    return monthly_results


# ==================== APPOINTMENT STATUS ANALYTICS ====================

def get_appointment_status_breakdown(
    db: Session, 
    doctor_id: int, 
    start_date: date = None, 
    end_date: date = None
) -> AppointmentStatusBreakdown:
    """Get appointment status breakdown for a date range"""
    
    query = db.query(
        Appointment.status,
        func.count(Appointment.id).label('count')
    ).join(
        DoctorSlot, DoctorSlot.id == Appointment.slot_id
    ).filter(
        DoctorSlot.doctor_id == doctor_id
    )
    
    if start_date:
        query = query.filter(DoctorSlot.date >= start_date)
    if end_date:
        query = query.filter(DoctorSlot.date <= end_date)
    
    results = query.group_by(Appointment.status).all()
    
    # Initialize counts
    status_counts = {status.value: 0 for status in AppointmentStatus}
    total = 0
    
    for row in results:
        status_counts[row.status.value] = row.count
        total += row.count
    
    # Create breakdown list
    breakdown = [
        AppointmentStatusCount(
            status=status,
            count=count,
            percentage=calculate_percentage(count, total)
        )
        for status, count in status_counts.items()
    ]
    
    return AppointmentStatusBreakdown(
        total_appointments=total,
        requested=status_counts[AppointmentStatus.REQUESTED.value],
        approved=status_counts[AppointmentStatus.APPROVED.value],
        rejected=status_counts[AppointmentStatus.REJECTED.value],
        paid=status_counts[AppointmentStatus.PAID.value],
        completed=status_counts[AppointmentStatus.COMPLETED.value],
        cancelled=status_counts[AppointmentStatus.CANCELLED.value],
        breakdown=breakdown
    )


# ==================== LEAVE ANALYTICS ====================

def get_leave_analytics(db: Session, doctor_id: int, month: int, year: int) -> Dict:
    """Get leave/availability analytics for a specific month"""
    
    first_day, last_day = get_month_bounds(year, month)
    total_days = (last_day - first_day).days + 1
    
    # Get all availability records for the month
    availabilities = db.query(DoctorAvailability).filter(
        DoctorAvailability.doctor_id == doctor_id,
        DoctorAvailability.date >= first_day,
        DoctorAvailability.date <= last_day
    ).all()
    
    # Create a set of all dates in month
    all_dates = {first_day + timedelta(days=i) for i in range(total_days)}
    
    # Create sets for working and leave days
    working_dates = {avail.date for avail in availabilities if avail.is_available}
    leave_dates = {avail.date for avail in availabilities if not avail.is_available}
    
    # Dates with no availability record are considered leave
    unrecorded_dates = all_dates - {avail.date for avail in availabilities}
    leave_dates.update(unrecorded_dates)
    
    working_days = len(working_dates)
    leave_days = len(leave_dates)
    
    return {
        'month': month,
        'year': year,
        'total_days_in_month': total_days,
        'working_days': working_days,
        'leave_days': leave_days,
        'leave_percentage': calculate_percentage(leave_days, total_days),
        'leave_dates': sorted(list(leave_dates))
    }


# ==================== SLOT PREFERENCE ANALYTICS ====================

def get_slot_preferences(db: Session, doctor_id: int) -> Dict:
    """Get time slot preference analytics based on all appointments"""
    
    # Get doctor's slot duration
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        return None
    
    slot_duration = doctor.minimum_slot_duration
    
    # Calculate total possible slots per day (9 AM to 5 PM = 8 hours)
    working_hours = 8
    total_slots_per_day = int(working_hours / float(slot_duration))
    
    # Get ALL appointments with their slot times
    # Group by time slot (start_time, end_time combination)
    results = db.query(
        DoctorSlot.start_time,
        DoctorSlot.end_time,
        func.count(Appointment.id).label('total_bookings'),
        func.sum(
            case(
                (Appointment.status.in_([AppointmentStatus.PAID, AppointmentStatus.COMPLETED]), 1),
                else_=0
            )
        ).label('completed_bookings')
    ).join(
        Appointment, Appointment.slot_id == DoctorSlot.id  # Inner join - only slots with appointments
    ).filter(
        DoctorSlot.doctor_id == doctor_id
        # ✅ NO status filter here - count ALL appointments (even CANCELLED, REJECTED)
        # This shows true demand for each time slot
    ).group_by(
        DoctorSlot.start_time,
        DoctorSlot.end_time
    ).order_by(
        DoctorSlot.start_time
    ).all()
    
    if not results:
        # No appointments exist at all
        return {
            'total_completed_appointments': 0,
            'slot_duration_hours': slot_duration,
            'total_slots_per_day': total_slots_per_day,
            'preferences': [],
            'most_popular_slot': None,
            'least_popular_slot': None
        }
    
    # Calculate total completed appointments (PAID + COMPLETED only)
    total_completed = sum(row.completed_bookings or 0 for row in results)
    
    # Create slot preference objects
    preferences = []
    for row in results:
        total = row.total_bookings or 0
        completed = row.completed_bookings or 0
        
        preferences.append(
            SlotPreference(
                time_slot=f"{row.start_time.strftime('%H:%M')}-{row.end_time.strftime('%H:%M')}",
                start_time=row.start_time,
                end_time=row.end_time,
                total_bookings=total,
                completed_bookings=completed,
                percentage_of_total=calculate_percentage(completed, total_completed) if total_completed > 0 else 0.0
            )
        )
    
    # Find most and least popular slots based on completed bookings
    # Filter out slots with 0 completed bookings for min/max calculation
    slots_with_bookings = [p for p in preferences if p.completed_bookings > 0]
    
    if slots_with_bookings:
        most_popular = max(slots_with_bookings, key=lambda x: x.completed_bookings)
        least_popular = min(slots_with_bookings, key=lambda x: x.completed_bookings)
    else:
        # If no completed bookings, use total bookings
        most_popular = max(preferences, key=lambda x: x.total_bookings) if preferences else None
        least_popular = min(preferences, key=lambda x: x.total_bookings) if preferences else None
    
    return {
        'total_completed_appointments': total_completed,
        'slot_duration_hours': slot_duration,
        'total_slots_per_day': total_slots_per_day,
        'preferences': preferences,
        'most_popular_slot': most_popular,
        'least_popular_slot': least_popular
    }


# ==================== QUICK STATS ====================

def get_quick_stats(db: Session, doctor_id: int) -> QuickStats:
    """Get quick statistics for dashboard overview"""
    
    today = date.today()
    week_start, week_end = get_week_bounds(today)
    month_start, month_end = get_month_bounds(today.year, today.month)
    
    # Helper to count appointments
    def count_appointments(start: date = None, end: date = None, status: AppointmentStatus = None):
        query = db.query(func.count(Appointment.id)).join(
            DoctorSlot, DoctorSlot.id == Appointment.slot_id
        ).filter(
            DoctorSlot.doctor_id == doctor_id
        )
        
        if start:
            query = query.filter(DoctorSlot.date >= start)
        if end:
            query = query.filter(DoctorSlot.date <= end)
        if status:
            query = query.filter(Appointment.status == status)
        
        return query.scalar() or 0
    
    # Helper to calculate revenue
    def calculate_revenue(start: date = None, end: date = None):
        query = db.query(func.sum(Payment.amount)).join(
            Appointment, Appointment.id == Payment.appointment_id
        ).join(
            DoctorSlot, DoctorSlot.id == Appointment.slot_id
        ).filter(
            DoctorSlot.doctor_id == doctor_id,
            Appointment.status.in_([AppointmentStatus.PAID, AppointmentStatus.COMPLETED]),
            Payment.status == PaymentStatus.SUCCESS
        )
        
        if start:
            query = query.filter(func.date(Payment.updated_at) >= start)  # ✅ Use updated_at
        if end:
            query = query.filter(func.date(Payment.updated_at) <= end)
        
        return query.scalar() or Decimal("0.00")
    
    return QuickStats(
        total_appointments_today=count_appointments(today, today),
        total_appointments_this_week=count_appointments(week_start, week_end),
        total_appointments_this_month=count_appointments(month_start, month_end),
        total_appointments_all_time=count_appointments(),
        
        pending_approvals=count_appointments(status=AppointmentStatus.REQUESTED),
        upcoming_appointments=count_appointments(status=AppointmentStatus.PAID),
        completed_this_month=count_appointments(month_start, month_end, AppointmentStatus.COMPLETED),
        
        revenue_today=calculate_revenue(today, today),
        revenue_this_week=calculate_revenue(week_start, week_end),
        revenue_this_month=calculate_revenue(month_start, month_end),
        revenue_all_time=calculate_revenue()
    )