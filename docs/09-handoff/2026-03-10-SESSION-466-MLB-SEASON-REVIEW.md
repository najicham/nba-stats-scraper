# MLB 2026 Season Review & Improvement Plan

**Date:** 2026-03-10
**Purpose:** Full system review for incoming chat — understand the MLB prediction system end-to-end, identify improvement opportunities, and plan for opening day (March 27).

## System Overview

We predict MLB pitcher strikeouts (OVER/UNDER) using a CatBoost regressor, filtered through a signal-based best bets pipeline. The system is OVER-only for now.

**4-season replay performance:** 63.4% HR, 1538-916, +470.7u, 12.8% ROI. All 4 seasons profitable.

## Architecture

```
Scrapers (18) → GCS JSON → BQ Raw Tables → Analytics (pitcher_game_summary)
                                                    ↓
BettingPros Props → Feature Assembly (40 features) → CatBoost Regressor → Predictions
                                                    ↓
                              Supplemental Data (umpire, weather, game context, catcher framing)
                                                    ↓
                              Signal Evaluation (20 active + 30 shadow) → Negative Filters (6)
                                                    ↓
                              Best Bets Pipeline (edge floor → rescue → RSC gate → rank → cap)
                                                    ↓
                              signal_best_bets_picks (BQ) + /best-bets endpoint (JSON)
```

## Model

**Type:** CatBoost V2 Regressor — predicts raw strikeout count, not classification.

**Features (40):**

| Category | Features | Key Ones |
|----------|----------|----------|
| Rolling K stats | f00-f04 | k_avg_last_3, k_avg_last_5, k_std_last_10, ip_avg_last_5 |
| Season stats | f05-f09 | season_k_per_9, era, whip, games_started |
| Game context | f10, f25 | is_home, is_day_game |
| Opponent/park | f15-f16 | opponent_k_rate, ballpark_k_factor |
| Statcast | f19, f19b, f50-f53 | swstr_pct, csw_pct, swstr_trend, velocity_change |
| Workload | f20-f23 | days_rest, games_last_30, pitch_count_avg, season_ip |
| Line-relative | f30, f32 | k_avg_vs_line, line_level |
| Projections | f40-f44 | bp_projection, projection_diff, over_implied_prob |
| Vs opponent | f65-f66 | vs_opp_k_per_9, vs_opp_games |
| FanGraphs | f70-f73 | o_swing_pct, z_contact_pct, fip, gb_pct |

**Hyperparameters (Session 459 walk-forward validated):**
- depth=4, lr=0.015, iters=500, l2_leaf_reg=10, subsample=0.8, loss=RMSE

**Training:**
- 120-day rolling window, 14-day retrain interval
- Data: `bp_pitcher_props` JOIN `pitcher_game_summary` JOIN `statcast_rolling` JOIN `fangraphs_pitcher_season_stats`
- Filter: IP >= 3.0, rolling_stats_games >= 3, actual/line/projection all non-null
- Governance: MAE < 2.0, OVER HR >= 55% at edge >= 0.75, N >= 30

**Key files:**
- Training: `scripts/mlb/training/train_regressor_v2.py`
- Replay: `scripts/mlb/training/season_replay.py`
- Worker: `predictions/mlb/worker.py`

## Best Bets Pipeline

**File:** `ml/signals/mlb/best_bets_exporter.py`

Pipeline flow:
1. Load predictions for game_date
2. Direction filter (OVER only — UNDER disabled)
3. **Overconfidence cap:** edge > 2.0 K blocked (edge 2.0+ = 48-58% HR, losing)
4. **Probability cap:** p_over > 0.85 blocked
5. **Negative filters** (6): bullpen_game, il_return, pitch_count_cap, insufficient_data, pitcher_blacklist (28), whole_line_over
6. **Edge floor:** Home 0.75 K, Away 1.25 K (with rescue for home only)
7. **Signal evaluation:** 20 active + 30 shadow signals
8. **RSC gate:** real_signal_count >= 2 (OVER) or >= 3 (UNDER)
9. **Rank:** by pure edge (composite scoring failed cross-season validation)
10. **Cap:** top 5 per day
11. **Ultra tier:** home + proj_agrees + edge >= 0.5 + not rescued

**Key thresholds:**

