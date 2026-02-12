# Phase 6 API Gaps - Technical Review Request

**Date:** February 11, 2026
**Reviewer:** Opus
**Context:** Frontend team identified 16 API gaps. Analysis complete, need validation on technical approach before implementation.

---

## Background

Frontend team reviewed all Phase 6 API endpoints and identified:
- 31 players (16% of lined players) with inaccurate O/U history
- `prediction.factors` field missing (0/192 players) - #1 frontend request
- Best bets endpoint returns 0 picks for current dates
- Multiple missing fields that block UX features

Full analysis: `00-FRONTEND-GAP-ANALYSIS.md`

---

## Technical Decisions Needing Review

### 1. `prediction.factors` Implementation Approach ⭐ HIGH PRIORITY

**Problem:**
Frontend wants human-readable reasoning for predictions (e.g., "Why recommend OVER?"). Currently this field is never populated.

**Proposed Solution:**
Generate factors from existing `ml_feature_store_v2` data and prediction context:

```python
def _build_prediction_factors(
    self,
    player_data: Dict,
    feature_data: Dict,
    last_10_record: Optional[str]
) -> List[str]:
    """Build up to 4 human-readable factors."""
    factors = []

    # 1. Matchup strength (opponent defense)
    opp_def_rating = feature_data.get('opponent_def_rating')  # feature_13_value
    if opp_def_rating:
        if opp_def_rating > 115:
            factors.append("Faces weak defense (115+ def rating)")
        elif opp_def_rating < 105:
            factors.append("Faces elite defense (sub-105 def rating)")

    # 2. Historical trend (O/U record)
    if last_10_record:
        overs, unders = map(int, last_10_record.split('-'))
        if overs >= 7:
            factors.append(f"Hot over streak: {overs}-{unders} L10")
        elif unders >= 7:
            factors.append(f"Cold under streak: {overs}-{unders} L10")

    # 3. Rest/Fatigue
    fatigue_level = player_data.get('fatigue_level')
    days_rest = player_data.get('days_rest')
    if fatigue_level == 'fresh' or (days_rest and days_rest >= 3):
        factors.append("Well-rested (3+ days off)")
    elif fatigue_level == 'tired' or days_rest == 0:
        factors.append("Back-to-back game (fatigue risk)")

    # 4. Model conviction (edge size)
    predicted = player_data.get('predicted_points')
    line = player_data.get('current_points_line')
    if predicted and line:
        edge = abs(predicted - line)
        if edge >= 5:
            factors.append(f"Strong model edge ({edge:.1f} points)")
        elif edge >= 3:
            factors.append(f"Solid model edge ({edge:.1f} points)")

    # 5. Recent form vs season average
    recent_form = player_data.get('recent_form')
    if recent_form == 'Hot':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        diff = last_5 - season
        factors.append(f"Scoring surge (+{diff:.1f} vs season avg)")
    elif recent_form == 'Cold':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        diff = abs(last_5 - season)
        factors.append(f"Recent slump (-{diff:.1f} vs season avg)")

    return factors[:4]  # UI constraint: max 4 factors
```

**Questions for Opus:**

1. **Data sources:** Is using `ml_feature_store_v2` for factors appropriate, or should we compute fresh from raw data?
   - Pro: Feature store already has curated signals
   - Con: Adds dependency on Phase 4 completion

2. **Factor priority:** Should edge size be weighted higher than historical trends?
   - Current order: Matchup → Trend → Fatigue → Edge → Form
   - Alternative: Edge → Matchup → Trend → Fatigue → Form

3. **Threshold values:** Are these reasonable?
   - Def rating 115+ = weak, <105 = elite
   - 7+ O/U in last 10 = streak
   - 3+ points vs season = hot/cold
   - 5+ edge = strong, 3+ = solid

4. **Missing signals:** What should we add in Phase 2?
   - Injury context ("Star teammate out")
   - Matchup history ("Averages 28 vs this opponent")
   - Usage rate changes
   - Pace/tempo adjustments
   - Shot zone advantages

5. **Performance:** Will joining feature store for 192 players slow down export?
   - Current export: ~30s for all players
   - Adding feature store JOIN: estimate +5-10s?

**Alternative Considered:**
Store pre-computed factors in `player_prop_predictions` table during prediction time.
- Pro: Faster export (no runtime computation)
- Con: Requires worker changes, regeneration of historical data

**Recommendation Needed:** Phase 1 approach (feature store JOIN) vs pre-compute in worker?

---

### 2. `last_10_lines` Array Solution

**Problem:**
31 players have all-dash O/U results because they lack historical lines in `player_game_summary`. Frontend computes O/U using TODAY's line for historical games (inaccurate).

