# Session 43 Handoff: Analysis Framework & Best Bets Strategy

**Date:** 2026-01-14
**Session:** 43
**Status:** Documentation Complete - Implementation Pending

---

## Quick Start for New Chat

### Read These First
```
docs/08-projects/current/ml-model-v8-deployment/ANALYSIS-FRAMEWORK.md     # Critical findings
docs/08-projects/current/pipeline-reliability-improvements/BEST-BETS-SELECTION-STRATEGY.md
docs/09-handoff/2026-01-14-SESSION-41-COMPLETE-HANDOFF.md                 # Previous context
```

### Key Tables
```sql
-- Predictions with grading
SELECT * FROM nba_predictions.prediction_accuracy WHERE game_date >= '2026-01-01';

-- Raw predictions
SELECT * FROM nba_predictions.player_prop_predictions WHERE game_date >= '2026-01-01';
```

---

## What Was Done This Session

### 1. Comprehensive Analysis Framework Created

Created `ANALYSIS-FRAMEWORK.md` with data-driven analysis of 10,000+ predictions across multiple dimensions.

### 2. Critical Findings Documented

| Dimension | Finding | Impact |
|-----------|---------|--------|
| **UNDER vs OVER** | UNDER 95% hit rate, OVER 53% | +42% advantage |
| **Edge Threshold** | 5+ pts = 93%, <2 pts = 24% | Edge more important than confidence |
| **Player Tier** | Bench 89%, Stars 44% | Avoid star players entirely |
| **Day of Week** | Thu-Fri 84%, Mon 76% | Mid-week is best |
| **System** | xgboost 87.5%, catboost 74.8% | xgboost significantly better |
| **Team** | Utah/LAC/LAL 88-90% | Some teams more predictable |

### 3. Best Bets Strategy Updated

Updated `BEST-BETS-SELECTION-STRATEGY.md` with:
- Revised tier criteria based on analysis
- Multi-system strategy options
- AVOID criteria (what NOT to include)
- SQL queries for implementation

### 4. All Commits Pushed

15 commits pushed to origin/main, including:
- Phase 3 UPSERT fix (game_id → game_date)
- Enrichment processor
- Worker/Coordinator v3.5
- Challenger model V10
- Training data strategy
- Analysis framework
- Best bets updates

---

## CRITICAL FINDINGS (Must Understand)

### 1. UNDER Dominates OVER

```
UNDER at 90%+ confidence: 95.0% hit rate (7,709 picks)
OVER at 90%+ confidence:  53.2% hit rate (1,794 picks)
```

**Action Required:** Best bets should be UNDER-only at high confidence.

### 2. Edge is More Important Than Confidence

```
90%+ conf + 5+ edge:  92.9% hit rate
90%+ conf + <2 edge:  24.1% hit rate (TERRIBLE!)
```

**Action Required:** Minimum 4+ point edge for best bets.

### 3. Avoid Star Players

```
Bench (<12 predicted pts):  89.0% hit rate, MAE 3.13
Star (25+ predicted pts):   43.6% hit rate, MAE 16.55
```

**Action Required:** Exclude players with predicted_points >= 25.

### 4. 88-90% Confidence Tier is Broken

This tier consistently underperforms at ALL edge levels (42% hit rate). Already filtered, but reason unknown.

---

## REMAINING TASKS (Priority Order)

### HIGH Priority

#### 1. Implement Tiered Best Bets in Code
**Effort:** 2-3 hours
**Location:** `data_processors/publishing/best_bets_exporter.py`

**Current State:**
- Uses composite score ranking
- No minimum thresholds
- No UNDER preference

**Required Changes:**
```python
# Add to best_bets_exporter.py

TIER_CRITERIA = {
    'premium': {
        'recommendation': 'UNDER',
        'min_confidence': 0.90,
        'min_edge': 5.0,
        'max_predicted_points': 18,
        'max_picks': 5
    },
    'strong': {
        'recommendation': 'UNDER',
        'min_confidence': 0.90,
        'min_edge': 4.0,
        'max_predicted_points': 20,
        'max_picks': 10
    },
    'value': {
        'recommendation': 'UNDER',
        'min_confidence': 0.80,
        'min_edge': 5.0,
        'max_predicted_points': 22,
        'max_picks': 10
    }
}
```

#### 2. Schedule Enrichment Processor
**Effort:** 1-2 hours
**Location:** `data_processors/enrichment/prediction_line_enrichment/`

**Problem:** Processor exists but only runs manually.

**Solution:** Create Cloud Function wrapper:
```
orchestration/cloud_functions/prediction_line_enrichment/
├── main.py
└── requirements.txt
```

**Schedule:** 18:40 UTC daily (after props scraped at 18:00)

**Pattern to follow:** See `orchestration/cloud_functions/live_export/main.py`

#### 3. Adjust Phase 3 Timing
**Effort:** 15 minutes
**Problem:** Runs at 17:45 UTC, before props scraped at 18:00 UTC

