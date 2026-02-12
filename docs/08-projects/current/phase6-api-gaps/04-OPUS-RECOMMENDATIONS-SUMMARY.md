# Opus Review - Key Recommendations & Implementation Updates

**Date:** February 11, 2026
**Reviewer:** Opus (Claude Opus 4.6)
**Status:** ✅ Approved with corrections - Ready for implementation

---

## 🔴 Critical Corrections

### 1. **Factors MUST Be Directional** ⚠️ CRITICAL

**Issue Identified:**
Current proposal generates neutral observations like "Faces weak defense (115+ def rating)" which doesn't explain the recommendation.

**Opus Requirement:**
Factors must support the recommendation. If model says OVER, factor should say "Weak opposing defense favors scoring." If model says UNDER against elite defense, say "Elite opposing defense limits scoring."

**Corrected Implementation:**
```python
def _build_prediction_factors(
    self,
    player_data: Dict,
    feature_data: Dict,
    last_10_record: Optional[str]
) -> List[str]:
    """Build up to 4 directional factors supporting the recommendation."""
    factors = []
    rec = player_data.get('recommendation')  # 'OVER' or 'UNDER'

    # 1. Edge first (Opus priority order)
    predicted = player_data.get('predicted_points')
    line = player_data.get('current_points_line')
    if predicted and line:
        edge = abs(predicted - line)
        if edge >= 5:
            factors.append(f"Strong model conviction ({edge:.1f} point edge)")
        elif edge >= 3:
            factors.append(f"Solid model edge ({edge:.1f} points)")

    # 2. Matchup (directional - only if supports recommendation)
    opp_def_rating = feature_data.get('opponent_def_rating')
    if opp_def_rating:
        if opp_def_rating > 115 and rec == 'OVER':
            factors.append("Weak opposing defense favors scoring")
        elif opp_def_rating < 105 and rec == 'UNDER':
            factors.append("Elite opposing defense limits scoring")
        # Don't mention defense if it contradicts the recommendation

    # 3. Historical trend (directional)
    if last_10_record:
        try:
            overs, unders = map(int, last_10_record.split('-'))
            total = overs + unders
            if total >= 5:
                if overs >= 7 and rec == 'OVER':
                    factors.append(f"Hot over streak: {overs}-{unders} last 10")
                elif unders >= 7 and rec == 'UNDER':
                    factors.append(f"Cold under streak: {overs}-{unders} last 10")
                elif overs >= 5 and rec == 'OVER':
                    factors.append(f"Trending over: {overs}-{unders} last 10")
                elif unders >= 5 and rec == 'UNDER':
                    factors.append(f"Trending under: {overs}-{unders} last 10")
        except (ValueError, AttributeError):
            pass

    # 4. Fatigue (directional)
    fatigue_level = player_data.get('fatigue_level')
    days_rest = player_data.get('days_rest')
    if (fatigue_level == 'fresh' or (days_rest and days_rest >= 3)) and rec == 'OVER':
        factors.append("Well-rested, favors performance")
    elif (fatigue_level == 'tired' or (days_rest is not None and days_rest == 0)) and rec == 'UNDER':
        factors.append("Back-to-back fatigue risk")

    # 5. Recent form (directional)
    recent_form = player_data.get('recent_form')
    if recent_form == 'Hot' and rec == 'OVER':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        if last_5 and season:
            diff = last_5 - season
            factors.append(f"Scoring surge: +{diff:.1f} vs season avg")
    elif recent_form == 'Cold' and rec == 'UNDER':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        if last_5 and season:
            diff = abs(last_5 - season)
            factors.append(f"Recent slump: -{diff:.1f} vs season avg")

    return factors[:4]  # Max 4 factors
```

**Key Principle:** Only include factors that support the recommendation. Contradictory factors confuse users.

---

### 2. **Factor Priority Order: Edge First**

**Opus Recommendation:**
Edge > Matchup > Trend > Fatigue > Form

**Rationale:**
- Edge is the primary signal (what the model is actually saying)
- Matchup and trend explain WHY the model has that edge
- Fatigue and form are secondary context

**Updated in corrected implementation above** ✅

---

### 3. **game_time Fix: Use LTRIM(), Not %-I**

**Issue Identified:**
```python
FORMAT_TIMESTAMP('%-I:%M %p ET', ...)  # %-I NOT VALID in BigQuery
```

**Correct Fix:**
```python
LTRIM(FORMAT_TIMESTAMP('%I:%M %p ET', game_date_est, 'America/New_York'))
```

Or Python post-processing:
```python
'game_time': game.get('game_time', '').lstrip()
```

**Action:** Update implementation checklist with LTRIM() approach

---

### 4. **Confidence Scale Change: SKIP** ❌

**Opus Decision:** Remove from Sprint 1

