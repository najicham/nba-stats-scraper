# Session 41 Complete Handoff: Betting Lines Fix + Remaining Work

**Date:** 2026-01-14
**Session:** 41
**Status:** Core Fix Complete - Multiple Items Remaining

---

## For New Chat: Quick Start

### Project Documentation Locations

```
docs/
├── 08-projects/current/
│   ├── monitoring-improvements/     # Current monitoring project
│   │   ├── README.md               # Project overview
│   │   └── TODO.md                 # Detailed task list with commands
│   ├── pipeline-reliability-improvements/  # ML and pipeline docs
│   └── mlb-pitcher-strikeouts/     # MLB project (separate)
│
├── 09-handoff/
│   ├── 2026-01-14-SESSION-41-BETTING-LINES-FIX.md  # This session's details
│   ├── 2026-01-14-SESSION-40-COMPLETE-HANDOFF.md   # Previous session
│   └── [historical handoffs...]
│
└── 01-architecture/                # System architecture docs
```

### Key Tables to Query

```sql
-- Predictions with betting lines
SELECT * FROM nba_predictions.player_prop_predictions WHERE game_date >= '2026-01-01';

-- Graded accuracy with hit rates
SELECT * FROM nba_predictions.prediction_accuracy WHERE game_date >= '2026-01-01';

-- Raw betting props (source of truth)
SELECT * FROM nba_raw.odds_api_player_points_props WHERE game_date >= '2026-01-01';

-- Phase 3 player context (has duplicates issue)
SELECT * FROM nba_analytics.upcoming_player_game_context WHERE game_date >= '2026-01-01';
```

---

## What Was Fixed This Session

### Root Cause: Betting Lines Not Joined to Predictions

**Problem:** Predictions had `current_points_line = NULL` since Jan 1, preventing hit rate calculation.

**Root Causes Identified:**
1. **Timing Gap:** Predictions generated night-before (22:32 UTC), props scraped game-day (18:05 UTC)
2. **Phase 3 Timing:** Runs 17:45 UTC, props scraped 18:05 UTC (misses same-day props)
3. **Worker Bug:** When `has_prop_line=False`, set `current_points_line=None` (lost estimated lines)
4. **Phase 3 Duplicates:** Creates NEW rows on re-run instead of UPDATE
5. **No Deduplication:** Coordinator didn't pick latest Phase 3 record

### Solutions Implemented

| Fix | File | Description |
|-----|------|-------------|
| **Enrichment Processor** | `data_processors/enrichment/prediction_line_enrichment/` | Post-processing to add lines after props scraped |
| **Worker v3.5** | `predictions/worker/worker.py:1117-1143` | Use estimated lines when no prop exists |
| **Coordinator v3.5** | `predictions/coordinator/player_loader.py:294` | Deduplicate Phase 3 records |

### Results

- **1,935 predictions enriched** (Jan 1-14)
- **All dates now have hit rates** (was NULL for Jan 1, 6, 12-14)
- **Line coverage improved:** Jan 1: 0%→45%, Jan 6: 0%→69%, Jan 12-14: 0%→75-87%

---

## REMAINING WORK - Priority Order

### HIGH Priority

#### 1. Schedule Enrichment Processor
**Effort:** 1-2 hours (requires Cloud Run deployment)
**Problem:** Enrichment processor is a Python script, but scheduler uses HTTP endpoints

**Options:**
- A) Create Cloud Function wrapper
- B) Add endpoint to existing service (nba-phase1-scrapers or analytics)
- C) Integrate into daily orchestration workflow

**For now, run manually:**
```bash
# Run daily after 7pm ET when props are scraped
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor
```

### MEDIUM Priority

#### 2. Fix Phase 3 UPSERT Logic
**Effort:** 30-60 min
**Problem:** `upcoming_player_game_context` creates duplicate rows when processor re-runs

**Evidence:**
```sql
-- Many players have 2 rows per date
SELECT player_lookup, game_date, COUNT(*)
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2026-01-10'
GROUP BY 1,2 HAVING COUNT(*) > 1;
```

