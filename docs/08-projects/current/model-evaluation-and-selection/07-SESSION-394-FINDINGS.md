# Session 394 Findings — Analysis Results & Recommendations

**Date:** 2026-03-03
**Status:** Complete
**Scope:** Edge calibration, prediction correlation, filter audit, SC=3 analysis, tooling

## Tools Built

### 1. `bin/simulate_best_bets.py` (Priority 1 — DONE)

Simulates any model through the full best bets pipeline (filters + signals + ranking), bypassing per-player selection. This is the most important missing tool — it lets us evaluate models that never win selection in production.

**Usage:**
```bash
# Simulate a specific model
python bin/simulate_best_bets.py --model catboost_v16_noveg_train1201_0215 \
    --start-date 2026-02-01 --end-date 2026-02-28

# Compare two models side-by-side (includes bootstrap significance test)
python bin/simulate_best_bets.py --model catboost_v16_noveg_train1201_0215 \
    --compare catboost_v12_noveg_train0110_0220 \
    --start-date 2026-02-01 --end-date 2026-02-28

# Simulate production multi-model pipeline
python bin/simulate_best_bets.py --multi-model \
    --start-date 2026-02-01 --end-date 2026-02-28 --verbose
```

**Output:** HR by direction, edge band, signal count; filter rejection breakdown; P&L at -110 odds; zero-pick days; daily results.

### 2. `bin/bootstrap_hr.py` (Priority 1 — DONE)

Statistical significance testing for HR comparisons. Bootstrap CI + z-test + power analysis.

**Usage:**
```bash
# Compare two hit rates
python bin/bootstrap_hr.py --a-wins 26 --a-total 32 --b-wins 52 --b-total 82

# Power analysis
python bin/bootstrap_hr.py --power --baseline-hr 0.55 --target-hr 0.65
```

**Key finding from power analysis:** Need 376 picks per group to reliably detect a 10pp HR difference at 80% power. Most of our model comparisons have N < 30 — they are NOT statistically significant.

### 3. Training Window Sweep Template (Priority 1 — DONE)

Added `training_window_sweep` and `training_window_v16` templates to `grid_search_weights.py`.

**Usage:**
```bash
# Sweep 7 window sizes (28-70 days) for V12_noveg
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template training_window_sweep \
    --train-start 2025-12-01 --train-end 2026-02-15 \
    --eval-start 2026-02-16 --eval-end 2026-02-28

# Same for V16
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template training_window_v16 \
    --train-start 2025-12-01 --train-end 2026-02-15 \
    --eval-start 2026-02-16 --eval-end 2026-02-28
```

---

## Analysis Results

### Q7: Edge Calibration — Are Edges Meaningful?

**OVER edge is monotonically calibrated:**

| Edge Band | N | HR% |
|-----------|---|-----|
| 3-4 | 919 | 56.4% |
| 4-5 | 538 | 58.0% |
| 5-7 | 566 | 60.1% |
| 7-10 | 298 | 63.8% |
| 10+ | 308 | 69.2% |

**UNDER edge breaks at 10+:**

| Edge Band | N | HR% |
|-----------|---|-----|
| 3-4 | 2,270 | 54.2% |
| 4-5 | 1,462 | 58.1% |
| 5-7 | 1,455 | 57.7% |
| 7-10 | 708 | 61.3% |
| 10+ | 291 | **58.4%** (drops back) |

**Key findings:**
1. **OVER edge is well-calibrated.** Monotonic from 56% to 69%. The system's "rank by edge" approach works for OVER.
2. **UNDER edge 10+ is overconfident.** Drops from 61.3% back to 58.4%. The model predicts too far below the line. Consider capping UNDER edge credit at 10.
3. **OVER consistently outperforms UNDER** at every edge band. Gap widens at 10+: OVER 69.2% vs UNDER 58.4% (+10.8pp).
4. **Models disagree wildly on edge meaning.** At edge 5-7, HR ranges from 16.7% to 81.8% depending on model. Edge values are NOT comparable across models.
5. **Production catboost_v12 has INVERTED calibration** at 5-7 (44.0% vs 56.5% at 3-5). Its high-edge picks are WORSE.

