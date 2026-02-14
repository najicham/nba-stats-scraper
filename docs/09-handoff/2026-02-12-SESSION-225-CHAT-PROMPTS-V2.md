# Session 225 — Follow-Up Chat Prompts (V2)

Based on results from Chats 1-3. Updated with corrected analysis.

---

## Chat 7: V10 + Monotonic Experiments (PRIORITY — Run Now)

```
You are continuing work on the NBA props prediction project. Session 225 ran SQL diagnostics (Chat 1), multi-season training (Chat 2), and V10 code changes (Chat 3). Now we need to test V10 features and monotonic constraints.

## Critical Context

### What We Know
1. **CLV confirmed real edge in January** (+3.04 avg CLV) that collapsed in February (-0.08). Staleness is the problem. Retraining is the fix.
2. **Multi-season training (Wave 1)** showed structural improvements but not enough alone:
   - 2SZN_Q43_R120 (best config): 45% clean holdout HR, but FIXED role player UNDER (68.4% vs champion's 22%)
   - Vegas dependency dropped from 29-36% to 23%
   - 120d recency significantly outperformed 14d on clean holdout (45% vs 31.6%)
   - 3rd season added nothing (recency weighting zeros it out)
3. **Code changes are committed** (684d8b9): --feature-set v10 and --monotone-constraints both working
4. **Trade deadline (Feb 1-8) destroyed all models** — even fresh models hit ~37-40% in that window

### Critical Lesson from Wave 1: Avoid Training/Eval Overlap
Wave 1 experiments trained through Feb 7 but eval started Feb 2 — 5 days of overlap inflated Week 1 numbers. For these experiments, use SEPARATE windows:
- Train through **Jan 31** (not Feb 7)
- Eval **Feb 1-11** (11 days, clean holdout, includes trade deadline impact)
This gives apples-to-apples comparison with the original Q43_RECENCY14 baseline (55.4% on 92 picks, also trained Nov 2 - Jan 31).

### V10 Features Being Activated
V10 adds 4 features (indices 33-36) to V9's 33:
- **pts_slope_10g** (34): 10-game scoring momentum. HIGHEST expected impact — addresses trend blindness.
- **pts_vs_season_zscore** (35): How far recent performance deviates from season average. Catches mid-season breakouts.
- **dnp_rate** (33): Load management risk.
- **breakout_flag** (36): Binary breakout indicator.

### Monotonic Constraints
Force domain-correct feature relationships. Prevents CatBoost from learning spurious splits:
- Index 1 (points_avg_last_10): +1 (more points → higher prediction)
- Index 5 (fatigue_score): -1 (more fatigue → lower prediction)
- Index 13 (opponent_def_rating): -1 (better defense → lower prediction)
- Index 25 (vegas_points_line): +1 (higher line → higher prediction)
- Index 31 (minutes_avg_last_10): +1 (more minutes → more points)

## YOUR TASK: Run 6 experiments

### Group A: Single-Season Configs (apples-to-apples with 55.4% baseline)

```bash
# A1: V10 features, single season, Q43, 14d recency (compare to 55.4% baseline)
/model-experiment --name "V10_1SZN_Q43_R14" --feature-set v10 --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-01-31 --recency-weight 14 --walkforward --force

# A2: Monotonic constraints, single season, V9 features, Q43, 14d recency
/model-experiment --name "MONO_1SZN_Q43_R14" --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0" --train-start 2025-11-02 --train-end 2026-01-31 --recency-weight 14 --walkforward --force

# A3: V10 + Monotonic, single season, Q43, 14d recency (FULL COMBO)
/model-experiment --name "V10_MONO_1SZN_Q43" --feature-set v10 --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0" --train-start 2025-11-02 --train-end 2026-01-31 --recency-weight 14 --walkforward --force
```

### Group B: Multi-Season Configs (build on Wave 1 findings)

```bash
# B1: V10 features, 2 seasons, Q43, 120d recency (best Wave 1 base + V10)
/model-experiment --name "V10_2SZN_Q43_R120" --feature-set v10 --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-01-31 --recency-weight 120 --walkforward --force

# B2: Monotonic constraints, 2 seasons, V9 features, Q43, 120d recency
/model-experiment --name "MONO_2SZN_Q43_R120" --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0" --train-start 2024-12-01 --train-end 2026-01-31 --recency-weight 120 --walkforward --force

