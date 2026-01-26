"""
Property-based tests for game ID conversion and validation.

Uses Hypothesis to verify:
- convert_back(convert_forward(id)) == id (bijection)
- Different inputs produce different outputs (no collisions)
- Format validation consistency
- Game ID component extraction
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
from datetime import date, datetime
import re


# =============================================================================
# Game ID Converter Implementation (mirrors orchestration/shared/utils/game_id_converter.py)
# =============================================================================

VALID_TEAMS = frozenset([
    'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
    'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
    'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
])

STANDARD_PATTERN = re.compile(r'^(\d{8})_([A-Z]{3})_([A-Z]{3})$')


def to_standard_game_id(game_date, away_team, home_team):
    """Convert components to standard game ID: YYYYMMDD_AWAY_HOME."""
    if isinstance(game_date, date):
        date_str = game_date.strftime('%Y%m%d')
    elif isinstance(game_date, str):
        date_str = game_date.replace('-', '')
        if len(date_str) != 8 or not date_str.isdigit():
            raise ValueError(f"Invalid date format: {game_date}")
        # Validate it's a real date
        datetime.strptime(date_str, '%Y%m%d')
    else:
        raise ValueError(f"Invalid date type: {type(game_date)}")

    away_team = away_team.upper().strip()
    home_team = home_team.upper().strip()

    if away_team not in VALID_TEAMS:
        raise ValueError(f"Invalid away team: {away_team}")
    if home_team not in VALID_TEAMS:
        raise ValueError(f"Invalid home team: {home_team}")
    if away_team == home_team:
        raise ValueError(f"Teams cannot be the same: {away_team}")

    return f"{date_str}_{away_team}_{home_team}"


def parse_game_id(game_id):
    """Parse standard game ID into components."""
    match = STANDARD_PATTERN.match(game_id)
    if not match:
        raise ValueError(f"Invalid game ID format: {game_id}")

    date_str, away, home = match.groups()

    # Validate date
    datetime.strptime(date_str, '%Y%m%d')

    # Validate teams
    if away not in VALID_TEAMS or home not in VALID_TEAMS:
        raise ValueError(f"Invalid teams in game ID: {game_id}")

    if away == home:
        raise ValueError(f"Teams cannot be the same: {game_id}")

    return date_str, away, home


def is_valid_game_id(game_id):
    """Check if game ID is valid."""
    try:
        parse_game_id(game_id)
        return True
    except (ValueError, AttributeError):
        return False


# =============================================================================
# Strategies for Game ID Testing
# =============================================================================

@composite
def valid_nba_team(draw):
    """Generate a valid NBA team code."""
    return draw(st.sampled_from(sorted(VALID_TEAMS)))


@composite
def valid_game_date(draw):
    """Generate a valid game date."""
    return draw(st.dates(min_value=date(2015, 10, 1), max_value=date(2030, 6, 30)))


@composite
def valid_game_id_components(draw):
    """Generate valid game ID components."""
    game_date = draw(valid_game_date())
    away = draw(valid_nba_team())
    home = draw(valid_nba_team())
    assume(away != home)  # Different teams

    return game_date, away, home


@composite
def valid_game_id(draw):
    """Generate a valid standard format game ID."""
    game_date, away, home = draw(valid_game_id_components())
    return to_standard_game_id(game_date, away, home)


# =============================================================================
# Bijection Tests (Round-Trip)
# =============================================================================

class TestGameIdBijection:
    """Test that game ID conversion is a bijection (reversible)."""

    @given(valid_game_id_components())
    @settings(max_examples=500)
    def test_round_trip_conversion(self, components):
        """Property: parse(to_standard(components)) == components."""
        game_date, away, home = components

        # Convert to game ID
        game_id = to_standard_game_id(game_date, away, home)

        # Parse back
        parsed_date, parsed_away, parsed_home = parse_game_id(game_id)

        # Should match original
        assert parsed_date == game_date.strftime('%Y%m%d')
        assert parsed_away == away
        assert parsed_home == home

    @given(valid_game_id())
    def test_round_trip_from_game_id(self, game_id):
        """Property: to_standard(parse(game_id)) == game_id."""
        # Parse
        date_str, away, home = parse_game_id(game_id)

        # Convert back
        reconstructed = to_standard_game_id(date_str, away, home)

        assert reconstructed == game_id

    @given(valid_game_id_components())
    def test_multiple_round_trips(self, components):
        """Property: Multiple round trips preserve value."""
        game_date, away, home = components

        # First round trip
        game_id1 = to_standard_game_id(game_date, away, home)
        parsed1 = parse_game_id(game_id1)
        game_id2 = to_standard_game_id(parsed1[0], parsed1[1], parsed1[2])

        # Second round trip
        parsed2 = parse_game_id(game_id2)
        game_id3 = to_standard_game_id(parsed2[0], parsed2[1], parsed2[2])

        # All should be identical
        assert game_id1 == game_id2 == game_id3


# =============================================================================
# Collision Tests (No Duplicates)
# =============================================================================

class TestNoCollisions:
    """Test that different inputs produce different game IDs."""

    @given(valid_game_id_components(), valid_game_id_components())
    def test_different_dates_different_ids(self, comp1, comp2):
        """Property: Different dates produce different game IDs."""
        date1, away1, home1 = comp1
        date2, away2, home2 = comp2

        # Same teams, different dates
        assume(date1 != date2)
        assume(away1 == away2 and home1 == home2)

        game_id1 = to_standard_game_id(date1, away1, home1)
        game_id2 = to_standard_game_id(date2, away2, home2)

        assert game_id1 != game_id2

    @given(valid_game_date(), valid_nba_team(), valid_nba_team(), valid_nba_team())
    def test_different_teams_different_ids(self, game_date, away1, away2, home):
        """Property: Different away teams produce different game IDs."""
        assume(away1 != away2)
        assume(away1 != home and away2 != home)

        game_id1 = to_standard_game_id(game_date, away1, home)
        game_id2 = to_standard_game_id(game_date, away2, home)

        assert game_id1 != game_id2

    @given(valid_game_id_components())
    def test_swapped_teams_different_ids(self, components):
        """Property: Swapping home/away produces different ID."""
        game_date, away, home = components

        game_id_normal = to_standard_game_id(game_date, away, home)
        game_id_swapped = to_standard_game_id(game_date, home, away)

        assert game_id_normal != game_id_swapped


# =============================================================================
# Format Validation Tests
# =============================================================================

class TestFormatValidation:
    """Test game ID format validation."""

    @given(valid_game_id())
    def test_valid_game_id_passes_validation(self, game_id):
        """Property: Valid game IDs pass validation."""
        assert is_valid_game_id(game_id)

    @given(valid_game_id())
    def test_valid_format_matches_pattern(self, game_id):
        """Property: Valid game IDs match the standard pattern."""
        assert STANDARD_PATTERN.match(game_id) is not None

    @given(st.text(min_size=1, max_size=50))
    def test_random_strings_mostly_invalid(self, random_str):
        """Property: Random strings are mostly invalid (unless they happen to be valid)."""
        # This just ensures validation doesn't crash
        try:
            result = is_valid_game_id(random_str)
            assert isinstance(result, bool)
        except Exception:
            # Should not raise, should return False
            assert False, f"Validation should not raise for: {random_str}"

    @given(st.sampled_from([
        "20240101_LAL",  # Missing home team
        "20240101_LAL_",  # Empty home team
        "2024-01-01_LAL_GSW",  # Hyphens in date
        "20241301_LAL_GSW",  # Invalid month
        "20240132_LAL_GSW",  # Invalid day
        "20240101_XXX_GSW",  # Invalid away team
        "20240101_LAL_XXX",  # Invalid home team
        "20240101_LAL_LAL",  # Same teams
        "",  # Empty
    ]))
    def test_known_invalid_formats(self, invalid_id):
        """Property: Known invalid formats are rejected."""
        assert not is_valid_game_id(invalid_id)


# =============================================================================
# Component Extraction Tests
# =============================================================================

class TestComponentExtraction:
    """Test game ID component extraction."""

    @given(valid_game_id())
    def test_extract_date_component(self, game_id):
        """Property: Date component extraction is valid."""
        date_str, _, _ = parse_game_id(game_id)

        # Should be 8 digits
        assert len(date_str) == 8
        assert date_str.isdigit()

        # Should be a valid date
        parsed_date = datetime.strptime(date_str, '%Y%m%d').date()
        assert parsed_date.year >= 2015
        assert parsed_date.year <= 2030

    @given(valid_game_id())
    def test_extract_team_components(self, game_id):
        """Property: Team components are valid NBA teams."""
        _, away, home = parse_game_id(game_id)

        assert away in VALID_TEAMS
        assert home in VALID_TEAMS
        assert away != home

    @given(valid_game_id())
    def test_components_have_correct_format(self, game_id):
        """Property: Extracted components have correct format."""
        date_str, away, home = parse_game_id(game_id)

        # Date is 8 digits
        assert len(date_str) == 8
        assert date_str.isdigit()

        # Teams are 3 uppercase letters
        assert len(away) == 3
        assert away.isupper()
        assert away.isalpha()

        assert len(home) == 3
        assert home.isupper()
        assert home.isalpha()


# =============================================================================
# Date Handling Tests
# =============================================================================

class TestDateHandling:
    """Test date handling in game IDs."""

    @given(valid_game_date(), valid_nba_team(), valid_nba_team())
    def test_date_object_accepted(self, game_date, away, home):
        """Property: date objects are accepted."""
        assume(away != home)

        game_id = to_standard_game_id(game_date, away, home)

        assert is_valid_game_id(game_id)

    @given(valid_game_date(), valid_nba_team(), valid_nba_team())
    def test_date_string_accepted(self, game_date, away, home):
        """Property: date strings (YYYYMMDD) are accepted."""
        assume(away != home)

        date_str = game_date.strftime('%Y%m%d')
        game_id = to_standard_game_id(date_str, away, home)

        assert is_valid_game_id(game_id)

    @given(valid_game_date(), valid_nba_team(), valid_nba_team())
    def test_iso_date_string_accepted(self, game_date, away, home):
        """Property: ISO date strings (YYYY-MM-DD) are accepted."""
        assume(away != home)

        iso_str = game_date.isoformat()  # YYYY-MM-DD
        game_id = to_standard_game_id(iso_str, away, home)

        assert is_valid_game_id(game_id)

    @given(valid_game_id_components())
    def test_date_formats_produce_same_id(self, components):
        """Property: Different date formats produce same game ID."""
        game_date, away, home = components

        # Different date formats
        game_id1 = to_standard_game_id(game_date, away, home)  # date object
        game_id2 = to_standard_game_id(game_date.strftime('%Y%m%d'), away, home)  # YYYYMMDD
        game_id3 = to_standard_game_id(game_date.isoformat(), away, home)  # YYYY-MM-DD

        assert game_id1 == game_id2 == game_id3


# =============================================================================
# Team Code Handling Tests
# =============================================================================

class TestTeamCodeHandling:
    """Test team code handling in game IDs."""

    @given(valid_game_date(), valid_nba_team(), valid_nba_team())
    def test_lowercase_teams_normalized(self, game_date, away, home):
        """Property: Lowercase team codes are normalized to uppercase."""
        assume(away != home)

        game_id = to_standard_game_id(game_date, away.lower(), home.lower())

        _, parsed_away, parsed_home = parse_game_id(game_id)

        assert parsed_away == away
        assert parsed_home == home

    @given(valid_game_date(), valid_nba_team(), valid_nba_team())
    def test_whitespace_trimmed(self, game_date, away, home):
        """Property: Whitespace in team codes is trimmed."""
        assume(away != home)

        game_id = to_standard_game_id(game_date, f"  {away}  ", f"  {home}  ")

        _, parsed_away, parsed_home = parse_game_id(game_id)

        assert parsed_away == away
        assert parsed_home == home


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling for invalid inputs."""

    @given(valid_game_date(), valid_nba_team())
    def test_same_teams_raises_error(self, game_date, team):
        """Property: Same home/away teams raises error."""
        with pytest.raises(ValueError):
            to_standard_game_id(game_date, team, team)

    @given(valid_game_date(), valid_nba_team(), st.text(min_size=3, max_size=3).filter(lambda t: t.upper() not in VALID_TEAMS))
    def test_invalid_team_raises_error(self, game_date, valid_team, invalid_team):
        """Property: Invalid team code raises error."""
        with pytest.raises(ValueError):
            to_standard_game_id(game_date, valid_team, invalid_team)

    @given(st.text(min_size=1, max_size=20))
    def test_invalid_game_id_raises_error(self, invalid_id):
        """Property: Invalid game ID raises error on parse."""
        assume(not is_valid_game_id(invalid_id))

        with pytest.raises(ValueError):
            parse_game_id(invalid_id)


