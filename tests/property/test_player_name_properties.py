"""
Property-based tests for player name normalization.

Uses Hypothesis to verify:
- Name normalization idempotence (normalize twice = normalize once)
- Non-empty inputs never produce empty normalized outputs
- Common variations map to same canonical form
- Suffix handling consistency
- Diacritic removal correctness
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
import unicodedata


# =============================================================================
# Name Normalization Functions (mirroring shared/utils/player_name_normalizer.py)
# =============================================================================

def remove_diacritics(text: str) -> str:
    """Remove diacritics and accents from text."""
    if not text:
        return ""
    nfd = unicodedata.normalize('NFD', text)
    ascii_text = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    return ascii_text


def normalize_name_for_lookup(name: str) -> str:
    """Normalize player name for consistent lookups."""
    if not name:
        return ""

    normalized = name.lower()
    normalized = remove_diacritics(normalized)

    # Remove punctuation and separators
    normalized = normalized.replace(' ', '')
    normalized = normalized.replace('-', '')
    normalized = normalized.replace("'", '')
    normalized = normalized.replace('.', '')
    normalized = normalized.replace(',', '')
    normalized = normalized.replace('_', '')

    # Remove any remaining non-alphanumeric
    import re
    normalized = re.sub(r'[^a-z0-9]', '', normalized)

    return normalized


def extract_suffix(name: str):
    """Extract suffix from player name."""
    if not name:
        return "", None

    suffixes = [
        'Junior', 'Senior',
        'Jr.', 'Sr.',
        'III', 'IV', 'V', 'II',
        '3rd', '4th', '5th', '2nd',
        'Jr', 'Sr',
    ]

    name_trimmed = name.strip()

    for suffix in suffixes:
        if name_trimmed.lower().endswith(suffix.lower()):
            base_name = name_trimmed[:-len(suffix)].strip()
            return base_name, suffix

    return name_trimmed, None


# =============================================================================
# Hypothesis Strategies for Player Names
# =============================================================================

@composite
def player_first_name(draw):
    """Generate realistic first names."""
    common_first = ['LeBron', 'Stephen', 'Kevin', 'James', 'Anthony',
                   'Chris', 'Michael', 'Kobe', 'Tim', 'Larry', 'Magic',
                   'Karl', 'Dirk', 'Pau', 'Tony', 'Manu', 'José', 'Luka']

    return draw(st.sampled_from(common_first))


@composite
def player_last_name(draw):
    """Generate realistic last names."""
    common_last = ['James', 'Curry', 'Durant', 'Harden', 'Davis',
                  'Paul', 'Jordan', 'Bryant', 'Duncan', 'Bird', 'Johnson',
                  'Anthony', 'Towns', 'Nowitzki', 'Gasol', 'Parker',
                  'Ginobili', 'Alvarado', 'Dončić', 'Jokić']

    return draw(st.sampled_from(common_last))


@composite
def player_name_with_suffix(draw):
    """Generate player name with suffix."""
    first = draw(player_first_name())
    last = draw(player_last_name())
    suffix = draw(st.sampled_from(['Jr.', 'Sr.', 'II', 'III', 'IV']))

    return f"{first} {last} {suffix}"


@composite
def player_name_with_punctuation(draw):
    """Generate names with various punctuation."""
    first = draw(player_first_name())
    last = draw(player_last_name())

    # Add punctuation variations
    variations = [
        f"{first} {last}",
        f"{first}-{last}",
        f"{first}.{last}",
        f"{first}'{last}",
        f"O'{last}",
        f"De'{first}",
        f"{first} {last}, {draw(st.sampled_from(['Jr.', 'Sr.']))}",
    ]

    return draw(st.sampled_from(variations))


@composite
def player_name_with_diacritics(draw):
    """Generate names with diacritics."""
    names_with_diacritics = [
        'José Alvarado',
        'Dāvis Bertāns',
        'Luka Dončić',
        'Nikola Jokić',
        'Bogdan Bogdanović',
        'Nicolás Laprovíttola',
        'Ömer Aşık',
        'Sasha Vujačić',
        'Žarko Čabarkapa',
        'Goran Dragić',
    ]

    return draw(st.sampled_from(names_with_diacritics))


@composite
def player_name_any(draw):
    """Generate any type of player name."""
    return draw(st.one_of(
        player_first_name(),
        player_last_name(),
        st.text(min_size=1, max_size=2).map(lambda s: f"{s} {s}"),
        player_name_with_suffix(),
        player_name_with_punctuation(),
        player_name_with_diacritics(),
    ))


# =============================================================================
# Idempotence Tests
# =============================================================================

class TestNameNormalizationIdempotence:
    """Test that normalization is idempotent (applying twice = applying once)."""

    @given(player_name_any())
    @settings(max_examples=200)
    def test_normalize_is_idempotent(self, name):
        """Property: normalize(normalize(name)) == normalize(name)."""
        normalized_once = normalize_name_for_lookup(name)
        normalized_twice = normalize_name_for_lookup(normalized_once)

        assert normalized_once == normalized_twice, \
            f"Not idempotent: {name!r} -> {normalized_once!r} -> {normalized_twice!r}"

    @given(st.text(min_size=1, max_size=50))
    @settings(max_examples=500)
    def test_normalize_any_string_is_idempotent(self, text):
        """Property: Idempotence holds for any string."""
        normalized_once = normalize_name_for_lookup(text)
        normalized_twice = normalize_name_for_lookup(normalized_once)

        assert normalized_once == normalized_twice


# =============================================================================
# Non-Empty Output Tests
# =============================================================================

class TestNonEmptyOutput:
    """Test that non-empty inputs never produce empty normalized outputs."""

    @given(st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=('L', 'N'),  # Letters and numbers
        min_codepoint=ord('a'), max_codepoint=ord('z')
    )))
    @settings(max_examples=200)
    def test_non_empty_alphanumeric_never_empty(self, name):
        """Property: Non-empty alphanumeric input never produces empty output."""
        assume(name.strip())  # Skip pure whitespace

        result = normalize_name_for_lookup(name)

        assert result != "", \
            f"Empty output for non-empty input: {name!r}"

    @given(player_name_any())
    def test_player_names_never_empty(self, name):
        """Property: Real player names never normalize to empty string."""
        # Skip if name only contains punctuation/separators
        assume(any(c.isalnum() for c in name))

        result = normalize_name_for_lookup(name)

        assert result != "", \
            f"Player name normalized to empty: {name!r}"

    @given(st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=('P', 'Z'),  # Punctuation and separators only
    )))
    def test_pure_punctuation_produces_empty(self, punctuation):
        """Property: Pure punctuation/whitespace produces empty output."""
        result = normalize_name_for_lookup(punctuation)

        # This is expected behavior - no letters/numbers means empty output
        assert result == ""


# =============================================================================
# Common Variations Tests
# =============================================================================

class TestCommonVariations:
    """Test that common variations map to same canonical form."""

    @example("LeBron James Jr.")
    @example("LeBron James Jr")
    @example("lebron james jr.")
    @given(st.sampled_from([
        ("LeBron James Jr.", "LeBron James Jr"),
        ("LeBron James Jr.", "lebron james jr."),
        ("P.J. Tucker", "PJ Tucker"),
        ("T.J. McConnell", "TJ McConnell"),
        ("Michael Porter Jr.", "Michael Porter Jr"),
        ("O'Neal", "ONeal"),
        ("De'Andre Jordan", "DeAndre Jordan"),
    ]))
    def test_suffix_variations_normalize_same(self, name_pair):
        """Property: Different suffix formats normalize to same value."""
        name1, name2 = name_pair

        result1 = normalize_name_for_lookup(name1)
        result2 = normalize_name_for_lookup(name2)

        assert result1 == result2, \
            f"Variations don't match: {name1!r} -> {result1!r}, {name2!r} -> {result2!r}"

    @given(player_name_any())
    def test_case_insensitive(self, name):
        """Property: Normalization is case insensitive."""
        upper = normalize_name_for_lookup(name.upper())
        lower = normalize_name_for_lookup(name.lower())
        original = normalize_name_for_lookup(name)

        assert upper == lower == original

    @given(player_name_any())
    def test_whitespace_insensitive(self, name):
        """Property: Extra whitespace doesn't affect normalization."""
        normal = normalize_name_for_lookup(name)
        with_spaces = normalize_name_for_lookup(f"  {name}  ")
        double_spaces = normalize_name_for_lookup(name.replace(' ', '  '))

        assert normal == with_spaces == double_spaces


