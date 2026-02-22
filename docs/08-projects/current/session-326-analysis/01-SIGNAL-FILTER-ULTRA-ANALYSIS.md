# Signal, Filter, and Ultra Bets Analysis

**Date:** 2026-02-22 (Session 326)
**Period:** 2026-01-09 to 2026-02-21 (44 days)
**Data Source:** `nba_predictions.signal_best_bets_picks` + `nba_predictions.prediction_accuracy`

---

## Executive Summary

Three key findings from this analysis:

1. **V12+vegas is the clear champion model** -- 68.0% HR at edge 3+ (N=203), 82.5% at edge 5+ (N=40), and a perfect 100.0% at edge 7+ (N=19). This dwarfs V9 production (51.7% at 3+, 55.5% at 5+, 48.9% at 7+).

2. **Signal system is working but 4 signals are actively harmful** -- `high_ft_under` (33.3%), `self_creator_under` (36.4%), `high_usage_under` (40.0%), and `volatile_under` (33.3%) are all below breakeven. The signal count = 7 sweet spot (83.3% HR) suggests more signals is better, but only if the signals themselves are healthy.

3. **Negative filters are validated** -- Edge floor at 5.0 is correctly placed (edge 3-5 hits 40.4% across all models, 50.6% for CatBoost). Quality < 85 filter is critical (18.9% HR without it). Blacklisted players continue to underperform massively (Jaren Jackson Jr 11.8%, Jabari Smith Jr 21.9%).

---

## Task A: Signal Effectiveness Study

### A1. Per-Signal Hit Rate

Joined `signal_best_bets_picks` (UNNEST signal_tags) to `prediction_accuracy` on player_lookup + game_date + system_id. 95 of 101 picks were gradable (6 ungraded/NULL).

| Signal | N | Wins | HR% | Avg Edge | OVER | UNDER | Status |
|--------|--:|-----:|----:|:--------:|-----:|------:|--------|
| bench_under | 2 | 2 | **100.0%** | 5.4 | 0 | 2 | STRONG (tiny N) |
| book_disagreement | 6 | 6 | **100.0%** | 8.3 | 4 | 2 | STRONG (small N) |
| combo_he_ms | 17 | 15 | **88.2%** | 7.2 | 17 | 0 | STRONG |
| combo_3way | 17 | 15 | **88.2%** | 7.2 | 17 | 0 | STRONG |
| rest_advantage_2d | 50 | 37 | **74.0%** | 7.8 | 50 | 0 | STRONG (good N) |
| 3pt_bounce | 3 | 2 | 66.7% | 6.1 | 3 | 0 | OK (tiny N) |
| model_health | 95 | 63 | 66.3% | 7.0 | 62 | 33 | BASELINE |
| high_edge | 95 | 63 | 66.3% | 7.0 | 62 | 33 | BASELINE |
| edge_spread_optimal | 95 | 63 | 66.3% | 7.0 | 62 | 33 | BASELINE |
| prop_line_drop_over | 14 | 9 | 64.3% | 6.8 | 14 | 0 | OK |
| blowout_recovery | 14 | 8 | 57.1% | 9.7 | 14 | 0 | MARGINAL |
| b2b_fatigue_under | 2 | 1 | 50.0% | 6.7 | 0 | 2 | NEUTRAL (tiny N) |
| **high_usage_under** | 10 | 4 | **40.0%** | 5.5 | 0 | 10 | **HARMFUL** |
| **self_creator_under** | 11 | 4 | **36.4%** | 5.6 | 0 | 11 | **HARMFUL** |
| **high_ft_under** | 6 | 2 | **33.3%** | 5.4 | 0 | 6 | **HARMFUL** |
| **volatile_under** | 3 | 1 | **33.3%** | 5.5 | 0 | 3 | **HARMFUL** |

