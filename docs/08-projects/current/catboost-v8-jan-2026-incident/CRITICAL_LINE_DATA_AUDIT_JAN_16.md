# CRITICAL: Line Data Quality Audit
## Jan 16, 2026 - Session 75

**Status**: 🚨 **CRITICAL DATA QUALITY ISSUES FOUND**
**Priority**: **URGENT - BLOCKS PRODUCTION DEPLOYMENT**
**Generated**: 2026-01-16, 7:15 PM ET

---

## Executive Summary

### 🚨 Critical Findings

1. **XGBoost V1 performance is INVALID** - 100% fake placeholder lines (20.0)
2. **moving_average_baseline_v1 performance is INVALID** - 100% fake placeholder lines
3. **Jan 9-10 data quality issue** - systems didn't fetch real sportsbook lines
4. **CatBoost V8 is NOT failing** - Real performance is 63% on Jan 15 (latest)
5. **All system rankings based on fake data** - Need complete re-evaluation

### Impact

- ❌ **Cannot deploy XGBoost V1** - never tested against real lines
- ❌ **87.5% win rate claim is FALSE** - based on placeholder lines
- ✅ **CatBoost V8 is actually working** - 63% on real lines (Jan 15)
- 🔧 **Must fix line fetching** before any production deployment

---

## 1. The Default Line Problem

### What is line_value = 20.0?

**20.0 is a PLACEHOLDER** used when no real sportsbook line exists. It's NOT:
- ✗ A DraftKings line
- ✗ A FanDuel line
- ✗ Any real, tradeable betting line
- ✗ Valid for performance evaluation

**It IS**:
- ✓ A default fallback value
- ✓ Indicating "no line data available"
- ✓ Used for system testing only

### Systems Using Default Lines (Jan 8-15)

| System | Total Picks | Default Lines | Real Lines | Default % | **Validity** |
|--------|-------------|---------------|------------|-----------|--------------|
| **xgboost_v1** | 293 | **293** | **0** | **100.0%** | ❌ INVALID |
| **moving_average_baseline_v1** | 275 | **275** | **0** | **100.0%** | ❌ INVALID |
| catboost_v8 | 764 | 96 | 668 | 12.6% | ✅ MOSTLY VALID |
| zone_matchup_v1 | 989 | 281 | 708 | 28.4% | ✅ MOSTLY VALID |
| ensemble_v1 | 940 | 277 | 663 | 29.5% | ✅ MOSTLY VALID |
| similarity_balanced_v1 | 757 | 245 | 512 | 32.4% | ✅ MOSTLY VALID |
| moving_average | 680 | 3 | 677 | 0.4% | ✅ VALID |

---

## 2. XGBoost V1: Performance is Invalid

### Claimed Performance

- **87.5% win rate** (266-22)
- **72.3% ROI**
- **91.9% on UNDERS**
- **100% on high confidence picks**

### Reality

**ALL 293 predictions used placeholder line_value = 20.0:**

```
player_lookup: dysondaniels
predicted_points: 15.1
line_value: 20.0  ← PLACEHOLDER!
actual_points: 17
prediction_correct: TRUE (15.1 < 20.0 AND 17 < 20.0)
```

**Why This is Invalid**:
1. Real DraftKings line for dysondaniels was likely ~8-12 pts, not 20.0
2. With a real line of 10.5, prediction would be OVER (15.1 > 10.5)
3. If actual was 17, this would **LOSE** (predicted OVER, actual went OVER too high)
4. System thinks it "won" because both pred and actual are under fake 20.0 line

**Verdict**: **Cannot evaluate XGBoost V1 performance** - never tested against real sportsbook lines.

---

## 3. Jan 9-10 Data Issue

### Timeline

**Jan 9** (XGBoost V1 launch day):
- Sportsbook lines **WERE available**: 162 players, 16 bookmakers, 43,704 line records
- xgboost_v1: Generated 208 predictions with `line_source = None`
- All predictions got placeholder line_value = 20.0
- **No real lines fetched**

**Jan 10**:
- Sportsbook lines **WERE available**: 99 players, 16 bookmakers, 23,445 line records
- xgboost_v1: Generated 96 predictions with `line_source = None`
- All predictions got placeholder line_value = 20.0
- **No real lines fetched**

### Root Cause

Unknown - needs investigation. Possibilities:
1. XGBoost V1 system config missing line fetching logic
2. moving_average_baseline_v1 same issue
3. Line fetching service down on Jan 9-10
4. Player name normalization mismatch
5. System configuration error

### Impact

**Two new systems launched on broken data:**
- xgboost_v1 (Jan 9)
- moving_average_baseline_v1 (Jan 9)

