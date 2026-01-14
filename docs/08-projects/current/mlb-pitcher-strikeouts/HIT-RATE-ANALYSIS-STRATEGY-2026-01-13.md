# MLB Strikeout Predictions - Hit Rate Analysis Strategy

**Created**: 2026-01-13
**Status**: Investigation Complete - Ready for Execution
**Author**: Ultra-Deep Analysis Session

---

## Executive Summary

We have **8,130 MLB strikeout predictions** from the 2024-2025 seasons that were generated WITHOUT betting lines. A comprehensive investigation reveals the path to proper hit rate analysis.

### Current State
- ✅ **8,130 predictions** (2024-04-09 to 2025-09-28)
- ✅ **9,742 actual results** (100% matchable)
- ✅ **Trained model** (MAE 1.71, v1_20260107)
- ❌ **0 betting lines** collected
- ❌ **0% graded** predictions

### Key Finding
**The predictions were generated without betting context**, which means:
- No OVER/UNDER recommendations (all marked `NO_LINE`)
- Cannot calculate traditional "hit rate against the spread"
- Can still measure raw prediction accuracy (MAE, calibration)
- Historical betting lines ARE retrievable via Odds API

---

## The High-Quality Approach: Three-Phase Strategy

### Phase 1: Raw Accuracy Analysis (Immediate - 30 min)

**Purpose**: Validate model quality independent of betting context

**What We Can Measure:**
1. **Mean Absolute Error (MAE)**: Average prediction error
2. **Directional Accuracy**: Predictions vs actuals directionally
3. **Calibration**: Are high-confidence predictions more accurate?
4. **Systematic Biases**: Over/under-prediction patterns
5. **Performance by Context**: Home/away, day/night, etc.

**Why This Matters:**
- If MAE is poor (>2.0), model needs retraining before betting analysis
- If calibration is bad, confidence scores are meaningless
- Establishes baseline for model quality

**Deliverable**: Comprehensive model quality report

---

### Phase 2: Historical Betting Lines Investigation (30-60 min)

**Purpose**: Determine if proper retrospective analysis is possible

**Investigation Steps:**

#### 2a. Check Odds API Historical Data Availability
```bash
# Test historical endpoint for a sample date
python scrapers/mlb/oddsapi/mlb_pitcher_props_his.py \
  --event_id <sample> \
  --game_date 2024-06-15 \
  --snapshot_timestamp 2024-06-15T18:00:00Z \
  --group dev
```

**Questions to Answer:**
- Are historical lines available for 2024-2025 seasons?
- What's the coverage percentage?
- What's the API cost? (Odds API charges per historical request)
- Are the lines accurate/representative of what was available?

#### 2b. Evaluate Data Quality
- Do retrieved lines match expected market patterns?
- Are there gaps in coverage?
- Is timing representative (pre-game, not post-game)?

**Decision Matrix:**

| Historical Lines Coverage | Recommendation |
|---------------------------|----------------|
| **>90% with good quality** | Proceed to Phase 3 (backfill) |
| **60-90% partial** | Backfill available data, note limitations |
| **<60% or poor quality** | Skip to Phase 4 (prospective only) |

---

### Phase 3: Comprehensive Historical Analysis (If Lines Available)

**IF Phase 2 determines historical lines are available...**

#### 3a. Backfill Historical Betting Lines (4-8 hours)

**Process:**
1. **Get event IDs** for prediction dates
   - Scrape `mlb_events_his` for each prediction date
   - Map games to Odds API event IDs

2. **Scrape historical lines**
   - For each prediction date, scrape pitcher strikeout lines
   - Use snapshot_timestamp ~2 hours before game time
   - Target: DraftKings, FanDuel primary books

3. **Process to BigQuery**
   - Load into `mlb_raw.oddsa_pitcher_props`
   - Normalize player names for matching

4. **Match predictions to lines**
   - Join predictions with betting lines
   - Calculate implied OVER/UNDER recommendations
   - Re-grade predictions WITH betting context

**Script to Create:**
```python
# scripts/mlb/backfill_historical_odds.py
# - Takes date range from predictions
# - Fetches historical lines from Odds API
# - Processes and loads to BigQuery
# - Matches and grades predictions
```

#### 3b. Full Hit Rate Analysis (NBA-style)