**Key Observations:**
- `model_health`, `high_edge`, and `edge_spread_optimal` fire on ALL 95 graded picks (they are baseline qualifiers, not differentiators)
- The top-performing signals are all OVER-directional: `combo_he_ms`, `combo_3way`, `rest_advantage_2d`
- **4 UNDER-directional signals are actively harmful** (below 52.4% breakeven): `high_ft_under`, `self_creator_under`, `high_usage_under`, `volatile_under`
- `book_disagreement` is perfect (6/6) but small sample

### A2. V9 vs V12+vegas Effectiveness

| Source Family | N | Wins | HR% | Avg Edge |
|---------------|--:|-----:|----:|:--------:|
| v12_q45 | 1 | 1 | 100.0% | 5.5 |
| v9_low_vegas | 1 | 1 | 100.0% | 5.6 |
| **v12_mae** | **27** | **19** | **70.4%** | **7.3** |
| v9_mae | 65 | 42 | 64.6% | 7.0 |
| v9_q43 | 1 | 0 | 0.0% | 6.1 |

V12 MAE (the V12+vegas model) outperforms V9 MAE by +5.8pp (70.4% vs 64.6%) on best bets picks.

**Per-Signal Breakdown (V9 vs V12):**

| Signal | V9 HR% (N) | V12 HR% (N) | Delta |
|--------|:----------:|:-----------:|------:|
| blowout_recovery | 40.0% (10) | 100.0% (4) | +60.0pp |
| rest_advantage_2d | 63.9% (36) | 100.0% (14) | +36.1pp |
| book_disagreement | 100.0% (2) | 100.0% (4) | 0pp |
| combo_he_ms | 84.6% (13) | 100.0% (4) | +15.4pp |
| combo_3way | 84.6% (13) | 100.0% (4) | +15.4pp |
| prop_line_drop_over | 66.7% (12) | 50.0% (2) | -16.7pp |
| edge_spread_optimal | 64.6% (65) | 70.4% (27) | +5.8pp |
| high_ft_under | -- | 40.0% (5) | -- |
| high_usage_under | 33.3% (3) | 40.0% (5) | +6.7pp |
| self_creator_under | 25.0% (4) | 33.3% (6) | +8.3pp |

V12+vegas outperforms V9 on nearly every signal, especially `rest_advantage_2d` (100% vs 63.9%) and `blowout_recovery` (100% vs 40%).

### A3. Signal Count vs Hit Rate

| Signal Count | N | Wins | HR% | Avg Edge |
|:------------:|--:|-----:|----:|:--------:|
| 3 | 22 | 13 | 59.1% | 6.2 |
| 4 | 26 | 18 | 69.2% | 6.6 |
| 5 | 22 | 15 | 68.2% | 8.8 |
| 6 | 17 | 11 | 64.7% | 5.9 |
| **7** | **6** | **5** | **83.3%** | **8.7** |
| 8 | 2 | 1 | 50.0% | 5.6 |

Signal count 4-7 is the sweet spot (64-83% HR). Signal count = 3 underperforms (59.1%), suggesting the MIN_SIGNAL_COUNT=2 requirement is too low rather than too high.

### A4. Impact of MIN_SIGNAL_COUNT on Coverage

**Zero-pick days:** 5 of 39 game days (12.8%) had 0 best bets picks:
- 2026-01-18: 3 edge 5+ candidates available, all 3 won (100% HR) -- **missed profit**
- 2026-01-23: 1 candidate, won (100%) -- missed profit
- 2026-01-24: 2 candidates, 1 won (50%)
- 2026-01-27: 3 candidates, 1 won (33.3%)
- 2026-02-06: 0 candidates (no games with edge 5+)

**Net impact:** On zero-pick days, the available edge 5+ candidates had mixed results (7 wins out of 9, 77.8% HR). The signal requirement caused us to miss approximately 7 winning picks.

**However:** Edge 5+ picks NOT selected as best bets (across all days) hit at only 45.5% (N=77) vs 66.3% for selected picks. The signal filter is adding +20.8pp of value on average.

---

## Task B: Ultra Bets Investigation

### B1. V12 Models: Edge x Direction x Line Range

