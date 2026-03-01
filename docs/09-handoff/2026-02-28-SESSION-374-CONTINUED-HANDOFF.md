# Session 374 Continued Handoff — Filter Experiments, Fleet Triage & Deep Research

**Date:** 2026-02-28
**Prior Session:** 374 (2 shadow models deployed, percentile features dead end)

---

## What Was Done

### Phase 1: BQ Validation Queries (5 planned experiments)

All 5 filter/signal hypotheses were tested against best-bets-level data. **None passed decision gates:**

| Experiment | Result | Decision |
|---|---|---|
| **E1: Low CV UNDER block** | N=3 at best bets, HR=66.7% | SKIP — filter stack handles it |
| **E2: Adaptive signal floor** | Feb SC=3 = 57.1% (above breakeven) | SKIP — no SC below breakeven in Feb |
| **E3: Slate size filter** | Light slate N=6 total | SKIP — too rare to implement |
| **E4: Time slot x direction** | Worst = primetime UNDER 55.2% raw | SKIP — nothing below 45% |
| **E5: Model agreement signal** | 2+ models = 92.3% HR (N=13) | SKIP — 12/13 from Jan, redundant |

### Shadow Fleet Triage (14-day window, Feb 14-27)

22 enabled models in registry. No DISABLE (HR<40% N>=20) or PROMOTE (HR>55% N>=30) candidates beyond known v9_low_vegas (56.7%, N=60). Session 374 models deployed Mar 1 via BQ registry, not yet generating predictions. Worker loads from `model_registry` table, not GCS manifest.

### Phase 2: Deep Multi-Dimensional Research (5 parallel agents)

Launched 5 research agents covering 27 BQ queries across minutes groupings, scoring patterns, opponent/matchup, signal combos, and feature interactions. **All queries ran at best-bets level (N=110 graded picks, Dec 1 - Feb 27).**

---

## Research Findings — Prioritized

### TIER 1: High-Confidence Filter Candidates (implement next session)

| # | Pattern | HR | N | Source | Mechanism |
|---|---|---|---|---|---|
| **F1** | **SC=3 + edge 5-7** | **48.4%** | **31** | Signal Combo Agent | Biggest profit leak. SC=4+ same edge = 70-76%. Fix: restrict SC=3 to edge 7+ only (85.7% there). |
| **F2** | **Season avg > line by 3+ pts, OVER** | **47.6%** | **21** | Usage Agent | When player averages 3+ above prop line, OVER loses. Market already prices regression. `feature_1_value - line_value > 3` |
| **F3** | **Avg implied total (108-115) + OVER** | **46.7%** | **15** | Feature Agent | Average-scoring environments are OVER death zone. High (115+) = 79.2%, Low (<108) = 80%. Only the middle loses. |
| **F4** | **Mid 3PT (15-30%) + OVER** | **46.2%** | **13** | Feature Agent | Hybrid scorers OVER fails. U-shaped: paint (<15%) = 88.9%, heavy 3PT (45%+) = 77.4%. Middle loses. |
| **F5** | **AWAY + high line (25+) + UNDER** | **30.0%** | **10** | Opponent Agent | Stars on the road go off. Luka 4x in this bucket. Complements existing model-family AWAY block. |

**IMPORTANT:** F2, F3, F4 may overlap (same losing OVER picks failing for correlated reasons). Must validate overlap before implementing all three. Run intersection query first.

### TIER 2: Strong Signal Candidates (implement as signals)

| # | Pattern | HR | N | Source | Notes |
|---|---|---|---|---|---|
| **S1** | **3 days rest + OVER** | **91.7%** | **12** | Feature Agent | Rested players crush OVER. Mirror: 3d rest UNDER = 0% (N=3). Extends existing rest_advantage_2d concept. |
| **S2** | **OVER + very fast pace (102+)** | **81.5%** | **27** | Opponent Agent | More possessions = more scoring. Largest high-HR cell with meaningful N. |
| **S3** | **Very volatile scoring (50%+ CV) + OVER** | **81.5%** | **27** | Minutes Agent | High-variance scorers going OVER. Validated at raw level too (61.9%, N=845). |
| **S4** | **Low-line (<12) + OVER** | **78.1%** | **32** | Minutes Agent | Role players OVER on low lines. Largest single high-HR group. |
| **S5** | **Hot streak (L5 > L10 by 10%+) + OVER** | **79.2%** | **24** | Usage Agent | Momentum-driven OVER. |
| **S6** | **HOME + high line (25+) + UNDER** | **90.0%** | **10** | Opponent Agent | Stars at home get rest in comfortable wins. Mirror of F5. |
| **S7** | **Slightly high line (avg-line -3 to 0) + UNDER** | **76.5%** | **17** | Usage Agent | Market slightly overvalues → UNDER wins. |
| **S8** | **Starter (25-32 min) + low line (<15) + OVER** | **88.9%** | **18** | Minutes Agent | Starters on low lines going OVER is elite. |

