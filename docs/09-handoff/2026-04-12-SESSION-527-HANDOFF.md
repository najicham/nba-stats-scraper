# Session 527 Handoff — MLB Pipeline Deep Audit (8 Fixes + Game Lines Scheduler)

**Date:** 2026-04-12
**Focus:** Post-Session-526 follow-up: 4-agent review revealed systemic issues; 5-agent deep dive fixed them
**Commits:** `8ae780b5` → `365a6531` (3 commits, all pushed to main, all auto-deployed)

---

## TL;DR

Session 526 read-back triggered a 4-agent + 5-agent review cycle. Agents found 8 more issues across the MLB pipeline — two of them silent bugs that have existed since the signals were written. All fixed and deployed.

- **Critical (silent since day one):** `GameTotalLowOverSignal` and `HeavyFavoriteOverSignal` never fired — game_id STRING vs game_pk INT64 type mismatch in supplemental_loader.py
- **Critical (blocked retrain):** `bp_pitcher_props.actual_value = 0` for all 2026 games — scraper runs pre-game, grading never wrote back. Retroactively fixed 19 rows + added permanent backfill step.
- **Medium:** `_write_best_bets` used streaming insert after scoped DELETE — 90-min BQ buffer means same-day re-exports create dupes in `signal_best_bets_picks`
- **Medium:** `blacklist_shadow_picks` and `best_bets_filter_audit` accumulated duplicates on every pipeline run (no DELETE before insert)
- **Medium:** `ultra_tier`/`ultra_criteria`/`staking_multiplier` written by exporter but absent from BQ schema — load job would have silently failed
- **Medium:** Training script included zero-actual rows in validation holdout, producing nonsense governance metrics
- **Low:** Veteran pitchers on 2nd start of season blocked by `season_games_started == 0` guard (should be `is None`) — ~1-2 valid picks/day lost
- **Infrastructure:** `mlb_game_lines` scraper existed since Jan 2026 but had no scheduler — table was empty all season

---

## What Was Done (Chronological)

### Bug 1: `game_id` / `game_pk` type mismatch (`8ae780b5`)
`supplemental_loader.py::_load_game_context()` keyed its result dict by `row['game_id']` (STRING from `oddsa_game_lines`). The caller looked up by `game_pk` (INT64 from `mlb_schedule`). String key `"745629"` never matches integer key `745629`. Both `GameTotalLowOverSignal` and `HeavyFavoriteOverSignal` have been dead since they were written (Sessions 460/465).

**Fix:** `result[int(row['game_id'])] = {...}` — one-line cast.

### Bug 2: `_write_best_bets` streaming insert after DELETE (`8ae780b5`)
`best_bets_exporter.py::_write_best_bets` did: scoped DELETE (DML) → `insert_rows_json` (streaming). BQ streaming buffer is invisible to DML for 90 minutes. Same-day re-export couldn't delete buffered rows before adding new ones → duplicates.

**Fix:** Replaced `insert_rows_json` with `load_table_from_json` + `ignore_unknown_values=True` (same pattern as Session 526 grading processor fix).

### Bug 3: Shadow picks + filter audit accumulating dupes (`8ae780b5`)
`_write_shadow_picks` and `_write_filter_audit` both used plain `insert_rows_json` with no preceding DELETE. Every pipeline run appended rows. Multiple runs/day (morning + afternoon) accumulated duplicates in `blacklist_shadow_picks` and `best_bets_filter_audit`, inflating shadow HR and CF HR calculations.

**Fix:** Added `DELETE FROM table WHERE game_date = '{game_date}'` before each insert.

### Bug 4: `ultra_tier`/`ultra_criteria`/`staking_multiplier` not in BQ schema (`780c55a7`)
The exporter writes these 3 fields on every best bets run. They were absent from the `signal_best_bets_picks` schema SQL and absent from the live BQ table. `load_table_from_json` (the new write path from Bug 2 fix) fails on unknown fields by default — would have broken every best bets write on the first run.

**Fix:** `ALTER TABLE` to add the 3 columns to the live table + updated schema SQL file + added `ignore_unknown_values=True` to `LoadJobConfig` as a permanent safety guard.

### Bug 5: `bp_pitcher_props.actual_value = 0` for all 2026 games (`365a6531`)
**Root cause:** BettingPros scraper runs at 10:45 AM and 12:45 PM ET (pre-game). The API returns `actual=0` (not null) for unscored games. All 2025 data came from a historical backfill scraper. Live scraper only started writing in April 2026.

**Impact:** Retrain failed catastrophically (MAE=4.4, OVER HR=25%, N=19) because zero-actual rows were included in the validation holdout. Apr 9 had real actuals (6 rows); Apr 10-12 all zeros.