| Parameter | Value | Why |
|-----------|-------|-----|
| Edge floor (home) | 0.75 K | Walk-forward sweet spot |
| Edge floor (away) | 1.25 K | Away pitchers 54.1% HR baseline (10pp worse than home) |
| Max edge | 2.0 K | Overconfident predictions lose money |
| Max picks/day | 5 | Rank 5 still profitable (58.4% HR, +32u cross-season) |
| RSC gate | >= 2 | RSC=2 is actually 75.9% HR (best bucket!) |
| Away rescue | BLOCKED | Away rescued picks = 51% HR cross-season |
| Rescue signal | opponent_k_prone only | All others removed (< 55% solo HR) |

## Signal System

**File:** `ml/signals/mlb/signals.py` (~2000 lines), `ml/signals/mlb/registry.py`

### 20 Active Signals

| Signal | Direction | Mechanism | Cross-Season HR |
|--------|-----------|-----------|----------------|
| high_edge | OVER/UNDER | Edge >= 1.0 K (BASE — inflates SC) | N/A |
| opponent_k_prone | OVER | Team K-rate >= 24% (RESCUE signal) | 63.5% |
| projection_agrees_over | OVER | BettingPros proj > line + 0.5 | 65.1% |
| regressor_projection_agrees | OVER | Projection value > line | 64.8% |
| home_pitcher_over | OVER | Pitcher is at home | 64.2% |
| recent_k_above_line | OVER | K avg last 5 > line | 63.1% |
| high_csw_over | OVER | CSW% >= 30% | 64.7% |
| elite_peripherals_over | OVER | FIP < 3.5 + K/9 >= 9.0 | 66.4% |
| pitch_efficiency_depth_over | OVER | IP avg >= 6.0 | 66.2% |
| day_game_shadow_over | OVER | Day game visibility stress | 61.5% |
| pitcher_on_roll_over | OVER | K avg L3 AND L5 > line | 63.5% |
| **xfip_elite_over** | OVER | **xFIP < 3.5 (S465 promoted)** | **67.5% (N=704)** |
| **day_game_high_csw_combo** | OVER | **Day game + CSW >= 30% (S465)** | **73.0% (N=122)** |
| ballpark_k_boost | OVER | Park K-factor > 1.05 | 62.8% |
| umpire_k_friendly | OVER | Umpire K-rate top 25% | ~64% (partial) |
| velocity_drop_under | UNDER | FB velocity down 1.5+ mph | N/A |
| short_rest_under | UNDER | < 4 days rest | N/A |
| high_variance_under | UNDER | K std > 3.5 last 10 | N/A |
| k_trending_over | OVER | K avg L3 > L10 + 1.0 (TRACKING_ONLY) | 55.6% |
| long_rest_over | OVER | 8+ days rest (TRACKING_ONLY) | 55.4% |

### 30 Shadow Signals (tracking data, not counting toward RSC)

Key ones to watch during paper trading:
- `day_game_elite_peripherals_combo_over` — 72.0% HR (N=182) but 2023: 55.2%
- `high_csw_low_era_high_k_combo_over` — 70.6% HR (N=170) but 2023: 50.0%
- `umpire_csw_combo_over` — 80.0% in partial data (N=10)
- `k_rate_bounce_over` — 76.1% HR (N=46) but low N
- `catcher_framing_over/poor_under` — waiting for data (scraper ready)
- `chase_rate_over`, `contact_specialist_under` — Session 464 additions

### 6 Negative Filters

| Filter | What it blocks | Why |
|--------|---------------|-----|
| bullpen_game_skip | Opener/bullpen games | No true starter = unpredictable Ks |
| il_return_skip | First start from IL | Pitch count limited, rusty |
| pitch_count_cap_skip | UNDER with documented cap | Cap = known low K ceiling |
| insufficient_data_skip | < 3 career starts | No rolling features |
| pitcher_blacklist | 28 specific pitchers | Walk-forward < 45% HR |
| whole_line_over | Whole-number OVER lines | +9.6pp structural bias |

### 28-Pitcher Blacklist

Pitchers with < 45% HR in walk-forward replay. Includes: tanner_bibee, logan_webb, mitchell_parker, casey_mize, logan_gilbert, jake_irvin, george_kirby, bailey_ober, blake_snell, paul_skenes, and 18 others.

## Supplemental Data

**File:** `predictions/mlb/supplemental_loader.py`