**Fix:**
```bash
gcloud scheduler jobs update http same-day-phase3-tomorrow \
  --location=us-west2 \
  --schedule="0 19 * * *"
```

### MEDIUM Priority

#### 4. Investigate 88-90% Confidence Anomaly
**Effort:** 1 hour

The 88-90% confidence tier hits only 42% even with 4+ edge. Need to understand why.

**Queries to run:**
```sql
-- What's different about 88-90% picks?
SELECT
  system_id,
  recommendation,
  AVG(ABS(predicted_points - line_value)) as avg_edge,
  COUNT(*) as picks
FROM nba_predictions.prediction_accuracy
WHERE confidence_score >= 0.88 AND confidence_score < 0.90
  AND game_date >= '2025-10-01'
GROUP BY 1, 2
ORDER BY picks DESC;
```

#### 5. Investigate xgboost vs catboost Gap
**Effort:** 1-2 hours

xgboost_v1 (87.5%) significantly outperforms catboost_v8 (74.8%). Why?

### LOW Priority

#### 6. Cloud Monitoring Alert Policy
**Effort:** 5 minutes (manual in Cloud Console)

Create alert for auth errors using existing log-based metric.

---

## KEY CODE LOCATIONS

| Component | Location |
|-----------|----------|
| Best Bets Exporter | `data_processors/publishing/best_bets_exporter.py` |
| Enrichment Processor | `data_processors/enrichment/prediction_line_enrichment/` |
| Phase 3 Processor | `data_processors/analytics/upcoming_player_game_context/` |
| Prediction Worker | `predictions/worker/worker.py` |
| XGBoost System | `predictions/systems/xgboost_v1.py` |
| CatBoost System | `predictions/systems/catboost_v8.py` |
| Ensemble | `predictions/systems/ensemble_v1.py` |

---

## KEY DOCUMENTATION

| Document | Purpose |
|----------|---------|
| `ANALYSIS-FRAMEWORK.md` | Complete dimensional analysis |
| `BEST-BETS-SELECTION-STRATEGY.md` | Tiered pick selection strategy |
| `TRAINING-DATA-STRATEGY.md` | ML training recommendations |
| `CHAMPION-CHALLENGER-FRAMEWORK.md` | Model promotion criteria |
| `PERFORMANCE-ANALYSIS-GUIDE.md` | How to grade and analyze |

All in: `docs/08-projects/current/ml-model-v8-deployment/`

---

## VERIFICATION COMMANDS

### Check System Performance
```bash
bq query --use_legacy_sql=false '
SELECT system_id, COUNT(*) as picks,
       ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= "2025-10-01" AND line_value IS NOT NULL
GROUP BY 1 ORDER BY hit_rate DESC'
```

### Check UNDER vs OVER
```bash
bq query --use_legacy_sql=false '
SELECT recommendation,
       CASE WHEN confidence_score >= 0.90 THEN "90%+" ELSE "80-90%" END as conf,
       COUNT(*) as picks,
       ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= "2025-10-01" AND line_value IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2 DESC'
```

### Check Git Status
```bash
git status --short
git log --oneline -10
```

### Run Enrichment Manually (if needed)
```bash
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --dry-run
```

---

## UNCOMMITTED FILES (MLB Project - Separate)

There are untracked MLB files that are part of a separate project:
- `predictions/mlb/pitcher_strikeouts_predictor_v2.py`
- `scrapers/bettingpros/bp_mlb_player_props.py`
- `shared/utils/mlb_*`
- `scripts/mlb/*`

These can be committed separately when ready.

---

## CONTEXT FROM PREVIOUS SESSIONS

### Session 41: Betting Lines Fix
- Created enrichment processor to backfill betting lines
- Fixed worker v3.5 to preserve estimated lines
- Fixed coordinator v3.5 with deduplication

### Session 42: Champion-Challenger
- Trained challenger V10 with extended data
- V8 still wins (72.5% vs 72.2% on high-confidence)
- Documented why older training data performs better

### Session 43 (This Session): Analysis Framework
- Created comprehensive dimensional analysis
- Found UNDER >> OVER (95% vs 53%)
- Found edge >> confidence for predictions
- Documented multi-system strategy

---

## RECOMMENDED NEXT STEPS

1. **Start with:** Implement tiered best bets in code
   - Highest impact change
   - Strategy is fully documented
   - Just needs code implementation

2. **Then:** Schedule enrichment processor
   - Follow Cloud Function pattern
   - Schedule at 18:40 UTC

3. **Quick wins:**
   - Adjust Phase 3 timing (15 min)
   - Cloud Monitoring alert (5 min manual)

---

## QUESTIONS FOR USER (If Unclear)

1. Should best bets be UNDER-only or weighted heavily toward UNDER?
2. Should we expose tier labels on the website (Premium/Strong/Value)?
3. Should we filter by system_id (xgboost_v1 only for premium)?
4. What's the desired volume vs quality tradeoff?

---

*Last Updated: 2026-01-14*
*Git Status: All pushed to origin/main*