**Rationale:**
- Frontend already handles division by 100
- Breaking change with zero functional benefit
- Requires updating every exporter
- Deployment coordination risk
- **Negative ROI**

**If needed later:** Add `confidence_normalized` field alongside `confidence`, deprecate old one after frontend migrates

**Action:** Remove from all sprint plans

---

### 5. **Best Bets UNDER-only Filter: KEEP**

**Opus Clarification:**
The UNDER-only filter in best bets is **intentional and should stay**.

**Rationale:**
- Historical accuracy CTE is tuned for UNDER performance
- Model's edge is strongest on UNDER bets
- Expanding to OVER is a methodology change, not a bug fix

**Current Issue:** 0 picks because querying wrong table (prediction_accuracy for current dates)

**Fix:** Table selection logic only, don't change UNDER filter

**Action:** Update implementation to keep UNDER filter

---

## ✅ Approvals

### 1. **prediction.factors: Runtime (Feature Store JOIN)** ✅

**Approved with directional correction above**

**Rationale:**
- Factors are presentation concern, belong in publishing layer
- Can iterate on wording without touching prediction pipeline
- Performance impact negligible (~5s)
- Pre-computing is premature optimization

---

### 2. **last_10_lines: Parallel Arrays** ✅

**Approved exactly as proposed**

**Format:**
```json
{
  "last_10_points": [25, 18, 22, 30, 19],
  "last_10_lines": [20.5, 18.5, 19.5, 21.5, 17.5],
  "last_10_results": ["O", "U", "O", "O", "O"]
}
```

**Null handling:** Variable length arrays (if player has 5 games, return 5-element arrays)

**Don't add:** last_10_dates (not requested, adds complexity)

---

### 3. **Best Bets Date Boundary: target_date < today** ✅

**Approved with implementation note**

**Logic:**
```python
if target_date < today:
    source_table = 'nba_predictions.prediction_accuracy'
else:
    source_table = 'nba_predictions.player_prop_predictions'
```

**Don't over-engineer:** No grading completeness check needed (99% of cases covered)

**Fix fragile string matching:**
```python
# Bad (fragile)
{"AND p.is_active = TRUE" if 'predictions' in source_table else ""}

# Good (explicit)
use_predictions_table = target_date >= today
if use_predictions_table:
    # ... query with is_active = TRUE
else:
    # ... query without is_active
```

---

## 🎯 Revised Sprint Plan

### Sprint 1 - Quick Wins (~45 min)
**Changes from original:**
- ❌ Removed: Confidence scale change (not worth risk)
- ✅ Updated: game_time fix uses LTRIM()
- ⬆️ Slightly increased: 30min → 45min

1. `days_rest` (5 min)
2. `minutes_avg` alias (2 min)
3. `game_time` whitespace fix with LTRIM() (5 min)
4. `recent_form` calculation (15 min)
5. Odds validation with `safe_odds()` (15 min)
6. `player_lookup` in picks (10 min)

**Files:** 3 files
**Deploy:** Push to main → auto-deploy

---

### Sprint 2 - High Impact (~5 hours)
**Changes from original:**
- ⬇️ Reduced estimate: 8h → 5h (runtime approach simpler)
- 🔄 Reordered: last_10_lines first (simpler, unblocks O/U)
- ⚠️ Critical: Factors MUST be directional

1. `last_10_lines` array (2 hours) - **DO FIRST**
2. `prediction.factors` with **directional logic** (2-3 hours)
3. Best bets table selection fix (1 hour)

**Files:** 2 files
**Deploy:** Push to main → auto-deploy → trigger Phase 6 export

---

### Sprint 3 - Enhancements (~1.5 hours)
**Changes from original:**
- ⬇️ Reduced: 2h → 1.5h

1. Date-specific tonight files (15 min)
2. Calendar game counts (1 hour)

**Files:** 2 files (1 new)
**Deploy:** Push to main → auto-deploy → trigger Phase 6 export

---

## 📋 Design Decisions

### Performance
**Opus:** Non-issue, don't optimize

- 30s → 37s with 540s timeout (7% usage)
- Future scaling to 500 players: ~96s (18% usage)
- **Action:** Don't cache, don't batch, just implement

---

### Data Consistency
**Opus:** Graceful degradation, no blocking

- If Phase 4 hasn't run yet → feature store returns NULL → factors = []
- Don't block early exports (data fills progressively)
- Players missing from feature store still get predictions (just no factors)

**Action:** LEFT JOIN feature store, accept empty factors early in the day

---

### Error Handling
**Opus:** Show partial data, never hide players

- Player with `has_line: true` always appears (even with empty factors)
- Empty factors array `[]` is correct degradation
- Don't add explanatory strings like "Insufficient historical data"
- Don't fail export if >50% have incomplete factors (expected at 2:30 AM)
- Injured players with lines: still show prediction

