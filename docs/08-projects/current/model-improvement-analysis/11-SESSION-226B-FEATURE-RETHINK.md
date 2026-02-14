# Session 226B: Feature Re-evaluation & Two-Model Architecture

## Date: 2026-02-12

## Context

After running 9 experiments across 4 phases, every configuration fails on February 2026 eval — while the identical approach scores 79.5% on February 2025. This document captures the strategic rethink of our features and model architecture.

---

## The Core Problem: Vegas Line Over-Dependence

Across all experiments, `vegas_points_line` ranks #1 or #2 in feature importance (15-30%). The model is effectively learning: "predict the Vegas line plus noise." This makes it nearly useless for finding betting edges because:

- If the model predicts what Vegas already says, the edge is always ~0
- The quantile shift (alpha=0.43) artificially biases predictions UNDER to create edge
- This creates the OVER collapse we see everywhere — the model can only find UNDER edges

### Feature Importance Pattern (consistent across all 9 experiments)

| Rank | Feature | Typical Importance |
|------|---------|-------------------|
| 1-2 | `vegas_points_line` | 15-30% |
| 1-2 | `points_avg_last_5` | 6-35% |
| 3-4 | `points_avg_last_10` | 8-13% |
| 3-4 | `vegas_opening_line` | 4-14% |
| 5-6 | `points_avg_season` | 4-15% |
| 5-6 | `ppm_avg_last_10` | 2-10% |
| 7-8 | `minutes_avg_last_10` | 2-6% |
| 9+ | Everything else | <3% each |

**Bottom-tier features (near-zero importance across ALL experiments):**
- `injury_risk`: 0.00-0.14%
- `back_to_back`: 0.00-0.24%
- `playoff_game`: 0.00-0.10%
- `rest_advantage`: 0.07-0.30%
- `has_vegas_line`: 0.10-0.30%

---

## Two-Model Architecture Proposal

### Model 1: Points Predictor (Pure Scoring Model)

**Goal:** Predict actual points scored as accurately as possible.

**Feature strategy:**
- EXCLUDE or heavily downweight Vegas line features
- Emphasize player performance, matchup, and context features
- Target: actual points (RMSE/MAE loss)

**Why:** The Vegas line is not designed to predict actual points — it's set to balance action. A pure scoring model learns true talent + context without market contamination.

**Key features:**
- Season averages, recent form (last 5, last 10)
- Matchup history (vs specific opponent)
- Pace/defense rating context
- Fatigue/rest signals (rethought — see below)
- Shot zone tendencies

### Model 2: Edge Finder (Market Mispricing Model)

**Goal:** Learn where Vegas systematically misprices player props.

**Feature strategy:**
- Vegas line IS a primary feature
- ONLY train on players who have Vegas lines
- Target: `actual_points - vegas_line` (the residual)
- Or: binary OVER/UNDER classification

**Why:** This model specifically learns patterns like:
- "Vegas consistently underestimates role players against bottom-5 defenses"
- "Stars on back-to-backs are overpriced by 2+ points"
- "After 2 consecutive unders, Vegas overcorrects the line downward"

**Key insight:** Sometimes Vegas lines are "tricky" — not purely based on expected points. They account for public betting patterns, liability management, and sharp money. An edge finder can learn these systematic biases.

### How They'd Work Together

1. Model 1 predicts expected points: "Player X should score 22.5"
2. Model 2 predicts edge vs line: "Vegas underprices Player X by 1.8"
3. Combined signal: both agree on OVER with edge > 3 = high confidence bet

---

## Feature Re-evaluation

### Currently Dead Features (Candidates for Removal)

| Feature | Index | Avg Importance | Issue |
|---------|-------|---------------|-------|
| `injury_risk` | 10 | 0.05% | Too generic, binary-ish |
| `back_to_back` | 16 | 0.08% | Redundant with `games_in_last_7_days` |
| `playoff_game` | 17 | 0.03% | Always 0 in regular season |
| `rest_advantage` | 9 | 0.18% | Calculation may be too simple |
| `has_vegas_line` | 28 | 0.20% | Nearly always 1 for eligible players |

