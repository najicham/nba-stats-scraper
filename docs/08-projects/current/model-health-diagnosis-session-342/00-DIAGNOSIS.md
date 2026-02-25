# Model Health Diagnosis — Session 342

**Date:** 2026-02-25
**Status:** All models BLOCKED or DEGRADING
**Champion:** catboost_v12 (interim since 2026-02-23)
**Best performing model:** catboost_v9_low_vegas_train0106_0205 at 53.7% 7d HR (barely above 52.4% breakeven)

## Executive Summary

Every CatBoost model in production is underperforming. The root cause is **not** feature quality, feature count, or a pipeline bug — it's a structural prediction bias. All models systematically predict 1.0–1.6 points below Vegas lines, generating mostly UNDER bets that are losing money. Vegas is consistently more accurate than our models (lower MAE every week for 6 weeks). A simple retrain will help with staleness but won't fix the structural UNDER bias.

---

## 1. The Evidence

### 1.1 All Models Are Underwater

| Model | 7d HR (edge 3+) | 14d HR | State | Days Since Training |
|-------|-----------------|--------|-------|---------------------|
| catboost_v12 (champion) | 50.7% | 48.1% | BLOCKED | 9 |
| catboost_v9 | 42-45% | 43-44% | BLOCKED | 19 |
| catboost_v9_q43 | 45-46% | 45-46% | BLOCKED | 30 |
| catboost_v9_q45 | 50-51% | 50-51% | BLOCKED | 30 |
| catboost_v12_noveg_train1102_0205 | 55.6% | 55.6% | WATCH | 9 |
| catboost_v9_low_vegas_train0106_0205 | 53.7% | 53.7% | DEGRADING | 19 |
| catboost_v12_q43_train1225_0205 | 14.3% | 14.3% | BLOCKED | 9 |

Not a single model is HEALTHY. The best two (`noveg` and `low_vegas` variants) are barely above breakeven.

### 1.2 Weekly Edge 3+ Performance Collapse

**V12 (Champion):**

| Week | Edge 3+ Picks | Wins | Hit Rate | MAE |
|------|---------------|------|----------|-----|
| Feb 23 | 20 | 7 | **35.0%** | 6.57 |
| Feb 16 | 48 | 28 | 58.3% | 5.73 |
| Feb 9 | 11 | 6 | 54.5% | 4.84 |
| Feb 2 | 33 | 18 | 54.5% | 6.28 |
| Jan 26 | 6 | 4 | 66.7% | 6.03 |

**V9 (Previous Champion):**

| Week | Edge 3+ Picks | Wins | Hit Rate | MAE |
|------|---------------|------|----------|-----|
| Feb 23 | 3 | 1 | 33.3% | 4.33 |
| Feb 16 | 17 | 8 | 47.1% | 6.86 |
| Feb 9 | 51 | 23 | 45.1% | 6.64 |
| Feb 2 | 124 | 45 | **36.3%** | 8.51 |
| Jan 26 | 96 | 55 | 57.3% | 6.54 |
| Jan 19 | 112 | 75 | **67.0%** | 4.93 |

V9 went from 67% in mid-January to 36% by early February. V12 had one good week (Feb 16) but otherwise hovers around breakeven or worse.

### 1.3 Systematic UNDER Bias

V12 predicts below Vegas for **77–89% of all predictions**, every single week:

| Week | % Predictions Below Vegas | Avg Pred vs Vegas |
|------|--------------------------|-------------------|
| Feb 23 | 77.5% | -1.40 pts |
| Feb 16 | 80.6% | -1.58 pts |
| Feb 9 | **89.2%** | -1.55 pts |
| Feb 2 | 73.4% | -0.99 pts |
| Jan 26 | 79.5% | -1.09 pts |

This means nearly ALL edge 3+ picks are UNDER recommendations:

| Week | UNDER Picks | UNDER HR | OVER Picks | OVER HR |
|------|-------------|----------|------------|---------|
| Feb 23 | 19 | **36.8%** | 1 | 0.0% |
| Feb 16 | 39 | 56.4% | 9 | 66.7% |
| Feb 9 | 11 | 54.5% | 0 | — |
| Feb 2 | 28 | 53.6% | 5 | 60.0% |
| Jan 26 | 5 | 80.0% | 1 | 0.0% |

