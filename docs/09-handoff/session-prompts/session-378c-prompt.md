# Session 378c — XGBoost Crisis + Ultra Bug + Phase 6 Auto-Export

## CRITICAL: Best Bets Poisoned by XGBoost Model

### What Happened

The XGBoost model `xgb_v12_noveg_train1221_0208` (deployed Session 378, DMatrix fix in 378b) is **catastrophically miscalibrated**:

- **134 predictions, ALL UNDER**, average edge -9.06 (range -5.5 to -13.5)
- Predicts every player ~9 points below their line (e.g., Kawhi 16.9 on a 29.5 line)
- Session 378b already flagged "avg predicted 4.9 pts" but it was not disabled

### Damage

The original 3 CatBoost/LightGBM best bets picks for March 1 were:

| Pick | Edge | Signals | Model |
|------|------|---------|-------|
| Kawhi Leonard UNDER 29.5 | 5.4 | 5 (model_health, high_edge, edge_spread, home_under, extended_rest_under) | catboost_v12_noveg_train0110_0220 |
| Cam Thomas OVER 12.5 | 5.1 | 6 (model_health, high_edge, edge_spread, cold_streak, volatile_scoring, line_rising) | catboost_v12_noveg_train0110_0220 |
| Luke Kennard OVER 7.5 | 3.8 | 4 (model_health, high_scoring_env, low_line, line_rising) | lgbm_v12_noveg_train1102_0209 |

These were written to BQ at 16:12:42 UTC. Then at **16:30-16:38**, XGBoost predictions were written to `player_prop_predictions`. At **16:40**, Phase 6 re-ran and overwrote the picks with 7 all-UNDER XGBoost picks. The GCS export (`signal-best-bets/2026-03-01.json`) now contains the broken picks.

### Why XGBoost Won Selection

The aggregator selects the highest-edge prediction per player across all models (ROW_NUMBER by effective_edge). XGBoost's inflated edges (8.8-12.6) overwhelm CatBoost's legitimate edges (3.5-5.4). There is **no model-level sanity check** to prevent a single broken model from dominating all selections.

### Root Cause

The XGBoost model's predictions are on a different scale. Its `evaluation_mae: 4.99` in the registry suggests it may be trained correctly but predicting on a different basis (e.g., deviation from line rather than absolute points, or a feature mismatch at inference time). The Session 378b prompt noted this but investigation wasn't completed.

### Fix Plan (Priority 1)

1. **Disable XGBoost in model_registry** (BQ):
```sql
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET enabled = FALSE, status = 'blocked'
WHERE model_id = 'xgb_v12_noveg_train1221_0208';
```

2. **Re-trigger Phase 6 export** to restore correct CatBoost/LightGBM picks:
```bash
# Trigger Phase 6 signal-best-bets export for today
gcloud functions call phase6-export --region=us-west2 --project=nba-props-platform \
  --data='{"export_types": ["signal-best-bets"], "target_date": "2026-03-01"}'
```

3. **Verify** the restored picks match the original 3 (Kawhi, Cam Thomas, Kennard).

---

## BUG: Ultra Bets Classification Not Firing

### Symptoms

Pick angles include "ULTRA BET" text (e.g., `"ULTRA BET: V12+vegas OVER, edge >= 5 — 100.0% HR (18 picks)"` for Cam Thomas), but `ultra_tier = false` and `ultra_criteria = []` in BQ.

### Expected Behavior

- **Cam Thomas OVER 12.5** (edge 5.1, source_model_family=`v12_mae`):
  - Should match `v12_over_edge_5plus` (v12 + OVER + edge >= 5.0)
  - Should match `v12_edge_4_5plus` (v12 + edge >= 4.5)
- **Kawhi Leonard UNDER 29.5** (edge 5.4, source_model_family=`v12_mae`):
  - Should match `v12_edge_4_5plus` (v12 + edge >= 4.5)

### Last Working

Feb 20-21: LeBron James (OVER, edge 6.5) and Desmond Bane (OVER, edge 7.7) both had `ultra_tier=true` with correct criteria. Same aggregator code, same ultra_bets.py.

### Where to Look

The ultra classification happens in `aggregator.py` lines 482-487:
```python
from ml.signals.ultra_bets import classify_ultra_pick
for pick_entry in scored:
    ultra_criteria = classify_ultra_pick(pick_entry)
    pick_entry['ultra_tier'] = len(ultra_criteria) > 0
    pick_entry['ultra_criteria'] = ultra_criteria
```

The `_check_criterion()` in `ultra_bets.py` (line 76) reads `source_model_family` from the pick dict and checks `.startswith('v12')`. The value IS `v12_mae` which startswith `v12` = True.

**Possible causes:**
1. The XGBoost re-run at 16:40 may have run `classify_ultra_pick()` with XGBoost picks (source_model_family=`xgb_v12_noveg_mae`), which does NOT start with `v12`. This would explain ultra_tier=false for the XGBoost picks.
2. If there was a period between Feb 21 and Mar 1 with no picks (no games), the bug may not exist — it could be purely the XGBoost overwrite.
3. The pick_angle_builder may have been referencing ultra criteria from a DIFFERENT code path than the aggregator's classification.

