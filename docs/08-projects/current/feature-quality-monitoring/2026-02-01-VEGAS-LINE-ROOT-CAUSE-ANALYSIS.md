# Vegas Line Feature Store Root Cause Analysis

**Date:** 2026-02-01 (Session 62)
**Severity:** CRITICAL
**Status:** Root Cause Confirmed - Fix Designed

---

## Executive Summary

The ML feature store `vegas_line` coverage dropped from **99.4%** (Jan 2025) to **43.4%** (Jan 2026), causing the V8 model hit rate to collapse from 70-76% to 48-67%.

**Root Cause:** Two well-intentioned changes created an unintended incompatibility:
1. **Backfill mode** (Dec 10, 2025): Expanded player list to include ALL players who played
2. **Vegas source migration** (Jan 31, 2026): Changed Vegas extraction to use Phase 3 cascade

The result: Feature store now includes 500+ players per day, but only ~200 have Vegas lines in Phase 3.

---

## Timeline of Changes

| Date | Commit | Change | Intent | Unintended Effect |
|------|--------|--------|--------|-------------------|
| Dec 10, 2025 | `e4e31c06` | Added backfill_mode | Fix 35% roster coverage gap for Dec 2021 | Expanded player list without expanding Vegas source |
| Jan 31, 2026 | `bde97bd7` | Vegas source → Phase 3 | Use cascade for scraper resilience | Phase 3 only has Vegas for expected players |

---

## The Architectural Mismatch

### Data Flow Before (Working)

```
upcoming_player_game_context
├── Player list: 150-200 (players with props)
└── Vegas lines: 150-200 (same source, 99% match)

Result: 99.4% vegas_line coverage
```

### Data Flow After (Broken)

```
get_players_with_games(backfill_mode=True)
├── Source: player_game_summary
└── Returns: 500+ players (ALL who played)

_batch_extract_vegas_lines()
├── Source: upcoming_player_game_context
└── Returns: 150-200 players (only those with props)

Result: 43.4% vegas_line coverage (200/500)
```

### Why This Happened

1. **Backfill mode was designed to fix roster coverage**, not Vegas coverage
   - Goal: Include Luka, Jokic, etc. who were missing from Dec 2021 backfill
   - Side effect: Also included all bench players, DNPs, etc.

2. **Phase 3 cascade was designed for scraper resilience**, not backfill support
   - Goal: When BettingPros is down, fall back to Odds API
   - Side effect: Phase 3 only has lines for "expected" players, not all players

3. **The changes happened at different times by different people**
   - No one connected that backfill mode expansion + Phase 3 Vegas source = mismatch

---

## Why This Wasn't Detected

### Gap 1: No Vegas Line Coverage Monitoring

**What exists:** Pre-write validation checks value ranges (vegas_line between 0-80)
**What's missing:** Coverage check comparing vegas_line presence to baseline

```sql
-- This check didn't exist
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_coverage
FROM ml_feature_store_v2
WHERE game_date = @date
-- Should alert if <80% (baseline was 99.4%)
```

### Gap 2: No Cross-Source Validation

**What exists:** Per-table health checks
**What's missing:** Validation that player list source and feature source are compatible

```sql
-- This check didn't exist
WITH players AS (
  SELECT COUNT(*) as player_count FROM player_game_summary WHERE game_date = @date
),
vegas AS (
  SELECT COUNT(*) as vegas_count FROM upcoming_player_game_context
  WHERE game_date = @date AND current_points_line > 0
)
SELECT vegas_count / player_count as expected_coverage
-- Should warn if < 0.5 (means sources are mismatched)
```

### Gap 3: No Historical Baseline Comparison

**What exists:** Daily health metrics
**What's missing:** Comparison to same period last season

```sql
-- This check didn't exist
WITH current AS (
  SELECT AVG(CASE WHEN features[OFFSET(25)] > 0 THEN 1 ELSE 0 END) as coverage
  FROM ml_feature_store_v2 WHERE game_date BETWEEN '2026-01-01' AND '2026-01-31'
),
baseline AS (
  SELECT AVG(CASE WHEN features[OFFSET(25)] > 0 THEN 1 ELSE 0 END) as coverage
  FROM ml_feature_store_v2 WHERE game_date BETWEEN '2025-01-01' AND '2025-01-31'
)
SELECT current.coverage - baseline.coverage as drift
-- Should alert if drift > 0.2 (20% drop from baseline)
```

