# Session 526 Handoff — MLB Pipeline Hardening (7 Bugs Fixed + Data Cleanup)

**Date:** 2026-04-12 (overnight session, bleeds into morning)
**Focus:** Systematic MLB pipeline audit triggered by investigating today's (Apr 12) readiness
**Commits:** `23f080c6` → `f0bde371` (7 commits, all pushed to main, all auto-deployed)

---

## TL;DR

What started as "verify the Apr 12 MLB pipeline is ready" turned into a 7-bug systematic cleanup. Every bug was real production data pollution or silent failure. All deployed and data cleaned.

- **Critical:** MLB best bets endpoint was returning 500s on Apr 11 (`effective_rescue_tags` scope bug, only triggered when any pitcher hit the blacklist filter)
- **Medium:** 1,168 duplicate prediction rows + 3 duplicate `prediction_accuracy` rows + 2 duplicate `model_performance_daily` rows
- **Medium:** 261 pitcher_name mismaps on Apr 10 (all non-starters got team's starter's name)
- **Low:** Silent column-name failure in supplemental loader, silent gap in best-bets grading
- Root-caused but NOT a bug: FanGraphs JOIN was fine, Phase 3 is fine, missing features warning only affects 1 pitcher

---

## What Was Done (Chronological)

### Bug 1: `effective_rescue_tags` scope error (`23f080c6`)
`ml/signals/mlb/best_bets_exporter.py::_evaluate_shadow_picks()` referenced a local var from the outer `export()` method. Python scoping — NameError. Only triggered when the blacklist filter blocked at least one pitcher (first time Apr 11 — previous days had empty blacklists). Apr 11 best bets failed with 500s until fix.

**Fix:** Added `effective_rescue_tags` as explicit parameter with `RESCUE_SIGNAL_TAGS` default.

### Bug 2: `oddsa_game_lines` wrong columns (`c3bb0b6d`)
`predictions/mlb/supplemental_loader.py::_load_game_context()` queried `game_pk`/`home_moneyline`/`away_moneyline`. Actual columns: `game_id`/`home_ml`/`away_ml`. Silent 400 error on every run — game total and moneyline signals never fired. Table is empty for 2026 anyway, but query would fail once data arrives.

**Fix:** Column names corrected. Added SQL alias to preserve the `home_moneyline`/`away_moneyline` naming downstream.

### Bug 3: 1,168 duplicate MLB predictions (`d6e3d088`)
An Apr 5 backfill re-wrote all Apr 1-4 predictions. Backfill used a write path that bypassed the `_count_predictions_for_date` guard (guard only existed on `/best-bets` endpoint). All duplicate rows were identical.

**Fix:** Moved dedup INTO `write_predictions_to_bigquery()` itself — now queries existing `pitcher_lookup`s for `game_date` before insert and filters them out. Protects ALL write paths (`/predict-batch`, `/best-bets`, `/pubsub`, future backfills). Fails open on dedup check error.

**Cleanup:** 1,168 rows DELETEd (kept earliest `created_at`). Verified zero remaining.

### Bug 4: `pitcher_name` mismapped (`b2ff2b7c`)
Session 519's fix populated `pitcher_name` from a schedule lookup with team-level fallback. The team fallback returned the STARTING pitcher's info for every non-starter on that team. Result on Apr 10: all LAD pitchers got `pitcher_name='Tyler Glasnow'`, all ATL got `'Bryce Elder'`, etc. 261 rows affected.

**Fix:** Team fallback retained for `game_id`/`is_home` (team-level facts), but `pitcher_name` now requires a direct pitcher match.

**Cleanup:** 261 rows NULLed on Apr 10 (can't recover correct individual names — they weren't in the schedule).

**Note:** Why only Apr 10 and not prior dates? Apr 1-9 had `pitcher_name=NULL` for everyone because an earlier query filter (Session 519 "only return pitchers with betting lines") wasn't deployed until Apr 10. So there was a 1-day window where the team-fallback bug fired on the full ~300 pitchers/day. Apr 11 onwards writes ~25 rows/day (starters only), so fallback doesn't trigger.

### Bug 5: MLB grading never graded `signal_best_bets_picks` (`ed6b6d10`)
Schema had `actual_strikeouts` and `prediction_correct` columns, but no code populated them. All 3 graded MLB best bets (Springs/Ginn/Montero) had NULL actuals despite `prediction_accuracy` having the data. Every consumer had to JOIN.

**Fix:** Added `_batch_update_best_bets()` that MERGEs actuals into `signal_best_bets_picks` keyed on `(pitcher_lookup, game_date, system_id)`. Called from `grade_predictions()` after `prediction_accuracy` write. Non-fatal on failure.

**Cleanup:** Backfilled 3 rows via one-shot MERGE. All 3 now show `prediction_correct=true`.

### Bug 6: `model_performance_daily` duplicates (`375de9fe`)
`ml/analysis/mlb_model_performance.py::write_rows()` used plain `insert_rows_json` with no dedup. Apr 10 had 3 rows from 3 separate analytics job runs.

**Fix:** Ported DELETE-before-write pattern from NBA version (`ml/analysis/model_performance.py`). Switched from streaming insert to load job so DELETE isn't blocked by streaming buffer.

**Cleanup:** 2 extra Apr 10 rows DELETEd.

### Bug 7: `prediction_accuracy` defense-in-depth (`f0bde371`)
`_batch_insert_accuracy` had DELETE+INSERT, but the DELETE was scoped to `game_date` — it couldn't protect against same-batch duplicates. When the original `pitcher_strikeouts` had dupes, grading iterated through both copies and emitted duplicate `prediction_accuracy` rows.

**Fix:** Added input dedup by `(pitcher_lookup, system_id)` before the DELETE+INSERT.

