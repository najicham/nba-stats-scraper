# Session 127 Start Prompt - Breakout Detection v2

**Date:** 2026-02-05
**Focus:** Complete breakout detection system deployment and remaining tasks
**Previous:** Session 126 built v2_39features with breakout_risk_score and composite_breakout_signal

---

## Immediate Priority: Deploy Services

```bash
# Check deployment drift first
./bin/check-deployment-drift.sh --verbose

# Deploy all stale services (run in parallel)
./bin/deploy-service.sh nba-phase4-precompute-processors &
./bin/deploy-service.sh prediction-worker &
./bin/deploy-service.sh prediction-coordinator &
./bin/deploy-service.sh nba-phase3-analytics-processors &
wait

# Verify deployment
./bin/whats-deployed.sh
```

---

## What Was Built (Session 126)

### Feature Store: v2_39features

| Feature # | Name | Range | Purpose |
|-----------|------|-------|---------|
| 37 | `breakout_risk_score` | 0-100 | Composite breakout probability |
| 38 | `composite_breakout_signal` | 0-5 | Simple factor count (4+ = 37% breakout rate) |

### Breakout Risk Calculator Components

| Component | Weight | Key Signal |
|-----------|--------|------------|
| Hot Streak | 15% | pts_vs_season_zscore |
| **Cold Streak Bonus** | 10% | L5 vs L10 (mean reversion) |
| **Volatility (CV ratio)** | 25% | std/avg - strongest predictor |
| Opponent Defense | 20% | opponent_def_rating |
| **Opportunity** | 15% | usage_trend + injury placeholder |
| Historical | 15% | L10 breakout rate |

### Key Counter-Intuitive Findings

1. **Cold players break out MORE** - 27.1% vs 21.7% for hot players (mean reversion)
2. **CV ratio is strongest predictor** - 29.5% breakout at CV 60%+ vs 9.0% at CV <25%
3. **Lower scorers break out more** - 33.6% for bench (5-8 PPG) vs 6.1% for stars

---

## Remaining Tasks

### P1: Deploy (Immediate)
All 4 services have deployment drift - code committed but not deployed.

### P2: Implement Real injured_teammates_ppg
Currently placeholder. Need to:
1. Query `nba_raw.nbac_injury_report` for injured players
2. Join with `player_daily_cache` for their PPG
3. Pass team_context to breakout_risk_calculator

When 30+ PPG injured: **24.5%** breakout rate (vs 16.2% baseline)

### P3: Role Player Definition (Open Question)

**How do we define "role players" for training the breakout classifier?**

| Option | Definition | Pro | Con |
|--------|------------|-----|-----|
| **A (Recommended)** | PPG on final training date | Simple, no lookahead | Status changes |
| B | Per-game PPG at that point | Reflects evolution | Complex |
| C | Minutes (15-28 min) | More stable | Not scoring-related |
| D | Hybrid PPG + Minutes | Precise | Small sample |

### P4: Train Breakout Classifier
```bash
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_V1" \
    --train-start 2025-11-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-04
```

### P5: Shadow Mode Validation
Target 100+ samples per filter category before enabling production filters.

---

## Key Files

| Purpose | File |
|---------|------|
| Risk Calculator | `data_processors/precompute/ml_feature_store/breakout_risk_calculator.py` |
| Feature Store | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` |
| Feature Contract | `shared/ml/feature_contract.py` |
| Prediction Filters | `predictions/worker/worker.py` |
| Classifier Training | `ml/experiments/train_breakout_classifier.py` |
| Design Doc | `docs/08-projects/current/breakout-detection-v2/BREAKOUT-DETECTION-V2-DESIGN.md` |

---

## Verification Queries

### Check New Features Generating (after deploy)
```sql
SELECT
  game_date,
  COUNT(*) as records,
  ROUND(AVG(features[OFFSET(37)]), 1) as avg_breakout_risk,
  ROUND(AVG(features[OFFSET(38)]), 1) as avg_composite_signal
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1
```

### Check Session 125B Filters Working
```sql
SELECT
  filter_reason,
  COUNT(*) as filtered,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as would_have_hit
FROM nba_predictions.prediction_accuracy
WHERE is_actionable = FALSE
  AND filter_reason IS NOT NULL
  AND game_date >= '2026-02-04'
GROUP BY 1
```

---

## Session 126 Commits

```
5a7e3431 - feat: Add breakout detection v2 with CV ratio, usage trend, and composite signal
8fd93790 - docs: Add Session 126 handoff
944b2f9e - docs: Add Session 126 final handoff with deployment drift warning
0db20268 - docs: Update breakout v2 design doc with implementation status
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  BREAKOUT DETECTION v2                       │
├─────────────────────────────────────────────────────────────┤
│ LAYER 1: Feature Store (Phase 4) - v2_39features            │
│   Features 37-38: breakout_risk_score, composite_signal     │
├─────────────────────────────────────────────────────────────┤
│ LAYER 2: Breakout Risk Calculator                           │
│   6 components: hot, cold, volatility, defense, opp, hist   │
├─────────────────────────────────────────────────────────────┤
│ LAYER 3: Prediction Worker Filters (Session 125B)           │
│   role_player_under_low_edge, hot_streak_under_risk,        │
│   low_data_quality                                          │
├─────────────────────────────────────────────────────────────┤
│ LAYER 4: Breakout Classifier (NOT YET TRAINED)              │
│   Target: AUC >= 0.65                                       │
└─────────────────────────────────────────────────────────────┘
```

---

*Ready for Session 127 - Deploy and continue breakout detection work*