---

## Fix Design

### Option A: Fix Vegas Extraction for Backfill (RECOMMENDED)

Modify `_batch_extract_vegas_lines()` to use raw betting tables when Phase 3 doesn't have coverage:

```python
def _batch_extract_vegas_lines(self, game_date: date, player_lookups: List[str],
                                backfill_mode: bool = False) -> None:
    """
    Batch extract Vegas betting lines.

    For backfill_mode: Join with raw betting tables (odds_api, bettingpros)
    For production: Use Phase 3 cascade (current behavior)
    """
    if backfill_mode:
        # Join directly with raw betting tables for historical dates
        query = f"""
        WITH odds_lines AS (
            SELECT DISTINCT
                player_lookup,
                FIRST_VALUE(points_line) OVER (
                    PARTITION BY player_lookup
                    ORDER BY snapshot_timestamp DESC
                ) as vegas_points_line
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = '{game_date}'
              AND bookmaker = 'draftkings'
              AND points_line > 0
        )
        SELECT player_lookup, vegas_points_line, vegas_points_line as vegas_opening_line,
               0.0 as vegas_line_move, 1.0 as has_vegas_line
        FROM odds_lines
        """
    else:
        # Production: Use Phase 3 cascade
        query = f"""..."""  # Current implementation
```

**Pros:**
- Fixes backfill coverage to match baseline (~99%)
- Raw tables have full historical data
- No changes needed to Phase 3

**Cons:**
- Bypasses cascade logic for backfill
- Need to re-run backfill for Nov 2025 - Feb 2026

### Option B: Filter Feature Store to Props-Only Players

Modify backfill mode to only include players who have betting lines:

```python
# In get_players_with_games(), add join:
LEFT JOIN odds_api_player_points_props props
  ON pgs.player_lookup = props.player_lookup AND pgs.game_date = props.game_date
WHERE props.player_lookup IS NOT NULL  -- Only players with lines
```

**Pros:**
- Matches original behavior exactly
- Fewer records = faster processing

**Cons:**
- Loses coverage for non-props players (might want them later)
- Changes semantics of backfill mode

### Recommended Path: Option A

1. Add `backfill_mode` parameter to `_batch_extract_vegas_lines()`
2. Implement raw table join for backfill
3. Pass `backfill_mode` through `batch_extract_all_data()`
4. Re-run feature store backfill for Nov 2025 - Feb 2026
5. Verify coverage >95%

---

## Prevention Mechanisms

### 1. Add Vegas Coverage Check to `/validate-daily`

**File:** `.claude/skills/validate-daily.md`

```sql
-- Priority 2D: Feature Store - Vegas Line Coverage
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_coverage_pct,
  COUNT(*) as total_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33

-- ALERT if vegas_coverage_pct < 80%
```

### 2. Add Historical Drift Check to `/validate-feature-drift`

**File:** `.claude/skills/validate-feature-drift.md`

```sql
-- Compare current month to same month last year
WITH current AS (
  SELECT AVG(CASE WHEN features[OFFSET(25)] > 0 THEN 1 ELSE 0 END) as coverage
  FROM ml_feature_store_v2
  WHERE game_date >= DATE_TRUNC(CURRENT_DATE(), MONTH)
),
baseline AS (
  SELECT AVG(CASE WHEN features[OFFSET(25)] > 0 THEN 1 ELSE 0 END) as coverage
  FROM ml_feature_store_v2
  WHERE game_date >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 1 YEAR)
    AND game_date < DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 11 MONTH)
)
SELECT
  current.coverage as current_coverage,
  baseline.coverage as last_year_coverage,
  baseline.coverage - current.coverage as drift
-- ALERT if drift > 0.20 (20% drop from baseline)
```

### 3. Add Pre-Backfill Validation Check

Before running any backfill, check that sources are compatible:

