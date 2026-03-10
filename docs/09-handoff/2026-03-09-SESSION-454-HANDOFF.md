# Session 454 Handoff — Feature Store Backfill + Walk-Forward Simulation

**Date:** 2026-03-09
**Session:** 454 (NBA)
**Status:** Feature store backfill COMPLETE. Walk-forward simulation BUILT and VALIDATED.

---

## What Was Done

### 1. Historical Odds Backfill

**Problem:** `odds_api_player_points_props` had zero data before May 2023. The 2022-23 season had no raw odds, so the feature store couldn't populate feature_25 (vegas_points_line).

**Solution:** Created `scripts/backfill_historical_odds.py` that inserts lines from `prediction_accuracy.line_value` into `odds_api_player_points_props` for dates without raw odds data.

**Result:** 13,191 rows inserted covering Nov 2022 - Jun 2023 (171 game dates). Bookmaker tagged as `historical_backfill`.

### 2. Full Feature Store Regeneration (3 Seasons)

**Problem:** Feature store had multiple issues:
- No vegas lines (feature_25-28) for 2022-23 season
- Quality scorer artifact: 2024-25 Mar-Jun had 0% clean rows (`required_default_count=1` for all)
- Older seasons had lower clean rates from outdated quality scoring

**Solution:** Created `scripts/regenerate_feature_store_parallel.py` — parallel regeneration using ThreadPoolExecutor (4 workers). Supports resume via progress file.

**Result:** 590/618 game dates regenerated successfully (2.6 hours). 28 failures are all season-opening dates (Oct) where insufficient prior games exist — expected and harmless.

**Before/After:**

| Month | Clean% Before | Clean% After | Lines Before | Lines After |
|-------|--------------|-------------|-------------|------------|
| 2022-12 | 47.3% | **96.4%** | 0 | **2,454** |
| 2023-01 | 49.4% | **97.3%** | 0 | **2,456** |
| 2023-03 | 51.6% | **94.5%** | 0 | **2,656** |
| 2025-03 | **0.0%** | **94.7%** | 3,636 | 3,636 |
| 2025-04 | **0.0%** | **96.7%** | 2,314 | 2,314 |
| 2025-05 | **0.0%** | **95.1%** | 638 | 638 |

### 3. Walk-Forward Simulation Built

**File:** `scripts/nba/training/walk_forward_simulation.py`

Architecture:
1. Load all feature store data upfront (chunked BQ queries to avoid timeout)
2. For each game date: check retrain → train CatBoost on rolling window → predict → grade
3. Test multiple configs (window sizes × retrain cadences)
4. Output: daily metrics CSV, predictions CSV, retrain log, summary JSON

**Key design decisions:**
- Feature set: V12_NOVEG (50 features, excludes vegas indices 25-28)
- Vegas line (feature_25_value) used only for HR grading, not training
- CatBoost production defaults: iterations=1000, lr=0.05, depth=6, l2=3
- Quality gate: `required_default_count = 0` (zero tolerance)
- 85/15 train/val split by date (not random)
- Data loaded in 6-month chunks to avoid BQ timeout

### 4. Walk-Forward Results — Cross-Season Validation

**Test:** Seed on 2022-23 season, predict through 2023-24 + 2024-25 (2 full seasons).

| Config | HR (edge 3+) | N | MAE | P&L | OVER | UNDER |
|--------|-------------|------|-----|------|------|-------|
| w42_r7 | 84.2% | 9,150 | 3.73 | +6,122 | 86.0% | 82.8% |
| w42_r14 | 82.6% | 9,309 | 3.80 | +5,913 | 84.8% | 80.9% |
| **w56_r7** | **85.0%** | **9,080** | **3.70** | **+6,222** | **87.0%** | **83.4%** |
| w56_r14 | 83.5% | 9,306 | 3.76 | +6,089 | 86.1% | 81.4% |
| w90_r7 | 85.3% | 8,743 | 3.70 | +6,049 | 87.3% | 83.6% |
| w90_r14 | 83.8% | 8,887 | 3.76 | +5,855 | 86.4% | 81.6% |

