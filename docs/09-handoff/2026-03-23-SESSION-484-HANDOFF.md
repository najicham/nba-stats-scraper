# Session 484 Handoff — 2026-03-23

**Latest commit:** `8af2c766` — MLB signal health tracker
**Branch:** main (auto-deployed)

---

## System State: HEALTHY

### NBA Fleet (3 enabled LGBM models)
| Model | State | HR 7d | N 7d | Notes |
|-------|-------|-------|------|-------|
| `lgbm_v12_noveg_train0103_0227` | HEALTHY | 61.5% | 26 | Primary workhorse |
| `lgbm_v12_noveg_train1215_0214` | WATCH | 57.1% | 21 | Decision point Mar 25 — let decay CF handle |
| `lgbm_v12_noveg_train0103_0228` | NEW | — | — | Just trained Session 483, not in perf table yet |

### Today's Picks (Mar 23 — 10 games)
**0 best bets today.** This is **expected, not broken.**

Filter audit confirmed:
- 25 candidates reached the pipeline
- **16 blocked by `over_edge_floor`** — OVER picks all have edge < 5.0
- 9 UNDER candidates blocked by: `flat_trend_under`(3), `line_jumped_under`(2), `neg_pm_streak`(2), others

Root cause: avg_abs_diff 1.29-1.47 across all 3 models. Only 4 edge5+ predictions total.
Market is NORMAL (vegas_mae 5.23). Pick drought is market-driven, not a pipeline bug.

BB HR since Mar 11 fleet reset: **100% (5-6 picks)**. Quality over quantity.

---

## What Was Done This Session (484)

### 1. Pre-commit YAML multi-doc fix
`.pre-commit-config.yaml`: added `--allow-multiple-documents` to `check-yaml`.
Previously blocked commits with `--- ` separated YAML files (deployment/scheduler/mlb/).

### 2. MLB orchestrator `write_to_bigquery: True` (CRITICAL fix)
`orchestration/cloud_functions/mlb_phase4_to_phase5/main.py`: added `"write_to_bigquery": True` to the predict-batch payload.
Without this, Opening Day predictions would be computed but **never saved to BigQuery**.
Deployed in commit `3ee57011`.

### 3. Single-model dominance alert
`ml/signals/pipeline_merger.py`: added `SINGLE_MODEL_DOMINANCE` warning when one model
sources >40% of selected picks. Uses `source_pipeline` from selected picks (not pre-dedup candidates).

### 4. MLB signal_health.py built
`ml/signals/mlb/signal_health.py` (695 lines):
- 20 active + 30 shadow MLB signals tracked
- Joins `signal_best_bets_picks` + `mlb_predictions.prediction_accuracy`
- HOT/NORMAL/COLD regime classification (same thresholds as NBA)
- Session 483 HOT gate: `picks_7d >= 5 AND hr_30d >= 50%`
- Writes to `mlb_predictions.signal_health_daily`
- CLI: `--date`, `--backfill --start --end`, `--season-start`, `--dry-run`
- Public function `get_signal_health_summary()` for exporters/monitoring

### 5. Fleet + edge analysis (3-agent review)
Full system analysis confirmed:
- 0 picks today is system working correctly
- Do NOT re-enable CatBoost models (trained through TIGHT market, N too small, no diversity)
- `lgbm_v12_noveg_train1215_0214` WATCH → let decay detection auto-handle

### 6. MLB Opening Day readiness confirmed (GREEN)
- `write_to_bigquery` fix verified correct
- `_get_regime_context()` safely returns defaults on Day 1 (no league_macro_daily data)
- Validator schedules fixed (3-10 includes Mar 27)
- Season resume script ready

---

## Tomorrow's Critical Action (Mar 24)

```bash
./bin/mlb-season-resume.sh --dry-run   # Preview first
./bin/mlb-season-resume.sh              # Execute — unpauses ~24 MLB scheduler jobs
```

**This MUST run before Opening Day (Mar 27).**

---

## Opening Day Verification (Mar 27)

### Evening after predictions (6-8 PM ET):
```sql
-- Predictions saved?
SELECT game_date, COUNT(*) as n FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 15-20 predictions

-- Best bets published?
SELECT game_date, COUNT(*) as picks FROM mlb_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 3-5 picks
```

### Morning after (Mar 28):
```sql
-- Grading complete?
SELECT game_date, COUNT(*) as graded FROM mlb_predictions.prediction_accuracy
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 15-20 graded
```

**Note:** `mlb_predictions.league_macro_daily` will be empty on Day 1 — regime context
returns safe defaults. Regime awareness kicks in after first games grade (~Mar 28).

---

## Key Active Constraints (unchanged from Session 483)

- `weekly-retrain` CF: **KEEP PAUSED** (retrain gate logic is backwards)
- OVER floor: **5.0** (auto-rises to 6.0 when vegas_mae < 4.5)
- `catboost_v9_low_vegas`: **DO NOT RE-ENABLE**
- CatBoost fleet (all `train0118_0315` variants): **KEEP DISABLED** — trained through
  TIGHT market, edge collapse likely, N=7-8 too small to be confident

---

## Remaining Pending Items

- [ ] `lgbm_v12_noveg_train1215_0214` deactivation → **Mar 25** (auto via decay-detection CF)
- [ ] MLB season resume → **Tomorrow Mar 24**
- [ ] MLB Opening Day verification → **Mar 27 evening + Mar 28 morning**
- [ ] Add `mlb_league_macro.py` auto-trigger post-MLB-grading (no CF trigger today)
- [ ] Playoffs: activate shadow mode → **Apr 14** (Scheduler reminder fires 9 AM ET)
- [ ] Playoffs: review shadow HR → **May 1** (Scheduler reminder fires 9 AM ET)

---

## New Gotchas (Session 484)

**`model_bb_candidates` is empty when 0 picks pass.** The table only stores picks that
survive all filters. Use `best_bets_filter_audit.rejected_json` to diagnose pick droughts —
it shows every filter and how many candidates it blocked.

**MLB `mlb_league_macro.py` has no auto-trigger.** Unlike NBA (post_grading_export runs
it automatically), the MLB version must be manually backfilled. Run:
```bash
PYTHONPATH=. .venv/bin/python ml/analysis/mlb_league_macro.py --date 2026-03-28
```
after first games grade if regime awareness is needed early in the season.

**signal_stack_2plus_obs is observation only.** When filter audit shows high counts of
`signal_stack_2plus_obs`, it means many picks have only 2 real signals — but this does
NOT block them. The actual blocker for OVER picks is `over_edge_floor`. For UNDER it's
individual negative filters.

---

## Session 484 Commits (2 total)
```
8af2c766 feat: MLB signal health tracker (ml/signals/mlb/signal_health.py)
3ee57011 fix: pre-commit YAML multi-doc, MLB write_to_bigquery, dominance alert
```
