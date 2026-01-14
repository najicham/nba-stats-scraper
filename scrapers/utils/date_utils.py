# scrapers/utils/date_utils.py

import math
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
import pytz

def validate_date_string(date_text):
    """
    Check if date_text is in YYYY-MM-DD format.
    Returns:
        bool: True if valid date string, False if invalid format.
    """
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def get_datetime_string_pacific(string=True):
    west = ZoneInfo("America/Los_Angeles")
    now_pacific = datetime.now(tz=west)
    return now_pacific.strftime("%Y-%m-%d %H:%M:%S") if string else now_pacific


def get_year_pacific_time():
    tz_west = pytz.timezone("America/Los_Angeles")
    return str(datetime.now(tz_west).year)


def subtract_days_from_date_string(date_string, days):
    """
    Subtract X days from a 'YYYY-MM-DD' string.
    Returns the new date string in same format.
    """
    try:
        x = datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError:
        return False

    new_ds = x - timedelta(days=days)
    return new_ds.strftime("%Y-%m-%d")


def is_date_string_ahead_of_today(date_string):
    """
    If the given date is in the future, raise an Exception.
    """
    today = date.today()
    date_obj = datetime.strptime(date_string, "%Y-%m-%d").date()
    if date_obj > today:
        raise Exception(f"Invalid date: {date_string} is ahead of today {today}")

def get_yesterday_eastern() -> str:
    """
    Get yesterday's date in Eastern Time (YYYY-MM-DD format).

    This is the correct date to use for NBA data since:
    - NBA games are scheduled in Eastern Time
    - West coast games ending at 11 PM PT (2 AM ET next day) still count as
      the previous ET day for box score purposes
    - Using ET ensures consistent date boundaries for all games

    Returns:
        str: Yesterday's date in YYYY-MM-DD format (Eastern Time)
    """
    et_tz = ZoneInfo("America/New_York")
    et_now = datetime.now(et_tz)
    yesterday = (et_now - timedelta(days=1)).date()
    return yesterday.isoformat()


def get_today_eastern() -> str:
    """
    Get today's date in Eastern Time (YYYY-MM-DD format).

    Returns:
        str: Today's date in YYYY-MM-DD format (Eastern Time)
    """
    et_tz = ZoneInfo("America/New_York")
    et_now = datetime.now(et_tz)
    return et_now.date().isoformat()


def get_yesterday_pacific() -> str:
    """
    Get yesterday's date in Pacific Time (YYYY-MM-DD format).

    This is the correct date to use for MLB data since:
    - Many MLB games are played on the west coast
    - Games ending at 10-11 PM PT still count as that PT day
    - Using PT ensures consistent date boundaries for west coast games

    Returns:
        str: Yesterday's date in YYYY-MM-DD format (Pacific Time)
    """
    pt_tz = ZoneInfo("America/Los_Angeles")
    pt_now = datetime.now(pt_tz)
    yesterday = (pt_now - timedelta(days=1)).date()
    return yesterday.isoformat()


def get_today_pacific() -> str:
    """
    Get today's date in Pacific Time (YYYY-MM-DD format).

    Returns:
        str: Today's date in YYYY-MM-DD format (Pacific Time)
    """
    pt_tz = ZoneInfo("America/Los_Angeles")
    pt_now = datetime.now(pt_tz)
    return pt_now.date().isoformat()


# ...Add any other date/time utilities you actually need...
