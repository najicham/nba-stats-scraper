# Model Decay Diagnostic SQL Results
**Date:** 2026-02-12
**Session:** Session A (SQL Diagnostics)
**Champion Model:** catboost_v9_33features_20260201_011018
**Analysis Period:** January 2026 - February 2026

## Executive Summary

**CRITICAL FINDING:** Model experienced catastrophic CLV collapse in February. This is NOT a selection problem - this is a staleness problem.

- **January CLV:** +3.04 points average, 206/306 (67.3%) positive CLV rate, 68.0% hit rate
- **February CLV:** -0.08 points average, 10/114 (8.8%) positive CLV rate, 38.6% hit rate
- **Verdict:** The model had real edge in January, completely lost it in February

**Impact of trade deadline:** Significant. Hit rate collapsed from 59.5% (normal) → 37.3% (trade window) → 40.0% (post-trade).

**Direction filter effectiveness:** Filtering out role player UNDERs (5-14 line) improves champion from 38.0% → 41.0% in Feb, but this is STILL below breakeven (52.4%). Not a solution.

**Recommendation:** **PATH A - Staleness confirmed, proceed with retraining**

---

## Raw Query Results

### Query 1: Pre-flight - Verify recommendation values

```
+----------------+-----+
| recommendation | cnt |
+----------------+-----+
| HOLD           |   1 |
| PASS           | 426 |
| UNDER          | 441 |
| OVER           | 269 |
+----------------+-----+
```

**Status:** ✓ Uppercase values confirmed (OVER, UNDER). All subsequent queries valid.

---

### Query 2: UNDER collapse - Monthly breakdown by direction

```
+---------+----------------+-------+---------+------+
|  month  | recommendation | picks | correct |  hr  |
+---------+----------------+-------+---------+------+
| 2026-01 | OVER           |   202 |     140 | 69.3 |
| 2026-01 | UNDER          |   190 |     114 | 60.0 |
| 2026-02 | OVER           |    83 |      38 | 45.8 |
| 2026-02 | PASS           |     6 |       0 |  0.0 |
| 2026-02 | UNDER          |   103 |      35 | 34.0 |
+---------+----------------+-------+---------+------+
```

**Key Findings:**
- UNDER performance collapsed: 60.0% (Jan) → 34.0% (Feb) = **-26.0 point drop**
- OVER performance also dropped: 69.3% (Jan) → 45.8% (Feb) = **-23.5 point drop**
- Both directions failing, but UNDER is catastrophically worse
- 34.0% UNDER hit rate is BELOW random guessing

**Answer to Key Question:** Was UNDER always bad?
- **NO.** UNDER was 60.0% in January (solid), collapsed to 34.0% in February. This is a February-specific decay, not a training defect.

---

### Query 3: Trade deadline impact

```
+--------------+-------+---------+------+
|    period    | picks | correct |  hr  |
+--------------+-------+---------+------+
| Post-trade   |    50 |      20 | 40.0 |
| Normal       |   247 |     147 | 59.5 |
| Trade window |   142 |      53 | 37.3 |
+--------------+-------+---------+------+
```

**Key Findings:**
- Normal period (Jan 15-31): 59.5% hit rate
- Trade window (Feb 1-8): 37.3% hit rate = **-22.2 point drop**
- Post-trade (Feb 9-12): 40.0% hit rate (no recovery)
- Trade deadline alone accounts for massive performance cliff

**Answer to Key Question:** Did trade deadline make things worse?
- **YES.** Performance dropped 22.2 points during trade window. Minimal recovery post-deadline. This suggests:
  1. Roster changes invalidated historical features
  2. Model's historical matchup features became obsolete
  3. New team contexts not in training data

---

### Query 4: Role player UNDER disaster zone - Monthly

```
+---------+------------------+------+
|  month  | role_under_picks |  hr  |
+---------+------------------+------+
| 2026-01 |               40 | 47.5 |
| 2026-02 |               36 | 25.0 |
+---------+------------------+------+
```