**Verification step:** After restoring CatBoost picks (by disabling XGBoost + re-exporting), check if ultra_tier is correctly set on the restored picks. If yes, the ultra bug is a consequence of the XGBoost overwrite. If no, there's a real bug.

### Key Files
- `ml/signals/ultra_bets.py` — Classification logic (lines 76-94)
- `ml/signals/aggregator.py` — Where classify_ultra_pick is called (lines 482-487)
- `ml/signals/pick_angle_builder.py` — Where ultra angles are generated (line 261+)

---

## Harden UNDER 21.5 — Correctly Filtered

The session prompt expected 4 picks, but Harden was correctly filtered. Investigation confirmed:

- Harden's best prediction: edge -3.51 UNDER 21.5 from `catboost_v12_vw015_train1201_1231`
- **Only 1 model agreed UNDER** — most models predicted HOLD near the line
- With only ~1 signal (model_health), he failed the **signal count filter** (minimum 3 required)
- His line of 21.5 falls in a middle zone (not star ≥25, not starter 15-20) where directional filters don't apply
- The filter stack worked correctly here

---

## Model Health for Sourcing Models

| Model | 7d HR | 14d HR | Best Bets 14d | Notes |
|-------|-------|--------|----------------|-------|
| catboost_v12_train0104_0208 | — | — | — | **NOT in model_performance_daily** — new model, no tracking data yet |
| catboost_v12_noveg_train0110_0220 | — | — | — | **NOT in model_performance_daily** — new model, no tracking data yet |
| lgbm_v12_noveg_train1102_0209 | 71.4% (N=7) | 50-71.4% | — | Best fleet model, OVER 80% / UNDER 50% |
| catboost_v12_vw015_train1201_1231 | 66.7% (N=3) | 66.7% (N=3) | 100% (N=1) | Tiny sample, OVER only |

**Gap:** Two of the three sourcing models (v12_train0104_0208 and v12_noveg_train0110_0220) have NO model_performance_daily records. This means the model HR-weighted selection introduced in Session 365 defaults to 50% (weight 0.91) for these models, which is correct behavior but means we're flying blind on their actual performance.

---

## Signal Firing Verification

### Cam Thomas OVER 12.5 — 6 signals (ALL VERIFIED)
1. **model_health** — Always fires
2. **high_edge** — edge 5.1 ≥ 5.0 ✓
3. **edge_spread_optimal** — edge 5.1 + confidence in valid band ✓
4. **scoring_cold_streak_over** — OVER + prop_under_streak ≥ 3 + points_avg ≥ 10 ✓ (regression after cold streak)
5. **volatile_scoring_over** — OVER + scoring CV ≥ 0.50 ✓ (high variance scorer)
6. **line_rising_over** — OVER + prop_line_delta ≥ 0.5 ✓ (market agrees player trending up)

### Luke Kennard OVER 7.5 — 4 signals (ALL VERIFIED)
1. **model_health** — Always fires
2. **high_scoring_environment_over** — OVER + implied_team_total ≥ 120 ✓ (LAL game)
3. **low_line_over** — OVER + line < 12 ✓ (7.5 line, conservative book pricing)
4. **line_rising_over** — OVER + prop_line_delta ≥ 0.5 ✓

### Kawhi Leonard UNDER 29.5 — 5 signals (VERIFIED, one to confirm)
1. **model_health** — Always fires
2. **high_edge** — edge 5.4 ≥ 5.0 ✓
3. **edge_spread_optimal** — edge 5.4 + confidence in valid band ✓
4. **home_under** — UNDER + HOME + line ≥ 15 ✓ (LAC home vs NOP)
5. **extended_rest_under** — UNDER + rest_days ≥ 4 + line ≥ 15 — **Need to verify** Kawhi had 4+ days rest before Mar 1. Given Kawhi's load management history, likely correct.

---

## Feature Request: Phase 6 Auto-Re-Export on BQ Data Changes

User asked: "If we change the DB data that is tied to Phase 6, it will export it the next day."

### Current Phase 6 Triggers
1. **Phase 5→6 orchestrator** — fires after Phase 5 predictions complete
2. **Cloud Scheduler** — `phase6-hourly-trends` and other scheduled exports
3. **Manual** — `gcloud functions call phase6-export`

### Problem Statement
When manual DB changes are made (e.g., grading corrections, model registry updates, filter changes), the Phase 6 export doesn't automatically re-run. The stale JSON in GCS persists until the next natural trigger.

### Proposed Solutions

**Option A: Daily Phase 6 "sweep" scheduler (RECOMMENDED)**
- Add a Cloud Scheduler job that runs Phase 6 export at a fixed time (e.g., 3:30 PM ET, after manual morning work is done)
- Simple, reliable, no BQ audit log complexity
- Session 378b already proposed this: `phase6-afternoon-reexport`
- Covers the common case: morning pipeline runs, operator makes adjustments, afternoon re-export captures them

