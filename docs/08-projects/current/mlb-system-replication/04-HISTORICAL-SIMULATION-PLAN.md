# 2025 Historical Season Simulation Plan

> **Purpose:** Step-by-step plan to simulate both MLB prediction tracks against the 2025 season before going live. Covers data inventory, walk-forward protocol, signal/filter discovery, model experiments, and validation gates.

---

## Step 1: Data Inventory & Backfill

### 1.1 Track A Data (Pitcher Strikeouts)

| Table | Content | 2025 Coverage | Gap |
|-------|---------|---------------|-----|
| `mlb_raw.mlb_pitcher_stats` | Pitcher game stats | Verify Apr-Sep 2025 | Check completeness |
| `mlb_raw.statcast_pitcher_game_stats` | Statcast metrics | 39,918 rows through Jun 2025 | **Jul-Sep missing** |
| `mlb_raw.fangraphs_pitcher_season_stats` | SwStr%, CSW% | 1,704 rows | Verify full season |
| `mlb_raw.oddsa_pitcher_props` | Betting lines (K props) | Verify coverage | Check line availability |
| `mlb_raw.bp_pitcher_props` | BettingPros historical props | 100K+ rows | Verify date range |
| `mlb_analytics.pitcher_game_summary` | Rolling K averages | 9,800+ rows | Verify full season |
| `mlb_precompute.pitcher_ml_features` | 35-feature store | Verify coverage | Check feature completeness |
| `mlb_raw.mlb_lineup_batters` | Lineup data | Critical for bottom-up K | Verify availability |
| `mlb_raw.mlb_ballpark_factors` | Park K factors | Reference table | Should be static |
| `mlb_raw.mlb_umpire_stats` | Umpire tendencies | Reference table | Verify coverage |

**Priority backfill order:** Statcast Jul-Sep gap → pitcher stats → batter stats → schedule → betting lines → analytics → features.

**Existing backfill scripts:**
- `scripts/mlb/backfill_statcast_game_stats.py`
- `scripts/mlb/backfill_pitcher_splits.py`
- `scripts/mlb/backfill_mlb_schedule.py`
- `scripts/mlb/backfill_fangraphs_stats.py`
- `scripts/mlb/historical_odds_backfill/` — parallel odds backfill infrastructure

### 1.2 Track B Data (Team Game Total O/U)

| Table | Content | 2025 Coverage | Gap |
|-------|---------|---------------|-----|
| `mlb_raw.oddsa_game_lines` | Game total lines (O/U) | Verify Apr-Sep 2025 | Check line types |
| `mlb_raw.oddsa_game_lines_his` | Historical game lines | Verify depth | May need backfill |
| `mlb_raw.oddsa_events` | Game events metadata | Verify coverage | Check game IDs |
| `mlb_raw.bdl_box_scores` | Team box scores (R/H/E) | Verify full season | Check completeness |
| `mlb_raw.bdl_team_season_stats` | Team season aggregates | Verify | May be end-of-season only |
| `mlb_raw.mlb_schedule` | Schedule + probable pitchers | Verify full season | Check pitcher coverage |
| `mlb_raw.mlb_ballpark_factors` | Park run/HR factors | Reference table | Should be static |
| `mlb_raw.mlb_weather` | Temperature, wind, humidity | Verify game-level | Critical for Track B |

**Track B additional build requirements (before simulation can start):**
1. Build `team_game_summary` analytics processor — derive per-game team stats from box scores
2. Build `team_ml_features` feature store — team-level feature vectors
3. This is why Track B is offset 4-8 weeks from Track A

**Derived team stats needed (not in raw tables):**
- Team batting: OPS, wOBA, K rate, runs/game (rolling 10/30 game windows)
- Team pitching: ERA, WHIP, K/9 (rolling windows)
- Bullpen: ERA, innings pitched, rest days (rolling 3-day window)
- Starting pitcher: recent ERA last 3/5 starts, WHIP, K/9

### 1.3 Backfill Execution Protocol

Follow the NBA phase-by-phase pattern (NOT date-by-date):

```
Phase 2 (ALL dates) → Phase 3 (ALL dates) → Phase 4 (ALL dates) → Phase 5 (simulation)
```

Phase 4 needs lookback windows — running date-by-date fails when prior dates haven't been processed. See `docs/02-operations/backfill/backfill-guide.md` for the full protocol.

---

## Step 2: Walk-Forward Training Protocol

### 2.1 Track A: Pitcher Strikeouts