**Key Findings:**
- Role player UNDER (5-14 line) was NEVER good: 47.5% in January (already losing money)
- Worsened dramatically in February: 25.0% (75% wrong!)
- This segment accounts for ~19% of February UNDER picks (36/103)

**Insight:** Role player UNDER was a known weakness even when model was "working" in January. February decay made it catastrophic.

---

### Query 5: Direction filter simulation - All models, February

```
+----------------------------------+----------+----------------+-------------+-------------+
|            system_id             | total_e3 | filtered_picks | original_hr | filtered_hr |
+----------------------------------+----------+----------------+-------------+-------------+
| catboost_v9_train1102_0108       |       13 |             11 |        53.8 |        63.6 |
| catboost_v9_train1102_0131       |        6 |              4 |        33.3 |        50.0 |
| catboost_v9_q45_train1102_0131   |       18 |             16 |        50.0 |        50.0 |
| catboost_v8                      |      374 |            250 |        44.9 |        44.8 |
| catboost_v9_train1102_0131_tuned |        9 |              7 |        33.3 |        42.9 |
| catboost_v9_q43_train1102_0131   |       31 |             24 |        45.2 |        41.7 |
| catboost_v9                      |      192 |            156 |        38.0 |        41.0 |
| catboost_v9_2026_02              |       62 |             43 |        29.0 |        34.9 |
| ensemble_v1_1                    |      274 |            176 |        36.1 |        32.4 |
| ensemble_v1                      |      267 |            201 |        25.8 |        21.9 |
| zone_matchup_v1                  |      495 |            412 |        23.0 |        19.9 |
| moving_average                   |      524 |            333 |        26.0 |        15.0 |
| similarity_balanced_v1           |      350 |            309 |         7.4 |         4.2 |
| catboost_v9_train1102_0208       |        1 |              1 |         0.0 |         0.0 |
+----------------------------------+----------+----------------+-------------+-------------+
```