### TIER 3: Structural Insights (informational, no immediate action)

1. **OVER scales monotonically with edge** (67.6% → 77.8%), but **UNDER has a dead zone at edge 5-7** (56.3%) — moderate UNDER edge (3-5) at 62.5% actually beats strong edge (5-7).
2. **v12_mae OVER = 90.0% (N=20)** vs UNDER = 53.3% (N=15). v9_mae carries 58% of volume at 63.9% combined.
3. **Repeat within 3 days = 50.0% (N=10)** — picking same player back-to-back loses edge. Repeat within week = 90.0% (N=10, hot hand effect).
4. **1 star teammate out boosts both directions** (83.3% OVER, 75.0% UNDER, N=20). Model handles this feature well.
5. **OVER collapsed 80% → 56% Jan → Feb** (-24pp). UNDER stable at 63% → 61% (-2pp). Feb degradation is OVER-specific.
6. **combo_3way and combo_he_ms always co-occur** (both N=17, identical wins). Effectively one signal with two tags.
7. **prop_line_drop_over underperforms** at 62.5% — below system avg 67.3%. Monitor for potential removal.
8. **Friday = 42.9% (N=14), Saturday OVER = 91.7% (N=12)** — day-of-week patterns exist but N too small.

---

## Implementation Plan for Next Session

### Step 1: Validate Filter Overlaps (MUST DO FIRST)

```sql
-- Check if F2, F3, F4 overlap (same picks failing for correlated reasons)
SELECT
  CASE WHEN (fs.feature_1_value - sbp.line_value) > 3 THEN 1 ELSE 0 END AS f2_flag,
  CASE WHEN fs.feature_42_value BETWEEN 108 AND 115 THEN 1 ELSE 0 END AS f3_flag,
  CASE WHEN fs.feature_20_value BETWEEN 0.15 AND 0.30 THEN 1 ELSE 0 END AS f4_flag,
  COUNT(*) AS n,
  COUNTIF(prediction_correct) AS wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr
FROM nba_predictions.signal_best_bets_picks sbp
LEFT JOIN nba_predictions.ml_feature_store_v2 fs
  ON fs.player_lookup = sbp.player_lookup AND fs.game_date = sbp.game_date
WHERE sbp.game_date >= '2025-12-01' AND sbp.prediction_correct IS NOT NULL
  AND sbp.recommendation = 'OVER'
GROUP BY 1, 2, 3
HAVING n >= 3
ORDER BY hr ASC
```

### Step 2: Implement F1 (SC=3 + edge restriction)

**Highest confidence, largest N, simplest to implement.**

Modify `ml/signals/aggregator.py` signal_count filter:
```python
# Current: skip if signal_count < MIN_SIGNAL_COUNT (3)
# New: skip if signal_count == 3 AND edge < 7.0
if signal_count < self.MIN_SIGNAL_COUNT:
    filter_counts['signal_count'] += 1
    continue
if signal_count == 3 and abs(edge) < 7.0:
    filter_counts['sc3_edge_floor'] += 1
    continue
```

Expected impact: removes ~31 picks at 48.4% HR, keeps ~7 SC=3 edge 7+ picks at 85.7% HR.

### Step 3: Implement F5 (AWAY + star UNDER block)

Add to aggregator after existing away_noveg block:
```python
if (pred.get('recommendation') == 'UNDER'
        and not pred.get('is_home', True)
        and line_val >= 25):
    filter_counts['away_star_under'] += 1
    continue
```

### Step 4: Implement top signals (S1-S4)

Each follows the standard signal pattern: create class in `ml/signals/`, register in `registry.py`, add pick angle.

Priority order: S2 (fast pace OVER, N=27) → S3 (volatile OVER, N=27) → S4 (low-line OVER, N=32) → S1 (3d rest OVER, N=12)

### Step 5: Backfill validation

```bash
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-01 --end 2026-02-27 --compare
```

---

## Feature Store Column Reference (used in queries)

