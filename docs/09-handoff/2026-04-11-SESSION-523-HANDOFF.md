# Session 523 Handoff — MLB Pipeline Hardening + Over-Prediction Fix

**Date:** 2026-04-11
**Focus:** MLB grading pipeline bugs, cross-season feature contamination, system improvement roadmap
**Commits:** `56f401cc` through `dc8a6180` (4 commits on `main`)

---

## TL;DR

Fixed 6 MLB pipeline bugs including the root cause of +1.15 K over-prediction bias on OVER picks (37.5% HR). Cross-season feature contamination was feeding 2025 end-of-season stats as if current — 65% of predictions used features averaging 236 days stale. Also fixed scraper import deadlocks, pitcher name normalization mismatches, and BQ library Decimal serialization errors. MLB best bets are live and published at 3-0 (100%).

---

## What Was Done

### 1. MLB Grading Pipeline — 4 Bugs Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| **Box scores scraper silent failure** | `mlb-box-scores-daily` + `mlb-statcast-daily` both at `0 8 * * *` → Python `_ModuleLock` deadlock on cold start | Staggered: statcast `5 8`, schedule-yesterday `3 8`, reddit `5 11` |
| **Pitcher name mismatch** | Phase 2 `normalize_name()`: "J.T. Ginn" → `j_t_ginn` (periods→underscores) vs schedule API `jt_ginn` | Strip periods before underscore replacement + fuzzy fallback in grading |
| **signal_health Decimal→STRING** | BQ client 3.13.0 serializes `decimal.Decimal` as STRING in `load_table_from_json` | Upgraded to 3.40.0 + explicit Decimal→float conversion |
| **model_performance Decimal** | Same BQ 3.13.0 issue with `insert_rows_json` | Same upgrade + Decimal→float conversion |

### 2. Cross-Season Feature Contamination — Root Cause of Over-Prediction

**Problem:** `load_batch_features()` in `pitcher_loader.py` gets the most recent pitcher_game_summary row (up to 365 days back). For pitchers who haven't played in 2026, this returns September 2025 features:
- `season_games_started = 22` (full 2025 season)
- `season_k_per_9 = 8.49` (full 2025 season rate)
- `season_innings = 105` (full 2025 season IP)
- `month_of_season = 6` (September, not April)
- `days_into_season = 180` (late season, not early season)

The model, trained on June-September data, interpreted these as mid-season indicators → predicted 5.23 K avg vs 4.08 actual (+1.15 K bias).

**Fix:** 120-day staleness guard in the SQL query:
- Season-accumulation features (`season_games_started`, `season_strikeouts`, `season_innings`, `season_swstr_pct`, `season_csw_pct`) → NULL when feature row >120 days stale
- `season_k_per_9` → falls back to `k_per_9_rolling_10` (rolling stats still useful cross-season)
- `games_last_30_days` → 0 when >45 days stale
- `month_of_season` and `days_into_season` → computed from prediction date, not feature date
- CatBoost handles NaN natively via learned split directions

**Verified locally:** keider_montero (195 days stale) → `season_games_started=None`, `month_of_season=1`, `days_into_season=9`. tyler_glasnow (6 days stale) → all features preserved.

### 3. BQ Library Upgrade

Both grading services (NBA + MLB) upgraded from `google-cloud-bigquery==3.13.0` to `3.40.0`, matching Phase 2/3/4 services. Fixes Decimal serialization in `load_table_from_json` and `insert_rows_json`.

### 4. Grading Backfill

All dates Apr 1-10 re-graded with fuzzy name fallback. Apr 4-8 correctly show 0 graded (all predictions BLOCKED by quality gates — early season).

### 5. NBA Fleet Verification

Confirmed 4 new models from Session 522 have GCS files and are enabled in registry. Worker cache refreshed. Auto-halt active (avg edge 4.03). Season effectively over.

---

## System State

### MLB Pipeline
- **Best bets published:** 3-0 (100%) — jeffrey_springs, jt_ginn, keider_montero
- **Raw model:** 13-16 (44.8%) — OVER 37.5%, UNDER 80% (tiny N)
- **Cross-season fix deployed:** Will take effect on next prediction cycle (Apr 12)
- **Signal health:** 6 signals tracked for Apr 10, all NORMAL
- **Line coverage:** Apr 10 had 90% (27/30 starters) — best day yet. Earlier days had 0-27%.

### MLB Scheduler Collision Fixes
| Job | Old Schedule | New Schedule |
|-----|-------------|-------------|
| `mlb-statcast-daily` | `0 8 * * *` | `5 8 * * *` |
| `mlb-schedule-yesterday` | `0 8 * * *` | `3 8 * * *` |
| `mlb-reddit-discussion` | `0 11 * * *` | `5 11 * * *` |

### NBA Pipeline
- Auto-halt ACTIVE (avg edge 4.03 < 5.0) — zero BB picks
- Season record: **415-235 (63.8%)**
- 4 new fleet models registered + cache refreshed
- Last regular season games: Apr 12 (15 games)

---

## Commits

| SHA | What |
|-----|------|
| `56f401cc` | MLB grading 3-bug fix: pitcher lookup normalization, signal health Decimal, model perf Decimal |
| `3330dfcb` | signal_health comprehensive Decimal→float conversion at write level |
| `e0626074` | Upgrade grading services BQ library 3.13.0→3.40.0 |
| `dc8a6180` | MLB cross-season feature contamination fix in pitcher_loader.py |

