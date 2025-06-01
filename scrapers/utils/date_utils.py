# scrapers/utils/date_utils.py

import math
from datetime import datetime, timedelta, timezone, date
import pytz

def validate_date_string(date_text):
    """
    Check if date_text is in YYYY-MM-DD format.
    Returns True/False instead of raising.
    """
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def get_datetime_string_pacific(string=True):
    """
    Returns current time in Pacific Timezone.
    If string=True, returns 'YYYY-MM-DD HH:MM:SS'.
    Else returns a datetime object.
    """
    tz_west = pytz.timezone("America/Los_Angeles")
    x = datetime.now(tz_west)
    return x.strftime("%Y-%m-%d %H:%M:%S") if string else x


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

# ...Add any other date/time utilities you actually need...
