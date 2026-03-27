# Session 495 Handoff

**Date:** 2026-03-26
**Previous session:** Session 494 (Layer 6 fixes, filter promotions, retrain.sh bug fix)
**Commit:** `1b5cbf8a`

---

## What Was Done

### 1. Signal drought root cause found and fixed (`home_under` restored)

**Root cause:** `home_under` was demoted to `BASE_SIGNALS` in Session 483 (48.1% HR 30d reading on
Session 483 raw data). That reading was during the March 8 toxic window. Current 7d HR is 69.2%
(HOT). Demotion removed `home_under` from `UNDER_SIGNAL_WEIGHTS` — it stopped contributing to
`real_sc` and to UNDER pick ranking. This collapsed the UNDER pipeline's signal quality scores,
causing the SC≥2 gate to block most UNDER picks.

**Fix:** Restored `home_under` to `UNDER_SIGNAL_WEIGHTS` with weight 1.0. Added comment explaining
why it was removed (Session 483) and restored (Session 495).

Note: `home_under` is NOT in `rescue_tags` (only `hot_3pt_under` and `line_drifted_down_under`
rescue UNDER picks from the edge floor). The old rescue_tags comment at line 546 was stale dead code
— the actual rescue block at line 540 never included it.

### 2. `usage_surge_over` graduated from SHADOW to ACTIVE

- 68.8% HR at N=32 at BB level — meets graduation criteria (N≥30, HR≥60%).
- Removed from `SHADOW_SIGNALS` in `aggregator.py`.
- Added to `ACTIVE_SIGNALS` in `signal_health.py` for monitoring.
- Comment added to `SHADOW_SIGNALS` block explaining the graduation.

### 3. 9 signals added to `signal_health.py` ACTIVE_SIGNALS (monitoring fix)

Signals that were active in `aggregator.py` but missing from `signal_health.py`'s `ACTIVE_SIGNALS`
set — meaning their health was never tracked in `signal_health_daily`:

- `dvp_favorable_over`, `dvp_favorable_under`
- `minutes_surge_over`
- `hot_shooting_reversion_over` (newly promoted to active block this session)
- `book_disagree_over`, `book_disagree_under`
- `line_rising_over`
- `sharp_line_drop_under`
- `usage_surge_over` (graduated this session)

### 4. Dead code cleanup

- Removed stale `combo_3way`/`combo_he_ms` entries from the UNDER `rescue_tags` comment block in
  `aggregator.py`. These signals have OVER-only qualification gates (`combo_3way.py:46`,
  `combo_he_ms.py:39`) — they never qualified for UNDER picks. The comment was misleading.
- Removed stale `diversity_mult`/`consensus_bonus` references from `pipeline_merger.py` (Session 445
  per-model refactor made them dead code).

### 5. MLB scheduler yaml updated

`deployment/scheduler/mlb/validator-schedules.yaml` updated with correct season months (March-October
`3-10`). **GCP deployment is pending** — agent was dispatched to run the 6 gcloud commands. Verify
below.

### 6. `retrain.sh` display bugs fixed

Minor: dry-run output was showing incorrect date ranges in some display paths. No functional change
to the actual training logic (the substantive eval date fix was Session 494).

### 7. `SIGNAL-INVENTORY.md` and `CLAUDE.md` updated

- SIGNAL-INVENTORY.md: `home_under` moved from BASE_SIGNALS back to UNDER_SIGNALS section.
- CLAUDE.md: Updated UNDER_SIGNAL_WEIGHTS list, added Session 495 notes.

---

## Expected Pick Volume Tomorrow (March 27)

**Before Session 483 (home_under active):** 10-16 picks/day
**After Session 483 demotion (home_under in BASE_SIGNALS):** 0-7 picks/day

**Expected for March 27:** 8-14 picks/day

Reasoning:

1. **home_under restoration** is the dominant factor. Restoring it to `UNDER_SIGNAL_WEIGHTS` (weight
   1.0) re-enables it to count toward `real_sc` — picks that previously failed the SC≥2 gate will
   now pass. This is the main signal that was blocking UNDER picks.

2. **Upward pressure vs. Session 483 baseline:**
   - 5 observation filters removed (familiar_matchup, b2b_under, ft_variance_under, neg_pm_streak,
     line_dropped_over) — these were blocking winners; removal adds picks.
   - `flat_trend_under_obs` removed — directly adds UNDER candidates.
   - `usage_surge_over` now counts toward real_sc — marginal OVER boost.

3. **Downward pressure vs. Session 483 baseline:**
   - 3 observation filters promoted to active blocks (monday_over, home_over,
     hot_shooting_reversion) — these reduce OVER picks.
   - OVER edge floor raised to 5.0 (was 4.0 at time of Session 483).
   - Fleet is degraded (1 DEGRADING model, 2 BLOCKED) — fewer raw predictions feeding the pipeline
     vs. a healthy 4-model fleet.