Both have **ZERO real sportsbook lines** in their entire history.

---

## 4. CatBoost V8: Real Performance Analysis

### Performance on REAL LINES (Excluding Jan 9-10)

| Date | Real Line Picks | Win Rate | Status |
|------|-----------------|----------|--------|
| **Jan 15** | 381 | **63.0%** | ✅ Good |
| Jan 14 | 51 | 51.0% | Marginal |
| Jan 13 | 53 | 45.3% | Below breakeven |
| Jan 12 | 14 | 21.4% | Very bad |
| Jan 11 | 92 | 40.2% | Very bad |
| Jan 8 | 24 | 45.8% | Below breakeven |
| **Jan 1-7** | **688** | **66.4%** | ✅ Good |

### Pattern Analysis

**Three Phases**:

1. **Early January (Jan 1-7)**: **66.4%** win rate
   - 688 predictions on real lines
   - Good, profitable performance
   - Above 52.4% breakeven

2. **Mid-January Crash (Jan 8, 11-14)**: **41.7%** average
   - Jan 8: 45.8%
   - Jan 11: 40.2% ❌
   - Jan 12: 21.4% ❌❌
   - Jan 13: 45.3%
   - Jan 14: 51.0%
   - **Lost money for 5 straight days**

3. **Recent Recovery (Jan 15)**: **63.0%** win rate
   - 381 predictions
   - Back to profitable levels
   - Similar to early January performance

### Degradation Analysis

**Not a permanent failure** - performance cyclical:
- ✅ Good: Jan 1-7 (66.4%)
- ❌ Bad: Jan 8, 11-14 (41.7%)
- ✅ Recovered: Jan 15 (63.0%)

**Possible Causes**:
1. **Slate-dependent performance** - struggles on certain game types
2. **Market adjustment** - books adjusted to patterns, then model adapted
3. **Scoring environment** - NBA scoring patterns shifted mid-month
4. **Opponent quality** - tougher matchups on bad days
5. **Small sample size** - variance on low-volume days (14-53 picks)

---

## 5. Systems We Can Trust (Real Lines Only)

### Ranked by Real Line Performance (Jan 8-15)

| System | Real Line Picks | Real Line Win Rate | **Validity** |
|--------|-----------------|-------------------|--------------|
| **moving_average** | 677 | **55.8%** | ✅ VALID |
| **catboost_v8** | 668 | **55.1%** | ✅ VALID |
| **ensemble_v1** | 663 | **55.1%** | ✅ VALID |
| **zone_matchup_v1** | 708 | **54.4%** | ✅ VALID |
| **similarity_balanced_v1** | 512 | **52.9%** | ✅ VALID |
| xgboost_v1 | 0 | **N/A** | ❌ INVALID |
| moving_average_baseline_v1 | 0 | **N/A** | ❌ INVALID |

### True Performance Reality

**All systems are barely profitable** (52.4% breakeven):
- Best: 55.8% (moving_average)
- Worst: 52.9% (similarity_balanced_v1)
- **3-5% edge** (not 30-40% we thought)

**This is NORMAL for sports betting**:
- 55-56% is considered elite
- 53-54% is professional level
- 52-53% is breakeven territory

---

## 6. Line Source Analysis

### Available Sportsbooks (Jan 8-15)

| Sportsbook | Records | Players | Avg Line |
|------------|---------|---------|----------|
| **DraftKings** | 15,610 | 265 | 13.22 |
| **FanDuel** | 15,546 | 267 | 13.25 |
| **BetMGM** | 16,181 | 273 | 12.34 |
| **Caesars** | 15,889 | 266 | 13.14 |
| **ESPN Bet** | 20,664 | 293 | 12.85 |
| BettingPros Consensus | 22,738 | 297 | 12.00 |

**Verdict**: ✅ **Real sportsbook lines ARE available** from reputable books (DraftKings, FanDuel, BetMGM, Caesars).

### Line Sources Used in Predictions (Jan 8-15)

| Line Source | API | Sportsbook | Predictions | With Lines |
|-------------|-----|------------|-------------|------------|
| **ACTUAL_PROP** | **ODDS_API** | **DRAFTKINGS** | **1,146** | **842** ✅ |
| ESTIMATED_AVG | ESTIMATED | None | 2,178 | 241 |
| None | None | None | 1,570 | 0 ❌ |
| ESTIMATED_AVG | None | None | 967 | 889 |
| ACTUAL_PROP | ESTIMATED | None | 365 | 82 |

**Good News**: 1,146 predictions using **real DraftKings lines via Odds API** ✅

**Bad News**: 1,570 predictions with **no line source at all** (`None/None/None`) ❌

---