# =============================================================================
# Suffix Extraction Tests
# =============================================================================

class TestSuffixExtraction:
    """Test suffix extraction consistency."""

    @given(player_name_with_suffix())
    def test_suffix_extracted_correctly(self, name):
        """Property: Suffixes are correctly extracted."""
        base_name, suffix = extract_suffix(name)

        # Base name should not be empty
        assert base_name.strip() != ""

        # Suffix should be recognized
        assert suffix is not None

        # Reconstructing should give similar result
        if suffix:
            assert suffix.lower() in name.lower()

    @given(st.sampled_from(['Jr.', 'Sr.', 'II', 'III', 'IV', 'V']))
    def test_suffix_with_same_suffix_idempotent(self, suffix):
        """Property: Extracting suffix twice gives same result."""
        name = f"John Smith {suffix}"

        base1, suffix1 = extract_suffix(name)
        base2, suffix2 = extract_suffix(base1)

        # Second extraction should not find a suffix
        assert suffix1 == suffix
        assert suffix2 is None
        assert base1 == base2

    @given(player_first_name(), player_last_name())
    def test_no_suffix_returns_none(self, first, last):
        """Property: Names without suffixes return None."""
        name = f"{first} {last}"
        base_name, suffix = extract_suffix(name)

        assert suffix is None
        assert base_name == name.strip()

    @given(st.sampled_from([
        ("Charlie Brown Jr.", "Jr."),
        ("John Smith Sr.", "Sr."),
        ("Robert Jones III", "III"),
        ("Michael Davis IV", "IV"),
    ]))
    def test_known_suffixes_extracted(self, name_suffix_pair):
        """Property: Known suffix patterns are correctly extracted."""
        name, expected_suffix = name_suffix_pair
        base_name, suffix = extract_suffix(name)

        assert suffix == expected_suffix
        assert suffix not in base_name


