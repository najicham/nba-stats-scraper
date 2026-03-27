# Session 495 Handoff — Signal Drought Root Cause + home_under Restore

**Date:** 2026-03-26
**Previous session:** Session 494 (Layer 6 fixes, observation filter audit, retrain bug fix)
**Commit:** `1b5cbf8a`

---

## System State: RECOVERING (signal drought root cause fixed, awaiting March 27 verification)

The system dropped from 10-16 BB picks/day to 0-7/day starting March 14. Root cause identified and fixed: `home_under` demotion to BASE_SIGNALS in Session 483 silently killed real_sc for ~50% of UNDER picks. Secondary issue: 9 signals were firing but invisible to monitoring.

---

## What Happened

### Root Cause: home_under Demotion Starved UNDER Picks of real_sc

In Session 483 (during the toxic Feb-March window), `home_under` was demoted from an active weighted signal to BASE_SIGNALS. BASE_SIGNALS do not contribute to `real_sc` (the non-base signal count). The `under_low_rsc>=2` gate requires at least 2 real signals for UNDER picks.

**Impact chain:**
1. `home_under` moved to BASE_SIGNALS --> provides real_sc=0 instead of real_sc=1
2. Every home UNDER pick with line >= 15 lost 1 real_sc point
3. ~50% of all UNDER picks hit real_sc=0 or real_sc=1 --> blocked at signal_density gate
4. Pick volume collapsed from 10-16/day to 0-7/day on March 14

The Session 483 demotion was based on the toxic Feb-March window where `home_under` HR briefly dipped. Current 7d HR is 69.2% (HOT). Backtest HR across 1,386 picks is 63.9%. The demotion was a toxic-window artifact, not a structural problem.

### Secondary Discovery: 9 Signals Missing from ACTIVE_SIGNALS

Nine signals added/promoted in Sessions 462-469 were never registered in `ACTIVE_SIGNALS` in `signal_health.py`:

| Signal | Added In | Status |
|--------|----------|--------|
| `hot_3pt_under` | Session 462 | Firing, contributing to real_sc |
| `cold_3pt_over` | Session 462 | Firing, contributing to real_sc |
| `line_drifted_down_under` | Session 462 | Firing, contributing to real_sc |
| `ft_anomaly_under` | Session 465 | Firing, contributing to real_sc |
| `slow_pace_under` | Session 466 | Firing, contributing to real_sc |
| `star_line_under` | Session 467 | Firing, contributing to real_sc |
| `sharp_consensus_under` | Session 468 | Firing, contributing to real_sc |
| `book_disagree_over` | Session 469 | Firing, contributing to real_sc |
| `book_disagree_under` | Session 469 | Firing, contributing to real_sc |

These signals were functional in the aggregator (computing, contributing to real_sc, appearing in pick_signal_tags). But `signal_health_daily` monitoring filters on `ACTIVE_SIGNALS`, so their health was never tracked. Any regime drift in these signals was invisible.

---

## Changes Made (commit `1b5cbf8a`)

### aggregator.py

**1. `home_under` restored to active signal (HIGH)**

- Removed from `BASE_SIGNALS`
- Added to `UNDER_SIGNAL_WEIGHTS` at weight 1.0 (NOT rescue-tier)
- Structural signal: UNDER + home + line >= 15
- Backtest HR: 63.9% (N=1,386), current 7d HR: 69.2% (HOT)
- The `under_low_rsc>=2` gate still protects: `home_under` provides real_sc=1, pick still needs 1 more signal to pass

**2. `usage_surge_over` graduated from SHADOW to active (MEDIUM)**

- Removed from `SHADOW_SIGNALS`
- Added to `OVER_SIGNAL_WEIGHTS` at weight 2.0
- Meets graduation criteria: 68.8% HR (N=32), N >= 30, HR >= 60%

**3. `combo_3way`/`combo_he_ms` removed from UNDER rescue_tags (LOW)**

- These are OVER-only signals (confirmed in signal files -- gated on `recommendation == 'OVER'`)
- Presence in UNDER rescue_tags was dead code from Session 483
- No pick impact -- these tags never fired for UNDER picks