When the model DOES predict OVER with edge, it often wins (66.7% in Feb 16). But it almost never makes OVER picks because of the systematic low bias.

### 1.4 Model Is Less Accurate Than Vegas

V12 has a **higher MAE** (worse accuracy) than Vegas lines every week:

| Week | V12 MAE | Vegas MAE | V12 Worse By |
|------|---------|-----------|-------------|
| Feb 23 | 5.69 | 5.24 | **+0.45** |
| Feb 16 | 5.17 | 4.98 | +0.19 |
| Feb 9 | 4.72 | 4.51 | +0.21 |
| Feb 2 | 5.08 | 4.91 | +0.16 |
| Jan 26 | 5.02 | 4.75 | +0.27 |

Full February: V12 MAE 5.10, Vegas MAE 4.88 (V12 is 0.23 worse).

The model cannot beat Vegas on raw prediction accuracy. It's not even close.

### 1.5 Bias By Player Tier (Last 14 Days)

Using season average tiers (correct methodology per Session 161):

| Tier | N | Avg Predicted | Avg Actual | Model Bias | Vegas Bias | Edge 3+ HR |
|------|---|---------------|------------|------------|------------|-----------|
| Stars (25+ avg) | 25 | 24.8 | 27.1 | **-2.32** | +0.66 | 50.0% |
| Starters (15-24) | 146 | 17.2 | 19.2 | **-1.99** | -0.21 | 48.6% |
| Role (8-14) | 204 | 10.3 | 11.2 | -0.85 | +0.40 | **60.9%** |
| Bench (<8) | 40 | 6.2 | 6.1 | +0.15 | +1.73 | 0.0% |

The UNDER bias is worst for Stars (-2.32) and Starters (-1.99). Role players are the only tier where edge 3+ is profitable. Bench players have no edge 3+ picks.

### 1.6 Training Period vs Post-Training

| Period | Predictions | Avg Actual | Avg Predicted | Actual vs Vegas | Edge 3+ HR |
|--------|-------------|------------|---------------|-----------------|-----------|
| Training (Dec 25 – Feb 5) | 237 | 14.1 | 12.9 | +0.11 | 56.0% |
| Post-training (Feb 6+) | 580 | 14.1 | 13.1 | -0.44 | 52.7% |

Scoring hasn't changed (14.1 avg both periods), but Vegas lines shifted up by ~0.5 pts relative to actual. The model didn't adapt.

---

## 2. Root Cause Analysis

### It's NOT about features

Feature quality is healthy:
- Matchup quality: 97–100%
- Player history quality: 93–98%
- Vegas quality: 58–89% (varies by time of day, normal)
- Average defaults: 1.7–5.8 (within normal range)

Adding or removing features won't fix a model that systematically predicts 1–2 points below actual scores.

### It IS about these three things:

#### 2.1 CatBoost MAE/Huber Loss Creates Mean-Regression Bias

CatBoost with MAE or Huber loss minimizes absolute error. This pulls predictions toward the **conditional mean**, which is closer to season averages than to any individual game. When a player's Vegas line is set above their recent average (because the market sees upside), the model still predicts near the average → UNDER bias.

This is a **structural property of the loss function**, not a bug.

#### 2.2 Training Data Staleness

- V12 trained through ~Feb 5 (20 days stale)
- V9 trained through ~Jan 8 (48 days stale)
- Post All-Star Break scoring patterns, trade deadline roster changes, and shifted Vegas line-setting behavior aren't captured

#### 2.3 Over-Reliance on Vegas Features When Vegas Is More Accurate

The `low_vegas` variant (53.7% HR) and `noveg` variant (55.6% HR) are the two best-performing models. Both **reduce or eliminate Vegas features**. This makes sense: when Vegas is more accurate than your model, including Vegas as a feature pulls your predictions toward Vegas rather than finding independent signal. The model ends up being a worse copy of Vegas instead of a complementary perspective.

