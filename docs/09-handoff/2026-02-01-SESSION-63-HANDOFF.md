# Session 63 Handoff - V8 Hit Rate Investigation

**Date:** 2026-02-01
**Focus:** Deep investigation into V8 hit rate collapse, daily vs backfill code path analysis
**Previous:** Session 62 (Vegas line backfill fix)

---

## Session Summary

Conducted extensive investigation into V8 hit rate collapse. Ruled out team_win_pct as sole cause. Identified **daily orchestration vs backfill code path difference** as likely primary cause - hit rate collapsed on Jan 9, 2026 when daily orchestration started.

---

## Key Findings

### 1. Hit Rate Collapse Correlates with Daily Orchestration Start

| Period | Hit Rate | Source |
|--------|----------|--------|
| Jan 1-7, 2026 | 62-70% | Backfilled |
| **Jan 9+, 2026** | **40-58%** | Daily orchestration |

### 2. Daily vs Backfill Code Differences

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| **Vegas Line Source** | Phase 3 (43% coverage) | Raw tables (95% coverage) |
| **Player Query** | `upcoming_player_game_context` | `player_game_summary` |
| **Completeness Checks** | Full validation | Skipped |
| **Dependency Threshold** | 100 players | 20 players |

### 3. team_win_pct Hypothesis DISPROVEN

Within Nov 2025-Jan 2026, predictions with team_win_pct = 0.5 (matching training) do **WORSE**:

| Month | team_win_pct = 0.5 | Realistic |
|-------|-------------------|-----------|
| Nov 2025 | 42.6% | 58.5% |
| Dec 2025 | 63.3% | 69.2% |
| Jan 2026 | 52.9% | 56.0% |

### 4. Broken Features Found

| Feature | Issue |
|---------|-------|
| pace_score | 100% zeros in ALL periods |
| usage_spike_score | 100% zeros in ALL periods |

---

## Documents Created

| Document | Location |
|----------|----------|
| Investigation Findings | `docs/08-projects/current/feature-quality-monitoring/2026-02-01-SESSION-63-INVESTIGATION-FINDINGS.md` |
| Updated README | `docs/08-projects/current/feature-quality-monitoring/README.md` |

---

## What Still Needs to Be Done

### CRITICAL (Next Session)

1. **Fix daily Vegas source** - Daily mode should query raw betting tables like backfill
   - File: `data_processors/precompute/ml_feature_store/feature_extractor.py`
   - The `_batch_extract_vegas_lines()` function already has backfill mode logic
   - Daily mode needs to use the same logic OR always use backfill_mode=True for Vegas

2. **Verify hypothesis** - Re-run predictions for Jan 9+ using backfill mode
   - If hit rates improve, confirms daily orchestration is the cause

### High Priority

1. Add `feature_source_mode` column to feature store ('daily' or 'backfill')
2. Add `predicted_at` timestamp to predictions table
3. Investigate pace_score and usage_spike_score (100% zeros)
4. Add broken feature detection to /validate-daily

### Medium Priority

1. Create daily vs backfill comparison dashboard
2. Retrain V8 on Nov 2025+ data (clean features)
3. Add feature distribution drift detection

---

## Verification Queries

### Check hit rate by date
```sql
SELECT game_date, COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND prediction_correct IS NOT NULL
  AND game_date >= '2026-01-01'
GROUP BY 1 ORDER BY 1
```

### Check broken features
```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(100.0 * COUNTIF(CAST(features[OFFSET(7)] AS FLOAT64) = 0) / COUNT(*), 1) as pace_zero_pct,
  ROUND(100.0 * COUNTIF(CAST(features[OFFSET(8)] AS FLOAT64) = 0) / COUNT(*), 1) as usage_spike_zero_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-01-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
```

---

## Files Changed (Uncommitted from Session 62)

```
M .claude/skills/validate-daily/SKILL.md
M data_processors/precompute/ml_feature_store/feature_extractor.py
M data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
M docs/08-projects/current/feature-quality-monitoring/README.md
M docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md
M docs/08-projects/current/ml-challenger-training-strategy/README.md
A docs/08-projects/current/feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md
A docs/08-projects/current/feature-quality-monitoring/2026-02-01-SESSION-63-INVESTIGATION-FINDINGS.md
A docs/08-projects/current/ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md
A docs/09-handoff/2026-02-01-SESSION-62-PART2-VEGAS-LINE-FIX.md
A docs/09-handoff/2026-02-01-SESSION-63-HANDOFF.md
```

---

## Key Learnings

1. **Correlation vs Causation** - team_win_pct change correlated with hit rate drop but wasn't the cause
2. **Check code paths** - Daily vs backfill can use different data sources
3. **Timestamps are essential** - No `predicted_at` field made investigation harder
4. **All predictions were backfilled** - Even Jan-Jun 2025 predictions were made in Jan 2026
5. **Broken features can hide** - pace_score and usage_spike_score were 100% zeros but not detected

---

## Next Session Checklist

1. [ ] Commit Session 62+63 changes
2. [ ] Fix daily Vegas source (critical)
3. [ ] Test fix by re-running predictions for a few Jan 9+ dates
4. [ ] Verify hit rates improve
5. [ ] Add monitoring for daily vs backfill differences

---

*Created: 2026-02-01 Session 63*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
