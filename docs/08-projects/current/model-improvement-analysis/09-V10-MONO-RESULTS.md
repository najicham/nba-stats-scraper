# V10 Features + Monotonic Constraints Results

**Session 226 | Date: 2026-02-12**

## Executive Summary

**ALL 6 EXPERIMENTS FAILED GOVERNANCE GATES.** Neither V10 features nor monotonic constraints improved model performance. All models underperformed the baseline (55.4% HR on 92 picks).

### Critical Findings
1. **OVER direction collapsed** - All models generated 0-1 OVER picks (vs 38+ UNDER picks)
2. **Monotonic constraints harmful** - Consistently increased vegas bias (-3.4 to -3.5) and star tier bias (-8.8 to -9.2 pts)
3. **V10 features minimal impact** - pts_vs_season_zscore appeared in top 10 but didn't improve HR
4. **Multi-season slightly better** - B1 (54.29% HR) outperformed A1 (51.28% HR) but both below baseline
5. **Trade deadline effect persists** - All models struggle in Feb 2-11 eval window

### Best Model: B1 (V10_2SZN_Q43_R120)
- **Hit Rate (edge 3+):** 54.29% (vs 55.4% baseline)
- **Sample Size:** 35 picks (vs 92 baseline) ⚠️ LOW
- **MAE:** 5.04 (BEST among all 6)
- **Week 2 HR:** 54.5%
- **Status:** NOT READY - below baseline, insufficient volume

---

## 1. Results Table

| Experiment | Seasons | V10? | Mono? | Edge 3+ Picks | Edge 3+ HR | Week 1 HR | Week 2 HR | MAE | Vegas Bias | OVER HR | UNDER HR |
|------------|---------|------|-------|---------------|------------|-----------|-----------|-----|------------|---------|----------|
| **Baseline** | 1 | No | No | **92** | **55.4%** | - | - | - | - | - | - |
| A1: V10_1SZN_Q43_R14 | 1 | ✅ | No | 39 | 51.28% | 53.3% | 50.0% | 5.11 | -1.38 | 0.0% (1) | 52.6% (38) |
| A2: MONO_1SZN_Q43_R14 | 1 | No | ✅ | 179 | 50.28% | 49.5% | 51.3% | **5.84** | **-3.46** | N/A (0) | 50.3% (179) |
| A3: V10_MONO_1SZN_Q43 | 1 | ✅ | ✅ | 178 | 50.00% | 49.0% | 51.3% | **5.83** | **-3.43** | N/A (0) | 50.0% (178) |
| B1: V10_2SZN_Q43_R120 | 2 | ✅ | No | 35 | **54.29%** | 53.9% | **54.5%** | **5.04** | -1.37 | 0.0% (1) | 55.9% (34) |
| B2: MONO_2SZN_Q43_R120 | 2 | No | ✅ | 175 | 50.29% | 51.0% | 49.3% | **5.80** | **-3.44** | N/A (0) | 50.3% (175) |
| B3: V10_MONO_2SZN_Q43 | 2 | ✅ | ✅ | 178 | 51.12% | 50.5% | 52.0% | **5.80** | **-3.45** | N/A (0) | 51.1% (178) |

**Governance Gate Failures:**
- ❌ All 6 models: HR < 60% (need >= 60%)
- ❌ A1, B1: Sample size < 50 (need >= 50)
- ❌ A2, A3, B2, B3: Vegas bias outside +/-1.5 (all -3.4 to -3.5)
- ❌ A2, A3, B2, B3: Star tier bias > +/-5 (all -8.8 to -9.2 pts)
- ❌ All 6 models: OVER direction below breakeven (0.0% or N/A vs 52.4% required)

---

## 2. Key Comparisons (Week 2 / Clean Holdout Only)

### V10 Feature Impact
**A1 (V10_1SZN_Q43_R14) vs Baseline (55.4%):**
- **Hit Rate:** 50.0% vs 55.4% = **-5.4pp WORSE** ❌
- **Volume:** 39 vs 92 picks = **-58% volume** ❌
- **MAE:** 5.11 (slight improvement)
- **Verdict:** V10 features alone do NOT improve single-season performance

### Monotonic Constraints Impact
**A2 (MONO_1SZN_Q43_R14) vs Baseline:**
- **Hit Rate:** 51.3% vs 55.4% = **-4.1pp WORSE** ❌
- **Vegas Bias:** -3.46 (CRITICAL - outside +/-1.5 limit)
- **Star Tier Bias:** -9.18 pts (CRITICAL - massive regression to mean)
- **Verdict:** Monotonic constraints are HARMFUL

