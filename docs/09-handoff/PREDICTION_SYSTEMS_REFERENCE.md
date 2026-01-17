# NBA Prediction Systems Reference
## Training Data, Performance Tracking & Model Comparison

**Last Updated**: 2026-01-16
**Session**: 75
**Purpose**: Track training data, performance metrics, and model evolution for all prediction systems

---

## Quick Reference Table

| System | Type | Status | Training Period | Deployed | Best Win Rate | Notes |
|--------|------|--------|----------------|----------|---------------|-------|
| **catboost_v8** | ML Ensemble | ✅ Active | 2021-2024 (76,863 games) | Jan 1, 2026 | 73.3% (90-92% conf) | Production champion, filter 88-90% tier |
| **xgboost_v1** | ML | ❌ Invalid Data | Unknown | Jan 9, 2026 | N/A | Needs real lines, relaunch required |
| **moving_average_baseline_v1** | Statistical | ❌ Invalid Data | N/A | Jan 9, 2026 | N/A | Needs real lines, relaunch required |
| **ensemble_v1** | Ensemble | ✅ Active | N/A (combines others) | Deployed | 58.2% (86-88% conf) | Combines 4 systems |
| **similarity_balanced_v1** | Rule-based | ✅ Active | N/A (historical games) | Deployed | 60.4% (<80% conf) | Uses last 30 games |
| **zone_matchup_v1** | Rule-based | ✅ Active | N/A (shot zones) | Deployed | 55.4% | Shot zone analysis |
| **moving_average** | Statistical | ✅ Active | N/A (rolling avg) | Deployed | 55.8% | Simple baseline |

---

## System Details

### 1. CatBoost V8 (ML Ensemble)

#### System Information
- **System ID**: `catboost_v8`
- **Type**: Machine Learning (Stacked Ensemble)
- **Algorithm**: XGBoost + LightGBM + CatBoost with Ridge meta-learner
- **Features**: 33 features
- **Model File**: `models/catboost_v8_33features_*.cbm`

#### Training Data
- **Training Period**: 2021-2024 seasons
- **Training Games**: 76,863 games
- **Training MAE**: 3.40 points
- **Training Set**: Historical NBA games 2021-2024
- **Validation**: Out-of-sample 2024-25 data
- **Last Retrained**: Unknown (prior to Jan 2026)

#### Features Used (33)
**Base Features (25)**:
- points_avg_last_5, points_avg_last_10, points_avg_season
- points_std_last_10, games_in_last_7_days, fatigue_score
- shot_zone_mismatch_score, pace_score, usage_spike_score
- rest_advantage, injury_risk, recent_trend, minutes_change
- opponent_def_rating, opponent_pace, home_away
- back_to_back, playoff_game
- pct_paint, pct_mid_range, pct_three, pct_free_throw
- team_pace, team_off_rating, team_win_pct

**Vegas Features (4)**:
- vegas_points_line, vegas_opening_line
- vegas_line_move, has_vegas_line

**Opponent History (2)**:
- avg_points_vs_opponent, games_vs_opponent

**Minutes/PPM History (2)**:
- minutes_avg_last_10, ppm_avg_last_10

#### Performance by Time Period (Real Lines Only)

**November 2025**:
- Games: 2,875
- Win Rate: 84.4%
- MAE: 6.77
- Status: Excellent

**December 2025**:
- Games: 4,261
- Win Rate: 82.0%
- MAE: 6.30
- Status: Excellent

**January 1-7, 2026**:
- Games: 688
- Win Rate: 66.4%
- MAE: 4.30
- Status: Good (declining from Dec)

**January 8-15, 2026 (Real Lines Only)**:
- Games: 668
- Win Rate: 55.1%
- MAE: 6.41
- Status: Marginal (recovered to 63% on Jan 15)

#### Performance by Confidence Tier (Jan 1-15, Real Lines)

| Confidence Tier | Picks | Win Rate | MAE | Status |
|----------------|-------|----------|-----|--------|
| 92%+ | 287 | **71.8%** | 3.05 | ✅ Excellent |
| 90-92% | 165 | **73.3%** | 4.23 | ✅ Excellent |
| **88-90%** | **156** | **45.5%** | **8.28** | ❌ **FILTERED** |
| 86-88% | 173 | 56.1% | 5.65 | ✅ OK |
| 80-86% | 76 | 48.7% | 7.45 | ⚠️ Marginal |
| <80% | 499 | 58.7% | 5.89 | ✅ OK |

