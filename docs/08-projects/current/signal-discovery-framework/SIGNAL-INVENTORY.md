# Signal Inventory — Complete List

**Last Updated:** 2026-03-26 (Session 494 audit)
**Active Signals:** 28 (+ 32 shadow/observation accumulating data)
**Negative Filters:** 25 active (+ 30 observation — see aggregator.py audit block)
**Combo Registry:** 11 SYNERGISTIC entries
**Algorithm Version:** `v469_health_aware_weights_line_rose_block`

---

## Architecture

**Edge-first:** Signals filter and annotate picks, not select them. Rankings are by edge (OVER) or signal quality score (UNDER).

**SC Architecture (Session 397):** `real_sc` = non-base signal count. Base signals (`model_health`, `high_edge`, `edge_spread_optimal`) fire on ~100% of picks, inflating total SC to 3 with zero discriminative power. All SC-based filters use `real_sc` instead of total SC.

**Best Bets Pipeline:** `edge 3+ (or signal rescue) → negative filters → signal count ≥ 3 → real_sc gate (OVER: real_sc>0, UNDER edge<7: real_sc>0) → rank by edge`

**Signal Rescue (Session 398):** Picks below edge 3.0 (or OVER below 5.0) bypass edge floors if they have a validated high-HR signal or 2+ real signals. Tracked via `signal_rescued` + `rescue_signal` in BQ.

**OVER Edge Floor (Session 468):** Raised from 4.0 to 5.0. 5-season discovery analysis (79K predictions) showed OVER at edge 3-5 is net-negative in 4/5 historical seasons (43-50% HR). Only 2025-26 showed profitability at edge 3-5. UNDER at edge 3-5 is consistently 56.7%. OVER only viable at edge 5+.

Rescue tags: `combo_3way`, `combo_he_ms`, `home_under` (75%), `high_scoring_environment_over` (71.4%). Signal stacking: 2+ real signals = 62.2% HR (N=45). Session 415: removed `low_line_over` from rescue. Session 420: restored `high_scoring_environment_over`. Session 427: removed `mean_reversion_under` (cross-season decay to 53.0%). Session 431: removed `sharp_book_lean_under` (zero production fires in 2026). Session 462: removed `sharp_book_lean_over` (41.7% HR 5-season cross-validated), removed `book_disagreement` (Session 434), removed `volatile_scoring_over` (Session 436).

**Rescue Cap (Session 415):** Maximum percentage of picks that can be rescue-sourced per slate. Prevents rescue from dominating when edge compression makes most picks low-edge. Threshold: 40% of total picks. Excess rescue picks are dropped by weakest rescue signal.

**`signal_stack_2plus` demotion (Session 415):** Demoted from rescue qualification to observation-only. 50% HR at N=6 — thinnest quality tier with only 2 real signals. Still tracked in `pick_signal_tags` for monitoring.

**UNDER ranking (Session 400):** Signal-first, not edge-first. UNDER edge is flat at 52-53% across ALL edge buckets — ranking by edge is meaningless for UNDER. Weighted signal quality score ranks UNDER picks.

**Pick Angles:** Each pick includes `pick_angles` — human-readable reasoning. See `ml/signals/pick_angle_builder.py`.

---

## Active Signals (28)

### Base/Infrastructure (3) — fire on ~100% of picks

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `model_health` | BOTH | 52.6% | META | Not in pick_signal_tags — signal density only |
| `high_edge` | BOTH | 66.7% | PRODUCTION | |
| `edge_spread_optimal` | BOTH | 67.2% | PRODUCTION | |

### Combo Signals (2)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `combo_he_ms` | OVER | 94.9% | PRODUCTION | High edge + minutes surge |
| `combo_3way` | OVER | 95.5% | PRODUCTION | ESO + high edge + minutes surge |