### Q8: Prediction Correlation — Are 16 Models Actually 3?

**Answer: 12 enabled models are functionally 2 models.**

**Cluster A: "The CatBoost Monolith" (11 models)**
- All CatBoost V12/V16 variants: r = 0.971–0.990
- Direction agreement: 93–100%
- Average prediction difference: <1 point

**Cluster B: "The Lone LightGBM" (1 model)**
- `lgbm_v12_noveg_train0103_0227`: r = 0.938–0.960 vs CatBoost
- Direction agreement: 88–91%
- Most diverse model, but still shares 88% of variance

**Historical diversity (now disabled):**
- `catboost_v9 vs zone_matchup_v1`: r = 0.416 (71% agreement)
- `catboost_v8 vs zone_matchup_v1`: r = 0.682 (56% agreement)
- These were genuinely different perspectives. Nothing like them in the current fleet.

**Implications:**
- Running 12 models that agree 95%+ is burning compute for near-zero information gain
- Per-player selection chooses from nearly identical candidates — the "winner" is determined by sub-1-point random variation
- Model agreement signals are meaningless when all models are clones

### Q9: Filter Temporal Audit

The `best_bets_filter_audit` table only has 1 day of data (March 3, recently deployed). Cannot do temporal degradation analysis across Dec/Jan/Feb.

**Current snapshot (March 3):**
- Total candidates: 16, passed: 1 (6.25% pass rate)
- Top rejections: `away_noveg` 37.5%, `over_edge_floor` 25%, `line_jumped_under` 12.5%, `star_under` 12.5%

**Recommendation:** Need 30+ days of filter audit data before this analysis is meaningful. Revisit in late March.

### SC=3 Elimination Analysis

**SC=3 overview:**

| SC | Picks | HR% | P&L | P&L per Pick |
|----|-------|-----|-----|-------------|
| 3 | 49 | 55.1% | +2.80 | +0.057 |
| 4+ | 67 | 73.1% | +33.40 | +0.499 |

SC=3 = 42% of picks but only 7.7% of P&L. SC=4+ is 8.7x more capital-efficient.

**SC=3 by direction — the real story:**

| Direction | SC Group | N | HR% | P&L |
|-----------|----------|---|-----|-----|
| **OVER** | **SC=3** | **11** | **45.5%** | **-1.60** |
| OVER | SC=4+ | 59 | 74.6% | +27.50 |
| UNDER | SC=3 | 38 | 57.9% | +4.40 |
| UNDER | SC=4+ | 8 | 87.5% | +5.90 |

**SC=3 OVER is a net loser** at 45.5% HR, -1.6 units. SC=3 UNDER is profitable at 57.9%.

**SC=3 by period:**

| Period | SC Group | N | HR% | P&L |
|--------|----------|---|-----|-----|
| Jan | SC=3 | 25 | 56.0% | +1.90 |
| Jan | SC=4+ | 42 | 83.3% | +27.30 |
| Feb | SC=3 | 24 | 54.2% | +0.90 |
| Feb | SC=4+ | 23 | 60.9% | +4.10 |

**Volume impact of dropping all SC=3:**
- Current avg daily picks: 3.02
- SC=4+ only: 1.71 (-43%)
- Zero-pick days: 0 → 12 (28.6% of game days)

---

## Concrete Recommendations

### Recommendation 1: Block SC=3 OVER (Not All SC=3) — IMMEDIATE

**Action:** Change the existing `sc3_edge_floor` filter to block ALL SC=3 OVER picks, not just those below edge 7.

**Impact:** +1.6 units P&L, eliminates 11 losing picks, minimal volume loss.

**Current filter (aggregator.py):**
```python
# SC=3 OVER edge restriction: SC=3 + OVER needs edge >= 7
```

**Proposed change:**
```python
# SC=3 OVER block: SC=3 + OVER picks are net losers (45.5% HR, -1.6 units)
if signal_count == 3 and direction == 'OVER':
    reject('sc3_over_block')
```

