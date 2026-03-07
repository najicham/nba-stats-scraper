# MLB Sprint 1 Handoff — Data Foundation & Architecture Review

**Date:** 2026-03-06
**Session Focus:** MLB Pitcher Strikeouts — Sprint 1 of 4-sprint plan
**MLB Season Start:** 2026-03-27 (21 days)

---

## What Was Done

### Decision: What to Build Next

Evaluated 3 options: MLB Strikeouts (finish), NBA Game Totals, MLB Game Totals. **MLB Strikeouts won** — 95% built, 5-6 hours to launch, season starts in 21 days. MLB Game Totals next (richer features than NBA totals due to weather/park/umpire data). NBA Totals last (most efficient market).

### Sprint 1 Deliverables (16 files)

**3 New Scrapers:**

| Scraper | File | Replaces |
|---------|------|----------|
| `mlb_box_scores_mlbapi` | `scrapers/mlb/mlbstatsapi/mlb_box_scores.py` | BDL `mlb_pitcher_stats` + `mlb_batter_stats` + `mlb_box_scores` (3-in-1) |
| `mlb_statcast_daily` | `scrapers/mlb/statcast/mlb_statcast_daily.py` | Enhances single-pitcher Statcast scraper to daily batch |
| `mlb_reddit_discussion` | `scrapers/mlb/external/mlb_reddit_discussion.py` | New — r/sportsbook, r/baseball, r/fantasybaseball |

**3 New Processors:**

| Processor | File | Target Table |
|-----------|------|--------------|
| `MlbApiPitcherStatsProcessor` | `data_processors/raw/mlb/mlbapi_pitcher_stats_processor.py` | `mlb_raw.mlbapi_pitcher_stats` |
| `MlbApiBatterStatsProcessor` | `data_processors/raw/mlb/mlbapi_batter_stats_processor.py` | `mlb_raw.mlbapi_batter_stats` |
| `MlbStatcastDailyProcessor` | `data_processors/raw/mlb/mlb_statcast_daily_processor.py` | `mlb_raw.statcast_pitcher_daily` |

**8 New BigQuery Schemas:**

| Schema File | Table |
|-------------|-------|
| `schemas/bigquery/mlb_predictions/prediction_accuracy.sql` | `mlb_predictions.prediction_accuracy` |
| `schemas/bigquery/mlb_predictions/model_registry.sql` | `mlb_predictions.model_registry` |
| `schemas/bigquery/mlb_predictions/model_performance_daily.sql` | `mlb_predictions.model_performance_daily` |
| `schemas/bigquery/mlb_predictions/signal_health_daily.sql` | `mlb_predictions.signal_health_daily` |
| `schemas/bigquery/mlb_predictions/signal_best_bets_picks.sql` | `mlb_predictions.signal_best_bets_picks` |
| `schemas/bigquery/mlb_predictions/best_bets_filter_audit.sql` | `mlb_predictions.best_bets_filter_audit` |
| `schemas/bigquery/mlb_raw/mlbapi_stats_tables.sql` | `mlb_raw.mlbapi_pitcher_stats` + `mlb_raw.mlbapi_batter_stats` |
| `schemas/bigquery/mlb_raw/statcast_pitcher_daily_tables.sql` | `mlb_raw.statcast_pitcher_daily` |

**1 Master Plan + 1 Updated Doc:**
- `docs/08-projects/current/mlb-pitcher-strikeouts/2026-03-MLB-MASTER-PLAN.md` (29KB comprehensive plan)
- `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md` (updated)

**1 Modified Registry:**
- `scrapers/mlb/registry.py` — 31 scrapers (was 28), updated priority list

### Bug Fixes Applied

1. **Lifecycle fix** — Statcast + Reddit scrapers defined `download()` but base class calls `download_and_decode()`. Renamed to `download_and_decode()` so the code actually runs.
2. **game_pk type** — Changed STRING → INT64 in `prediction_accuracy.sql` and `signal_best_bets_picks.sql` to match MLB Stats API (returns integer).
3. **K_KEYWORDS noise** — Removed overly broad 'over'/'under' from Reddit scraper keywords, added specific patterns like 'k prop', 'over .5'.