**4. Algorithm version bumped**

- `v470_demote_high_skew` --> `v495_restore_home_under`

### pipeline_merger.py

**5. Stale `home_under: 2` removed from RESCUE_SIGNAL_PRIORITY (LOW)**

- Dead code left over from Session 483 demotion
- `home_under` is no longer a rescue signal; it is a standard weighted signal

### signal_health.py

**6. 9 signals added to ACTIVE_SIGNALS + 1 graduation (MEDIUM)**

Added to `ACTIVE_SIGNALS`: `hot_3pt_under`, `cold_3pt_over`, `line_drifted_down_under`, `ft_anomaly_under`, `slow_pace_under`, `star_line_under`, `sharp_consensus_under`, `book_disagree_over`, `book_disagree_under`, `usage_surge_over`

These signals will now appear in `signal_health_daily` monitoring. Any HOT/COLD/DEGRADED regime changes will be tracked and used for health-aware weighting.

### bin/retrain.sh

**7. Display fix: show EFFECTIVE_TRAIN_END in dry-run output (LOW)**

Dry-run now prints the actual training end date (after eval window subtraction), not the raw `--train-end` value.

**8. Filter-validation eval window fix (LOW)**

Eval window for filter validation aligned with the corrected date computation from Session 494.

### deployment/scheduler/mlb/*.yaml

**9. MLB monitoring scheduler season dates: 4-10 --> 3-10 (MEDIUM)**

Six MLB monitoring schedulers had schedule `4-10` (April-October). MLB Opening Day is March 27. Updated all 6 to `3-10` (March-October):
- pitcher-props-validator
- game-props-validator
- mlb-grading-validator
- mlb-model-health
- mlb-pipeline-canary
- mlb-daily-summary

### deployment/scripts/deploy-mlb-monitoring.sh

**10. 7 definitions updated to match new schedule (LOW)**

### SIGNAL-INVENTORY.md

**11. Fix 5 stale PRODUCTION entries (LOW)**

Inventory showed 28 active signals; actual count is 25 active + 34 shadow (after `usage_surge_over` graduation). Five signals incorrectly listed as PRODUCTION were corrected.

### CLAUDE.md

**12. Retrain LOOSE gate bug marked FIXED (LOW)**

The `weekly-retrain` CF LOOSE gate bug (pausing training when MAE > 5.0) was already fixed in Session 486 via `cap_to_last_loose_market_date()`. CLAUDE.md still listed it as an open issue. Marked as FIXED.

---

## Key Corrections to Previous Understanding

These corrections emerged during investigation and are important for future sessions:

1. **`combo_3way`/`book_disagreement` do NOT require cross-model diversity.**
   - `combo_3way`: checks edge + minutes + confidence from a single model's data
   - `book_disagreement`: checks sportsbook line standard deviation (not model disagreement)
   - Session 487's "fleet diversity collapse" narrative was incorrect about these signals

2. **`combo_3way`/`combo_he_ms` cannot rescue UNDER picks.**
   - Both signals have `recommendation == 'OVER'` gates in their signal files
   - Their presence in UNDER rescue_tags was dead code

3. **Decay-detection safety floor limits to 1 disable per run.**
   - Formula: `max_to_disable = enabled_count - safety_floor(3)`. With 4 enabled models: `4-3=1`.
   - Even with 3 BLOCKED models, only 1 gets disabled per CF invocation

4. **Weekly-retrain LOOSE gate bug was already FIXED in Session 486.**
   - `cap_to_last_loose_market_date()` already handles this correctly
   - No fix needed; CLAUDE.md was simply stale

5. **`flat_trend_under_obs` removal (Session 494) had zero pick impact.**
   - Was observation-only -- never blocked any picks
   - Removal was cleanup, not a pick-volume change

---

## Earlier Session 494 Work (already in main)

Session 494 was the same calendar date. Key changes already deployed (commit `0ad2bd66` and subsequent):

