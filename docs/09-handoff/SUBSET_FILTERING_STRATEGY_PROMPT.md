# Subset Filtering Strategy - Comprehensive Context Prompt
## For Fresh Chat Session Analysis
**Created**: 2026-01-16, Session 75
**Purpose**: Provide complete context for designing optimal pick filtering and subset strategies
**Use**: Copy entire "PROMPT FOR CHAT" section below into new chat session

---

## PROMPT FOR CHAT

I need help designing an optimal filtering and subset strategy for NBA player prop prediction systems. Here's the complete context:

### 1. CRITICAL DISCOVERY: Placeholder Line Issue

**Problem Found**: Some prediction systems were evaluated against fake "placeholder" lines (value = 20.0) instead of real DraftKings/sportsbook lines, making their performance metrics invalid.

**Affected Systems**:
- `xgboost_v1`: 100% placeholder lines (293/293 picks on Jan 9-10)
- `moving_average_baseline_v1`: 100% placeholder lines (275/275 picks on Jan 9-10)
- `catboost_v8`: Had placeholder lines Nov 4 - Dec 19, 2025; real lines started Dec 20, 2025

**Valid Data Only**:
- CatBoost V8: Dec 20, 2025 - Jan 15, 2026 (4 weeks, 1,625 real line picks)
- XGBoost V1: NONE - needs relaunch with real lines
- Other systems: Need validation (check if line_value != 20.0)

### 2. CURRENT SYSTEM PERFORMANCE (Real Lines Only)

#### Overall Rankings (Jan 8-15, 2026, Real Lines Only)

| System | Real Line Picks | Win Rate | Status |
|--------|----------------|----------|---------|
| moving_average | 677 | 55.8% | ✅ Best |
| catboost_v8 | 668 | 55.1% | ✅ Good |
| ensemble_v1 | 663 | 55.1% | ✅ Good |
| zone_matchup_v1 | 708 | 54.4% | ✅ OK |
| similarity_balanced_v1 | 512 | 52.9% | ✅ OK |
| xgboost_v1 | 0 | N/A | ❌ Invalid |
| moving_average_baseline_v1 | 0 | N/A | ❌ Invalid |

**Breakeven**: 52.4% win rate (to overcome -110 odds)

#### CatBoost V8 Detailed Performance

**Full Season (Real Lines, Dec 20, 2025 - Jan 15, 2026)**:
- Total: 1,625 picks, 825 wins, **50.8% win rate** overall
- December (Dec 20-31): 1,319 picks, 784 wins, **59.4% win rate** ✅
- January (Jan 1-15): 1,625 picks, 825 wins, **50.8% win rate** ⚠️

**Weekly Breakdown**:
| Week | Dates | Win Rate | Trend |
|------|-------|----------|-------|
| Week 1 | Dec 20-26 | 60.8% | ✅ Strong |
| Week 2 | Dec 27-31 | 56.0% | ✅ Solid |
| Week 3 | Jan 1-7 | 66.4% | ✅ **Best** |
| Week 4 | Jan 8-14 | 42.4% | ❌ **Worst** |
| Latest | Jan 15 | 51.8% | ⬆️ Recovering |

**Notable**: Jan 11-13 had severe dip (35.6% win rate), appears to be variance/outlier.

### 3. CONFIDENCE TIER ANALYSIS (CatBoost V8)

**Current Filtering**:
- ❌ NO confidence-based filtering exists in code
- Only rejects picks with confidence < 60%
- All other picks (60-100%) are published

**Performance by Confidence Tier** (Dec 20, 2025 - Jan 15, 2026, Real Lines):

| Confidence Tier | Picks | Wins | Win Rate | Avg Error | % of Volume |
|----------------|-------|------|----------|-----------|-------------|
| **Very High (≥92%)** | 287 | 206 | **71.8%** ✅ | 3.05 pts | 18% |
| **High (86-92%)** | 710 | 410 | **57.7%** ✅ | 4.18 pts | 44% |
| **88-90% SUB-TIER** | 166 | 83 | **50.0%** ⚠️ | 4.67 pts | 10% |
| **Medium High (80-86%)** | 390 | 186 | **47.7%** ❌ | 5.79 pts | 24% |
| **Medium Low (74-80%)** | 186 | 88 | **47.3%** ❌ | 5.54 pts | 11% |
| **Low (60-74%)** | 52 | 25 | **48.1%** ❌ | 6.87 pts | 3% |

**Key Observations**:
1. Clear performance cliff between ≥86% and <86%
2. ≥92% tier is ELITE (71.8% win rate - matches the original 71% claim!)
3. 88-90% sub-tier is at breakeven (50.0%) - concerning
4. Everything <86% is losing money (<52.4% breakeven)
5. 62% of all picks (confidence <86%) are unprofitable