**Current Query (Broken):**
```sql
-- Only returns O/U result if historical line existed
WITH recent_games AS (
    SELECT
        player_lookup,
        over_under_result,  -- NULL if no points_line in history
        points
    FROM player_game_summary
    WHERE game_date < @target_date
    QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) <= 10
)
```

**Proposed Solution:**
Add separate CTE to query historical lines:

```sql
last_10_with_lines AS (
    SELECT
        player_lookup,
        ARRAY_AGG(
            STRUCT(
                game_date,
                points,
                points_line,
                over_under_result
            )
            ORDER BY game_date DESC
            LIMIT 10
        ) as last_10_games
    FROM player_game_summary
    WHERE game_date < @target_date
      AND points_line IS NOT NULL  -- Only games with lines
    GROUP BY player_lookup
)
```

**Output Format:**
```json
{
  "last_10_points": [25, 18, 22, 30, 19, 21, 24, 17, 23, 20],
  "last_10_lines": [20.5, 18.5, 19.5, 21.5, 17.5, 19.5, 20.5, 16.5, 19.5, 18.5],
  "last_10_results": ["O", "U", "O", "O", "O", "O", "O", "O", "O", "O"]
}
```

Frontend can accurately compute: `last_10_points[i] >= last_10_lines[i] ? "O" : "U"`

**Questions for Opus:**

1. **Data size:** Adding 10 floats per player (40-80 bytes). With 192 lined players, adds ~15KB to 150KB payload (10% increase). Acceptable?

2. **Null handling:** What if player only has 5 games with lines in history?
   - Option A: Return 5-element array (frontend handles variable length)
   - Option B: Pad with nulls to 10 elements
   - Option C: Return empty array if <10 games

3. **Historical accuracy:** Should we also add `last_10_dates` to show WHEN these games were?
   - Useful for "3 of last 4" vs "7 of last 10 but 5 weeks ago"
   - Adds another 10 strings (100 bytes)

4. **Alternative approach:** Instead of separate arrays, return structured history:
```json
"last_10_history": [
  {"date": "2026-02-10", "points": 25, "line": 20.5, "result": "O"},
  {"date": "2026-02-08", "points": 18, "line": 18.5, "result": "U"},
  ...
]
```
Pro: More structured, easier to extend
Con: Larger payload (200+ bytes per player)

**Recommendation Needed:** Separate arrays (current proposal) vs structured history?

---

### 3. Best Bets Methodology Fix

**Problem:**
Best bets exporter returns 0 picks for current/future dates because it queries `prediction_accuracy` table (graded historical data only).

**Current Code:**
```python
def _query_ranked_predictions(self, target_date: str, top_n: int):
    query = """
    SELECT ...
    FROM `nba-props-platform.nba_predictions.prediction_accuracy` p
    WHERE p.game_date = @target_date
      AND p.system_id = 'catboost_v9'
    """
```

**Proposed Fix:**
```python
def _query_ranked_predictions(self, target_date: str, top_n: int):
    from datetime import datetime
    target = datetime.strptime(target_date, '%Y-%m-%d').date()
    today = datetime.now().date()

    # Select table based on whether date is historical or current/future
    if target < today:
        # Historical: Use graded predictions
        source_table = 'nba_predictions.prediction_accuracy'
        actual_fields = "p.actual_points, p.prediction_correct,"
    else:
        # Current/Future: Use active predictions
        source_table = 'nba_predictions.player_prop_predictions'
        actual_fields = "NULL as actual_points, NULL as prediction_correct,"

    query = f"""
    SELECT
        p.player_lookup,
        {actual_fields}
        p.predicted_points,
        ...
    FROM `nba-props-platform.{source_table}` p
    WHERE p.game_date = @target_date
      AND p.system_id = 'catboost_v9'
      {"AND p.is_active = TRUE" if 'predictions' in source_table else ""}
    """
```

**Questions for Opus:**

1. **Date boundary:** Should we use `target < today` or `target <= today`?
   - `<`: Today's games use predictions table (before grading)
   - `<=`: Today's games use accuracy table (after grading)
   - Issue: Games grade throughout the night, table choice depends on WHEN export runs

2. **Grading race condition:** If export runs at 2 AM, some games from "yesterday" may still be in progress.
   - Option A: Check if grading complete before deciding table
   - Option B: Always use predictions table for game_date >= yesterday
   - Option C: Query both tables, prioritize graded if exists

3. **Field compatibility:** `prediction_accuracy` has extra fields (actual_points, prediction_correct, absolute_error). How to handle?
   - Current: Use NULL for ungraded dates
   - Frontend: Shows "PENDING" when these fields are NULL
   - Works, but should we explicitly mark as pending?

