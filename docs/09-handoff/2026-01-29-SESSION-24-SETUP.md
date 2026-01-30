# Session 24 Setup - CatBoost V8 Data Validation & Training Strategy

**Date:** 2026-01-29
**Previous Session:** 23 (Performance Analysis)
**Priority:** HIGH - Critical model performance issues identified

---

## Recommendation: Use Opus for Strategic Analysis

**Why Opus?**
- Complex multi-faceted problem requiring architectural thinking
- Need to design training/evaluation strategy
- Trade-off analysis between multiple approaches
- Code investigation + data analysis + strategic planning

**Session Strategy:**
1. **One Opus session** for the full analysis
2. Use Task agents liberally for parallel data queries
3. Expect 60-90 minutes of work

---

## The Problem We're Solving

### Critical Discovery from Session 23

**The reported 73% hit rate is INVALID** due to data leakage:

1. Model trained on: **Nov 2021 - June 2024** data
2. On Jan 9, 2026: Someone ran the model retroactively on **ALL historical data** (2021-2025)
3. This means we "predicted" games the model was trained on
4. True out-of-sample performance is unknown but appears to be **54-66%**

### What We Need to Figure Out

1. **Exactly which data was used for training** (verify the Nov 2021 - June 2024 claim)
2. **What is the safe evaluation period** (data model never saw during training)
3. **What is the true forward-looking performance** on uncontaminated data
4. **Should we retrain** and if so, on what data?
5. **Should we have multiple models** for different scenarios?

---

## Key Files to Read First

### Project Documentation
```
docs/08-projects/current/catboost-v8-performance-analysis/
├── CATBOOST-V8-PERFORMANCE-ANALYSIS.md   # Full analysis from Session 23
└── README.md                              # Project overview
```

### Training Code
```
ml/train_final_ensemble_v8.py             # Training script - CRITICAL
models/ensemble_v8_*_metadata.json        # Model metadata
```

### Production Code
```
predictions/worker/prediction_systems/catboost_v8.py  # Inference code
```

### Previous Handoffs
```
docs/09-handoff/2026-01-29-SESSION-23-PERFORMANCE-ANALYSIS.md  # Just completed
docs/09-handoff/2026-01-29-SESSION-20-CATBOOST-V8-FIX-AND-SAFEGUARDS.md  # Feature bug
```

---

## Questions to Answer

### 1. Training Data Verification

**Goal:** Confirm exactly what data the model trained on

Questions:
- [ ] What SQL query was used to fetch training data?
- [ ] What date range was specified?
- [ ] Were there any additional filters (e.g., minimum games played)?
- [ ] How many samples were in train/val/test splits?
- [ ] What was the chronological cutoff between splits?

**Where to look:**
- `ml/train_final_ensemble_v8.py` lines 56-77
- `models/ensemble_v8_*_metadata.json`

### 2. Safe Evaluation Period

**Goal:** Identify dates we can trust for performance evaluation

| Period | Status | Notes |
|--------|--------|-------|
| Nov 2021 - June 2024 | TRAINING DATA | Never use for evaluation |
| July 2024 - Dec 2024 | VALIDATION/TEST? | Need to verify split |
| Jan 2025 - Dec 2025 | OUT-OF-SAMPLE? | Should be safe if not in training |
| Jan 2026+ | FORWARD-LOOKING | Only use predictions created BEFORE game |

Questions:
- [ ] Where exactly did the test set end?
- [ ] Is any 2024 data usable for evaluation?
- [ ] Can we trust retroactive predictions on 2025 data?

### 3. True Performance Calculation

**Goal:** Calculate hit rate only on uncontaminated data

Requirements:
- Only include games AFTER training period ended
- For 2026 data: only include forward-looking predictions (created_at <= game_date)
- Verify line sources are correct
- Handle confidence scale issues (0-1 vs 0-100)

### 4. Training Strategy Analysis

**Goal:** Determine optimal approach for model improvement

Questions to explore:
- [ ] Should we retrain on more recent data?
- [ ] What's the right train/val/test split for time series?
- [ ] Should we have separate models for:
  - Different confidence tiers?
  - Different player types (stars vs role players)?
  - Different line sources (ODDS_API vs BETTINGPROS)?
  - Home vs away?
- [ ] How often should we retrain?
- [ ] Should we use walk-forward validation?

### 5. Data Correction Plan

**Goal:** Fix the corrupted prediction data

Options:
1. **Mark contaminated predictions** - Add `is_valid_for_evaluation` flag
2. **Delete retroactive predictions** - Remove all predictions where created_at > game_date + 1 day
3. **Recalculate metrics** - Create clean views for reporting

---

## Key Queries to Run

### Q1: Verify Training Data Period
```sql
-- Check what data was actually available for training
SELECT
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game,
  COUNT(*) as total_games
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
```