### OVER Signals (12)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `3pt_bounce` | OVER | 74.9% | CONDITIONAL | Cold 3PT shooter regression |
| `line_rising_over` | OVER | 96.6% | PRODUCTION | Session 374b, fixed 387 (was dead — champion dependency) |
| `scoring_cold_streak_over` | OVER | 65.1% | CONDITIONAL | Session 371 |
| `high_scoring_environment_over` | OVER | 70.2% | CONDITIONAL | Session 373 |
| `fast_pace_over` | OVER | 81.5% | PRODUCTION | Session 374, fixed 387 (threshold was raw 102 on 0-1 scale) |
| `volatile_scoring_over` | OVER | 77.8% post-toxic | PRODUCTION | Session 374, disabled 391 (toxic 50%), re-enabled 411 (77.8% recovery) |
| `low_line_over` | OVER | 78.1% | PRODUCTION | Session 374 |
| `b2b_boost_over` | OVER | 64.3% | PRODUCTION | Session 396, inverse of b2b_fatigue_under |
| `q4_scorer_over` | OVER | 64.4% | PRODUCTION | Session 397, from BDL PBP Q4 ratio |
| `denver_visitor_over` | OVER | 67.8% | PRODUCTION | Session 398, altitude effect |
| `day_of_week_over` | OVER | 66-70% | PRODUCTION | Session 398, Mon/Thu/Sat boost |
| `sharp_book_lean_over` | OVER | 70.3% | PRODUCTION | Session 399, sharp books 1.5+ higher than soft |