**Parameter matrix:**

| Dimension | Values | Rationale |
|-----------|--------|-----------|
| Window sizes | 21, 42, 63, 84 days | Pitchers start ~1x/5 days — may need wider than NBA's 42d |
| Retrain cadences | 7, 14, 21, 28 days | Find decay rate |
| Model families | V1 baseline (XGBoost), V1.6 rolling (XGBoost), CatBoost MAE, CatBoost no-vegas | Compare existing vs fresh |
| Vegas weights | 1.0, 0.25, 0.15, 0.0 | NBA found 0.15-0.25 optimal |

**Key questions to answer:**

1. **Do existing XGBoost V1/V1.6 models outperform fresh CatBoost?**
   - This determines the Phase 1 champion. If existing models are competitive, MVP is mostly deployment.
   - Run both on identical eval windows.

2. **Is the 35-feature set optimal or should we trim?**
   - NBA found fewer features often better (V12 50 features > V13 56 features > V15 55 features > V16 52 features).
   - Run feature importance analysis, then ablation: all 35, no-vegas, top 15, top 10.

3. **What's the MLB edge threshold?**
   - Existing config uses 0.5 K. NBA uses 3.0 pts.
   - Profile edge bands: 0-0.5, 0.5-1.0, 1.0-2.0, 2.0-3.0, 3.0+ strikeouts.
   - Find the threshold where HR consistently exceeds 52.4%.

4. **How fast do MLB models decay?**
   - NBA ~21 days. MLB may be slower (stable 5-man rotations vs NBA lineup variation).
   - Track HR by days-since-training across all windows.

5. **Does Jul-Aug 2025 market efficiency hold or was it transient?**
   - Known drift documented in `MODEL-DRIFT-ANALYSIS-JUL-AUG-2025.md`.
   - Run monthly evaluation windows to identify structural vs transient patterns.

**Adapt from:** `ml/experiments/season_walkforward.py` (NBA walk-forward simulator).

### 2.2 Track B: Team Game Total O/U

**Parameter matrix (smaller, exploratory):**

| Dimension | Values | Rationale |
|-----------|--------|-----------|
| Window sizes | 42, 63, 84, 120 days | Teams play daily — more data per window than pitchers |
| Retrain cadences | 14, 21, 28 days | Start conservative |
| Model families | CatBoost MAE, CatBoost no-vegas | Proven framework only |
| Feature sets | Full (~25), no-vegas (~20), minimal (top 10) | Discover what matters |

**Key questions to answer:**

1. **Is game total O/U predictable above breakeven?**
   - Fundamental viability question. If no config beats 52.4%, don't proceed to live.

2. **What features matter most?**
   - Starting pitcher quality? Bullpen rest? Park factors? Weather?
   - Feature importance ranking determines the minimal viable feature set.

3. **What edge threshold is profitable?**
   - Game totals are in runs (~8-10). Edge bands: 0-0.5, 0.5-1.0, 1.0-1.5, 1.5-2.0, 2.0+ runs.
   - Find the breakeven threshold.

4. **Does OVER or UNDER systematically fail in certain months?**
   - NBA's OVER collapsed in February. Check MLB monthly directional patterns.
   - Particularly watch July (All-Star break) and late July (trade deadline).

5. **How does the trade deadline affect model stability?**
   - Late July: teams acquire/trade players, fundamentally changing roster quality.
   - Models trained before the deadline may fail after. Test window spanning the deadline.

---

## Step 3: Signal & Filter Discovery

### 3.1 Track A Signal Hypotheses (13 candidates)

