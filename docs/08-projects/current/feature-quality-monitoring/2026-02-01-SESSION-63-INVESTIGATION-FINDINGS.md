# Session 63 Investigation Findings

**Date:** 2026-02-01
**Focus:** Deep investigation into V8 hit rate collapse
**Status:** Root cause likely identified - Daily vs Backfill code path difference

---

## Executive Summary

V8 hit rate collapsed from 72.8% (Jan 2025) to 55.5% (Jan 2026). After extensive investigation, we identified that **the decline correlates with the start of daily orchestration on Jan 9, 2026**. Daily orchestration uses different code paths than backfill, particularly for Vegas line extraction.

---

## Key Finding: Daily Orchestration Start Date

| Period | Hit Rate | Likely Source |
|--------|----------|---------------|
| Jan 1-7, 2026 | 62-70% | Backfilled |
| **Jan 9+, 2026** | **40-58%** | Daily orchestration |

The hit rate dropped sharply on **Jan 9, 2026** - the same time daily orchestration started running.

---

## Issues Discovered During Investigation

### 1. Daily vs Backfill Code Path Differences (CRITICAL)

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| **Vegas Line Source** | Phase 3 (43% coverage) | Raw tables (95% coverage) |
| **Player Query** | `upcoming_player_game_context` | `player_game_summary` |
| **Dependency Threshold** | 100 players | 20 players |
| **Per-Player Completeness** | Full validation | Skipped |

**The Vegas line source difference is the most likely cause of the decline.**

### 2. Feature Store Issues Found

| Issue | Impact | Period Affected |
|-------|--------|-----------------|
| team_win_pct = 0.5 for 100% | Model trained on this | 2021-Jun 2025 |
| team_win_pct fixed (realistic) | Model sees new values | Nov 2025+ |
| pace_score = 0 for 100% | Broken feature | ALL time |
| usage_spike_score = 0 for 100% | Broken feature | ALL time |
| vegas_line coverage drop | 99% → 43% | Nov 2025+ (feature store) |

### 3. Prediction Table Timestamp Issues

- All predictions graded in Jan 2026 (even Jan-Jun 2025 games)
- No `predicted_at` timestamp to distinguish when predictions were made
- No way to know if features were regenerated after predictions

### 4. Feature Version Changes

| Period | Feature Count | Version |
|--------|---------------|---------|
| Jan-Jun 2025 | 33 | v2_33features |
| Nov 2025+ | 37 | v2_37features (mostly) |

Feature order is the same, but extra features added at end.

### 5. Counter-Intuitive Finding

Within Nov 2025-Jan 2026, predictions with team_win_pct = 0.5 (matching training) do **WORSE** than realistic values:

| Month | team_win_pct = 0.5 | Realistic |
|-------|-------------------|-----------|
| Nov 2025 | 42.6% | 58.5% |
| Dec 2025 | 63.3% | 69.2% |
| Jan 2026 | 52.9% | 56.0% |

This suggests team_win_pct mismatch is NOT the primary cause, but may be correlated with the real cause.

---

## Hypotheses Tested

### Hypothesis 1: team_win_pct Distribution Mismatch
- **Status:** PARTIALLY DISPROVEN
- **Evidence:** Records with team_win_pct = 0.5 do worse, not better
- **Conclusion:** Not the primary cause, but may be correlated

### Hypothesis 2: Vegas Line Coverage Drop
- **Status:** PARTIALLY CONFIRMED
- **Evidence:** Feature store shows 43% coverage vs 99% in training
- **BUT:** Actual betting line used at inference is similar to Jan 2025

### Hypothesis 3: Daily vs Backfill Code Path
- **Status:** LIKELY PRIMARY CAUSE
- **Evidence:**
  - Hit rate drop correlates with Jan 9 (daily orchestration start)
  - Daily mode uses Phase 3 for Vegas (43% coverage)
  - Backfill mode uses raw tables (95% coverage)
- **Conclusion:** Most likely cause - needs further validation

---

## Validation Improvements Needed

### 1. Add Timestamps to Track Data Lineage

```sql
-- Proposed new fields for ml_feature_store_v2
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN feature_generated_at TIMESTAMP,
ADD COLUMN feature_source_mode STRING,  -- 'daily' or 'backfill'
ADD COLUMN orchestration_run_id STRING;

-- Proposed new fields for prediction_accuracy
ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN predicted_at TIMESTAMP,
ADD COLUMN feature_generated_at TIMESTAMP,
ADD COLUMN feature_source_mode STRING;
```

### 2. Add Feature Distribution Monitoring

```sql
-- Daily check for feature anomalies
SELECT
  game_date,
  -- Key features should have realistic distributions
  ROUND(100.0 * COUNTIF(features[OFFSET(7)] = 0) / COUNT(*), 1) as pct_pace_zero,
  ROUND(100.0 * COUNTIF(features[OFFSET(8)] = 0) / COUNT(*), 1) as pct_usage_spike_zero,
  ROUND(100.0 * COUNTIF(features[OFFSET(24)] = 0.5) / COUNT(*), 1) as pct_team_win_half,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as pct_has_vegas
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
-- ALERT if pct_pace_zero > 50% or pct_usage_spike_zero > 50%
```

### 3. Add Code Path Indicator to Logs

```python
# In ML feature store processor
logger.info(
    f"Processing {analysis_date}",
    extra={
        "mode": "daily" if not self.is_backfill_mode else "backfill",
        "vegas_source": "phase3" if not self.is_backfill_mode else "raw_tables",
        "player_source": self._get_player_source(),
    }
)
```

### 4. Add Daily vs Backfill Comparison Check

```sql
-- Compare feature coverage between daily and backfill for same date
SELECT
  feature_source_mode,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_coverage
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = @date
GROUP BY 1
-- ALERT if daily vegas_coverage < backfill vegas_coverage by > 10%
```

---

## Broken Features Detected

### pace_score (feature index 7)
- **Status:** 100% zeros in ALL periods
- **Impact:** Feature provides no signal
- **Root Cause:** Unknown - needs investigation
- **Action:** Add to validation, investigate calculator

### usage_spike_score (feature index 8)
- **Status:** 100% zeros in ALL periods
- **Impact:** Feature provides no signal
- **Root Cause:** Unknown - needs investigation
- **Action:** Add to validation, investigate calculator

### team_win_pct (feature index 24)
- **Status:** Was 0.5 for 100% of records (2021-Jun 2025), now realistic
- **Impact:** Model trained on constant value
- **Root Cause:** Bug in feature calculator (fixed Nov 2025)
- **Action:** Consider retraining model on recent data

---

## Action Items

### Immediate (Session 63+)

1. [ ] Fix daily orchestration to use raw Vegas tables (like backfill)
2. [ ] Add `feature_source_mode` column to feature store
3. [ ] Add `predicted_at` timestamp to predictions table
4. [ ] Re-run predictions for Jan 9+ using backfill mode to verify hypothesis

### Short-term

1. [ ] Investigate why pace_score and usage_spike_score are always 0
2. [ ] Add broken feature detection to /validate-daily
3. [ ] Create daily vs backfill comparison dashboard
4. [ ] Document code path differences

### Medium-term

1. [ ] Retrain V8 on Nov 2025+ data (clean features)
2. [ ] Add feature distribution drift detection
3. [ ] Create automated alerts for hit rate drops

---

## Related Documents

- [V8 Training Distribution Mismatch](../ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md)
- [Vegas Line Root Cause Analysis](./2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md)
- [Experiment Plan](../ml-challenger-experiments/EXPERIMENT-PLAN.md)

---

*Created: 2026-02-01 Session 63*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
