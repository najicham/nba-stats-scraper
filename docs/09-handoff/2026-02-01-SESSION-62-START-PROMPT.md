# Session 62 Start Prompt - Feature Store Fix & ML Experiments

**Date:** 2026-02-01
**Previous Sessions:** 61 (Feature drift discovery), 49 (Comprehensive feature investigation), 48 (Pre-write validation)
**Priority:** CRITICAL - Fix feature store before running ML experiments

---

## Quick Context

**The V8 model isn't broken - the data is.**

The `vegas_line` feature (player's points prop line, e.g., "LeBron O/U 25.5 points") dropped from **99.4% coverage** in Jan 2025 to **43.4%** in Jan 2026. This directly caused hit rates to collapse:

| Edge Bucket | Jan 2025 | Jan 2026 | Drop |
|-------------|----------|----------|------|
| High (5+) | **86.1%** | **60.5%** | **-26%** |

**Root Cause:** 2025-26 season feature store was generated in **backfill mode** which includes ALL players (300-500/day) but sets `has_prop_line=FALSE`. Last season only included players with props (130-190/day).

---

## Priority 1: Fix Feature Store (CRITICAL)

### The Problem

```python
# feature_extractor.py line 162 (backfill mode)
FALSE AS has_prop_line,  -- No betting lines for backfill
CAST(NULL AS FLOAT64) AS current_points_line
```

### Options

**Option A (Recommended):** Modify backfill mode to join with betting data
1. Update `data_processors/precompute/ml_feature_store/feature_extractor.py`
2. Add join to `nba_raw.bettingpros_player_points_props` or `nba_raw.odds_api_player_points_props`
3. Re-run feature store generation for Nov 2025 - Feb 2026
4. Verify vegas_line coverage improves to >95%

**Option B:** Filter to only players with props (fewer predictions, matches original behavior)
1. Add `WHERE has_prop_line = TRUE` filter
2. Fewer predictions but higher quality

**Option C:** Train model to handle missing vegas_line
1. Add fallback when vegas_line is missing
2. Most complex, least likely to help

### Verification Query

```sql
-- Check vegas_line coverage after fix
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
```

**Expected after fix:** vegas_line_pct >95% (matching Jan 2025 baseline)

---

## Priority 2: Run ML Experiments (After Fix)

Six experiments planned in `docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md`:

| ID | Hypothesis | Training Data |
|----|------------|---------------|
| `exp_20260201_dk_only` | DK-trained better for DK bets | Odds API DK (~100K) |
| `exp_20260201_dk_bettingpros` | More BP DK data helps | BettingPros DK (~330K) |
| `exp_20260201_recency_90d` | 90-day weighting adapts faster | All + 90d decay |
| `exp_20260201_recency_180d` | 180-day better balance | All + 180d decay |
| `exp_20260201_current_szn` | Current season patterns | Oct 2025 - Jan 2026 (~40K) |
| `exp_20260201_multi_book` | Learn book-specific biases | All sources (~500K+) |

**Start with:** `exp_20260201_dk_only` (simplest change from V8)

### Experiment Infrastructure

Existing tools:
- `ml/experiments/train_walkforward.py` - Walk-forward validation
- `ml/experiment_registry.py` - Experiment tracking
- `.claude/skills/model-experiment/` - Experiment skill (review before use)

---

## Priority 3: Other Feature Quality TODOs

From Sessions 48-49 investigation:

### High Priority

| Task | Status | Notes |
|------|--------|-------|
| Fix `usage_spike_score` | ❌ | `projected_usage_rate = NULL` upstream |
| Fix `pace_score` | ❌ | `opponent_pace_last_10 = NULL` upstream |
| Investigate `games_in_last_7_days` bug | ❌ | Values up to 24 (impossible) since Dec 2025 |

### Medium Priority

| Task | Status | Notes |
|------|--------|-------|
| Add vegas_line check to `/validate-daily` | ❌ | Add to Priority 2D |
| Expand drift detector to 37 features | ❌ | Currently monitors key features only |
| Deploy Phase 2 with heartbeat fix | ❌ | Part 1 Session 61 |
| Run heartbeat cleanup script | ❌ | Part 1 Session 61 |

### Low Priority

| Task | Status | Notes |
|------|--------|-------|
| Integrate `schedule_context_calculator` | ❌ | File exists but not called |
| Clean up 50 staging tables | ❌ | Infrastructure audit |
| Set up GCS lifecycle policies | ❌ | Infrastructure audit |
| Configure budget alerts | ❌ | Infrastructure audit |

---

## Key Files

| Purpose | File |
|---------|------|
| Feature extractor (FIX HERE) | `data_processors/precompute/ml_feature_store/feature_extractor.py` |
| Vegas line incident doc | `docs/08-projects/current/feature-quality-monitoring/2026-02-01-VEGAS-LINE-DRIFT-INCIDENT.md` |
| Experiment plan | `docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md` |
| Feature drift validation | `.claude/skills/validate-feature-drift.md` |
| Feature quality README | `docs/08-projects/current/feature-quality-monitoring/README.md` |
| Session 61 handoff | `docs/09-handoff/2026-02-01-SESSION-61-HANDOFF.md` |

---

## Validation Commands

### Check current vegas_line coverage
```bash
bq query --use_legacy_sql=false "
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct,
  COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1"
```

### Compare to Phase 3 context
```bash
bq query --use_legacy_sql=false "
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(100.0 * COUNTIF(current_points_line > 0) / COUNT(*), 1) as with_line
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2025-10-01'
GROUP BY 1 ORDER BY 1"
```

### Run feature drift validation
```
/validate-feature-drift
```

---

## Success Criteria

1. **Feature store fixed:** vegas_line coverage >95% for Nov 2025 - Feb 2026
2. **First experiment complete:** `exp_20260201_dk_only` trained and evaluated
3. **Comparison done:** V8 vs experiment hit rates on Jan 2026 holdout

---

## Clarifications from Previous Session

**Q: What is vegas_line?**
A: The player's points prop line (e.g., "LeBron O/U 25.5 points"), NOT the team spread. Feature index 25 in the ML feature store.

**Q: Why didn't we detect this sooner?**
A: No validation compared current feature store quality to historical baseline. Created `/validate-feature-drift` skill to catch this going forward.

**Q: Is Oct 2025 feature store empty a bug?**
A: No. Oct 21 - Nov 3 is "bootstrap period" (first 14 days of season). Feature store correctly starts Nov 4.

---

*Created: 2026-02-01*
*For Session 62 continuation*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