| # | Signal | Direction | Hypothesis | Data Source |
|---|--------|-----------|-----------|-------------|
| 1 | `high_k_rate_over` | OVER | K/9 rolling >= 10.0 + OVER | `pitcher_game_summary` |
| 2 | `elite_swstr_over` | OVER | SwStr% >= 12% + OVER (validated in RedFlagConfig) | `fangraphs_pitcher_season_stats` |
| 3 | `weak_lineup_over` | OVER | Opponent team K rate top quartile + OVER | `bdl_team_season_stats` |
| 4 | `pitcher_park_over` | OVER | Ballpark K factor >= 1.10 + OVER | `mlb_ballpark_factors` |
| 5 | `short_rest_under` | UNDER | Days rest <= 3 + UNDER (in RedFlagConfig) | Schedule |
| 6 | `high_workload_under` | UNDER | 6+ starts in 30 days + UNDER | `pitcher_game_summary` |
| 7 | `bottom_up_agreement` | BOTH | Bottom-up K estimate agrees with model direction | `mlb_lineup_batters` |
| 8 | `velocity_decline_under` | UNDER | Fastball velo down 1+ mph vs season avg + UNDER | `statcast_pitcher_game_stats` |
| 9 | `game_total_high_over` | OVER | Game O/U >= 9.0 + OVER (more Ks in high-scoring games) | `oddsa_game_lines` |
| 10 | `home_over` | OVER | Home pitcher + OVER (home/away K differential) | Schedule |
| 11 | `hot_swstr_trend_over` | OVER | Recent SwStr% > season avg by 3%+ | `statcast_pitcher_game_stats` |
| 12 | `cold_swstr_trend_under` | UNDER | Recent SwStr% < season avg by 3%- | `statcast_pitcher_game_stats` |
| 13 | `platoon_advantage_over` | OVER | Hand advantage vs majority of lineup | `mlb_lineup_batters` |

### 3.2 Track B Signal Hypotheses (10 candidates)

