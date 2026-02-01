# Session 67 Handoff - V9 Model Deployed, Experimentation Infrastructure Complete

**Date:** 2026-02-01
**Session:** 67
**Duration:** ~3 hours
**Status:** ✅ V9 DEPLOYED AND PERFORMING WELL

---

## Executive Summary

Session 67 discovered the V8 model's 84% hit rate was fake (data leakage), trained CatBoost V9 on clean current-season data, deployed it to production, and backfilled predictions showing **79.4% high-edge hit rate**. Created comprehensive experimentation infrastructure for ongoing model improvements.

---

## Key Accomplishments

### 1. V9 Model Training & Deployment ✅

| Property | Value |
|----------|-------|
| Model | CatBoost V9 |
| System ID | `catboost_v9` |
| Training | Nov 2, 2025 → Jan 8, 2026 |
| Samples | 9,993 |
| Features | 33 (same as V8) |
| GCS Path | `gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260201_011018.cbm` |

**Backfill Results (Jan 9-31, 2026):**

| Filter | Predictions | Hit Rate |
|--------|-------------|----------|
| All (1+ edge) | 1,502 | 52.8% |
| Premium (3+ edge) | 392 | **65.6%** |
| High Edge (5+) | 141 | **79.4%** |

### 2. Data Quality Verification ✅

Confirmed training and evaluation data have **NO contamination**:

| Feature | Status | Notes |
|---------|--------|-------|
| Rolling averages | ✅ CLEAN | 0.95+ correlation with correct values |
| team_win_pct | ✅ CORRECT | Early Nov 0.5 is legitimate (<5 games) |
| Vegas features | ⚠️ PARTIAL | 26-46% real coverage |
| No data leakage | ✅ VERIFIED | Features 4.9 pts from actual (not 0) |

### 3. Experimentation Infrastructure ✅

Created tools for ongoing model improvement:

| Tool | Purpose |
|------|---------|
| `bin/audit_feature_store.py` | Scan all seasons for data quality issues |
| `ml/experiments/last_season_analysis.py` | Analyze 2024-25 trajectory for retraining insights |
| `ml/experiments/quick_retrain.py` | Monthly retraining with V9 support |
| `ml/backfill_v8_predictions.py` | Backfill with --model-version flag |

### 4. Features Snapshot Fix ✅

All predictions now capture `features_snapshot` with 15 key features for debugging:
- points_avg_last_5, points_avg_last_10, points_avg_season
- vegas_points_line, has_vegas_line
- team_win_pct, fatigue_score, opponent_def_rating
- And more...

---

## IMPORTANT: Experiment vs Backfill Hit Rate Discrepancy

### The Issue

| Source | High-Edge Bets | Hit Rate |
|--------|----------------|----------|
| Experiment (training eval) | 90 | 72.2% |
| Backfill (production data) | 141 | **79.4%** |

### Root Cause

**Different line sources:**
- Experiment uses **BettingPros Consensus** lines
- Backfill/Production uses **Odds API DraftKings** lines (via `current_points_line`)

The DraftKings lines may be more favorable or the sample selection differs.

### Action Required

**Update experiment code** (`ml/experiments/quick_retrain.py`) to use the same line source as production for accurate evaluation:

```python
# Current (BettingPros):
FROM nba_raw.bettingpros_player_points_props
WHERE bookmaker = 'BettingPros Consensus'

# Should be (Odds API DraftKings):
FROM nba_raw.odds_api_player_points_props
WHERE bookmaker = 'draftkings'
```

---

## Last Season Analysis Findings

Analyzed 2024-25 season to predict 2025-26 trajectory:

### Performance Decay Without Retraining

| Eval Period | Initial Model | After Retrain | Improvement |
|-------------|---------------|---------------|-------------|
| February | 56.4% | 55.7% (Jan retrain) | Minimal |
| March | 58.4% | **67.9%** (Feb retrain) | +9.5% |
| April | 53.2% | **68.2%** (Mar retrain) | +15% |
| Playoffs | 50.9% | **68.5%** (Apr retrain) | +17.6% |

### Key Insight

**March retrain is critical** - Hit rate jumps from 53% to 68%. Monthly retraining provides significant benefit, especially before playoffs.

### Retraining Schedule

| Month | Action | Training Window |
|-------|--------|-----------------|
| Feb | Retrain V9 | Nov 2 - Jan 31 |
| Mar | Retrain V9 | Nov 2 - Feb 28 |
| Apr | Retrain V9 | Nov 2 - Mar 31 |
| Playoffs | Retrain V9 | Full season |

---

## Plans & Roadmaps

### Plan 1: Historical Feature Store Cleanup

**Goal:** Clean 2024-25 and 2023-24 data for cross-season training

**Issues Found:**

| Season | team_win_pct | Other Issues |
|--------|--------------|--------------|
| 2024-25 | 100% = 0.5 ❌ | pace_score=0, back_to_back=0 |
| 2023-24 | 100% = 0.5 ❌ | Same issues |

**Fix Steps:**
1. Run `bin/audit_feature_store.py --season 2024-25`
2. Create team_win_pct correction table from game results
3. Backfill feature store with corrected values
4. Verify with audit script

**Documentation:** `docs/08-projects/current/ml-challenger-experiments/HISTORICAL-FEATURE-CLEANUP-PLAN.md`

### Plan 2: Monthly Retraining Strategy

**Current Model:** V9 (CATBOOST_VERSION=v9 default)

