# Session 13B: Data Quality Investigation - line_value = 20

**Date:** January 12, 2026
**Focus:** Investigate why 6,000+ picks have line_value = 20 instead of real prop lines
**Priority:** P1 - This is causing OVER picks to show 51.6% win rate instead of 73.1%
**Status:** ROOT CAUSE IDENTIFIED - Fix Planned

---

## Executive Summary

### The Problem
OVER picks appear to have 51.6% win rate, but this is WRONG. The actual performance is:

| Condition | OVER Win Rate | UNDER Win Rate |
|-----------|---------------|----------------|
| With real lines (line_value != 20) | **73.1%** | 69.5% |
| With default line (line_value = 20) | 36.7% | 97.9% |
| Combined (corrupted) | 51.6% | 94.3% |

### Root Cause (CONFIRMED)
**Player name normalization inconsistency** between data sources:

| Processor | Suffixes | `"Michael Porter Jr."` → |
|-----------|----------|--------------------------|
| ESPN Rosters | **REMOVES** | `michaelporter` |
| BettingPros Props | **REMOVES** | `michaelporter` |
| Odds API Props | KEEPS | `michaelporterjr` |

**Result:** JOIN fails for all suffix players (Jr., Sr., II, III, etc.)

### Affected Players
- Michael Porter Jr., Kelly Oubre Jr., Gary Payton II, Tim Hardaway Jr.
- Jaren Jackson Jr., Marcus Morris Sr., Larry Nance Jr., Wendell Carter Jr.
- And all other players with suffixes

---

## Investigation Results

### Hypothesis #2 CONFIRMED: player_lookup Format Mismatch

The investigation confirmed that:
1. ESPN roster processor uses custom `_normalize_player_name()` that REMOVES suffixes
2. BettingPros props processor uses custom `normalize_player_name()` that REMOVES suffixes
3. Odds API props processor uses shared `normalize_name()` that KEEPS suffixes
4. When `upcoming_player_game_context` JOINs ESPN rosters with Odds API props, suffix players don't match
5. Coordinator falls back to estimated/default line when no match found

### Files with Inconsistent Normalization
- `data_processors/raw/espn/espn_team_roster_processor.py:443-458` - Custom, removes suffixes
- `data_processors/raw/bettingpros/bettingpros_player_props_processor.py:149-158` - Custom, removes suffixes

### Files with Correct Normalization (Standard)
- `data_processors/raw/utils/name_utils.py:14` - Shared, keeps suffixes
- `shared/utils/player_name_normalizer.py:16` - Shared, keeps suffixes
- `data_processors/raw/oddsapi/odds_api_props_processor.py:483` - Uses shared
- `data_processors/raw/nbacom/nbac_gamebook_processor.py:662` - Uses shared

---

## Fix Plan

### Phase 1: Code Changes (P1)
1. **P1-DATA-3:** Update ESPN roster processor to use `normalize_name()` from `name_utils.py`
2. **P1-DATA-4:** Update BettingPros props processor to use `normalize_name()` from `name_utils.py`

### Phase 2: Data Backfill (P2)
3. **P2-DATA-3:** Backfill `espn_team_rosters.player_lookup` with correct normalization
4. **P2-DATA-4:** Backfill `bettingpros_player_points_props.player_lookup` with correct normalization

### Phase 3: Downstream (P2)
5. Regenerate `upcoming_player_game_context` for affected dates
6. Optionally re-run predictions/grading for historical data

---

## Documentation Created

- **Investigation Report:** `docs/08-projects/current/pipeline-reliability-improvements/data-quality/2026-01-12-PLAYER-LOOKUP-NORMALIZATION-MISMATCH.md`
- **TODO Items Added:** MASTER-TODO.md updated with P1-DATA-3, P1-DATA-4, P2-DATA-3, P2-DATA-4

---

## Original Investigation Context

---

## Key Findings from Session 12

### Dates with 100% line_value = 20
Many dates have ALL picks using the default line:
- Nov 19, 21, 22, 24, 25, 26, 29, 30
- Dec 2, 3, 5, 7, 8, 10, 12, 13, 16, 17, 18

### Props Exist But Don't Match
Example: Dec 12, 2025
- prediction_accuracy: 239 picks, ALL with line_value = 20
- odds_api_player_points_props: 105 unique players, 555 prop records

So the props exist - the matching is failing.

---

## Investigation Steps

### 1. Understand the Prop Matching Flow

```bash
# Study these files:
# - Where are prop lines assigned during prediction generation?
# - Where are prop lines assigned during grading?

# Key files to read:
cat predictions/coordinator/coordinator.py | head -200
cat predictions/coordinator/player_loader.py | head -200
cat orchestration/cloud_functions/grading/main.py
```

### 2. Check Prop Matching Logic

```sql
-- Find mismatches between predictions and props
SELECT
  ppp.game_date,
  ppp.player_lookup,
  ppp.predicted_points,
  props.points_line as actual_prop,
  CASE WHEN props.points_line IS NULL THEN 'NO_MATCH' ELSE 'MATCHED' END as status
FROM `nba-props-platform.nba_predictions.player_prop_predictions` ppp
LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` props
  ON ppp.player_lookup = props.player_lookup
  AND ppp.game_date = props.game_date
WHERE ppp.game_date = '2025-12-12'
  AND ppp.system_id = 'catboost_v8'
LIMIT 20
```

### 3. Check player_lookup Format Mismatches

```sql
-- Are player_lookups different between tables?
SELECT DISTINCT p.player_lookup as pred_lookup,
  (SELECT player_lookup FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
   WHERE game_date = '2025-12-12' AND player_name LIKE CONCAT('%', SPLIT(p.player_lookup, '')[1], '%')
   LIMIT 1) as props_lookup
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
WHERE p.game_date = '2025-12-12' AND p.system_id = 'catboost_v8'
LIMIT 20
```

---

## Key Code Locations

### Prediction Generation (where line is first assigned)
- `predictions/coordinator/player_loader.py` - `_create_prediction_request()`
- Look for where `prop_line` or `line_value` is set

### Grading (where line is used for accuracy)
- `orchestration/cloud_functions/grading/main.py`
- `data_processors/predictions/grading/` (if exists)
- Look for where `line_value = 20` default might be set

### Props Loading
- `scrapers/odds_api/` - How props are scraped
- `data_processors/raw/odds_api/` - How props are processed

---

## Hypothesis to Test

1. **Timing issue:** Props loaded AFTER predictions generated, so no match at prediction time
2. **player_lookup mismatch:** Different formats between predictions and props tables
3. **game_date mismatch:** Timezone issues causing date differences
4. **Default fallback:** Code explicitly sets 20 as default when no prop found

---

## DO NOT WORK ON

These are handled by other sessions:
- **Session 13A:** Pipeline recovery (Phase 4, predictions, grading backfill)
- **Session 13C:** Retry mechanisms, monitoring alerts

---

## Success Criteria

1. Identify WHY props aren't matching
2. Propose fix (code change or backfill)
3. Estimate impact: How many picks can be fixed?

---

## Quick Reference Queries

```sql
-- Check a specific date's prop coverage
SELECT
  COUNT(*) as total_picks,
  COUNTIF(line_value = 20) as default_line,
  COUNTIF(line_value != 20) as real_line
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = '2025-12-12' AND system_id = 'catboost_v8'

-- Check raw props for same date
SELECT COUNT(DISTINCT player_lookup), COUNT(*)
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date = '2025-12-12'
```