**Key findings:**
1. **56-day window + 7-day retrain is the sweet spot** — confirms production defaults
2. **7-day retrain consistently beats 14-day** by ~2pp
3. **Model generalizes across seasons** — consistent 85%+ mid-season
4. **Early season dip is predictable** — Nov-Dec drops to 48-57%, recovers by Jan
5. **OVER and UNDER both strong** — no directional bias

**Edge-HR curve (w56_r7):**

| Edge | HR | N | % of picks |
|------|-----|------|----------|
| 0-1 | 53.6% | 9,419 | 31% |
| 1-2 | 61.6% | 6,966 | 23% |
| 2-3 | 69.7% | 4,599 | 15% |
| 3-5 | 81.2% | 5,126 | 17% |
| 5-10 | 91.0% | 3,523 | 12% |

**Diagnostic checks:**
- Overall model HR (all edges): 67.4% — consistent with production
- Model MAE: 4.08 vs Line MAE: 4.95 — model beats market by 0.87 pts
- Model closer to actual than line: 72.4% of the time
- Edge 3+ is 30% of all predictions (~25 per game date)

**Important context:** These are RAW MODEL hit rates for ALL predictions at each edge threshold — not filtered through the best bets pipeline. Production best bets gets ~65% because it selects ~15 of ~25 edge 3+ picks per day through signals/filters/caps.

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `scripts/backfill_historical_odds.py` | Backfill odds_api table from prediction_accuracy |
| `scripts/regenerate_feature_store_parallel.py` | Parallel feature store regeneration (resume support) |
| `scripts/nba/training/walk_forward_simulation.py` | Walk-forward simulation engine |
| `results/nba_walkforward/` | All simulation outputs (6 configs) |

## Data Changes

| Table | Change |
|-------|--------|
| `nba_raw.odds_api_player_points_props` | +13,191 rows (2022-23 backfill, bookmaker='historical_backfill') |
| `nba_predictions.ml_feature_store_v2` | Regenerated 590 dates (Nov 2022 - Jun 2025) |

---

## What to Do Next

### Priority 1: Investigate BB Pipeline Gap
The raw model gets 85% HR at edge 3+ but best bets only gets ~65%. Understand where the 20pp is lost:
- Is the signal/filter pipeline degrading pick quality?
- Are rescue picks dragging down HR?
- Would a simpler "top N by edge" strategy outperform the current pipeline?

Run Layer 2 of the walk-forward: feed walk-forward predictions through `bin/replay_per_model_pipeline.py` to see what the pipeline does to them.

### Priority 2: Early Season Strategy
Nov-Dec HR is 48-57% each year. Investigate:
- Should we reduce volume in first 6 weeks?
- Can we use prior-season model as seed and reduce retrain cadence?
- The 56-day window means Nov predictions use mostly prior-season data

### Priority 3: 2025-26 Season Walk-Forward
Run the walk-forward with:
- Seed: 2024-25 season (Oct 2024 - Jun 2025)
- Simulate: 2025-26 season (Nov 2025 - Mar 2026)
- Compare to actual production results

### Priority 4: Observation Promotion
Still pending from Session 450. Wait for N >= 20-30 in `best_bets_filtered_picks`.

---

## Key Insights for Future Sessions

### Feature Store Coverage (Post-Backfill)

| Season | Total Rows | Clean% | Has Lines |
|--------|-----------|--------|-----------|
| 2022-23 | ~25K | 93% (mid-season) | ~2,300/mo |
| 2023-24 | ~26K | 93% (mid-season) | ~2,700/mo |
| 2024-25 | ~26K | 93% (mid-season) | ~2,800/mo |
| 2025-26 | ~30K | 72% | ~2,700/mo |

### Upstream Data Availability
- `player_daily_cache`: Nov 2021+
- `player_composite_factors`: Nov 2021+
- `player_shot_zone_analysis`: Nov 2021+
- `team_defense_zone_analysis`: Nov 2021+
- `odds_api_player_points_props`: Nov 2022+ (backfilled) / May 2023+ (original)
- `player_game_summary`: Oct 2022+
- `prediction_accuracy`: Nov 2022+ (100% line coverage for 2022-23)
