# Historical Data Validation Findings - January 26, 2026

## Purpose

This document summarizes the findings from a comprehensive historical data validation run covering the last 7 days (2026-01-19 to 2026-01-25). The validation revealed critical data integrity issues that require remediation.

**Request for Opus**: Review these findings and provide a detailed remediation plan with prioritized steps, code changes needed, and verification procedures.

---

## Executive Summary

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Spot Check Accuracy | 32.2% | ≥95% | :red_circle: CRITICAL |
| Analytics Coverage | 60-75% | ≥95% | :red_circle: CRITICAL |
| Usage Rate Coverage | 0-54% | ≥90% | :red_circle: CRITICAL |
| Raw Data Completeness | Missing 2 days | 100% | :red_circle: CRITICAL |

**Overall Assessment**: Data integrity is severely compromised. Multiple P1 issues affecting predictions across a 21+ day cascade window.

---

## Issue 1: Missing Raw Data (Jan 22-23)

### Problem Statement

NBA.com raw data (`nba_raw.nbac_gamebook_player_stats`) is completely missing for January 22-23, 2026.

### Evidence

```
| game_date  | raw_records | analytics_records | notes                    |
|------------|-------------|-------------------|--------------------------|
| 2026-01-23 | 0           | 281               | Analytics from BDL only  |
| 2026-01-22 | 0           | 282               | Analytics from BDL only  |
```

- Schedule shows 8 games each day (games were played)
- BallDontLie (`nba_raw.bdl_player_boxscores`) has data: 282 records (Jan 22), 281 records (Jan 23)
- Analytics was built from BDL fallback, not primary NBA.com source

### Root Cause Hypothesis

NBA.com scraper (`nbac_gamebook`) failed for these dates. The pipeline fell back to BallDontLie data for analytics processing.

### Cascade Impact

- **Affected window**: Jan 23 through Feb 13 (21 days for L10+ features)
- **Affected players**: ~180 per day
- **Affected predictions**: ~1,500+ across cascade window

### Questions for Opus

1. Is NBA.com data still scrapeable for these dates, or has the window closed?
2. Should we accept BDL as the source of truth for these dates, or attempt re-scrape?
3. How do we verify data consistency between BDL-sourced and NBAC-sourced records?

---

## Issue 2: Usage Rate Calculation Broken

### Problem Statement

`usage_rate` is NULL for the vast majority of records, despite team stats existing in `team_offense_game_summary`.

### Evidence

```
| game_date  | total_records | has_usage | usage_pct |
|------------|---------------|-----------|-----------|
| 2026-01-25 | 139           | 49        | 35.3%     |
| 2026-01-24 | 183           | 99        | 54.1%     |
| 2026-01-23 | 281           | 0         | 0.0%      |
| 2026-01-22 | 282           | 0         | 0.0%      |
| 2026-01-21 | 156           | 0         | 0.0%      |
| 2026-01-20 | 147           | 0         | 0.0%      |
| 2026-01-19 | 227           | 0         | 0.0%      |
```

### Root Cause Analysis

The `source_team_last_updated` field in `player_game_summary` is NULL for most records:

```
| game_date  | missing_team_join | missing_usage_with_minutes |
|------------|-------------------|----------------------------|
| 2026-01-25 | 0                 | 90                         |
| 2026-01-24 | 0                 | 26                         |
| 2026-01-23 | 281               | 159                        |
| 2026-01-22 | 282               | 165                        |
| 2026-01-21 | 156               | 156                        |
| 2026-01-20 | 147               | 147                        |
| 2026-01-19 | 227               | 197                        |
```

**Key finding**: Team stats exist in `team_offense_game_summary` for all games. The join succeeds when queried manually:

```sql
-- This works - team stats CAN be joined
SELECT p.game_id, p.team_abbr, t.team_abbr as team_stats_team
FROM player_game_summary p
JOIN team_offense_game_summary t ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr
WHERE p.game_date = '2026-01-22'
-- Returns matching records
```