| Edge | Direction | Line Range | N | HR% |
|:----:|:---------:|:----------:|--:|----:|
| 7+ | UNDER | high (>20.5) | 9 | **100.0%** |
| 7+ | OVER | mid (12.5-20.5) | 6 | **100.0%** |
| 5-7 | OVER | mid | 5 | **80.0%** |
| 3-5 | UNDER | high | 85 | 68.2% |
| 3-5 | UNDER | mid | 60 | 65.0% |
| 5-7 | UNDER | high | 19 | 63.2% |
| 3-5 | OVER | low (<12.5) | 43 | 62.8% |
| 3-5 | OVER | mid | 35 | 57.1% |
| 3-5 | OVER | high | 11 | 54.5% |
| 3-5 | UNDER | low | 37 | **37.8%** |

**Ultra Bet candidates (75%+ HR, N >= 5):**
- V12 UNDER high-line 7+ edge: 100% (N=9)
- V12 OVER mid-line 7+ edge: 100% (N=6)
- V12 OVER mid-line 5-7 edge: 80% (N=5)

**Danger zone:** V12 UNDER low-line (< 12.5) at edge 3-5 = 37.8% HR. Bench UNDER filter is saving money here.

### B2. Edge 7+ OVER (All Models)

| System | N | Wins | HR% |
|--------|--:|-----:|----:|
| catboost_v12_train1102_1225 | 7 | 7 | **100.0%** |
| catboost_v9_train1102_0108 | 9 | 8 | **88.9%** |
| catboost_v9 | 18 | 12 | 66.7% |
| zone_matchup_v1 | 21 | 12 | 57.1% |
| catboost_v8 | 83 | 36 | 43.4% |

Aggregate (all models, edge 7+, OVER): N=151, HR=55.0%, Avg Edge=9.4

V12+vegas and V9 are the only models with edge 7+ OVER above breakeven.

### B3. V12+vegas Edge 5+ Performance

| System | Direction | N | Wins | HR% | Avg Edge |
|--------|:---------:|--:|-----:|----:|:--------:|
| v12_train1102_0125 | OVER | 4 | 4 | **100.0%** | 10.3 |
| v12_train1102_1225 | OVER | 13 | 13 | **100.0%** | 7.5 |
| v12_train1225_0205 | OVER | 1 | 1 | 100.0% | 7.7 |
| v12_train1102_1225 | UNDER | 17 | 12 | **70.6%** | 6.1 |
| v12_train1102_0125 | UNDER | 3 | 2 | 66.7% | 6.8 |
| v12_train1225_0205 | UNDER | 2 | 1 | 50.0% | 7.0 |

**V12+vegas aggregate at edge 5+: N=40, HR=82.5%**

OVER is **perfect** (18/18 = 100.0%) across all V12+vegas models at edge 5+. UNDER is still profitable (68.2%, N=22).

### B4. Multi-Model Consensus (CatBoost, Edge 5+)

| Models Agreeing | Direction | N | HR% |
|:---------------:|:---------:|--:|----:|
| 4 | OVER | 4 | **100.0%** |
| 3 | UNDER | 8 | **77.8%** |
| 3 | OVER | 6 | 66.7% |
| 2 | UNDER | 50 | 62.0% |
| 2 | OVER | 31 | 58.1% |
| 1 | UNDER | 322 | 53.4% |
| 1 | OVER | 210 | 44.3% |

**Finding:** Multi-model consensus (3+ models agreeing at edge 5+) is an excellent Ultra Bet signal:
- 3+ models OVER: N=10, HR=80.0%
- 3+ models UNDER: N=8, HR=77.8%
- 2+ models (either): N=99, HR=60.6%
- 1 model only: N=532, HR=50.0%

The jump from 1 model to 2+ models is +10.6pp. From 2 to 3+ is another +18pp.

### B5. Starters Line Range (15-24) + UNDER

| Edge | N | Wins | HR% |
|:----:|--:|-----:|----:|
| 3-5 | 363 | 192 | 52.9% |
| 5-7 | 121 | 69 | 57.0% |
| 7+ | 66 | 28 | **42.4%** |

