# Pipeline Error Catalog

Living document of recurring failure modes, their root causes, detection, and prevention.
Each entry added when a failure is first diagnosed. Updated when it recurs.

**How to use:** When the pipeline produces 0 picks or behaves unexpectedly, scan this catalog
before investigating from scratch. Most failures are recurrences of known patterns.

---

## Error 001 — Registry Status Stale After Manual Model Enable

**Category:** Fleet / Registry
**Severity:** HIGH — causes 0 picks silently
**First seen:** 2026-03-21 (Session 477)

**Symptom:**
- 0 best-bet picks on game days
- `player_prop_predictions` has rows for enabled models
- `model_bb_candidates` has 0 rows

**Root cause:**
The decay detection CF (`decay-detection`, 11 AM ET) sets `status='blocked'` when a model
degrades. The CF is **one-directional** — it never automatically unblocks. When a user
manually re-enables a model (or a model HR recovers), the registry `status` stays `'blocked'`
until manually updated. The BB pipeline's per-model aggregator explicitly skips BLOCKED models.

**Detection:**
```sql
SELECT model_id, status, enabled
FROM nba_predictions.model_registry
WHERE enabled = TRUE AND status = 'blocked';
```
Now also caught by canary: **"Registry Blocked Models"** (fires every 30 min).

**Fix:**
```bash
./bin/unblock-model.sh MODEL_ID       # Update status + refresh cache
```

**Prevention added (Session 477):**
- Canary check `check_registry_blocked_enabled` fires immediately when `enabled=TRUE, status='blocked'`
- `./bin/unblock-model.sh` script standardizes the fix procedure

**Recurrence risk:** HIGH — decay CF runs daily and will re-block any model that dips below threshold.
After the canary was added, future occurrences will alert within 30 minutes.

---

## Error 002 — BB Pipeline Never Triggered (Phase 5 Stall)

**Category:** Orchestration
**Severity:** HIGH — causes 0 picks silently
**First seen:** 2026-03-20 (Session 477 diagnosis)

**Symptom:**
- `player_prop_predictions` has rows for today
- `model_bb_candidates` has 0 rows for today
- `signal_best_bets_picks` has 0 rows for today
- `phase_completions` shows Phase 4 done but no Phase 5 entry

**Root cause:**
Phase 4 → Phase 5 handoff failed silently. The Phase 5 orchestrator received no trigger
(or the trigger was dropped), so the BB pipeline never ran. Predictions exist but were
never evaluated for best bets.

**Detection:**
```sql
-- Phase 4 done but no BB candidates 2+ hours later
SELECT p.phase4_completed_at, b.candidate_count
FROM (
  SELECT MAX(completed_at) as phase4_completed_at
  FROM nba_orchestration.phase_completions
  WHERE game_date = CURRENT_DATE()
    AND phase_name IN ('phase4', 'ml_feature_store', 'precompute')
) p
CROSS JOIN (
  SELECT COUNT(*) as candidate_count
  FROM nba_predictions.model_bb_candidates
  WHERE game_date = CURRENT_DATE()
) b
WHERE p.phase4_completed_at IS NOT NULL
  AND b.candidate_count = 0
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), p.phase4_completed_at, HOUR) >= 2;
```
Now also caught by canary: **"BB Pipeline Today"** (fires every 30 min).

**Fix:**
```bash
# Trigger Phase 6 export (re-runs BB pipeline via signal-best-bets exporter)
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["signal-best-bets"], "target_date": "YYYY-MM-DD"}'

# If model_bb_candidates also empty (pipeline truly never ran), trigger Phase 5:
gcloud pubsub topics publish nba-phase5-predictions-complete \
  --project=nba-props-platform \
  --message='{"game_date": "YYYY-MM-DD", "trigger_type": "manual"}'
```

**Prevention added (Session 477):**
- Canary check `check_bb_candidates_today` alerts when Phase 4 done but 0 candidates after 2h

**Recurrence risk:** MEDIUM — Pub/Sub messages can be dropped under load or during CF cold starts.

---

## Error 003 — Model Recovery Not Surfaced (Silent Block After HR Recovery)

**Category:** Fleet / Monitoring
**Severity:** MEDIUM — causes reduced pick volume
**First seen:** 2026-03-20 (Session 477 diagnosis)

**Symptom:**
- `model_performance_daily` shows model HEALTHY (e.g., 62.5% 7d HR)
- `model_registry` still shows `status='blocked'`
- Model generating predictions but contributing 0 picks to BB pipeline

**Root cause:**
The decay detection CF runs one-directional (HEALTHY→BLOCKED). When a blocked model's
HR recovers, there is no automated alert or unblock. The discrepancy between
`model_performance_daily.model_state = HEALTHY` and `model_registry.status = blocked`
can persist indefinitely without human intervention.

