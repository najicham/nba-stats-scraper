# Prevention Strategy: Player Lookup Normalization Issues

**Date:** January 12, 2026
**Status:** Implemented
**Related Issue:** Session 13B - Player name normalization mismatch

---

## Problem Summary

ESPN rosters and BettingPros processors had custom normalization functions that REMOVED player name suffixes (Jr., Sr., II, III, IV, V), while Odds API used the shared `normalize_name()` function that correctly KEPT suffixes.

**Impact:** 6,000+ predictions got default `line_value = 20` instead of real Vegas lines due to JOIN failures.

---

## Root Cause Analysis

### Why It Happened

1. **Independent Development:** ESPN and BettingPros processors were developed separately
2. **Reasonable Local Assumption:** Developers assumed "suffixes should be cleaned for consistency"
3. **No Shared Standard Enforcement:** The `normalize_name()` function existed but wasn't mandated
4. **Test Blind Spot:** Unit tests used mock data without suffix players

### Why It Wasn't Caught

- Unit tests used generic names (`lebronjames`, `paulgeorge`) - no suffix players
- No cross-processor consistency tests
- No downstream JOIN validation tests
- Silent failure in production (defaulted to estimated lines)

---

## Prevention Measures

### 1. Single Source of Truth (Implemented)

**Location:** `data_processors/raw/utils/name_utils.py::normalize_name()`

All processors MUST use this shared function for player name normalization:

```python
from data_processors.raw.utils.name_utils import normalize_name

# Always use this for player_lookup
player_lookup = normalize_name(player_full_name)
```

**Verification:** Run `python bin/patches/verify_normalization_fix.py` before deployment.

### 2. Deprecation Markers (Implemented)

Old custom normalization methods are marked with:
```python
# DEPRECATED: Use normalize_name() from data_processors.raw.utils.name_utils instead
# This method incorrectly removes suffixes (Jr., Sr., II, III)
```

### 3. Cross-Processor Integration Tests (Recommended)

Add tests that verify suffix players match across sources:

```python
# tests/integration/test_player_lookup_consistency.py

SUFFIX_PLAYERS = [
    ('Michael Porter Jr.', 'michaelporterjr'),
    ('Gary Payton II', 'garypaytonii'),
    ('Jaren Jackson Jr.', 'jarenjacksonjr'),
    ('Tim Hardaway Jr.', 'timhardawayjr'),
    ('Robert Williams III', 'robertwilliamsiii'),
    ('Marcus Morris Sr.', 'marcusmorrissr'),
]

def test_suffix_players_normalize_correctly():
    """Verify suffix players produce consistent player_lookup values."""
    for full_name, expected_lookup in SUFFIX_PLAYERS:
        assert normalize_name(full_name) == expected_lookup

def test_cross_processor_suffix_matching():
    """Verify suffix players from ESPN can JOIN with Odds API props."""
    # Query BigQuery for suffix players across sources
    # Verify match rate > 90%
```

### 4. Pre-Commit Hook (Recommended)

Add a pre-commit hook that checks for custom normalization patterns:

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: check-normalization
      name: Check for custom normalization
      entry: grep -r "\.lower().*\.strip().*suffix" data_processors/
      language: system
      pass_filenames: false
      types: [python]
```

### 5. Data Quality Alert (Recommended)

Add a Cloud Scheduler job that checks for JOIN failures:

```sql
-- Check for suffix players with missing props
WITH suffix_players AS (
    SELECT player_lookup, player_full_name
    FROM `nba_raw.espn_team_rosters`
    WHERE roster_date = CURRENT_DATE()
      AND (player_full_name LIKE '%Jr.%' OR player_full_name LIKE '%II%')
),
odds_props AS (
    SELECT DISTINCT player_lookup
    FROM `nba_raw.odds_api_player_points_props`
    WHERE game_date = CURRENT_DATE()
)
SELECT COUNT(*) as unmatched_suffix_players
FROM suffix_players s
LEFT JOIN odds_props o ON s.player_lookup = o.player_lookup
WHERE o.player_lookup IS NULL;
-- Alert if unmatched_suffix_players > 5
```

### 6. Schema Documentation (Implemented)

Document `player_lookup` semantics in schema files:

```sql
-- player_lookup: Normalized player name for JOINs
-- MUST be generated using normalize_name() from name_utils.py
-- Suffixes (Jr., Sr., II, III, IV, V) are KEPT
-- Example: "Michael Porter Jr." -> "michaelporterjr"
```

---

## Validation Queries

### Check Suffix Player Match Rate

```sql
WITH espn_suffix AS (
    SELECT DISTINCT player_lookup, player_full_name
    FROM `nba_raw.espn_team_rosters`
    WHERE roster_date >= '2025-11-01'
      AND (player_full_name LIKE '%Jr.%' OR player_full_name LIKE '%II%')
),
odds_suffix AS (
    SELECT DISTINCT player_lookup
    FROM `nba_raw.odds_api_player_points_props`
    WHERE game_date >= '2025-11-01'
)
SELECT
    COUNT(*) as total,
    COUNTIF(o.player_lookup IS NOT NULL) as matched,
    ROUND(COUNTIF(o.player_lookup IS NOT NULL) * 100.0 / COUNT(*), 1) as match_pct
FROM espn_suffix e
LEFT JOIN odds_suffix o ON e.player_lookup = o.player_lookup;
-- Expected: match_pct > 50% (some suffix players don't have props)
```

### Check for Default Line Values

```sql
SELECT game_date, COUNT(*) as default_line_predictions
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= '2025-11-01'
  AND current_points_line = 20
  AND line_source = 'ACTUAL_PROP'  -- Should use actual line, but got default
GROUP BY game_date
ORDER BY game_date DESC;
-- Expected: 0 predictions with line_value = 20 and ACTUAL_PROP source
```

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/raw/espn/espn_team_roster_processor.py` | Now uses `normalize_name()` |
| `data_processors/raw/bettingpros/bettingpros_player_props_processor.py` | Now uses `normalize_name()` |
| `bin/patches/verify_normalization_fix.py` | Verification script |
| `bin/patches/patch_player_lookup_normalization.sql` | Backfill SQL |

---

## Version History

- **v1.0 (Jan 12, 2026):** Initial prevention strategy document