4. **Table schema drift:** What if these tables diverge in schema?
   - Should we create a view that unifies both?
   - Or document which fields are safe to query from both?

**Recommendation Needed:** Date boundary logic and grading race condition handling?

---

### 4. Priority Matrix & Sprint Allocation

**Proposed Allocation:**

| Sprint | Items | Hours | Rationale |
|--------|-------|-------|-----------|
| Sprint 1 | 7 quick wins | 0.5h | Low-hanging fruit, immediate impact |
| Sprint 2 | prediction.factors + last_10_lines + best_bets | 8h | High-impact features |
| Sprint 3 | Date navigation + calendar | 2h | Nice-to-have enhancements |

**Questions for Opus:**

1. **Sprint 1 scope:** Should we include odds validation and player_lookup in Sprint 1, or defer to Sprint 2?
   - Current: Included in Sprint 1 (total 30 min)
   - Alternative: Only do the 5 trivial fields in Sprint 1, others in Sprint 2

2. **Sprint 2 prioritization:** Should prediction.factors come before or after last_10_lines?
   - Current order: Implement both in parallel (different files)
   - Alternative: Do last_10_lines first (simpler, unblocks accurate O/U), then factors

3. **Testing allocation:** Estimated 6 hours for prediction.factors, but how much should be testing vs implementation?
   - Current: 3h implement, 2h test, 1h edge cases
   - Does this seem reasonable?

4. **Deployment strategy:** Should we deploy after each sprint, or batch all 3?
   - Current plan: Deploy after each sprint for incremental validation
   - Alternative: Batch all changes, single deployment (faster but riskier)

**Recommendation Needed:** Sprint scope and deployment cadence?

---

### 5. Performance & Scalability Concerns

**Current Export Performance:**
- `tonight_all_players_exporter.py`: ~30 seconds for 481 players (192 with lines)
- Bottleneck: Individual player queries for last_10_results (192 queries)

**Proposed Changes Add:**
1. Feature store JOIN (1 query, all players)
2. last_10_lines CTE (already queried, just restructured)
3. Factor generation logic (Python, per player)

**Estimated New Performance:**
- Feature store JOIN: +5s (one-time query for 192 players)
- Factor generation: +2s (192 * ~10ms per player)
- **Total: 30s → 37s** (23% increase)

**Questions for Opus:**

1. **Acceptable slowdown?** Export currently runs in ~30s, new version ~37s. Phase 6 has 540s timeout.
   - Is 23% slowdown acceptable for the added value?
   - Should we optimize before adding features?

2. **Batch optimization:** Could we batch factor generation?
   - Current: Per-player function call (192 calls)
   - Alternative: Vectorize factor logic (single pass over all players)
   - Trade-off: Code complexity vs performance

3. **Caching opportunity:** Should we cache feature store data?
   - Phase 4 runs before Phase 6 export
   - Feature store data is immutable for a given game_date
   - Could cache in Redis/Memcache with game_date key
   - Trade-off: Complexity vs marginal speed gain

4. **Future growth:** What if we scale to 500 lined players (currently 192)?
   - 37s * (500/192) = ~96s
   - Still well under 540s timeout
   - Should we design for 1000 players? Or optimize when we hit 500?

**Recommendation Needed:** Performance optimization priority?

---

## Architecture & Design Questions

### 6. Data Consistency

**Current State:**
- `tonight_all_players_exporter.py` pulls from 6 different tables:
  - `upcoming_player_game_context`
  - `player_prop_predictions`
  - `player_composite_factors`
  - `nbac_injury_report`
  - `player_game_summary`
  - `bettingpros_player_points_props`
  - (NEW) `ml_feature_store_v2`

**Questions:**
1. **Join consistency:** What if player exists in predictions but not in feature store?
   - Current: LEFT JOIN, feature_data will be NULL
   - Impact: Factors will be empty (matchup/edge factors missing)
   - Is this acceptable, or should we block predictions without features?

2. **Temporal consistency:** All tables should be for same game_date, but:
   - `player_game_summary` is historical (<game_date)
   - `upcoming_player_game_context` is future (=game_date)
   - `ml_feature_store_v2` is current (=game_date)
   - Could they be out of sync if Phase 4 hasn't run yet?

3. **Data freshness:** Export runs multiple times per day (2:30 AM, 10 AM, 2 PM, 6 PM).
   - Early runs: Feature store may not exist yet (Phase 4 pending)
   - Late runs: Feature store complete
   - Should we add readiness check before export?

**Recommendation Needed:** How to handle partial data availability?

---

### 7. Schema Evolution