| Change | Commit |
|--------|--------|
| DELETE failure gate in `signal_best_bets_exporter.py` | `0ad2bd66` |
| Row-level fallback in `best_bets_all_exporter.py` | `0ad2bd66` |
| GCS duplicate picks canary + fleet diversity canary | `0ad2bd66` |
| 30 observation filters catalogued in aggregator.py | `0ad2bd66` |
| 10 observation filters promoted/removed | `79f6a0f8`, `98b59ecc` |
| shared/ sync (24 CF copies) | `68c5eb1e` |
| retrain.sh: python --> .venv/bin/python3 | `7b2901c9` |
| retrain.sh: eval date computation bug fix | `0652741a` |

---

## Fleet Status (as of session end)

| Model | State | HR 7d | Notes |
|-------|-------|-------|-------|
| lgbm_v12_noveg_train0103_0227 | DEGRADING | 54.1% | Sole workhorse |
| lgbm_v12_noveg_train0103_0228 | BLOCKED | 48.3% | Pending auto-disable |
| lgbm_v12_noveg_train1215_0214 | BLOCKED | 41.0% | Pending auto-disable |
| catboost_v12_noveg_train0118_0315 | BLOCKED | 42.9% | Pending auto-disable |

Decay-detection CF will auto-disable 1 BLOCKED model per run (safety floor: max 1 at current fleet size of 4).

### New Models (LOCAL ONLY -- not deployed)

Two models trained with corrected retrain.sh date logic (train: Jan 21 - Mar 18, eval: Mar 19 - Mar 25):

| Model | HR | N | Status |
|-------|-----|---|--------|
| lgbm_v12_noveg_train0121_0318 | 59.05% | 105 | Saved to `models/` directory |
| catboost_v12_noveg_train0121_0318 | 58.82% | 51 | Saved to `models/` directory |

Both failed the 60% governance gate by ~1pp (statistically noise at N=51-105). These models are significantly better than the current DEGRADING fleet (54.1% HR).

**NOT in GCS. NOT in model_registry. REQUIRES EXPLICIT USER APPROVAL to enable.**

Enable process: upload to GCS --> INSERT into `model_registry` --> `./bin/refresh-model-cache.sh --verify`

---

## MLB Status

- **Model:** `catboost_mlb_v2_regressor_40f_20250928.cbm`
- **Opening Day:** March 27, 2026
- **All 33 schedulers:** ENABLED
- **Monitoring schedulers:** Updated from `4-10` to `3-10` (GCP deployment pending for 6 schedulers)
- **Worker health:** OK
- **Pre-game verification checklist:** `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md`

---

## Full Session 495 Commit Log

| Commit | Description |
|--------|-------------|
| `1b5cbf8a` | fix: restore home_under + 9 signal health fixes + MLB scheduler season dates |

Prior Session 494 commits (same calendar date):

| Commit | Description |
|--------|-------------|
| `a91fe520` | docs: Session 494 extended handoff |
| `0652741a` | fix: retrain.sh eval date computation bug |
| `7b2901c9` | fix: retrain.sh use .venv/bin/python3 |
| `98b59ecc` | fix: promote hot_shooting_reversion + remove flat_trend_under |
| `79f6a0f8` | fix: promote/remove 7 observation filters |
| `68c5eb1e` | chore: sync shared/ to 6 CF directories |
| `ff7b8922` | docs: Session 494 handoff |
| `0ad2bd66` | fix: Layer 6 structural fixes, canaries, filter audit |

---

## End of Session Checklist

