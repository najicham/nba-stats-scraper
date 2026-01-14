# MLB Pitcher Strikeouts - Complete Implementation Handoff

**Date**: 2026-01-07
**Status**: V2 Features Complete, ML Pipeline Not Started
**Priority**: Build ML training and prediction infrastructure for MLB season (starts late March 2026)

---

## EXECUTIVE SUMMARY

### What's Done
- **35-feature vector** implemented with MLB-specific bottom-up K model
- **28 scrapers** ready (ahead of NBA's 27)
- **5 new BigQuery tables** for V1/V2 features
- **2 precompute processors** (pitcher_features, lineup_k_analysis)
- **31 unit tests** passing

### What's Missing (vs NBA Parity)
- **Training infrastructure** - No ML training script exists
- **Prediction workers** - No prediction systems (NBA has 5)
- **Grading pipeline** - No accuracy tracking
- **Orchestration** - No Cloud Functions for MLB predictions
- **Historical data** - All tables are EMPTY

### Critical Blocker
**No training data.** Tables exist but are empty. Cannot train ML model or validate the bottom-up K formula without 2024 season data.

---

## CURRENT STATE: MLB vs NBA COMPARISON

### Infrastructure Comparison

| Component | NBA Status | MLB Status | Gap |
|-----------|------------|------------|-----|
| **Scrapers** | 27 | 28 | MLB ahead |
| **Raw Tables** | 18 | 22+ | MLB ahead |
| **Analytics Tables** | 6 (254 fields) | 2 (80 fields) | Medium gap |
| **Precompute Tables** | 7 | 5 | Small gap |
| **Feature Vector** | 25 features | 35 features | MLB ahead |
| **Data Population** | 3+ seasons | **EMPTY** | **CRITICAL** |
| **ML Training** | XGBoost V4 live | Not started | Large gap |
| **Prediction Workers** | 5 systems | 0 | Large gap |
| **Grading Pipeline** | Complete | 0 | Large gap |
| **Orchestration** | Full Cloud Functions | 0 | Large gap |

### What MLB Has That NBA Doesn't

**The Bottom-Up K Model** (f25_bottom_up_k_expected):
```
MLB: Pitcher Ks = SUM(batter_i_K_rate × expected_ABs_i) for all 9 batters
```

This is **deterministic** because we KNOW the exact lineup before the game. NBA predictions are probabilistic (unknown defensive matchups).

### Files Implemented

```
data_processors/precompute/mlb/
├── pitcher_features_processor.py      # 35-feature vector (V2)
├── lineup_k_analysis_processor.py     # Bottom-up K calculation
└── __init__.py

schemas/bigquery/mlb_precompute/
└── ml_feature_store_tables.sql        # Updated for 35 features

tests/processors/precompute/mlb/
├── lineup_k_analysis/test_unit.py     # 9 tests
└── pitcher_features/test_unit.py      # 22 tests
```

### BigQuery Tables Created

| Table | Dataset | Purpose |
|-------|---------|---------|
| `pitcher_ml_features` | mlb_precompute | 35-feature vector storage |
| `lineup_k_analysis` | mlb_precompute | Bottom-up K per game |
| `pitcher_innings_projection` | mlb_precompute | Expected IP |
| `pitcher_arsenal_summary` | mlb_precompute | Velocity, whiff rates |
| `batter_k_profile` | mlb_precompute | Batter K vulnerability |
| `umpire_game_assignment` | mlb_raw | Umpire K tendencies |

---

## WHAT NEEDS TO BE BUILT

### 1. ML Training Infrastructure

**NBA Has**: `ml/train_real_xgboost.py`
- 8-phase training pipeline
- Chronological train/val/test split
- Feature importance analysis
- Model versioning with metadata
- GCS storage for models

**MLB Needs**: `ml/train_pitcher_strikeouts_xgboost.py`

```python
# Structure to implement:
Phase 1: Extract training data from BigQuery (35 features)
Phase 2: Feature validation (check for nulls, outliers)
Phase 3: Chronological split (70/15/15)
Phase 4: Train XGBoost with hyperparameters
Phase 5: Evaluate (MAE, RMSE, within-1K accuracy)
Phase 6: Compare to baseline (bottom-up formula alone)
Phase 7: Feature importance analysis
Phase 8: Save model + metadata to GCS

# Target metrics:
- MAE < 1.5 strikeouts (NBA equivalent: 4.27 points MAE)
- Within-1K accuracy > 50%
- Within-2K accuracy > 75%
```

### 2. Prediction Workers (5 systems)

**NBA Has**: `predictions/worker/prediction_systems/`
- moving_average_baseline.py
- zone_matchup_v1.py
- similarity_balanced_v1.py
- xgboost_v1.py
- ensemble_v1.py

**MLB Needs**: `predictions/worker/prediction_systems/pitcher_strikeouts/`

| System | Purpose | Priority |
|--------|---------|----------|
| `strikeout_baseline.py` | Rolling K averages + context | P0 |
| `batter_matchup_v1.py` | Lineup K rates vs pitcher hand | P0 |
| `similar_pitcher_v1.py` | Find similar historical starts | P1 |
| `xgboost_pitcher_v1.py` | ML model with 35 features | P0 |
| `ensemble_pitcher_v1.py` | Weighted average of systems | P0 |

**Also Need**:
- `predictions/worker/pitcher_worker.py` - Flask app for Cloud Run
- `predictions/coordinator/pitcher_coordinator.py` - Batch orchestration

### 3. Grading Pipeline

**NBA Has**: `data_processors/grading/prediction_accuracy/`
- Compares predictions to actuals
- Tracks MAE, accuracy rates
- Writes to `prediction_accuracy` table

**MLB Needs**: `data_processors/grading/strikeout_accuracy/`

```python
# Metrics to track:
- absolute_error: |predicted_k - actual_k|
- prediction_correct: Did OVER/UNDER hit the line?
- within_1_k, within_2_k, within_3_k: Accuracy thresholds
- rate_adjusted_error: Account for IP variance (short outings)
```

### 4. Orchestration (Cloud Functions)

**NBA Has**:
- `phase4_to_phase5/` - Trigger predictions
- `phase5_to_phase6/` - Validate predictions ready
- `grading/` - Grade after games complete

**MLB Needs**:
- `phase4_to_phase5_mlb/` - Trigger pitcher predictions
- `phase5_to_phase6_mlb/` - Validate pitcher predictions
- `grading_mlb/` - Grade strikeout predictions

---

## OPEN QUESTIONS FOR ML TRAINING

### Data Questions

1. **How much historical data do we need?**
   - NBA uses 70,000+ games (2021-2024)
   - MLB: ~5,400 pitcher starts per season × 3 seasons = 16,200 samples
   - Recommendation: 2022-2024 seasons minimum (3 years)

2. **What's the minimum viable training set?**
   - One full season (2024) = ~5,400 samples
   - This is enough for initial model, but 3 seasons preferred

3. **Do we have access to historical lineups?**
   - MLB Stats API provides current/scheduled only
   - May need to scrape historical lineups separately
   - Alternative: Use team-level K rates instead of per-batter

4. **What about odds data?**
   - Odds API historical endpoints cost $$$
   - Can train without odds initially
   - Add betting line features later

### Feature Questions

1. **Which of the 35 features are most important?**
   - Need to run feature importance analysis
   - Hypothesis: f25 (bottom_up_k_expected) is dominant
   - May be able to simplify to 15-20 key features

2. **Should we use f25 as-is or let ML learn the relationship?**
   - Option A: Include f25 as a feature (let ML adjust)
   - Option B: Use bottom-up as baseline, ML predicts residual
   - Recommendation: Start with Option A

3. **How do we handle missing data?**
   - New batters with no K rate history
   - Pitchers with few starts
   - Recommendation: League average fallbacks

### Model Questions

1. **XGBoost vs other algorithms?**
   - NBA uses XGBoost successfully
   - Recommendation: Start with XGBoost, same hyperparameters
   - Consider LightGBM later for comparison

2. **How often to retrain?**
   - NBA retrains monthly
   - MLB: Weekly during season (sample size grows fast)
   - Pre-season: Use prior year data

3. **How to handle pitcher injuries/IL stints?**
   - Long IL stints = stale features
   - Recommendation: Decay weights for old data
   - Flag low-confidence predictions for returning pitchers

### Infrastructure Questions

1. **Separate GCS bucket for MLB models?**
   - Current: `gs://nba-scraped-data/ml-models/`
   - Options:
     - Same bucket, `/ml-models-mlb/` prefix
     - New bucket: `gs://mlb-scraped-data/ml-models/`
   - Recommendation: Same bucket, different prefix

2. **Separate BigQuery datasets confirmed?**
   - Yes: `mlb_raw`, `mlb_analytics`, `mlb_precompute`, `mlb_predictions`

3. **Pub/Sub topics for MLB?**
   - Need: `mlb-prediction-request`, `mlb-grading-trigger`
   - Already configured in `shared/config/pubsub_topics.py`

---

## PRIORITIZED ROADMAP

### Phase 1: Data Population (Week 1) - CRITICAL PATH

| Day | Task | Outcome |
|-----|------|---------|
| 1 | Install pybaseball, test BDL MLB API | Verify data access |
| 2 | Scrape 2024 pitcher game logs | TARGET variable ready |
| 3 | Scrape 2024 batter season stats | Bottom-up model input |
| 4-5 | Run analytics processors | Rolling averages populated |

**Validation**: Query `mlb_raw.bdl_pitcher_stats` returns 5,000+ rows

### Phase 2: Baseline Validation (Week 2)

| Day | Task | Outcome |
|-----|------|---------|
| 1-2 | Generate feature vectors for 2024 | Training data ready |
| 3-4 | Test bottom-up formula vs actuals | Baseline MAE established |
| 5 | Document baseline accuracy | Know if ML will help |

**Validation**: Bottom-up formula MAE calculated (target: < 2.0)

### Phase 3: ML Training (Week 3)

| Day | Task | Outcome |
|-----|------|---------|
| 1-2 | Create training script | `ml/train_pitcher_strikeouts_xgboost.py` |
| 3 | Run initial training | First model saved |
| 4 | Feature importance analysis | Know which features matter |
| 5 | Hyperparameter tuning | Optimized model |

**Validation**: Model MAE < baseline MAE

### Phase 4: Prediction Workers (Week 4-5)

| Day | Task | Outcome |
|-----|------|---------|
| 1-3 | Create 4 prediction systems | Baseline, matchup, ML, ensemble |
| 4-5 | Create pitcher_worker.py | Flask app ready |
| 6-7 | Create pitcher_coordinator.py | Batch orchestration |
| 8-10 | Integration testing | End-to-end predictions working |

**Validation**: Can generate predictions for test date

### Phase 5: Grading & Orchestration (Week 6-7)

| Day | Task | Outcome |
|-----|------|---------|
| 1-3 | Create grading processor | Accuracy tracking |
| 4-5 | Create Cloud Functions | Automated pipeline |
| 6-7 | Schedule and test | Production-ready |

**Validation**: Full daily pipeline runs automatically

### Phase 6: Production Readiness (Week 8)

- Deploy to Cloud Run
- Set up monitoring dashboards
- Document operations procedures
- Prepare for MLB season start

---

## QUICK START FOR NEXT SESSION

### Immediate Actions

```bash
# 1. Verify pybaseball is available
pip install pybaseball

# 2. Test BDL MLB API access
SPORT=mlb PYTHONPATH=. python -c "
from scrapers.mlb.balldontlie.mlb_pitcher_stats import MlbPitcherStatsScraper
s = MlbPitcherStatsScraper()
print('Ready:', s.name)
"

# 3. Check current table state
bq query --use_legacy_sql=false "
SELECT 'pitcher_stats' as t, COUNT(*) FROM mlb_raw.bdl_pitcher_stats
UNION ALL
SELECT 'batter_stats', COUNT(*) FROM mlb_raw.bdl_batter_stats
"
```

### Copy-Paste Prompt for Next Session

```
Continue MLB pitcher strikeouts implementation.

CURRENT STATUS:
- V2 features complete (35-feature vector)
- 28 scrapers, 5 new BigQuery tables, 31 unit tests passing
- All tables are EMPTY - no historical data

IMMEDIATE PRIORITY:
Start historical data population for 2024 season:
1. Run pitcher game log scraper for 2024
2. Run batter stats scraper for 2024
3. Process through analytics layer
4. Generate feature vectors

THEN:
1. Validate bottom-up K formula accuracy
2. Create ML training script (copy from NBA's train_real_xgboost.py)
3. Train initial XGBoost model

DOCS TO READ:
- docs/09-handoff/2026-01-07-MLB-PITCHER-STRIKEOUTS-COMPLETE-HANDOFF.md
- docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md

REFERENCE:
- NBA training: ml/train_real_xgboost.py
- MLB feature processor: data_processors/precompute/mlb/pitcher_features_processor.py
```

---

## FILE REFERENCE

### Existing MLB Files

| Category | File | Status |
|----------|------|--------|
| Scrapers | `scrapers/mlb/` (28 files) | Complete |
| Raw Processors | `data_processors/raw/mlb/` (8 files) | Complete |
| Analytics Processors | `data_processors/analytics/mlb/` (2 files) | Complete |
| Precompute Processors | `data_processors/precompute/mlb/` (2 files) | Complete |
| Schemas | `schemas/bigquery/mlb_*/` | Complete |
| Tests | `tests/processors/precompute/mlb/` | Complete |

### Files to Create

| Category | File | Priority |
|----------|------|----------|
| Training | `ml/train_pitcher_strikeouts_xgboost.py` | P0 |
| Predictions | `predictions/worker/pitcher_worker.py` | P0 |
| Predictions | `predictions/worker/prediction_systems/pitcher_strikeouts/*.py` | P0 |
| Predictions | `predictions/coordinator/pitcher_coordinator.py` | P1 |
| Grading | `data_processors/grading/strikeout_accuracy/*.py` | P1 |
| Orchestration | `orchestration/cloud_functions/*_mlb/` | P2 |

---

## SUCCESS CRITERIA

### By MLB Opening Day (Late March 2026)

- [ ] Historical data populated (2022-2024 seasons)
- [ ] ML model trained with MAE < 1.5 strikeouts
- [ ] 4+ prediction systems operational
- [ ] Grading pipeline tracking accuracy
- [ ] Daily automation running
- [ ] Monitoring dashboards live

### Stretch Goals

- [ ] Ensemble outperforms any single system
- [ ] Integration with live odds for line shopping
- [ ] Batter strikeout predictions (secondary target)
- [ ] Real-time in-game K tracking

---

## CONTACTS & RESOURCES

### Documentation
- Project docs: `docs/08-projects/current/mlb-pitcher-strikeouts/`
- Architecture: `ULTRATHINK-MLB-SPECIFIC-ARCHITECTURE.md`
- Progress log: `PROGRESS-LOG.md`

### Key Decisions Made
1. **35 features** - MLB-specific bottom-up model + V2 advanced metrics
2. **Same repo** - MLB code lives alongside NBA code
3. **SPORT env var** - Controls which sport's config is active
4. **Separate datasets** - `mlb_*` BigQuery datasets

### Known Issues
1. MLB datasets created in wrong region initially (fixed)
2. pybaseball may have rate limits for historical data
3. Historical lineup data availability uncertain
