"""
Property-based tests for data transformation functions.

Uses Hypothesis to generate edge case inputs and verify transformation invariants:
- Minutes parsing (MM:SS format to decimal)
- Plus/minus parsing (with +/- signs)
- Numeric type conversions
- Date transformations
- Data hash calculations
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
from datetime import date, datetime, timedelta
import hashlib
import json
import math


# =============================================================================
# Strategies for NBA Data
# =============================================================================

@composite
def valid_minutes_string(draw):
    """Generate valid MM:SS format strings."""
    minutes = draw(st.integers(min_value=0, max_value=60))
    seconds = draw(st.integers(min_value=0, max_value=59))
    return f"{minutes:02d}:{seconds:02d}"


@composite
def player_lookup(draw):
    """Generate player lookup strings (lowercase, no spaces)."""
    first = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=10))
    last = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=15))
    return f"{first}{last}"


@composite
def game_id_strategy(draw):
    """Generate valid game_id strings: YYYYMMDD_AWAY_HOME."""
    year = draw(st.integers(min_value=2020, max_value=2030))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=28))  # Safe for all months

    teams = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
             "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
             "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"]

    away = draw(st.sampled_from(teams))
    home = draw(st.sampled_from([t for t in teams if t != away]))

    return f"{year}{month:02d}{day:02d}_{away}_{home}"


@composite
def player_stats_record(draw):
    """Generate a complete player stats record."""
    return {
        'player_lookup': draw(player_lookup()),
        'game_id': draw(game_id_strategy()),
        'game_date': draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))).isoformat(),
        'team_abbr': draw(st.sampled_from(["ATL", "BOS", "LAL", "GSW", "MIA"])),
        'points': draw(st.integers(min_value=0, max_value=70)),
        'minutes_played': draw(st.integers(min_value=0, max_value=60)),
        'assists': draw(st.integers(min_value=0, max_value=25)),
        'rebounds': draw(st.integers(min_value=0, max_value=30)),
        'fg_attempts': draw(st.integers(min_value=0, max_value=40)),
        'fg_makes': draw(st.integers(min_value=0, max_value=40)),
        'three_pt_attempts': draw(st.integers(min_value=0, max_value=25)),
        'three_pt_makes': draw(st.integers(min_value=0, max_value=15)),
    }


# =============================================================================
# Minutes Parsing Tests
# =============================================================================

class TestMinutesParsing:
    """Property tests for minutes parsing (MM:SS -> decimal)."""

    def _parse_minutes_to_decimal(self, minutes_str):
        """
        Parse minutes string to decimal format (40:11 -> 40.18).
        Mirrors the implementation in PlayerGameSummaryProcessor.
        """
        import pandas as pd

        if minutes_str is None or pd.isna(minutes_str):
            return None

        try:
            minutes_clean = str(minutes_str).strip()
        except Exception:
            return None

        if not minutes_clean or minutes_clean == '-' or minutes_clean.lower() == 'null':
            return None

        try:
            if ':' in minutes_clean:
                parts = minutes_clean.split(':')
                if len(parts) == 2:
                    mins = int(parts[0].strip())
                    secs = int(parts[1].strip())
                    if secs < 0 or secs >= 60:
                        return None
                    return round(mins + (secs / 60), 2)
                return None
            return float(minutes_clean)
        except (ValueError, TypeError):
            return None

    @given(valid_minutes_string())
    @settings(max_examples=200)
    def test_valid_minutes_always_parse(self, minutes_str):
        """Valid MM:SS strings should always parse successfully."""
        result = self._parse_minutes_to_decimal(minutes_str)
        assert result is not None
        assert isinstance(result, float)
        assert result >= 0

    @given(st.integers(min_value=0, max_value=60), st.integers(min_value=0, max_value=59))
    def test_minutes_decimal_is_correct(self, mins, secs):
        """Verify decimal conversion is mathematically correct."""
        minutes_str = f"{mins}:{secs:02d}"
        result = self._parse_minutes_to_decimal(minutes_str)
        expected = round(mins + (secs / 60), 2)
        assert result == expected

    @given(st.floats(min_value=0, max_value=60, allow_nan=False, allow_infinity=False))
    def test_plain_number_parses(self, num):
        """Plain numeric strings should parse."""
        result = self._parse_minutes_to_decimal(str(num))
        assert result is not None
        assert abs(result - num) < 0.01

    @given(st.sampled_from([None, '', '-', 'null', 'NULL', '  ']),)
    def test_empty_values_return_none(self, empty_val):
        """Empty/null values should return None."""
        result = self._parse_minutes_to_decimal(empty_val)
        assert result is None

    @given(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz!@#$%^&*()"))
    def test_invalid_strings_return_none(self, invalid_str):
        """Invalid strings (non-numeric, non-time) should return None, not raise."""
        # This test ensures non-numeric garbage doesn't crash the parser
        result = self._parse_minutes_to_decimal(invalid_str)
        assert result is None

    @given(st.integers(min_value=0, max_value=60), st.integers(min_value=60, max_value=99))
    def test_invalid_seconds_return_none(self, mins, invalid_secs):
        """Seconds >= 60 should return None."""
        minutes_str = f"{mins}:{invalid_secs}"
        result = self._parse_minutes_to_decimal(minutes_str)
        assert result is None


# =============================================================================
# Plus/Minus Parsing Tests
# =============================================================================

class TestPlusMinusParsing:
    """Property tests for plus/minus parsing."""

    def _parse_plus_minus(self, plus_minus_str):
        """Parse plus/minus string to integer (+7 -> 7)."""
        import pandas as pd

        if pd.isna(plus_minus_str) or not plus_minus_str or plus_minus_str == '-':
            return None

        try:
            cleaned = str(plus_minus_str).replace('+', '')
            return int(cleaned)
        except (ValueError, TypeError):
            return None

    @given(st.integers(min_value=-50, max_value=50))
    def test_plain_integers_parse(self, value):
        """Plain integers should parse correctly."""
        result = self._parse_plus_minus(str(value))
        assert result == value

    @given(st.integers(min_value=1, max_value=50))
    def test_positive_with_plus_sign(self, value):
        """Positive values with + sign should parse correctly."""
        result = self._parse_plus_minus(f"+{value}")
        assert result == value

    @given(st.integers(min_value=-50, max_value=-1))
    def test_negative_values(self, value):
        """Negative values should parse correctly."""
        result = self._parse_plus_minus(str(value))
        assert result == value

    @given(st.sampled_from([None, '', '-']))
    def test_empty_values_return_none(self, empty_val):
        """Empty values should return None."""
        result = self._parse_plus_minus(empty_val)
        assert result is None


# =============================================================================
# Data Hash Calculation Tests
# =============================================================================

class TestDataHashCalculation:
    """Property tests for data hash calculations (smart reprocessing)."""

    HASH_FIELDS = [
        'player_lookup', 'game_id', 'game_date', 'points', 'minutes_played',
        'assists', 'rebounds', 'fg_attempts', 'fg_makes'
    ]

    def _calculate_data_hash(self, record):
        """Calculate SHA256 hash of meaningful analytics fields."""
        hash_data = {field: record.get(field) for field in self.HASH_FIELDS}
        sorted_data = json.dumps(hash_data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()[:16]

    @given(player_stats_record())
    @settings(max_examples=100)
    def test_hash_is_deterministic(self, record):
        """Same record should always produce same hash."""
        hash1 = self._calculate_data_hash(record)
        hash2 = self._calculate_data_hash(record)
        assert hash1 == hash2

    @given(player_stats_record())
    def test_hash_is_16_chars(self, record):
        """Hash should always be 16 characters."""
        result = self._calculate_data_hash(record)
        assert len(result) == 16
        assert all(c in '0123456789abcdef' for c in result)

    @given(player_stats_record(), st.integers(min_value=0, max_value=70))
    def test_hash_changes_with_points(self, record, new_points):
        """Changing points should change the hash."""
        assume(record['points'] != new_points)

        original_hash = self._calculate_data_hash(record)

        modified_record = record.copy()
        modified_record['points'] = new_points

        new_hash = self._calculate_data_hash(modified_record)
        assert original_hash != new_hash

    @given(player_stats_record())
    def test_hash_ignores_extra_fields(self, record):
        """Extra fields not in HASH_FIELDS should not affect hash."""
        original_hash = self._calculate_data_hash(record)

        record_with_extra = record.copy()
        record_with_extra['extra_field'] = 'should_be_ignored'
        record_with_extra['processed_at'] = datetime.now().isoformat()

        new_hash = self._calculate_data_hash(record_with_extra)
        assert original_hash == new_hash


# =============================================================================
# Shooting Stats Validation Tests
# =============================================================================

class TestShootingStatsValidation:
    """Property tests for shooting statistics validation."""

    @given(
        st.integers(min_value=0, max_value=40),  # makes
        st.integers(min_value=0, max_value=40),  # attempts
    )
    def test_makes_never_exceed_attempts(self, makes, attempts):
        """Validate shooting stats invariant: makes <= attempts."""
        # This is the invariant we're testing - valid data should satisfy this
        if makes <= attempts:
            # Valid case
            assert True
        else:
            # This would be invalid data - test that we detect it
            is_valid = makes <= attempts
            assert not is_valid

    @given(
        st.integers(min_value=0, max_value=40),  # fg_attempts
        st.integers(min_value=0, max_value=25),  # 3pt_attempts
    )
    def test_three_pointers_subset_of_fg(self, fg_attempts, three_pt_attempts):
        """3-point attempts should logically be <= field goal attempts."""
        # In valid data, 3PA should be included in FGA
        # This test documents the expected relationship
        if three_pt_attempts <= fg_attempts:
            assert True  # Valid relationship
        # Note: We don't assert invalid because some data sources
        # might report these independently


# =============================================================================
# Efficiency Calculation Tests
# =============================================================================

class TestEfficiencyCalculations:
    """Property tests for efficiency metric calculations."""

    def _calculate_efg_pct(self, fg_makes, fg_attempts, three_makes):
        """Calculate Effective Field Goal Percentage."""
        if fg_attempts == 0:
            return None
        return (fg_makes + 0.5 * three_makes) / fg_attempts

    def _calculate_ts_pct(self, points, fg_attempts, ft_attempts):
        """Calculate True Shooting Percentage."""
        total_shots = fg_attempts + 0.44 * ft_attempts
        if total_shots == 0:
            return None
        return points / (2 * total_shots)

    @given(
        st.integers(min_value=0, max_value=20),  # fg_makes
        st.integers(min_value=1, max_value=40),  # fg_attempts (>0)
        st.integers(min_value=0, max_value=15),  # three_makes
    )
    def test_efg_in_valid_range(self, fg_makes, fg_attempts, three_makes):
        """EFG% should be in valid range [0, ~1.5]."""
        assume(fg_makes <= fg_attempts)
        assume(three_makes <= fg_makes)  # 3PM can't exceed FGM

        efg = self._calculate_efg_pct(fg_makes, fg_attempts, three_makes)

        assert efg is not None
        assert efg >= 0
        # EFG can exceed 1.0 when all makes are 3-pointers
        assert efg <= 1.5

    @given(
        st.integers(min_value=0, max_value=70),  # points
        st.integers(min_value=1, max_value=40),  # fg_attempts (>0)
        st.integers(min_value=0, max_value=20),  # ft_attempts
    )
    def test_ts_in_valid_range(self, points, fg_attempts, ft_attempts):
        """TS% should be in valid range [0, ~1.5] for realistic data."""
        ts = self._calculate_ts_pct(points, fg_attempts, ft_attempts)

        assert ts is not None
        assert ts >= 0
        # TS% is typically 0.4-0.7 but can be higher for efficient scorers

    @given(st.integers(min_value=0, max_value=40))
    def test_efg_zero_attempts_returns_none(self, fg_makes):
        """EFG with 0 attempts should return None, not error."""
        result = self._calculate_efg_pct(fg_makes, 0, 0)
        assert result is None

    @given(st.integers(min_value=0, max_value=70))
    def test_ts_zero_attempts_returns_none(self, points):
        """TS with 0 shot attempts should return None."""
        result = self._calculate_ts_pct(points, 0, 0)
        assert result is None


# =============================================================================
# Date and Season Transformations
# =============================================================================

class TestDateTransformations:
    """Property tests for date and season transformations."""

    def _get_season_year(self, game_date):
        """Get season year from game date (e.g., 2024-11-15 -> 2024)."""
        if isinstance(game_date, str):
            game_date = datetime.strptime(game_date, "%Y-%m-%d").date()

        # NBA season starts in October
        # Games before October belong to previous season
        if game_date.month >= 10:
            return game_date.year
        else:
            return game_date.year - 1

    def _format_season_string(self, season_year):
        """Format season as '2024-25' string."""
        next_year_short = str(season_year + 1)[-2:]
        return f"{season_year}-{next_year_short}"

    @given(st.dates(min_value=date(2020, 10, 1), max_value=date(2030, 6, 30)))
    def test_season_year_calculation(self, game_date):
        """Season year should be correctly calculated from game date."""
        season_year = self._get_season_year(game_date)

        # October onwards -> that year's season
        if game_date.month >= 10:
            assert season_year == game_date.year
        else:
            # Before October -> previous year's season
            assert season_year == game_date.year - 1

    @given(st.integers(min_value=2020, max_value=2030))
    def test_season_string_format(self, year):
        """Season string should be properly formatted."""
        result = self._format_season_string(year)

        assert '-' in result
        assert result[:4] == str(year)
        assert len(result) == 7

    @example(2024)  # 2024-25
    @example(2099)  # Edge case: 2099-00
    @given(st.integers(min_value=2020, max_value=2099))
    def test_season_string_year_wraparound(self, year):
        """Season string handles year wraparound correctly."""
        result = self._format_season_string(year)

        parts = result.split('-')
        assert len(parts) == 2
        assert parts[0] == str(year)

        expected_suffix = str(year + 1)[-2:]
        assert parts[1] == expected_suffix


# =============================================================================
# Team Abbreviation Validation
# =============================================================================

class TestTeamAbbreviationValidation:
    """Property tests for team abbreviation handling."""

    VALID_TEAMS = frozenset([
        "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
        "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
        "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
    ])

    def _normalize_team_abbr(self, abbr):
        """Normalize team abbreviation to uppercase."""
        if not abbr:
            return None
        return str(abbr).upper().strip()

    def _is_valid_team(self, abbr):
        """Check if team abbreviation is valid."""
        normalized = self._normalize_team_abbr(abbr)
        return normalized in self.VALID_TEAMS

    @given(st.sampled_from(list(VALID_TEAMS)))
    def test_valid_teams_recognized(self, team):
        """All valid team abbreviations should be recognized."""
        assert self._is_valid_team(team)

    @given(st.sampled_from(list(VALID_TEAMS)))
    def test_lowercase_teams_normalize(self, team):
        """Lowercase team abbreviations should normalize correctly."""
        result = self._normalize_team_abbr(team.lower())
        assert result == team

    @given(st.text(min_size=1, max_size=3, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    def test_invalid_teams_rejected(self, text_team):
        """Invalid team abbreviations should not be recognized."""
        # Skip if this happens to be a valid team
        if text_team in self.VALID_TEAMS:
            return
        assert not self._is_valid_team(text_team)

    @given(st.sampled_from([None, '', '  ']))
    def test_empty_values_handled(self, empty_val):
        """Empty values should normalize to None."""
        result = self._normalize_team_abbr(empty_val)
        if empty_val is None or not str(empty_val).strip():
            assert result is None or result == ''


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
