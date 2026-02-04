# Investigation Findings - Session 107

**Date:** 2026-02-03
**Investigators:** 5 parallel agents analyzing different aspects

## Summary

Five concurrent investigations revealed multiple interconnected causes for the regression-to-mean bias in CatBoost V9.

## Investigation 1: Feature Store December Quality

**Agent Focus:** Spot-check feature accuracy for December 2025

### Key Findings

1. **Feature store has 37 features** per player-game (not 33 as sometimes documented)

2. **Dec 21 anomaly:** 60.2% of players (311/517) had only 33 features - missing trajectory features (`dnp_rate`, `pts_slope_10g`, `pts_vs_season_zscore`, `breakout_flag`)

3. **Quality by tier:**

   | Tier | Avg Quality | Zero pts_avg_last_5 | Vegas Coverage |
   |------|-------------|---------------------|----------------|
   | Star | 84.1 | 0.0% | 86.2% |
   | Starter | 84.4 | 3.1% | 76.6% |
   | Rotation | 84.3 | 1.0% | 75.3% |
   | Bench | **80.4** | **27.3%** | **28.6%** |

4. **Cache timing bug:** Feature averages may use post-game cache instead of pre-game cache, causing ~1 point discrepancy

5. **Injury data not captured:** All players show `injury_risk = 0` despite some being questionable/doubtful

---

## Investigation 2: Feature Store November Cold Start

**Agent Focus:** Compare November (season start) to December patterns

### Key Findings

1. **Feature count changed Nov 13:**
   - Nov 2-12: 33 features
   - Nov 13+: 37 features (added 4 trajectory features)

2. **Critical default value issue:**

   | Date | Records with Default (10.0) | Percentage |
   |------|----------------------------|------------|
   | Nov 4 | 76 | **35.2%** |
   | Nov 5 | 80 | **20.7%** |
   | Nov 6 | 6 | 17.6% |
   | Nov 7 | 11 | 2.9% |

3. **Specific examples of wrong defaults:**
   - Josh Giddey (Nov 4): `points_avg_last_5=10.0`, actual L10=23.25 (**wrong by 13.25 pts**)
   - Nikola Vucevic (Nov 4): `points_avg_last_5=10.0`, actual L10=18.25 (**wrong by 8.25 pts**)

4. **Vegas lines completely missing Nov 5-12:**
   - Nov 4: 25.5% coverage
   - **Nov 5-12: 0.0% coverage** (8 days!)
   - Nov 13+: 20-43% coverage

5. **Quality score progression:**
   | Period | Avg Quality | Avg Features |
   |--------|-------------|--------------|
   | Early Nov | 74.2 | 34.0 |
   | Late Nov | 82.3 | 37.0 |
   | December | 83.2 | 36.8 |

---

## Investigation 3: Star Prediction Error Patterns

**Agent Focus:** Analyze high-error predictions for star players

### Key Findings

1. **Massive predicted vs actual mismatch for 25+ scorers:**

   | Predicted Range | Count | Percentage |
   |-----------------|-------|------------|
   | < 25 pts | 142 | **69%** |
   | 25-29 pts | 46 | 22% |
   | 30+ pts | 18 | 9% |

   When players scored 25+, model predicted <25 in 69% of cases.

2. **UNDER recommendations on stars are catastrophic:**

   | Edge | OVER Win Rate | UNDER Win Rate |
   |------|---------------|----------------|
   | 5+ | **100%** (15/15) | 31% (5/16) |
   | 3-5 | **100%** (13/13) | 16% (5/32) |
   | <3 | 91% (42/46) | 12% (10/84) |

3. **Repeat offenders:**

   | Player | Errors | Avg Predicted | Avg Actual | Avg Miss |
   |--------|--------|---------------|------------|----------|
   | Luka Doncic | 7 | 29.6 | 37.4 | 9.6 |
   | Alperen Sengun | 3 | 18.3 | 32.3 | 14.1 |
   | Julius Randle | 4 | 19.6 | 31.5 | 11.8 |
   | Tyrese Maxey | 4 | 23.6 | 34.5 | 10.9 |

4. **Breakout game vulnerability:** Low-line players exploding (e.g., Jaylon Tyson: line 13.4, predicted 11.1, actual 39)

5. **Opponent patterns:** Charlotte, Memphis, Houston games have highest error rates (weak defense)

---

## Investigation 4: Feature Completeness Hypothesis

**Agent Focus:** Do missing features cause scoring correlation?

### Key Findings

1. **Default values are LOW, not high:**
   | Feature | Default Value |
   |---------|---------------|
   | points_avg_last_5/10/season | **10.0** |
   | ppm_avg_last_10 | **0.4** |
   | minutes_avg_last_10 | 28.0 |

   This means missing features → model predicts lower, not higher.

