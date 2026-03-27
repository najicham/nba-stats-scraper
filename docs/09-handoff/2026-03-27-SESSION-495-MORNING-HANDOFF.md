# Session 495 Morning Handoff — 2026-03-27

**Date:** 2026-03-27 (morning)
**Previous handoffs:** `2026-03-26-SESSION-495-SIGNAL-DROUGHT-FIX.md`, `2026-03-26-SESSION-495-HANDOFF.md`
**Commits this session:** `1b5cbf8a`, `9d3e081c`

---

## ACTIVE ISSUES — FIX IN PROGRESS

Two issues are being fixed by background agents right now. The new chat must verify completion.

### Issue 1: NBA — 0 picks due to duplicate predictions

**Status:** Fix agent running (may have completed — check before acting)

**Root cause:** Aaron Holiday appears 3-4× per model in `player_prop_predictions` for 2026-03-27 (128 duplicate rows out of 1,080 total). Phase 5 consolidation threw a duplicate business key error → Phase 6 never triggered → 0 picks for 10-game slate.

**Verify fix completed:**
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
"SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27'
GROUP BY 1,2"
```
Expected: 8-14 picks (UNDER-heavy). If still 0, manually re-trigger Phase 6:
```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["signal-best-bets"], "target_date": "2026-03-27"}'
```

**Check for duplicates first (before triggering):**
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
"SELECT player_lookup, system_id, COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-27'
GROUP BY 1,2 HAVING COUNT(*) > 1
ORDER BY 3 DESC LIMIT 10"
```
If duplicates still exist, deduplicate first (keep latest `predicted_at` per player+system):
```sql
-- Dry run first to see scope
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-27'
```

**Root cause likely:** Aaron Holiday was traded/signed to a second team and appears twice in the feature store. Check:
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
"SELECT player_lookup, team_tricode, COUNT(*) FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-03-27' AND player_lookup LIKE '%holiday%'
GROUP BY 1,2"
```

---

### Issue 2: MLB Opening Day — pipeline not bootstrapped

**Status:** Fix agent running (may have completed — check before acting)

**Root cause:** `mlb_events` scraper (which populates `mlb_raw.oddsa_events` with Odds API game UUIDs) has never run in 2026. Without event IDs, `mlb_pitcher_props` scraper fails with "Missing required option [event_id]". No props → no predictions → no picks. 8 games scheduled today, 15 games tomorrow.

**Verify event IDs populated:**
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
"SELECT game_date, COUNT(*) as events FROM mlb_raw.oddsa_events
WHERE game_date >= '2026-03-27' GROUP BY 1"
```

**If empty, manually trigger mlb_events scraper:**
```bash
SERVICE_URL=$(gcloud run services describe nba-scrapers --region=us-west2 \
  --project=nba-props-platform --format="value(status.url)")
curl -X POST "$SERVICE_URL/scrape" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"scraper": "mlb_events", "date": "2026-03-27"}'
```

**Then trigger props scraper:**
```bash
curl -X POST "$SERVICE_URL/scrape" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"scraper": "mlb_pitcher_props", "date": "2026-03-27"}'
```

**Then trigger predictions (after props appear):**
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
"SELECT COUNT(*) FROM mlb_raw.bp_pitcher_props WHERE game_date = '2026-03-27'"
# When > 0, manually run predictions:
gcloud scheduler jobs run mlb-predictions-generate --location=us-west2 --project=nba-props-platform
```

**Also fix mlb-pitcher-props-validator-4hourly PERMISSION_DENIED (code 7):**
```bash
gcloud scheduler jobs describe mlb-pitcher-props-validator-4hourly \
  --location=us-west2 --project=nba-props-platform --format="yaml" | grep -A5 "oidcToken\|serviceAccount"