**Filtering Applied**: 88-90% confidence tier (since deployment)

#### Performance by Recommendation Type (Jan 1-15, Real Lines)

| Type | Picks | Win Rate | MAE |
|------|-------|----------|-----|
| UNDER | 893 | 60.3% | 5.89 |
| OVER | 463 | 44.9% | 6.97 |

**Strength**: UNDER predictions (+15.4% vs OVER)

#### Next Actions
- Monitor Jan 15+ performance for sustained recovery
- Consider retraining if win rate stays below 60%
- Possible 80-86% tier filtering

---

### 2. XGBoost V1 (ML - Gradient Boosted Trees)

#### System Information
- **System ID**: `xgboost_v1`
- **Type**: Machine Learning (XGBoost)
- **Algorithm**: Gradient Boosted Decision Trees
- **Features**: 25 features (subset of v8)
- **Model File**: `models/xgboost_v1_*.pkl` (assumed)

#### Training Data
- **Training Period**: UNKNOWN (needs documentation)
- **Training Games**: UNKNOWN
- **Training MAE**: UNKNOWN
- **Last Retrained**: Unknown

#### Features Used (25)
Same as CatBoost V8 base features (without Vegas, opponent history, minutes/PPM)

#### Deployment History
- **Launched**: Jan 9, 2026
- **Status**: ❌ INVALID DATA - All predictions used placeholder lines (20.0)
- **Games**: 2 days (Jan 9-10)
- **Predictions**: 293 total

#### Performance (INVALID - Placeholder Lines)
- **Claimed Win Rate**: 87.5% (249-22)
- **ACTUAL Win Rate**: UNKNOWN (no real sportsbook lines)
- **Line Quality**: 0% real lines, 100% placeholder (20.0)
- **Verdict**: Cannot evaluate performance

#### Next Actions
- ✅ **CRITICAL**: Fix line fetching
- ✅ Re-launch with real DraftKings/FanDuel lines
- ✅ Run for 7+ days to gather valid data
- ✅ Delete Jan 9-10 invalid predictions
- Document training data details

---

### 3. moving_average_baseline_v1 (Statistical)

#### System Information
- **System ID**: `moving_average_baseline_v1`
- **Type**: Statistical Baseline
- **Algorithm**: Simple moving average
- **Features**: Basic stats only

#### Training Data
- **Training Period**: N/A (no training, uses live data)
- **Calculation**: Rolling average of recent games

#### Deployment History
- **Launched**: Jan 9, 2026
- **Status**: ❌ INVALID DATA - All predictions used placeholder lines (20.0)
- **Games**: 2 days (Jan 9-10)
- **Predictions**: 275 total

#### Performance (INVALID - Placeholder Lines)
- **Claimed Win Rate**: 83.2% (253-17)
- **ACTUAL Win Rate**: UNKNOWN (no real sportsbook lines)
- **Line Quality**: 0% real lines, 100% placeholder (20.0)
- **Verdict**: Cannot evaluate performance

#### Next Actions
- Same as XGBoost V1 (fix lines, relaunch, validate)

---

### 4. Ensemble V1 (Ensemble Combiner)

#### System Information
- **System ID**: `ensemble_v1`
- **Type**: Ensemble (Meta-predictor)
- **Algorithm**: Combines 4 base systems with weighted average
- **Components**: moving_average, zone_matchup_v1, similarity_balanced_v1, catboost_v8