**Action:** No validation blocking, graceful degradation throughout

---

### Schema Evolution
**Opus:** No versioning needed

- Don't add `api_version` field (single consumer we control)
- Don't rename `season_mpg` → add `minutes_avg` as alias (both fields)
- No breaking changes

**Action:** Additive changes only, maintain backward compatibility

---

## 🔧 Implementation Notes

### Best Bets Table Selection - Corrected Approach

**Explicit boolean flag (not string matching):**

```python
def _query_ranked_predictions(self, target_date: str, top_n: int) -> List[Dict]:
    from datetime import datetime
    target = datetime.strptime(target_date, '%Y-%m-%d').date()
    today = datetime.now().date()

    # Explicit flag
    use_predictions_table = target >= today

    # Build query based on flag
    if use_predictions_table:
        query = """
        WITH player_history AS (...),
        predictions AS (
            SELECT
                p.player_lookup,
                NULL as actual_points,
                NULL as prediction_correct,
                p.predicted_points,
                p.current_points_line as line_value,
                p.recommendation,
                p.confidence_score,
                ...
            FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
            WHERE p.game_date = @target_date
              AND p.system_id = 'catboost_v9'
              AND p.is_active = TRUE
              AND p.recommendation IN ('UNDER', 'OVER')  -- Keep UNDER/OVER both
              ...
        )
        """
    else:
        query = """
        WITH player_history AS (...),
        predictions AS (
            SELECT
                p.player_lookup,
                p.actual_points,
                p.prediction_correct,
                p.predicted_points,
                p.line_value,
                p.recommendation,
                p.confidence_score,
                ...
            FROM `nba-props-platform.nba_predictions.prediction_accuracy` p
            WHERE p.game_date = @target_date
              AND p.system_id = 'catboost_v9'
              AND p.recommendation IN ('UNDER', 'OVER')  -- Keep UNDER/OVER both
              ...
        )
        """
```

**Key:** UNDER-only filtering happens in the tier classification WHERE clause (line 230+), not the table selection. Don't change it.

---

### game_time Whitespace - Two Options

**Option A: BigQuery LTRIM (RECOMMENDED)**
```sql
LTRIM(FORMAT_TIMESTAMP('%I:%M %p ET', game_date_est, 'America/New_York')) as game_time
```

**Option B: Python post-processing**
```python
'game_time': game.get('game_time', '').lstrip()
```

**Test before deploying** - Verify LTRIM works in BigQuery

---

## 📊 Updated Effort Estimates

| Sprint | Original | Revised | Savings |
|--------|----------|---------|---------|
| Sprint 1 | 30 min | 45 min | -15 min (added validation) |
| Sprint 2 | 8 hours | 5 hours | **+3 hours** |
| Sprint 3 | 2 hours | 1.5 hours | **+30 min** |
| **TOTAL** | **10.5 hours** | **~7 hours** | **+3.5 hours savings** |

**Why reduced:**
- Confidence scale change removed (was 5min but had deployment risk)
- Runtime factors simpler than estimated (no worker changes)
- Calendar exporter simpler than estimated

---

## ✅ Implementation Checklist Updates

### Critical Changes to Make

1. **Factor generation:**
   - ✅ Make all factors directional
   - ✅ Reorder priority: Edge > Matchup > Trend > Fatigue > Form
   - ✅ Pass `recommendation` to function
   - ✅ Only include factors that support recommendation

2. **game_time fix:**
   - ✅ Use LTRIM() not %-I
   - ✅ Test in BigQuery before deploying

3. **Confidence scale:**
   - ❌ Remove from Sprint 1
   - ❌ Remove from all plans
   - 📝 Document as "future enhancement if needed"

4. **Best bets:**
   - ✅ Explicit boolean flag (not string matching)
   - ✅ Keep UNDER-only filter (don't change methodology)
   - ✅ Separate query templates for clarity

5. **Schema:**
   - ✅ Add `minutes_avg` as alias (keep `season_mpg` too)
   - ✅ No breaking changes
   - ✅ Graceful degradation (empty arrays, not validation errors)

---

## 🚀 Ready for Implementation

**Status:** ✅ All critical decisions validated
**Next Steps:**
1. Update implementation checklist with corrections
2. Begin Sprint 1 (45 min quick wins)
3. Test and deploy
4. Move to Sprint 2 with directional factors

**Key Reminders:**
- Factors MUST be directional
- Use LTRIM() for game_time
- Skip confidence scale change
- Keep UNDER-only filter in best bets
- Graceful degradation throughout
- Deploy after each sprint

---

**Review Complete:** ✅
**Approved By:** Opus (Claude Opus 4.6)
**Implementation Ready:** Yes
**Estimated Total Effort:** ~7 hours (down from 10.5h)