**Proposed New Fields:**
```json
{
  "days_rest": 2,
  "minutes_avg": 32.5,
  "recent_form": "Hot",
  "last_10_lines": [20.5, 18.5, ...],
  "prediction": {
    "factors": ["...", "...", "...", "..."],
    "confidence": 0.85  // Changed from 85
  }
}
```

**Questions:**

1. **Breaking change:** `confidence` changes from 0-100 to 0.0-1.0.
   - Other exporters (best_bets, predictions) also use confidence
   - Should we update ALL exporters at once?
   - Or add a `confidence_pct` field and deprecate `confidence`?

2. **Field naming:** Frontend requested `minutes_avg`, we have `season_mpg`.
   - Option A: Add `minutes_avg` as alias, keep `season_mpg`
   - Option B: Rename to `minutes_avg`, remove `season_mpg` (breaking)
   - Which is cleaner long-term?

3. **Versioning:** Should we add an `api_version` field to JSON?
   - Enables frontend to detect schema changes
   - Useful for gradual rollout
   - Example: `"api_version": "2.1.0"`

4. **Backward compatibility:** Current consumers:
   - Frontend (props-web)
   - Internal analytics scripts
   - Potentially mobile app (future)
   - Should we maintain v1 endpoints while rolling out v2?

**Recommendation Needed:** Breaking change strategy and versioning approach?

---

## Edge Cases & Error Handling

### 8. Null/Missing Data Scenarios

**Scenarios to Handle:**

1. **Rookie with 0 historical games:**
   - `last_10_lines` = empty array
   - `last_10_results` = empty array
   - `season_ppg` = NULL
   - `recent_form` = NULL (can't compute)
   - `prediction.factors` = ??? (what can we say?)

2. **Player missing from feature store:**
   - Phase 4 didn't run OR
   - Player filtered out by quality gate
   - Should we show prediction without factors, or block prediction entirely?

3. **Injured player with line:**
   - Sportsbooks may still offer line
   - Should we show "Out - don't bet" in factors?
   - Or suppress prediction entirely?

4. **Line exists but no prediction:**
   - Player failed quality gate (Session 141 zero tolerance)
   - Should they appear in export with `has_line: true` but no prediction?
   - Or exclude from export?

**Questions for Opus:**

1. **Graceful degradation:** Should we show partial data or hide player entirely?
   - Current: Show player with NULL fields
   - Alternative: Only show players with complete data
   - Which provides better UX?

2. **Error messaging:** Should factors include explanations for missing data?
   - Example: ["Insufficient historical data (rookie)"]
   - Or just return empty array?

3. **Validation:** Should export fail if too many players have incomplete data?
   - Example: If >50% have NULL factors, something is wrong
   - Should we alert instead of silently exporting?

**Recommendation Needed:** Error handling philosophy?

---

## Summary of Questions

### Critical (Block implementation):
1. **prediction.factors:** Feature store JOIN vs pre-compute in worker?
2. **last_10_lines:** Separate arrays vs structured history object?
3. **Best bets:** Date boundary logic (`<` vs `<=` today)?
4. **Confidence scale:** Breaking change strategy (all exporters at once)?

### Important (Affect design):
5. **Factor priority:** Edge-first vs matchup-first ordering?
6. **Performance:** 23% slowdown acceptable?
7. **Data consistency:** How to handle Phase 4 not complete yet?
8. **Schema evolution:** Versioning and backward compatibility strategy?

### Nice-to-have (Can decide during implementation):
9. **Threshold values:** Are def_rating 115+/105- reasonable?
10. **Missing signals:** What to add in Phase 2?
11. **Null handling:** Show partial data or hide player?
12. **Sprint allocation:** Current 3-sprint plan vs alternatives?

---

## Recommendation Request

**Please review and provide:**

1. ✅ Validation on technical approaches (factors, last_10_lines, best_bets)
2. ✅ Recommendations on critical decisions (pre-compute vs runtime, arrays vs objects)
3. ⚠️ Warnings on potential issues (performance, consistency, edge cases)
4. 💡 Suggestions for improvements or alternatives
5. 📊 Assessment of priority matrix and sprint allocation

**Particular focus areas:**
- Prediction factors implementation (biggest unknown)
- Performance impact estimates
- Breaking change strategy (confidence scale)
- Error handling philosophy

---

**Review documents:**
- `00-FRONTEND-GAP-ANALYSIS.md` - Full technical analysis
- `01-QUICK-REFERENCE.md` - Implementation snippets
- `02-IMPLEMENTATION-CHECKLIST.md` - Task breakdown

**Context files:**
- `data_processors/publishing/tonight_all_players_exporter.py` (main file to modify)
- `data_processors/publishing/best_bets_exporter.py` (best bets fix)

**Thank you for the review!** 🙏
