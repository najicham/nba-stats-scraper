"""
Property-based tests for date parsing and formatting.

Uses Hypothesis to verify:
- Round-trip property (parse(format(date)) == date)
- Timezone conversion consistency
- Date ordering preserved
- Format detection correctness
- Edge cases (leap years, month boundaries)
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
from datetime import datetime, date, timedelta, timezone
import re


# =============================================================================
# Date Parsing/Formatting Functions
# =============================================================================

def format_date_iso(dt):
    """Format date as ISO string (YYYY-MM-DD)."""
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    elif isinstance(dt, date):
        return dt.isoformat()
    else:
        raise ValueError(f"Invalid date type: {type(dt)}")


def format_date_compact(dt):
    """Format date as compact string (YYYYMMDD)."""
    if isinstance(dt, datetime):
        return dt.strftime('%Y%m%d')
    elif isinstance(dt, date):
        return dt.strftime('%Y%m%d')
    else:
        raise ValueError(f"Invalid date type: {type(dt)}")


def parse_date_iso(date_str):
    """Parse ISO date string (YYYY-MM-DD)."""
    return datetime.strptime(date_str, '%Y-%m-%d').date()


def parse_date_compact(date_str):
    """Parse compact date string (YYYYMMDD)."""
    return datetime.strptime(date_str, '%Y%m%d').date()


def parse_date_flexible(date_str):
    """Parse date string in multiple formats."""
    if not date_str:
        return None

    # Remove whitespace
    date_str = date_str.strip()

    # Try ISO format first (YYYY-MM-DD)
    if '-' in date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Try compact format (YYYYMMDD)
    if len(date_str) == 8 and date_str.isdigit():
        try:
            return datetime.strptime(date_str, '%Y%m%d').date()
        except ValueError:
            pass

    # Try slash format (MM/DD/YYYY)
    if '/' in date_str:
        try:
            return datetime.strptime(date_str, '%m/%d/%Y').date()
        except ValueError:
            pass

    return None


def get_season_year(game_date):
    """Get season year from game date (NBA season starts in October)."""
    if isinstance(game_date, str):
        game_date = parse_date_flexible(game_date)

    if game_date is None:
        return None

    # NBA season starts in October
    if game_date.month >= 10:
        return game_date.year
    else:
        return game_date.year - 1


# =============================================================================
# Strategies for Date Testing
# =============================================================================

@composite
def nba_game_date(draw):
    """Generate a realistic NBA game date."""
    # NBA regular season: October through April
    # Playoffs: April through June
    return draw(st.dates(min_value=date(2015, 10, 1), max_value=date(2030, 6, 30)))


@composite
def date_string_iso(draw):
    """Generate ISO format date string."""
    dt = draw(nba_game_date())
    return dt.isoformat()


@composite
def date_string_compact(draw):
    """Generate compact format date string."""
    dt = draw(nba_game_date())
    return dt.strftime('%Y%m%d')


# =============================================================================
# Round-Trip Tests
# =============================================================================

class TestRoundTrip:
    """Test that date parsing/formatting is reversible."""

    @given(nba_game_date())
    @settings(max_examples=500)
    def test_iso_round_trip(self, dt):
        """Property: parse(format_iso(date)) == date."""
        formatted = format_date_iso(dt)
        parsed = parse_date_iso(formatted)

        assert parsed == dt

    @given(nba_game_date())
    def test_compact_round_trip(self, dt):
        """Property: parse(format_compact(date)) == date."""
        formatted = format_date_compact(dt)
        parsed = parse_date_compact(formatted)

        assert parsed == dt

    @given(nba_game_date())
    def test_flexible_parse_iso(self, dt):
        """Property: Flexible parser handles ISO format."""
        iso_str = format_date_iso(dt)
        parsed = parse_date_flexible(iso_str)

        assert parsed == dt

    @given(nba_game_date())
    def test_flexible_parse_compact(self, dt):
        """Property: Flexible parser handles compact format."""
        compact_str = format_date_compact(dt)
        parsed = parse_date_flexible(compact_str)

        assert parsed == dt

    @given(nba_game_date())
    def test_multiple_round_trips(self, dt):
        """Property: Multiple round trips preserve value."""
        # ISO round trip
        iso1 = format_date_iso(dt)
        parsed1 = parse_date_iso(iso1)
        iso2 = format_date_iso(parsed1)
        parsed2 = parse_date_iso(iso2)

        assert dt == parsed1 == parsed2
        assert iso1 == iso2


# =============================================================================
# Format Detection Tests
# =============================================================================

class TestFormatDetection:
    """Test that date format is correctly detected."""

    @given(date_string_iso())
    def test_iso_format_detected(self, iso_str):
        """Property: ISO format strings are recognized."""
        assert '-' in iso_str
        assert len(iso_str) == 10

        parsed = parse_date_flexible(iso_str)
        assert parsed is not None

    @given(date_string_compact())
    def test_compact_format_detected(self, compact_str):
        """Property: Compact format strings are recognized."""
        assert len(compact_str) == 8
        assert compact_str.isdigit()

        parsed = parse_date_flexible(compact_str)
        assert parsed is not None

    @given(st.sampled_from(['invalid', '2024-13-01', '2024-01-32', '', '   ']))
    def test_invalid_format_returns_none(self, invalid_str):
        """Property: Invalid date strings return None."""
        parsed = parse_date_flexible(invalid_str)
        assert parsed is None


# =============================================================================
# Date Ordering Tests
# =============================================================================

class TestDateOrdering:
    """Test that date ordering is preserved."""

    @given(nba_game_date(), st.integers(min_value=1, max_value=365))
    def test_later_date_compares_greater(self, dt, days_ahead):
        """Property: Later dates compare greater."""
        later_date = dt + timedelta(days=days_ahead)

        assert later_date > dt
        assert dt < later_date

    @given(nba_game_date())
    def test_same_date_compares_equal(self, dt):
        """Property: Same date compares equal."""
        dt_copy = date(dt.year, dt.month, dt.day)

        assert dt == dt_copy
        assert not (dt < dt_copy)
        assert not (dt > dt_copy)

    @given(nba_game_date(), nba_game_date())
    def test_ordering_preserved_through_format(self, dt1, dt2):
        """Property: Date ordering preserved through format/parse."""
        # Format both dates
        iso1 = format_date_iso(dt1)
        iso2 = format_date_iso(dt2)

        # String comparison should preserve ordering
        if dt1 < dt2:
            assert iso1 < iso2
        elif dt1 > dt2:
            assert iso1 > iso2
        else:
            assert iso1 == iso2

    @given(st.lists(nba_game_date(), min_size=2, max_size=20))
    def test_sorting_preserves_order(self, dates):
        """Property: Sorting dates maintains chronological order."""
        sorted_dates = sorted(dates)

        # Each date should be <= next date
        for i in range(len(sorted_dates) - 1):
            assert sorted_dates[i] <= sorted_dates[i + 1]


# =============================================================================
# Season Year Calculation Tests
# =============================================================================

class TestSeasonYear:
    """Test season year calculation."""

    @given(st.dates(min_value=date(2020, 10, 1), max_value=date(2030, 12, 31)))
    def test_october_onwards_same_year(self, dt):
        """Property: Games in Oct-Dec belong to that year's season."""
        assume(dt.month >= 10)

        season = get_season_year(dt)
        assert season == dt.year

    @given(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 9, 30)))
    def test_before_october_previous_year(self, dt):
        """Property: Games in Jan-Sep belong to previous year's season."""
        assume(dt.month < 10)

        season = get_season_year(dt)
        assert season == dt.year - 1

    @given(nba_game_date())
    def test_season_year_consistent_with_string(self, dt):
        """Property: Season year same for date object and string."""
        season_from_date = get_season_year(dt)
        season_from_string = get_season_year(dt.isoformat())

        assert season_from_date == season_from_string

    @given(st.integers(min_value=2020, max_value=2030))
    def test_season_boundary_october_1(self, year):
        """Property: October 1st is start of new season."""
        oct_1 = date(year, 10, 1)
        season = get_season_year(oct_1)

        assert season == year

    @given(st.integers(min_value=2020, max_value=2030))
    def test_season_boundary_september_30(self, year):
        """Property: September 30th is end of previous season."""
        sep_30 = date(year, 9, 30)
        season = get_season_year(sep_30)

        assert season == year - 1


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Test edge cases in date handling."""

    @example(date(2024, 2, 29))  # Leap year
    @given(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
    def test_leap_year_dates(self, dt):
        """Property: Leap year dates are handled correctly."""
        formatted = format_date_iso(dt)
        parsed = parse_date_iso(formatted)

        assert parsed == dt

    @given(st.integers(min_value=2020, max_value=2030), st.integers(min_value=1, max_value=12))
    def test_month_boundaries(self, year, month):
        """Property: Month boundaries are handled correctly."""
        # Get last day of month
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        last_day = next_month - timedelta(days=1)

        formatted = format_date_iso(last_day)
        parsed = parse_date_iso(formatted)

        assert parsed == last_day

    @given(st.integers(min_value=2020, max_value=2030))
    def test_year_boundaries(self, year):
        """Property: Year boundaries are handled correctly."""
        jan_1 = date(year, 1, 1)
        dec_31 = date(year, 12, 31)

        # Format and parse both
        jan_formatted = format_date_iso(jan_1)
        dec_formatted = format_date_iso(dec_31)

        jan_parsed = parse_date_iso(jan_formatted)
        dec_parsed = parse_date_iso(dec_formatted)

        assert jan_parsed == jan_1
        assert dec_parsed == dec_31


# =============================================================================
# Format Consistency Tests
# =============================================================================

class TestFormatConsistency:
    """Test that formatting is consistent."""

    @given(nba_game_date())
    def test_iso_format_structure(self, dt):
        """Property: ISO format always has correct structure."""
        formatted = format_date_iso(dt)

        # Should match YYYY-MM-DD pattern
        assert re.match(r'^\d{4}-\d{2}-\d{2}$', formatted)

    @given(nba_game_date())
    def test_compact_format_structure(self, dt):
        """Property: Compact format always has correct structure."""
        formatted = format_date_compact(dt)

        # Should be 8 digits
        assert len(formatted) == 8
        assert formatted.isdigit()

    @given(nba_game_date())
    def test_formatting_deterministic(self, dt):
        """Property: Same date produces same formatted string."""
        iso1 = format_date_iso(dt)
        iso2 = format_date_iso(dt)
        iso3 = format_date_iso(dt)

        assert iso1 == iso2 == iso3

        compact1 = format_date_compact(dt)
        compact2 = format_date_compact(dt)

        assert compact1 == compact2


# =============================================================================
# Conversion Between Formats Tests
# =============================================================================

class TestFormatConversion:
    """Test conversion between different date formats."""

    @given(nba_game_date())
    def test_iso_to_compact_conversion(self, dt):
        """Property: Can convert between ISO and compact formats."""
        iso = format_date_iso(dt)
        compact = format_date_compact(dt)

        # Parse both and should get same date
        parsed_iso = parse_date_iso(iso)
        parsed_compact = parse_date_compact(compact)

        assert parsed_iso == parsed_compact == dt

    @given(date_string_iso())
    def test_convert_iso_to_compact(self, iso_str):
        """Property: Converting ISO to compact preserves date."""
        parsed = parse_date_iso(iso_str)
        compact = format_date_compact(parsed)
        reparsed = parse_date_compact(compact)

        assert parsed == reparsed

    @given(date_string_compact())
    def test_convert_compact_to_iso(self, compact_str):
        """Property: Converting compact to ISO preserves date."""
        parsed = parse_date_compact(compact_str)
        iso = format_date_iso(parsed)
        reparsed = parse_date_iso(iso)

        assert parsed == reparsed


# =============================================================================
# Null/Empty Handling Tests
# =============================================================================

class TestNullHandling:
    """Test handling of null/empty date values."""

    @given(st.sampled_from([None, '', '  ', '\t']))
    def test_empty_date_returns_none(self, empty_val):
        """Property: Empty date strings return None."""
        result = parse_date_flexible(empty_val or '')
        assert result is None

    @given(st.sampled_from([None, '', '  ']))
    def test_empty_season_year_returns_none(self, empty_val):
        """Property: Empty date for season returns None."""
        result = get_season_year(empty_val or '')
        assert result is None


# =============================================================================
# Date Arithmetic Tests
# =============================================================================

class TestDateArithmetic:
    """Test date arithmetic properties."""

    @given(nba_game_date(), st.integers(min_value=0, max_value=100))
    def test_add_days_preserves_format(self, dt, days):
        """Property: Adding days and reformatting preserves new date."""
        new_date = dt + timedelta(days=days)

        formatted = format_date_iso(new_date)
        parsed = parse_date_iso(formatted)

        assert parsed == new_date

    @given(nba_game_date(), st.integers(min_value=1, max_value=365))
    def test_date_difference_consistent(self, dt, days):
        """Property: Date difference is consistent."""
        future_date = dt + timedelta(days=days)

        diff = (future_date - dt).days

        assert diff == days


# =============================================================================
# Known Date Tests
# =============================================================================

class TestKnownDates:
    """Test specific known dates."""

    def test_christmas_games(self):
        """Test Christmas Day game dates."""
        christmas_2024 = date(2024, 12, 25)

        formatted = format_date_iso(christmas_2024)
        assert formatted == '2024-12-25'

        parsed = parse_date_iso(formatted)
        assert parsed == christmas_2024

        # Christmas is in 2024-25 season
        season = get_season_year(christmas_2024)
        assert season == 2024

    def test_season_opener(self):
        """Test typical season opener date."""
        opener_2024 = date(2024, 10, 22)

        formatted = format_date_iso(opener_2024)
        parsed = parse_date_iso(formatted)

        assert parsed == opener_2024

        season = get_season_year(opener_2024)
        assert season == 2024

    def test_playoffs_june(self):
        """Test playoffs date in June."""
        finals_2024 = date(2024, 6, 15)

        formatted = format_date_iso(finals_2024)
        parsed = parse_date_iso(formatted)

        assert parsed == finals_2024

        # June finals are part of 2023-24 season
        season = get_season_year(finals_2024)
        assert season == 2023


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
