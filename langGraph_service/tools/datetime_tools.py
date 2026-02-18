"""
Date and time utilities for IST timezone
Handles date parsing, day calculations, and time conversions
"""

from datetime import datetime, timedelta, date as dt_date
from zoneinfo import ZoneInfo
from typing import Optional, Tuple
import re

IST = ZoneInfo("Asia/Kolkata")


def get_current_ist_time() -> datetime:
    """Get current time in IST timezone"""
    return datetime.now(IST)


def get_current_ist_date() -> dt_date:
    """Get current date in IST timezone"""
    return get_current_ist_time().date()


def format_ist_datetime(dt: datetime) -> str:
    """Format datetime in IST for display"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(IST).strftime("%d %B %Y, %I:%M %p IST")


def parse_relative_date(text: str) -> Optional[dt_date]:
    """Parse relative date expressions like 'today', 'tomorrow', 'day after tomorrow'"""
    text_lower = text.lower().strip()
    today = get_current_ist_date()

    if "day after tomorrow" in text_lower or "overmorrow" in text_lower:
        return today + timedelta(days=2)
    elif "tomorrow" in text_lower:
        return today + timedelta(days=1)
    elif "today" in text_lower:
        return today
    elif "yesterday" in text_lower:
        return today - timedelta(days=1)

    return None


def parse_day_name(text: str) -> Optional[str]:
    """Extract day name from text (Monday, Tuesday, etc.)"""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    text_lower = text.lower()
    for day in days:
        if day in text_lower:
            return day.capitalize()
    return None


def parse_date_string(text: str) -> Optional[dt_date]:
    """Parse various date formats from text"""
    # YYYY-MM-DD
    match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if match:
        try:
            return dt_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    # DD/MM/YYYY or DD-MM-YYYY
    match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', text)
    if match:
        try:
            return dt_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            pass

    # Text date formats
    date_formats = [
        "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
        "%d %B", "%d %b",
    ]
    for fmt in date_formats:
        try:
            parsed = datetime.strptime(text.strip(), fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=get_current_ist_date().year)
            return parsed.date()
        except ValueError:
            continue

    return None


def parse_time_string(text: str) -> Optional[Tuple[int, int]]:
    """Parse time from text. Returns (hour, minute) in 24-hr format."""
    match = re.search(r'(\d{1,2}):(\d{2})', text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 'pm' in text.lower() and hour < 12:
            hour += 12
        elif 'am' in text.lower() and hour == 12:
            hour = 0
        if 0 <= hour < 24 and 0 <= minute < 60:
            return (hour, minute)

    match = re.search(r'(\d{1,2})\s*(am|pm)', text.lower())
    if match:
        hour = int(match.group(1))
        period = match.group(2)
        if period == 'pm' and hour < 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0
        if 0 <= hour < 24:
            return (hour, 0)

    return None


def get_next_weekday(day_name: str) -> dt_date:
    """Get the next occurrence of a weekday from today."""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_day = days.index(day_name.lower())
    today = get_current_ist_date()
    current_day = today.weekday()
    days_ahead = target_day - current_day
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def is_date_in_past(date: dt_date) -> bool:
    """Check if date is in the past"""
    return date < get_current_ist_date()


def is_within_25_hours(date: dt_date, time_hour: int = 0, time_minute: int = 0) -> bool:
    """
    Check if datetime is within 25 hours from now.
    (Used for 25-hour advance booking rule — doctor needs 24hrs to approve)
    """
    target_dt = datetime.combine(
        date,
        datetime.min.time().replace(hour=time_hour, minute=time_minute)
    ).replace(tzinfo=IST)
    now = get_current_ist_time()
    hours_until = (target_dt - now).total_seconds() / 3600
    return hours_until < 25


def format_date_friendly(date: dt_date) -> str:
    """Format date in friendly format (e.g., '25 December 2024')"""
    return date.strftime("%d %B %Y")


def format_time_friendly(hour: int, minute: int) -> str:
    """Format time in friendly format (e.g., '02:30 PM')"""
    period = "AM" if hour < 12 else "PM"
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour:02d}:{minute:02d} {period}"