| # | Signal | Direction | Hypothesis | Data Source |
|---|--------|-----------|-----------|-------------|
| 1 | `park_factor_over` | OVER | High run-scoring park (factor >= 1.10) + OVER | `mlb_ballpark_factors` |
| 2 | `weather_warm_over` | OVER | 80°F+ temp + wind blowing out + OVER | `mlb_weather` |
| 3 | `weather_cold_under` | UNDER | < 50°F or rain threat + UNDER | `mlb_weather` |
| 4 | `bullpen_depleted_over` | OVER | Both teams bullpen high usage last 3 days + OVER | Derived from box scores |
| 5 | `ace_matchup_under` | UNDER | Both SPs ERA < 3.0 + UNDER (pitchers' duel) | `mlb_pitcher_stats` |
| 6 | `weak_sp_matchup_over` | OVER | Both SPs ERA > 4.5 + OVER (slugfest) | `mlb_pitcher_stats` |
| 7 | `hot_offense_over` | OVER | Combined team runs/game last 10 above season avg + OVER | `team_game_summary` |
| 8 | `cold_pitching_over` | OVER | Combined team ERA last 10 above season avg + OVER | `team_game_summary` |
| 9 | `wind_in_under` | UNDER | Wind blowing in strongly + UNDER (suppresses HRs) | `mlb_weather` |
| 10 | `high_total_under` | UNDER | Game total line >= 9.5 + UNDER (market overestimates?) | `oddsa_game_lines` |

### 3.3 Negative Filter Dimensions to Scan (Both Tracks)

Profile HR across each dimension. Block any combination below 45% HR with N >= 15:

| Dimension | Track A | Track B |
|-----------|---------|---------|
| Direction × edge band | OVER/UNDER × edge ranges | OVER/UNDER × edge ranges |
| Home/Away | Pitcher home/away | Home team favored/underdog |
| Day/Night | Game time slot | Game time slot |
| Days rest | Pitcher rest days | N/A (teams play daily) |
| Month | Apr-Sep monthly | Apr-Sep monthly |
| Ballpark | Indoor/outdoor, K factor | Indoor/outdoor, run factor |
| Line range | Low/mid/high K line | Low/mid/high total line |
| Model agreement | Multi-model consensus | Multi-model consensus |
| Weather | N/A | Temperature/wind/humidity buckets |
| Division | AL/NL matchup type | Interleague vs same-league |

### 3.4 Evaluation Windows

6 monthly windows for both tracks:

| Window | Dates | MLB Context |
|--------|-------|-------------|
| W1_Apr | Apr 1-30 | Season start, cold weather, small sample |
| W2_May | May 1-31 | Rotations stabilize |
| W3_Jun | Jun 1-30 | Mid-season, warm weather arrives |
| W4_Jul | Jul 1-31 | All-Star break mid-month, trade deadline late |
| W5_Aug | Aug 1-31 | Post-deadline rosters, September call-up prep |
| W6_Sep | Sep 1-28 | Expanded rosters, playoff push, rest management |

### 3.5 Signal Acceptance Criteria

Same standards as NBA:
- HR must be **above breakeven (52.4%)** over full evaluation period
- **Blocked HR < 45%** on N >= 15 (for negative filters)
- **Multi-month stable** — signal can't work only in one month
- **Must reach best bets** — signals that fire but never make it through the filter stack are useless
- **Feb-resilience equivalent:** Check Jul-Aug (known MLB drift period) performance separately

---

## Step 4: Model Architecture Experiments

### 4.1 Track A: Feature & Framework Analysis

**Feature importance analysis:**
- Run SHAP/importance on existing 35 features across all trained models
- Identify dominant features (NBA: `vegas_points_line` at 22.8% was too dominant)
- Check for features with zero variance or <1% importance (dead features)

**Feature set ablation:**
| Config | Features | Hypothesis |
|--------|----------|-----------|
| Full | All 35 | Baseline |
| No-vegas | ~30 (exclude vegas features) | NBA found no-vegas often better |
| Minimal top 10 | Top 10 by importance | NBA found fewer features often better |
| Bottom-up only | K prediction features only | Test bottom-up model in isolation |

**Framework comparison:**
| Framework | Models | Notes |
|-----------|--------|-------|
| XGBoost V1/V1.6 | Existing trained models | Already validated, known behavior |
| CatBoost MAE | New training | NBA champion framework |
| LightGBM | New training | NBA showed genuine feature diversity from CatBoost |

**Dead ends to skip (from NBA experience):**
- Quantile regression (generates volume but not profitably)
- Two-stage pipeline (Edge Classifier AUC < 0.50)
- Direction-specific models (feature distributions identical between outcomes)
- Stacked residuals (learns noise)
- Anchor-line training (collapses feature importance)

### 4.2 Track B: Feature Set Design

Design ~20-25 features from scratch:

| # | Feature | Category | Source |
|---|---------|----------|--------|
| 1 | Home SP ERA (season) | Pitching | `mlb_pitcher_stats` |
| 2 | Home SP ERA (last 3 starts) | Pitching | `pitcher_game_summary` |
| 3 | Home SP WHIP | Pitching | `mlb_pitcher_stats` |
| 4 | Home SP K/9 | Pitching | `mlb_pitcher_stats` |
| 5 | Away SP ERA (season) | Pitching | `mlb_pitcher_stats` |
| 6 | Away SP ERA (last 3 starts) | Pitching | `pitcher_game_summary` |
| 7 | Away SP WHIP | Pitching | `mlb_pitcher_stats` |
| 8 | Away SP K/9 | Pitching | `mlb_pitcher_stats` |
| 9 | Home team OPS (season) | Offense | `bdl_team_season_stats` |
| 10 | Home team runs/game (last 10) | Offense | `team_game_summary` |
| 11 | Away team OPS (season) | Offense | `bdl_team_season_stats` |
| 12 | Away team runs/game (last 10) | Offense | `team_game_summary` |
| 13 | Home bullpen ERA (last 7 days) | Bullpen | `team_game_summary` |
| 14 | Home bullpen innings (last 3 days) | Bullpen | `team_game_summary` |
| 15 | Away bullpen ERA (last 7 days) | Bullpen | `team_game_summary` |
| 16 | Away bullpen innings (last 3 days) | Bullpen | `team_game_summary` |
| 17 | Park run factor | Park | `mlb_ballpark_factors` |
| 18 | Park HR factor | Park | `mlb_ballpark_factors` |
| 19 | Temperature | Weather | `mlb_weather` |
| 20 | Wind speed × direction | Weather | `mlb_weather` |
| 21 | Game total line (vegas) | Vegas | `oddsa_game_lines` |
| 22 | Home ML implied probability | Vegas | `oddsa_game_lines` |
| 23 | SP career ERA at this park | Historical | `pitcher_game_summary` + park |
| 24 | Day/night flag | Context | Schedule |
| 25 | Interleague flag | Context | Schedule |

**Target variable:** Total runs scored (both teams combined).

**Edge calculation:** `predicted_total_runs - game_total_line`.

**Start with CatBoost MAE only** — proven framework. Add a second framework only if CatBoost underperforms on walk-forward simulation.

---

## Step 5: How Results Feed Into Phase 1

| Simulation Question | Track A Impact | Track B Impact |
|---------------------|---------------|---------------|
| Training window | Use existing model or retrain with optimal window | Set initial training config |
| Retrain cadence | Set automated retrain schedule | Set automated retrain schedule |
| Edge threshold | Recalibrate `MIN_EDGE` from 0.5 K | Discover `MIN_EDGE` for game totals |
| Best model | Keep existing XGBoost or switch to CatBoost | Set champion model |
| Effective signals | Deploy initial signal set | Deploy initial signal set |
| Effective filters | Deploy initial filter stack | Deploy initial filter stack |
| Pitcher/team exclusions | Initial pitcher blacklist | Initial team/park blacklist |
| Model shelf life | Set decay detection thresholds | Set decay detection thresholds |
| Feature importance | Trim or keep 35 features | Finalize ~20-25 feature contract |
| Directional patterns | OVER/UNDER balance by month | OVER/UNDER balance by month |

---

## Step 6: Validation Before Going Live

### 6.1 Cross-Season Validation

- Run best config against **2024 data** (if available in BQ or backfillable)
- NBA lesson: Config difference < 5pp across seasons is noise. Only trust > 5pp differences.
- If 2024 data unavailable, rely on out-of-sample holdout (below)

### 6.2 Out-of-Sample Holdout

- **Reserve September 10-28, 2025** as pure holdout — never used for tuning or signal discovery
- This is the final validation gate before going live
- Must beat breakeven (52.4%) on holdout to proceed to Phase 1 live

### 6.3 Paper Trading

- Run full pipeline on **March 2026 Spring Training** games (no real bets)
- Validates operational readiness: scraping, processing, predictions, grading, publishing
- Identifies deployment issues before regular season stakes

### 6.4 Documentation

Before going live, document:
- Dead-ends list (approaches that don't work — prevents revisiting)
- Winning configs (exact parameters for champion model)
- Known risks (months/parks/scenarios where model underperforms)
- MLB-specific operational notes (scratched pitchers, rain delays, doubleheaders)

---

## MLB-Specific Considerations (Both Tracks)

### Data Density

| Factor | NBA | MLB (Track A: Pitchers) | MLB (Track B: Teams) |
|--------|-----|-------------------------|----------------------|
| Games per week | 3-4 per team | 1 start per pitcher | 6-7 per team |
| Data per 42-day window | ~15 games/player | ~8 starts/pitcher | ~40 games/team |
| Implication | Standard windows | **May need wider windows** | Closer to NBA density |

### Unique MLB Factors

1. **Sparse pitcher data:** 1 start per 5 days means fewer data points per pitcher per window. May need 63-84 day windows where NBA uses 42.

2. **Teams play daily:** Track B has dense data similar to NBA. 42-day windows likely sufficient.

3. **Strong platoon effects:** L/R matchup is fundamental for Track A. Lineup composition changes the K prediction significantly.

4. **Weather and park effects:** Both tracks are affected. Track B especially — temperature, wind, altitude (Coors Field) directly impact run scoring.

5. **Lineup uncertainty:** Probable pitchers can be scratched day-of. Need a fallback strategy (skip prediction or use bullpen game model).

6. **Market efficiency evolution:** Jul-Aug 2025 drift is documented. Verify whether this is seasonal or structural for both markets.

7. **162-game season:** More evaluation windows than NBA (82 games). Better stability testing possible across 6 monthly windows.

8. **All-Star Break:** ~4 day gap in mid-July. Models may need to handle the break (stale rolling averages).

9. **Trade Deadline:** Late July roster changes fundamentally alter team composition. Models trained pre-deadline may fail post-deadline. Track B is especially vulnerable.

10. **September Roster Expansion:** Teams can call up minor league players. Changes depth, bullpen composition, and rest patterns. Both tracks affected.

---

## Key Files Referenced

| File | Track | Purpose |
|------|-------|---------|
| `ml/experiments/season_walkforward.py` | Both | NBA walk-forward simulator to adapt |
| `ml/experiments/season_replay_full.py` | Both | Full season replay with 22+ dimensions |
| `bin/testing/mlb/replay_mlb_pipeline.py` | A | MLB replay template (already exists) |
| `ml/experiments/signal_backtest.py` | Both | Signal backtesting harness |
| `data_processors/precompute/mlb/pitcher_features_processor.py` | A | Existing 35-feature store |
| `predictions/mlb/config.py` | A | Existing MLB config with RedFlagConfig |
| `predictions/mlb/worker.py` | A | Existing prediction worker (24K lines) |
| `ml/signals/aggregator.py` | Both | NBA aggregator pattern to replicate |
| `scripts/mlb/backfill_*.py` | Both | Existing backfill scripts |
| `scrapers/mlb/oddsapi/mlb_game_lines.py` | B | Game lines scraper (already exists) |
| `data_processors/raw/mlb/mlb_game_lines_processor.py` | B | Game lines processor (already exists) |
| `docs/02-operations/backfill/backfill-guide.md` | Both | Backfill protocol |
| `docs/01-architecture/bootstrap-period-overview.md` | Both | Bootstrap period handling |