---

## Architecture Review Findings (Prioritized)

Two review agents critically evaluated the plan and found 22 improvements. Key findings:

### BLOCKING — Must Fix Before Launch

| # | Issue | Where | Fix |
|---|-------|-------|-----|
| 1 | **Default feature contamination** | `predictions/mlb/prediction_systems/v1_baseline_predictor.py` line 32: `FEATURE_DEFAULTS` dict silently substitutes defaults. `scripts/mlb/training/walk_forward_validation.py` line 181: `fillna(X.median())` contaminates training data. | Port NBA's zero-tolerance: count defaults per prediction, block when `default_feature_count > 0`. Fix training to drop NaN rows not fill them. |
| 2 | **Grading lacks void logic** | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | Rain-shortened games (pitcher pulled after 4 IP), postponements, and suspended games produce incorrect grades. Sportsbooks void props when pitcher doesn't complete min innings. Add void logic. |
| 3 | **Statcast backfill gap** | `mlb_raw.statcast_pitcher_game_stats` only has data through Jun 2025 | Walk-forward can't evaluate Jul-Aug drift without Jul-Sep 2025 Statcast. Backfill using pybaseball: `statcast(start_dt='2025-07-01', end_dt='2025-09-28')` |
| 4 | **Grading DML locks** | `mlb_prediction_grading_processor.py` lines 166-178 | Row-by-row UPDATE will lock during catch-up. Batch the writes like NBA does. |

### HIGH — Before Opening Day

| # | Issue | Action |
|---|-------|--------|
| 5 | **Catcher framing** | Elite framers add 1-2 called strikes/game. Scrape from Baseball Savant. Higher impact than originally estimated — promote to Phase 1 feature. |
| 6 | **Pitch count limits** | Teams cap young pitchers at 80-85 pitches. Directly caps K upside. Add as negative filter: `pitch_count_limit_under` — skip OVER when pitcher has documented limit. |
| 7 | **CLV tracking** | MLB has line timing infrastructure (`line_minutes_before_game`) but no CLV signal. Port NBA CLV pattern immediately. |
| 8 | **Signal shadow period** | Don't start all 14 signals active. 8 active + 6 shadow. Signals need 30+ days before promotion (NBA lesson). |
| 9 | **Market efficiency monitor** | Root cause of Jul-Aug 2025 drift was market efficiency improving. Add daily tracking: avg |model edge|, % predictions with edge > 1.0 K, 14d trend. |
| 10 | **Edge threshold sweep** | Don't assume 1.0 K. Test 0.5, 0.75, 1.0, 1.5, 2.0 in walk-forward simulation. |

### MEDIUM — First 2 Weeks of Season

| # | Issue | Notes |
|---|-------|-------|
| 11 | Bullpen tiredness feature | Tired bullpen = longer starter outing = more Ks. Binary: "bullpen used 4+ pitchers yesterday" |
| 12 | Day-after-night for opposing team | Hitters strike out more. Schedule data already exists. |
| 13 | Early hook UNDER signal | Manager avg IP < 5.0 recent starts → K ceiling capped |
| 14 | Training window 90d/120d test | 56d = ~11 starts per pitcher. Too thin. Test longer windows. |
| 15 | September mode | Raise min career starts to 5, reduce confidence 20%, skip eliminated teams |

### DE-PRIORITIZED

| # | Issue | Why |
|---|-------|-----|
| 16 | Reddit scraping | Low ROI vs engineering effort. Keep as experimental shadow signal. |
| 17 | Travel distance feature | Marginal effect. Shadow signal at best. |
| 18 | DFS ownership % | Noisy proxy. Action Network/Covers data is better. |

### Model Architecture Insights