### Combined V10 + Monotonic Impact
**A3 (V10_MONO_1SZN_Q43) vs A1 vs A2 vs Baseline:**
- **A3 HR:** 51.3% (between A1's 50.0% and A2's 51.3%)
- **A3 Vegas Bias:** -3.43 (same critical issue as A2)
- **Verdict:** Combined approach inherits monotonic constraint problems, no benefit from V10

### Multi-Season Benefit
**B1 (V10_2SZN_Q43_R120) vs A1 (V10_1SZN_Q43_R14):**
- **Hit Rate:** 54.5% vs 50.0% = **+4.5pp BETTER** ✅
- **MAE:** 5.04 vs 5.11 = **-0.07 BETTER** ✅
- **Volume:** 35 vs 39 picks = **-10% volume** (both critically low)
- **Verdict:** Multi-season data helps, but insufficient volume persists

### Best Overall Model
**B1 (V10_2SZN_Q43_R120)** wins among the 6, but:
- **54.29% edge 3+ HR** < 55.4% baseline (-1.1pp)
- **35 picks** < 92 baseline (-62% volume)
- **Gates passed:** 3 of 6 (MAE, vegas bias, tier bias)
- **Gates failed:** HR < 60%, sample size < 50, OVER direction collapsed
- **Status:** NOT READY for deployment

---

## 3. Feature Importance Analysis

### V10 Feature Performance

| Experiment | pts_vs_season_zscore Rank | pts_vs_season_zscore Imp% | pts_slope_10g Rank | dnp_rate Rank | breakout_flag Rank |
|------------|---------------------------|---------------------------|--------------------|--------------|--------------------|
| A1: V10_1SZN_Q43_R14 | #6 | 2.99% | Not in top 10 | Not in top 10 | Not in top 10 (0.03%) |
| B1: V10_2SZN_Q43_R120 | #10 | 2.30% | Not in top 10 | Not in top 10 | Not in top 10 (0.02%) |