**Question**: Should we filter out 88-90%? Or is it just 88-89% that's bad?

### 4. OVER vs UNDER PERFORMANCE

**Aggregate Performance** (All systems, Jan 8-15, Real Lines):

| Type | Picks | Win Rate | Net Profit ($100/pick) | ROI |
|------|-------|----------|----------------------|-----|
| UNDER | 3,000 | 68.8% | $98,129 | 32.7% |
| OVER | 1,698 | 60.8% | $30,519 | 18.0% |

**CatBoost V8 Breakdown**:
- UNDERS: Higher volume, better performance historically
- OVERS: Lower volume, still profitable but less so

### 5. HISTORICAL CONTEXT

**CatBoost V8 Timeline**:
- **Oct 2021 - Apr 2024**: Model training period
- **Nov 4, 2025**: First deployment (but with placeholder lines ❌)
- **Dec 20, 2025**: Real DraftKings lines integrated ✅
- **Dec 20 - Jan 15**: Only 4 weeks of valid performance data

**Original Performance Guide Claimed**: 71-72% win rate
- ✅ CORRECT for confidence ≥92% tier (71.8% actual)
- ❌ INCORRECT for overall (50.8% actual, not 71%)
- Guide was based on placeholder line data (invalid)

**No Previous Season Data**: CatBoost V8 with real lines only exists for 4 weeks total.

### 6. ARCHITECTURE QUESTION

**Current State**: All systems generate all predictions with minimal filtering

**Two Approaches Under Consideration**:

**Option A: Foundation Layer (System Level)**
- Modify catboost_v8.py to only output picks with confidence ≥ 86%
- Pros: Cleaner data, less noise
- Cons: Can't analyze filtered-out picks, harder to A/B test, code changes required

**Option B: Subset Layer (Query Level)**
- Keep catboost_v8 generating ALL picks (foundation never changes)
- Create "virtual systems" via SQL queries: `catboost_v8_premium`, `catboost_v8_quality`
- Pros: Flexible, easy A/B testing, rapid iteration, stable historical data
- Cons: More data storage, need to manage subset definitions

**Proposed Architecture** (Option B):
```
Layer 1: Foundation (catboost_v8, xgboost_v1, etc.)
  ↓ Generate ALL picks, minimal filtering
Layer 2: Subsets (catboost_v8_premium, catboost_v8_quality, etc.)
  ↓ SQL-based filtering, rapid iteration
Layer 3: User Selection (users choose which subset to follow)
```

### 7. EXISTING SYSTEMS INVENTORY

**Production Systems** (Need Real Line Validation):
1. `catboost_v8` - CatBoost ML model (33 features)
2. `xgboost_v1` - XGBoost ML model (NEEDS RELAUNCH - no valid data)
3. `moving_average` - Statistical baseline
4. `moving_average_baseline_v1` - Enhanced version (NEEDS RELAUNCH)
5. `ensemble_v1` - Ensemble of multiple models
6. `zone_matchup_v1` - Rule-based matchup system
7. `similarity_balanced_v1` - Similar game matching

**Only validated with real lines**: catboost_v8, moving_average, ensemble_v1, zone_matchup_v1, similarity_balanced_v1

### 8. QUESTIONS TO ANSWER

Please help me design the optimal filtering strategy by answering:

#### A. Confidence Tier Filtering
1. Should we filter at confidence ≥86%, ≥88%, ≥90%, or ≥92%?
2. What's the optimal threshold for the 88-90% sub-tier issue?
   - Should we create a "donut" filter (≥86% EXCLUDING 88-90%)?
   - Or is the entire 88-90% range acceptable?
3. Should different systems have different confidence thresholds?

#### B. Subset Strategy Design
1. What subsets should we create? Examples:
   - `catboost_v8_premium` (confidence ≥92%)
   - `catboost_v8_quality` (confidence 86-92%, possibly excluding 88-90%)
   - `catboost_v8_premium_unders` (≥92% + UNDER only)
   - `consensus_3plus` (3+ systems agree on direction)
   - `high_edge_picks` (|predicted - line| > 2.5)

2. How should we tier/categorize subsets?
   - Elite tier (≥65% expected win rate)
   - Quality tier (55-65% expected win rate)
   - Volume tier (52-55% expected win rate)

3. Should we create cross-system subsets?
   - Multi-system consensus picks
   - Best-of-breed (top system per player type)

#### C. Architecture Decisions
1. Foundation vs Layers:
   - Should base systems filter heavily (Option A)?
   - Or keep base systems clean and filter via subsets (Option B)?