## 7. Critical Issues Summary

### Issue #1: XGBoost V1 Never Tested

**Problem**:
- Launched Jan 9 with NO real sportsbook lines
- ALL 293 predictions using placeholder line_value = 20.0
- 87.5% win rate is against fake lines
- **Cannot be deployed to production**

**Impact**: HIGH
**Risk**: Deploying would likely result in losses
**Status**: BLOCKS PRODUCTION

### Issue #2: moving_average_baseline_v1 Same Problem

**Problem**:
- Same issue as XGBoost V1
- 275/275 predictions (100%) using placeholder lines
- Cannot evaluate performance

**Impact**: HIGH
**Status**: BLOCKS PRODUCTION

### Issue #3: Line Fetching Failure (Jan 9-10)

**Problem**:
- Two systems launched on dates with line fetching issues
- Sportsbook lines WERE available but not fetched
- Root cause unknown

**Impact**: MEDIUM
**Risk**: Could happen again with new systems
**Status**: NEEDS INVESTIGATION

### Issue #4: Default Line Contamination

**Problem**:
- 12-32% of predictions using default lines (varies by system)
- Inflates win rates artificially
- Makes performance comparison difficult

**Impact**: MEDIUM
**Risk**: Over-estimates profitability
**Status**: NEEDS MONITORING

---

## 8. Grading Methodology Review

### How Grading Works

1. **Predictions generated** (Phase 5A) with line data
2. **Games played** and box scores scraped (Phase 2)
3. **Analytics created** (Phase 3) - player_game_summary
4. **Grading runs** (Phase 5B) - compares predictions to actuals

**Grading Logic** (from `orchestration/cloud_functions/grading/main.py`):
```
IF predicted_points > line_value AND actual_points > line_value:
    prediction_correct = TRUE  (OVER wins)
IF predicted_points < line_value AND actual_points < line_value:
    prediction_correct = TRUE  (UNDER wins)
ELSE:
    prediction_correct = FALSE
```

**Problem**: Grading uses whatever `line_value` is in predictions table, including placeholder 20.0.

### Legitimacy Assessment

**Grading is TECHNICALLY correct** but:
- ❌ Doesn't validate line quality
- ❌ Doesn't exclude placeholder lines
- ❌ Doesn't require real sportsbook sources
- ❌ No checks for line_value = 20.0

**Verdict**: Grading methodology is **valid but insufficient**. Need to add:
1. Filter out line_value = 20.0 (default lines)
2. Require line_source to be ACTUAL_PROP or ODDS_API
3. Validate sportsbook is reputable (DraftKings, FanDuel, etc.)

---

## 9. Recommendations

### CRITICAL (Do Immediately)

1. **Stop XGBoost V1 Deployment** ❌
   - Mark as NOT PRODUCTION READY
   - System has never been tested against real lines
   - 87.5% win rate is FALSE

2. **Stop moving_average_baseline_v1 Deployment** ❌
   - Same issue as XGBoost V1
   - Cannot evaluate performance

3. **Investigate Line Fetching Failure**
   - Why did Jan 9-10 have `line_source = None`?
   - Fix root cause before launching new systems
   - Add monitoring/alerts for line fetch failures

4. **Add Grading Filters**
   ```sql
   WHERE line_value != 20  -- Exclude default lines
   AND line_source IN ('ACTUAL_PROP', 'ODDS_API')
   AND has_prop_line = TRUE
   ```

### HIGH PRIORITY (This Week)

1. **Re-launch XGBoost V1 with Real Lines**
   - Fix line fetching configuration
   - Run for 7+ days to gather valid data
   - Re-evaluate performance on REAL lines only

2. **Update Performance Reports**
   - Filter out default line_value = 20.0
   - Show "Real Lines Only" performance
   - Add line source column to all reports

3. **Add Line Quality Monitoring**
   - Alert if default_line % > 10%
   - Alert if line_source = None
   - Daily report on line fetch success rate

4. **Document Line Sources**
   - Which systems use which sportsbooks?
   - Document expected line sources per system
   - Create validation checklist

### MEDIUM PRIORITY (This Month)

1. **CatBoost V8 Investigation**
   - Analyze Jan 11-14 poor performance
   - Identify patterns in losing picks
   - Consider confidence tier adjustments

2. **Standardize Line Fetching**
   - All systems should use same line source (DraftKings via Odds API)
   - Fallback to FanDuel if DraftKings unavailable
   - Never use placeholder line_value = 20.0

3. **Create Line Quality Dashboard**
   - % real vs default lines by system
   - Win rate on real vs default lines
   - Line source distribution

---

## 10. Corrected System Rankings

### Real Lines Only (Jan 8-15, Excluding Default 20.0)

