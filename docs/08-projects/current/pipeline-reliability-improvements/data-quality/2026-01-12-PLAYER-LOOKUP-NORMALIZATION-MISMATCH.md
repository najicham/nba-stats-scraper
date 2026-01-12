# Player Lookup Normalization Mismatch Investigation

**Discovery Date:** January 12, 2026
**Severity:** High (P1)
**Status:** Root Cause Identified - Fix Planned
**Impact:** 6,000+ predictions have incorrect `line_value = 20` due to props not matching

---

## Executive Summary

### The Problem
OVER picks appear to have 51.6% win rate when the **actual performance is 73.1%**. This is caused by 6,000+ picks using `line_value = 20` (a default) instead of real prop lines.

| Condition | OVER Win Rate | UNDER Win Rate |
|-----------|---------------|----------------|
| With real lines (line_value != 20) | **73.1%** | 69.5% |
| With default line (line_value = 20) | 36.7% | 97.9% |
| Combined (corrupted) | 51.6% | 94.3% |

### Root Cause
**Player name normalization inconsistency** between data sources:
- ESPN rosters and BettingPros props **REMOVE** suffixes (Jr., Sr., II, III)
- Odds API props **KEEPS** suffixes

This causes JOIN failures for all players with suffixes (Michael Porter Jr., Gary Payton II, etc.)

---

## Technical Analysis

### Normalization Functions Comparison

| Processor | File | Function | Suffixes | Example Output |
|-----------|------|----------|----------|----------------|
| **ESPN Rosters** | `espn_team_roster_processor.py:443` | `_normalize_player_name()` | REMOVES | `michaelporter` |
| **BettingPros Props** | `bettingpros_player_props_processor.py:149` | `normalize_player_name()` | REMOVES | `michaelporter` |
| **Odds API Props** | `odds_api_props_processor.py:483` | `normalize_name()` | KEEPS | `michaelporterjr` |
| **NBAC Gamebook** | `nbac_gamebook_processor.py:662` | `normalize_name_for_lookup()` | KEEPS | `michaelporterjr` |
| **BDL Active Players** | `bdl_active_players_processor.py:280` | `normalize_name()` | KEEPS | `michaelporterjr` |

### The Standard (Shared Normalizers)

Two shared normalizers exist, both produce identical output and **KEEP suffixes**:

1. `data_processors/raw/utils/name_utils.py::normalize_name()`
2. `shared/utils/player_name_normalizer.py::normalize_name_for_lookup()`

### The Deviation (Custom Normalizers)

**ESPN Roster Processor** (`espn_team_roster_processor.py:443-458`):
```python
def _normalize_player_name(self, name: str) -> str:
    normalized = name.lower().strip()
    # REMOVES suffixes - this is the problem!
    suffixes = [' jr.', ' jr', ' sr.', ' sr', ' ii', ' iii', ' iv', ' v']
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    return normalized
```

**BettingPros Props Processor** (`bettingpros_player_props_processor.py:149-158`):
```python
def normalize_player_name(self, player_name: str) -> str:
    normalized = player_name.lower().strip()
    # REMOVES suffixes - same problem!
    normalized = re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', normalized)
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    return normalized
```

### Data Flow Where Mismatch Occurs

```
ESPN Rosters                    Odds API Props
     │                               │
     │ player_lookup =               │ player_lookup =
     │ "michaelporter"               │ "michaelporterjr"
     │                               │
     └──────────┬────────────────────┘
                │
                ▼
    upcoming_player_game_context
    (LEFT JOIN on player_lookup)
                │
                │ NO MATCH for suffix players!
                │ has_prop_line = FALSE
                ▼
    Coordinator falls back to
    estimated line or default
                │
                ▼
    Predictions use line_value = 20
    (historical default)
```

---

## Affected Players (Examples)

Common NBA players with suffixes who are affected:
- Michael Porter Jr.
- Kelly Oubre Jr.
- Gary Payton II
- Tim Hardaway Jr.
- Jaren Jackson Jr.
- Marcus Morris Sr.
- Larry Nance Jr.
- Wendell Carter Jr.
- Gary Trent Jr.
- Kenyon Martin Jr.
- Jabari Smith Jr.
- Scottie Barnes Jr. (if applicable)

---

## Fix Plan

### Phase 1: Code Changes (P1 - Immediate)

**1. Update ESPN Roster Processor**
- File: `data_processors/raw/espn/espn_team_roster_processor.py`
- Change: Import and use `normalize_name` from `name_utils.py`
- Lines affected: 162, 443-458

```python
# Add import
from data_processors.raw.utils.name_utils import normalize_name

# Replace line 162:
# OLD: player_lookup = self._normalize_player_name(full_name)
# NEW: player_lookup = normalize_name(full_name)
```