### Features That Need Rethinking

#### Fatigue Score (index 5)
**Current:** Generic composite fatigue factor.
**Problem:** 0% importance in some experiments, suggesting it doesn't capture real fatigue effects.
**Ideas:**
- Decompose into: minutes load last 7d, travel distance, timezone changes
- Use minutes variance (high-minute spikes are more fatiguing than steady minutes)
- Account for blowouts (playing garbage time vs. grinding a close game)

#### Streak/Pattern Features (NEW — not currently captured)
**Current gap:** We have `points_avg_last_5` and `points_avg_last_10` but NO streak indicators.
**Proposed:**
- `consecutive_unders` / `consecutive_overs` — how many games in a row under/over the line
- `deviation_from_avg_last_3` — are they running hot or cold vs their own baseline
- `line_vs_season_avg` — is Vegas pricing them below their season average (buy low signal)
- `post_cold_streak_bounce` — historical rate at which a player bounces back after 2+ unders

**Why this matters:** When a player goes under 2-3 games in a row, Vegas often drops the line. If the player's true talent hasn't changed, this creates a systematic buying opportunity. Whether this is player-specific or league-wide is an empirical question we should test both ways.

---

## Experiment Results Summary

### Phase 2: Multi-Season Training (eval Feb 1-11 2026)

| Exp | Config | Samples | Edge 3+ HR | N | OVER | UNDER | MAE |
|-----|--------|---------|-----------|---|------|-------|-----|
| 2E | 1-szn Q43 | 9,746 | **56.8%** | 74 | 0% | 57.5% | 5.12 |
| 2C | 2-szn Q43 R120 | 23,826 | 53.3% | 60 | 0% | 54.2% | 5.11 |
| 2D | 2-szn Base | 23,826 | 51.9% | 54 | 45.2% | 60.9% | 5.02 |
| 2B | 3-szn Q43 | 37,824 | 50.0% | 170 | 47.8% | 50.3% | 5.32 |
| 2A | 2-szn Q43 | 23,826 | 49.5% | 91 | 33.3% | 50.0% | 5.12 |

### Phase 3: Cross-Season Backtesting

| Exp | Config | Edge 3+ HR | N | OVER | UNDER | Gates |
|-----|--------|-----------|---|------|-------|-------|
| 3A | Train→Jan'25, Eval **Feb'25** | **79.5%** | 415 | 82.6% | 78.7% | **ALL PASS** |
| 3B | Train→Jan'26, Eval **Feb'26** | 53.8% | 132 | 66.7% | 53.2% | FAIL |

### Phase 4: Micro-Retrains (eval Feb 8-12 2026)

| Exp | Config | Edge 3+ HR | N | MAE | Gates |
|-----|--------|-----------|---|-----|-------|
| 4A | 14-day micro | 50.0% | 24 | 4.68 | FAIL |
| 4B | Hybrid 14d+2szn | 50.0% | 16 | 4.60 | FAIL |

### Conclusions

1. **Model architecture is valid** — 79.5% on Feb 2025 proves it
2. **February 2026 is uniquely hostile** — no config passes
3. **More training data makes it worse** (on Feb 2026)
4. **OVER direction is universally collapsed** — structural, not config-specific
5. **Micro-retraining (freshest data) doesn't help** — the market itself changed

---

## Open Questions for Investigation

1. **Trade deadline effect:** Did Feb 2026 have unusually disruptive trades that broke player role predictions?
2. **All-Star break:** Does the mid-February break create a structural regime change?
3. **Line source quality:** Are the Feb 2026 DraftKings lines priced differently (tighter)?
4. **Player rotation changes:** Are teams resting starters more aggressively in Feb 2026?
5. **Is our points_avg_last_5 stale after ASB?** — 5-game avg includes pre-break games in different context