### Q2: Find Safe Evaluation Period
```sql
-- Predictions on data NOT in training period
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(*) as predictions,
  SUM(CASE WHEN DATE(created_at) <= game_date THEN 1 ELSE 0 END) as forward_looking,
  SUM(CASE WHEN DATE(created_at) > game_date THEN 1 ELSE 0 END) as retroactive
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date > '2024-06-01'  -- After training period
GROUP BY 1, 2
ORDER BY 1, 2
```

### Q3: True Forward-Looking Performance
```sql
-- Only predictions made BEFORE the game, on data AFTER training period
SELECT
  COUNT(*) as predictions,
  SUM(CASE WHEN
    (p.recommendation = 'OVER' AND g.points > p.current_points_line) OR
    (p.recommendation = 'UNDER' AND g.points < p.current_points_line)
  THEN 1 ELSE 0 END) as hits,
  ROUND(SUM(CASE WHEN
    (p.recommendation = 'OVER' AND g.points > p.current_points_line) OR
    (p.recommendation = 'UNDER' AND g.points < p.current_points_line)
  THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary g
  ON p.player_lookup = g.player_lookup AND p.game_date = g.game_date
WHERE p.system_id = 'catboost_v8'
  AND p.has_prop_line = TRUE
  AND p.recommendation IN ('OVER', 'UNDER')
  AND p.game_date > '2024-06-01'  -- After training period
  AND DATE(p.created_at) <= p.game_date  -- Forward-looking only
  AND g.points IS NOT NULL
  AND g.points != p.current_points_line  -- Exclude pushes
```

### Q4: Performance by Evaluation Period
```sql
-- Break down by period to see trends
SELECT
  CASE
    WHEN game_date BETWEEN '2024-07-01' AND '2024-12-31' THEN '2024 H2'
    WHEN game_date BETWEEN '2025-01-01' AND '2025-06-30' THEN '2025 H1'
    WHEN game_date BETWEEN '2025-07-01' AND '2025-12-31' THEN '2025 H2'
    ELSE '2026'
  END as period,
  -- ... hit rate calculation
FROM ...
GROUP BY 1
ORDER BY 1
```

---

## Known Issues to Fix

### 1. Confidence Scale Bug
- Some predictions use 0-1 scale, others use 0-100
- Need to normalize before filtering
- Percent-scale 95%+ = 66% hit rate
- Decimal-scale = 48-52% (coin flip)

### 2. Feature Passing Bug (Session 20)
- Worker doesn't pass Vegas/opponent/PPM features correctly
- Causes extreme predictions (60+ points)
- Already documented, needs verification of fix

### 3. Line Source Attribution
- ~38% of predictions have unverifiable line sources
- Backfills create phantom lines
- Need to validate or exclude

---

## Expected Deliverables

By end of session, we should have:

1. **Data Validation Report**
   - Confirmed training data period
   - Identified safe evaluation windows
   - Quantified contamination

2. **True Performance Metrics**
   - Forward-looking hit rate by period
   - Confidence tier analysis (normalized)
   - Line source comparison

3. **Training Strategy Recommendation**
   - Should we retrain? When?
   - What data to use?
   - Single model vs multiple models?

4. **Data Correction Plan**
   - How to mark/fix contaminated predictions
   - Schema changes if needed
   - Migration scripts

5. **Updated Project Docs**
   - `docs/08-projects/current/catboost-v8-performance-analysis/`
   - Add findings and recommendations

---

## Success Criteria

After this session, we should be able to answer:

1. **"What is the true hit rate of CatBoost V8?"**
   - Answer: X% on forward-looking predictions after training period

2. **"Can we achieve 70%+ hit rate?"**
   - Answer: Yes/No, with evidence and conditions

3. **"What should we do next?"**
   - Clear action plan with priorities

4. **"How do we prevent this contamination in the future?"**
   - Validation checks, monitoring, alerts

---

## Context from Session 23

### What We Discovered

| Finding | Impact |
|---------|--------|
| 114,884 predictions created retroactively on Jan 9, 2026 | Historical metrics invalid |
| Training period: Nov 2021 - June 2024 | 2021-2024 predictions are contaminated |
| Confidence scale inconsistency | Can't reliably filter by confidence |
| ~38% of line sources unverifiable | Many predictions use phantom lines |
| True 2026 forward-looking: ~54% overall | Marginal edge at best |
| 95%+ percent-scale: 66% hit rate | This might be the real signal |

### Key Insight

The model might actually be performing well (66% on high-confidence), but:
1. We can't trust historical metrics
2. Bugs (confidence scale, feature passing) are polluting results
3. Need clean data to validate

---

## How to Start

```
1. Read the project docs:
   cat docs/08-projects/current/catboost-v8-performance-analysis/CATBOOST-V8-PERFORMANCE-ANALYSIS.md

2. Read the training script:
   cat ml/train_final_ensemble_v8.py

3. Read the model metadata:
   cat models/ensemble_v8_*_metadata.json

4. Run the verification queries above

5. Use Task agents liberally for parallel analysis
```

---

*Handoff created: 2026-01-29 Session 23*
*Ready for: Session 24 with Opus*