```python
def validate_backfill_sources(self, game_date: date) -> tuple[bool, str]:
    """
    Validate that player source and feature sources are compatible.
    Returns (is_valid, warning_message)
    """
    # Count players from backfill source
    player_count_query = f"""
    SELECT COUNT(DISTINCT player_lookup) as count
    FROM player_game_summary WHERE game_date = '{game_date}'
    """

    # Count players with Vegas from Phase 3
    vegas_count_query = f"""
    SELECT COUNT(DISTINCT player_lookup) as count
    FROM upcoming_player_game_context
    WHERE game_date = '{game_date}' AND current_points_line > 0
    """

    player_count = self._safe_query(player_count_query).iloc[0]['count']
    vegas_count = self._safe_query(vegas_count_query).iloc[0]['count']

    coverage = vegas_count / player_count if player_count > 0 else 0

    if coverage < 0.5:
        return False, (
            f"WARNING: Vegas coverage only {coverage:.1%} for backfill. "
            f"Players: {player_count}, Vegas: {vegas_count}. "
            f"Consider using raw betting tables for backfill."
        )
    return True, ""
```

### 4. Add Unit Test for Backfill Coverage

```python
def test_backfill_vegas_coverage():
    """Ensure backfill mode maintains >80% Vegas coverage."""
    # Sample historical date
    game_date = date(2025, 1, 15)

    players = extractor.get_players_with_games(game_date, backfill_mode=True)
    extractor.batch_extract_all_data(game_date, players, backfill_mode=True)

    with_vegas = sum(1 for p in players if extractor.get_vegas_lines(p['player_lookup']))
    coverage = with_vegas / len(players)

    assert coverage >= 0.80, f"Backfill Vegas coverage {coverage:.1%} < 80%"
```

---

## Detection for Future Issues

### Automated Checks (Add to CI/CD)

| Check | Frequency | Alert Threshold |
|-------|-----------|-----------------|
| Vegas coverage daily | Daily 6 AM | <80% |
| Vegas coverage drift vs last year | Weekly | >20% drop |
| Player count vs Vegas count ratio | Per backfill | <50% |
| Feature variance check | Per batch | Zero variance on critical features |

### Dashboard Metrics

Add to unified dashboard:
- Vegas line coverage % (7-day rolling)
- Vegas line coverage trend chart
- Comparison to same period last season

### Query for Investigation

```sql
-- Quick diagnosis of Vegas coverage issue
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as total_records,
  COUNTIF(features[OFFSET(25)] > 0) as with_vegas,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as coverage_pct,
  ROUND(AVG(CASE WHEN features[OFFSET(25)] > 0 THEN features[OFFSET(25)] END), 1) as avg_line
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2024-11-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1
ORDER BY 1
```

---

## Lessons Learned

### 1. Cross-Component Changes Need Integration Tests

When changing data sources in one component, test the full pipeline:
- Unit tests verify component works
- Integration tests verify components work TOGETHER

### 2. Coverage Metrics Are As Important As Value Metrics

Pre-write validation catches wrong VALUES but not missing COVERAGE.
Need both:
- Value validation: "Is vegas_line between 0-80?"
- Coverage validation: "Do 80%+ of records have vegas_line?"

### 3. Backfill Mode Should Be Tested Against Production Baseline

Backfill should produce similar results to production, not just "more data":
- Backfill for Dec 2021 → compare to Jan 2022 production
- Check that feature distributions match

### 4. Architectural Changes Need Documentation

The backfill mode and Vegas source changes were both documented individually, but no one documented their interaction. Need:
- "This change affects X, Y, Z components"
- "Compatible with backfill mode: Yes/No"

---

## Next Steps

1. [ ] Implement Option A fix in `feature_extractor.py`
2. [ ] Add `backfill_mode` parameter to `batch_extract_all_data()`
3. [ ] Re-run feature store backfill for Nov 2025 - Feb 2026
4. [ ] Add Vegas coverage check to `/validate-daily`
5. [ ] Add unit test for backfill coverage
6. [ ] Update README with new prevention mechanisms
7. [ ] Verify coverage >95% after fix

---

*Created: 2026-02-01 Session 62*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