But `source_team_last_updated` is still NULL, meaning the Phase 3 pipeline is not persisting the team stats join.

### Hypothesis

The `player_game_summary` processor:
1. Creates player records first
2. Should update records with team stats later (setting `source_team_last_updated`)
3. Step 2 is not happening, OR the timestamp field is not being set even when the join succeeds

### Files to Investigate

- `shared/processors/player_game_summary_processor.py` - Main processor logic
- Any scheduled job that updates team stats joins after initial processing

### Questions for Opus

1. How is `source_team_last_updated` supposed to be populated?
2. Is there a separate process that enriches player records with team stats?
3. Should usage_rate be calculated at write time or as a materialized view?

---

## Issue 3: Incomplete Analytics Coverage

### Problem Statement

Analytics (`player_game_summary`) contains only 60-75% of raw records for most dates.

### Evidence

```
| game_date  | raw_records | analytics_records | coverage_pct |
|------------|-------------|-------------------|--------------|
| 2026-01-25 | 212         | 139               | 65.6%        |
| 2026-01-24 | 243         | 183               | 75.3%        |
| 2026-01-21 | 247         | 156               | 63.2%        |
| 2026-01-20 | 245         | 147               | 60.0%        |
| 2026-01-19 | 275         | 227               | 82.5%        |
| 2026-01-18 | 192         | 147               | 76.6%        |
| 2026-01-17 | 195         | 272               | 139.5% (!)   |
| 2026-01-16 | 210         | 119               | 56.7%        |
```

**Note**: Jan 17 has MORE analytics records than raw (139.5%), suggesting duplicate processing or multiple sources being merged.

### Hypothesis Options

1. **Game ID mismatch**: Raw uses different game_id format than analytics expects
2. **Player filtering**: Some players filtered out (DNP, <1 minute, etc.)
3. **Processing failures**: Phase 3 partially fails and doesn't process all records
4. **Deduplication issues**: Raw has duplicates that get filtered

### Questions for Opus

1. What is the expected coverage ratio? Is ~65% normal (DNP players filtered)?
2. Why does Jan 17 have more analytics than raw?
3. Should we compare at game level to identify which games have gaps?

---

## Issue 4: Rolling Average Mismatches

### Problem Statement

Spot checks show 10-60% discrepancy between cached rolling averages and recalculated values.

### Evidence (from spot_check_data_accuracy.py)

```
Player: clintcapela (2026-01-23)
  - points_avg_last_10 mismatch: 10.00%
  - ML Feature Store points_avg_last_5 mismatch: 57.14%
  - ML Feature Store points_avg_last_10 mismatch: 27.78%

Player: simonefontecchio (2026-01-20)
  - points_avg_last_5 mismatch: 61.90%
  - points_avg_last_10 mismatch: 27.50%
  - ML Feature Store mismatch: 52-74%
  - Cache mismatch: 27-62%
```

### Hypothesis

1. Missing games from Jan 22-23 (or earlier) not included in rolling average calculation
2. Cache was built with incomplete data and never refreshed
3. Different date semantics: `cache_date = game_date - 1` may be misapplied

### Questions for Opus

1. What is the correct formula for L5/L10 averages?
2. How should `cache_date` relate to `game_date`?
3. Should we regenerate all cache data for the affected cascade window?

---

## Data Architecture Context

### Pipeline Phases

```
Phase 1: Raw Scraping → nba_raw.nbac_gamebook_player_stats (primary)
                      → nba_raw.bdl_player_boxscores (fallback)

Phase 2: Team Stats  → nba_analytics.team_offense_game_summary

Phase 3: Analytics   → nba_analytics.player_game_summary
                       (should join team stats, calculate usage_rate)

Phase 4: Precompute  → nba_precompute.player_daily_cache
                       (rolling averages L5, L10)

Phase 5: ML Features → nba_predictions.ml_feature_store_v2
                       (features for predictions)

Phase 6: Predictions → nba_predictions.player_prop_predictions
```