**Detection:**
```sql
WITH latest_perf AS (
  SELECT system_id, model_state, rolling_hr_7d, n_graded_7d
  FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY system_id ORDER BY game_date DESC) as rn
    FROM nba_predictions.model_performance_daily
    WHERE game_date >= CURRENT_DATE() - 7
  ) WHERE rn = 1
)
SELECT mr.model_id, lp.model_state, lp.rolling_hr_7d, lp.n_graded_7d
FROM nba_predictions.model_registry mr
JOIN latest_perf lp ON mr.model_id = lp.system_id
WHERE mr.enabled = TRUE AND mr.status = 'blocked'
  AND lp.model_state = 'HEALTHY' AND lp.rolling_hr_7d >= 52.4 AND lp.n_graded_7d >= 10;
```
Now also caught by canary: **"Model Recovery Gap"** (fires every 30 min).

**Fix:**
```bash
./bin/unblock-model.sh MODEL_ID
```

**Prevention added (Session 477):**
- Canary check `check_model_recovery_gap` alerts when a model is unblockable

**Recurrence risk:** HIGH — decay CF runs daily. Any model that dips below threshold and
then recovers will hit this pattern. Now auto-detected within 30 min of recovery.

---

## Error 004 — CatBoost Edge Collapse in Tight Markets

**Category:** Fleet / Model Architecture
**Severity:** HIGH — causes 0 picks (no edge for BB pipeline)
**First seen:** 2026-02-xx, diagnosed 2026-03-21 (Session 476)

**Symptom:**
- CatBoost models have `avg_abs_diff < 1.2` (vs LGBM at 1.5-2.0+)
- Correlation between `predicted_points` and `current_points_line` >= 0.97
- All picks filtered by edge floor or real_sc gate

**Root cause:**
CatBoost uses symmetric trees + ordered boosting. The feature `line_vs_season_avg`
(= `vegas_line - season_avg`) allows CatBoost to reconstruct the Vegas line internally,
creating pred-line correlation 0.974-0.989. This is an **architectural issue**,
not a training data issue. Tighter markets (Vegas MAE < 4.5) amplify the effect.
Changing training windows does NOT fix this.

**Detection:**
```sql
SELECT system_id, ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_abs_diff
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;
-- CatBoost models < 1.2 = collapsed. LGBM models should be 1.5+.
```

**Fix:**
- Use Feb-trained models (trained before market tightened, `avg_abs_diff >= 1.5`)
- Shift fleet to LGBM/XGBoost heavy when Vegas MAE < 5.0
- Disable collapsed CatBoost models (avg_abs_diff < 1.0)

**Long-term fix (post-season):**
Remove `line_vs_season_avg` from v12_noveg feature set. Replace with
`deviation_from_season_avg_abs` or drop entirely. Must validate with walk-forward.

**Prevention status:** PARTIAL — known architectural issue, no automated detection yet.
Add `avg_abs_diff < 1.2` alert to canary for all enabled CatBoost models.

**Recurrence risk:** CERTAIN every tight-market period (~late Feb through end of season).

---

## Error 005 — New Model Registered but No Predictions

**Category:** Fleet / Worker Cache
**Severity:** MEDIUM — reduces pick volume
**First seen:** 2026-03-21 (Session 477)

**Symptom:**
- Model appears in `model_registry` with `enabled=TRUE, status='active'`
- 0 rows in `player_prop_predictions` for this `system_id` for today/recent days

**Root cause:**
The prediction worker loads its model list from the registry at startup, with a 4-hour TTL cache.
After a new model is registered, the worker doesn't pick it up until the cache expires or is
manually refreshed. New models also need their GCS artifact to be accessible.

**Detection:**
```sql
SELECT mr.model_id
FROM nba_predictions.model_registry mr
WHERE mr.enabled = TRUE AND mr.status = 'active'
  AND NOT EXISTS (
    SELECT 1 FROM nba_predictions.player_prop_predictions p
    WHERE p.system_id = mr.model_id
      AND p.game_date >= CURRENT_DATE() - 1
  );
```

**Fix:**
```bash
./bin/refresh-model-cache.sh --verify   # Force worker cache refresh
# New model predictions will appear in next pipeline run (~next game day)
```

**Prevention added (Session 477):**
- `./bin/unblock-model.sh` includes worker cache refresh as standard step
- After any registry change, refresh-model-cache.sh should be run immediately

**Recurrence risk:** LOW after cache refresh procedure is followed. HIGH if procedure skipped.

---

## Error 006 — Grading Lag Blocking league_macro_daily Updates

**Category:** Grading / Analytics
**Severity:** MEDIUM — stale MAE data, blocks retrain gate evaluation
**First seen:** 2026-03-16 (Session 476), recurring through 2026-03-21

