# Vegas Line Feature Drift Incident

**Date Discovered:** 2026-02-01 (Session 61)
**Severity:** CRITICAL
**Status:** INVESTIGATING

---

## Executive Summary

The `vegas_line` feature in the ML feature store dropped from **99.4% coverage** in Jan 2025 to **43.4% coverage** in Jan 2026. This directly caused the V8 model hit rate to collapse from 70-76% to 48-67%.

---

## Impact

### Model Performance Degradation

| Period | Hit Rate | MAE | vegas_line Coverage |
|--------|----------|-----|---------------------|
| Jan 2025 | 70-76% | 3.8-4.3 | **99.4%** |
| Jan 2026 | 48-67% | 4.4-5.9 | **43.4%** |

### High-Edge Hit Rate Collapse

| Edge Bucket | Jan 2025 | Jan 2026 | Drop |
|-------------|----------|----------|------|
| 0-2 (low) | 60.3% | 52.2% | -8% |
| 2-5 (medium) | 72.3% | 55.3% | -17% |
| **5+ (high)** | **86.1%** | **60.5%** | **-26%** |

---

## Root Cause Analysis

### Timeline of Coverage Degradation

| Month | Feature Store vegas_line | Phase 3 current_points_line |
|-------|--------------------------|----------------------------|
| Oct 2025 | N/A (bootstrap) | 16.8% |
| Nov 2025 | 57.9% | 25.4% |
| Dec 2025 | 32.5% | 44.1% |
| Jan 2026 | 43.4% | 44.7% |
| Feb 2026 | 0.0% | 0.0% |
| **Jan 2025** | **99.4%** | N/A |

### Data Flow

```
Raw Props Data (Odds API / BettingPros)
         ↓
Phase 3: upcoming_player_game_context.current_points_line
         ↓
Phase 4: player_daily_cache
         ↓
Feature Store: ml_feature_store_v2.features[25] (vegas_points_line)
```

### Key Finding

The issue originates in **Phase 3 context** - only 25-45% of player records have `current_points_line` populated.

Possible causes:
1. **Player matching failures** - player_lookup not matching between raw props and context
2. **Scraper coverage gaps** - Odds API only covers ~300 unique players/month
3. **BettingPros data not flowing** - BettingPros has more players but may not be used
4. **Timing issues** - Lines scraped after context is generated

---

## Why Wasn't This Detected Earlier?

### Validation Gap Analysis

| Skill | What It Checks | Would Catch This? |
|-------|----------------|-------------------|
| `/validate-daily` | Orchestrator health, phase flow | ❌ No |
| `/validate-historical` | player_game_summary fields | ❌ No |
| `/validate-scraped-data` | Raw data GCS vs BigQuery | ❌ No |
| `/hit-rate-analysis` | Hit rates (symptom, not cause) | ⚠️ Symptom only |

**Missing validation**: No check compares current feature store quality to historical baseline.

---

## Detection Enhancement

### New Skill: `/validate-feature-drift`

Created in Session 61: `.claude/skills/validate-feature-drift.md`

Key checks:
1. **Compare to last season** - vegas_line should be >95% if last season was 99%
2. **Weekly trend** - Catch gradual degradation (>20% week-over-week drop = alert)
3. **Value distribution drift** - Feature values shouldn't shift significantly

### Add to `/validate-daily`

```sql
-- Priority 2D: Feature Store Quality (NEW)
SELECT ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33

-- Alert if <80%
```

---

## Investigation Status

### Completed
- [x] Identified coverage drop (99.4% → 43.4%)
- [x] Linked to Phase 3 context (source of issue)
- [x] Created `/validate-feature-drift` skill
- [x] Documented in experiment plan

### In Progress
- [ ] Find WHY Phase 3 coverage is low for 2025-26 season
- [ ] Check if data source changed (BettingPros vs Odds API)
- [ ] Determine fix needed (scraper, matcher, or extractor)

## Confirmed Root Cause

### Feature Store Record Selection Changed

| Period | Records/Day | With Vegas Line | Mode |
|--------|-------------|-----------------|------|
| Jan 2025 | 130-190 | 99%+ | **Selective** - only players with props |
| Jan 2026 | 300-500+ | ~40% | **All players** - includes those without props |

The 2025-26 season feature store includes ALL players, not just those with betting lines. This dilutes the vegas_line coverage.

### Why Did This Change?

The feature store code has two modes:
1. **Production mode**: Uses `upcoming_player_game_context` with prop lines
2. **Backfill mode**: Uses `player_game_summary` with `has_prop_line = FALSE`

```python
# feature_extractor.py line 162
FALSE AS has_prop_line,  -- No betting lines for backfill
CAST(NULL AS FLOAT64) AS current_points_line
```

The 2025-26 season appears to have been generated in backfill mode, which sets vegas_line to 0 for all records.

---

## Next Steps

### Option A: Fix Backfill Mode
1. Modify backfill mode to join with betting data
2. Re-run feature store backfill for 2025-26 season
3. Verify vegas_line coverage improves

### Option B: Filter Predictions to Only Players with Props
1. Don't train/predict on players without betting lines
2. This matches the original behavior
3. Fewer predictions but higher quality

### Option C: Handle Missing Vegas Line in Model
1. Add fallback when vegas_line is missing
2. Use player's scoring average as proxy
3. Train model to handle missing feature

### Recommended Path
**Option A** - Fix backfill mode to include betting data, then re-run for 2025-26 season.

---

## Prevention Measures

### Short-term
1. Add feature drift check to `/validate-daily` Priority 2
2. Weekly manual `/validate-feature-drift` check
3. Alert on >10% coverage drop from baseline

### Medium-term
1. Automated daily BigQuery scheduled query for feature coverage
2. Slack alert when vegas_line < 80%
3. Dashboard widget for feature store health

### Long-term
1. Feature store quality scoring in pipeline
2. Block predictions if critical features missing
3. Fallback feature values from alternative sources

---

## Related Files

- `.claude/skills/validate-feature-drift.md` - New validation skill
- `docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md` - Experiment plan with findings
- `data_processors/precompute/ml_feature_store/` - Feature store processor

---

*Created: 2026-02-01 Session 61*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