### Key Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `nba_raw.nbac_gamebook_player_stats` | Primary raw player stats | game_id, player_lookup, points, minutes |
| `nba_raw.bdl_player_boxscores` | Fallback raw stats | game_id, player_lookup, points, minutes |
| `nba_analytics.team_offense_game_summary` | Team totals per game | game_id, team_abbr, fg_attempts, turnovers |
| `nba_analytics.player_game_summary` | Enriched player stats | game_id, player_lookup, usage_rate, source_team_last_updated |
| `nba_precompute.player_daily_cache` | Rolling averages | player_lookup, cache_date, points_avg_last_5/10 |

### Important Semantics

- `cache_date = game_date - 1` (cache is built day before the game)
- `usage_rate = 100 * ((FGA + 0.44 * FTA + TOV) * (Team Minutes / 5)) / (Minutes * (Team FGA + 0.44 * Team FTA + Team TOV))`

---

## Remediation Options

### Option A: Surgical Fix (Faster, Riskier)

1. Re-scrape Jan 22-23 from NBA.com (if still available)
2. Fix `source_team_last_updated` population in Phase 3
3. Regenerate cache for Jan 19 - Feb 13 cascade window
4. Verify with spot checks

### Option B: Full Rebuild (Slower, Safer)

1. Investigate and fix all root causes first
2. Re-run Phase 3 for entire affected period (Jan 9 - Jan 25)
3. Re-run Phase 4 for cascade window (Jan 19 - Feb 13)
4. Re-run Phase 5 to regenerate ML features
5. Full validation

### Option C: Hybrid (Recommended?)

1. Accept BDL data for Jan 22-23 as source of truth
2. Fix Phase 3 team stats join (code fix required)
3. Backfill Phase 3 for Jan 19 - Jan 25
4. Regenerate Phase 4 cache for Jan 19 - Feb 13
5. Spot check validation

---

## Specific Questions for Opus Review

1. **Priority ordering**: Which issue should we fix first? (Raw data vs usage_rate vs analytics coverage)

2. **Root cause for usage_rate**: What code change is needed to populate `source_team_last_updated`?

3. **BDL vs NBAC**: Should we accept BDL data for Jan 22-23 or attempt re-scrape?

4. **Analytics coverage**: Is 60-75% coverage expected (DNP filtering) or a bug?

5. **Cascade window**: What is the correct date range to regenerate? (L5=5 days, L10=10 days, ML features use what window?)

6. **Verification strategy**: After remediation, how do we verify the fix is complete?

7. **Prevention**: What monitoring/alerts should we add to catch this earlier?

---

## Appendix: Raw Query Results

### Spot Check Full Output

```
======================================================================
SPOT CHECK REPORT: Data Accuracy Verification
======================================================================
Date: 2026-01-26 20:11:34
Samples: 15 player-date combinations

======================================================================
SUMMARY
======================================================================
Total checks: 90
  Passed:  26 (28.9%)
  Failed:  7 (7.8%)
  Skipped: 57 (63.3%)
  Errors:  0 (0.0%)

Samples: 11/15 passed (73.3%)

======================================================================
FAILURES
======================================================================

1. clintcapela (2026-01-23)
   - points_avg_last_10 mismatch: 10.00%
   - usage_rate is NULL but should be calculated
   - ML Feature Store points_avg_last_5 mismatch: 57.14%
   - ML Feature Store points_avg_last_10 mismatch: 27.78%
   - Cache points_avg_last_10 mismatch: 10.00%

2. rjbarrett (2026-01-23)
   - usage_rate is NULL but should be calculated

3. brandonmiller (2026-01-22)
   - usage_rate is NULL but should be calculated

4. aarongordon (2026-01-22)
   - usage_rate is NULL but should be calculated

5. dannywolf (2026-01-19)
   - points_avg_last_5 mismatch: 6.98%
   - points_avg_last_10 mismatch: 19.72%
   - ML Feature Store points_avg_last_5 mismatch: 19.57%
   - ML Feature Store points_avg_last_10 mismatch: 22.35%
   - Cache points_avg_last_5 mismatch: 6.98%
   - Cache points_avg_last_10 mismatch: 19.72%

6. simonefontecchio (2026-01-20)
   - points_avg_last_5 mismatch: 61.90%
   - points_avg_last_10 mismatch: 27.50%
   - ML Feature Store points_avg_last_5 mismatch: 52.94%
   - ML Feature Store points_avg_last_10 mismatch: 74.51%
   - Cache points_avg_last_5 mismatch: 61.90%
   - Cache points_avg_last_10 mismatch: 27.50%
```