**Cleanup:** 3 existing prediction_accuracy dupes DELETEd.

---

## System State

### Deployed Revisions (as of end of session)
- `mlb-prediction-worker`: revision `00060-88d` (has bugs 1, 2, 3, 4 fixed; bugs 5-7 are in shared code / Cloud Function flow, not worker)
- Cloud Build is auto-deploying `f0bde371` (last commit)

### NBA
- Auto-halt correctly ACTIVE for Apr 12 — avg edge 1.2-1.8K across all models (floor 5.0)
- Apr 12 is last regular season day (15 games)
- Nothing to do — system handles playoffs/off-season automatically

### MLB
- 3 all-time best bets: 3-0 (Springs 6>4.5, Ginn 4>3.5, Montero 7>3.5) — now properly reflected in `signal_best_bets_picks`
- UNDER raw record: 3-1 (75%) on N=4 deduped (was inflated to 4-1 by the Eovaldi duplicate). Too small to enable.
- Raw OVER: 22 deduped graded, 36.4% HR — all old-model data. New model (April-inclusive) was deployed Apr 11 session 524.

---

## What To Work On Next (Priority Order)

### Priority 1: Validate Apr 12 MLB pipeline end-to-end

**Timeline today:**
- **10 AM ET**: `mlb-grading-daily` fires → grades Apr 11 games (6 UNDER + 14 OVER currently ungraded). **This will be the first real test of Bug 5 fix** — `signal_best_bets_picks` should get actuals populated for whichever picks ran yesterday (none actually cleared thresholds but if any did, they'll be properly graded).
- **1 PM ET**: `mlb-predictions-generate` fires → produces Apr 12 predictions. Check OVER bias:
  ```sql
  SELECT recommendation, COUNT(*) as n,
    ROUND(AVG(predicted_strikeouts - strikeouts_line), 2) as avg_bias
  FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
  WHERE game_date = '2026-04-12' AND strikeouts_line IS NOT NULL
  GROUP BY 1;
  ```
  Expected OVER bias: **near 0 ± 0.3K** (was +1.15K old model, +0.52K with new model yesterday).

- **2 PM ET**: `mlb-daily-best-bets-publish` fires → runs best bets for Apr 12. **This is the first run with all 7 fixes live.** Check:
  ```sql
  SELECT game_date, pitcher_name, team_abbr, edge, line_value, predicted_strikeouts,
    ARRAY_TO_STRING(signal_tags, ', ') as signals
  FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
  WHERE game_date = '2026-04-12'
  ORDER BY edge DESC;
  ```
  Expected: `elite_peripherals_over` should fire for qualifying starters for the first time. Multiple starters today likely qualify (FIP < 3.5, K/9 ≥ 9.0) — check `fangraphs_pitcher_season_stats` to see who.

### Priority 2: MLB UNDER tracking (still promising, still too small)

Currently 3-1 (75%) on N=4 deduped. Apr 11 has 6 UNDERs ungraded — tomorrow's grading run will push N toward 10. Need N≥15 at ≥65% HR before enabling.

Enable command (DO NOT run until N≥15):
```bash
gcloud run services update mlb-prediction-worker --region=us-west2 \
  --update-env-vars="MLB_UNDER_ENABLED=true"
```

### Priority 3: Biweekly retrain (due Apr 15)

```bash
PYTHONPATH=. .venv/bin/python3 scripts/mlb/training/train_regressor_v2.py \
  --training-start 2024-04-01 \
  --training-end 2026-04-13 \
  --output-dir models/mlb/
```

Note: `--training-start 2024-04-01` is mandatory — it captures 2 Aprils for early-season inclusion. Without this, model develops April-specific bias (Session 524 fixed this).

### Priority 4 (optional, if time): Recompute MPD with backfilled BB actuals

The `bb_hr_7d` / `bb_picks_7d` columns in `model_performance_daily` are NULL because they were computed before `signal_best_bets_picks` had actuals. Now that actuals are backfilled, a recomputation would populate them:

```bash
PYTHONPATH=. .venv/bin/python3 ml/analysis/mlb_model_performance.py \
  --target-date 2026-04-10 --backfill
```

(Low priority — NBA pattern historically uses JOIN for BB HR anyway.)

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/mlb/best_bets_exporter.py` | `_evaluate_shadow_picks` takes `effective_rescue_tags` param |
| `predictions/mlb/supplemental_loader.py` | `oddsa_game_lines` column names corrected |
| `predictions/mlb/worker.py` | Per-pitcher dedup in `write_predictions_to_bigquery` + `pitcher_name` only from direct schedule match |
| `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | Added `_batch_update_best_bets` + input dedup in `_batch_insert_accuracy` |
| `ml/analysis/mlb_model_performance.py` | DELETE-before-write pattern |

---

## Lessons / Guardrails

- **Dedup must live at the write layer**, not the endpoint layer. Any of 3 write paths + future backfills will now hit the guard.
- **Batch INSERT patterns without DELETE-first create silent duplicate accumulation over time.** MPD and prediction_accuracy both had this pattern and both had duplicates. Worth auditing any other `insert_rows_json` calls for the same issue.
- **Fallback lookups need to distinguish entity-level vs group-level fields.** The `sched_by_team` fallback was fine for `game_id`/`is_home` (group-level) but wrong for `pitcher_name` (entity-level). This pattern likely recurs.
- **Schema columns that nothing populates are dead.** `signal_best_bets_picks.actual_strikeouts` existed for months with no code writing to it. Worth auditing other "defined but NULL" columns.

---

## Memory Updates

- `memory/session-526.md` created with all 7 fixes documented
- `MEMORY.md` index updated with pointer to session 526