**Monthly Process:**
```bash
# 1. Retrain with expanded window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31 \
    --eval-start 2026-01-25 \
    --eval-end 2026-01-31

# 2. If better, upload and deploy
gsutil cp models/catboost_retrain_*.cbm gs://nba-props-platform-models/catboost/v9/
./bin/deploy-service.sh prediction-worker

# 3. Backfill recent predictions
PYTHONPATH=. python ml/backfill_v8_predictions.py --start-date 2026-02-01 --end-date 2026-02-07
```

### Plan 3: Experiment Roadmap

20+ experiments documented in `ML-EXPERIMENTATION-ROADMAP.md`:

**Batch 1: Training Window**
- 30-day, 60-day, 90-day rolling windows
- Full season comparison

**Batch 2: Recency Weighting**
- 90-day and 180-day half-life decay

**Batch 3: Data Sources**
- DraftKings-only training
- Multi-book with indicator feature

**Batch 4: Seasonal Patterns**
- Late season specialist
- Back-to-back specialist

**Batch 5: Feature Engineering**
- Momentum features
- Enhanced matchup features

---

## Files Changed

### New Files

| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v9.py` | V9 prediction system |
| `bin/audit_feature_store.py` | Feature quality scanner |
| `ml/experiments/last_season_analysis.py` | Season trajectory analysis |
| `docs/08-projects/current/ml-challenger-experiments/README.md` | Project summary |
| `docs/08-projects/current/ml-challenger-experiments/V9-PROMOTION-PLAN.md` | Deployment checklist |
| `docs/08-projects/current/ml-challenger-experiments/HISTORICAL-FEATURE-CLEANUP-PLAN.md` | Cleanup strategy |
| `docs/08-projects/current/ml-challenger-experiments/ML-EXPERIMENTATION-ROADMAP.md` | Experiment plans |

### Modified Files

| File | Changes |
|------|---------|
| `predictions/worker/worker.py` | V9 support, features_snapshot for all predictions |
| `ml/backfill_v8_predictions.py` | --model-version flag for V8/V9 |
| `CLAUDE.md` | ML Models section with V9 info |

---

## Commits (18 total)

```
11df6105 feat: Update backfill script to support V9 model
59ff2ecc fix: Add GCS model loading support to CatBoost V9
7a02393b feat: Add ML experimentation roadmap and last season analysis script
d963d2a8 fix: Add features_snapshot to ALL predictions, fix catboost_v9 condition
3a964256 docs: Update project docs with V9 model information
40cd139b feat: Add CatBoost V9 prediction system with current season training
90e0d888 feat: Add ML feature store audit script and historical cleanup plan
c74c209c docs: Add data quality audit confirming training data is clean
a47b0d3e docs: Add V9 promotion plan with full implementation checklist
ec59ad35 docs: Add Session 67 ML experiment results - V9 candidate found
```

---

## Verification Commands

```bash
# Check V9 is deployed
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"CATBOOST_VERSION=v9"' --limit=5

# Check V9 predictions
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*), MIN(game_date), MAX(game_date)
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
GROUP BY 1"

# Check hit rates
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 'High Edge'
       WHEN ABS(predicted_points - current_points_line) >= 3 THEN 'Premium'
       ELSE 'Standard' END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.system_id = 'catboost_v9'
  AND p.game_date >= '2026-01-09'
  AND p.current_points_line IS NOT NULL
GROUP BY 1"

# Run feature audit
PYTHONPATH=. python bin/audit_feature_store.py --start 2025-11-01 --end 2026-01-31 --check-leakage
```

---

## Next Session Priorities

### Priority 1: Fix Experiment Code
Update `ml/experiments/quick_retrain.py` to use Odds API DraftKings lines instead of BettingPros Consensus for accurate evaluation.

### Priority 2: February Retrain
Retrain V9 with expanded window (Nov 2 - Jan 31) and evaluate.

### Priority 3: Historical Cleanup
Fix team_win_pct for 2024-25 season to enable cross-season training.

### Priority 4: More Experiments
Run experiments from the roadmap (training windows, recency weighting).

---

## For Next Claude Session

**IMPORTANT:** Use agents liberally to study the documentation and code:

```
# Study the experimentation infrastructure
Task(subagent_type="Explore", prompt="Read docs/08-projects/current/ml-challenger-experiments/ to understand V9 model and experiment plans")

# Understand the V9 implementation
Task(subagent_type="Explore", prompt="Read predictions/worker/prediction_systems/catboost_v9.py and understand how it differs from V8")

# Check experiment code for line source issue
Task(subagent_type="Explore", prompt="Read ml/experiments/quick_retrain.py and identify where BettingPros lines are used that should be Odds API")
```

**Key Documents to Read:**
1. `docs/08-projects/current/ml-challenger-experiments/README.md` - Project overview
2. `docs/08-projects/current/ml-challenger-experiments/ML-EXPERIMENTATION-ROADMAP.md` - All experiment plans
3. `docs/08-projects/current/ml-challenger-experiments/HISTORICAL-FEATURE-CLEANUP-PLAN.md` - Feature store cleanup

---

## Session Statistics

| Metric | Value |
|--------|-------|
| Commits | 18 |
| Files Created | 7 |
| Files Modified | 5 |
| Predictions Backfilled | 6,465 |
| High-Edge Hit Rate | 79.4% |
| Premium Hit Rate | 65.6% |

---

*Created: Session 67, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