- **Classification > Regression** — Current XGBoost V1.6 is a classifier (target: `went_over`). Plan proposed switching to CatBoost regressor. Reviewer recommends keeping classification primary (you only need direction vs line, not exact count). Regression supplements for edge calculation.
- **Training window risk** — 56 days = ~11 data points per pitcher. Universal model is the only viable approach (150 starters, each starts every 5 days). But need to test 90d/120d/full-season windows.
- **Pitcher tier governance** — Add separate governance gates for aces (top 20% K/9), mid-rotation, back-end starters.

### Operational Risks Identified

- **Rain-shortened games** — If game called after 5 innings, pitcher may have only 3-4 Ks. Sportsbooks void. Our grading doesn't.
- **`innings_pitched` is MLB string notation** — "6.1" means 6 and 1/3 innings (not 6.1). Downstream float parsing will be wrong. Need conversion utility.
- **Opener/bullpen games increasing** — Current detection (IP avg < 4.0) is good but should also check role designation and recent usage pattern.
- **September call-ups** — Flood system with unknown pitchers. Need stricter filters.
- **Postseason dynamics** — Longer rest (6-7d), higher pitch counts, adrenaline velocity boost (+1-2 mph). Consider postseason confidence adjustment.

---

## Current MLB System State

### What Exists (Pre-Sprint 1)

| Component | Status |
|-----------|--------|
| 31 scrapers (BDL + MLBAPI + OddsAPI + External + Statcast) | Working but BDL unreliable |
| Analytics: pitcher_game_summary (85 cols), batter_game_summary (64 cols) | Working |
| Feature store: pitcher_ml_features (35 features) | Working |
| Models: V1.4 champion (57.9% HR), V1.6 challenger (69.9% HR) | V1.6 not promoted |
| Shadow mode runner | Working |
| 20+ Cloud Scheduler jobs | All PAUSED |
| Prediction worker | Not deployed since Jan 15 |

### What's Missing (Gap vs NBA)

| Component | NBA Has | MLB Has |
|-----------|---------|---------|
| `prediction_accuracy` table | 419K+ records | Schema created (Sprint 1), no data |
| Model registry | Full governance | Schema created (Sprint 1), empty |
| Model performance daily + decay | Auto-disable on BLOCKED | Schema created (Sprint 1) |
| Signal system (28 active + 26 shadow) | Full pipeline | Nothing — no signals at all |
| Best bets pipeline | Edge + signals + filters + angles | Nothing |
| Zero-tolerance defaults | 3 enforcement layers | Silently substitutes defaults |
| Grading void logic | DNP/injury voiding | No void handling |

---

## Sprint 2 Plan (Next Session)

**Goal:** Model architecture, signal system, walk-forward simulation prep.

### Sprint 2a: Fix Blocking Issues (2-3 hours)

1. **Fix default feature contamination**
   - Add `default_feature_count` tracking to `v1_baseline_predictor.py` and `v1_6_rolling_predictor.py`
   - Remove `fillna(X.median())` from `walk_forward_validation.py` — drop rows with NaN instead
   - Add quality gate: block predictions with `default_feature_count > 0`

2. **Fix grading void logic**
   - Add to `mlb_prediction_grading_processor.py`:
     - `is_voided = True` when pitcher IP < 4.0 (short start)
     - `void_reason = 'rain_shortened'` when game status indicates weather
     - `void_reason = 'postponed'` when game never completed
   - Batch DML writes instead of row-by-row

3. **Backfill Statcast Jul-Sep 2025**
   - Run: `PYTHONPATH=. python scrapers/mlb/statcast/mlb_statcast_daily.py --start_date 2025-07-01 --end_date 2025-09-28`
   - Process through `MlbStatcastDailyProcessor`

### Sprint 2b: Signal System (3-4 hours)

4. **Create MLB signal registry** — Port `ml/signals/registry.py` pattern
5. **Build 8 active signals:**
   - `high_edge` (edge >= 1.0 K)
   - `swstr_surge` (SwStr% last 3 > season avg + 2%)
   - `velocity_drop_under` (FB velocity down 1.5+ mph)
   - `opponent_k_prone` (team K-rate top 25%)
   - `short_rest_under` (< 4 days rest)
   - `high_variance_under` (K std > 3.5 last 10)
   - `ballpark_k_boost` (park K-factor > 1.05)
   - `umpire_k_friendly` (umpire K-rate top 25%)

