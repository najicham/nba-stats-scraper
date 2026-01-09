# ML Model Improvement Journey

## Timeline Visualization

```
Mock Baseline (4.80 MAE)
         │
         │ ML infrastructure investment
         ▼
v5 XGBoost (4.63 MAE) ❌ FAILED
         │ • 21 features (incomplete data, 77-89% coverage)
         │ • Overfitting: train/test gap = 0.49
         │
         │ Fixed: game_id format, feature extraction
         ▼
v6 XGBoost (4.14 MAE) ✓ FUNCTIONAL [-13.8% vs mock]
         │ • 25 features (100% coverage)
         │ • Reduced overfitting: gap = 0.18
         │
         │ Added: Vegas betting lines as features
         ▼
v7 Stacked (3.88 MAE) ✓ GOOD [-19.2% vs mock]
         │ • 31 features (+6 Vegas features)
         │ • XGBoost + LightGBM + CatBoost ensemble
         │
         │ Added: Minutes/PPM history ← BREAKTHROUGH
         ▼
v8 Stacked (3.40 MAE) ✓✓ BEST [-29.1% vs mock]
         │ • 33 features (+2 minutes/PPM)
         │ • Same ensemble architecture
         │
         │ Tested: Injury data (didn't help)
         ▼
v9 (3.41 MAE) ⚠️ NO IMPROVEMENT
         │ • +1 injury feature (2.6% coverage only)
         │
         │ Tested: Star-specific models
         ▼
v10 (3.54 MAE) ❌ WORSE
         • Star/tier segmentation caused overfitting
```

---

## Detailed Progression

### Version 5: First Real Attempt (FAILED)
**MAE**: 4.63 (worse than mock!)

**What went wrong**:
- game_id format mismatch caused usage_rate to have only 47% coverage
- Feature coverage was 77-89% (incomplete historical data)
- Severe overfitting: train MAE 4.14, test MAE 4.63 (gap: 0.49)

**Lesson**: Data quality > model complexity

---

### Version 6: Fixed Foundation (SUCCESS)
**MAE**: 4.14 (-13.8% vs mock)

**What changed**:
- Fixed game_id format (usage_rate → 95% coverage)
- Complete feature extraction (100% coverage)
- Added regularization (reduced train/test gap to 0.18)

**Features**: 25 from ml_feature_store_v2

---

### Version 7: Vegas Integration (SUCCESS)
**MAE**: 3.88 (-6.3% improvement over v6)

**What changed**:
- Added Vegas betting lines as features
- Implemented stacked ensemble (XGBoost + LightGBM + CatBoost)

**New features** (6):
- `vegas_points_line`, `vegas_opening_line`
- `vegas_line_movement`, `vegas_line_indicator`
- `points_avg_vs_opponent`, `games_vs_opponent`

**Why Vegas helps**: Lines incorporate injury/lineup info we don't have

---

### Version 8: The Breakthrough (BEST)
**MAE**: 3.40 (-12.3% improvement over v7)

**What changed**:
- Added minutes per minute and points per minute history

**New features** (2):
- `ppm_avg_last_10` - points per minute efficiency (14.6% importance!)
- `minutes_avg_last_10` - playing time trends (10.9% importance!)

**Why this worked**:
- Captures coach rotation decisions
- Identifies increasing/decreasing roles
- Complements recent points averages with efficiency context

---

### Version 9: Injury Attempt (NO IMPROVEMENT)
**MAE**: 3.41 (+0.01, essentially same)

**What was tested**:
- `teammate_injury_count` - marginal importance (1.2%)
- `player_injury_status` - negligible (0.1%)

**Why it didn't help**:
- Only 2.6% of games have injury report entries
- Historical injury data lacks real-time game-day decisions
- Model already indirectly captures injury impact via Vegas lines

---

### Version 10: Star-Specific Models (WORSE)
**MAE**: 3.54+ (worse than baseline)

**What was tested**:
- Separate models for Star/Starter/Role/Bench tiers
- Individual models for top 30 scorers
- Star-tuned hyperparameters

**Why it failed**:
- Not enough data per segment → overfitting
- Lost transfer learning from full dataset
- Unified model already captures player-specific patterns

---

## What Worked vs What Didn't

### Worked
| Approach | Impact | Key Insight |
|----------|--------|-------------|
| Complete feature data | -13.8% MAE | Data quality > model complexity |
| Vegas lines as features | -6.3% MAE | Market captures info we lack |
| Minutes/PPM history | -12.3% MAE | Efficiency + role trends matter |
| Stacked ensemble | -0.5% MAE | Small but consistent gain |
| Proper regularization | Reduced gap 0.49→0.18 | Prevents overfitting |

### Didn't Work
| Approach | Result | Why |
|----------|--------|-----|
| Two-stage model | +0.14 MAE | Architecture complexity unnecessary |
| Injury data | +0.01 MAE | Low coverage (2.6%) |
| Star-specific models | +0.14 MAE | Overfitting, lost transfer learning |
| Tier segmentation | ~0 MAE | Features already capture this |
| Hyperparameter tuning | -0.01 MAE | Diminishing returns |
| Mock improvements | +0.02 MAE | Already near-optimal |

---

## Key Learnings

1. **Data quality is foundational** - v5 failed purely due to incomplete data
2. **Simple features can be powerful** - minutes/PPM history was the biggest gain
3. **Vegas is a feature, not a competitor** - use market consensus as input
4. **Specialization hurts** - unified models beat segmented approaches
5. **Theoretical floor exists** - ~3.0-3.2 MAE based on player variance
6. **Know when to stop** - 3.40 MAE is likely within 0.2-0.4 of optimal