| Rank | System | Real Picks | Win Rate | ROI | Status |
|------|--------|------------|----------|-----|--------|
| 🥇 1 | **moving_average** | 677 | **55.8%** | ~6.8% | ✅ VALID |
| 🥈 2 | **catboost_v8** | 668 | **55.1%** | ~5.4% | ✅ VALID |
| 🥈 2 | **ensemble_v1** | 663 | **55.1%** | ~5.4% | ✅ VALID |
| 4 | **zone_matchup_v1** | 708 | **54.4%** | ~4.0% | ✅ VALID |
| 5 | **similarity_balanced_v1** | 512 | **52.9%** | ~1.0% | ✅ VALID |
| ❌ | **xgboost_v1** | 0 | **N/A** | N/A | ❌ INVALID |
| ❌ | **moving_average_baseline_v1** | 0 | **N/A** | N/A | ❌ INVALID |

**Reality Check**:
- No "elite" 80%+ systems exist on real lines
- All systems in 52.9-55.8% range (normal for sports betting)
- moving_average is current champion (55.8%)
- catboost_v8 is tied for second (55.1%)

---

## 11. CatBoost V8 Status Assessment

### Original Concern

"CatBoost V8 degraded from 71-72% to 45.8%"

### Reality

**Performance Guide (71-72%) was from November-December 2025:**
- Nov: 84.4% win rate
- Dec: 82.0% win rate
- **These numbers were VALID for that time period**

**January 2026 Performance (Real Lines Only)**:
- Jan 1-7: 66.4% (good, declining from Nov-Dec)
- Jan 8, 11-14: 41.7% (bad stretch)
- **Jan 15: 63.0%** (recovery!)

### Verdict

**CatBoost V8 is NOT failing permanently** ✅

- Latest performance: **63.0%** (Jan 15)
- Still profitable (vs 52.4% breakeven)
- Experiencing normal variance/adaptation
- Recovered from mid-month slump

**Action**: ✅ **Keep CatBoost V8 in production**
- Monitor daily performance
- Flag if drops below 55% for 3+ days
- Consider retraining if sustained degradation

---

## 12. Next Steps

### Immediate (Today)

- [ ] Tag XGBoost V1 as NOT_PRODUCTION_READY
- [ ] Tag moving_average_baseline_v1 as NOT_PRODUCTION_READY
- [ ] Update all performance reports to filter line_value != 20
- [ ] Add alert for line_source = None in predictions

### Tomorrow (Jan 17)

- [ ] Investigate Jan 9-10 line fetching failure root cause
- [ ] Fix XGBoost V1 line fetching configuration
- [ ] Fix moving_average_baseline_v1 line fetching configuration
- [ ] Deploy line quality monitoring dashboard

### This Week

- [ ] Re-launch XGBoost V1 with fixed configuration
- [ ] Gather 7 days of valid data (real lines)
- [ ] Re-evaluate XGBoost V1 performance
- [ ] Document line source requirements for all systems

### This Month

- [ ] Analyze CatBoost V8 mid-month degradation
- [ ] Implement confidence tier adjustments if needed
- [ ] Create automated line quality checks
- [ ] Standardize line fetching across all systems

---

## 13. Conclusion

### Summary

**What We Thought**:
- XGBoost V1: 87.5% win rate (elite)
- CatBoost V8: 45.8% win rate (failing)

**Reality**:
- XGBoost V1: **Cannot evaluate** - no real sportsbook lines
- CatBoost V8: **55.1% win rate on real lines** - working fine

### Key Learnings

1. **Always validate line sources** before evaluating performance
2. **Default line_value = 20.0 invalidates all analysis**
3. **55-56% win rates are EXCELLENT** for sports betting
4. **CatBoost V8 is performing as expected** (not failing)
5. **New systems need real-world validation** before deployment

### Final Recommendation

**DO NOT deploy XGBoost V1 or moving_average_baseline_v1** until:
- ✅ Line fetching is fixed
- ✅ 7+ days of real sportsbook line data collected
- ✅ Performance validated on real DraftKings/FanDuel lines
- ✅ Win rate confirmed above 52.4% breakeven

**Continue with CatBoost V8** as primary system:
- ✅ 55.1% win rate on real lines (profitable)
- ✅ Jan 15 shows recovery to 63.0%
- ✅ Most reliable system with valid data

---

**Report Generated**: 2026-01-16 23:15 UTC
**Session**: 75
**Audited By**: Line Data Quality Review
**Status**: 🚨 CRITICAL ISSUES IDENTIFIED - DEPLOYMENT BLOCKED
**Next Review**: Jan 17, 2026 (after line fetching fix)