SC=3 UNDER stays — it's profitable at 57.9% HR.

### Recommendation 2: Cap UNDER Edge Credit at 10 — MEDIUM PRIORITY

UNDER edge 10+ drops to 58.4% (vs 61.3% at 7-10). Extremely high UNDER edges are overconfident.

**Options:**
- A. Hard cap: `effective_edge = min(abs(edge), 10)` in ranking
- B. Skepticism filter: UNDER + edge >= 10 → require SC >= 5

### Recommendation 3: Fleet Rationalization — HIGH PRIORITY

11 CatBoost models with r > 0.97 is waste. The fleet should be pruned to:

1. **Keep 2-3 CatBoost V12 variants** (freshest training windows only)
2. **Keep 1 V16 model** (slightly different features, even if r=0.97)
3. **Keep LightGBM** (only genuine diversity at r=0.94)
4. **Disable the rest** — they add compute cost without information

**Target fleet:** 4-5 models instead of 12.

**To get REAL diversity, you need:**
- Different target formulations (binary over/under vs regression)
- Different feature engineering (player-focused vs matchup-focused vs market-focused)
- Different architectures (tree vs linear vs neural)
- The historical `zone_matchup_v1` (r=0.42 vs CatBoost) was genuinely diverse

### Recommendation 4: Shadow Monitoring — Option B (Post-Hoc Simulation)

From `05-SHADOW-MONITORING.md`, I recommend **Option B** for these reasons:

1. **Option A (Full Shadow Pipeline)** doubles prediction compute cost for models that are disabled for good reason. Not justified when the fleet is already 11 near-identical models.
2. **Option B (Post-Hoc Simulation)** uses `simulate_best_bets.py` (now built!) to retroactively evaluate any model's "would-be" best bets. Zero additional compute cost. Can run on-demand or daily.
3. **Option C (Manual Only)** is too easy to forget.

**Implementation:** Add a daily cron (or Cloud Function) that runs `simulate_best_bets.py --model MODEL --start-date YESTERDAY --end-date YESTERDAY` for each recently-disabled model and writes results to `shadow_best_bets_daily` BQ table. Alert if shadow model BB HR > 65% over 14 days.

### Recommendation 5: Per-Model Filters — NOT YET

From Q1 analysis: we don't have enough data to justify per-model filter criteria.

- `model_profile_daily` is in observation mode
- Most newer models have <30 graded edge 3+ picks
- Any HR difference <5pp is within noise at these sample sizes (need 376+ per group)

**Revisit when:** At least 3 models have 50+ graded edge 3+ picks each.

### Recommendation 6: EV Ranking — DEFERRED

Expected value ranking (`edge × P(win)`) requires calibrated per-model P(win) estimates. Edge calibration analysis shows models disagree wildly on what edge means. We'd need 200+ graded picks per model × direction × edge band to build reliable calibration curves.

**Prerequisite:** Fleet rationalization (Rec 3) → accumulate data on fewer models → build calibration curves → then test EV ranking.

### Recommendation 7: V16 Fresh Retrain — NEXT SESSION

V16 shows promise (66.7% HR, best-calibrated edges) but is trained on old data (Dec 1 - Feb 15). Use the new training window sweep template:

```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template training_window_v16 \
    --train-start 2025-12-01 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-03
```

---

## Summary

| Action | Priority | Effort | P&L Impact |
|--------|----------|--------|------------|
| Block SC=3 OVER | **IMMEDIATE** | 10 min | +1.6 units |
| Cap UNDER edge at 10 | Medium | 30 min | Unknown (need sim) |
| Fleet rationalization | **HIGH** | 1 hour | Reduced compute |
| Shadow monitoring (Option B) | Medium | 2 hours | Information preservation |
| V16 fresh retrain | Next session | 1 hour | Potential improvement |
| Per-model filters | Deferred | N/A | Need more data |
| EV ranking | Deferred | N/A | Need calibration first |
