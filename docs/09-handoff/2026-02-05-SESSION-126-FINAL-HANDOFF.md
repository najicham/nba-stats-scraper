# Session 126 Final Handoff - Breakout Detection v2

**Date:** 2026-02-05
**Status:** Core implementation complete, ready for deployment and validation
**Next Session:** Continue with deployment, training, and open questions

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-05-SESSION-126-FINAL-HANDOFF.md

# 2. Check deployment status
./bin/check-deployment-drift.sh --verbose

# 3. Deploy Phase 4 with new features (v2_39features)
./bin/deploy-service.sh nba-phase4-precompute-processors

# 4. Verify new features are generating
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as records,
  ROUND(AVG(features[OFFSET(37)]), 1) as avg_breakout_risk,
  ROUND(AVG(features[OFFSET(38)]), 1) as avg_composite_signal
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1"
```

---

## What Was Built (Session 126)

### 1. Breakout Detection v2 - Feature Store Integration

**ML Feature Store updated to v2_39features:**

| Feature # | Name | Range | Description |
|-----------|------|-------|-------------|
| 37 | `breakout_risk_score` | 0-100 | Composite score predicting breakout probability |
| 38 | `composite_breakout_signal` | 0-5 | Simple factor count (37% breakout rate at 4+) |

### 2. Enhanced Breakout Risk Calculator

**New weight distribution (Session 126):**

| Component | Weight | Source | Key Insight |
|-----------|--------|--------|-------------|
| Hot Streak | 15% | pts_vs_season_zscore | Reduced from 30% |
| **Cold Streak Bonus** | **10%** | L5 vs L10 trend | **NEW** - Mean reversion |
| **Volatility (CV ratio)** | **25%** | std/avg | **Enhanced** - Strongest predictor |
| Opponent Defense | 20% | opponent_def_rating | Unchanged |
| **Opportunity** | **15%** | usage_trend + injury | **Enhanced** - Usage trend added |
| Historical | 15% | breakout rate L10 | Unchanged |

**Key additions:**
- `cv_ratio` (coefficient of variation) - correlation +0.198
- `cold_streak_bonus` - mean reversion signal
- `usage_trend` - rising usage indicates opportunity
- `composite_breakout_signal` - 0-5 factor count

### 3. Composite Breakout Signal (0-5)

Each factor adds +1:
1. High variance (CV >= 60%)
2. Cold streak (L5 20%+ below L10)
3. Starter status (usage >= 18% proxy)
4. Home game
5. Rested (<=2 games in 7 days)

**Historical Performance:**
| Score | Breakout Rate | Games |
|-------|---------------|-------|
| 5 | 57.1% | 14 |
| 4 | **37.4%** | 107 |
| 3 | 29.6% | 334 |
| 2 | 24.8% | 448 |
| 1 | 15.4% | 298 |
| 0 | 2.9% | 35 |

**Key insight:** Score 4+ = 37% breakout rate (2x the 19.8% baseline)

---

## Validated Correlation Coefficients

BigQuery analysis confirmed our feature priorities:

| Feature | Correlation | Implementation |
|---------|-------------|----------------|
| cv_ratio | **+0.198** | ✅ Primary volatility signal |
| is_starter | +0.162 | ✅ Composite signal factor |
| points_avg_season | -0.218 | ✅ Role player focus (8-16 PPG) |
| usage_rate | -0.134 | ✅ Usage trend component |
| is_home | +0.028 | ✅ Composite signal factor |
| games_in_last_7_days | -0.027 | ✅ "Rested" factor |
| trend_ratio | -0.020 | ✅ Cold streak bonus |

---

## Counter-Intuitive Findings (IMPORTANT)

### 1. Cold Players Break Out MORE
- Cold streak (L5 20%+ below L10): **27.1%** breakout rate
- Hot streak (L5 20%+ above L10): 21.7% breakout rate
- **Mean reversion is real in NBA scoring**

### 2. Lower Scorers Break Out More
- Bench (5-8 PPG): 33.6% breakout rate
- Role (8-14 PPG): 19.3% breakout rate
- Stars (25+ PPG): 6.1% breakout rate
- **Easier threshold to hit for lower scorers**

### 3. CV Ratio is Strongest Predictor
- High variance (CV 60%+): 29.5% breakout rate
- Very consistent (CV <25%): 9.0% breakout rate
- **3.3x difference!**

---

## Deployed Services (Session 125B + 126)

**⚠️ DEPLOYMENT DRIFT DETECTED** - v2_39features code committed but not deployed

| Service | Status | What's Needed |
|---------|--------|---------------|
| prediction-worker | ❌ **NEEDS DEPLOY** | v2_39features code |
| prediction-coordinator | ❌ **NEEDS DEPLOY** | v2_39features code |
| nba-phase4-precompute-processors | ❌ **NEEDS DEPLOY** | v2_39features (critical!) |
| nba-phase3-analytics-processors | ❌ **NEEDS DEPLOY** | v2_39features code |

**To deploy all stale services:**
```bash
# Deploy all 4 stale services (can run in parallel)
./bin/deploy-service.sh nba-phase4-precompute-processors &
./bin/deploy-service.sh prediction-worker &
./bin/deploy-service.sh prediction-coordinator &
./bin/deploy-service.sh nba-phase3-analytics-processors &
wait
```

---

## Files Changed (Session 126)

| File | Changes |
|------|---------|
| `data_processors/precompute/ml_feature_store/breakout_risk_calculator.py` | +CV ratio, +cold streak, +usage trend, +composite signal |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Integrated features 37-38, v2_39features |
| `shared/ml/feature_contract.py` | Updated to v2_39features, 39 features |
| `tests/.../test_breakout_risk_calculator.py` | Updated tests for new components |
| `docs/08-projects/current/breakout-detection-v2/BREAKOUT-DETECTION-V2-DESIGN.md` | Full design document |

---

## Remaining Tasks

### P1: Deploy Phase 4 (Immediate)
```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