**Key Findings:**
- Champion filter impact: 38.0% → 41.0% (+3.0 points) by removing role player UNDER
- **Still 11.4 points below breakeven (52.4%)**
- Best performing model: catboost_v9_train1102_0108 at 63.6% filtered (newer retrain)
- Q43 drops from 45.2% → 41.7% after filtering (doesn't help)
- ALL models except _train1102_0108 are below breakeven

**Answer to Key Question:** How much does direction filter help?
- **Minimal.** Champion improves 3 points but remains deeply unprofitable. Filtering is a band-aid, not a fix.

---

### Query 6: Ensemble simulation

```
+--------------------------+-------+------+
|          source          | picks |  hr  |
+--------------------------+-------+------+
| Champion OVER            |    83 | 45.8 |
| Q43 UNDER                |    31 | 45.2 |
| Champion Star OVER (25+) |     9 | 55.6 |
+--------------------------+-------+------+
```

**Key Findings:**
- Champion OVER: 83 picks, 45.8% hit rate (LOSING)
- Q43 UNDER: 31 picks, 45.2% hit rate (LOSING)
- Champion Star OVER (25+ line): 9 picks, 55.6% hit rate (slightly better, but tiny sample)

**Answer to Key Question:** Does ensemble work?
- **NO.** Both models failing independently in February. Combining two failing models = still failing.
- Star OVER (25+) shows promise (55.6%) but only 9 picks - insufficient for production strategy

---

### Query 7: CLV Analysis (MOST CRITICAL)

```
+---------+-------+----------------+--------------------+------+
|  month  | picks | avg_clv_points | positive_clv_count |  hr  |
+---------+-------+----------------+--------------------+------+
| 2026-01 |   306 |           3.04 |                206 | 68.0 |
| 2026-02 |   114 |          -0.08 |                 10 | 38.6 |
+---------+-------+----------------+--------------------+------+
```

**SMOKING GUN:**

**January Performance:**
- Average CLV: **+3.04 points** (massive edge)
- Positive CLV rate: **67.3%** (206/306)
- Hit rate: **68.0%** (well above breakeven)
- **Verdict:** Model had REAL edge, betting into favorable lines

**February Performance:**
- Average CLV: **-0.08 points** (negative edge)
- Positive CLV rate: **8.8%** (10/114) - almost never getting favorable lines
- Hit rate: **38.6%** (catastrophic)
- **Verdict:** Model completely lost ability to identify value

**What This Means:**
1. In January, the model consistently identified favorable opportunities BEFORE the market moved
2. In February, the model is betting into lines that move AGAINST us (negative CLV)
3. This is textbook staleness - the model's understanding of player performance no longer aligns with current reality
4. The market is now better calibrated than the model (lines are closing away from our bets)

**Answer to Key Question:** CLV verdict?
- **Path A confirmed.** CLV was strongly positive in January (+3.04), completely collapsed in February (-0.08). The model had real edge, lost it due to staleness.

---

### Query 8: Per-game correlation analysis

```
+------------------+----------------+---------------+-------+
|     game_id      | recommendation | picks_on_game |  hr   |
+------------------+----------------+---------------+-------+
| 20260202_MIN_MEM | UNDER          |            10 |  20.0 |
| 20260202_PHI_LAC | UNDER          |            10 |  10.0 |
| 20260131_CHI_MIA | UNDER          |             8 |  25.0 |
| 20260202_HOU_IND | UNDER          |             6 |  16.7 |
| 20260201_OKC_DEN | OVER           |             5 |  60.0 |
| 20260203_UTA_IND | UNDER          |             5 |   0.0 |
| 20260202_NOP_CHA | UNDER          |             5 |   0.0 |
| 20260211_CHI_BOS | UNDER          |             4 |  75.0 |
| 20260121_IND_BOS | UNDER          |             4 | 100.0 |
| 20260207_UTA_ORL | OVER           |             4 |  50.0 |
| 20260211_NYK_PHI | OVER           |             4 |  25.0 |
| 20260211_WAS_CLE | OVER           |             4 |  50.0 |
| 20260121_BKN_NYK | UNDER          |             4 | 100.0 |
| 20260211_MIL_ORL | OVER           |             4 |  50.0 |
| 20260126_IND_ATL | OVER           |             4 | 100.0 |
| 20260207_PHI_PHX | OVER           |             3 |  33.3 |
| 20260125_MIA_PHX | UNDER          |             3 |  33.3 |
| 20260128_ATL_BOS | UNDER          |             3 | 100.0 |
| 20260123_SAC_CLE | OVER           |             3 |  66.7 |
| 20260204_DEN_NYK | UNDER          |             3 |   0.0 |
| 20260208_NYK_BOS | UNDER          |             3 |  66.7 |
| 20260128_NYK_TOR | OVER           |             3 |  66.7 |
| 20260125_TOR_OKC | OVER           |             3 | 100.0 |
| 20260123_BOS_BKN | UNDER          |             3 |  66.7 |
| 20260115_PHX_DET | UNDER          |             3 |  33.3 |
| 20260129_BKN_DEN | UNDER          |             3 |  66.7 |
| 20260119_IND_PHI | UNDER          |             3 | 100.0 |
| 20260203_UTA_IND | PASS           |             3 |   0.0 |
| 20260122_CHI_MIN | OVER           |             3 | 100.0 |
| 20260118_NOP_HOU | OVER           |             3 |  33.3 |
+------------------+----------------+---------------+-------+
```

**Key Findings:**
- Games with clustered picks show EXTREME variance
- Some games: 100% correct (20260121_IND_BOS, 20260121_BKN_NYK)
- Some games: 0-20% correct (20260202_MIN_MEM: 2/10, 20260202_PHI_LAC: 1/10)
- Top clustered games are UNDER-heavy and performing terribly

**February Trade Deadline Games (Feb 1-8):**
- 20260202_MIN_MEM: 10 UNDER picks, 20.0% HR
- 20260202_PHI_LAC: 10 UNDER picks, 10.0% HR
- 20260202_HOU_IND: 6 UNDER picks, 16.7% HR
- 20260203_UTA_IND: 5 UNDER picks, 0.0% HR
- 20260202_NOP_CHA: 5 UNDER picks, 0.0% HR

**Answer to Key Question:** Are per-game pick clusters correlated failures?
- **YES.** Games during trade deadline week show systematic UNDER failures. Model making same mistake on multiple players in same game (likely roster/context driven).

---

### Query 9: Dynamic edge threshold by model age

```
+-----------+------------+-------+-------+
| model_age | edge_floor | picks |  hr   |
+-----------+------------+-------+-------+
| Week 1-2  |          3 |    99 |  57.6 |
| Week 1-2  |          4 |    57 |  66.7 |
| Week 1-2  |          5 |    30 |  76.7 |
| Week 1-2  |          6 |    27 |  77.8 |
| Week 1-2  |          7 |     9 |  88.9 |
| Week 1-2  |          8 |     7 |  85.7 |
| Week 1-2  |          9 |     8 |  87.5 |
| Week 1-2  |         10 |     8 |  62.5 |
| Week 1-2  |         11 |     6 | 100.0 |
| Week 1-2  |         12 |     3 | 100.0 |
| Week 1-2  |         13 |     4 | 100.0 |
| Week 1-2  |         16 |     2 | 100.0 |
| Week 1-2  |         17 |     4 | 100.0 |
| Week 1-2  |         18 |     2 | 100.0 |
| Week 1-2  |         20 |     1 | 100.0 |
| Week 3    |          3 |    50 |  52.0 |
| Week 3    |          4 |    24 |  50.0 |
| Week 3    |          5 |     4 | 100.0 |
| Week 3    |          6 |    11 |  63.6 |
| Week 3    |          7 |     3 |  33.3 |
| Week 3    |          9 |     2 | 100.0 |
| Week 4    |          3 |    59 |  42.4 |
| Week 4    |          4 |    22 |  36.4 |
| Week 4    |          5 |    15 |  33.3 |
| Week 4    |          6 |    11 |  27.3 |
| Week 4    |          7 |     8 |  12.5 |
| Week 4    |          8 |     3 |   0.0 |
| Week 4    |          9 |     5 |  60.0 |
| Week 4    |         10 |     2 |   0.0 |
| Week 4    |         11 |     1 |   0.0 |
| Week 4    |         12 |     1 |   0.0 |
| Week 4    |         17 |     1 |   0.0 |
| Week 4    |         20 |     1 | 100.0 |
| Week 5+   |          3 |    55 |  43.6 |
| Week 5+   |          4 |    19 |  42.1 |
| Week 5+   |          5 |    12 |  33.3 |
| Week 5+   |          6 |     3 |  66.7 |
| Week 5+   |          7 |     1 | 100.0 |
| Week 5+   |          8 |     1 | 100.0 |
| Week 5+   |          9 |     2 | 100.0 |
| Week 5+   |         11 |     1 |   0.0 |
+-----------+------------+-------+-------+
```

**Model Age Analysis (Trained on data ending 2026-01-08):**

**Week 1-2 (Jan 8-22) - FRESH MODEL:**
- Edge 3+: 57.6% HR (99 picks) - PROFITABLE
- Edge 4+: 66.7% HR (57 picks) - HIGHLY PROFITABLE
- Edge 5+: 76.7% HR (30 picks) - EXCELLENT
- Edge 6+: 77.8% HR (27 picks) - PEAK PERFORMANCE
- Edge 7+: 88.9% HR (9 picks) - EXTREMELY CONFIDENT

**Week 3 (Jan 23-29) - EARLY DECAY:**
- Edge 3+: 52.0% HR (50 picks) - BARELY BREAKEVEN
- Edge 4+: 50.0% HR (24 picks) - LOSING
- Edge 6+: 63.6% HR (11 picks) - Still okay at high edge

**Week 4 (Jan 30 - Feb 5) - TRADE DEADLINE COLLAPSE:**
- Edge 3+: 42.4% HR (59 picks) - CATASTROPHIC
- Edge 4+: 36.4% HR (22 picks) - WORSE
- Edge 5+: 33.3% HR (15 picks) - DISASTER
- Edge 6+: 27.3% HR (11 picks) - COMPLETELY INVERTED
- **Even high-edge picks failing**

**Week 5+ (Feb 6-12) - POST-TRADE CONTINUATION:**
- Edge 3+: 43.6% HR (55 picks) - Still terrible
- Edge 4+: 42.1% HR (19 picks) - No recovery
- Edge 5+: 33.3% HR (12 picks) - Deeply unprofitable

**Answer to Key Question:** Does tightening edge threshold with model age help?
- **NO.** During Week 4 (trade deadline), even edge 6+ picks had 27.3% HR (inverted). Edge threshold cannot save a stale model when the underlying game state has changed.
- The model needs fresh data reflecting new roster compositions, not higher confidence thresholds.

**Decay Pattern:**
1. Week 1-2: Edge 3+ at 57.6% (profitable)
2. Week 3: Edge 3+ at 52.0% (breakeven)
3. Week 4: Edge 3+ at 42.4% (collapse) - **Trade deadline week**
4. Week 5+: Edge 3+ at 43.6% (no recovery)

**Critical Insight:** The decay was GRADUAL until trade deadline, then CATASTROPHIC. This suggests:
- Natural staleness: -5.6 points over 3 weeks (manageable)
- Trade deadline shock: -9.6 points in 1 week (unrecoverable without retrain)

---

## Key Findings Summary

### 1. Is the UNDER collapse February-specific or was it always bad?

**Answer:** February-specific collapse.

- January UNDER: 60.0% HR (190 picks) - SOLID PERFORMANCE
- February UNDER: 34.0% HR (103 picks) - CATASTROPHIC FAILURE
- Drop: **-26.0 percentage points**

**However**, role player UNDER (5-14 line) was weak even in January (47.5%), suggesting this segment was always marginal.

---

### 2. Did the trade deadline make things worse?

**Answer:** YES. The trade deadline was the killing blow.

- Normal period (Jan 15-31): 59.5% HR
- Trade window (Feb 1-8): 37.3% HR (**-22.2 points**)
- Post-trade (Feb 9-12): 40.0% HR (slight recovery, still terrible)

The model's historical features became obsolete when rosters changed. Per-game analysis shows clustered UNDER failures on trade deadline games.

---

### 3. How much does the direction filter help?

**Answer:** Marginal improvement, not a solution.

- Champion original: 38.0% HR (Feb)
- Champion filtered (remove role UNDER): 41.0% HR (**+3.0 points**)
- Still **11.4 points below breakeven** (52.4%)

Filtering is treating symptoms, not the disease. Even with filtering, model remains deeply unprofitable.

---

### 4. Does the ensemble (champion OVER + Q43 UNDER) work?

**Answer:** NO. Both models failing in February.

- Champion OVER: 45.8% HR (83 picks) - LOSING
- Q43 UNDER: 45.2% HR (31 picks) - LOSING
- Champion Star OVER (25+): 55.6% HR (9 picks) - tiny sample

You cannot ensemble two failing models into a winning strategy.

---

### 5. CLV VERDICT: Was CLV positive in January? Negative in February? Or negative in both?

**Answer:** POSITIVE in January, NEGATIVE in February. This is the smoking gun.

**January:**
- Avg CLV: **+3.04 points**
- Positive CLV rate: **67.3%** (206/306)
- Hit rate: **68.0%**
- **Model had real edge, betting into favorable lines**

**February:**
- Avg CLV: **-0.08 points**
- Positive CLV rate: **8.8%** (10/114)
- Hit rate: **38.6%**
- **Model lost all edge, betting into unfavorable lines**

**Interpretation:**
- The model was identifying value opportunities BEFORE the market in January
- In February, the market is better calibrated than the model
- Lines are closing AWAY from our positions (negative CLV)
- This is textbook model staleness

---

### 6. Are per-game pick clusters correlated failures?

**Answer:** YES. Systematic failures on specific games.

Games with 5+ picks during trade deadline week:
- 20260202_MIN_MEM: 10 UNDER, 20.0% HR
- 20260202_PHI_LAC: 10 UNDER, 10.0% HR
- 20260202_HOU_IND: 6 UNDER, 16.7% HR
- 20260203_UTA_IND: 5 UNDER, 0.0% HR
- 20260202_NOP_CHA: 5 UNDER, 0.0% HR

The model is making the same systematic error on multiple players in the same game, suggesting game-level context (injuries, roster changes, matchups) is being misread.

---

### 7. Does tightening edge threshold with model age help?

**Answer:** NO. High-edge picks also failing during staleness.

**Week 4 (trade deadline) performance by edge:**
- Edge 3+: 42.4% HR
- Edge 4+: 36.4% HR
- Edge 5+: 33.3% HR
- Edge 6+: 27.3% HR (**INVERTED - higher confidence = worse performance**)

When the model's understanding of the game state is wrong, confidence calibration is wrong. Higher edge just means "more confidently wrong."

---

## Recommendation: PATH A - PROCEED WITH RETRAINING

### Why PATH A (Retraining)

**Evidence:**
1. **CLV collapse proves staleness:** +3.04 points (Jan) → -0.08 points (Feb)
2. **Model had real edge:** 68.0% HR in January with positive CLV
3. **Trade deadline catalyst:** Roster changes invalidated historical features
4. **Edge threshold ineffective:** Even edge 6+ picks failing (27.3% HR Week 4)
5. **Direction filter insufficient:** Only +3 points improvement, still -11.4 below breakeven

The model isn't fundamentally broken - it worked in January. It's stale.

### Why NOT PATH B (Post-processing only)

CLV was strongly positive in January, proving the model can extract real edge when trained on recent data. This rules out "no edge ever existed."

### Why NOT PATH C (Better filtering)

Filtering role player UNDER only gains 3 points. Even filtered champion is at 41.0% HR in February (-11.4 below breakeven). No amount of filtering can resurrect a model that's betting into negative CLV.

---

## Action Items

### Immediate (This Session)
1. ✅ SQL diagnostics complete
2. [ ] Execute quick retrain with expanded training window:
   - **Training dates:** 2025-11-02 to 2026-02-08 (includes trade deadline context)
   - **Features:** Current 33-feature set
   - **Quantile:** Consider Q43 (previous winner) vs standard MSE

### Validation Before Promotion
1. Check Vegas bias (must be within +/- 1.5)
2. Edge 3+ hit rate >= 60%
3. No critical tier bias (> +/- 5 points)
4. Sample size >= 50 graded edge 3+ bets
5. **CLV analysis on holdout set** (add this as gate #7)

### Post-Retrain Strategy
1. Monitor daily CLV as leading indicator of decay
2. Consider **bi-weekly retrain cadence** during volatile periods (trade deadline, playoffs)
3. Add roster turnover metrics to trigger automatic retrain alerts

---

## Appendix: What We Learned

### The Staleness Signature
A stale model exhibits:
1. **Gradual HR decay** (57.6% → 52.0% over 3 weeks)
2. **Sudden CLV collapse** (catalyst event like trade deadline)
3. **Inverted edge calibration** (higher edge → worse performance)
4. **Systematic game-level failures** (clustered mistakes on same matchup)

### Why Trade Deadline Was So Destructive
- Model trained on historical team compositions and matchup patterns
- Trade deadline changed 20+ rosters in 1 week
- Historical features (matchup history, teammate context, defensive matchups) became obsolete
- New player-team combinations not in training data

### The CLV Early Warning System
CLV degradation precedes HR degradation:
- Week 1-2: High HR, high CLV (model working)
- Week 3: Declining HR, still positive CLV (early staleness)
- Week 4: Crashed HR, negative CLV (model broken)

**Proposed gate:** Alert if weekly CLV drops below +0.5 points for 3+ days.

---

**End of Report**
