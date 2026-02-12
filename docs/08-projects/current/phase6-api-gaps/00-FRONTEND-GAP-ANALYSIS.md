# Phase 6 API Gaps - Frontend Integration Analysis

**Date:** February 11, 2026
**Source:** Frontend team API endpoint review
**Status:** Analysis complete - ready for prioritization and implementation

---

## Executive Summary

The frontend team reviewed all API endpoints and identified **6 working endpoints, 4 missing endpoints, and multiple data quality issues**. Overall coverage is good (192/481 players with lines, up from 21→192 since last review), but several critical gaps block features and user experience improvements.

**Critical Finding:** 31 players (16% of lined players) still return all-dash `last_10_results` because they lack historical lines in `player_game_summary`. Frontend is using an inaccurate workaround (today's line for historical games).

---

## P0 - Data Quality Issues (Affects Accuracy)

### 1. 31 Players with All-Dash `last_10_results`

**Impact:** High - Frontend shows inaccurate O/U history for 16% of lined players
**Severity:** Data integrity issue

**Root Cause:**
- Query in `tonight_all_players_exporter.py` (line 284-303) pulls `over_under_result` from `player_game_summary`
- `over_under_result` is only populated when `points_line` exists (see `prop_calculator.py` line 48)
- 31 players lack historical lines in `player_game_summary` because:
  - Player is a rookie/new to rotation (no historical props data)
  - Historical line coverage gaps (pre-2024 season data incomplete)
  - Player recently became relevant (wasn't getting lines before)

**Current Workaround (Frontend):**
```typescript
// api-adapters.ts line 135-150
// Computes O/U from last_10_points vs CURRENT line
// Inaccurate because historical lines were different
```

**Solution Options:**

**Option A: Add `last_10_lines` field (RECOMMENDED)**
```sql
-- In tonight_all_players_exporter.py, add query for historical lines
WITH last_10_lines AS (
  SELECT
    player_lookup,
    ARRAY_AGG(points_line ORDER BY game_date DESC LIMIT 10) as historical_lines
  FROM nba_analytics.player_game_summary
  WHERE game_date < @target_date AND points_line IS NOT NULL
  GROUP BY player_lookup
)
```
- Pros: Accurate, frontend can compute correct O/U, useful for sparklines
- Cons: Adds 10-50 bytes per player (minimal)
- Estimate: 2 hours (add query CTE, add to JSON output, test)

**Option B: Default to dashes for players without history**
- Keep current behavior, document it as expected for rookies/new players
- Pros: Simple, no changes needed
- Cons: Frontend still shows incomplete data

**Recommendation:** Option A. Gives frontend accurate data for historical O/U calculations.

**Files to Change:**
- `data_processors/publishing/tonight_all_players_exporter.py`: Add `last_10_lines` CTE and output field
- Test with players who have partial history

---

### 2. Bogus Odds Data (`over_odds: 199900`)

**Impact:** Medium - Bad data visible to users (though frontend doesn't render it)
**Severity:** Data quality issue

**Example:** OG Anunoby has `over_odds: 199900` (clearly invalid)

**Root Cause:**
- Query pulls odds from `bettingpros_player_points_props` (line 209-220)
- BettingPros API occasionally returns malformed odds
- No validation before writing to export

**Solution:**
```python
# In tonight_all_players_exporter.py, add validation before output
def safe_odds(odds_value):
    """Validate American odds are in reasonable range."""
    if odds_value is None:
        return None
    # American odds typically range from -10000 to +10000
    # Most common: -300 to +300
    if -10000 <= odds_value <= 10000:
        return odds_value
    return None  # Invalid, return None instead
```

Apply to lines 259-260:
```python
'over_odds': safe_odds(p.get('over_odds')),
'under_odds': safe_odds(p.get('under_odds')),
```

**Estimate:** 30 minutes

**Files to Change:**
- `data_processors/publishing/tonight_all_players_exporter.py`: Add `safe_odds()` helper
- `data_processors/publishing/exporter_utils.py`: Consider adding to shared utils

---

### 3. Live Grading Stuck Game (Feb 10 shows "in-progress")

**Impact:** Low - Stale data in historical view
**Severity:** Pipeline issue

**Root Cause:**
- Live grading exporter queries `nba_raw.nbac_schedule` for game status
- If final game finishes after exporter runs, status stays at "2" (in-progress)
- No final sweep to re-export once all games are done

**Solution:**
- Add final grading run 4-6 hours after last game's scheduled start time
- Or: Check `game_status = 3` in schedule, re-export if changed since last run

**Recommendation:** Low priority - this is a 1-time issue, will auto-resolve tomorrow

**Files to Check:**
- `data_processors/publishing/live_grading_exporter.py`
- Scheduler configuration for grading runs

---

## P1 - Missing Fields (Features Blocked)

### 4. `prediction.factors` Always Missing (0/192)

**Impact:** HIGH - Blocks "why this pick" feature for users
**Severity:** Major UX gap

**Root Cause:**
- `prediction.factors` field is never populated in `tonight_all_players_exporter.py`
- Field exists in frontend TypeScript interface but backend doesn't send it

**What Frontend Wants:**
```json
{
  "prediction": {
    "predicted": 26.2,
    "confidence": 0.85,
    "recommendation": "OVER",
    "factors": [
      "High usage when star teammate out",
      "Strong vs opponent defense ranking",
      "Hit over in 7 of last 10"
    ]
  }
}
```

**Solution:**

**Phase 1 - Basic Factors (Week 1)**
Use existing feature store data to generate human-readable factors:

```python
def _build_prediction_factors(self, player_data: Dict, feature_data: Dict) -> List[str]:
    """Build human-readable prediction factors."""
    factors = []

    # Matchup factors (features 5-8, 13-14)
    if feature_data.get('matchup_quality_pct', 0) >= 85:
        opp_def_rating = feature_data.get('feature_13_value')  # opponent_def_rating
        if opp_def_rating and opp_def_rating > 115:
            factors.append("Faces weak defense (115+ def rating)")
        elif opp_def_rating and opp_def_rating < 105:
            factors.append("Faces strong defense (sub-105 def rating)")

    # Historical trend (last 10 O/U record)
    last_10_record = player_data.get('last_10_record')
    if last_10_record:
        overs, unders = map(int, last_10_record.split('-'))
        if overs >= 7:
            factors.append(f"Hot streak: {overs}-{unders} over last 10")
        elif unders >= 7:
            factors.append(f"Cold streak: {overs}-{unders} over last 10")

    # Fatigue
    fatigue_level = player_data.get('fatigue_level')
    if fatigue_level == 'fresh':
        factors.append("Well-rested (3+ days)")
    elif fatigue_level == 'tired':
        factors.append("Playing on short rest")

    # Edge size
    edge = abs(player_data.get('predicted_points', 0) - player_data.get('current_points_line', 0))
    if edge >= 5:
        factors.append(f"Strong model edge ({edge:.1f} points)")

    return factors[:4]  # Max 4 factors for UI
```

**Phase 2 - Advanced Factors (Future)**
- Injury context ("Star teammate out")
- Matchup history ("Averages 28 vs this opponent")
- Pace/usage adjustments
- Shot zone advantages

**Estimate:**
- Phase 1: 4-6 hours (basic factors from existing data)
- Phase 2: 2-3 days (requires new feature engineering)

**Files to Change:**
- `data_processors/publishing/tonight_all_players_exporter.py`: Add `_build_prediction_factors()` method
- Join with `ml_feature_store_v2` to access feature values
- Add `factors` to prediction dict (line 431-435)

**Recommendation:** HIGH PRIORITY - This is the #1 requested feature from frontend

---

### 5. `days_rest` Never Populated (0/192)

**Impact:** Medium - UI component ready but no data
**Severity:** Missing feature

**Root Cause:**
- Field exists in query (line 205, 244) from `upcoming_player_game_context`
- Field IS in the data, but NOT being output to JSON

**Solution:**
```python
# Line 385 in tonight_all_players_exporter.py
'days_rest': p.get('days_rest'),  # Already queried, just needs to be added to output
```

**Estimate:** 5 minutes

**Files to Change:**
- `data_processors/publishing/tonight_all_players_exporter.py`: Add line 385 (already in comment above!)

**Recommendation:** QUICK WIN - Add in next deployment

---

### 6. `recent_form` Never Populated (0/192)

**Impact:** Low - Nice-to-have stat
**Severity:** Enhancement

**What Is This?:**
Frontend expects a string like "Hot" / "Cold" / "Neutral" based on recent performance vs season average.

**Solution:**
```python
# Add to player_data dict
last_5_ppg = p.get('last_5_ppg')
season_ppg = p.get('season_ppg')

if last_5_ppg and season_ppg:
    diff = last_5_ppg - season_ppg
    if diff >= 3:
        recent_form = 'Hot'
    elif diff <= -3:
        recent_form = 'Cold'
    else:
        recent_form = 'Neutral'
else:
    recent_form = None

player_data['recent_form'] = recent_form
```

**Estimate:** 15 minutes

**Files to Change:**
- `data_processors/publishing/tonight_all_players_exporter.py`: Add `recent_form` calculation

---

### 7. `minutes_avg` Never Populated (0/192)

**Impact:** Low - Duplicate of `season_mpg` which IS populated
**Severity:** Schema mismatch

**Root Cause:**
- Frontend expects `minutes_avg`
- Backend sends `season_mpg` (same data, different name)

**Solution:**
```python
# Option A: Add alias (RECOMMENDED)
player_data['minutes_avg'] = safe_float(p.get('season_mpg'))

# Option B: Rename field (breaking change for existing consumers)
player_data['season_mpg'] = safe_float(p.get('season_mpg'))
```

**Estimate:** 2 minutes

**Recommendation:** Add `minutes_avg` as alias, keep `season_mpg` for backward compatibility

---

### 8. `player_lookup` Missing in Picks Endpoint

**Impact:** Medium - Frontend has to derive from player name (fragile)
**Severity:** Schema gap

**Root Cause:**
- `/picks/{date}.json` exporter (`subset_materializer.py`) includes `player_lookup` in materialized table
- But `all_subsets_picks_exporter.py` may not be outputting it

**Solution:**
Check `all_subsets_picks_exporter.py` - if `player_lookup` is queried but not output, add to pick dict.

**Estimate:** 30 minutes (investigate + fix)

**Files to Check:**
- `data_processors/publishing/all_subsets_picks_exporter.py`
- `data_processors/publishing/subset_materializer.py` (line 128 shows it's stored)

---

### 9. `results/latest.json` Stale (Feb 10 Data Missing)

**Impact:** Low - Historical data lag
**Severity:** Pipeline timing issue

**Root Cause:**
- Results exporter runs as part of Phase 6 daily export
- Feb 10 games may not have been graded yet when export ran
- Export script doesn't wait for grading to complete

**Solution:**
- Ensure grading runs BEFORE results export
- Or: Results export should check if grading is complete before running

**Recommendation:** Monitor - if this is consistent, add grading check to export script

---

## P2 - New Endpoints (Unlock Features)

### 10. `tonight/{YYYY-MM-DD}.json` - Historical Date Browsing (404)

**Impact:** Medium - Date picker doesn't work
**Severity:** Missing feature

**Current State:**
- Only `/tonight/all-players.json` exists (always current date)
- Frontend date picker hits `/tonight/2026-02-10.json` → 404

**Options:**

**Option A: Generate date-specific files**
```python
# In tonight_all_players_exporter.py
def export(self, target_date: str) -> str:
    # Keep current: tonight/all-players.json
    self.upload_to_gcs(json_data, 'tonight/all-players.json', 'public, max-age=300')

    # Add: tonight/YYYY-MM-DD.json
    self.upload_to_gcs(json_data, f'tonight/{target_date}.json', 'public, max-age=86400')
```

**Option B: Remove date picker from frontend**
- Document that `/tonight/` is current-date-only
- Frontend removes historical browsing feature

**Recommendation:** Option A if we want historical browsing, Option B if not

**Estimate:** 15 minutes (Option A)

---

### 11. `calendar/game-counts.json` - Calendar Widget (404)

**Impact:** Low - Nice-to-have for UX
**Severity:** Enhancement

**What Frontend Wants:**
```json
{
  "2026-02-11": 14,
  "2026-02-10": 4,
  "2026-02-09": 12,
  ...
}
```

**Solution:**
```python
# New exporter: calendar_exporter.py
class CalendarExporter(BaseExporter):
    def generate_json(self, days_back: int = 30) -> Dict[str, int]:
        query = """
        SELECT game_date, COUNT(DISTINCT game_id) as game_count
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days_back DAY)
        GROUP BY game_date
        ORDER BY game_date DESC
        """
        # Return as {date: count} dict
```

**Estimate:** 1 hour (new exporter + add to daily export)

---

### 12. `news/latest.json` - News Integration (404)

**Impact:** Low - Feature not implemented yet
**Severity:** Future enhancement

**Status:** Deferred - news scraping not yet implemented

---

## P3 - Schema Alignment (Nice-to-Have)

### 13. Confidence Scale (0-100 vs 0.0-1.0)

**Current:** Backend sends `confidence: 85` (0-100 scale)
**Frontend:** Divides by 100 → `0.85`

**Recommendation:**
- Backend change to 0.0-1.0 would be cleaner
- But this is cosmetic - frontend handles it fine
- **Priority:** Low

**If changing:**
```python
# Line 433 in tonight_all_players_exporter.py
'confidence': safe_float(p.get('confidence_score')) / 100.0
```

**Breaking Change Risk:** If other consumers expect 0-100 scale

---

### 14. `game_time` Leading Whitespace

**Current:** `" 7:00 PM ET"`
**Expected:** `"7:00 PM ET"`

**Root Cause:**
```python
# Line 108 in tonight_all_players_exporter.py
FORMAT_TIMESTAMP('%l:%M %p ET', ...)  # %l = space-padded hour
```

**Solution:**
```python
FORMAT_TIMESTAMP('%-I:%M %p ET', ...)  # %-I = no padding
```

**Estimate:** 2 minutes

---

### 15. Best Bets Methodology Too Restrictive

**Current:** 0 picks for Feb 11 (UNDER only filter = no results)
**Frontend:** Shows empty best bets section

**Root Cause:**
- `best_bets_exporter.py` line 230: `AND p.recommendation IN ('UNDER', 'OVER')`
- But also queries from `prediction_accuracy` which only has graded (historical) data
- For today's date, no graded predictions exist yet → 0 results

**Solution:**

**Option A: Query from `player_prop_predictions` instead (for future dates)**
```python
# Use prediction_accuracy for historical (graded) dates
# Use player_prop_predictions for current/future dates
if target_date <= today:
    query_table = 'nba_predictions.prediction_accuracy'
else:
    query_table = 'nba_predictions.player_prop_predictions'
```

**Option B: Remove UNDER-only filter**
- Line 230 already allows both OVER and UNDER
- Issue is querying wrong table for ungraded dates

**Recommendation:** Option A - Check if date is historical or future, query appropriate table

**Estimate:** 1 hour

**Files to Change:**
- `data_processors/publishing/best_bets_exporter.py`: Add date-based table selection logic

---

### 16. Profile Field Mismatches

**Impact:** Low - Frontend adapts to backend schema
**Severity:** Documentation gap

**Mismatches:**
- API: `summary.team` → Frontend expects: `team_abbr`
- API: `fg = "8/17"` (string) → Frontend expects: `fg_makes`, `fg_attempts` (numbers)
- API: `three = "3/7"` → Frontend expects: `three_makes`, `three_attempts`
- API: `ft = "2/2"` → Frontend expects: `ft_makes`, `ft_attempts`

**Recommendation:**
- Keep current format (frontend will adapt)
- Or: Add parsed fields alongside string format (backward compatible)

**If adding parsed fields:**
```python
# In player_profile_exporter.py
game_log_entry['fg_makes'] = int(fg.split('/')[0])
game_log_entry['fg_attempts'] = int(fg.split('/')[1])
```

**Priority:** Low - frontend handles this fine

---

## Implementation Priority Matrix

| Priority | Item | Impact | Effort | ROI |
|----------|------|--------|--------|-----|
| **P0** | 4. `prediction.factors` | HIGH | 6h | HIGH |
| **P0** | 5. `days_rest` | MED | 5min | HIGH |
| **P1** | 1. `last_10_lines` array | HIGH | 2h | HIGH |
| **P1** | 2. Bogus odds validation | MED | 30min | MED |
| **P1** | 6. `recent_form` | LOW | 15min | MED |
| **P1** | 7. `minutes_avg` alias | LOW | 2min | HIGH |
| **P1** | 8. `player_lookup` in picks | MED | 30min | MED |
| **P2** | 15. Best bets methodology | HIGH | 1h | HIGH |
| **P2** | 10. Date-specific tonight files | MED | 15min | MED |
| **P2** | 11. Calendar game counts | LOW | 1h | LOW |
| **P3** | 14. `game_time` trim whitespace | LOW | 2min | LOW |
| **P3** | 13. Confidence scale | LOW | 5min | LOW |

**Recommended Sprint 1 (Quick Wins - 4 hours):**
1. ✅ `days_rest` (5min)
2. ✅ `minutes_avg` (2min)
3. ✅ `game_time` trim (2min)
4. ✅ Confidence scale (5min)
5. ✅ `recent_form` (15min)
6. ✅ Bogus odds validation (30min)
7. ✅ `player_lookup` in picks (30min)
8. ✅ `last_10_lines` array (2h)

**Recommended Sprint 2 (High-Impact Features - 1 day):**
1. ✅ `prediction.factors` Phase 1 (6h)
2. ✅ Best bets methodology fix (1h)

**Recommended Sprint 3 (Enhancements - 2 hours):**
1. ✅ Date-specific tonight files (15min)
2. ✅ Calendar game counts (1h)

---

## Files to Modify (Summary)

| File | Changes | Lines |
|------|---------|-------|
| `tonight_all_players_exporter.py` | Add factors, days_rest, recent_form, minutes_avg, last_10_lines, trim game_time, fix confidence | Multiple |
| `best_bets_exporter.py` | Fix table selection for future dates | 1 method |
| `all_subsets_picks_exporter.py` | Add player_lookup to output | 1 line |
| `exporter_utils.py` | Add safe_odds() helper | New function |
| `calendar_exporter.py` | NEW FILE | Full file |
| `daily_export.py` | Add calendar export | 10 lines |

---

## Testing Checklist

- [ ] Validate `last_10_lines` matches `last_10_results` length
- [ ] Verify `prediction.factors` renders correctly for 10 sample players
- [ ] Check `days_rest` populates for all players
- [ ] Test `recent_form` calculation for hot/cold/neutral cases
- [ ] Validate odds filtering removes 199900 outliers
- [ ] Verify best bets returns >0 picks for current date
- [ ] Test date-specific tonight files for historical dates
- [ ] Validate calendar game counts for past 30 days

---

## Next Steps

1. **Review with team:** Discuss priority matrix and sprint allocation
2. **User approval:** Get sign-off on Sprint 1-3 scope
3. **Create tasks:** Break down into trackable work items
4. **Implement:** Start with Sprint 1 quick wins
5. **Deploy & validate:** Push changes, verify with frontend team
6. **Document:** Update API documentation with new fields

---

**Document Created:** Session 209
**Owner:** Backend team
**Reviewer:** Frontend team
**Status:** Ready for implementation planning