**Fix Location:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- Change INSERT to MERGE/UPSERT
- Use `player_lookup + game_date` as key

#### 3. Adjust Phase 3 Scheduler Timing
**Effort:** 15 min
**Problem:** Phase 3 runs at 17:45 UTC, props scraped at 18:05 UTC

**Fix:** Move Phase 3 to 19:00 UTC (after props available)
```bash
# Find the scheduler job
gcloud scheduler jobs list --location=us-west2 | grep -i upcoming
# Update timing
gcloud scheduler jobs update http <job-name> --schedule="0 19 * * *"
```

### LOW Priority

#### 4. Add NULL Lines Monitoring Alert
Alert when >20% predictions have NULL lines on game day

#### 5. Automate Grading Re-run After Enrichment
Currently manual - should trigger automatically

#### 6. Auth Error Alert Policy (from Session 40)
Manual Cloud Console setup - 5 minutes

### INVESTIGATE

#### 7. Hit Rate Variance Analysis
**Anomaly:** Jan 9 hit rate 83.2% vs Jan 11 hit rate 31.4%

```sql
-- Investigate the variance
SELECT game_date,
       COUNT(*) as graded,
       ROUND(AVG(absolute_error), 2) as mae,
       ROUND(COUNTIF(prediction_correct) / NULLIF(COUNTIF(line_value IS NOT NULL), 0) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-01-08' AND '2026-01-13'
GROUP BY game_date ORDER BY game_date;
```

Questions to answer:
- Were different prediction systems used?
- Were the games unusual (blowouts, injuries)?
- Is there a data quality issue?

---

## TRAINING DATA INVESTIGATION

### Current ML Models

The prediction system uses multiple models in `predictions/systems/`:
- `moving_average_baseline_v1` - Simple baseline
- `zone_matchup_v1` - Matchup-based
- `similarity_balanced_v1` - Similar game lookup
- `xgboost_v1` - Gradient boosting (v8 model)
- `ensemble_v1` - Combines all above

### Training Data Location

```
models/
├── xgboost/
│   └── nba_points_v8/           # Current production model
│       ├── model.json           # Model weights
│       └── metadata.json        # Training metadata
│
predictions/systems/
├── xgboost_v1.py               # Model wrapper
└── ensemble_v1.py              # Ensemble logic
```

### Questions to Investigate

1. **What data was used for training?**
   - Check `models/xgboost/nba_points_v8/metadata.json`
   - Look at training scripts in `scripts/ml/` or `training/`

2. **When was it last trained?**
   - Check model metadata timestamp
   - Review git history for model updates

3. **Should we retrain?**
   Consider retraining if:
   - Hit rates consistently below target (50%?)
   - New features available (e.g., better injury data)
   - Significant drift in prediction accuracy
   - Season-over-season patterns change

4. **Training data quality issues:**
   - Did training data have the same NULL lines problem?
   - Were predictions graded with correct lines?
   - Is there survivorship bias (only players with props)?

### Commands to Explore Training

```bash
# Find training scripts
find . -name "*train*" -type f | grep -v __pycache__

# Check model metadata
cat models/xgboost/nba_points_v8/metadata.json 2>/dev/null || echo "No metadata found"

# Find where models are trained
grep -r "fit\|train" predictions/systems/*.py | head -20

# Check ML feature store (training features)
ls -la data_processors/precompute/ml_feature_store/
```

### Relevant Project Docs

```
docs/08-projects/current/
├── ml-model-v8-deployment/      # V8 model deployment docs
├── pipeline-reliability-improvements/
│   └── FILTER-DECISIONS.md     # Confidence tier filtering logic
```

---

## VERIFICATION COMMANDS

### Check Current State