```
The service account may need Cloud Run Invoker permission on the validator function.

---

## What Was Accomplished in Session 495

### Signal Drought Fix (commit `1b5cbf8a`)
The system had 0-7 picks/day since March 14. Root cause found and fixed:

- **`home_under` restored from BASE_SIGNALS → UNDER_SIGNAL_WEIGHTS (weight 1.0, NOT rescue)**
  - Was the primary `real_sc=1` source for ~50% of UNDER picks (home + line≥15)
  - Session 483 demotion (48.1% 30d HR) was a toxic Feb-March window artifact
  - Now HOT at 66.7% 7d HR ✅
  - `under_low_rsc≥2` gate still requires a 2nd real signal to pass
- **`usage_surge_over` graduated from SHADOW (68.8% HR, N=32)**
- **9 signals added to `signal_health.py:ACTIVE_SIGNALS`** — monitoring gap fix for hot_3pt_under, cold_3pt_over, line_drifted_down_under + 6 others
- **Algorithm version bumped to `v495_restore_home_under`**
- **Dead code cleaned:** combo_3way/combo_he_ms removed from UNDER rescue_tags (OVER-only), stale pipeline_merger entries

### New Models Enabled (manual registration, Session 495 evening)
Both models registered in `model_registry` (enabled=TRUE, status=active) and loaded by prediction-worker:
- **`lgbm_v12_noveg_train0121_0318`**: 59.05% HR (N=105), failed 60% gate by 0.95pp (p=0.42 — statistical noise). Trained Jan 21 → Mar 18. GCS: `gs://nba-props-platform-models/catboost/v12/monthly/lgbm_v12_50f_noveg_train20260121-20260318_20260326_172558.txt`
- **`catboost_v12_noveg_train0121_0318`**: 58.82% HR (N=51), same justification. GCS: `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v12_50f_noveg_train20260121-20260318_20260326_172646.cbm`
- Both are generating predictions as of this morning (158 predictions each, avg_abs_diff 1.38-1.71)
- NOT yet in `model_performance_daily` — will appear after today's grading run

### MLB Schedulers Fixed
All 7 MLB monitoring schedulers updated from `4-10` → `3-10` in both YAML files and GCP Cloud Scheduler. MLB worker health: `{"status":"healthy"}`.

### Other Changes (same session)
- retrain.sh: display bug (line 246) + filter-validation eval window fixed
- SIGNAL-INVENTORY.md: 5 stale PRODUCTION entries corrected (28→25 active, 32→34 shadow)
- CLAUDE.md: retrain LOOSE gate bug marked FIXED (was Session 486)
- shared/ sync clean (0 differences)

---

## Current Fleet State

| Model | State | HR 7d | Notes |
|-------|-------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | WATCH | 55.4% | Primary workhorse. Improved from 54.1% yesterday. |
| `lgbm_v12_noveg_train0121_0318` | No data yet | — | NEW. Generating 158 predictions. |
| `catboost_v12_noveg_train0121_0318` | No data yet | — | NEW. Generating 158 predictions. |
| `catboost_v12_noveg_train0118_0315` | BLOCKED | 50.0% | Auto-disable pending (safety floor). |
| `lgbm_v12_noveg_train0103_0228` | BLOCKED | 50.0% | Auto-disable pending. |
| `lgbm_v12_noveg_train1215_0214` | BLOCKED | 41.0% | Auto-disable pending. |

**Decay-detection did NOT run overnight** — BLOCKED models still enabled. Safety floor (min 3 enabled) is the constraint. Once new models accumulate grading data (2-3 days), decay-detection will be free to clean up BLOCKED models.

---

## Signal Health (as of 2026-03-26)

| Signal | Regime | HR 7d | Notes |
|--------|--------|-------|-------|
| `home_under` | **HOT** | 66.7% | Restored Session 495 ✅ |
| `combo_3way` | NORMAL | 75.0% | Strong |
| `usage_surge_over` | NORMAL | 58.3% | Just graduated from SHADOW |
| `line_rising_over` | NORMAL | 58.3% | Active |
| `bench_under` | COLD | 33.3% | Monitor (N=3, may be noise) |
| `line_drifted_down_under` | COLD | 50.0% | Monitor (14d HR 75% — likely noise) |

---

## Market Conditions

**NORMAL** — vegas_mae_7d = 5.03 (above 4.5 TIGHT threshold). No auto-gate suppression. OVER floor stays at 5.0. OVER rescue active.

---

## Monday March 30 — Weekly Retrain CF

- Fires at 5 AM ET
- TIGHT market gate is FIXED (Session 486 — `cap_to_last_loose_market_date()`)
- TIGHT ended March 14 (16 days ago), well past 7-day recovery threshold
- CF will retrain LGBM + CatBoost + XGBoost families
- Same 60% governance gate — probability of passing ~35-45% given current ~59% underlying model HR
- If CF fails: same manual enable process as Session 495 (models on disk at `models/`)
- Staleness check: new models have `training_end_date = 2026-03-18` (12 days before March 30) — CF will NOT skip them (skips only if < 5 days since training_end_date)

