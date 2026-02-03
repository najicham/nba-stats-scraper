# Phase 6 Subset & Model Enhancement - Findings Summary

**Session**: 86
**Date**: 2026-02-02

## Executive Summary

We have two major features built in the backend that are **not exposed** to the website through Phase 6:
1. **Dynamic Subsets** - Signal-aware pick filtering (9 active subsets, 82% hit rate on GREEN days)
2. **Model Attribution** - Training metadata and model provenance (Session 84 fields exist but not exported)

## What We're Currently Pushing to Website

### Existing Phase 6 Endpoints (21 exporters)

| Endpoint | Data | Update Frequency |
|----------|------|------------------|
| `/tonight/all-players.json` | All predictions for today (~300 players) | After Phase 5 |
| `/tonight/player/{lookup}.json` | Individual player cards | After Phase 5 |
| `/predictions/{date}.json` | All predictions by game | After Phase 5 |
| `/best-bets/{date}.json` | Top 15-25 picks (basic edge threshold) | After Phase 5 |
| `/results/{date}.json` | Yesterday's graded results | 5 AM ET |
| `/systems/performance.json` | System accuracy (7/30/season windows) | Daily |
| `/live/{date}.json` | Live scores during games | Every 3 min |
| `/live-grading/{date}.json` | Real-time grading | Every 3 min |
| `/trends/whos-hot-v2.json` | Hot/cold players | Hourly |
| `/trends/bounce-back-v2.json` | Bounce-back candidates | Hourly |
| `/players/{lookup}.json` | Player profiles with history | Weekly |
| `/streaks/{date}.json` | OVER/UNDER streaks | Daily |

### What Model Info Is Currently Exported

**In `/systems/performance.json`:**
- System ID, display name, description
- Rolling metrics (win_rate, MAE, prediction_count)
- OVER/UNDER breakdown
- High confidence stats

**What's MISSING:**
- ❌ Model file name (e.g., "catboost_v9_feb_02_retrain.cbm")
- ❌ Training dates (start/end)
- ❌ Expected performance (MAE, hit rate targets)
- ❌ Feature count
- ❌ Retraining schedule
- ❌ Model provenance per prediction

---

## What We Should Be Pushing (Gaps)

### Gap 1: Subset System (NOT EXPOSED AT ALL)

**Backend Status**: ✅ Fully built (Sessions 70-71)
- 9 active dynamic subsets defined
- Daily signal calculation (GREEN/YELLOW/RED)
- Signal-aware performance tracking
- 28-point hit rate difference (82% GREEN vs 54% RED)

**Frontend Status**: ❌ No access
- Website cannot query subsets
- Cannot show signal status
- Cannot filter by subset
- Cannot display subset performance comparison

**What we need to export:**

1. **Subset Definitions** (`/systems/subsets.json`)
   - Metadata for all 9 subsets
   - Selection strategy (RANKED vs FILTERED)
   - Signal conditions (ANY, GREEN, etc.)
   - Historical performance summary

2. **Daily Signals** (`/signals/{date}.json`)
   - Today's signal status (GREEN/YELLOW/RED)
   - Signal metrics (pct_over, avg_edge, etc.)
   - Historical signal performance
   - Signal explanation for users

3. **Subset Picks** (`/subsets/{subset_id}/{date}.json`)
   - Picks from specific subset
   - Ranked by composite score
   - Signal match indicator
   - Subset metadata

4. **Subset Performance** (`/subsets/performance.json`)
   - Compare all subsets side-by-side
   - 7/30/season windows
   - Signal effectiveness breakdown
   - ROI estimates

**Impact of gap:**
- Users cannot access best-performing picks (82% hit rate on GREEN days)
- No visibility into market signals
- Missing recommended default subset (v9_high_edge_top5)
- No performance comparison between subset strategies

---

### Gap 2: Model Attribution (FIELDS EXIST, NOT EXPORTED)

**Backend Status**: ✅ Fields added (Session 84)
- `model_file_name` in predictions table
- `model_training_start_date` / `model_training_end_date`
- `model_expected_mae` / `model_expected_hit_rate`
- `model_trained_at`

**Frontend Status**: ❌ Fields not exported to JSON
- Website cannot show which model file generated prediction
- Cannot display training period
- Cannot show expected vs actual performance
- No model provenance audit trail

**What we need to export:**