### Schedule vs Raw vs Analytics Comparison

```
| game_date  | scheduled | raw | analytics | pct   | status           |
|------------|-----------|-----|-----------|-------|------------------|
| 2026-01-25 | 8         | 212 | 139       | 65.6% | INCOMPLETE       |
| 2026-01-24 | 7         | 243 | 183       | 75.3% | INCOMPLETE       |
| 2026-01-23 | 8         | 0   | 281       | N/A   | RAW MISSING      |
| 2026-01-22 | 8         | 0   | 282       | N/A   | RAW MISSING      |
| 2026-01-21 | 7         | 247 | 156       | 63.2% | INCOMPLETE       |
| 2026-01-20 | 7         | 245 | 147       | 60.0% | INCOMPLETE       |
| 2026-01-19 | 9         | 275 | 227       | 82.5% | INCOMPLETE       |
```

---

## Files Modified in This Session

None - this was a read-only validation session.

## Files to Investigate for Remediation

1. **`data_processors/analytics/player_game_summary/player_game_summary_processor.py`** - Main processor with usage_rate calculation
   - Lines 1199-1226: usage_rate calculation (requires team_fg_attempts, team_ft_attempts, team_turnovers)
   - Lines 559-582: Team stats join query (team_stats CTE)
   - The `source_team_last_updated` field is NOT being set in the processor (not found in code)

2. **`tests/processors/analytics/player_game_summary/test_usage_rate_calculation.py`** - Test file documenting the expected behavior
   - Line 203-218: Test `test_team_stats_join_creates_source_timestamp()` - confirms `source_team_last_updated` SHOULD be set
   - Tests were created 2026-01-25 "in response to Jan 2026 data quality issues where usage_rate was 0% coverage"

3. **`scripts/backfill_player_game_summary.py`** - Backfill script for Phase 3
4. **`scripts/regenerate_player_daily_cache.py`** - Cache regeneration for Phase 4
5. **`scripts/spot_check_data_accuracy.py`** - Validation script (used for verification)

## Key Code Finding: Missing source_team_last_updated Assignment

The test file expects `source_team_last_updated` to be set:

```python
# From test_usage_rate_calculation.py line 203-218
def test_team_stats_join_creates_source_timestamp(self):
    """
    Test that team stats join creates source_team_last_updated timestamp.

    This is used to verify that the processor actually joined team stats,
    not just failed silently with NULLs.
    """
    team_stats_joined = True
    source_team_last_updated = pd.Timestamp.now() if team_stats_joined else None
    assert source_team_last_updated is not None
```

**But** searching the processor code (`player_game_summary_processor.py`) shows NO assignment to `source_team_last_updated`. This field is expected in the schema but never populated by the processor.

**This is likely the root cause of the usage_rate issue** - the processor calculates usage_rate correctly when team stats are available in the JOIN, but doesn't set the timestamp field that tracks whether the join succeeded.

---

*Document created: 2026-01-26*
*Validation run by: Claude Sonnet via /validate-historical skill*