- [x] Root cause identified: `home_under` demotion to BASE_SIGNALS starved UNDER real_sc
- [x] `home_under` restored to UNDER_SIGNAL_WEIGHTS (weight 1.0)
- [x] `usage_surge_over` graduated from SHADOW to active (68.8% HR, N=32)
- [x] `combo_3way`/`combo_he_ms` removed from UNDER rescue_tags (dead code)
- [x] 9 missing signals added to ACTIVE_SIGNALS in signal_health.py
- [x] Stale `home_under` entry removed from RESCUE_SIGNAL_PRIORITY in pipeline_merger.py
- [x] Algorithm version bumped to `v495_restore_home_under`
- [x] MLB monitoring schedulers updated (4-10 --> 3-10)
- [x] SIGNAL-INVENTORY.md corrected (25 active, 34 shadow)
- [x] CLAUDE.md retrain LOOSE gate bug marked FIXED
- [x] retrain.sh display and eval window fixes
- [x] Pushed to main (`1b5cbf8a`), auto-deploy triggered
- [ ] **Verify March 27 pick counts** (expected 8-15 UNDER picks/day)
- [ ] **Enable new retrained models** (requires user approval)
- [ ] **MLB Opening Day verification** (March 27)
- [ ] **Deploy MLB monitoring scheduler updates to GCP**
- [ ] **Observation filter BQ verification** (neg_pm_streak_obs, line_dropped_over_obs)

---

## Next Session Priorities

### 1. Verify signal drought fix (URGENT -- first day with fix is March 27)

Check pick counts for March 27. Expected: 8-15 UNDER picks per day (vs 0-7 before fix).

```sql
SELECT recommendation, COUNT(*)
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27'
GROUP BY 1;
```

Also verify `home_under` is appearing in pick_signal_tags:

```sql
SELECT player_lookup, pick_signal_tags
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27'
  AND pick_signal_tags LIKE '%home_under%';
```

### 2. Enable new models (requires user approval)

Two locally-trained models (59.05% LGBM, 58.82% CatBoost) are significantly better than the sole DEGRADING workhorse (54.1%). They failed the 60% governance gate by ~1pp at low N (statistical noise).

**Process:**
1. Upload model files from `models/` to GCS
2. INSERT into `model_registry` with appropriate metadata
3. `./bin/refresh-model-cache.sh --verify`
4. Monitor for 2+ days in shadow before promoting

See Session 494 handoff for exact SQL and GCS paths.

### 3. MLB Opening Day verification (March 27)

Run pre-game checklist from `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md`.

Key checks:
- Props may not appear until afternoon -- check hourly after 10 AM ET
- Verify scraper is pulling MLB odds from odds_api
- Confirm predictions generating in `mlb_predictions.player_prop_predictions`
- Deploy the 6 updated MLB monitoring schedulers to GCP

### 4. Observation filter BQ verification

Run CF HR query against `filter_counterfactual_daily` for current-season data. Top candidates for action:

| Filter | Simulator CF HR | N | Expected Action |
|--------|----------------|---|-----------------|
| `neg_pm_streak_obs` | 64.5% | 758 | Remove (blocking 64.5% winners) |
| `line_dropped_over_obs` | 60.0% | 477 | Remove (smart money is bullish) |

```sql
SELECT
  filter_name,
  AVG(cf_hr) AS avg_cf_hr,
  SUM(n_blocked) AS total_n,
  COUNT(DISTINCT game_date) AS n_days
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date >= '2025-11-01'
GROUP BY 1
ORDER BY total_n DESC;
```

### 5. Shadow signal graduation pipeline

`usage_surge_over` just graduated this session. Next candidate: `consistent_scorer_over` (80% HR, N=20). Needs N >= 30 before graduation.

### 6. downtrend_under -- DO NOT PROMOTE

Keep in SHADOW. Season BB HR is 1-5 (16.7%). The 7d HOT reading is misleading with tiny N. Do not promote despite the favorable short-term signal.

---

## Warnings for Future Sessions

1. **Toxic window artifact pattern:** Session 483 demoted `home_under` based on a toxic Feb-March window dip. This caused a 12-day pick drought. Before demoting any structural signal, verify that the dip persists outside the toxic window.

2. **ACTIVE_SIGNALS registration:** When adding new signals to the aggregator, ALWAYS add them to `ACTIVE_SIGNALS` in `signal_health.py` simultaneously. Otherwise they fire but are invisible to monitoring.

3. **real_sc cascading impact:** Moving any signal into BASE_SIGNALS reduces real_sc for all picks that depended on it. The `signal_density` gate and `under_low_rsc` gate will silently block those picks. Always check what percentage of picks a signal contributes real_sc to before demoting.
