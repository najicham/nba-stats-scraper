# Signal Inventory — Complete List

**Last Updated:** 2026-03-04 (Session 404)
**Active Signals:** 26 (+ 8 shadow accumulating data)
**Negative Filters:** 17
**Combo Registry:** 11 SYNERGISTIC entries

---

## Architecture

**Edge-first:** Signals filter and annotate picks, not select them. Rankings are by edge (OVER) or signal quality score (UNDER).

**SC Architecture (Session 397):** `real_sc` = non-base signal count. Base signals (`model_health`, `high_edge`, `edge_spread_optimal`) fire on ~100% of picks, inflating total SC to 3 with zero discriminative power. All SC-based filters use `real_sc` instead of total SC.

**Best Bets Pipeline:** `edge 3+ (or signal rescue) → negative filters → signal count ≥ 3 → real_sc gate (OVER: real_sc>0, UNDER edge<7: real_sc>0) → rank by edge`

**Signal Rescue (Session 398):** Picks below edge 3.0 (or OVER below 5.0) bypass edge floors if they have a validated high-HR signal or 2+ real signals. Tracked via `signal_rescued` + `rescue_signal` in BQ.

Rescue tags: `combo_3way`, `combo_he_ms`, `book_disagreement` (72%), `home_under` (75%), `low_line_over` (66.7%), `volatile_scoring_over` (66.7%), `high_scoring_environment_over` (100% edge 3-5), `sharp_book_lean_over` (70.3%), `sharp_book_lean_under` (84.7%). Signal stacking: 2+ real signals = 62.2% HR (N=45).

**UNDER ranking (Session 400):** Signal-first, not edge-first. UNDER edge is flat at 52-53% across ALL edge buckets — ranking by edge is meaningless for UNDER. Weighted signal quality score ranks UNDER picks.

**Pick Angles:** Each pick includes `pick_angles` — human-readable reasoning. See `ml/signals/pick_angle_builder.py`.

---

## Active Signals (26)

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
| `volatile_scoring_over` | OVER | 81.5% | PRODUCTION | Session 374 |
| `low_line_over` | OVER | 78.1% | PRODUCTION | Session 374 |
| `b2b_boost_over` | OVER | 64.3% | PRODUCTION | Session 396, inverse of b2b_fatigue_under |
| `q4_scorer_over` | OVER | 64.4% | PRODUCTION | Session 397, from BDL PBP Q4 ratio |
| `denver_visitor_over` | OVER | 67.8% | PRODUCTION | Session 398, altitude effect |
| `day_of_week_over` | OVER | 66-70% | PRODUCTION | Session 398, Mon/Thu/Sat boost |
| `sharp_book_lean_over` | OVER | 70.3% | PRODUCTION | Session 399, sharp books 1.5+ higher than soft |

### UNDER Signals (5)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `bench_under` | UNDER | 76.9% | PRODUCTION | |
| `home_under` | UNDER | 63.9% | PRODUCTION | Session 371 |
| `extended_rest_under` | UNDER | 61.8% | PRODUCTION | Session 372 |
| `starter_under` | UNDER | 54.8-68.1% | PRODUCTION | Session 372 |
| `sharp_book_lean_under` | UNDER | 84.7% | PRODUCTION | Session 399, soft books 1.5+ higher |

### BOTH Direction (1)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `book_disagreement` | BOTH | 93.0% | WATCH | |

### WATCH / Special (2)

| Signal | Direction | HR | Status | Notes |
|--------|-----------|-----|--------|-------|
| `ft_rate_bench_over` | OVER | 72.5% | WATCH | |
| `rest_advantage_2d` | BOTH | 64.8% | DISABLED | Session 396 — re-enable October |

---

## Shadow Signals (8) — Session 401, accumulating data

| Signal | Direction | Source | Notes |
|--------|-----------|--------|-------|
| `projection_consensus_over` | OVER | FantasyPros, DFF, Dimers, NumberFire | 2+ sources above line + OVER |
| `projection_consensus_under` | UNDER | Same 4 sources | 2+ sources below line + UNDER |
| `projection_disagreement` | BOTH | Same 4 sources | 0 sources agree — caution filter |
| `predicted_pace_over` | OVER | TeamRankings pace | Top-10 pace matchup |
| `dvp_favorable_over` | OVER | Hashtag Basketball DvP | Bottom-5 defense |
| `positive_clv_over` | OVER | Odds API closing lines | Closing line value confirms edge |
| `positive_clv_under` | UNDER | Odds API closing lines | CLV confirms UNDER direction |
| `negative_clv_filter` | BOTH | Odds API closing lines | CLV contradicts — negative filter |

---

## Disabled / Removed Signals

| Signal | HR | Disabled | Reason |
|--------|-----|---------|--------|
| `blowout_recovery` | 50.0% | Session 349 | 25% in Feb, not reliable |
| `b2b_fatigue_under` | 39.5% Feb | Session 373 | Boosts losing pattern |
| `prop_line_drop_over` | 53.3% Feb | Session 374b | Conceptually backward — line drops are bearish |
| `dual_agree` | 45.5% | Session 275 | V9+V12 agreement anti-correlated |
| `hot_streak_2/3` | 45-47% | Session 275 | Net negative, false qualifier |
| `cold_continuation_2` | 45.8% | Session 275 | Never above breakeven |
| 6 "never fire" signals | N=0 | Session 275 | Dead code — see Session 275 notes |

---

## Negative Filters (17)

| # | Filter | Condition | HR | Session |
|---|--------|-----------|-----|---------|
| 1 | Player blacklist | <40% HR on 8+ edge-3+ picks | varies | — |
| 2 | Avoid familiar | 6+ games vs opponent | varies | — |
| 3 | Edge floor | edge < 3.0 (bypassed by rescue) | — | 352 |
| 4 | Model-direction affinity | HR < 45% on 15+ picks for model+direction+edge combo | <45% | 343 |
| 5 | Feature quality floor | quality < 85 | 24.0% | — |
| 6 | Bench UNDER block | UNDER + line < 12 | 35.1% | — |
| 7 | UNDER + line jumped 2+ | prop_line_delta >= 2.0 | 38.2% | — |
| 8 | UNDER + line dropped 2+ | prop_line_delta <= -2.0 | 35.2% | — |
| 9 | Away block | REMOVED Session 401 | — | 401 |
| 10 | Signal density | base-only signals, skip unless edge ≥ 7.0 | — | 352 |
| 11 | Opponent UNDER block | UNDER + opponent in {MIN, MEM, MIL} | 43.8-48.7% | 372 |
| 12 | SC=3 OVER block | OVER + signal_count == 3 | 45.5% | 394 |
| 13 | OVER + line dropped 2+ | OVER + prop_line_delta <= -2.0 | 39.1% | 374b |
| 14 | Opponent depleted UNDER | UNDER + 3+ opponent stars out | 44.4% | 374b |
| 15 | Q4 scorer UNDER block | UNDER + Q4_ratio >= 0.35 | 34.0% | 397 |
| 16 | Friday OVER block | OVER + Friday | 37.5% | 398 |
| 17 | High skew OVER block | OVER + mean_median_gap > 2.0 | 49.1% | 399 |

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

**Last Updated:** 2026-03-04, Session 404
**Source of truth for active signals.** CLAUDE.md has a summary; this is the full reference.