# B3: V10 + Monotonic, 2 seasons, Q43, 120d recency (FULL COMBO)
/model-experiment --name "V10_MONO_2SZN_Q43" --feature-set v10 --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0" --train-start 2024-12-01 --train-end 2026-01-31 --recency-weight 120 --walkforward --force
```

NOTE: V10 monotonic constraints have 37 values (4 extra zeros at end for the new features, leaving them unconstrained). V9 has 33 values.

## AFTER ALL 6 COMPLETE: Analysis

Create docs/08-projects/current/model-improvement-analysis/09-V10-MONO-RESULTS.md with:

### 1. Results Table
| Experiment | Seasons | V10? | Mono? | Edge 3+ Picks | Edge 3+ HR | Week 1 HR | Week 2 HR | MAE | Vegas Bias |

### 2. Key Comparisons (use ONLY Week 2 / clean holdout numbers for HR)
- **V10 impact:** A1 vs baseline (55.4%). Does V10 improve single-season?
- **Monotonic impact:** A2 vs baseline. Do constraints improve generalization?
- **Combined impact:** A3 vs A1 vs A2 vs baseline. Is the combination better?
- **Multi-season benefit:** B1 vs A1 (same features, more data). Does 2-season help?
- **Best overall:** Which of the 6 has highest clean holdout HR on 30+ picks?

### 3. Feature Importance Analysis
For V10 experiments, report:
- Do pts_slope_10g and pts_vs_season_zscore appear in the top 15 features?
- What percentage of total importance do the 4 new features capture?
- Did Vegas dependency (features 25-28 combined) decrease?

### 4. Tier x Direction Breakdown
For the best model, report hit rates by tier (Stars/Starters/Role/Bench) × direction (OVER/UNDER). Compare to:
- Champion: Role UNDER 22%, Star OVER 62.5%
- 2SZN_Q43_R120 (Wave 1): Role UNDER 68.4%

### 5. Governance Assessment
For the best model, check:
- Gate 1: HR > 52.4%?
- Gate 2: P(true HR > 52.4%) > 90%?
- Gate 3: Better than champion (38%) by 8+ pp?
- Gate 4: No walkforward week below 40%?
- Gate 5: Volume (picks per day)?

### 6. Recommendation
- If any model > 55% on clean holdout with 30+ picks → shadow deploy candidate
- If 52.4-55% → promising, consider combining with post-processing (direction filter for starters)
- If < 52.4% → V10 and monotonic aren't enough, need new features (star_teammate_out, game_total_line)
- Compare 1-season vs 2-season to settle the data volume question

Do NOT deploy. Training and analysis only.
```

---

## Chat 8: Multi-Quantile Ensemble (Can Run in Parallel with Chat 7)

```
You are continuing work on the NBA props prediction project. We're testing whether running multiple quantile models and only betting when they AGREE produces higher hit rates.

## Context
- Champion model at 38% edge 3+ HR (decayed, 35 days stale)
- Q43 quantile is the only technique that generates edge when fresh
- The hypothesis: Train Q30, Q43, Q57 models. When all 3 predict the same direction, that's a high-confidence pick.
  - Q30 predicts ABOVE median (optimistic)
  - Q43 predicts BELOW median (our proven winner)
  - Q57 predicts ABOVE median
  - If even the optimistic Q57 predicts UNDER → very high confidence UNDER
  - If even the conservative Q43 predicts OVER → very high confidence OVER

## YOUR TASK: Train 3 models + analyze agreement

### Step 1: Train 3 quantile models (same training config)

Use single-season, 14d recency (the known-good base config). Train through Jan 31, eval Feb 1-11.

```bash
# Q30 (optimistic — predicts above median)
/model-experiment --name "MULTIQ_Q30_R14" --quantile-alpha 0.30 --train-start 2025-11-02 --train-end 2026-01-31 --recency-weight 14 --walkforward --force

# Q43 (conservative — our proven technique)
/model-experiment --name "MULTIQ_Q43_R14" --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-01-31 --recency-weight 14 --walkforward --force

# Q57 (optimistic — predicts above median)
/model-experiment --name "MULTIQ_Q57_R14" --quantile-alpha 0.57 --train-start 2025-11-02 --train-end 2026-01-31 --recency-weight 14 --walkforward --force
```

### Step 2: Analyze individual model performance

For each model, report: Edge 3+ picks, HR, OVER/UNDER split, walkforward weeks.

### Step 3: Simulate agreement-based filtering via SQL

After all 3 models are registered, query their predictions to find agreement:

```sql
-- Find picks where multiple quantile models agree on direction
-- This requires checking the ml_experiments or prediction outputs
-- If experiments produce model files but not production predictions,
-- note this limitation and describe what WOULD need to happen
```

If models don't produce queryable predictions (only backtest results), that's OK — report each model's individual performance and describe the ensemble methodology for future implementation.

### Step 4: Write results

Create docs/08-projects/current/model-improvement-analysis/10-MULTIQUANTILE-RESULTS.md with:

1. Individual model results table
2. Agreement analysis (if possible) or methodology description
3. Key questions answered:
   - Does Q30 generate OVER picks that Q43 misses?
   - Does Q57 confirm Q43's UNDER picks?
   - What's the volume of 3-model-agreement picks?
   - Is the agreement HR significantly higher than individual model HR?
4. Recommendation on whether to pursue multi-quantile in production

Do NOT deploy. Training and analysis only.
```

---

## Notes for the Operator

- **Chat 7** is the highest priority — directly tests V10 features and monotonic constraints
- **Chat 8** can run in parallel — tests a different approach (ensemble)
- Both use train-end Jan 31 / eval Feb 1-11 to avoid the overlap problem from Wave 1
- Chat 7 results determine whether we shadow-deploy or need more features
- If BOTH chats produce models above 55%: shadow deploy the best one
- If NEITHER breaks 52.4%: pivot to feature engineering (star_teammate_out, game_total_line)