2. **Vegas line coverage is the key differentiator:**
   - Stars: ~95% have Vegas lines
   - Bench: ~15-40% have Vegas lines
   - `has_vegas_line = 1.0` becomes proxy for "is star"

3. **Quality score correlation:**
   - Stars: quality ~95+
   - Bench: quality ~70-80 (more defaults used)

4. **Shot zone features use NULL/NaN** (not defaults), allowing CatBoost to handle natively

5. **The mechanism:**
   - Model learns: "complete features + Vegas line = higher scorer"
   - But can't distinguish 20-pt starter from 35-pt superstar
   - Both look "complete" so both regress toward same range

---

## Investigation 5: Training Data and Model Configuration

**Agent Focus:** Understand why model regresses to mean

### Key Findings

1. **Training data distribution is extremely imbalanced:**

   | Point Range | Samples | Percentage |
   |-------------|---------|------------|
   | 0-10 | 47,307 | **57.2%** |
   | 11-20 | 23,522 | 28.4% |
   | 21-30 | 9,083 | 11.0% |
   | 30+ | 2,794 | **3.4%** |

   **Training mean: ~10.7 points**

2. **By player tier:**

   | Tier | Samples | Percentage |
   |------|---------|------------|
   | Stars (20+ ppg) | 7,990 | **9.7%** |
   | Starters | 19,205 | 23.2% |
   | Role | 33,522 | 40.5% |
   | Bench | 21,989 | **26.6%** |

3. **L2 regularization causes shrinkage:**
   - CatBoost: `l2_leaf_reg=3.8`
   - XGBoost: `reg_lambda=5.0`
   - These naturally pull predictions toward training mean

4. **Top features by correlation:**
   | Feature | Correlation with actual |
   |---------|------------------------|
   | points_avg_last_10 | **+0.739** |
   | points_avg_season | **+0.726** |
   | points_avg_last_5 | **+0.725** |
   | vegas_points_line | ~+0.7 (est) |

5. **No post-prediction calibration:**
   ```python
   'calibration_method': 'none'  # From catboost_v8.py
   ```

6. **Vegas itself is biased:**
   | Tier | Vegas Avg | Actual Avg | Vegas Bias |
   |------|-----------|------------|------------|
   | Star | ~26 | ~32 | **-6** |
   | Bench | ~7 | ~3 | +4 |

---

## Synthesis: The Complete Picture

```
Root Cause Chain:

1. TRAINING DATA (57% low scorers, mean=10.7)
           ↓
2. COLD START (Nov 2-12: wrong defaults, no Vegas)
           ↓
3. MODEL LEARNS:
   - "Default features (10.0) = low scorer"
   - "Complete features + Vegas = higher scorer"
   - "But regress toward 10.7 mean due to L2 regularization"
           ↓
4. VEGAS FOLLOWING:
   - Model follows Vegas closely (0.7+ correlation)
   - Vegas under-predicts stars by ~6 pts
   - Model inherits this bias
           ↓
5. PREDICTION OUTPUT:
   - Star should score 32 → Model predicts 22 → UNDER bet
   - Bench should score 3 → Model predicts 8 → UNDER bet still (correctly)
           ↓
6. RESULT:
   - Star UNDERs lose 69% of time
   - High-edge UNDER hit rate: 31%
   - 6 consecutive RED signal days
```

---

## Data Quality Timeline

| Date Range | Issues | Impact |
|------------|--------|--------|
| Nov 2-6 | 35% wrong defaults | Model learns bad patterns |
| Nov 5-12 | 0% Vegas coverage | Most important feature missing |
| Nov 2-12 | 33 features | Missing trajectory features |
| Nov 13+ | Clean data | But damage already done |
| Dec 21 | 60% missing trajectory | One-day anomaly |

---

## Files Referenced

| Investigation | Key Files |
|---------------|-----------|
| Feature store | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` |
| Defaults | `ml_feature_store_processor.py` lines 1548-1656 |
| Training | `ml/train_final_ensemble_v8.py`, `ml/train_final_ensemble_v9.py` |
| Predictor | `predictions/worker/prediction_systems/catboost_v8.py` |
| Quality scoring | `data_processors/precompute/ml_feature_store/quality_scorer.py` |
| Data report | `ml/reports/COMPREHENSIVE_DATA_QUALITY_REPORT.md` |
| Prior investigations | `docs/08-projects/current/feature-mismatch-investigation/` |

---

## Recommended Reading

1. `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`
2. `docs/08-projects/current/model-bias-investigation/TIER-FEATURES-VS-MISSING-FEATURES.md`
3. `ml/reports/COMPREHENSIVE_DATA_QUALITY_REPORT.md`