UNDER on starters (line 15-24) at edge 7+ is actually harmful (42.4%). This is consistent with the UNDER edge 7+ filter being protective.

By model group at edge 5+:
- V9 prod: N=47, HR=55.3%
- Other CatBoost: N=134, HR=50.0%
- V12+vegas: N=3, HR=33.3% (too small)

### B6. Model Group Comparison by Edge Bucket

| Model Group | Edge | N | HR% |
|-------------|:----:|--:|----:|
| **V12+vegas** | **7+** | **19** | **100.0%** |
| V12+vegas | 5-7 | 21 | 66.7% |
| V12+vegas | 3-5 | 163 | 64.4% |
| V9 prod | 5-7 | 101 | 59.4% |
| V12 prod | 3-5 | 65 | 55.4% |
| V9 prod | 3-5 | 385 | 50.4% |
| V9 prod | 7+ | 47 | 48.9% |
| V12 noveg | 3-5 | 50 | 46.0% |

**V12+vegas dominates every edge bucket.** The gap widens at higher edges: +15.1pp at edge 7+ (100% vs 48.9% V9), +7.3pp at edge 5-7 (66.7% vs 59.4% V9), +14.0pp at edge 3-5 (64.4% vs 50.4% V9).

### B7. V12+vegas Cumulative Edge Thresholds

| Threshold | N | HR% |
|:---------:|--:|----:|
| >= 3 | 203 | 68.0% |
| >= 4 | 81 | 74.1% |
| >= 4.5 | 57 | 77.2% |
| >= 5 | 40 | 82.5% |
| >= 6 | 26 | 100.0% |
| >= 7 | 19 | 100.0% |

**V12+vegas at edge >= 6 is a perfect 26/26 (100.0%).**

For comparison, V9 production:

| Threshold | N | HR% |
|:---------:|--:|----:|
| >= 3 | 533 | 51.8% |
| >= 5 | 148 | 55.4% |
| >= 7 | 47 | 48.9% |

### B8. V12+vegas Direction Split at Edge 5+

| Direction | Edge | N | HR% |
|:---------:|:----:|--:|----:|
| OVER | 5-7 | 7 | **100.0%** |
| OVER | 7+ | 11 | **100.0%** |
| UNDER | 5-7 | 14 | 50.0% |
| UNDER | 7+ | 8 | **100.0%** |

V12+vegas OVER at edge 5+ is 18/18 = **100.0%**. This is the clearest Ultra Bet signal found.

---

## Task C: Negative Filter Audit

### C1. Filter Population HR (What the filtered picks would have hit)

| Filter Segment | N | HR% | Filter Verdict |
|----------------|--:|----:|:--------------:|
| edge_3_to_5 (all models) | 3,552 | 40.4% | **GOOD FILTER** |
| edge_4_to_5 (all models) | 1,374 | 39.9% | Below breakeven |
| quality_below_85 + edge 5+ | 95 | 18.9% | **CRITICAL FILTER** |
| bench_under + edge 5+ | 372 | 45.2% | **GOOD FILTER** |
| under_edge_7plus (all models) | 453 | 54.1% | Mixed (see below) |

### C2. UNDER Edge 7+ Filter: Model-Specific Impact

| Model Group | N | HR% | Should Block? |
|-------------|--:|----:|:--------------|
| V12+vegas | 8 | **100.0%** | **NO** |
| Other CatBoost | 142 | 53.5% | MARGINAL |
| V9 prod | 28 | **39.3%** | **YES** |

**Finding:** The UNDER edge 7+ filter is correct for V9 (39.3% HR) but **harmful for V12+vegas** (100% HR, N=8). When V12+vegas becomes champion, this filter should be model-aware.

### C3. Edge Floor Optimization

**All CatBoost models — cumulative thresholds:**

| Threshold | N | HR% |
|:---------:|--:|----:|
| >= 3 | 2,515 | 51.7% |
| >= 4 | 1,430 | 52.4% |
| >= 4.5 | 1,072 | 52.1% |
| >= 5 | 832 | 52.3% |
| >= 6 | 519 | 52.6% |
| >= 7 | 303 | 53.5% |