1. **Model Registry** (`/systems/models.json`)
   - All production models
   - Training details (dates, samples, approach)
   - Expected performance metrics
   - Deployment info
   - Retraining schedule

2. **Enhanced System Performance** (modify `/systems/performance.json`)
   - Add `model_info` section with file name, training dates
   - Add `tier_breakdown` with premium/high-edge stats

3. **Model Attribution on Predictions** (modify `/predictions/{date}.json`)
   - Add `model_attribution` to each prediction
   - Include model file, training period, expected performance

**Impact of gap:**
- Users cannot verify which model version made prediction
- No transparency into model training
- Cannot compare expected vs actual performance
- Missing trust/transparency features

---

## Key Data Available for Export

### Subset Data (Fully Available)

**Tables:**
- `nba_predictions.dynamic_subset_definitions` - 9 active subsets
- `nba_predictions.daily_prediction_signals` - Daily signal metrics
- `nba_predictions.player_prop_predictions` - Raw predictions (filter by subset)

**Views:**
- `nba_predictions.v_dynamic_subset_performance` - Pre-aggregated performance

**Sample subset definitions:**
- `v9_high_edge_top5` - Top 5 ranked (recommended default)
- `v9_high_edge_balanced` - All high-edge on GREEN days (82% HR)
- `v9_premium_safe` - Premium confidence on safe days
- `v9_high_edge_top1` - Lock of the day
- ... 5 more

**Signal metrics:**
- `total_picks`, `high_edge_picks`, `premium_picks`
- `pct_over`, `pct_under`, `avg_confidence`, `avg_edge`
- `skew_category` (UNDER_HEAVY, BALANCED, OVER_HEAVY)
- `daily_signal` (GREEN/YELLOW/RED)
- Signal performance history (HR by color)

---

### Model Data (Partially Available)

**In BigQuery** (Session 84):
- Model attribution fields in `player_prop_predictions` table
- 6 new fields per prediction: file name, training dates, expected performance

**In Code** (`predictions/worker/prediction_systems/*.py`):
- `TRAINING_INFO` dicts with full model metadata
- Training approach, feature count, model file paths
- Expected MAE, hit rate targets

**Current production model (CatBoost V9):**
- File: `catboost_v9_feb_02_retrain.cbm`
- Training: Nov 2, 2025 → Jan 31, 2026 (91 days)
- Features: 33 (v2_33features)
- Expected MAE: 4.12
- Expected High-Edge HR: 74.6%
- Expected Premium HR: 56.5%
- Training samples: ~180,000
- Approach: Current season only

---

## Implementation Priority

### Priority 1: Subsets (High Impact, Low Risk)
- **Impact**: Expose 82% hit rate picks (GREEN days)
- **Effort**: 4 new exporters + orchestration changes
- **Risk**: Low (all data exists, well-tested queries)
- **Value**: Immediate user benefit, differentiated feature

**Recommended endpoints:**
1. `/systems/subsets.json` - List all subsets
2. `/signals/{date}.json` - Daily signal status
3. `/subsets/{subset_id}/{date}.json` - Subset picks
4. `/subsets/performance.json` - Performance comparison

---

### Priority 2: Model Attribution (Transparency, Medium Effort)
- **Impact**: Trust, transparency, audit trail
- **Effort**: 1 new exporter + 3 modified exporters
- **Risk**: Low (fields exist, just need to export)
- **Value**: Builds user trust, enables model comparison

**Recommended changes:**
1. Create `/systems/models.json` - Model registry
2. Enhance `/systems/performance.json` - Add model_info, tier_breakdown
3. Modify `/predictions/{date}.json` - Add model_attribution
4. Modify `/best-bets/{date}.json` - Add model_attribution

---

## Example Usage Scenarios

### Scenario 1: User Wants "Best Picks for Today"

**Current experience:**
- Visit `/best-bets/{date}.json`
- Get top 15-25 picks (basic edge threshold)
- No signal awareness
- No subset filtering
- ~55% hit rate

**Improved experience:**
- Check `/signals/2026-02-02.json` → "GREEN signal day"
- Visit `/subsets/v9_high_edge_balanced/2026-02-02.json`
- Get ~12 high-edge picks filtered for GREEN days
- **82% expected hit rate** vs 55% current

**Value**: 27-point hit rate improvement

---

### Scenario 2: User Wants to Compare Subset Strategies

**Current experience:**
- Not possible - no subset data exposed