# =============================================================================
# Diacritic Removal Tests
# =============================================================================

class TestDiacriticRemoval:
    """Test diacritic and accent removal."""

    @given(player_name_with_diacritics())
    def test_diacritics_removed(self, name):
        """Property: Diacritics are removed in normalization."""
        normalized = normalize_name_for_lookup(name)

        # Result should only contain ASCII characters
        assert all(ord(c) < 128 for c in normalized), \
            f"Non-ASCII in result: {normalized!r}"

    @given(st.sampled_from([
        ('José', 'jose'),
        ('Dāvis', 'davis'),
        ('Nikola', 'nikola'),  # No diacritics - should stay same
        ('Bogdanović', 'bogdanovic'),
        ('Ömer', 'omer'),
        ('Nicolás', 'nicolas'),
    ]))
    def test_specific_diacritics(self, name_pair):
        """Property: Specific diacritics map correctly."""
        original, expected = name_pair
        result = remove_diacritics(original.lower())

        assert result == expected.lower()

    @given(st.text(min_size=1, max_size=30, alphabet=st.characters(
        whitelist_categories=('L',),
        min_codepoint=0x0100,  # Latin Extended-A (includes ā, ē, etc.)
        max_codepoint=0x017F
    )))
    def test_extended_latin_removed(self, text):
        """Property: Extended Latin characters are converted to ASCII."""
        result = remove_diacritics(text)

        # All characters should be basic ASCII or empty
        for char in result:
            assert ord(char) < 128 or char == ''


