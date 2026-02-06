from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, time
from decimal import Decimal

# ==================== REVENUE ANALYTICS ====================

class DailyRevenue(BaseModel):
    date: date
    total_revenue: Decimal = Field(default=Decimal("0.00"))
    completed_appointments: int = 0
    
    class Config:
        from_attributes = True


class WeeklyRevenue(BaseModel):
    week_start: date
    week_end: date
    total_revenue: Decimal = Field(default=Decimal("0.00"))
    completed_appointments: int = 0
    daily_breakdown: List[DailyRevenue] = []
    
    class Config:
        from_attributes = True


class MonthlyRevenue(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int
    total_revenue: Decimal = Field(default=Decimal("0.00"))
    completed_appointments: int = 0
    weekly_breakdown: List[WeeklyRevenue] = []
    
    class Config:
        from_attributes = True


class RevenueAnalyticsResponse(BaseModel):
    daily: List[DailyRevenue] = []
    weekly: List[WeeklyRevenue] = []
    monthly: List[MonthlyRevenue] = []
    
    class Config:
        from_attributes = True


# ==================== APPOINTMENT STATUS ANALYTICS ====================

class AppointmentStatusCount(BaseModel):
    status: str
    count: int
    percentage: float = Field(ge=0, le=100)
    
    class Config:
        from_attributes = True


class AppointmentStatusBreakdown(BaseModel):
    total_appointments: int = 0
    requested: int = 0
    approved: int = 0
    rejected: int = 0
    paid: int = 0
    completed: int = 0
    cancelled: int = 0
    breakdown: List[AppointmentStatusCount] = []
    
    class Config:
        from_attributes = True


class AppointmentStatusAnalyticsResponse(BaseModel):
    all_time: AppointmentStatusBreakdown
    this_month: AppointmentStatusBreakdown
    this_week: AppointmentStatusBreakdown
    today: AppointmentStatusBreakdown
    
    class Config:
        from_attributes = True


# ==================== LEAVE/AVAILABILITY ANALYTICS ====================

class LeaveDay(BaseModel):
    date: date
    is_available: bool = False
    
    class Config:
        from_attributes = True


class LeaveAnalyticsResponse(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int
    total_days_in_month: int
    working_days: int = 0
    leave_days: int = 0
    leave_percentage: float = Field(ge=0, le=100)
    leave_dates: List[date] = []
    
    class Config:
        from_attributes = True


# ==================== SLOT PREFERENCE ANALYTICS ====================

class SlotPreference(BaseModel):
    time_slot: str  # e.g., "09:00-09:30"
    start_time: time
    end_time: time
    total_bookings: int = 0
    completed_bookings: int = 0
    percentage_of_total: float = Field(ge=0, le=100)
    
    class Config:
        from_attributes = True


class SlotPreferenceAnalyticsResponse(BaseModel):
    total_completed_appointments: int = 0
    slot_duration_hours: Decimal
    total_slots_per_day: int
    preferences: List[SlotPreference] = []
    most_popular_slot: Optional[SlotPreference] = None
    least_popular_slot: Optional[SlotPreference] = None
    
    class Config:
        from_attributes = True


# ==================== DASHBOARD OVERVIEW ====================

class QuickStats(BaseModel):
    total_appointments_today: int = 0
    total_appointments_this_week: int = 0
    total_appointments_this_month: int = 0
    total_appointments_all_time: int = 0
    
    pending_approvals: int = 0  # REQUESTED status
    upcoming_appointments: int = 0  # PAID status
    completed_this_month: int = 0
    
    revenue_today: Decimal = Field(default=Decimal("0.00"))
    revenue_this_week: Decimal = Field(default=Decimal("0.00"))
    revenue_this_month: Decimal = Field(default=Decimal("0.00"))
    revenue_all_time: Decimal = Field(default=Decimal("0.00"))
    
    class Config:
        from_attributes = True


class DashboardOverviewResponse(BaseModel):
    doctor_id: int
    doctor_name: str
    speciality: str
    opd_fees: Decimal
    quick_stats: QuickStats
    
    class Config:
        from_attributes = True


# ==================== QUERY PARAMETERS ====================

class DateRangeParams(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class MonthYearParams(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2020, le=2100)