**Improved experience:**
- Visit `/subsets/performance.json`
- See all 9 subsets compared:
  - Top 1 (Lock): 5 picks/day, 76% HR
  - Top 5 (Default): 5 picks/day, 75% HR
  - Balanced (GREEN only): 12 picks/day, 82% HR
  - Premium Safe: 8 picks/day, 71% HR
- Choose strategy based on risk tolerance

**Value**: Personalized strategy selection

---

### Scenario 3: User Questions Prediction Quality

**Current experience:**
- See prediction: "LeBron OVER 24.5, conf 92%"
- No model info
- No training context
- Cannot verify which model version

**Improved experience:**
- See prediction with model attribution:
  - "Generated by: catboost_v9_feb_02_retrain.cbm"
  - "Model trained: Nov 2, 2025 - Jan 31, 2026"
  - "Expected accuracy: 74.6% (high-edge picks)"
  - "Model MAE: 4.12 points"
- Visit `/systems/models.json` for full model details

**Value**: Trust, transparency, audit trail

---

## Next Steps

1. **Review Implementation Plan** - See `IMPLEMENTATION_PLAN.md` for detailed specs
2. **Prioritize features** - Subsets (Priority 1) vs Model Attribution (Priority 2)
3. **Answer clarification questions**:
   - Export all 9 subsets or just top 3-4?
   - How many days of historical signals to backfill?
   - Cache TTL for new endpoints?
4. **Begin implementation** - Start with subset infrastructure
5. **Test with website team** - Validate JSON structure meets frontend needs

---

## Data Sources Summary

### For Subsets
```sql
-- Subset definitions
SELECT * FROM nba_predictions.dynamic_subset_definitions WHERE is_active = TRUE;

-- Daily signals
SELECT * FROM nba_predictions.daily_prediction_signals WHERE game_date = CURRENT_DATE();

-- Subset picks (example: top 5)
SELECT p.*, (ABS(predicted_points - current_points_line) * 10 + confidence_score * 0.5) as score
FROM nba_predictions.player_prop_predictions p
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
  AND ABS(predicted_points - current_points_line) >= 5
ORDER BY score DESC LIMIT 5;

-- Subset performance
SELECT * FROM nba_predictions.v_dynamic_subset_performance
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
```

### For Model Attribution
```sql
-- Model metadata from predictions table (Session 84 fields)
SELECT DISTINCT model_file_name, model_training_start_date, model_training_end_date,
  model_expected_mae, model_expected_hit_rate, model_trained_at
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE;

-- Also read from code: predictions/worker/prediction_systems/catboost_v9.py (TRAINING_INFO)
```

---

## Questions to Answer Before Implementation

1. **Subset scope**: Export all 9 subsets or prioritize top 3-4?
   - Recommendation: All 9 (small overhead, enables comparison)

2. **Historical depth**: Backfill how many days of `/signals/{date}.json`?
   - Recommendation: 7 days (1 week of signal history)

3. **Cache TTL**: What caching for new endpoints?
   - Recommendation:
     - `/systems/subsets.json`: 1 day (rarely changes)
     - `/signals/{date}.json`: 5 minutes (static after generation)
     - `/subsets/{subset_id}/{date}.json`: 5 minutes
     - `/subsets/performance.json`: 1 hour (pre-aggregated)
     - `/systems/models.json`: 1 day (changes monthly)

4. **Model info source**: Code (TRAINING_INFO) or BigQuery only?
   - Recommendation: Combine both (code for comprehensive metadata, BQ for deployment tracking)

5. **Tier definitions**: Hardcode premium/high-edge or make configurable?
   - Recommendation: Hardcode initially (matches CLAUDE.md standards), make configurable later if needed

---

## Success Criteria

### Functional
- [ ] All 9 subsets have picks exported daily
- [ ] Signal data matches database calculations
- [ ] Model attribution fields populated from Session 84 work
- [ ] Performance metrics match BigQuery views
- [ ] Exports complete within 5 minutes

### Business Value
- [ ] Website can display subset picks with 82% hit rate (GREEN days)
- [ ] Users can compare subset strategies
- [ ] Model provenance visible on every prediction
- [ ] Trust/transparency features working

### Technical Quality
- [ ] JSON structure validates against specs
- [ ] No BigQuery quota errors
- [ ] GCS upload latency < 10s per file
- [ ] Circuit breaker doesn't trip
- [ ] All fields populated (no nulls where unexpected)
