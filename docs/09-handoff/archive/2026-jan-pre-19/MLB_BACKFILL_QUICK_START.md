# MLB 4-Season Backfill - Quick Start Guide

**Goal:** Generate V1.6 predictions for 2022-2025 (all 4 seasons)
**Total Time:** 14-18 hours optimized, 18-27 hours sequential
**Prerequisites:** Read `MLB_PREDICTION_SYSTEM_INVENTORY.md` for full details

---

## Current State Summary

✅ **What's Working:**
- V1 predictions exist for 2024-2025 (67.3% win rate!)
- Analytics tables exist for 2024-2025
- V1.6 model trained and ready locally

❌ **What's Missing:**
- 2022-2023 analytics tables (pitcher_game_summary)
- Any V1.6 predictions (model not deployed)
- V1.6 model not in GCS

⏸️ **What Needs Verification:**
- Does raw data exist for 2022-2023? (likely yes)

---

## 5-Phase Execution Plan

### Phase 1: Data Verification (2 hours)

**Check if we have the raw data:**

```bash
# Create and run data check script
cat > /tmp/verify_2022_2023_data.sql << 'EOF'
-- Check raw pitcher stats
SELECT 'mlb_pitcher_stats' as source, EXTRACT(YEAR FROM game_date) as year,
       COUNT(*) as records, COUNT(DISTINCT player_lookup) as pitchers
FROM `nba-props-platform.mlb_raw.mlb_pitcher_stats`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year

UNION ALL

-- Check statcast (for V1.6)
SELECT 'statcast_pitcher_game_stats' as source, EXTRACT(YEAR FROM game_date) as year,
       COUNT(*) as records, COUNT(DISTINCT player_lookup) as pitchers
FROM `nba-props-platform.mlb_raw.statcast_pitcher_game_stats`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year

ORDER BY source, year DESC;
EOF

bq query --use_legacy_sql=false < /tmp/verify_2022_2023_data.sql
```

**Decision:** If missing → STOP (cannot proceed). If exists → Continue to Phase 2.

---

### Phase 2: Rebuild Analytics (8-12 hours, parallelizable to 6 hours)

**Goal:** Populate `mlb_analytics.pitcher_game_summary` for 2022-2023

#### Option A: Use Existing Processor (If Works)
```bash
# Test on single date first
PYTHONPATH=. python -c "
from data_processors.analytics.mlb.pitcher_game_summary_processor import MlbPitcherGameSummaryProcessor
from datetime import date
processor = MlbPitcherGameSummaryProcessor()
result = processor.process_date(date(2022, 4, 8))
print(f'Test result: {result}')
"

# If test works, backfill 2022
PYTHONPATH=. python scripts/mlb/backfill_pitcher_game_summary.py \
  --start-date 2022-04-07 --end-date 2022-10-05

# Backfill 2023
PYTHONPATH=. python scripts/mlb/backfill_pitcher_game_summary.py \
  --start-date 2023-03-30 --end-date 2023-10-01
```

#### Option B: Create Backfill Script (If processor doesn't exist/work)
```bash
# Create simple backfill script
# See MLB_PREDICTION_SYSTEM_INVENTORY.md Section 5 Phase 2 for details
```

**Validation:**
```sql
SELECT season_year, COUNT(*) as records, COUNT(DISTINCT player_lookup) as pitchers
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
GROUP BY season_year
ORDER BY season_year;
```

**Expected:** ~4,500 records per season for 2022-2023

---

### Phase 3: Deploy V1.6 & Generate Predictions (4-6 hours, parallelizable to 2 hours)

#### Step 1: Upload V1.6 to GCS (5 minutes)
```bash
gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
  gs://nba-scraped-data/ml-models/mlb/

gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json \
  gs://nba-scraped-data/ml-models/mlb/
```

#### Step 2: Test V1.6 Predictor
```bash
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
from datetime import date

predictor = PitcherStrikeoutsPredictor(
    model_path='gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'
)
preds = predictor.batch_predict(date(2024, 4, 10))
print(f'Test: {len(preds)} predictions')
"
```

#### Step 3: Generate Predictions for All 4 Seasons
```bash
# Can run all 4 in parallel if you have multiple terminals/workers
for year in 2022 2023 2024 2025; do
  PYTHONPATH=. python scripts/mlb/generate_historical_predictions_v16.py \
    --season $year \
    --model-version v1.6
done
```

**Expected:** ~17,500 total predictions

---

### Phase 4: Grade Predictions (2-4 hours, parallelizable to 1 hour)

```bash
# Grade all V1.6 predictions
PYTHONPATH=. python scripts/mlb/grade_all_v16_predictions.py \
  --start-date 2022-04-07 \
  --end-date 2025-09-30 \
  --model-filter v1_6
```

