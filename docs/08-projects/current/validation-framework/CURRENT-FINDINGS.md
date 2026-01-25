# Current Findings - Jan 25, 2026 (Updated)

**Investigation Date:** 2026-01-25 ~7:30 AM PST (Morning Validation)
**Context:** Daily orchestration validation after 2-day Firestore permission outage recovery

---

## Executive Summary

| Metric | Status | Value | Notes |
|--------|--------|-------|-------|
| **Schedule** | OK | 7 games | All finalized |
| **Boxscores** | CRITICAL | 6/7 games (85.7%) | GSW@MIN missing |
| **Analytics** | WARNING | 6 games, 183 players | Missing 1 game |
| **Features** | WARNING | 181 features, 100% bronze | Quality regression |
| **Predictions** | OK | 486 predictions | Across 7 games |
| **Grading** | WARNING | 124/486 (25.5%) | Blocked by boxscores |

**Overall Status:** Pipeline operational but with 1 missing game and low grading rate.

---

## Validation Tool Results

### 1. Daily Data Completeness (`daily_data_completeness.py --days 3`)

```
Date         Expected      BDL  Analytics  Grading
------------------------------------------------------------
2026-01-24          7    85.7%      85.7%    42.9%
2026-01-23          8   100.0%     100.0%    87.5%
2026-01-22          8   100.0%     100.0%    87.5%
```

**Analysis:** Jan 24 has gaps across all phases due to 1 missing game.

### 2. Workflow Health (`workflow_health.py --hours 48`)

```
Summary: 6 checks
  ERROR: 1 (phase_transitions - none in 48h)
  WARNING: 1 (processor_completions - 2 low completion rate)
  OK: 4
```

**Problem Processors:**
- `nbac_player_boxscore` - 1 start, 0 completions, 1 error
- `bdl_player_box_scores_scraper` - 1 start, 0 completions

**Analysis:** Boxscore scrapers encountering issues for GSW@MIN game.

### 3. Phase Transition Health (`phase_transition_health.py --days 3`)

```
2026-01-24 - PARTIAL (Bottleneck: schedule)
   schedule -> boxscores:      85.7% (6/7 games)
   boxscores -> analytics:     87.6% (183/209 players)
   analytics -> features:      98.9% (181/183 players)
   features -> predictions:   141.3% (65/46 high-quality)
   predictions -> grading:     79.3% (23/29 predictions)

2026-01-23 - OK (all phases green)

2026-01-22 - PARTIAL (Bottleneck: features)
   features -> predictions:    45.8% (88/192 features)
```

### 4. Pipeline Doctor (`daily_pipeline_doctor.py --days 3 --show-fixes`)

**Issues Found:**
| Severity | Issue | Count |
|----------|-------|-------|
| CRITICAL | Boxscore gaps | 1 game |
| WARNING | Low prediction coverage | 2 dates (62.6% avg) |
| WARNING | Feature quality regression | 2 dates |

### 5. Comprehensive Health Check (`comprehensive_health_check.py --date 2026-01-24`)

```
Summary: 9 checks
  CRITICAL: 1 (feature_quality - 64.43 avg, threshold 65)
  ERROR: 4
  OK: 4
```

**Failing Checks:**
- `feature_quality`: Critically low at 64.43 avg (threshold: 65)
- `rolling_window_completeness`: L7D=73.2%, L14D=65.6%
- `grading_lag`: 79.3% (23/29 predictions)
- `cross_phase_consistency`: Missing boxscores
- `prediction_funnel`: Low quality rate 25.4%

---

## Detailed Issue Analysis

### Issue #1: Missing Boxscore - GSW@MIN (CRITICAL)

**Game Details:**
| Field | Value |
|-------|-------|
| Game | Golden State Warriors @ Minnesota Timberwolves |
| Game ID (NBA.com) | 0022500644 |
| Game Code | 20260124/GSWMIN |
| Game Status | 3 (Final) |
| Scores | NULL/NULL (not populated) |

**Symptoms:**
- Schedule shows game as Final but no scores
- BDL boxscore table has 6 games, missing this one
- Analytics has 183 players (should be ~210 for 7 games)

**Root Cause:**
The `nbac_player_boxscore` processor failed with error:
```
Max decode/download retries reached: 8
```

Currently in retry queue:
```
Status: pending
First Failure: 2026-01-25 12:37:36
Next Retry: 2026-01-25 12:52:36
Retry Count: 0
```

**Fix:**
```bash
python bin/backfill/bdl_boxscores.py --date 2026-01-24
```