**2. Update BettingPros Props Processor**
- File: `data_processors/raw/bettingpros/bettingpros_player_props_processor.py`
- Change: Import and use `normalize_name` from `name_utils.py`
- Lines affected: 149-158, all usages

```python
# Add import
from data_processors.raw.utils.name_utils import normalize_name

# Replace usage of self.normalize_player_name() with normalize_name()
```

### Phase 2: Data Backfill (P2 - After Deploy)

**1. Backfill ESPN Rosters**
```sql
-- Update player_lookup to include suffixes
UPDATE `nba-props-platform.nba_raw.espn_team_rosters`
SET player_lookup = LOWER(REGEXP_REPLACE(
    NORMALIZE(player_full_name, NFD),
    r'[^a-z0-9]', ''
))
WHERE player_lookup IS NOT NULL;
```

**2. Backfill BettingPros Props**
```sql
-- Update player_lookup to include suffixes
UPDATE `nba-props-platform.nba_raw.bettingpros_player_points_props`
SET player_lookup = LOWER(REGEXP_REPLACE(
    NORMALIZE(player_name, NFD),
    r'[^a-z0-9]', ''
))
WHERE player_lookup IS NOT NULL;
```

**3. Verify Backfill Success**
```sql
-- Check suffix players now have correct format
SELECT player_full_name, player_lookup
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE player_full_name LIKE '%Jr.%'
   OR player_full_name LIKE '%Sr.%'
   OR player_full_name LIKE '%II%'
LIMIT 20;
```

### Phase 3: Downstream Regeneration (P2)

1. Regenerate `upcoming_player_game_context` for affected dates
2. Optionally re-run predictions for affected dates (high effort)
3. Re-grade affected predictions

### Phase 4: Prevention (P3)

1. Add unit test verifying all processors use standard normalizer
2. Document `normalize_name()` as the canonical function in README
3. Consider adding a linter rule

---

## Verification Queries

### Check Current Mismatch
```sql
-- Find suffix players in Odds API that don't match ESPN rosters
WITH odds_players AS (
    SELECT DISTINCT player_name, player_lookup
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date >= '2025-11-01'
),
espn_players AS (
    SELECT DISTINCT player_full_name, player_lookup
    FROM `nba-props-platform.nba_raw.espn_team_rosters`
    WHERE roster_date >= '2025-11-01'
)
SELECT
    o.player_name as odds_name,
    o.player_lookup as odds_lookup,
    e.player_full_name as espn_name,
    e.player_lookup as espn_lookup
FROM odds_players o
LEFT JOIN espn_players e ON o.player_lookup = e.player_lookup
WHERE o.player_lookup LIKE '%jr%'
   OR o.player_lookup LIKE '%sr%'
   OR o.player_lookup LIKE '%ii%'
   OR o.player_lookup LIKE '%iii%';
```

### Check line_value = 20 Distribution
```sql
-- Dates with highest proportion of default lines
SELECT
    game_date,
    COUNT(*) as total_picks,
    COUNTIF(line_value = 20) as default_line,
    COUNTIF(line_value != 20) as real_line,
    ROUND(100.0 * COUNTIF(line_value = 20) / COUNT(*), 1) as pct_default
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8'
  AND game_date >= '2025-11-01'
GROUP BY game_date
HAVING COUNTIF(line_value = 20) > 0
ORDER BY pct_default DESC;
```

---

## Risk Assessment

### Risks of the Fix
1. **Low:** Code change is straightforward import swap
2. **Medium:** Backfill SQL needs testing in non-prod first
3. **Low:** Downstream regeneration is standard backfill process

### Risks of NOT Fixing
1. **High:** All suffix players continue to have wrong predictions
2. **High:** Performance metrics remain corrupted
3. **High:** Model evaluation is inaccurate

---

## Related Documents

- **Original Handoff:** `docs/09-handoff/2026-01-12-SESSION-13B-DATA-QUALITY.md`
- **Master TODO:** `docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md`
- **Shared Normalizer:** `data_processors/raw/utils/name_utils.py`
- **Alternative Normalizer:** `shared/utils/player_name_normalizer.py`

---

## Timeline

| Phase | Task | Effort | Priority |
|-------|------|--------|----------|
| 1 | Code fix: ESPN roster processor | 15 min | P1 |
| 1 | Code fix: BettingPros props processor | 15 min | P1 |
| 1 | Deploy and verify | 30 min | P1 |
| 2 | Backfill ESPN rosters | 30 min | P2 |
| 2 | Backfill BettingPros props | 30 min | P2 |
| 2 | Verify backfill | 15 min | P2 |
| 3 | Regenerate context for affected dates | 2-4 hrs | P2 |
| 4 | Add unit tests | 1 hr | P3 |
| 4 | Document standard | 30 min | P3 |

**Total Estimated Effort:** 5-7 hours

---

*Last Updated: January 12, 2026*
*Status: Root Cause Identified, Fix Planned*