**Option B: BQ audit log trigger**
- Cloud Function triggered by BQ audit logs for specific tables (signal_best_bets_picks, model_registry, etc.)
- More complex, but truly event-driven
- Risk of trigger loops (Phase 6 writes to BQ → triggers itself)
- Would need debouncing logic

**Option C: Mark-and-sweep pattern**
- When manual changes are made, write a "dirty" flag to a Firestore doc or BQ table
- A periodic checker (every 30 min) checks the flag and triggers Phase 6 if set
- Middle ground between A and B

**Recommendation:** Start with Option A (afternoon scheduler). It's the simplest, handles 90% of cases, and was already planned in Session 378b.

---

## Systemic Improvements to Consider

### 1. Model Sanity Guard in Aggregator
**Problem:** A single miscalibrated model can dominate all best bets selections via inflated edges.
**Fix:** Add a guard in the aggregator that blocks any model where >90% of predictions are the same direction:
```python
# In aggregator.py, before per-player selection
model_direction_counts = defaultdict(lambda: {'OVER': 0, 'UNDER': 0})
for pred in predictions:
    model_direction_counts[pred['system_id']][pred['recommendation']] += 1
blocked_models = set()
for model_id, counts in model_direction_counts.items():
    total = counts['OVER'] + counts['UNDER']
    if total > 10:
        over_pct = counts['OVER'] / total
        if over_pct > 0.90 or over_pct < 0.10:
            blocked_models.add(model_id)
            logger.warning(f"Model sanity guard: blocking {model_id} ({over_pct:.0%} OVER)")
```

### 2. Phase 6 Overwrite Protection
**Problem:** Re-exports DELETE existing picks before INSERT, losing previously correct picks.
**Fix:** When re-exporting, check if existing picks are from a different model family than the new run. If so, log a warning and potentially skip the re-export.

### 3. XGBoost Calibration Investigation
**Problem:** XGBoost may be predicting on a different scale (deviation-from-line vs absolute points).
**Fix:** Before re-enabling XGBoost:
- Compare XGBoost predictions vs CatBoost predictions for the same players
- Check if adding XGBoost's predicted value to the line gives a reasonable absolute points estimate
- If it's a scale issue, add a post-prediction transformation

### 4. Model Performance Tracking for New Models
**Problem:** Two sourcing models (v12_train0104_0208, v12_noveg_train0110_0220) have no performance tracking data.
**Fix:** Verify `post_grading_export` is generating `model_performance_daily` entries for all models producing predictions. May need to backfill.

### 5. Ultra Bets — Update Backtest Window
**Problem:** BACKTEST_END is still `2026-02-21` in `ultra_bets.py`. Live HR queries start after this date.
**Fix:** After verifying ultra classification works (post-XGBoost fix), consider updating the backtest window with fresh data to get more robust HR estimates.

---

## Quick Reference: Key Commands

```bash
# 1. Disable XGBoost
bq query --use_legacy_sql=false "
UPDATE \`nba-props-platform.nba_predictions.model_registry\`
SET enabled = FALSE, status = 'blocked'
WHERE model_id = 'xgb_v12_noveg_train1221_0208'"

# 2. Re-trigger Phase 6 export
gcloud functions call phase6-export --region=us-west2 --project=nba-props-platform \
  --data='{"export_types": ["signal-best-bets"], "target_date": "2026-03-01"}'

# 3. Verify restored picks
bq query --use_legacy_sql=false "
SELECT player_name, recommendation, line_value, edge, source_model_family, ultra_tier
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
WHERE game_date = '2026-03-01'
ORDER BY ABS(CAST(edge AS FLOAT64)) DESC"

# 4. Check GCS export
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/2026-03-01.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for p in d.get('picks', []):
    print(f'{p.get(\"player\")} {p.get(\"direction\")} {p.get(\"line\")} edge={p.get(\"edge\")}')"

# 5. Check ultra classification after restore
bq query --use_legacy_sql=false "
SELECT player_name, ultra_tier, ultra_criteria
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
WHERE game_date = '2026-03-01' AND ultra_tier = TRUE"

# 6. Add afternoon re-export scheduler (Phase 6 auto-re-export)
# See session-378b-prompt.md Priority 3 for full command
```

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | Best bets selection algorithm, ultra classification call (lines 482-487) |
| `ml/signals/ultra_bets.py` | Ultra bet criteria and classification logic |
| `ml/signals/signal_annotator.py` | Signal firing conditions |
| `ml/signals/pick_angle_builder.py` | Pick angle generation (ultra angles line 261+) |
| `predictions/worker/prediction_systems/catboost_monthly.py` | Shadow model loader (XGBoost support lines 317-486) |
| `shared/config/cross_model_subsets.py` | Model family classification (xgb_v12_noveg_mae line 121) |
| `ml/signals/model_direction_affinity.py` | Direction affinity blocking (XGBoost mapped line 79) |

## Season Context

**Record:** 77-39 (66.4%), +32.25 units. ATH +33.52 (Feb 22). FLAT regime.

Tonight: 11 games scheduled. Games NOT yet started (all game_status=1 as of session time).