| Feature | Column | Used In |
|---|---|---|
| points_avg_season | feature_1_value | F2 (season avg vs line) |
| points_avg_last_5 | feature_2_value | S5 (hot streak) |
| points_std_last_10 | feature_3_value | S3 (scoring volatility) |
| points_avg_last_10 | feature_4_value | S5 (hot streak) |
| pct_three | feature_5_value (or 20) | F4 (3PT dependency) |
| minutes_avg_last_10 | feature_8_value | S4, S8 (minutes bands) |
| opponent_def_rating | feature_17_value | Opponent defense analysis |
| opponent_pace | feature_18_value | S2 (fast pace) |
| star_teammates_out | feature_37_value | Stars out analysis |
| days_rest | feature_39_value | S1 (3 days rest) |
| implied_team_total | feature_42_value | F3 (implied total) |

**NOTE:** feature_5 vs feature_20 for pct_three — verify correct column before implementing F4.

---

## Deep Research: Infrastructure & Data Gaps (4 parallel agents)

### Referee Data
- **16,224 records exist** but **ZERO for 2025-26 season** — scraper works, API works, output never reaches GCS
- **9.7 point total scoring spread** across top/bottom referees
- **Fix:** Add dedicated Cloud Scheduler job → `nba-phase1-scrapers`, backfill ~130 game dates
- **Priority:** MEDIUM — effect is ~5pts per team, within noise

### Play-by-Play / Q4 Momentum — DEAD END
- **BigDataBall PBP active** (391K events, 672 games). NBA.com PBP has only 1 game.
- **Q4 carryover: NO SIGNAL.** 6 analyses (N=1,900). No monotonic relationship. 4.1pp spread within noise.
- **Verdict:** Q4/momentum features are dead ends. Vegas already prices player tendencies.

### Primetime/Broadcast Data
- **Full broadcast data already captured** in `nba_raw.nbac_schedule` but NOT in feature store
- **Star primetime effect: <1 point per player.** Saturday primetime stars = WORST day (-2.1 vs avg)
- **Priority:** LOW

### Injury Data — HIGHEST PRIORITY FINDINGS

#### BUG: `star_teammates_out` misses long-term injuries
- Uses `INTERVAL 10 DAY` — players out 10+ days aren't detected as stars
- **Currently missed:** Giannis (27 PPG), Tatum, Ja Morant, Franz Wagner, Anthony Davis
- **Fix:** `team_context.py:749` — use season averages as fallback

#### 2+ own-team stars out = 48.1% OVER / 48.3% UNDER (raw edge 3+)
- Feb: 34.6% OVER / 43.4% UNDER. Catastrophic with bug fix (will surface more cases).

#### Opponent star injuries: UNTRACKED
| Opp Stars Out | OVER HR | UNDER HR | N |
|---|---|---|---|
| 0 | **64.3%** | 57.6% | 3,282 |
| 1 | 56.3% (-8pp) | **59.7%** | 3,373 |
| 2+ | 58.5% | **52.1%** (-5.5pp) | 1,859 |

**No feature exists for opponent injuries.** Brand new feature opportunity.

---

## Comprehensive Next-Session Plan (Prioritized)

### TIER 1: Fix bugs + highest-impact changes
1. **Fix `star_teammates_out` 10-day window bug** — season avg fallback (`team_context.py:749`)
2. **Add `opponent_stars_out` feature** — reuse star detection for opponent team
3. **Implement F1: SC=3 edge restriction** — restrict SC=3 to edge 7+ only (remove 31 picks at 48.4%)

### TIER 2: Validate and implement filters
4. **Validate F2/F3/F4 overlap** — run intersection query first
5. **Implement F5: AWAY + star line (25+) + UNDER block** — 30% HR (N=10)
6. **Best of F2/F3/F4:** season avg > line OVER (47.6%), avg implied total OVER (46.7%), mid 3PT OVER (46.2%)

### TIER 3: Add signals
7. **S2: Fast pace (102+) OVER** — 81.5% HR, N=27
8. **S3: Volatile scoring (50%+ CV) OVER** — 81.5% HR, N=27
9. **S4: Low-line (<12) OVER** — 78.1% HR, N=32

### TIER 4: Infrastructure
10. **Fix referee scraper pipeline** — Cloud Scheduler job + backfill
11. **Fix nbac_play_by_play scraper** — only 1 game captured

### Dead Ends Confirmed This Session
- Q4 momentum/carryover, primetime scoring effect, adaptive signal floor, low CV UNDER, model agreement signal, slate size filter, time slot filter, Saturday primetime stars

---

## What Was NOT Changed
- No code changes (research-only session)
- No deployments
- No model promotions/disables
- CLAUDE.md dead ends list updated

---

## Season Performance (as of Feb 27)
- **75-36 (67.6%), +32.25 units** (ATH +33.52 on Feb 22)
- Current regime: FLAT — profitable but grinding
- Signal count 4+ = 76.0% HR
- OVER: Jan 80% → Feb 56% (collapsed)
- UNDER: Jan 63% → Feb 61% (stable)