### P2: Implement Real injured_teammates_ppg
Currently uses placeholder. Need to:
1. Query `nba_raw.nbac_injury_report`
2. Join with player PPG from `player_daily_cache`
3. Pass to breakout_risk_calculator

When 30+ PPG injured: **24.5%** breakout rate (vs 16.2% baseline)

### P3: Shadow Mode Validation
Run new filters in shadow mode to accumulate samples:
- Target: 100+ samples per filter category
- Duration: 2-4 weeks
- Then enable for production

---

## OPEN QUESTION: Role Player Definition for Training

**Question:** How do we determine who role players are for training the breakout classifier?

**Options:**

### Option A: Final Date of Training Range
- Take player PPG averages on the last day of training data
- Players with 8-16 PPG on that date are "role players"
- Use this fixed list for all training data
- **Pro:** Consistent definition, no lookahead bias
- **Con:** Player status changes mid-season (injury, trade, breakout)

### Option B: Per-Game Classification
- Classify player as role player on each game date based on their season avg at that point
- A player might be "role player" in Nov but "starter" by Feb
- **Pro:** Reflects evolving player status
- **Con:** More complex, training target changes

### Option C: Minutes-Based Definition
- Use minutes_avg instead of points_avg
- Role players: 15-28 minutes per game
- **Pro:** More stable than points (less variance)
- **Con:** Doesn't directly relate to scoring breakouts

### Option D: Hybrid (PPG + Minutes)
- Role player: 8-16 PPG AND 15-30 minutes
- Excludes high-minute low-scorers (defensive specialists)
- Excludes low-minute high-scorers (spark plugs)
- **Pro:** More precise targeting
- **Con:** Smaller sample size

**Recommendation:** Start with **Option A** (final date) for simplicity, then evaluate if per-game classification improves results.

**Related code location:** `ml/experiments/train_breakout_classifier.py` lines 80-100

---

## Key Documentation

| Document | Location |
|----------|----------|
| v2 Design Doc | `docs/08-projects/current/breakout-detection-v2/BREAKOUT-DETECTION-V2-DESIGN.md` |
| Session 125B Handoff | `docs/09-handoff/2026-02-05-SESSION-125B-BREAKOUT-DETECTION-HANDOFF.md` |
| Breakout Risk Score Design | `docs/08-projects/current/breakout-risk-score/BREAKOUT-RISK-SCORE-DESIGN.md` |
| Original Detection Design | `docs/08-projects/current/breakout-detection-design/BREAKOUT-DETECTION-DESIGN.md` |

---

## Commits (Session 126)

```
5a7e3431 - feat: Add breakout detection v2 with CV ratio, usage trend, and composite signal
8fd93790 - docs: Add Session 126 handoff
```

---

## Monitoring Queries

### Check New Features Are Generating
```sql
SELECT
  game_date,
  COUNT(*) as records,
  ROUND(AVG(features[OFFSET(37)]), 1) as avg_breakout_risk,
  ROUND(AVG(features[OFFSET(38)]), 1) as avg_composite_signal,
  COUNTIF(features[OFFSET(38)] >= 4) as high_signal_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1
ORDER BY 1 DESC
```

### Validate Composite Signal Distribution
```sql
SELECT
  CAST(features[OFFSET(38)] AS INT64) as composite_signal,
  COUNT(*) as players,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY 1
```

### Check Session 125B Filters Working
```sql
SELECT
  game_date,
  filter_reason,
  COUNT(*) as filtered,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1) as would_have_hit
FROM nba_predictions.prediction_accuracy
WHERE is_actionable = FALSE
  AND filter_reason IS NOT NULL
  AND game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2
ORDER BY 1 DESC, 2
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    BREAKOUT DETECTION v2                        │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 1: Feature Store (Phase 4)                                │
│   Features 37-38: breakout_risk_score, composite_breakout_signal│
│   File: ml_feature_store_processor.py                           │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 2: Breakout Risk Calculator                               │
│   Components: hot_streak, cold_streak_bonus, volatility (CV),   │
│               opponent_defense, opportunity (usage+injury),     │
│               historical_rate                                   │
│   File: breakout_risk_calculator.py                             │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 3: Prediction Worker Filters (Session 125B - DEPLOYED)    │
│   - role_player_under_low_edge                                  │
│   - hot_streak_under_risk                                       │
│   - low_data_quality                                            │
│   File: predictions/worker/worker.py                            │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 4: Future - Breakout Classifier (Not Yet Trained)         │
│   File: ml/experiments/train_breakout_classifier.py             │
│   Target: AUC >= 0.65                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Summary

Session 126 completed the core breakout detection v2 implementation:
- ✅ Integrated breakout_risk_score into feature store
- ✅ Added CV ratio (strongest predictor)
- ✅ Added cold streak bonus (mean reversion)
- ✅ Added usage trend to opportunity
- ✅ Created composite_breakout_signal (0-5)
- ✅ Updated tests (31 passing)
- ✅ Created documentation

**Next steps:**
1. Deploy Phase 4 to get new features live
2. Implement real injured_teammates_ppg
3. Decide role player definition for classifier training
4. Train breakout classifier
5. Shadow mode validation

---

*Session 126 - Breakout Detection v2 Complete*