---

## Continuation: What to Work on Next

### Priority 1: Validate the Cross-Season Fix (Apr 12)

Once Apr 12 predictions generate, compare:
```sql
-- Before fix: avg predicted_strikeouts for OVER picks should drop from ~5.23 to ~4.5
SELECT recommendation,
  ROUND(AVG(predicted_strikeouts), 2) as avg_predicted,
  ROUND(AVG(ABS(predicted_strikeouts - strikeouts_line)), 2) as avg_edge
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = '2026-04-12' AND strikeouts_line IS NOT NULL
GROUP BY 1
```

Expected: OVER predictions should center ~0.5-1.0 K above the line (not 1.15+ K).

### Priority 2: Retrain Decision (Apr 15)

The biweekly retrain fires Apr 15 (`mlb-biweekly-retrain` scheduler). With the feature fix in place, consider:
- **Include Apr 2026 data** in training window (the model currently trained on May-Sep 2025)
- **Expand training to include April months** from prior years (2022-2025 April data exists in `mlbapi_pitcher_stats`)
- The model trained on Jun-Sep is inherently biased toward mid-season K rates

### Priority 3: Model Quality Deep Dive

| Analysis | Why | How |
|----------|-----|-----|
| **Edge calibration** | Model MAE 1.85 vs Vegas 1.58 — is edge meaningful? | Plot model edge vs actual K margin per pick |
| **Feature importance** | Which features drive over-prediction? | `model.get_feature_importance()` on production model |
| **UNDER activation** | UNDER is 4-1 (80%) — structurally stronger? | Monitor for 2 more weeks, activate at N≥15 if HR holds |
| **Pitcher-type analysis** | Are certain pitcher archetypes more predictable? | Group by K/9, IP avg, starter experience |

### Priority 4: Signal System Maturation

Only 6 signals tracked. The MLB signal system has 20 active + 30 shadow signals. Check:
- Which signals are actually firing in best bets picks?
- Are any signals dead (never fire due to NULL supplemental data)?
- Signal health for all 50 signals, not just the 6 that have graded data

```sql
-- Check which signals appear in best bets picks
SELECT signal_tag, COUNT(*) as fires
FROM mlb_predictions.signal_best_bets_picks,
UNNEST(signal_tags) as signal_tag
WHERE game_date >= '2026-04-01'
GROUP BY 1 ORDER BY 2 DESC
```

### Priority 5: Line Coverage Monitoring

Apr 1-8 had terrible coverage (0-8 pitchers/day with lines). Apr 10 had 27/30 (90%). Verify this holds:
- Are both Odds API and BettingPros scrapers running daily?
- Is Phase 2 processing the props data correctly?
- Are lines arriving before prediction generation (1 PM ET)?

### Priority 6: NBA Off-Season Prep

Not urgent but worth doing:
- Verify weekly_retrain CF will auto-restart in October
- Check assists/rebounds data accumulation (started Apr 6)
- Plan first-week-of-season checklist for October

---

## Key Decisions Made

### Why 120 days for the staleness guard?
MLB offseason is ~150 days (Nov-Mar). Any feature row >120 days old is guaranteed to be from a prior season. Using days instead of season_year avoids hardcoding season boundaries.

### Why NULL instead of 0 for stale season features?
CatBoost handles NaN natively with learned split directions — it can learn "when season stats are missing, this pitcher is early-season." Setting to 0 would mean "zero games started" which is semantically different from "unknown."

### Why keep rolling stats (k_avg_last_5, era_rolling_10) for cross-season pitchers?
A pitcher's last 5-10 starts from 2025 are still informative about their skill level, even if the season context changed. The rolling K average from Sep 2025 is a better estimate than nothing.

---

## Files Changed

| Purpose | File |
|---------|------|
| Cross-season feature guard | `predictions/mlb/pitcher_loader.py` |
| Pitcher name normalization | `data_processors/raw/mlb/mlbapi_pitcher_stats_processor.py` |
| Batter name normalization | `data_processors/raw/mlb/mlbapi_batter_stats_processor.py` |
| Grading fuzzy fallback | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` |
| Signal health Decimal fix | `ml/signals/mlb/signal_health.py` |
| Model performance Decimal fix | `ml/analysis/mlb_model_performance.py` |
| MLB grading BQ library | `data_processors/grading/mlb/requirements.txt` |
| NBA grading BQ library | `data_processors/grading/nba/requirements.txt` + lock |

## Infrastructure Operations

| Operation | Detail |
|-----------|--------|
| Scheduler staggered | `mlb-statcast-daily` 0→5 min, `mlb-schedule-yesterday` 0→3 min, `mlb-reddit-discussion` 0→5 min |
| Box scores manually triggered | Apr 10: 132 pitcher records, 15 games |
| Phase 2 manually triggered | Apr 10: mlbapi_pitcher_stats populated |
| Grading backfilled | Apr 1-10 re-graded with fuzzy fallback |
| Signal health backfilled | Apr 10: 6 rows written locally |
| Worker cache refreshed | NBA new fleet (4 models) picked up |