6. **Build 6 shadow signals:**
   - `line_movement_over`, `weather_cold_under`, `platoon_advantage`
   - `ace_pitcher_over`, `catcher_framing_over`, `pitch_count_limit_under`

7. **Build negative filters:**
   - `bullpen_game_skip` (opener/bullpen game)
   - `il_return_skip` (first start from IL)
   - `pitch_count_limit_under` (documented cap)
   - `insufficient_data_skip` (< 3 starts)

### Sprint 2c: Best Bets Pipeline (2-3 hours)

8. **Port `signal_best_bets_exporter.py`** for MLB
9. **Build pick angle builder** for MLB
10. **Wire grading to `prediction_accuracy` table**

### Sprint 2d: Walk-Forward Prep (2-3 hours)

11. **Build `mlb/training/walk_forward_simulation.py`**
12. **Test training windows:** 42, 56, 90, 120 days
13. **Edge threshold sweep:** 0.5, 0.75, 1.0, 1.5, 2.0 K
14. **Run simulation on Apr-Jun 2025** (data-complete period)

---

## Key Files Reference

### New Files (Sprint 1)

```
scrapers/mlb/mlbstatsapi/mlb_box_scores.py        # MLB Stats API box scores (BDL replacement)
scrapers/mlb/statcast/mlb_statcast_daily.py        # Daily batch Statcast
scrapers/mlb/external/mlb_reddit_discussion.py     # Reddit community intel

data_processors/raw/mlb/mlbapi_pitcher_stats_processor.py
data_processors/raw/mlb/mlbapi_batter_stats_processor.py
data_processors/raw/mlb/mlb_statcast_daily_processor.py

schemas/bigquery/mlb_predictions/prediction_accuracy.sql
schemas/bigquery/mlb_predictions/model_registry.sql
schemas/bigquery/mlb_predictions/model_performance_daily.sql
schemas/bigquery/mlb_predictions/signal_health_daily.sql
schemas/bigquery/mlb_predictions/signal_best_bets_picks.sql
schemas/bigquery/mlb_predictions/best_bets_filter_audit.sql
schemas/bigquery/mlb_raw/mlbapi_stats_tables.sql
schemas/bigquery/mlb_raw/statcast_pitcher_daily_tables.sql
```

### Critical Files to Fix (Sprint 2)

```
predictions/mlb/prediction_systems/v1_baseline_predictor.py    # Remove FEATURE_DEFAULTS
predictions/mlb/prediction_systems/v1_6_rolling_predictor.py   # Same
scripts/mlb/training/walk_forward_validation.py                # Fix fillna(median) at line 181
data_processors/grading/mlb/mlb_prediction_grading_processor.py # Add void logic, batch DML
predictions/mlb/config.py                                      # Edge thresholds, red flags
```

### Master Plan

```
docs/08-projects/current/mlb-pitcher-strikeouts/2026-03-MLB-MASTER-PLAN.md  # Full 4-sprint plan
docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md           # Updated status
```

---

## Quick Start for Next Session

```bash
# 1. Read the master plan
cat docs/08-projects/current/mlb-pitcher-strikeouts/2026-03-MLB-MASTER-PLAN.md

# 2. Start with blocking issues
# Fix default feature contamination in predictors
# Fix grading void logic
# Backfill Statcast Jul-Sep 2025

# 3. Create BQ tables
# Run all SQL files in schemas/bigquery/mlb_predictions/
# Run schemas/bigquery/mlb_raw/mlbapi_stats_tables.sql
# Run schemas/bigquery/mlb_raw/statcast_pitcher_daily_tables.sql

# 4. Build signal system
# Port ml/signals/registry.py for MLB
# Build 8 active + 6 shadow signals
# Build best bets pipeline
```