```bash
# Line coverage by date
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as total,
       COUNTIF(current_points_line IS NOT NULL) as with_line,
       ROUND(COUNTIF(current_points_line IS NOT NULL) / COUNT(*) * 100, 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= "2026-01-01"
GROUP BY game_date ORDER BY game_date'

# Hit rates by date
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as graded,
       COUNTIF(line_value IS NOT NULL) as with_line,
       ROUND(COUNTIF(prediction_correct) / NULLIF(COUNTIF(line_value IS NOT NULL), 0) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= "2026-01-01"
GROUP BY game_date ORDER BY game_date'

# Phase 3 duplicates
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as total, COUNT(DISTINCT player_lookup) as unique_players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= "2026-01-10"
GROUP BY game_date ORDER BY game_date'
```

### Run Enrichment

```bash
# Dry run for today
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --dry-run

# Actually enrich
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor

# Re-run grading after enrichment
python -c "
from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor
from datetime import date
processor = PredictionAccuracyProcessor()
result = processor.process_date(date.today())
print(result)
"
```

---

## ARCHITECTURE CONTEXT

### Data Flow (Current)

```
1. Props scraped (18:05 UTC game day)
         ↓
2. Phase 3 runs (17:45 UTC) - BEFORE props!
         ↓
3. Predictions run (22:32 UTC night before)
         ↓
4. [NEW] Enrichment processor (manual, should be ~19:30 UTC)
         ↓
5. Grading (11:00 UTC next day)
```

### Key Code Locations

| Component | Location |
|-----------|----------|
| Prediction Worker | `predictions/worker/worker.py` |
| Prediction Coordinator | `predictions/coordinator/player_loader.py` |
| Phase 3 Processor | `data_processors/analytics/upcoming_player_game_context/` |
| Enrichment Processor | `data_processors/enrichment/prediction_line_enrichment/` |
| Grading Processor | `data_processors/grading/prediction_accuracy/` |
| XGBoost Model | `predictions/systems/xgboost_v1.py` |
| Ensemble | `predictions/systems/ensemble_v1.py` |

---

## FILES CHANGED THIS SESSION (uncommitted)

```
NEW:
  data_processors/enrichment/__init__.py
  data_processors/enrichment/prediction_line_enrichment/__init__.py
  data_processors/enrichment/prediction_line_enrichment/prediction_line_enrichment_processor.py
  docs/09-handoff/2026-01-14-SESSION-41-BETTING-LINES-FIX.md
  docs/09-handoff/2026-01-14-SESSION-41-COMPLETE-HANDOFF.md (this file)

MODIFIED:
  predictions/worker/worker.py (v3.5 - estimated lines fix)
  predictions/coordinator/player_loader.py (v3.5 - deduplication)
  docs/08-projects/current/monitoring-improvements/TODO.md
```

---

## RECOMMENDED NEXT STEPS

1. **Read this handoff** and the detailed one at `docs/09-handoff/2026-01-14-SESSION-41-BETTING-LINES-FIX.md`

2. **Verify current state** with the verification commands above

3. **Investigate training data:**
   - Find training scripts and metadata
   - Determine if NULL lines issue affected training data
   - Assess if retraining is needed

4. **Fix remaining issues** in priority order:
   - Schedule enrichment processor
   - Fix Phase 3 UPSERT
   - Adjust Phase 3 timing

5. **Investigate hit rate variance** (Jan 9: 83% vs Jan 11: 31%)

---

## CONTEXT FOR DECISIONS

### Why Enrichment Processor Instead of Fixing Timing?

We chose to create an enrichment processor (Option B) instead of fixing the timing (Option C) because:
1. **Lower risk** - Doesn't change core prediction pipeline
2. **Backward compatible** - Can backfill historical data
3. **Faster to implement** - No scheduler coordination needed
4. **Can be scheduled independently** - Runs after props available

The timing fixes (Phase 3 UPSERT, scheduler adjustment) are still valuable for long-term architecture improvement.

### Why Hit Rates Vary So Much?

Initial hypothesis:
- Jan 9: 83.2% hit rate, MAE 4.4
- Jan 11: 31.4% hit rate, MAE 6.72

Higher MAE correlates with lower hit rate, but the magnitude of difference is suspicious. Could be:
- Different line sources used
- Game slate characteristics (favorites vs underdogs)
- Injury surprises affecting results
- Data quality issues on specific dates

This needs investigation.