**Fix:** Added `_backfill_bp_pitcher_props()` to `MlbPredictionGradingProcessor.run()` as step 8. After every grading run, UPDATEs `bp_pitcher_props.actual_value=0` rows from `pitcher_game_summary.strikeouts` using `REPLACE`-normalized player_lookup JOIN (`shotaimanaga` ↔ `shota_imanaga`). Non-fatal. Retroactively fixed 19 rows (Apr 9-11). 4 rows remain zero (Luzardo, Imanaga, Marquez, McCullers — not in `pitcher_game_summary`, likely scratched).

### Bug 6: Training script included pre-game zeros in validation (`365a6531`)
Even with the backfill fix, rows scraped today (before today's grading runs) have `actual_value=0`. `WHERE bp.actual_value IS NOT NULL` passes these — validation holdout ends up with garbage rows that have never been graded.

**Fix:** Added `AND bp.actual_value > 0 AND bp.game_date < CURRENT_DATE()` to training query. Simple and correct.

### Bug 7: SKIP guard blocks veterans on 2nd start (`365a6531`)
`base_predictor.py` line 320: `if is_first_start or season_games == 0: skip`. When the feature store lags 1-2 days on updating `season_games_started`, veteran pitchers on their actual 2nd start appear with `season_games_started=0` and get SKIP'd. Feltner (edge +1.29), Fedde (+1.25), Junk (+1.23) were all blocked on Apr 11 by this.

**Fix:** Changed `season_games == 0` to `season_games is None`. True debut cases still caught by `is_first_start=True` and `rolling_stats_games < min_career_starts`.

**Note:** `ip_avg_last_5 < 4.0` threshold is separate and **appropriate** — Feltner (3.1 IP avg) and Junk (3.85 IP avg) are likely true short-outing starters. McCullers (3.8 IP avg) is injury-limited. These SKIP correctly.

### Infrastructure: `mlb-game-lines-morning` scheduler created (`gcloud`, no commit)
`mlb_game_lines` scraper existed since Jan 6, 2026 but had no Cloud Scheduler job. `mlb_raw.oddsa_game_lines` table was completely empty — `GameTotalLowOverSignal` and `HeavyFavoriteOverSignal` had no data to evaluate even after Bug 1 was fixed.

**Fix:** Created `mlb-game-lines-morning` scheduler — 10:30 AM ET daily — targeting the same `mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape` endpoint as other MLB scrapers. Fired immediately. Will populate starting Apr 13.

---

## System State

### Deployed Revisions
- `mlb-prediction-worker`: all fixes from Session 527 deployed (auto-deploy from push)
- `mlb-grading-service`: `_backfill_bp_pitcher_props()` deployed
- `nba-scrapers` (mlb scrapers): SKIP guard fix deployed

### MLB Pipeline Status (Apr 12 EOD)
- Apr 12 predictions: 26 rows (5 OVER, 12 UNDER, rest SKIP)
- Apr 11-12 best bets: 0 picks — correct behavior (away OVER edge floor 1.25K, best available edge was 1.36 with no signals)
- UNDER tracking: N=9, 66.7% HR (6 of 9 picks are ≤0.20K edge — noise, not signal)
- `bp_pitcher_props`: Apr 9-11 retroactively fixed; Apr 12 will be fixed by tomorrow's grading run
- `oddsa_game_lines`: scheduler just created, first data arrives Apr 13

### NBA
- Auto-halt active (avg edge 1.2-1.8, floor 5.0). Apr 12 was last regular season day.
- Playoffs start ~Apr 19. No code changes needed — pipeline handles `004%` game IDs natively.
- Apr 20 weekly retrain will attempt in season-restart mode (governance threshold lowered to 51%).

---

## What To Work On Next

### Priority 1: Verify Apr 13 pipeline (first run with all fixes)
Tomorrow's pipeline runs (10 AM grading, 1 PM predictions, 2 PM best bets) are the first with all 8 fixes live. Key things to verify:

```sql
-- Did game lines populate?
SELECT game_date, COUNT(*) as n, AVG(total_runs) as avg_total
FROM `nba-props-platform.mlb_raw.oddsa_game_lines`
WHERE game_date = '2026-04-13'
GROUP BY game_date

-- Did actual_value backfill run for Apr 12?
SELECT game_date, COUNTIF(actual_value > 0) as real_actuals, COUNT(*) as total
FROM `nba-props-platform.mlb_raw.bp_pitcher_props`
WHERE market_id = 285 AND game_date = '2026-04-12'
GROUP BY game_date

-- Did any SKIP pitchers now predict correctly (fewer SKIPs)?
SELECT recommendation, COUNT(*) as n
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date = '2026-04-13'
GROUP BY recommendation

-- Did new signals fire?
SELECT game_date, pitcher_name, signal_tags, edge
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date = '2026-04-13'
ORDER BY edge DESC
```

### Priority 2: UNDER enable threshold (target ~Apr 18-22)
UNDER is currently N=9, 66.7% HR. **The 66.7% is misleading** — 6 of 9 picks have edge ≤ 0.20K (near-zero conviction, essentially random). Only glasnow (-1.60K) and cabrera (-0.90K) had real edge, both correct.

**New rule before enabling:** Require edge ≥ 0.5K to count toward the N≥15 threshold. At ~2-3 qualifying UNDER picks/day with edge ≥ 0.5, the threshold will be hit around Apr 18-22.

Enable command (DO NOT run until N≥15 at edge ≥ 0.5K, HR ≥ 65%):
```bash
gcloud run services update mlb-prediction-worker --region=us-west2 \
  --update-env-vars="MLB_UNDER_ENABLED=true"
```

### Priority 3: Retrain timeline
**Do not retrain until ~May 1.** Rationale:
- Current model (Sep 2025) is still valid — DEGRADING not BLOCKED
- After actual_value backfill, valid 2026 rows are ~25. Need 200+ for meaningful calibration.
- At ~15 valid rows/day (after filters), 200 rows arrives ~May 1-5
- May retrain with `--training-start 2024-04-01 --training-end 2026-04-30` captures 2 Aprils (2024+2026) — important for April-specific K patterns

**Earliest governance-passing retrain (dry run):** ~Apr 17-20 once 30+ valid rows exist.

Retrain command when ready:
```bash
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
  --training-start 2024-04-01 \
  --training-end 2026-04-29 \
  --output-dir models/mlb/
```

### Priority 4: `elite_peripherals_over` + `high_csw_over` activation check (~May)
Both signals require `season_csw_pct` / FIP from FanGraphs. Signal has `NULL` blocker for early season. Check mid-May once pitchers have 5+ starts logged in 2026:
```sql
SELECT COUNT(*) as pitchers_with_season_csw
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
  AND season_csw_pct IS NOT NULL
```

### Priority 5: COALESCE fix for training script (optional improvement)
Agent A designed a COALESCE approach to pull actuals from `prediction_accuracy` when `bp.actual_value = 0`. This would recover ~12 additional training rows for Apr 1-11 that have actuals in `prediction_accuracy` but not in `bp_pitcher_props`. Not implemented yet — the `> 0` filter is sufficient for now and the COALESCE adds complexity. Implement before the May retrain if coverage is still low.

JOIN key if implementing: `REPLACE(bp.player_lookup, '_', '') = REPLACE(pgs.player_lookup, '_', '')` (strips underscores from both sides).

---

## Files Changed

| File | Change |
|------|--------|
| `predictions/mlb/supplemental_loader.py` | `game_id` cast to `int()` for game context lookup |
| `ml/signals/mlb/best_bets_exporter.py` | `_write_best_bets` → load job; shadow/filter audit DELETE before insert; `from google.cloud import bigquery` import |
| `schemas/bigquery/mlb_predictions/signal_best_bets_picks.sql` | Added `ultra_tier`, `ultra_criteria`, `staking_multiplier` columns |
| `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | Added `_backfill_bp_pitcher_props()` as step 8 in `run()` |
| `predictions/mlb/base_predictor.py` | SKIP guard: `season_games == 0` → `season_games is None` |
| `scripts/mlb/training/train_regressor_v2.py` | Added `AND bp.actual_value > 0 AND bp.game_date < CURRENT_DATE()` filters |
| **GCP (no commit)** | `mlb-game-lines-morning` scheduler created (10:30 AM ET daily) |
| **BQ (no commit)** | `ALTER TABLE signal_best_bets_picks` — added 3 ultra columns |
| **BQ (no commit)** | `UPDATE bp_pitcher_props` — 19 rows backfilled with real actuals |

---

## Lessons / Guardrails

- **Type mismatches between BQ table schemas are invisible at runtime.** STRING vs INT64 key lookups silently return empty dicts. Signals that depend on supplemental data fail quietly — they never fire and there's no error. Always verify signal fire rates in early monitoring.
- **Streaming insert after DML DELETE is a time bomb.** The 90-minute BQ streaming buffer means the DELETE cannot see recently-streamed rows. Any pattern of DELETE → `insert_rows_json` is a duplicate risk on same-day re-runs. Use `load_table_from_json` for production write paths.
- **Scrapers that run pre-game write zero actuals, not NULL.** `actual_value = 0` passes `IS NOT NULL` filters and silently corrupts training data. Any training script that uses a pre-game scraped table as the target variable needs `AND actual_value > 0`.
- **A scraper registered in the registry with no scheduler is dead.** `mlb_game_lines` existed for 3 months with no scheduler. Always verify that new scrapers have corresponding scheduler jobs after deployment.
- **`== 0` and `is None` are different for feature store values.** Feature store lag can leave valid pitchers with `season_games_started=0` even after their first start is graded. Guards that use `== 0` to catch "no data" cases will block pitchers who simply haven't propagated yet. Use `is None` for "truly missing" semantics.

---

## Memory Updates

- `memory/session-527.md` created with all 8 fixes documented
- `MEMORY.md` index updated