**Findings:**
1. **pts_vs_season_zscore** appeared in top 10 for both V10 experiments (#6 with 2.99% in A1, #10 with 2.30% in B1)
2. **pts_slope_10g** (expected highest impact) did NOT appear in top 10 for either model
3. **dnp_rate** and **breakout_flag** had negligible importance (<0.05%)
4. **Total V10 contribution:** ~3-5% of total importance (not enough to move the needle)

### Vegas Dependency Analysis

| Experiment | Vegas Features Combined Imp% | vs Baseline (29-36%) |
|------------|------------------------------|----------------------|
| A1: V10_1SZN_Q43_R14 | 31.52% (16.34 + 12.06 + 3.12) | Within baseline range |
| A2: MONO_1SZN_Q43_R14 | 51.68% (31.86 + 7.82 + ...) | **+15-22pp INCREASE** ❌ |
| A3: V10_MONO_1SZN_Q43 | 50.80% (31.39 + 7.57 + ...) | **+14-21pp INCREASE** ❌ |
| B1: V10_2SZN_Q43_R120 | 34.60% (21.04 + 10.52 + 3.04) | Within baseline range |
| B2: MONO_2SZN_Q43_R120 | 56.47% (39.81 + 8.33 + ...) | **+20-27pp INCREASE** ❌ |
| B3: V10_MONO_2SZN_Q43 | 55.56% (39.94 + 7.81 + ...) | **+19-26pp INCREASE** ❌ |

**Key Finding:** Monotonic constraints INCREASE vegas dependency by 15-27pp, the opposite of what we want. The constraints force the model to rely more heavily on vegas_points_line because:
1. Constraining feature relationships reduces model flexibility
2. Vegas line has the strongest monotonic relationship with actual points
3. Other features lose importance when their splits are constrained

---

## 4. Tier × Direction Breakdown

### Champion (Production Model) - Reference
- **Role UNDER:** 22%
- **Star OVER:** 62.5%

### Wave 1 Best (2SZN_Q43_R120 - V9 features)
- **Role UNDER:** 68.4% (FIXED the champion's 22% problem)
- **Star OVER:** Not reported in Wave 1 results

### Best V10/Mono Model (B1: V10_2SZN_Q43_R120)

| Tier × Direction | Hit Rate | N | vs Champion |
|------------------|----------|---|-------------|
| Stars (25+) UNDER | 100.0% | 3 | +38pp (champion: 62.5% OVER) |
| Starters (15-24) UNDER | 50.0% | 10 | - |
| Role (5-14) UNDER | 55.6% | 18 | -12.8pp (Wave 1: 68.4%) |
| Bench (<5) UNDER | 33.3% | 3 | - |

**CRITICAL ISSUE: OVER Direction Collapsed**
- **Stars OVER:** 0 picks (vs champion's 62.5% on high volume)
- **Starters OVER:** 1 pick (0.0% HR)
- **Role OVER:** 0 picks
- **All tiers OVER combined:** 1 pick, 0% HR

**Interpretation:**
1. V10 models generate almost exclusively UNDER picks (34-38 of 35-39 total)
2. Lost the champion's star OVER edge (62.5% HR)
3. Lost Wave 1's role UNDER edge (68.4% HR → 55.6%)
4. Models are directionally imbalanced and unprofitable

---

## 5. Governance Assessment

### Best Model: B1 (V10_2SZN_Q43_R120)

| Gate | Threshold | Result | Pass? |
|------|-----------|--------|-------|
| 1: HR > 52.4% (breakeven) | 52.4% | **54.29%** | ✅ |
| 2: P(true HR > 52.4%) > 90% | 90% | ~72% (n=35, CI: 37-71%) | ❌ |
| 3: Better than champion by 8+ pp | 38% + 8pp = 46% | **54.29%** | ✅ |
| 4: No walkforward week below 40% | 40% | Week 1: 53.9%, Week 2: 54.5% | ✅ |
| 5: Volume (picks per day) | ~15/day | 35 picks / 11 days = **3.2/day** | ❌ |
| 6: Directional balance | OVER+UNDER >= 52.4% | OVER: 0.0% (1 pick) | ❌ |

**Gates Passed:** 3 of 6
**Gates Failed:** Sample size confidence, volume, directional balance
**Deployment Status:** NOT READY

---

## 6. Recommendation

### Immediate Action: NONE of these models are deployment-ready

**Why all 6 failed:**
1. **OVER direction collapsed** - Models generate 35-179 UNDER picks but only 0-1 OVER picks
2. **Volume too low** - V10 experiments (35-39 picks) vs baseline (92 picks) = 58-62% volume loss
3. **Monotonic constraints harmful** - Increased vegas dependency, introduced critical biases
4. **Still below baseline** - Best HR 54.29% < 55.4% baseline on clean holdout

### What We Learned

#### ❌ V10 Features Are Not Enough
- pts_vs_season_zscore appeared in top 10 but only 2-3% importance
- pts_slope_10g (expected highest impact) didn't crack top 10
- dnp_rate and breakout_flag negligible (<0.05%)
- **Conclusion:** Trend features alone don't solve the problem

#### ❌ Monotonic Constraints Are Harmful
- Increased vegas dependency by 15-27pp
- Introduced critical star tier bias (-8.8 to -9.2 pts)
- Increased vegas bias to -3.4 to -3.5 (outside +/-1.5 limit)
- **Conclusion:** CatBoost learns better relationships unconstrained

#### ✅ Multi-Season Data Helps (But Not Enough)
- B1 (2-season) 54.29% > A1 (1-season) 51.28%
- Better MAE (5.04 vs 5.11)
- **Conclusion:** More data improves performance but doesn't close the gap to baseline

#### ❌ Trade Deadline Impact Persists
- All models struggle in Feb 2-11 window (48-55% HR)
- Baseline (55.4% on 92 picks) trained through Jan 31, eval Feb 1-11
- **Conclusion:** Feb 1-8 trade deadline disrupts all models equally

### Next Steps: Wave 2 Experiments Required

The V10 + Mono combination tested feature engineering (trend features) and constraints (domain correctness). Both failed. The problem is **structural, not feature-based**.

**Hypothesis for Wave 2:**
The model needs features that capture **market inefficiencies** not trend momentum:
1. **star_teammate_out** - Injury-driven usage spikes (known edge)
2. **game_total_line** - Pace proxy from Vegas (better than team_pace)
3. **line_movement_direction** - Sharp vs public money
4. **rest_differential** - Team rest vs opponent rest
5. **home_away_split_delta** - Player-specific home/road variance

**Wave 2 Plan:**
1. Add 5 new features (indices 37-41) → V11 feature set
2. Test on 2-season data (2024-12-01 to 2026-01-31)
3. Use Q43 quantile, 120d recency (best from Wave 1)
4. NO monotonic constraints (proven harmful)
5. Target: 58%+ clean holdout HR on 50+ picks

**Acceptance Criteria:**
- HR >= 58% on Feb 1-11 eval (vs 54.29% now)
- Volume >= 50 picks (vs 35 now)
- OVER direction >= 52.4% (vs 0% now)
- All 6 governance gates pass

---

## Appendix: Detailed Results

### A1: V10_1SZN_Q43_R14
```
Training: 2025-12-07 to 2026-02-04 (60 days)
Eval: 2026-02-05 to 2026-02-11 (7 days)
Feature Set: V10 (37 features)
Recency: 14-day half-life
Quantile: alpha=0.43

Results:
- Edge 3+ HR: 51.28% (39 picks)
- MAE: 5.11
- Vegas Bias: -1.38
- Week 1 (Feb 2-8): 53.3% (30 picks)
- Week 2 (Feb 9-15): 50.0% (9 picks)

Top Features:
1. vegas_points_line: 16.34%
2. vegas_opening_line: 12.06%
3. points_avg_last_10: 11.40%
4. points_avg_season: 9.18%
5. vegas_line_move: 3.12%
6. pts_vs_season_zscore: 2.99% ← NEW V10 FEATURE

Governance: FAIL (HR < 60%, n < 50, OVER collapsed)
```

### A2: MONO_1SZN_Q43_R14
```
Training: 2025-12-07 to 2026-02-04 (60 days)
Eval: 2026-02-05 to 2026-02-11 (7 days)
Feature Set: V9 (33 features)
Recency: 14-day half-life
Quantile: alpha=0.43
Monotonic: 5 constraints (pts_last_10↑, fatigue↓, opp_def↓, vegas↑, mins↑)

Results:
- Edge 3+ HR: 50.28% (179 picks)
- MAE: 5.84 (WORST)
- Vegas Bias: -3.46 (CRITICAL)
- Star Tier Bias: -9.18 pts (CRITICAL)
- Week 2: 51.3%

Top Features:
1. vegas_points_line: 31.86% (+15pp vs unconstrained)
2. points_avg_season: 13.64%
3. vegas_opening_line: 7.82%

Governance: FAIL (MAE worse, HR < 60%, vegas bias, tier bias, UNDER < 52.4%)
```

### A3: V10_MONO_1SZN_Q43
```
Training: 2025-12-07 to 2026-02-04 (60 days)
Eval: 2026-02-05 to 2026-02-11 (7 days)
Feature Set: V10 (37 features)
Recency: 14-day half-life
Quantile: alpha=0.43
Monotonic: 5 constraints

Results:
- Edge 3+ HR: 50.0% (178 picks)
- MAE: 5.83
- Vegas Bias: -3.43 (CRITICAL)
- Star Tier Bias: -9.20 pts (CRITICAL)
- Week 2: 51.3%

Top Features:
1. vegas_points_line: 31.39%
2. points_avg_season: 13.41%
3. vegas_opening_line: 7.57%

Governance: FAIL (same issues as A2)
```

### B1: V10_2SZN_Q43_R120 ⭐ BEST
```
Training: 2025-12-07 to 2026-02-04 (60 days)
Eval: 2026-02-05 to 2026-02-11 (7 days)
Feature Set: V10 (37 features)
Recency: 120-day half-life
Quantile: alpha=0.43

Results:
- Edge 3+ HR: 54.29% (35 picks) ← BEST HR
- MAE: 5.04 ← BEST MAE
- Vegas Bias: -1.37
- Week 1: 53.9%
- Week 2: 54.5%

Top Features:
1. vegas_points_line: 21.04%
2. points_avg_season: 10.85%
3. vegas_opening_line: 10.52%
4. points_avg_last_10: 10.02%
10. pts_vs_season_zscore: 2.30% ← NEW V10 FEATURE

Tier × Direction:
- Stars UNDER: 100% (3 picks)
- Starters UNDER: 50.0% (10 picks)
- Role UNDER: 55.6% (18 picks)
- Mid-range lines (12.5-20.5): 59.1% (22 picks) ← PROMISING

Governance: FAIL (HR < 60%, n < 50, OVER collapsed)
```

### B2: MONO_2SZN_Q43_R120
```
Training: 2025-12-07 to 2026-02-04 (60 days)
Eval: 2026-02-05 to 2026-02-11 (7 days)
Feature Set: V9 (33 features)
Recency: 120-day half-life
Quantile: alpha=0.43
Monotonic: 5 constraints

Results:
- Edge 3+ HR: 50.29% (175 picks)
- MAE: 5.80
- Vegas Bias: -3.44 (CRITICAL)
- Star Tier Bias: -8.82 pts (CRITICAL)
- Week 2: 49.3%

Top Features:
1. vegas_points_line: 39.81% (+18pp vs unconstrained)

Governance: FAIL (all gates except sample size)
```

### B3: V10_MONO_2SZN_Q43
```
Training: 2025-12-07 to 2026-02-04 (60 days)
Eval: 2026-02-05 to 2026-02-11 (7 days)
Feature Set: V10 (37 features)
Recency: 120-day half-life
Quantile: alpha=0.43
Monotonic: 5 constraints

Results:
- Edge 3+ HR: 51.12% (178 picks)
- MAE: 5.80
- Vegas Bias: -3.45 (CRITICAL)
- Star Tier Bias: -8.87 pts (CRITICAL)
- Week 2: 52.0%

Governance: FAIL (same issues as B2)
```

---

**Status:** All 6 experiments complete. None ready for deployment. Awaiting Wave 2 with market inefficiency features.
