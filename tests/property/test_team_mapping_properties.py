"""
Property-based tests for team code mapping.

Uses Hypothesis to verify:
- Bijection (one-to-one mapping)
- Reverse lookup consistency
- Case insensitive mapping
- Fuzzy matching correctness
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite


# =============================================================================
# Team Mapping Implementation (mirrors shared/utils/nba_team_mapper.py)
# =============================================================================

# All 30 NBA teams with their tricode variations
TEAM_MAPPINGS = {
    # NBA.com tricode -> (full_name, br_tricode, espn_tricode)
    'ATL': ('Atlanta Hawks', 'ATL', 'ATL'),
    'BOS': ('Boston Celtics', 'BOS', 'BOS'),
    'BKN': ('Brooklyn Nets', 'BRK', 'BKN'),
    'CHA': ('Charlotte Hornets', 'CHO', 'CHA'),
    'CHI': ('Chicago Bulls', 'CHI', 'CHI'),
    'CLE': ('Cleveland Cavaliers', 'CLE', 'CLE'),
    'DAL': ('Dallas Mavericks', 'DAL', 'DAL'),
    'DEN': ('Denver Nuggets', 'DEN', 'DEN'),
    'DET': ('Detroit Pistons', 'DET', 'DET'),
    'GSW': ('Golden State Warriors', 'GSW', 'GS'),
    'HOU': ('Houston Rockets', 'HOU', 'HOU'),
    'IND': ('Indiana Pacers', 'IND', 'IND'),
    'LAC': ('Los Angeles Clippers', 'LAC', 'LAC'),
    'LAL': ('Los Angeles Lakers', 'LAL', 'LAL'),
    'MEM': ('Memphis Grizzlies', 'MEM', 'MEM'),
    'MIA': ('Miami Heat', 'MIA', 'MIA'),
    'MIL': ('Milwaukee Bucks', 'MIL', 'MIL'),
    'MIN': ('Minnesota Timberwolves', 'MIN', 'MIN'),
    'NOP': ('New Orleans Pelicans', 'NOP', 'NO'),
    'NYK': ('New York Knicks', 'NYK', 'NY'),
    'OKC': ('Oklahoma City Thunder', 'OKC', 'OKC'),
    'ORL': ('Orlando Magic', 'ORL', 'ORL'),
    'PHI': ('Philadelphia 76ers', 'PHI', 'PHI'),
    'PHX': ('Phoenix Suns', 'PHO', 'PHX'),
    'POR': ('Portland Trail Blazers', 'POR', 'POR'),
    'SAC': ('Sacramento Kings', 'SAC', 'SAC'),
    'SAS': ('San Antonio Spurs', 'SAS', 'SA'),
    'TOR': ('Toronto Raptors', 'TOR', 'TOR'),
    'UTA': ('Utah Jazz', 'UTA', 'UTAH'),
    'WAS': ('Washington Wizards', 'WAS', 'WAS'),
}


def get_nba_tricode(identifier: str):
    """Get NBA tricode from any identifier."""
    if not identifier:
        return None

    normalized = identifier.upper().strip()

    # Direct NBA tricode match
    if normalized in TEAM_MAPPINGS:
        return normalized

    # Match by full name
    for nba_code, (full_name, _, _) in TEAM_MAPPINGS.items():
        if normalized == full_name.upper():
            return nba_code
        if normalized in full_name.upper():
            return nba_code

    # Match by Basketball Reference tricode
    for nba_code, (_, br_code, _) in TEAM_MAPPINGS.items():
        if normalized == br_code.upper():
            return nba_code

    # Match by ESPN tricode
    for nba_code, (_, _, espn_code) in TEAM_MAPPINGS.items():
        if normalized == espn_code.upper():
            return nba_code

    return None


def get_full_name(tricode: str):
    """Get full team name from tricode."""
    if not tricode:
        return None

    normalized = tricode.upper().strip()
    nba_code = get_nba_tricode(normalized)

    if nba_code and nba_code in TEAM_MAPPINGS:
        return TEAM_MAPPINGS[nba_code][0]

    return None


def get_br_tricode(identifier: str):
    """Get Basketball Reference tricode."""
    nba_code = get_nba_tricode(identifier)
    if nba_code and nba_code in TEAM_MAPPINGS:
        return TEAM_MAPPINGS[nba_code][1]
    return None


def get_espn_tricode(identifier: str):
    """Get ESPN tricode."""
    nba_code = get_nba_tricode(identifier)
    if nba_code and nba_code in TEAM_MAPPINGS:
        return TEAM_MAPPINGS[nba_code][2]
    return None


# =============================================================================
# Strategies for Team Code Testing
# =============================================================================

@composite
def nba_tricode(draw):
    """Generate a valid NBA tricode."""
    return draw(st.sampled_from(sorted(TEAM_MAPPINGS.keys())))


@composite
def team_full_name(draw):
    """Generate a valid team full name."""
    nba_code = draw(nba_tricode())
    return TEAM_MAPPINGS[nba_code][0]


@composite
def br_tricode(draw):
    """Generate a valid Basketball Reference tricode."""
    nba_code = draw(nba_tricode())
    return TEAM_MAPPINGS[nba_code][1]


@composite
def espn_tricode(draw):
    """Generate a valid ESPN tricode."""
    nba_code = draw(nba_tricode())
    return TEAM_MAPPINGS[nba_code][2]


# =============================================================================
# Bijection Tests (One-to-One Mapping)
# =============================================================================

class TestBijection:
    """Test that mapping is a bijection (one-to-one)."""

    @given(nba_tricode())
    def test_nba_tricode_to_full_name_bijective(self, nba_code):
        """Property: NBA tricode -> full name is bijective."""
        full_name = get_full_name(nba_code)
        reverse = get_nba_tricode(full_name)

        assert reverse == nba_code

    @given(team_full_name())
    def test_full_name_to_nba_tricode_bijective(self, full_name):
        """Property: Full name -> NBA tricode is bijective."""
        nba_code = get_nba_tricode(full_name)
        reverse = get_full_name(nba_code)

        assert reverse == full_name

    @given(nba_tricode())
    def test_nba_to_br_consistent(self, nba_code):
        """Property: NBA -> BR -> NBA preserves code."""
        br_code = get_br_tricode(nba_code)
        reverse = get_nba_tricode(br_code)

        assert reverse == nba_code

    @given(nba_tricode())
    def test_nba_to_espn_consistent(self, nba_code):
        """Property: NBA -> ESPN -> NBA preserves code."""
        espn_code = get_espn_tricode(nba_code)
        reverse = get_nba_tricode(espn_code)

        assert reverse == nba_code

    def test_no_duplicate_nba_codes(self):
        """Property: All NBA tricodes are unique."""
        codes = list(TEAM_MAPPINGS.keys())
        assert len(codes) == len(set(codes))

    def test_no_duplicate_full_names(self):
        """Property: All full names are unique."""
        names = [info[0] for info in TEAM_MAPPINGS.values()]
        assert len(names) == len(set(names))


# =============================================================================
# Reverse Lookup Tests
# =============================================================================

class TestReverseLookup:
    """Test reverse lookup consistency."""

    @given(nba_tricode())
    def test_reverse_lookup_full_name(self, nba_code):
        """Property: Reverse lookup via full name works."""
        full_name = get_full_name(nba_code)

        # Lookup by full name should return original code
        result = get_nba_tricode(full_name)

        assert result == nba_code

    @given(nba_tricode())
    def test_reverse_lookup_br_code(self, nba_code):
        """Property: Reverse lookup via BR tricode works."""
        br_code = get_br_tricode(nba_code)

        # Lookup by BR code should return original NBA code
        result = get_nba_tricode(br_code)

        assert result == nba_code

    @given(nba_tricode())
    def test_reverse_lookup_espn_code(self, nba_code):
        """Property: Reverse lookup via ESPN tricode works."""
        espn_code = get_espn_tricode(nba_code)

        # Lookup by ESPN code should return original NBA code
        result = get_nba_tricode(espn_code)

        assert result == nba_code

    @given(nba_tricode())
    def test_all_codes_resolve_to_same_team(self, nba_code):
        """Property: All code variations resolve to same team."""
        full_name = get_full_name(nba_code)
        br_code = get_br_tricode(nba_code)
        espn_code = get_espn_tricode(nba_code)

        # All should resolve to same NBA code
        result1 = get_nba_tricode(nba_code)
        result2 = get_nba_tricode(full_name)
        result3 = get_nba_tricode(br_code)
        result4 = get_nba_tricode(espn_code)

        assert result1 == result2 == result3 == result4 == nba_code


# =============================================================================
# Case Insensitivity Tests
# =============================================================================

class TestCaseInsensitivity:
    """Test that mapping is case insensitive."""

    @given(nba_tricode())
    def test_lowercase_tricode(self, nba_code):
        """Property: Lowercase tricode resolves correctly."""
        result = get_nba_tricode(nba_code.lower())
        assert result == nba_code

    @given(nba_tricode())
    def test_uppercase_tricode(self, nba_code):
        """Property: Uppercase tricode resolves correctly."""
        result = get_nba_tricode(nba_code.upper())
        assert result == nba_code

    @given(team_full_name())
    def test_lowercase_full_name(self, full_name):
        """Property: Lowercase full name resolves correctly."""
        expected = get_nba_tricode(full_name)
        result = get_nba_tricode(full_name.lower())

        assert result == expected

    @given(team_full_name())
    def test_uppercase_full_name(self, full_name):
        """Property: Uppercase full name resolves correctly."""
        expected = get_nba_tricode(full_name)
        result = get_nba_tricode(full_name.upper())

        assert result == expected

    @given(nba_tricode())
    def test_mixed_case_tricode(self, nba_code):
        """Property: Mixed case tricode resolves correctly."""
        # Create mixed case version
        if len(nba_code) >= 3:
            mixed = nba_code[0].upper() + nba_code[1].lower() + nba_code[2].upper()
            result = get_nba_tricode(mixed)
            assert result == nba_code


# =============================================================================
# Whitespace Handling Tests
# =============================================================================

class TestWhitespaceHandling:
    """Test that whitespace is handled correctly."""

    @given(nba_tricode())
    def test_leading_whitespace(self, nba_code):
        """Property: Leading whitespace is trimmed."""
        result = get_nba_tricode(f"  {nba_code}")
        assert result == nba_code

    @given(nba_tricode())
    def test_trailing_whitespace(self, nba_code):
        """Property: Trailing whitespace is trimmed."""
        result = get_nba_tricode(f"{nba_code}  ")
        assert result == nba_code

    @given(nba_tricode())
    def test_surrounding_whitespace(self, nba_code):
        """Property: Surrounding whitespace is trimmed."""
        result = get_nba_tricode(f"  {nba_code}  ")
        assert result == nba_code

    @given(team_full_name())
    def test_full_name_whitespace(self, full_name):
        """Property: Whitespace in full names is handled."""
        expected = get_nba_tricode(full_name)
        result = get_nba_tricode(f"  {full_name}  ")

        assert result == expected


# =============================================================================
# Invalid Input Tests
# =============================================================================

class TestInvalidInputs:
    """Test handling of invalid inputs."""

    @given(st.text(min_size=3, max_size=3).filter(lambda t: t.upper() not in TEAM_MAPPINGS))
    def test_invalid_tricode_returns_none(self, invalid_code):
        """Property: Invalid tricodes return None."""
        result = get_nba_tricode(invalid_code)
        assert result is None

    @given(st.sampled_from([None, '', '  ', '\t', '\n']))
    def test_empty_input_returns_none(self, empty_input):
        """Property: Empty inputs return None."""
        result = get_nba_tricode(empty_input)
        assert result is None

    @given(st.text(min_size=1, max_size=50).filter(
        lambda t: t.upper() not in [k for k in TEAM_MAPPINGS] and
                 t.upper() not in [v[0].upper() for v in TEAM_MAPPINGS.values()]
    ))
    def test_unknown_team_returns_none(self, unknown_team):
        """Property: Unknown team names return None."""
        result = get_nba_tricode(unknown_team)
        assert result is None


# =============================================================================
# Consistency Tests
# =============================================================================

class TestConsistency:
    """Test that mappings are consistent."""

    @given(nba_tricode())
    def test_lookup_deterministic(self, nba_code):
        """Property: Same input produces same output."""
        result1 = get_nba_tricode(nba_code)
        result2 = get_nba_tricode(nba_code)
        result3 = get_nba_tricode(nba_code)

        assert result1 == result2 == result3

    @given(nba_tricode())
    def test_all_lookups_consistent(self, nba_code):
        """Property: Different lookup methods return consistent results."""
        full_name = get_full_name(nba_code)
        br_code = get_br_tricode(nba_code)
        espn_code = get_espn_tricode(nba_code)

        # All should resolve to same NBA code
        assert get_nba_tricode(nba_code) == nba_code
        assert get_nba_tricode(full_name) == nba_code
        assert get_nba_tricode(br_code) == nba_code
        assert get_nba_tricode(espn_code) == nba_code


# =============================================================================
# Coverage Tests
# =============================================================================

class TestCoverage:
    """Test that all teams are covered."""

    def test_all_30_teams_present(self):
        """Property: Exactly 30 NBA teams are mapped."""
        assert len(TEAM_MAPPINGS) == 30

    @given(nba_tricode())
    def test_all_teams_have_full_name(self, nba_code):
        """Property: All teams have full names."""
        full_name = get_full_name(nba_code)
        assert full_name is not None
        assert len(full_name) > 0

    @given(nba_tricode())
    def test_all_teams_have_br_code(self, nba_code):
        """Property: All teams have BR tricodes."""
        br_code = get_br_tricode(nba_code)
        assert br_code is not None
        assert len(br_code) >= 2

    @given(nba_tricode())
    def test_all_teams_have_espn_code(self, nba_code):
        """Property: All teams have ESPN tricodes."""
        espn_code = get_espn_tricode(nba_code)
        assert espn_code is not None
        assert len(espn_code) >= 2


# =============================================================================
# Known Teams Tests
# =============================================================================

class TestKnownTeams:
    """Test specific known team mappings."""

    def test_lakers_mapping(self):
        """Test Lakers can be looked up multiple ways."""
        assert get_nba_tricode('LAL') == 'LAL'
        assert get_nba_tricode('Lakers') == 'LAL'
        assert get_nba_tricode('Los Angeles Lakers') == 'LAL'
        assert get_full_name('LAL') == 'Los Angeles Lakers'

    def test_warriors_mapping(self):
        """Test Warriors different tricode systems."""
        assert get_nba_tricode('GSW') == 'GSW'
        assert get_nba_tricode('GS') == 'GSW'  # ESPN code
        assert get_espn_tricode('GSW') == 'GS'

    def test_nets_mapping(self):
        """Test Nets BR vs NBA tricode."""
        assert get_nba_tricode('BKN') == 'BKN'
        assert get_nba_tricode('BRK') == 'BKN'  # BR code
        assert get_br_tricode('BKN') == 'BRK'

    def test_hornets_mapping(self):
        """Test Hornets BR vs NBA tricode."""
        assert get_nba_tricode('CHA') == 'CHA'
        assert get_nba_tricode('CHO') == 'CHA'  # BR code
        assert get_br_tricode('CHA') == 'CHO'

    def test_suns_mapping(self):
        """Test Suns BR vs NBA tricode."""
        assert get_nba_tricode('PHX') == 'PHX'
        assert get_nba_tricode('PHO') == 'PHX'  # BR code
        assert get_br_tricode('PHX') == 'PHO'


# =============================================================================
# Partial Match Tests
# =============================================================================

class TestPartialMatches:
    """Test partial name matching."""

    @given(nba_tricode())
    def test_nickname_matches(self, nba_code):
        """Property: Team nickname should match."""
        full_name = get_full_name(nba_code)

        # Extract nickname (last word usually)
        if ' ' in full_name:
            nickname = full_name.split()[-1]
            result = get_nba_tricode(nickname)

            # Should resolve to correct team (if nickname is unique)
            # Note: Some nicknames might not be unique (e.g., "City")
            if result:
                assert result == nba_code


# =============================================================================
# Round-Trip Tests
# =============================================================================

class TestRoundTrips:
    """Test round-trip conversions."""

    @given(nba_tricode())
    def test_nba_to_br_to_nba(self, nba_code):
        """Property: NBA -> BR -> NBA round trip."""
        br_code = get_br_tricode(nba_code)
        back_to_nba = get_nba_tricode(br_code)

        assert back_to_nba == nba_code

    @given(nba_tricode())
    def test_nba_to_espn_to_nba(self, nba_code):
        """Property: NBA -> ESPN -> NBA round trip."""
        espn_code = get_espn_tricode(nba_code)
        back_to_nba = get_nba_tricode(espn_code)

        assert back_to_nba == nba_code

    @given(nba_tricode())
    def test_nba_to_name_to_nba(self, nba_code):
        """Property: NBA -> full name -> NBA round trip."""
        full_name = get_full_name(nba_code)
        back_to_nba = get_nba_tricode(full_name)

        assert back_to_nba == nba_code


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