| Data | Source Table | Signal(s) | Status |
|------|-------------|-----------|--------|
| Umpire K-rate | `mlb_umpire_assignments` + `mlb_umpire_stats` | umpire_k_friendly | Ready (2025 backfill done) |
| Weather | `mlb_raw.mlb_weather` | weather_cold_under, cold_weather_k_over | Ready |
| Game context | `mlb_raw.oddsa_game_lines` | game_total_low_over, heavy_favorite_over | Ready |
| Catcher framing | `mlb_raw.catcher_framing` | catcher_framing_over/poor_under | Ready (scraper tested) |

## Scrapers (18 total)

| Category | Scrapers | Status |
|----------|----------|--------|
| MLB Stats API (3) | schedule, lineups, game_feed | Ready, PAUSED |
| Odds API (8) | events, game_lines, pitcher_props, batter_props (+historical each) | Ready, PAUSED |
| External (4) | weather, ballpark_factors, umpire_stats, catcher_framing | Ready, PAUSED |
| Statcast (2) | statcast_pitcher, statcast_daily | Ready, PAUSED |
| Supplemental (3) | box_scores, umpire_assignments, reddit_discussion | Ready, PAUSED |

**24 Cloud Scheduler jobs** — all PAUSED, resume Mar 24 via `./bin/mlb-season-resume.sh`

## Bootstrap Period

The system needs ~6-7 weeks to reach full performance:

| Period | BB HR | Picks/Day | Bottleneck |
|--------|-------|-----------|------------|
| Week 0-2 (Mar 27 - Apr 14) | ~56% | ~3 | Pitchers need 3+ starts for rolling features |
| Week 3-7 (Apr 15 - May 14) | ~58% | ~5 | Season stats (xFIP, CSW) still noisy |
| Week 8+ (May 15+) | ~68% | ~5 | Full signal coverage, stable features |

**Cumulative convergence:** HR crosses 63% at ~pick #200 (late May).

## Known Dead Ends (DO NOT retry)

| Idea | Result | Why |
|------|--------|-----|
| Adding features to model | Hurts HR | V12_noveg > V13 > V15 > V16 pattern |
| Dynamic pitcher blacklist | Only 3 suppressed | Not worth the complexity |
| Away edge floor changes | All within noise | 1.0/1.25/1.5 are equivalent |
| Raising RSC gate to 3 | RSC=2 is best bucket | 75.9% HR at RSC=2 |
| Composite scoring for ranking | Fails cross-season | Pure edge ranking is robust |
| ballpark_k_boost as rescue | 41.2% solo HR | Removed |
| swstr_surge as active | 55.2% HR cross-season | Demoted to shadow |
| xfip_regression_over (ERA >> xFIP) | Structurally broken | High-ERA pitchers get UNDER recs |
| Umpire signal as active | -1.7pp HR, -33u | Inflates RSC, lets marginal picks through |
| bench_under signal | Look-ahead bias | Used post-game starter_flag |

## Improvement Opportunities

### High Priority (Before Opening Day)

1. **Retrain model with fresh data** (CRITICAL)
   - Current model trained through Sep 2025. Need data through Mar 20.
   - `PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py --training-end 2026-03-20 --window 120`
   - Upload to GCS, update env var, deploy worker.

2. **Verify end-to-end pipeline**
   - Run a dry prediction request against the worker
   - Verify supplemental data flows (umpire, weather, game context, catcher framing)
   - Confirm all BQ tables have correct schemas

3. **Resume schedulers** (Mar 24)
   - `./bin/mlb-season-resume.sh`
   - Verify schedule scraper populates 2026 calendar

### Medium Priority (During Paper Trading, Apr-May)

4. **UNDER signal development**
   - The pipeline is 100% OVER — all 832 BB picks in 2025 replay are OVER
   - UNDER has 3 active signals (velocity_drop, short_rest, high_variance) + higher RSC gate (3)
   - Biggest untapped opportunity: dedicated UNDER research
   - Potential UNDER angles: bullpen usage, pitch mix changes, injury return regression

5. **Shadow signal promotion**
   - 30 shadow signals accumulating live data starting Mar 27
   - Promotion criteria: HR >= 60% + N >= 30 in live data
   - Best candidates: `day_game_elite_peripherals_combo` (72% replay), `high_csw_low_era_high_k_combo` (70.6%)