**Validation:**
```sql
SELECT
  season_year,
  COUNT(*) as total,
  COUNTIF(is_correct IS NOT NULL) as graded,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version LIKE '%v1_6%'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY season_year;
```

---

### Phase 5: Validate Everything (2-3 hours)

```bash
# Run all validation scripts
PYTHONPATH=. python scripts/mlb/validate_v1_6_backfill_comprehensive.py \
  --seasons 2022,2023,2024,2025 \
  --verbose

PYTHONPATH=. python scripts/mlb/validate_v1_6_statistical_analysis.py \
  --export-csv

# Compare V1 vs V1.6 (for 2024-2025 where both exist)
PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16.py --seasons 2024,2025
```

**Success Criteria:**
- ✅ Win rate >55% for each season
- ✅ MAE <2.0 for each season
- ✅ >95% graded
- ✅ Coverage >90%
- ✅ All validation scripts pass

---

## Quick Status Checks

### Check What You Have
```sql
-- Predictions by model and season
SELECT
  CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
  season_year,
  COUNT(*) as predictions,
  COUNTIF(is_correct IS NOT NULL) as graded
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
GROUP BY model, season_year
ORDER BY season_year, model;

-- Analytics tables by season
SELECT season_year, COUNT(*) as pitcher_records
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
GROUP BY season_year
ORDER BY season_year;
```

### Monitor Progress During Backfill
```bash
# Watch analytics backfill
watch -n 60 "bq query --use_legacy_sql=false 'SELECT season_year, COUNT(*) FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\` GROUP BY season_year ORDER BY season_year'"

# Watch prediction generation
watch -n 60 "bq query --use_legacy_sql=false 'SELECT EXTRACT(YEAR FROM game_date) as year, COUNT(*) as preds FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\` WHERE model_version LIKE \"%v1_6%\" GROUP BY year ORDER BY year'"
```

---

## Rollback Plan

**If something fails:**

- **Phase 1 fails:** STOP - need to investigate raw data
- **Phase 2 fails:** Debug processor, retry failed dates (no rollback needed)
- **Phase 3 fails:** V1 unaffected, debug V1.6, retry
- **Phase 4 fails:** Predictions exist but ungraded, debug grading
- **Phase 5 fails:** Analyze issues, may need to iterate on model

**V1 predictions are NEVER touched** - they remain safe in production.

---

## Decision Points

### Should We Backfill Batter Analytics?
- ✅ **Yes:** Better lineup features (f25-f28), more complete data
- ⚠️ **No:** Faster, use defaults for lineup features (still works)

**Recommendation:** Start without, add if needed for accuracy

### Should We Replace V1 with V1.6?
**Compare first on 2024-2025:**
- If V1.6 >= 67% win rate → Deploy V1.6
- If V1.6 60-67% → A/B test in parallel
- If V1.6 < 60% → Keep V1, iterate on V1.6

**Recommendation:** Keep both initially, gradually transition if V1.6 proves better

---

## Files & Documentation

**Read First:**
1. `MLB_PREDICTION_SYSTEM_INVENTORY.md` - Full detailed plan
2. `FINAL_V16_VALIDATION_FINDINGS.md` - Current state analysis

**Created:**
- ✅ Validation scripts (3 scripts)
- ✅ Inventory document
- ✅ Quick start guide (this file)
- ⏸️ Backfill scripts (need to create 5 scripts)

**Scripts Needed:**
1. `scripts/mlb/backfill_pitcher_game_summary.py`
2. `scripts/mlb/generate_historical_predictions_v16.py`
3. `scripts/mlb/grade_all_v16_predictions.py`
4. `scripts/mlb/compare_v1_vs_v16.py`
5. `scripts/mlb/check_2022_2023_data_availability.py`

---

## Timeline

| Phase | Time (Sequential) | Time (Parallel) |
|-------|-------------------|-----------------|
| 1. Data Verification | 2 hours | 2 hours |
| 2. Analytics Rebuild | 8-12 hours | 6 hours |
| 3. Prediction Generation | 4-6 hours | 2 hours |
| 4. Grading | 2-4 hours | 1 hour |
| 5. Validation | 2-3 hours | 3 hours |
| **Total** | **18-27 hours** | **14 hours** |

**Recommended:** Run over a weekend with parallelization

---

## Support

Questions? Check:
1. This guide for quick commands
2. `MLB_PREDICTION_SYSTEM_INVENTORY.md` for detailed explanations
3. Processor logs for debugging
4. Validation scripts for verification

**Status:** Ready to execute - all planning complete!