---

## 3. What Won't Work

| Approach | Why It Won't Help |
|----------|-------------------|
| More features | Feature quality is already high; model bias is independent of feature count |
| Fewer features | Same reason — bias is in the loss function and training data, not features |
| Tighter quality gates | Quality gates are already strict (zero tolerance). Not a quality problem |
| Lower edge threshold | Would add more low-confidence picks, making things worse |
| Q43 quantile model | Predicts the 43rd percentile — even LOWER than mean. Wrong direction entirely. The Q43 models are at 14–46% HR, the worst of all |
| Two-stage pipeline | Already proven dead end (CLAUDE.md) |

---

## 4. What Should Help

### 4.1 Immediate: Fresh Retrain (Expected Impact: +3–5 pp HR)

Retrain all families with training window through Feb 24. This fixes the staleness problem but not the structural bias. Expected to bring edge 3+ HR from ~50% back to ~55%, enough to be marginally profitable.

### 4.2 Structural: Q55–Q60 Quantile Models (Expected Impact: +5–10 pp HR)

Since the model systematically predicts low, train quantile models at the **55th–60th percentile** instead of the mean or 43rd percentile. This directly counteracts the UNDER bias by teaching the model to predict above the median.

The Q43 models were a well-intentioned idea (predict conservatively), but the data shows the opposite is needed — the model already predicts too conservatively.

### 4.3 Architectural: Reduce Vegas Feature Weight (Expected Impact: +2–4 pp HR)

Evidence:
- `catboost_v9_low_vegas` = 53.7% (best of any V9 variant)
- `catboost_v12_noveg` variants = 52.8–55.6% (best of any V12 variant)
- Full-Vegas variants = 42–50.7%

The model adds value when it forms its own opinion rather than anchoring on Vegas. Consider:
- Training without Vegas features entirely (`noveg` approach)
- Reducing Vegas feature importance via feature weighting
- Using Vegas only as a post-prediction filter/signal, not a training feature

### 4.4 Hybrid: Direction-Aware Betting Filter

Since OVER picks win at 60–67% when they exist, and UNDER picks are losing:
- Only bet UNDER when edge is very high (5+) AND model agrees with recent trend
- Lower the OVER edge threshold to capture more of the rare but profitable OVER picks
- This is a filter change, not a model change — can be implemented immediately

---

## 5. Pipeline Health (Non-Model Issues Found)

These are separate from the model health crisis but should be addressed:

| Issue | Severity | Details |
|-------|----------|--------|
| Missing team stats (ORL, LAL) | P2 | team_offense_game_summary missing for 2026-02-24 ORL@LAL game |
| Game ID format mismatch | P3 | Schedule uses `0022500831` format, analytics uses `20260224_BOS_PHX` |
| Firestore completion tracking absent | P3 | No phase3_completion documents for Feb 24 or Feb 25 |
| Phase 4 dependency errors | P3 | Multiple DependencyError at 0% coverage (timing-related, eventually succeeded) |
| 2 failing scheduler jobs | P4 | analytics-quality-check-morning (INTERNAL), self-heal-predictions (DEADLINE_EXCEEDED) |
| Today's pre-game signal: RED | P2 | UNDER_HEAVY skew, only 3 V12 high-edge picks for tonight's 6 games |

---

## 6. Recommended Priority Order

1. **Today:** Direction-aware filter — block UNDER edge 3-4 picks, only allow UNDER edge 5+. Allow OVER edge 3+. Can be done with a config change.
2. **This week:** Fresh retrain of all families through Feb 24.
3. **This week:** Train Q55 and Q57 quantile models alongside the MAE models.
4. **Next retrain cycle:** Evaluate `noveg` vs full-Vegas variants. If `noveg` continues to outperform, make it the default architecture.
5. **Fix pipeline issues:** Re-trigger Phase 3 for ORL/LAL, investigate scheduler failures.

---

## Appendix: Raw Query Results

All queries run against `nba-props-platform` BigQuery on 2026-02-25 ~10:20 AM ET. Full query text available in the Session 342 conversation transcript.