4. **Net estimate:** The filter removals and `home_under` restoration together should recover most of
   the lost UNDER volume. OVER volume will be slightly suppressed by the new active blocks and higher
   floor. Expect 8-14 picks on a normal 8-game slate, slightly lower than the 10-16 range due to the
   degraded fleet.

**If pick count is still < 5:** The fleet degradation is the limiting factor — only 1 DEGRADING model
is generating predictions. Enabling the borderline retrain models (pending approval below) is the fix.

---

## TONIGHT — Time-Critical Actions

### 1. Verify MLB scheduler GCP deployment (CRITICAL — Opening Day is TOMORROW)

Check if the agent's `gcloud` commands succeeded:

```bash
# Check if schedulers exist with correct config
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  | grep mlb

# Verify season months are 3-10 (not 4-10)
gcloud scheduler jobs describe mlb-pitcher-props-validator-4hourly \
  --location=us-west2 --project=nba-props-platform
```

If schedulers are missing or have wrong schedule, apply yaml:
```bash
# The yaml has create commands at the bottom — run each gcloud command from
# deployment/scheduler/mlb/validator-schedules.yaml
```

### 2. Verify MLB worker health

```bash
gcloud run services describe mlb-pitcher-props-worker \
  --region=us-west2 --project=nba-props-platform \
  --format="value(status.conditions[0].type,status.conditions[0].status)"
```

Expected: `Ready True`

### 3. Verify Cloud Build for Session 495 commit (`1b5cbf8a`) succeeded

```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

Check build for commit `1b5cbf8a` shows `SUCCESS`. This deploys the `home_under` fix and
`usage_surge_over` graduation to production.

### 4. Verify decay-detection CF auto-disabled BLOCKED models

BLOCKED models from Session 494 (train0103_0228 at 48.3%, train1215_0214 at 41.0%,
catboost_v12_noveg_train0118_0315 at 42.9%) should be auto-disabled at 4 PM UTC today.

```bash
python /home/naji/code/nba-stats-scraper/bin/model-registry.sh list 2>/dev/null || \
  bq query --nouse_legacy_sql \
  "SELECT model_id, state, enabled FROM nba_predictions.model_registry ORDER BY created_at DESC LIMIT 10"
```

---

## REQUIRES USER APPROVAL

### Enable borderline retrain models

**Context:** Two models were trained in Session 494 with corrected eval date logic. Both failed the
60% governance gate by ~1pp, but the fleet is currently down to 1 DEGRADING model (54.1% HR).

| Model | HR | N eval | Gate status |
|-------|----|--------|-------------|
| lgbm_v12_noveg (new) | 59.05% | 105 | Failed by 0.95pp |
| catboost_v12_noveg (new) | 58.82% | 51 | Failed by 1.18pp |

**Options:**

**Option A — Enable as-is with approval** (fast, today)
- Models are on local disk, not yet in GCS or model_registry.
- Requires: upload to GCS → INSERT into `model_registry` → `./bin/refresh-model-cache.sh --verify`
- Risk: ~1pp below governance threshold; both are statistically better than the DEGRADING workhorse
  at 54.1%.

**Option B — Retrain with wider window** (slower, better confidence)
```bash
./bin/retrain.sh --family lgbm --window 70 --no-production-lines
./bin/retrain.sh --family catboost --window 70 --no-production-lines
```
- Wider window = more eval rows = better estimate. May push above 60%.
- Takes ~30 min. Results available tonight.

**Option C — Wait for weekly-retrain CF** (Monday March 30)
- CF runs every Monday 5 AM ET. Gate is confirmed working (Session 494 verified).
- Clean data, auto-uploads, auto-registers. No manual steps.
- Risk: fleet stays at 1 DEGRADING model until Monday — may affect March 27-29 pick volume.

**Recommendation:** Option B if you have 30 minutes tonight. Option C if comfortable with degraded
fleet through the weekend.

---

## TOMORROW MORNING (March 27)

### 1. Verify signal drought is fixed — check pick counts

```bash
# Check March 27 predictions were generated
bq query --nouse_legacy_sql \
  "SELECT COUNT(*) as n FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-03-27'"

# Check best bets picks were exported
bq query --nouse_legacy_sql \
  "SELECT recommendation, COUNT(*) as n, AVG(ABS(predicted_points - current_points_line)) as avg_edge
   FROM nba_predictions.signal_best_bets_picks
   WHERE game_date = '2026-03-27'
   GROUP BY 1"
```

Expected: 8-14 picks total, split roughly 60/40 UNDER/OVER.
If < 5 picks: fleet degradation is the bottleneck (enable retrain models or wait for Monday CF).
If 0 picks: check pipeline canaries — may be a Phase 5 failure.

### 2. MLB Opening Day monitoring

BettingPros K props appear afternoon (typically 1-3 PM ET). Check hourly:

```bash
# Check if MLB predictions were generated
bq query --nouse_legacy_sql \
  "SELECT COUNT(*) FROM nba_predictions.mlb_predictions WHERE game_date = '2026-03-27'"