6. **Umpire signal calibration**
   - Signal fires at 64.2% HR but inflates RSC (net negative as active)
   - Options: (a) higher threshold (top 10% instead of 25%), (b) use as tiebreaker not RSC
   - Need full season of umpire data to calibrate properly

7. **Blacklist refresh**
   - Current 28 pitchers based on 2022-2025 data
   - After 4-6 weeks of 2026 data, some may have improved
   - Check: any blacklisted pitcher consistently beating the line?

### Lower Priority (Mid-Season)

8. **Multi-model fleet**
   - Currently single model (CatBoost V2). NBA has 10+ models.
   - LightGBM/XGBoost regressors could add diversity
   - Per-model pipeline architecture already exists (NBA side)

9. **Live line movement signals**
   - `line_movement_over` is shadow — needs BettingPros line history
   - CLV (closing line value) tracking for pick quality validation

10. **FanGraphs feature expansion**
    - xFIP proved valuable (73.8% HR as signal). Other FanGraphs metrics?
    - SIERA, K-BB%, CSW by zone could add signal value
    - BUT: adding features to model historically hurts. Better as signals.

11. **Catcher framing integration**
    - Scraper tested (57 catchers for 2025), BQ table + processor ready
    - Weekly scrape cadence during season
    - `catcher_framing_over/poor_under` signals ready, waiting for live data

## Critical Path to Opening Day

| When | Task | Status |
|------|------|--------|
| **Mar 11** | Phase 1: Dockerfile fix, multi-model, umpire tiebreaker, BQ verify | **DONE (Session 468)** |
| **Mar 18-20** | Retrain model (120d window through Mar 20) | TODO |
| **Mar 20-23** | Upload to GCS, update env var, deploy worker | TODO |
| **Mar 24** | Resume 24 MLB schedulers | TODO |
| **Mar 25-26** | Verify scrapers fire, data flows to BQ | TODO |
| **Mar 27** | Opening day — verify predictions + best bets | TODO |
| Apr 14 | First in-season retrain (auto via 14d cadence) | Scheduled |
| May 1 | UNDER enablement decision | Decision point |
| May 15 | Shadow signal promotion review | Decision point |

## Key Files Reference

| File | Purpose |
|------|---------|
| `scripts/mlb/training/train_regressor_v2.py` | Model training |
| `scripts/mlb/training/season_replay.py` | Walk-forward replay simulator |
| `ml/signals/mlb/signals.py` | All 56 signal classes (~2000 lines) |
| `ml/signals/mlb/registry.py` | Signal registration (20 active + 30 shadow + 6 filters) |
| `ml/signals/mlb/best_bets_exporter.py` | BB pipeline + pick angles |
| `predictions/mlb/supplemental_loader.py` | Umpire, weather, game context, catcher framing |
| `predictions/mlb/worker.py` | Cloud Run prediction worker |
| `scrapers/mlb/registry.py` | 18 MLB scrapers |
| `scrapers/mlb/external/mlb_catcher_framing.py` | Catcher framing scraper |
| `scripts/mlb/backfill_umpire_assignments.py` | Historical umpire backfill |
| `data_processors/raw/mlb/mlb_catcher_framing_processor.py` | Catcher framing processor |
| `docs/08-projects/current/mlb-session-464/EXPERIMENT-PLAN.md` | Full experiment history |
| `docs/08-projects/current/mlb-2026-season-strategy/03-DEPLOY-CHECKLIST.md` | Deploy steps |
| `docs/08-projects/current/mlb-2026-season-strategy/06-SEASON-PLAN-2026.md` | Season timeline |

## Session 465 Changes (This Session)

- **Promoted:** `xfip_elite_over` (67.5% HR, N=704) + `day_game_high_csw_combo_over` (73.0% HR, N=122)
- **Added:** 4 shadow signals (xfip, 3 combos), umpire replay infrastructure
- **Fixed:** xfip signal placement bug, combo column reference bug, catcher framing scraper, umpire backfill schema
- **Loaded:** 2,400+ umpire assignments for 2025 season
- **Finding:** Umpire signal as active hurts (-1.7pp) via RSC inflation → keep tracking-only
- **Finding:** Bootstrap period is ~6-7 weeks. Paper trade barely produces picks. Real eval = May 15+.