# =============================================================================
# Normalization Consistency Tests
# =============================================================================

class TestNormalizationConsistency:
    """Test that normalization produces consistent results."""

    @given(player_name_any(), player_name_any())
    def test_equal_names_equal_normalized(self, name1, name2):
        """Property: Equal names produce equal normalized forms."""
        if name1 == name2:
            result1 = normalize_name_for_lookup(name1)
            result2 = normalize_name_for_lookup(name2)
            assert result1 == result2

    @given(player_name_any())
    def test_normalized_only_alphanumeric(self, name):
        """Property: Normalized names only contain lowercase alphanumeric."""
        result = normalize_name_for_lookup(name)

        for char in result:
            assert char.isalnum() and char.islower(), \
                f"Invalid character in normalized: {char!r} in {result!r}"

    @given(st.text(min_size=1, max_size=50))
    def test_normalization_deterministic(self, name):
        """Property: Normalization is deterministic (same input -> same output)."""
        result1 = normalize_name_for_lookup(name)
        result2 = normalize_name_for_lookup(name)
        result3 = normalize_name_for_lookup(name)

        assert result1 == result2 == result3


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Test edge cases in name normalization."""

    @given(st.sampled_from([None, '', '   ', '\t', '\n']))
    def test_empty_inputs(self, empty_input):
        """Property: Empty inputs produce empty output."""
        result = normalize_name_for_lookup(empty_input or '')
        assert result == ""

    @given(st.integers(min_value=1, max_value=100))
    def test_very_long_names(self, length):
        """Property: Very long names are handled correctly."""
        long_name = 'a' * length
        result = normalize_name_for_lookup(long_name)

        assert result == 'a' * length
        assert len(result) == length

    @given(st.text(min_size=1, max_size=50, alphabet='.,\'-_ '))
    def test_only_separators(self, separators):
        """Property: Strings with only separators produce empty output."""
        result = normalize_name_for_lookup(separators)
        assert result == ""

    @given(st.text(min_size=1, max_size=20, alphabet='0123456789'))
    def test_numeric_names(self, numeric):
        """Property: Numeric strings are preserved (lowercase conversion only)."""
        result = normalize_name_for_lookup(numeric)
        assert result == numeric.lower()


# =============================================================================
# Real-World Examples Tests
# =============================================================================

class TestRealWorldExamples:
    """Test with real NBA player names."""

    def test_known_problematic_names(self):
        """Test names that have caused issues in production."""
        test_cases = [
            ("Charlie Brown Jr.", "charliebrownjr"),
            ("P.J. Tucker", "pjtucker"),
            ("T.J. McConnell", "tjmcconnell"),
            ("Michael Porter Jr.", "michaelporterjr"),
            ("O'Neal", "oneal"),
            ("De'Andre Jordan", "deandrejordan"),
            ("Karl-Anthony Towns", "karlanthonytowns"),
            ("José Alvarado", "josealvarado"),
            ("Luka Dončić", "lukadoncic"),
            ("Nikola Jokić", "nikolajokic"),
        ]

        for original, expected in test_cases:
            result = normalize_name_for_lookup(original)
            assert result == expected, \
                f"Failed: {original!r} -> {result!r}, expected {expected!r}"

    def test_suffix_variations_consistency(self):
        """Test that suffix variations normalize identically."""
        variants = [
            "LeBron James Jr.",
            "LeBron James Jr",
            "lebron james jr.",
            "LeBron James Junior",
        ]

        results = [normalize_name_for_lookup(v) for v in variants]

        # All should normalize to same value
        assert len(set(results)) == 1, \
            f"Inconsistent normalization: {list(zip(variants, results))}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