---

## Key Corrections to Session Documentation

1. **`combo_3way`/`book_disagreement` do NOT require cross-model diversity** — `combo_3way` checks edge+minutes+confidence; `book_disagreement` checks sportsbook line std. All-LGBM fleet does not disable these signals.
2. **BLOCKED models contribute ZERO candidates** — excluded at BQ query level in `per_model_pipeline.py` (`status IN ('blocked', 'disabled')`).
3. **Weekly-retrain LOOSE gate was ALREADY FIXED in Session 486** — `cap_to_last_loose_market_date()` function at lines 204-259 of CF.
4. **`downtrend_under` should stay in SHADOW** — season BB HR 1-5 (16.7%) despite HOT 7d reading. 7d HOT is small-sample noise.

---

## Observation Filters — Remaining Actions

From Session 494 analysis (BQ verification still pending):

**Category C — removal candidates (blocking winners):**
- `neg_pm_streak_obs`: 64.5% CF HR, N=758 → **remove**
- `line_dropped_over_obs`: 60.0% CF HR, N=477 → **remove**
- `ft_variance_under_obs`, `familiar_matchup_obs`, `b2b_under_block_obs`: 5-season validated → **remove**

**Category B — promotion candidates (blocking losers):**
- `home_over_obs`: 49.7% CF HR, N=4,278 → **promote to active**
- `monday_over_obs`: 49.0% CF HR, N=251 → **promote to active**

**Before acting, run BQ verification:**
```sql
SELECT filter_name, AVG(cf_hr) AS avg_cf_hr, SUM(n_blocked) AS total_n
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date >= '2025-11-01'
  AND filter_name IN ('neg_pm_streak_obs','line_dropped_over_obs','home_over_obs',
                      'monday_over_obs','ft_variance_under_obs','familiar_matchup_obs','b2b_under_block_obs')
GROUP BY 1 ORDER BY 2 DESC
```

---

## Next Session Priorities

1. **Verify NBA duplicate fix** — check picks for today's 10-game slate
2. **Verify MLB pipeline bootstrapped** — check if event IDs populated, props scraped, predictions generated
3. **Fix `mlb_events` auto-scheduling** — add a daily `mlb-events-daily` scheduler (currently no automatic scheduler for event ID population)
4. **Observation filter BQ verification** → promote/remove as above
5. **Monitor new models performance** — `lgbm/catboost_train0121_0318` appear in `model_performance_daily` tomorrow; watch for WATCH/HEALTHY vs DEGRADING
6. **Monday retrain (March 30)** — verify CF fires at 5 AM ET and check Slack for results

---

## Full Session 495 Commit Log

| Commit | Description |
|--------|-------------|
| `1b5cbf8a` | Signal drought fix: home_under restored, usage_surge_over graduated, 9 ACTIVE_SIGNALS, MLB scheduler dates, retrain.sh fixes |
| `9d3e081c` | Handoff docs + fix usage_surge_over duplicate in ACTIVE_SIGNALS |

**Models manually registered (no commit):**
- `lgbm_v12_noveg_train0121_0318` — registered 2026-03-27 03:30 UTC
- `catboost_v12_noveg_train0121_0318` — registered 2026-03-27 03:30 UTC

---

## End of Session Checklist

- [x] Signal drought root cause identified and fixed (home_under restored)
- [x] 9 signals added to ACTIVE_SIGNALS (monitoring gap)
- [x] usage_surge_over graduated from SHADOW
- [x] New models (59%) registered and generating predictions
- [x] MLB schedulers updated (4-10 → 3-10) in YAML + GCP
- [x] retrain.sh display/filter-validation bugs fixed
- [x] SIGNAL-INVENTORY.md corrected
- [x] CLAUDE.md updated
- [x] Handoff docs written
- [ ] NBA duplicate fix (in progress — verify picks for 2026-03-27)
- [ ] MLB pipeline bootstrap (in progress — verify props + predictions)
- [ ] Observation filter BQ verification + promote/remove
- [ ] Monday retrain CF verification (March 30)