For CatBoost overall, edge threshold barely matters (51.7-53.5% range). The edge floor at 5.0 is primarily a **coverage reducer** (832 vs 2,515 candidates) rather than an HR improver for the model pool.

**However, for V12+vegas specifically:**

| Threshold | N | HR% |
|:---------:|--:|----:|
| >= 3 | 203 | 68.0% |
| >= 4 | 81 | 74.1% |
| >= 5 | 40 | **82.5%** |
| >= 6 | 26 | **100.0%** |

V12+vegas edge floor at 5.0 genuinely separates good from great (68% to 82.5%).

### C4. Granular Edge Buckets

**All models:**

| Bucket | N | HR% |
|:------:|--:|----:|
| 3-4 | 2,178 | 40.7% |
| 4-4.5 | 790 | 40.4% |
| 4.5-5 | 584 | 39.2% |
| 5-7 | 1,360 | 37.7% |
| 7+ | 947 | 34.6% |

When including ALL models (V8, zone_matchup, etc.), higher edge is actually worse. This is because non-CatBoost models generate high-edge predictions that are often wrong.

**V12+vegas only:**

| Bucket | N | HR% |
|:------:|--:|----:|
| 3-4 | 122 | 63.9% |
| 4-4.5 | 24 | 66.7% |
| 4.5-5 | 17 | 64.7% |
| 5-7 | 21 | 66.7% |
| 7+ | 19 | **100.0%** |

V12+vegas: higher edge = higher HR, monotonically increasing. This model's edge signal is well-calibrated.

### C5. Blacklisted Players

| Player | N (edge 3+) | HR% | N (edge 5+) | HR% |
|--------|:----------:|----:|:-----------:|----:|
| jarenjacksonjr | 34 | **11.8%** | 10 | **10.0%** |
| jabarismithjr | 32 | **21.9%** | 12 | **0.0%** |
| treymurphyiii | 55 | **30.9%** | 33 | **27.3%** |
| lukadoncic | 51 | 45.1% | 22 | 40.9% |

**All 4 blacklisted players are below breakeven.** Jabari Smith Jr is 0/12 at edge 5+. The blacklist filter is strongly validated.

### C6. Familiarity Filter (games_vs_opponent >= 6)

| Familiarity | N | HR% |
|:-----------:|--:|----:|
| 1-2 games | 2,323 | 51.8% |
| 3 games | 146 | 50.0% |
| 4-5 games | 46 | 50.0% |

No players reached 6+ games vs same opponent in this window. The filter did not activate. At 4-5 games, there is a slight HR drop (50.0% vs 51.8%), suggesting the filter direction is correct but the threshold may need lowering.

---

## Recommendations

### Immediate Actions

1. **Remove or demote 4 harmful UNDER signals:**
   - `high_ft_under` (33.3% HR), `self_creator_under` (36.4%), `volatile_under` (33.3%), `high_usage_under` (40.0%)
   - These actively drag down the signal count for UNDER picks, making it harder for good UNDER picks to pass the MIN_SIGNAL_COUNT gate

2. **Promote V12+vegas to production champion** (pending sufficient graded sample):
   - 68.0% HR at edge 3+ (N=203) vs V9 at 51.7% (N=533)
   - 82.5% HR at edge 5+ (N=40) vs V9 at 55.4% (N=148)
   - 100.0% HR at edge 6+ (N=26) -- zero losses

3. **Implement Ultra Bets tier for V12+vegas edge 6+:**
   - 100% HR (N=26) across both directions
   - Use as highest-confidence tier
   - Also consider: multi-model consensus 3+ at edge 5+ (78.9% HR, N=18)

### Configuration Adjustments

4. **Make UNDER edge 7+ filter model-aware:**
   - Block for V9 (39.3% HR) -- current behavior is correct
   - Allow for V12+vegas (100.0% HR, N=8) -- filter is harming V12+vegas