#### Training Data
- **Training Period**: N/A (uses other systems' outputs)
- **Weights**: Learned or configured (needs documentation)

#### Performance (Jan 1-15, Real Lines)
- **Games**: 663
- **Win Rate**: 55.1%
- **MAE**: 5.58

#### Performance by Confidence Tier

| Confidence Tier | Win Rate | Status |
|----------------|----------|--------|
| 86-88% | 58.2% | ✅ OK |
| 80-86% | 54.9% | ✅ OK |
| <80% | 55.3% | ✅ OK |

**Verdict**: All tiers profitable, no filtering needed

#### Performance by Recommendation Type

| Type | Win Rate |
|------|----------|
| UNDER | 68.3% |
| OVER | 60.9% |

**Strength**: Balanced OVER/UNDER performance

---

### 5. Similarity Balanced V1 (Rule-based)

#### System Information
- **System ID**: `similarity_balanced_v1`
- **Type**: Rule-based (Case-based reasoning)
- **Algorithm**: Find similar historical games, average outcomes
- **Similarity Factors**: Opponent, rest, recent form, home/away

#### Training Data
- **Training Period**: N/A (uses last 30 games per player)
- **Lookback**: 90 days, max 30 games
- **Live Data**: player_game_summary table

#### Performance (Jan 1-15, Real Lines)
- **Games**: 512
- **Win Rate**: 52.9%
- **MAE**: 5.65

#### Performance by Confidence Tier

| Confidence Tier | Win Rate | Status |
|----------------|----------|--------|
| 92%+ | 54.4% | ✅ OK |
| 90-92% | 57.1% | ✅ OK |
| 88-90% | 50.0% | ⚠️ Breakeven |
| 80-86% | 54.0% | ✅ OK |
| <80% | 60.4% | ✅ Good |

**Verdict**: No filtering needed (but 88-90% marginal)

---

### 6. Zone Matchup V1 (Rule-based)

#### System Information
- **System ID**: `zone_matchup_v1`
- **Type**: Rule-based (Shot zone analysis)
- **Algorithm**: Analyze player shot zones vs team defense zones
- **Data Source**: player_shot_zone_analysis, team_defense_zone_analysis

#### Training Data
- **Training Period**: N/A (uses live precompute data)
- **Data Source**: Phase 4 precompute tables

#### Performance (Jan 1-15, Real Lines)
- **Games**: 708
- **Win Rate**: 54.4%
- **MAE**: 6.16

#### Performance by Confidence Tier
- All predictions in <80% tier
- Win Rate: 55.4%
- Status: ✅ OK

#### Performance by Recommendation Type

| Type | Win Rate |
|------|----------|
| UNDER | 64.2% |
| OVER | 64.7% |

**Strength**: Balanced performance

---

### 7. Moving Average (Statistical Baseline)

#### System Information
- **System ID**: `moving_average`
- **Type**: Statistical Baseline
- **Algorithm**: Simple rolling average
- **Features**: Basic recent game stats

#### Training Data
- **Training Period**: N/A (rolling calculation)
- **Window**: Recent games

#### Performance (Jan 1-15, Real Lines)
- **Games**: 677
- **Win Rate**: 55.8% **(BEST OVERALL)**
- **MAE**: 5.86

#### Performance by Confidence Tier
- All predictions in <80% tier
- Win Rate: 54.4%
- Status: ✅ OK

#### Performance by Recommendation Type

| Type | Win Rate |
|------|----------|
| UNDER | 50.2% |
| OVER | 61.3% |

**Strength**: OVER predictions

---

## Model Comparison Matrix

### Win Rate Comparison (Jan 1-15, Real Lines Only)

| System | Total Games | Win Rate | Best Confidence Tier | Best Rec Type |
|--------|------------|----------|---------------------|---------------|
| moving_average | 677 | **55.8%** | <80% (54.4%) | OVER (61.3%) |
| catboost_v8 | 668 | 55.1% | 90-92% (73.3%) | UNDER (60.3%) |
| ensemble_v1 | 663 | 55.1% | 86-88% (58.2%) | UNDER (68.3%) |
| zone_matchup_v1 | 708 | 54.4% | <80% (55.4%) | OVER (64.7%) |
| similarity_balanced_v1 | 512 | 52.9% | <80% (60.4%) | OVER (58.8%) |
| xgboost_v1 | 0 | N/A | N/A | N/A |
| moving_average_baseline_v1 | 0 | N/A | N/A | N/A |

### MAE Comparison (Lower is better)

| System | MAE | Best Tier MAE |
|--------|-----|---------------|
| catboost_v8 (92%+) | 6.41 | **3.05** |
| ensemble_v1 | 5.58 | 4.43 |
| similarity_balanced_v1 | 5.65 | 4.63 |
| moving_average | 5.86 | 5.76 |
| zone_matchup_v1 | 6.16 | 6.45 |

### Volume Comparison

| System | Picks/Day | Coverage |
|--------|-----------|----------|
| zone_matchup_v1 | ~99 | Highest |
| catboost_v8 | ~93 | High |
| moving_average | ~95 | High |
| ensemble_v1 | ~92 | High |
| similarity_balanced_v1 | ~71 | Medium |
| xgboost_v1 | N/A | Unknown |
| moving_average_baseline_v1 | N/A | Unknown |

---

## Performance Trends

### Historical Performance Timeline

**November 2025** (catboost_v8 only, others not tracked):
- catboost_v8: 84.4% win rate (peak performance)

**December 2025**:
- catboost_v8: 82.0% win rate (excellent)

**January 1-7, 2026**:
- catboost_v8: 66.4% win rate (declining)

**January 8-15, 2026** (all systems, real lines):
- moving_average: 55.8% (champion)
- catboost_v8: 55.1% (tied 2nd)
- ensemble_v1: 55.1% (tied 2nd)
- zone_matchup_v1: 54.4%
- similarity_balanced_v1: 52.9%

**Observation**: CatBoost V8 degraded from 82% (Dec) to 55% (Jan 8-15), but recovered to 63% on Jan 15.

---

## Retraining Decision Matrix

### When to Retrain CatBoost V8

**Triggers**:
- Win rate < 55% for 7+ consecutive days
- MAE > 7.0 for 7+ consecutive days
- Confidence calibration degrades (high conf performs worse than low)
- Market adaptation detected (lines adjusting to predictions)

**Current Status**: Monitor closely
- Jan 15 win rate: 63.0% (recovery signal)
- If sustains 60%+ through Jan 20, no retraining needed
- If drops below 55% again, schedule retraining

### When to Retrain XGBoost V1

**Cannot retrain until**:
- Fix line fetching issue
- Gather 30+ days of valid data with real lines
- Establish baseline performance metrics

**Training Data Needed**:
- Document training period
- Document training games count
- Document validation methodology
- Document expected performance (MAE, win rate)

### General Retraining Guidelines

**Frequency**: Quarterly (every 3 months) or when triggered
**Data Window**: Most recent 2-3 seasons
**Validation**: Out-of-sample testing on most recent month
**Acceptance Criteria**:
- New model MAE < Old model MAE
- New model win rate ≥ Old model win rate
- New model confidence calibration ≥ Old model

---

## System Rankings by Use Case

### Best for High-Confidence Picks
1. **catboost_v8** (92%+ conf): 71.8% win rate
2. **catboost_v8** (90-92% conf): 73.3% win rate
3. All others: <60% at high confidence

**Recommendation**: Use catboost_v8 for premium picks

### Best for Volume
1. **zone_matchup_v1**: 708 picks, 54.4% win rate
2. **catboost_v8**: 668 picks, 55.1% win rate
3. **moving_average**: 677 picks, 55.8% win rate

**Recommendation**: Combine all three for maximum coverage

### Best for UNDER Picks
1. **ensemble_v1**: 68.3% win rate
2. **zone_matchup_v1**: 64.2% win rate
3. **catboost_v8**: 60.3% win rate

### Best for OVER Picks
1. **zone_matchup_v1**: 64.7% win rate
2. **moving_average**: 61.3% win rate
3. **ensemble_v1**: 60.9% win rate

---

## Action Items & Next Steps

### Immediate (Today)
- [x] Document current system performance
- [ ] Fix xgboost_v1 and moving_average_baseline_v1 line issues
- [ ] Delete invalid Jan 9-10 data

### Short-term (This Week)
- [ ] Gather 7 days of valid xgboost_v1 data
- [ ] Revalidate all systems with real lines only
- [ ] Update performance tracking dashboard

### Medium-term (This Month)
- [ ] Document training data for all ML systems
- [ ] Create model retraining schedule
- [ ] Implement automated performance tracking
- [ ] Decision on catboost_v8 retraining (if needed)

### Long-term (This Quarter)
- [ ] Quarterly model retraining (if triggered)
- [ ] Evaluate new ML architectures
- [ ] Consider ensemble optimization
- [ ] Review and update system rankings

---

## Document Maintenance

**Update Frequency**: Weekly (every Monday)
**Owner**: ML Team
**Reviewers**: Data Science, Engineering
**Version Control**: Track changes in git

**Weekly Update Checklist**:
- [ ] Update performance metrics for past week
- [ ] Check for confidence tier degradation
- [ ] Review OVER/UNDER performance splits
- [ ] Update system rankings if changed
- [ ] Flag systems needing retraining
- [ ] Document any deployments or changes

---

**Document Version**: 1.0
**Last Updated**: 2026-01-16
**Next Update**: 2026-01-23
**Status**: ✅ COMPLETE - READY FOR USE