# =============================================================================
# Consistency Tests
# =============================================================================

class TestConsistency:
    """Test that game ID operations are consistent."""

    @given(valid_game_id_components())
    def test_deterministic_conversion(self, components):
        """Property: Same input produces same game ID."""
        game_date, away, home = components

        game_id1 = to_standard_game_id(game_date, away, home)
        game_id2 = to_standard_game_id(game_date, away, home)
        game_id3 = to_standard_game_id(game_date, away, home)

        assert game_id1 == game_id2 == game_id3

    @given(valid_game_id())
    def test_validation_consistent(self, game_id):
        """Property: Validation is consistent."""
        result1 = is_valid_game_id(game_id)
        result2 = is_valid_game_id(game_id)
        result3 = is_valid_game_id(game_id)

        assert result1 == result2 == result3
        assert result1 is True  # Should always be valid


# =============================================================================
# Real-World Examples Tests
# =============================================================================

class TestRealWorldExamples:
    """Test with real NBA game IDs."""

    def test_known_valid_game_ids(self):
        """Test known valid game IDs."""
        valid_ids = [
            "20240101_LAL_GSW",
            "20231225_BOS_LAL",
            "20240315_MIA_NYK",
            "20230410_CHI_PHI",
        ]

        for game_id in valid_ids:
            assert is_valid_game_id(game_id)
            # Should be parseable
            date_str, away, home = parse_game_id(game_id)
            assert len(date_str) == 8
            assert away in VALID_TEAMS
            assert home in VALID_TEAMS

    def test_known_invalid_game_ids(self):
        """Test known invalid game IDs."""
        invalid_ids = [
            "20240101_LAL",  # Missing team
            "2024-01-01_LAL_GSW",  # Wrong date format
            "20240101_LAL_LAL",  # Same teams
            "20241301_LAL_GSW",  # Invalid month
            "",
            "invalid",
        ]

        for game_id in invalid_ids:
            assert not is_valid_game_id(game_id)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