### UNDER Signals (7)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `bench_under` | UNDER | 76.9% | PRODUCTION | |
| `home_under` | UNDER | 63.9% | PRODUCTION | Session 371 |
| `extended_rest_under` | UNDER | 61.8% | PRODUCTION | Session 372 |
| `starter_under` | UNDER | 54.8-68.1% | PRODUCTION | Session 372 |
| `sharp_book_lean_under` | UNDER | 84.7% backtest / 0 fires | OBSERVATION | Session 399. Zero production fires — market regime: sharp books consistently set higher lines than soft. Demoted 3.0→1.0 (S423)→observation (S431). Removed from UNDER_SIGNAL_WEIGHTS and rescue_tags. |
| `mean_reversion_under` | UNDER | 53.0% (2026) | SHADOW (S451) | Session 413→429→451. Cross-season decay: 75.7%→65.2%→53.0%. Moved to SHADOW_SIGNALS (stops real_sc inflation). Added MAX_OVER_RATE=0.60 guard (don't fire on structural high-scorers). Removed from rescue (S427), weights (S429). |
| `day_of_week_under` | UNDER | 59.4-60.3% | SHADOW | Session 414, Monday 60.3% (N=277), Thursday 59.4% (N=419) |
| `sharp_line_drop_under` | UNDER | 87.5% | PRODUCTION | Session 382c. Now in UNDER_SIGNAL_WEIGHTS (2.5) since Session 422c |

### BOTH Direction (1)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `book_disagreement` | BOTH | 93.0% | WATCH | |

### WATCH / Special (2)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `ft_rate_bench_over` | OVER | 72.5% | WATCH | |
| `rest_advantage_2d` | BOTH | 74.0% BB (N=50) | PRODUCTION (weight 2.0) | Session 396 (disabled) → Session 442: added to OVER_SIGNAL_WEIGHTS at 2.0 (74.0% BB HR, N=50) |

---

## Shadow Signals (30) — Sessions 401 + 404 + 410 + 411 + 418 + 462, accumulating data

All shadow signals are registered and firing but NOT wired into aggregator rescue/ranking. They record to `pick_signal_tags` and `signal_health_daily` for validation.

### Session 401 — New Data Sources

| Signal | Direction | Source | Notes |
|--------|-----------|--------|-------|
| `projection_consensus_over` | OVER | FantasyPros, DFF, Dimers, NumberFire | 2+ sources above line + OVER |
| `projection_consensus_under` | UNDER | Same 4 sources | 2+ sources below line + UNDER |
| `projection_disagreement` | BOTH | Same 4 sources | 0 sources agree — negative filter (not active) |
| `predicted_pace_over` | OVER | TeamRankings pace | Predicted game pace >= 101 (first fire Mar 4: 2x) |
| `dvp_favorable_over` | OVER | Hashtag Basketball DvP | Bottom-5 defense at position |
| `positive_clv_over` | OVER | Odds API closing lines | Closing line value >= 0.5 confirms edge |
| `positive_clv_under` | UNDER | Odds API closing lines | CLV <= -0.5 confirms UNDER |
| `negative_clv_filter` | BOTH | Odds API closing lines | CLV contradicts — negative filter (not active) |

### Session 404 — VSiN Sharp Money + RotoWire Minutes

| Signal | Direction | Source | Notes |
|--------|-----------|--------|-------|
| `sharp_money_over` | OVER | VSiN betting splits | Handle >= 65% OVER + tickets <= 45% OVER |
| `sharp_money_under` | UNDER | VSiN betting splits | Handle >= 65% UNDER + tickets <= 45% UNDER |
| `public_fade_filter` | OVER | VSiN betting splits | 80%+ public tickets on OVER — negative filter (not active) |
| `minutes_surge_over` | OVER | RotoWire lineups | Projected minutes >= season avg + 3 |

**Data status (Mar 4):** VSiN table empty (scraper deployed, not yet triggered). RotoWire `projected_minutes` is null for all rows (scraper captures lineups but not minutes). 7 of 10 scrapers have data. NumberFire/VSiN/NBA Tracking need first trigger.

### Session 410 — Derived Feature Signals (experiment dead ends → contextual signals)

Features that failed as model inputs but are conceptually perfect as contextual evaluators: they identify WHEN to trust the model, not how to improve predictions.

| Signal | Direction | Source | Notes |
|--------|-----------|--------|-------|
| `hot_form_over` | OVER | f0 (pts_avg_last_5), f1 (pts_avg_last_10) | Form ratio >= 1.10 + line >= 10 |
| `consistent_scorer_over` | OVER | f3 (points_std_last_10) | CV <= 0.30 + line >= 12. Complement to volatile_scoring_over |
| `over_trend_over` | OVER | prev_over_1..5 (streak_data) | 60%+ over rate last 5 games + line >= 10 |

### Session 411 — Feature Store Signals (toxic window discovery → contextual signals)

Signals derived from feature store distributions. Discovered via toxic window analysis: most "dead" signals were casualties of Jan 30 - Feb 25 toxic window, not intrinsically broken. These exploit raw feature values as contextual evaluators.

| Signal | Direction | Source | Notes |
|--------|-----------|--------|-------|
| `usage_surge_over` | OVER | f48 (usage_rate_last_5) | Usage >= 25% (top quartile) + line >= 12 |
| `scoring_momentum_over` | OVER | f44 (trend_slope), f43 (pts_avg_last_3), f1 (pts_avg_last_10) | Slope > 1.0 + 3g avg > 10g avg |
| `career_matchup_over` | OVER | f29 (avg_pts_vs_opp), f30 (games_vs_opp) | Career avg vs opponent > line, 3+ games |
| `minutes_load_over` | OVER | f40 (minutes_load_7d) | 100+ min in 7 days = heavy engagement |
| `blowout_risk_under` | UNDER | f57 (blowout_risk) | 40%+ blowout bench rate + line >= 15. Fills UNDER gap (only 6th UNDER signal) |

### Session 418 — Player Profile Signals (deep dive findings)

| Signal | Direction | Source | Notes |
|--------|-----------|--------|-------|
| `bounce_back_over` | OVER | prev_game_context | Bad miss (FG% < 35% OR actual < line-5) + AWAY = 56.2% over (N=379). HOME bounce disappears. |
| ~~`over_streak_reversion_under`~~ | UNDER | — | **REMOVED Session 462:** 51.6% HR 5-season cross-validated — harmful. |

### Session 422c/423 — UNDER Signal Development

Three new UNDER signals to fill the UNDER signal vacuum. 98.4% of model-level UNDER predictions had zero real signals.

| Signal | Direction | Source | Notes |
|--------|-----------|--------|-------|
| `volatile_starter_under` | UNDER | line_value, f3 (points_std_last_10), edge | Starter (18-25) + volatile (std>8) + edge 5+. 65.5% HR (N=637). Monthly stable: Nov 63.6%, Dec 70.5%, Jan 61.9%, Feb 63.4%. |
| `downtrend_under` | UNDER | f44 (trend_slope) | Slight downtrend (slope -1.5 to -0.5). 63.9% HR (N=1,654). Highest-volume UNDER segment. |
| `star_favorite_under` | UNDER | line_value, f41 (spread_magnitude) | Star (line 25+) + team favored by 3+. ~73% HR (N=88). Blowout pull effect. |
| `starter_away_overtrend_under` | UNDER | line_value, is_home, f55 (over_rate_last_10) | **Session 462: 48.2% HR 5-season — harmful.** Demoted to shadow, removed from UNDER_SIGNAL_WEIGHTS. |

### Session 468 — Archetype Analyzer + OVER Bias Discovery

**Discovery tools built:** `scripts/nba/training/discovery/archetype_analyzer.py`, `expanded_scanner.py`

**OVER bias (79K predictions, 5 seasons):** OVER is net-negative in 4/5 seasons at edge 3-5 (43-50% HR). Only 2025-26 is profitable. OVER needs edge 5+ minimum. UNDER is stable at 57-58% across all edge levels and seasons.

**Archetype findings (cross-season validated):**
| Archetype | Dir | HR | N | Seasons |
|-----------|-----|-----|---|---------|
| low_line + low_var | UNDER | 62.0% | 819 | 4/4 |
| high_line + high_var | UNDER | 59.0% | 739 | 4/5 |
| low_line + mid_var | OVER | 58.3% | 657 | 3/4 |
| high_line + mid_var | UNDER | 56.8% | 621 | **5/5** |

**Hot shooting OVER is catastrophic:** FG% hot (diff >= 10%) = 24.1% OVER HR. 3PT hot (diff >= 15%) = 28.6%. Mean reversion kills OVER. → `hot_shooting_over_block` filter (Session 468).

**Edge 5+ scanner:** All 4 validated signals are UNDER (away_UNDER 58.4% N=2216, Fri_UNDER 58.8% N=386, Sun_UNDER 57.5% N=426, line_movement_low_UNDER 59.5% N=168).

### Session 469 — Direction-Specific Book Disagreement + Health-Aware Weights

**Direction-specific book_disagreement signals:**
| Signal | Direction | HR | N | Notes |
|--------|-----------|-----|---|-------|
| `book_disagree_over` | OVER | 79.6% | 211 | 5-season. Strongest directional signal — high book disagreement + OVER |
| `book_disagree_under` | UNDER | — | — | Shadow mode. Accumulating data for directional validation |

**Health-aware signal weighting (Session 469):**
Composite scores now apply signal health multipliers to weights. COLD behavioral signals get 0.5x weight (was 1.0x static). COLD model-dependent signals get 0.0x (unchanged). HOT signals get 1.2x. Prevents temporarily struggling signals (e.g., home_under at 33% 7d) from boosting bad picks.

**`over_line_rose_heavy` promoted to active filter:** OVER + BettingPros line rose >= 1.0 = 38.9% HR (N=54, 5-season). Fighting the market is losing.

### Session 462 — BB Pipeline Simulator Validated (5-season cross-validation)

| Signal | Direction | Source | HR | N | Notes |
|--------|-----------|--------|----|---|-------|
| `hot_3pt_under` | UNDER | supplemental['three_pt_stats'] | 62.5% | 670 | 3PT_last_3 - 3PT_season >= 10%. Books anchor to season avg; hot streak temporary. |
| `cold_3pt_over` | OVER | supplemental['three_pt_stats'] | 60.2% | 123 | 3PT_last_3 - 3PT_season <= -15%. Bounce-back from cold streak. |
| `line_drifted_down_under` | UNDER | pred['bp_line_movement'] (BettingPros) | 59.8% | 336 | BettingPros line movement [-0.5, -0.1). Smart money nudge. |
| `sharp_book_lean_over` | OVER | pred['sharp_book_lean'] | — | — | **Demoted from active.** 41.7% HR 5-season. Removed from OVER_SIGNAL_WEIGHTS and rescue. |

**Graduation criteria:** HR >= 60% + N >= 30 at BB level → promote to active. Check after 7+ days of production data.

---

## Disabled / Removed Signals

| Signal | HR | Disabled | Reason |
|--------|-----|---------|--------|
| `blowout_recovery` | 50.0% | Session 349 | 25% in Feb, not reliable. Session 422: demoted to BASE_SIGNALS. Session 431: suppressed during toxic window (75%→33% collapse). |
| `b2b_fatigue_under` | 39.5% Feb | Session 373 | Boosts losing pattern |
| `prop_line_drop_over` | 53.3% Feb | Session 374b | Conceptually backward — line drops are bearish |
| `dual_agree` | 45.5% | Session 275 | V9+V12 agreement anti-correlated |
| `hot_streak_2/3` | 45-47% | Session 275 | Net negative, false qualifier |
| `cold_continuation_2` | 45.8% | Session 275 | Never above breakeven |
| 6 "never fire" signals | N=0 | Session 275 | Dead code — see Session 275 notes |

---

## Negative Filters (22 active + 1 safety)

| # | Filter | Condition | HR | Session |
|---|--------|-----------|-----|---------|
| 1 | Player blacklist | <40% HR on 8+ edge-3+ picks | varies | — |
| — | ~~Avoid familiar~~ | ~~6+ games vs opponent~~ | 54.4% CF | **→obs 462** |
| 3 | Edge floor | edge < 3.0 (bypassed by rescue) | — | 352 |
| 4 | Model-direction affinity | HR < 45% on 15+ picks for model+direction+edge combo | <45% | 343 |
| 5 | Feature quality floor | quality < 85 | 24.0% | — |
| 6 | Bench UNDER block | UNDER + line < 12 | 35.1% | — |
| 7 | UNDER + line dropped 2+ | prop_line_delta <= -2.0 | 35.2% | — |
| 8 | Signal density | base-only signals, skip unless edge ≥ 7.0 | — | 352 |
| 9 | Opponent UNDER block | UNDER + opponent in {MIN, MEM, MIL} | 43.8-48.7% | 372 |
| 10 | SC=3 OVER block | OVER + signal_count == 3 | 45.5% | 394 |
| 11 | OVER + line dropped 2+ | OVER + prop_line_delta <= -2.0 | 39.1% | 374b |
| 12 | Opponent depleted UNDER | UNDER + 3+ opponent stars out | 44.4% | 374b |
| 13 | Q4 scorer UNDER block | UNDER + Q4_ratio >= 0.35 | 34.0% | 397 |
| 14 | Friday OVER block | OVER + Friday | 37.5% | 398 |
| 15 | High skew OVER block | OVER + mean_median_gap > 2.0 | 49.1% | 399 |
| 16 | High spread OVER block | OVER + spread >= 7 | 44.3% | 415 |
| 17 | Mid-line OVER block | OVER + line 15-25 | 47.9% | 415 |
| 18 | Flat trend UNDER block | UNDER + trend_slope -0.5 to 0.5 | 53% | 413 |
| 19 | UNDER after streak | UNDER + 3+ consecutive unders | 44.7% | 418 |
| 20 | Med usage UNDER block | UNDER + teammate_usage 15-30 | 32.0% | 355 |
| 21 | UNDER edge 7+ (V9) | UNDER + edge 7+ + V9 family | 34.1% | 297 |
| — | ~~B2B UNDER block~~ | ~~UNDER + rest_days <= 1~~ | 54.0% CF | **→obs 462** |
| 23 | Prediction sanity | pred > 2x season_avg + line < 18 | 40.9% (N=88) | 440 |
| 24 | Team cap | > 2 picks from same team | — | 441 |
| 25 | Line anomaly extreme drop | OVER + line drop >= 40% or >= 6pts from prev game | — | 451 |
| 26 | **Cold FG UNDER** | **UNDER + fg_last_3 - fg_season <= -10%** | **38.5% (N=457)** | **462** |
| 27 | **Cold 3PT UNDER** | **UNDER + 3pt_last_3 - 3pt_season <= -10%** | **45.6% (N=735)** | **462** |
| 28 | **Hot shooting OVER block** | **OVER + FG diff >= 10% OR 3PT diff >= 15%** | **24-29% (N=58/56)** | **468** |
| 29 | **OVER line rose heavy** | **OVER + BettingPros line rose >= 1.0** | **38.9% (N=54)** | **469** |
| — | Away block | REMOVED Session 401 | — | 401 |
| — | UNDER + line jumped 2+ | Demoted to observation Session 417 (5/5 winners blocked) | — | 417 |

### Observation-Only Filters (12 + Session 462 changes)

| Filter | Condition | HR | Session | Notes |
|--------|-----------|-----|---------|-------|
| `under_star_away` | UNDER + line >= 23 + away | 73.0% post-ASB | 415 | Demoted from active block (was 38.5% during toxic Feb, recovered post-ASB). Review ~Mar 19. |
| `line_jumped_under_obs` | UNDER + prop_line_delta >= 2.0 | 100% (5/5 winners blocked) | 417 | Demoted from active — was blocking winners. |
| `unreliable_over_low_mins_obs` | OVER + edge 5+ + minutes_load_7d < 45 | — | 421 | Wrong OVER fingerprint during toxic window. |
| `unreliable_under_flat_trend_obs` | UNDER + edge 5+ + minutes_load > 58 + flat trend | — | 421 | Wrong UNDER fingerprint during toxic window. |
| `blowout_risk_under_block_obs` | UNDER + blowout_risk >= 0.40 + line >= 15 | 16.7% (N=12) | 423 | Blowout benching → players get pulled → OVER. |
| `depleted_stars_over_obs` | OVER + star_teammates_out >= 3 | BB 0% (N=4), model 48.2% (N=137) | 439 | Skeleton crew = team offense degrades, volume boost doesn't materialize. |
| `hot_shooting_reversion_obs` | OVER + prev_game FG% >= 70% + 20+ min | 59.2% UNDER HR (N=250) | 441 | Efficiency mean-reverts at extreme — 60-69% shows no signal. |
| `public_fade_filter` | 80%+ public tickets OVER | — | 404 | VSiN data accumulating |
| `negative_clv_filter` | CLV contradicts pick direction | — | 401 | CLV data accumulating |
| `over_low_rsc_obs` | OVER + real_signal_count < 4 | 45.5% (rsc=3, N=11) vs 65.4% (rsc=4, N=26) | 442 | OVER rsc=3 underperforms significantly. Accumulating data. Promote at N >= 30. |
| `mae_gap_obs` | All picks when model MAE > Vegas MAE by 0.15+ (mae_gap_7d from league_macro_daily) | 40-50% | 442 | BB HR craters when model loses edge over Vegas. Observation mode. |
| `thin_slate_obs` | All picks on 4-6 game slates | 51.2% (76.7% OVER-heavy mix) | 442 | 7-9 games = 72.0% HR. Small slates = lower quality picks and OVER-heavy skew. Observation mode. |
| `hot_streak_under_obs` | UNDER + over_rate_last_10 >= 0.7 (feature 55) | 44.4% UNDER HR (N=18) vs 81-87% when cold | 442 | Betting UNDER on a hot player is anti-signal. Uses f55 (over_rate_last_10). Observation mode. |
| `player_under_suppression_obs` | UNDER + player UNDER HR < 35% at N >= 20 (enabled models) | Herro 22.5% (all models, N=40) | 451 | Direction-specific. Won't fire until fleet has 4-6 weeks history (~Mar 24). Check date: **Mar 24**. |
| `under_low_rsc` | UNDER + real_sc < 2 + edge < 7 | Mar 8: 6/7 UNDER losses had rsc 1-2 | 452 | **PROMOTED Session 452** to active filter. |
| `ft_variance_under_obs` | UNDER + fta_avg_last_10 >= 5 + fta_cv >= 0.5 | 56.0% CF HR (5-season) | 462 | **DEMOTED Session 462** from active. 5-season CF HR shows blocking winners. |
| `familiar_matchup_obs` | 6+ games vs opponent | 54.4% CF HR (5-season) | 462 | **DEMOTED Session 462** from active. 5-season CF HR shows blocking winners. |
| `b2b_under_block_obs` | UNDER + rest_days <= 1 | 54.0% CF HR (5-season) | 462 | **DEMOTED Session 462** from active. 5-season CF HR shows blocking winners. |
| ~~`over_line_rose_heavy_obs`~~ | ~~OVER + BettingPros line rose >= 1.0~~ | 38.9% (N=54) | 462→**469** | **PROMOTED to active filter Session 469.** 5-season confirmed. |

---

## Combo Registry (11 SYNERGISTIC)

| Combo | Signals | Direction | HR | Status |
|-------|---------|-----------|-----|--------|
| `combo_3way` | ESO + HE + MS | BOTH | 95.5% | PRODUCTION |
| `combo_he_ms` | HE + MS | OVER_ONLY | 94.9% | PRODUCTION |
| `bench_under` | bench_under | UNDER_ONLY | 76.9% | PRODUCTION |
| See `signal_combo_registry` BQ table for full list | | | | |

---

## Production Readiness Criteria

- **Performance:** AVG HR >= 60% across eval windows
- **Coverage:** N >= 20 picks total
- **Stability:** Doesn't crash catastrophically in worst window
- **Technical:** No data quality issues, runs without errors

---

## Observation Mechanics (Session 421)

Three edge overconfidence mitigations in observation mode. Data logged but no ranking/filtering changes.

### Player-Tier Edge Caps

| Tier | Line Range | Cap | Edge 7+ HR (pre-ASB) |
|------|-----------|-----|---------------------|
| Bench | < 12 | 5.0 | 34.1% (N=91) |
| Role | 12-17.5 | 6.0 | 43.1% (N=72) |
| Starter | 18-24.5 | uncapped | 63.2% (N=57) |
| Star | 25+ | uncapped | — |

BQ columns: `player_tier`, `tier_edge_cap_delta`, `capped_composite_score` on `signal_best_bets_picks`.

### Market Compression Detector

Compares 7d vs 30d P90 edge. Ratio < 0.70 = RED, 0.70-0.85 = YELLOW, > 0.85 = GREEN.
BQ columns: `compression_ratio`, `compression_scaled_edge` on `signal_best_bets_picks`.
Source: `ml/signals/regime_context.py::get_market_compression()`.

### Activation Criteria

| Mitigation | Activate When | Change |
|-----------|--------------|--------|
| Tier caps | 2+ weeks, capped HR < 50% at N >= 20 | Use `capped_composite_score` for ranking |
| Compression | 30+ days, RED edge 5+ HR < 50% at N >= 30 | Multiply composite by compression_ratio |
| Feature reliability | 2+ weeks, flagged HR < 45% at N >= 15 | Promote to active filter |

---

**Last Updated:** 2026-03-08, Session 442
**Source of truth for active signals.** CLAUDE.md has a summary; this is the full reference.

### Shadow Signal Promotion Criteria

| Signal Type | Promote to Production | Promote to Rescue | Disable |
|------------|----------------------|-------------------|---------|
| Positive signal | HR >= 60%, N >= 30 | HR >= 65% at edge 0-5, N >= 15 | HR < 50%, N >= 30 |
| Negative filter | Tagged picks HR < 50%, N >= 30 | N/A | Tagged picks HR >= 55% |
| UNDER signal | Add to `UNDER_SIGNAL_WEIGHTS` with HR-derived weight | N/A | N/A |

### Shadow Validation Query

```sql
WITH shadow_picks AS (
  SELECT pst.player_lookup, pst.game_date, pst.system_id, signal_tag
  FROM nba_predictions.pick_signal_tags pst
  CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
  WHERE signal_tag IN ('projection_consensus_over', 'projection_consensus_under',
    'predicted_pace_over', 'dvp_favorable_over',
    'positive_clv_over', 'positive_clv_under',
    'sharp_money_over', 'sharp_money_under', 'minutes_surge_over',
    'hot_form_over', 'consistent_scorer_over', 'over_trend_over',
    'volatile_starter_under', 'downtrend_under', 'star_favorite_under',
    'starter_away_overtrend_under')
    AND game_date >= '2026-03-05'
)
SELECT sp.signal_tag,
  COUNT(*) as fires, COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM shadow_picks sp
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON sp.player_lookup = pa.player_lookup AND sp.game_date = pa.game_date AND sp.system_id = pa.system_id
GROUP BY 1 ORDER BY fires DESC
```