2. How many subset variations to support?
   - Start small (3-5 subsets) and expand?
   - Or create comprehensive suite (20+ subsets) from day 1?

3. How to handle A/B testing?
   - Should we version subsets (catboost_v8_premium_v1, v2, v3)?
   - Or create parallel variants (catboost_v8_premium, catboost_v8_ultra)?

#### D. Risk Management
1. What's the optimal portfolio approach?
   - Bet only elite tier?
   - Bet elite + quality with different stakes?
   - Diversify across multiple subsets?

2. Volume considerations:
   - Premium tier (≥92%) = only 18% of picks (~5-10 per day)
   - Quality tier (86-92%) = 44% of picks (~15-20 per day)
   - Is low volume on elite tier acceptable?

3. Handling bad streaks:
   - Jan 11-13 was 35.6% win rate (3 days)
   - Should we pause betting after X consecutive bad days?
   - Or trust long-term performance?

#### E. Implementation Priorities
1. What should we build first?
   - Simple confidence cutoff (≥92%)?
   - Sophisticated multi-factor subsets?
   - A/B test framework?

2. How to validate subset performance?
   - Backtest on Dec 20 - Jan 15 data?
   - Wait for 7+ days of new data?
   - Both?

3. Monitoring strategy:
   - Daily performance reports per subset?
   - Alerts when subset underperforms?
   - Automated subset deactivation?

### 9. CONSTRAINTS & REQUIREMENTS

**Must Have**:
- Only use real DraftKings/sportsbook lines (line_value != 20.0)
- Maintain historical data integrity (don't delete old predictions)
- Track performance independently per subset
- Alert on unexpected performance drops

**Nice to Have**:
- Easy to create new subsets (SQL only, no code deployments)
- A/B testing capability
- User-facing subset selection
- Automated subset optimization

**Current Data Limitations**:
- CatBoost V8: Only 4 weeks of real line data
- XGBoost V1: No valid data yet (needs relaunch)
- Limited sample size for statistical confidence

### 10. DELIVERABLES REQUESTED

Please provide:

1. **Recommended Filtering Thresholds**
   - Specific confidence cutoffs for each system
   - Handling of 88-90% sub-tier
   - Justification based on data

2. **Subset Design Specification**
   - List of 5-10 initial subsets to create
   - Filter criteria for each
   - Expected performance and volume
   - Risk tier assignment

3. **Architecture Recommendation**
   - Foundation vs Layers (which approach?)
   - Implementation roadmap (phases/priorities)
   - Data schema (if needed)

4. **Risk Management Strategy**
   - Portfolio allocation across subsets
   - Bankroll management guidelines
   - Alert thresholds
   - Bad streak handling protocol

5. **Validation Plan**
   - How to backtest proposed subsets
   - Minimum data requirements before going live
   - Success criteria for each subset

6. **Next Steps / Action Items**
   - Prioritized list of what to build first
   - What additional data analysis is needed
   - Timeline estimate

---

## ADDITIONAL CONTEXT

### Current File Locations
- System code: `predictions/worker/prediction_systems/catboost_v8.py`
- Performance data: `nba-props-platform.nba_predictions.prediction_accuracy`
- Predictions table: `nba-props-platform.nba_predictions.player_prop_predictions`

### Key Code Insights
- No confidence filtering exists in catboost_v8.py (lines 409-433)
- Confidence calculation: base 75 + quality bonuses + consistency bonuses (lines 373-407)
- Only filter: confidence < 60% becomes "PASS" recommendation (line 419)

### Recent Documents Created
1. `CATBOOST_V8_HISTORICAL_ANALYSIS.md` - Full performance timeline
2. `SUBSET_SYSTEM_ARCHITECTURE.md` - Proposed layered architecture
3. `PLACEHOLDER_LINE_ELIMINATION_PLAN.md` - Fix for fake line issue
4. `PREDICTION_SYSTEMS_REFERENCE.md` - System tracking reference

### Assumptions You Can Make
- Breakeven win rate: 52.4% (for -110 odds)
- Target ROI: 10%+ (good), 20%+ (excellent)
- User base: Sophisticated bettors willing to be selective
- Volume tolerance: Users prefer quality over quantity

---

## END OF PROMPT

**Instructions for Use**:
1. Copy everything in the "PROMPT FOR CHAT" section (between the two horizontal rules)
2. Paste into a fresh Claude chat session (claude.ai or API)
3. The fresh session will have all context needed to provide comprehensive filtering recommendations
4. Review recommendations and implement prioritized action items

**Expected Output**: Comprehensive filtering strategy with specific thresholds, subset designs, architecture decisions, and implementation roadmap.