**Once betting lines are matched, run complete analysis:**

1. **Overall Hit Rate**
   ```sql
   SELECT
     COUNT(*) as total_picks,
     COUNTIF(is_correct = TRUE) as wins,
     ROUND(AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
     ROUND(AVG(absolute_error), 2) as mae
   FROM mlb_predictions.pitcher_strikeouts
   WHERE strikeouts_line IS NOT NULL
     AND recommendation IN ('OVER', 'UNDER')
   ```

2. **Hit Rate by Confidence Tier**
   - Bucket by confidence scores
   - Identify any problem tiers (like NBA's 88-90% issue)

3. **OVER vs UNDER Performance**
   - Systematic bias check
   - Market-making implications

4. **Performance by Context**
   - Home/away splits
   - Day/night games
   - By ballpark
   - Early vs late season

5. **Sportsbook Comparison** (if multi-book data available)
   - Hit rate vs DraftKings, FanDuel, etc.
   - Identify which book has beatable lines

**Deliverable**: Complete performance report matching NBA analysis quality

---

### Phase 4: Prospective Pipeline Setup (Regardless of Phase 2 Outcome)

**Purpose**: Ensure future predictions have proper betting context

#### 4a. Fix Prediction Pipeline

**Current Flow** (Broken):
```
1. Generate predictions from model
2. Look for betting lines (FAILS - none exist)
3. Save with NO_LINE recommendation
```

**Corrected Flow**:
```
1. Scrape betting lines FIRST (daily pre-game)
2. Process lines to BigQuery
3. Generate predictions WITH line context
4. Make OVER/UNDER recommendations
5. Save predictions WITH betting context
6. Grade after games complete
```

#### 4b. Daily Odds Collection

**Add to daily workflow:**
```bash
# Morning (8 AM ET) - Before games
1. Scrape today's MLB events → oddsa_events
2. Scrape pitcher props → oddsa_pitcher_props
3. Scrape batter props → oddsa_batter_props (for bottom-up model)
4. Scrape game lines → oddsa_game_lines

# Afternoon (12 PM ET) - Generate predictions
5. Run prediction coordinator WITH line context
6. Publish predictions with OVER/UNDER recommendations

# Evening (post-game) - Grade
7. Scrape actual results → bdl_pitcher_stats
8. Run grading processor
9. Update prediction accuracy table
```

#### 4c. Integration Points to Fix

**Files to Modify:**
1. `predictions/mlb/pitcher_strikeouts_predictor.py`
   - Add line lookup method
   - Generate OVER/UNDER from prediction vs line
   - Calculate edge percentage

2. `predictions/mlb/worker.py`
   - Query betting lines before prediction
   - Pass line context to predictor
   - Save predictions WITH line info

3. `data_processors/grading/mlb/mlb_prediction_grading_processor.py`
   - Already correct! Uses `mlb_raw.mlb_pitcher_stats`
   - Just needs predictions with lines to grade

**Deliverable**: Production-ready betting prediction system

---

## The Optimal Path Forward

### Recommended Execution Sequence

**Session 1: Immediate Insights (Today - 30 min)**
```bash
# Phase 1: Raw accuracy analysis
python scripts/mlb/analyze_prediction_accuracy.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --output docs/08-projects/current/mlb-pitcher-strikeouts/ACCURACY-REPORT.md
```

**Session 2: Historical Data Investigation (This week - 1 hour)**
```bash
# Phase 2: Test historical odds availability
python scripts/mlb/test_historical_odds_availability.py \
  --sample-dates 2024-06-15,2024-07-20,2024-08-10 \
  --output docs/08-projects/current/mlb-pitcher-strikeouts/HISTORICAL-ODDS-ASSESSMENT.md
```

**Session 3: Decision Point**
- Review Phase 1 + Phase 2 results
- Make informed decision on historical backfill
- Choose path: Full backfill OR prospective only

**Session 4a: IF backfilling (Next week - 6 hours)**
```bash
# Phase 3: Backfill and comprehensive analysis
python scripts/mlb/backfill_historical_odds.py \
  --start-date 2024-04-09 \
  --end-date 2025-09-28 \
  --books draftkings,fanduel

python scripts/mlb/comprehensive_hit_rate_analysis.py \
  --output docs/08-projects/current/mlb-pitcher-strikeouts/HIT-RATE-ANALYSIS.md
```

**Session 4b: ELSE prospective setup (Next week - 4 hours)**
```bash
# Phase 4: Fix pipeline for future
# 1. Implement daily odds collection
# 2. Update prediction pipeline
# 3. Test end-to-end
# 4. Deploy for upcoming season
```

---

## Cost-Benefit Analysis

### Option A: Full Historical Backfill

**Costs:**
- **Time**: 6-8 hours implementation + testing
- **API credits**: ~700 Odds API requests × 10 credits = 7,000 credits (~$70-140)
- **Complexity**: Matching historical data, data quality issues

**Benefits:**
- Complete historical performance analysis
- Understand model betting profitability
- Identify problem tiers/contexts
- Learn from 8,130 predictions worth of data
- Confidence for future deployment

**ROI**: High if model shows >54% hit rate. Invaluable learning.

### Option B: Prospective Only

**Costs:**
- **Time**: 4 hours pipeline fixes
- **API credits**: Ongoing daily costs (~$1-2/day during season)
- **Opportunity**: Miss learning from historical data

**Benefits:**
- Cleaner data (real-time betting context)
- Lower upfront cost
- Faster to production
- Still get betting analysis (just prospective)

**ROI**: Lower learning, but adequate for go-forward betting

---

## Success Criteria

### Phase 1 Success:
- [ ] MAE calculated and benchmarked
- [ ] Calibration curve generated
- [ ] Systematic biases identified
- [ ] Model quality verdict: Good/Needs-Work

### Phase 2 Success:
- [ ] Historical odds availability confirmed (% coverage)
- [ ] Data quality assessed
- [ ] Cost estimate calculated
- [ ] Go/no-go decision made

### Phase 3 Success (if executed):
- [ ] >85% of predictions matched to betting lines
- [ ] Hit rate against spread calculated
- [ ] Confidence tier analysis completed
- [ ] Problem areas identified
- [ ] Comprehensive report generated

### Phase 4 Success:
- [ ] Daily odds scraping implemented
- [ ] Prediction pipeline integrated with lines
- [ ] End-to-end test successful
- [ ] Documentation updated
- [ ] Ready for next MLB season

---

## Implementation Files Needed

### Analysis Scripts (Phase 1)
```
scripts/mlb/
├── analyze_prediction_accuracy.py     # Raw accuracy analysis
└── generate_accuracy_report.py        # Formatted output
```

### Historical Investigation (Phase 2)
```
scripts/mlb/
├── test_historical_odds_availability.py   # Sample test
└── assess_historical_odds_quality.py      # Quality check
```

### Backfill Scripts (Phase 3)
```
scripts/mlb/
├── backfill_historical_odds.py         # Main backfill
├── match_predictions_to_lines.py       # Re-grading
└── comprehensive_hit_rate_analysis.py  # Full analysis
```

### Pipeline Fixes (Phase 4)
```
predictions/mlb/
├── pitcher_strikeouts_predictor.py    # [MODIFY] Add line lookup
└── worker.py                          # [MODIFY] Query lines first

orchestration/
└── daily_mlb_odds_collection.py       # [NEW] Daily scraping
```

---

## Next Steps

**Immediate Action (You Decide):**

1. **Fast Track** → Run Phase 1 now (30 min)
   - Get immediate accuracy insights
   - See if model is worth analyzing further

2. **Thorough Investigation** → Phase 1 + 2 (90 min)
   - Accuracy analysis + historical odds assessment
   - Make fully informed decision

3. **All-In** → Execute all phases (8-10 hours)
   - Full historical analysis
   - Production pipeline fixes
   - Complete betting system

**My Recommendation**:
Start with **Phase 1 + Phase 2** (90 min total). This gives you:
- Model quality verdict (is it worth pursuing?)
- Historical data feasibility (can we backfill?)
- Informed decision on full backfill vs prospective only

Then make the final call on Phase 3 vs Phase 4 based on results.

---

## Documentation Updates

This document should be read alongside:
- `CURRENT-STATUS.md` - System status
- `ODDS-DATA-STRATEGY.md` - Original betting data plan
- `BASELINE-VALIDATION-RESULTS-2026-01-07.md` - Model training results

**Created**: 2026-01-13
**Next Review**: After Phase 1+2 completion