**Symptom:**
- `league_macro_daily` has no rows for N recent days
- `model_performance_daily` and `signal_health_daily` stuck at same date
- Vegas MAE recovery trend invisible (can't evaluate weekly-retrain CF resume gate)

**Root cause:**
The grading pipeline runs after game results are available (~9 AM ET next day).
If the grading service fails or games are missing box scores, the grading gap grows.
`league_macro_daily`, `model_performance_daily`, and `signal_health_daily` all depend
on graded predictions.

**Detection:**
```sql
SELECT MAX(game_date) as last_graded_date,
       DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_behind
FROM nba_predictions.prediction_accuracy
WHERE prediction_correct IS NOT NULL;
```

**Fix:**
Trigger grading backfill for missing dates via `/grade-date` endpoint on grading service:
```bash
for date in YYYY-MM-DD ...; do
  curl -X POST https://nba-grading-service-.../grade-date -d "{\"game_date\": \"$date\"}"
done
```

**Prevention status:** Existing `grading-gap-detector` CF runs daily at 9 AM ET. Alerts in #nba-alerts.
If gap > 3 days, escalate to manual backfill.

**Recurrence risk:** LOW with gap detector running. Happens when grading service or box score
scraper fails silently.

---

## Error 007 — Worker Running Disabled Models (Stale Cache)

**Category:** Fleet / Worker Cache
**Severity:** LOW-MEDIUM — wastes compute, pollutes predictions table
**First seen:** 2026-03-21 (Session 477)

**Symptom:**
- `player_prop_predictions` contains rows from `system_id` values that are
  `enabled=FALSE` or `status='blocked'` in the registry
- Worker has more models running than registry shows as enabled

**Root cause:**
Worker loads model list at startup with 4-hour TTL. After disabling models in the
registry, the worker continues using its cached (stale) list until cache expires.
The BB pipeline correctly ignores disabled/blocked models, so this is a prediction
table pollution issue (extra rows, extra compute) not a correctness issue.

**Detection:**
```sql
SELECT p.system_id, COUNT(*) as pred_count
FROM nba_predictions.player_prop_predictions p
LEFT JOIN nba_predictions.model_registry mr ON p.system_id = mr.model_id
WHERE p.game_date = CURRENT_DATE()
  AND (mr.model_id IS NULL OR mr.enabled = FALSE)
GROUP BY 1;
```

**Fix:**
```bash
./bin/refresh-model-cache.sh --verify
```

**Prevention:** Run cache refresh after any registry change (enable/disable/register).

**Recurrence risk:** LOW — inherent to TTL cache design. Acceptable until cache expires.

---

## Error 008 — v9_low_vegas Sanity Guard (100% UNDER)

**Category:** Fleet / Model Calibration
**Severity:** MEDIUM — blocks all v9_low_vegas picks
**First seen:** 2026-03-21 (Session 477)

**Symptom:**
- `catboost_v9_low_vegas` has high avg_abs_diff (e.g., 2.81) and is HEALTHY
- 0 picks from this model in BB pipeline
- Sanity guard log shows ">95% same direction" block

**Root cause:**
v9_low_vegas uses 0.25x vegas weight — much lower trust in the line. In a tight market
where Vegas is well-calibrated, the model systematically predicts below the line for
most players (100% UNDER). The model sanity guard (>95% same-direction) correctly
flags this as suspicious, blocking the model from BB pipeline.

The open question: is 100% UNDER correct behavior for this model, or is it miscalibrated?
The 57.3% UNDER HR in March suggests the direction predictions ARE correct, just extreme.

**Investigation query:**
```sql
SELECT system_id, recommendation, COUNT(*) as n,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_abs_diff
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id LIKE '%v9_low_vegas%'
  AND current_points_line IS NOT NULL
GROUP BY 1, 2;
```

**Potential fix (needs validation):**
Exempt v9_low_vegas from the sanity guard in `worker.py`, similar to how it was
exempted from `star_under_bias_suspect` in Session 476. Only do this if UNDER HR
confirms the direction is genuinely profitable (>57%).

**Status:** OPEN — needs 2-3 more game days of data to confirm before exempting from sanity guard.

**Recurrence risk:** HIGH — will repeat every game day until exemption added or model recalibrated.

---

## Error Patterns Summary

| # | Error | Frequency | Picks Lost | Auto-Detected? |
|---|-------|-----------|-----------|----------------|
| 001 | Registry status stale | Every model recovery | 2+ days | Yes (Session 477) |
| 002 | BB pipeline stall | Occasional | 1+ days | Yes (Session 477) |
| 003 | Model recovery gap | Every model recovery | Partial | Yes (Session 477) |
| 004 | CatBoost edge collapse | Every tight market | Weeks | No (manual) |
| 005 | New model no predictions | Every registration | 1 day | No (manual) |
| 006 | Grading lag | Occasional | MAE data only | Yes (gap-detector CF) |
| 007 | Worker stale cache | Every disable | Compute waste | No (acceptable) |
| 008 | v9_low_vegas sanity guard | Every game day | ~30% of fleet | No (open issue) |

---

## Adding New Entries

When diagnosing a new failure mode:
1. Add entry above with sequential number
2. Include: symptom, root cause, detection query, fix command, prevention added
3. Update the summary table
4. Reference the session number where it was first diagnosed