### Issue #2: Feature Quality Regression (WARNING)

**Feature Quality by Date:**
| Date | Total | Bronze | Silver | High |
|------|-------|--------|--------|------|
| 2026-01-24 | 181 | 181 (100%) | 0 | 0 |
| 2026-01-23 | 281 | 147 (52%) | 134 (48%) | 0 |
| 2026-01-22 | 283 | 147 (52%) | 136 (48%) | 0 |

**Analysis:**
- All Jan 24 features are "bronze" tier (lowest quality)
- Previous days had ~48% silver tier features
- Indicates incomplete rolling window data

**Impact:**
- Lower confidence predictions
- More predictions filtered out by quality gates
- Reduced production coverage

**Fix:**
```bash
python bin/backfill/phase4.py --date 2026-01-24
```

### Issue #3: Low Grading Rate (WARNING)

**Grading Status:**
| Date | Predictions | Graded | Rate |
|------|-------------|--------|------|
| 2026-01-24 | 486 | 124 | 25.5% |
| 2026-01-23 | 5193 | 1294 | 24.9% |
| 2026-01-22 | 609 | 449 | 73.7% |

**Root Cause:** Grading requires boxscore data. Missing GSW@MIN boxscore prevents grading for that game.

**Fix:** After boxscores are backfilled:
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-24
```

---

## Pipeline Event Log Analysis

**Recent Events (Last 48 Hours):**
| Event Type | Processor | Count | Last Event |
|------------|-----------|-------|------------|
| processor_start | bdl_player_box_scores_scraper | 1 | 2026-01-25 15:02:12 |
| error | nbac_player_boxscore | 1 | 2026-01-25 12:37:32 |
| processor_complete | MLFeatureStoreProcessor | 80 | 2026-01-25 04:57:58 |
| processor_complete | PlayerGameSummaryProcessor | 90 | 2026-01-25 03:21:06 |

**Analysis:** Pipeline is actively processing but boxscore scraper has stalled.

---

## Failed Processor Queue

| Processor | Phase | Status | Error | Next Retry |
|-----------|-------|--------|-------|------------|
| nbac_player_boxscore | phase_2 | pending | Max decode/download retries reached: 8 | 2026-01-25 12:52:36 |

**Analysis:** Auto-retry system is functioning. The processor will retry automatically.

---

## Game ID Mapping Discovery

During investigation, discovered that schedule and boxscore tables use different game ID formats:

| Source | Format | Example |
|--------|--------|---------|
| NBA.com Schedule | Numeric | `0022500644` |
| BDL Boxscores | String with teams | `20260124_GSW_MIN` |

**Impact:** Some validation scripts may be joining incorrectly, causing false-positive gaps.

**Recommendation:** Use `v_game_id_mappings` view for cross-table joins.

---

## Recovery Actions (Ordered)

### Priority 1: Fix Boxscore Gap
```bash
# Backfill missing boxscores for Jan 24
python bin/backfill/bdl_boxscores.py --date 2026-01-24
```

### Priority 2: Re-run Downstream Processing
```bash
# After boxscores complete, run Phase 3
python bin/backfill/phase3.py --date 2026-01-24

# Then Phase 4 for feature quality improvement
python bin/backfill/phase4.py --date 2026-01-24
```

### Priority 3: Complete Grading
```bash
# Run grading backfill
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-24
```

### Priority 4: Validate Recovery
```bash
# Re-run validation
python bin/validation/daily_pipeline_doctor.py --days 3
python bin/validation/comprehensive_health_check.py --date 2026-01-24
```

---

## Comparison with Previous Session (Jan 25 7:00 PM)

| Metric | Previous | Current | Change |
|--------|----------|---------|--------|
| Jan 24 Boxscores | 6/7 | 6/7 | No change |
| Jan 24 Analytics | Missing | 6 games | Improved |
| Jan 23 Grading | 1/8 games | 87.5% | Fixed |
| Failed Queue | Empty | 1 processor | New issue |

**Progress:** Jan 23 is now mostly recovered. Jan 24 still has the GSW@MIN gap.

---

## Next Steps

- [ ] Monitor auto-retry of `nbac_player_boxscore` processor
- [ ] If auto-retry fails, manually run boxscore backfill
- [ ] After boxscores complete, trigger Phase 3-4 cascade
- [ ] Run grading backfill
- [ ] Morning validation Jan 26 to confirm full recovery
- [ ] Investigate why GSW@MIN specifically failed (scraper issue? API issue?)

---

*Last Updated: 2026-01-25 07:30 AM PST*