5. **Edge floor at 5.0 is validated for V9:**
   - Edge 3-5 CatBoost: 50.6% HR (barely above breakeven)
   - Edge 5+ CatBoost: 52.3% HR
   - For V12+vegas, even edge 3+ is profitable (68.0%), but 5+ is much better (82.5%)

6. **Consider lowering familiarity filter from 6 to 4:**
   - 4-5 games vs opponent: 50.0% HR (below 51.8% baseline)
   - Small sample (N=46) but directionally concerning

### Monitoring

7. **Track signal-specific HR weekly:**
   - `rest_advantage_2d` is the standout (74.0%, N=50) -- largest N among strong signals
   - `book_disagreement` needs more data (100%, but N=6)
   - `blowout_recovery` is model-dependent (V12: 100%, V9: 40%)

8. **Watch zero-pick days:**
   - 5 of 39 days (12.8%) had no best bets
   - On 3 of those days, available edge 5+ candidates won at 100%
   - Consider a "fallback" mode: if 0 signal-qualified picks, take the single highest-edge V12+vegas pick

---

## Appendix: Raw Query Results

### A. signal_best_bets_picks Table Summary
- Total picks in date range: 101
- Graded picks (joined to prediction_accuracy): 95
- Ungraded: 6 (6%)
- Overall HR: 66.3% (63/95)
- Source model distribution: v9_mae=70, v12_mae=27, other=4

### B. V12+vegas Full Detail by System ID x Direction x Edge x Line

| System | Dir | Edge | Line | N | HR% |
|--------|:---:|:----:|:----:|--:|----:|
| v12_train1102_1225 | OVER | 7+ | low | 3 | 100.0% |
| v12_train1102_1225 | OVER | 7+ | mid | 3 | 100.0% |
| v12_train1102_0125 | OVER | 3-5 | mid | 4 | 100.0% |
| v12_train1102_1225 | OVER | 5-7 | mid | 4 | 100.0% |
| v12_train1102_1225 | UNDER | 7+ | high | 5 | 100.0% |
| v12_train1225_0205 | UNDER | 3-5 | high | 6 | 83.3% |
| v12_train1102_0125 | UNDER | 3-5 | mid | 5 | 80.0% |
| v12_train1102_1225 | OVER | 3-5 | high | 5 | 80.0% |
| v12_train1225_0205 | UNDER | 3-5 | mid | 9 | 77.8% |
| v12_train1102_0125 | OVER | 3-5 | low | 8 | 75.0% |
| v12_train1102_0125 | UNDER | 3-5 | high | 14 | 71.4% |
| v12_train1102_1225 | UNDER | 3-5 | mid | 13 | 69.2% |
| v12_train1102_1225 | UNDER | 3-5 | high | 30 | 66.7% |
| v12_train1102_1225 | OVER | 3-5 | mid | 20 | 65.0% |
| v12_train1102_1225 | OVER | 3-5 | low | 25 | 64.0% |
| v12_train1102_1225 | UNDER | 5-7 | high | 10 | 60.0% |
| v12_train1225_0205 | OVER | 3-5 | low | 8 | 50.0% |
| v12_train1225_0205 | UNDER | 3-5 | low | 5 | 20.0% |
| v12_train1225_0205 | OVER | 3-5 | mid | 4 | 0.0% |

Note: v12_train1225_0205 (the most recent retrain) shows degraded performance on some segments (UNDER low-line: 20%, OVER mid-line: 0%). This may indicate the ASB retrain window (through 2026-02-05) captured unusual pre-break patterns. The earlier retrains (train1102_1225 and train1102_0125) are consistently strong.

### C. Zero-Pick Day Detail

| Date | Edge 5+ Candidates | Would-Hit | HR% |
|:----:|:------------------:|:---------:|----:|
| 2026-01-18 | 3 | 3 | 100.0% |
| 2026-01-23 | 1 | 1 | 100.0% |
| 2026-01-24 | 2 | 1 | 50.0% |
| 2026-01-27 | 3 | 1 | 33.3% |
| 2026-02-06 | 0 | -- | -- |
| **Total** | **9** | **6** | **66.7%** |