```

Also verify the 4-hourly scheduler fired for `mlb-pitcher-props-validator-4hourly`:
```bash
gcloud scheduler jobs describe mlb-pitcher-props-validator-4hourly \
  --location=us-west2 --project=nba-props-platform \
  --format="value(lastAttemptTime,state)"
```

### 3. Run observation filter BQ query before promoting `neg_pm_streak_obs` removal

The Session 494 handoff showed `neg_pm_streak_obs` removed (CF HR 64.5%, N=758). That action was
taken in Session 494. Verify current-season numbers before deciding on the remaining Category C
filters:

```sql
SELECT
  filter_name,
  AVG(cf_hr) AS avg_cf_hr,
  SUM(n_blocked) AS total_n,
  COUNT(DISTINCT game_date) AS n_days
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date >= '2025-11-01'
  AND filter_name IN (
    'player_under_suppression_obs',
    'solo_game_pick_obs',
    'thin_slate_obs',
    'home_over_obs',
    'monday_over_obs'
  )
GROUP BY 1
ORDER BY total_n DESC
```

`home_over_obs` and `monday_over_obs` were promoted to active blocks on March 26 — verify the
current-season data supports them (CF HR should be ≤52%).

### 4. Check fleet state post decay-detection cleanup

```bash
./bin/check-deployment-drift.sh --verbose
```

---

## NEXT WEEK (Monday March 30)

### Weekly-retrain CF verification

The CF should auto-fire at 5 AM ET. Key facts:
- Gate fix is NOT needed for the CF (it already computes eval dates correctly per Session 494 analysis).
- `quick_retrain.py` eval hardcoded to `catboost_v9` bug still exists (COMMON ISSUES in CLAUDE.md).
  CF uses `--no-production-lines` internally — not affected.
- After retrain completes, run `./bin/model-registry.sh sync`.

Check if it ran:
```bash
gcloud functions logs read weekly-retrain \
  --region=us-west2 --project=nba-props-platform \
  --limit=50 --start-time="2026-03-30T05:00:00Z"
```

### Decay-detection state machine cleanup

If BLOCKED models were NOT auto-disabled on March 26 (4 PM UTC), manually disable them:
```bash
python bin/deactivate_model.py lgbm_v12_noveg_train0103_0228 --dry-run
python bin/deactivate_model.py lgbm_v12_noveg_train1215_0214 --dry-run
python bin/deactivate_model.py catboost_v12_noveg_train0118_0315 --dry-run
# Remove --dry-run when confirmed correct
```

---

## DEFERRED / LOW PRIORITY

| Item | Priority | Notes |
|------|----------|-------|
| `feature_extractor.py` system_id threading | LOW | V16 features 55-56 use MAX across systems. Requires threading system_id through 15+ ThreadPoolExecutor tasks. |
| `quick_retrain.py` eval hardcoded `catboost_v9` | MEDIUM | Line 569 bug. Workaround: always pass `--no-production-lines`. |
| Remaining Category C filter removals | MEDIUM | After verifying BQ CF HR data: `flat_trend_under_obs` already removed; check `line_jumped_under_obs` (CF 100%, N=5 too low). |
| `hot_shooting_reversion_obs` → UNDER signal | LOW | 59.2% UNDER HR — consider converting from block to signal. Needs current-season BQ verification. |
| `under_star_away` re-promotion | LOW | Was demoted during toxic Feb window. Confirm sustained recovery (check signal_health_daily). |

---

## Fleet State Summary (end of Session 495)

| Model | State | HR 7d |
|-------|-------|-------|
| lgbm_v12_noveg_train0103_0227 | DEGRADING | 54.1% |
| lgbm_v12_noveg_train0103_0228 | BLOCKED | 48.3% |
| lgbm_v12_noveg_train1215_0214 | BLOCKED | 41.0% |
| catboost_v12_noveg_train0118_0315 | BLOCKED | 42.9% |

3 BLOCKED models expected to be auto-disabled by `decay-detection` CF at 4 PM UTC today.
After cleanup: 1 active model (DEGRADING). Minimum fleet to keep `combo_3way`/`book_disagreement`
firing: 1 non-LGBM model (currently absent after CatBoost becomes auto-disabled).

**Fleet diversity warning:** After today's cleanup, the fleet will be 1 LGBM model only. Both
`combo_3way` and `book_disagreement` require cross-model disagreement and will NOT fire. This is the
Session 487 fleet diversity collapse scenario. Enabling the borderline CatBoost retrain model (or
waiting for Monday's weekly-retrain) is the fix.

---

## Session 495 Commit

| Commit | Description |
|--------|-------------|
| `1b5cbf8a` | fix: restore home_under + 9 signal health fixes + MLB scheduler season dates |
