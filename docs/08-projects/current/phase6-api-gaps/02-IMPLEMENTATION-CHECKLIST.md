# Phase 6 API Gaps - Implementation Checklist

**Track progress:** Mark items with ✅ as completed
**Testing:** Each item should be tested before marking complete

---

## Sprint 1: Quick Wins (30 minutes total)

**Target:** Deploy today - immediate data completeness improvements

### File: `tonight_all_players_exporter.py`

#### 1. Add `days_rest` field (5 minutes)
- [ ] Add to player_data dict (line ~385): `'days_rest': p.get('days_rest'),`
- [ ] Test: Verify field appears in JSON output
- [ ] Validate: Check values are numeric (0, 1, 2, 3, etc.)
```bash
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[] | select(.has_line) | .days_rest'
```

#### 2. Add `minutes_avg` field (2 minutes)
- [ ] Add alias for season_mpg: `'minutes_avg': safe_float(p.get('season_mpg')),`
- [ ] Test: Verify matches season_mpg value
- [ ] Validate: Check non-null for players with games played
```bash
jq '.games[0].players[] | {season_mpg, minutes_avg}' all-players.json | head -20
```

#### 3. Fix `game_time` leading whitespace (2 minutes)
- [ ] Change line 108: `FORMAT_TIMESTAMP('%-I:%M %p ET', ...)` (was `%l`)
- [ ] Test: Verify no leading space on times
- [ ] Validate: Check both single-digit (7:00) and double-digit (10:00) hours
```bash
jq '.games[].game_time' all-players.json
```

#### 4. Change confidence to 0.0-1.0 scale (5 minutes)
- [ ] Update line 433: `'confidence': safe_float(p.get('confidence_score')) / 100.0`
- [ ] Test: Verify values are 0.0-1.0 (not 0-100)
- [ ] Validate: Check range for sample of players
```bash
jq '.games[0].players[] | select(.has_line) | .prediction.confidence' all-players.json
```

**IMPORTANT:** This is a breaking change if other consumers expect 0-100 scale.
- [ ] Check if other exporters use confidence (best_bets, predictions, etc.)
- [ ] Update those exporters to match 0.0-1.0 scale

#### 5. Add `recent_form` field (15 minutes)
- [ ] Add calculation logic after line 256:
```python
# Calculate recent form
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
```
- [ ] Add to player_data dict: `'recent_form': recent_form,`
- [ ] Test: Verify logic for known hot/cold players
- [ ] Validate: Check distribution (expect ~20% hot, ~20% cold, ~60% neutral)
```bash
jq '[.games[].players[] | select(.has_line) | .recent_form] | group_by(.) | map({key: .[0], count: length})' all-players.json
```

---

## Sprint 1: Data Quality (30 minutes)

### File: `exporter_utils.py`

#### 6. Add `safe_odds()` helper (15 minutes)
- [ ] Add function to exporter_utils.py:
```python
def safe_odds(odds_value: Optional[int]) -> Optional[int]:
    """
    Validate American odds are in reasonable range.

    American odds typically range from -10000 to +10000.
    Returns None for invalid values (e.g., 199900).
    """
    if odds_value is None:
        return None
    if -10000 <= odds_value <= 10000:
        return odds_value
    return None
```
- [ ] Test: Verify OG Anunoby's 199900 becomes None
- [ ] Validate: Check normal odds pass through unchanged

### File: `tonight_all_players_exporter.py`

#### 7. Apply odds validation (5 minutes)
- [ ] Import safe_odds from exporter_utils
- [ ] Update lines 259-260:
```python
'over_odds': safe_odds(p.get('over_odds')),
'under_odds': safe_odds(p.get('under_odds')),
```
- [ ] Test: Export and verify no >10000 odds values
```bash
jq '[.games[].players[] | select(.props) | .props[].over_odds // 0] | max' all-players.json
jq '[.games[].players[] | select(.props) | .props[].under_odds // 0] | max' all-players.json
```

### File: `all_subsets_picks_exporter.py`

#### 8. Add `player_lookup` to picks output (10 minutes)
- [ ] Check if player_lookup is already in materialized table query
- [ ] If missing, add to pick dict in export method
- [ ] Test: Verify field appears in picks JSON
```bash
curl https://storage.googleapis.com/nba-props-platform-api/v1/picks/2026-02-11.json | \
  jq '.model_groups[0].subsets[0].picks[0] | {player, player_lookup}'
```

---

## Sprint 1: Deploy & Validate

- [ ] Run local tests: `PYTHONPATH=. python data_processors/publishing/tonight_all_players_exporter.py`
- [ ] Check deployment drift: `./bin/check-deployment-drift.sh`
- [ ] Commit changes: `git add . && git commit -m "feat: Add missing fields to tonight API (days_rest, minutes_avg, recent_form)"`
- [ ] Push to trigger auto-deploy: `git push origin main`
- [ ] Verify Cloud Build trigger fired
- [ ] Wait for deployment to complete (~5-10 min)
- [ ] Run Phase 6 export: Trigger via Cloud Scheduler or manual
- [ ] Validate output: Check all 8 new/fixed fields populated
- [ ] Notify frontend team: New fields available

**Validation checklist:**
- [ ] `days_rest` populated for all players
- [ ] `minutes_avg` matches `season_mpg`
- [ ] `game_time` has no leading whitespace
- [ ] `confidence` is 0.0-1.0 range
- [ ] `recent_form` shows Hot/Cold/Neutral distribution
- [ ] No odds values >10000
- [ ] `player_lookup` in picks endpoint

---

## Sprint 2: High-Impact Features (8 hours)

### File: `tonight_all_players_exporter.py`

#### 9. Add `last_10_lines` array (2 hours)

**Step 1: Add query CTE (30 min)**
- [ ] Add CTE after `last_5_stats` (line ~196):
```sql
last_10_with_lines AS (
    -- Get last 10 games WITH lines for accurate O/U calculation
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
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date < @target_date
      AND points_line IS NOT NULL  -- Only games with lines
    GROUP BY player_lookup
)
```

**Step 2: Join CTE (10 min)**
- [ ] Add LEFT JOIN to main query (line ~262):
```sql
LEFT JOIN last_10_with_lines l10l ON gc.player_lookup = l10l.player_lookup
```

**Step 3: Update result processing (1 hour)**
- [ ] Modify `_query_last_10_results` to return lines array
- [ ] Update `_build_games_data` to include lines in output
- [ ] Add to player_data dict:
```python
player_data['last_10_lines'] = last_10_data.get('lines', [])
```

**Step 4: Test & Validate (30 min)**
- [ ] Test: Find player with full 10-game line history
- [ ] Verify arrays match in length: `last_10_points`, `last_10_lines`, `last_10_results`
- [ ] Check player with partial history (e.g., rookie with 5 games)
- [ ] Validate NULL handling for players with no line history
```bash
# Check array lengths match
jq '.games[0].players[] | select(.has_line) | {
  points_len: (.last_10_points | length),
  lines_len: (.last_10_lines | length),
  results_len: (.last_10_results | length)
}' all-players.json | head -10
```

#### 10. Add `prediction.factors` field (6 hours)

**Step 1: Join feature store (30 min)**
- [ ] Add CTE for feature data:
```sql
feature_data AS (
    SELECT
        player_lookup,
        game_date,
        -- Matchup features
        matchup_quality_pct,
        feature_13_value as opponent_def_rating,  -- Feature 13
        feature_14_value as opponent_pace,        -- Feature 14
        -- Quality tracking
        feature_quality_score,
        default_feature_count
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date = @target_date
)
```
- [ ] Join in main query:
```sql
LEFT JOIN feature_data fd ON gc.player_lookup = fd.player_lookup
```

**Step 2: Create factor builder function (3 hours)**
- [ ] Add method to class:
```python
def _build_prediction_factors(
    self,
    player_data: Dict,
    feature_data: Dict,
    last_10_record: Optional[str]
) -> List[str]:
    """
    Build human-readable prediction factors.

    Returns up to 4 factors explaining the prediction.
    """
    factors = []

    # 1. Matchup strength (opponent defense)
    opp_def_rating = feature_data.get('opponent_def_rating')
    if opp_def_rating:
        if opp_def_rating > 115:
            factors.append("Faces weak defense (115+ def rating)")
        elif opp_def_rating < 105:
            factors.append("Faces elite defense (sub-105 def rating)")

    # 2. Historical trend (O/U record)
    if last_10_record:
        try:
            overs, unders = map(int, last_10_record.split('-'))
            total = overs + unders
            if total >= 5:  # Need at least 5 games
                if overs >= 7:
                    factors.append(f"Hot over streak: {overs}-{unders} L10")
                elif unders >= 7:
                    factors.append(f"Cold under streak: {overs}-{unders} L10")
                elif overs >= 5:
                    factors.append(f"Trending over: {overs}-{unders} L10")
                elif unders >= 5:
                    factors.append(f"Trending under: {overs}-{unders} L10")
        except (ValueError, AttributeError):
            pass

    # 3. Rest/Fatigue
    fatigue_level = player_data.get('fatigue_level')
    days_rest = player_data.get('days_rest')
    if fatigue_level == 'fresh' or (days_rest and days_rest >= 3):
        factors.append("Well-rested (3+ days off)")
    elif fatigue_level == 'tired' or (days_rest is not None and days_rest == 0):
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
        if last_5 and season:
            diff = last_5 - season
            factors.append(f"Scoring surge (+{diff:.1f} vs season avg)")
    elif recent_form == 'Cold':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        if last_5 and season:
            diff = abs(last_5 - season)
            factors.append(f"Recent slump (-{diff:.1f} vs season avg)")

    # Return top 4 factors (UI constraint)
    return factors[:4]
```

**Step 3: Integrate into output (30 min)**
- [ ] Call function when building player_data:
```python
# Get feature data for this player
player_feature_data = feature_map.get(player_lookup, {})

# Build factors
factors = self._build_prediction_factors(
    player_data=p,
    feature_data=player_feature_data,
    last_10_record=last_10.get('record')
)

# Add to prediction dict
if p.get('has_line'):
    player_data['prediction'] = {
        'predicted': safe_float(p.get('predicted_points')),
        'confidence': safe_float(p.get('confidence_score')) / 100.0,
        'recommendation': p.get('recommendation'),
        'factors': factors  # NEW
    }
```

**Step 4: Test & Validate (2 hours)**
- [ ] Test with 10 different player types:
  - Star player (high volume)
  - Role player (low volume)
  - Player on hot streak
  - Player on cold streak
  - Back-to-back game
  - Well-rested player
  - Strong matchup (weak defense)
  - Tough matchup (elite defense)
  - High edge (5+)
  - Low edge (<3)

- [ ] Validate factor quality:
  - [ ] No duplicate factors
  - [ ] Max 4 factors per player
  - [ ] Factors are human-readable
  - [ ] Factors are relevant to prediction

- [ ] Edge cases:
  - [ ] Player with no historical data
  - [ ] Player with missing feature data
  - [ ] Player with all NULL values
  - [ ] Ensure no crashes on bad data

```bash
# Sample 10 players with factors
jq '.games[0].players[] | select(.has_line and (.prediction.factors | length > 0)) | {
  name,
  recommendation: .prediction.recommendation,
  factors: .prediction.factors
}' all-players.json | head -50
```

---

## Sprint 2: Best Bets Fix (1 hour)

### File: `best_bets_exporter.py`

#### 11. Fix methodology for current/future dates (1 hour)

**Problem:** Queries `prediction_accuracy` (graded/historical) for current date → 0 results

**Step 1: Add date logic (30 min)**
- [ ] Modify `_query_ranked_predictions` method:
```python
def _query_ranked_predictions(self, target_date: str, top_n: int) -> List[Dict]:
    # Determine if this is a historical (graded) or current/future date
    from datetime import datetime
    target = datetime.strptime(target_date, '%Y-%m-%d').date()
    today = datetime.now().date()

    # Use different table based on date
    if target < today:
        # Historical: Use graded predictions from prediction_accuracy
        source_table = 'nba_predictions.prediction_accuracy'
        # Include actual_points, prediction_correct for graded data
        actual_fields = """
            p.actual_points,
            p.prediction_correct,
        """
    else:
        # Current/Future: Use active predictions from player_prop_predictions
        source_table = 'nba_predictions.player_prop_predictions'
        # These fields don't exist yet
        actual_fields = """
            NULL as actual_points,
            NULL as prediction_correct,
        """
```

**Step 2: Update query template (20 min)**
- [ ] Replace hardcoded table name with variable
- [ ] Add conditional fields
- [ ] Adjust filters for current vs historical:
```python
query = f"""
WITH player_history AS (
    SELECT player_lookup, ...
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date < @target_date
    ...
),
predictions AS (
    SELECT
        p.player_lookup,
        p.predicted_points,
        {actual_fields}  -- Conditional fields
        p.line_value as line_value,
        p.recommendation,
        p.confidence_score,
        ...
    FROM `nba-props-platform.{source_table}` p
    WHERE p.game_date = @target_date
      AND p.system_id = 'catboost_v9'
      AND p.recommendation IN ('UNDER', 'OVER')
      {"AND p.is_active = TRUE" if source_table.endswith('predictions') else ""}
      ...
)
...
"""
```

**Step 3: Test both modes (10 min)**
- [ ] Test historical date (e.g., Feb 9): Should return graded results
- [ ] Test current date (e.g., Feb 11): Should return active predictions
- [ ] Verify tier distribution in both cases
```bash
# Historical
PYTHONPATH=. python data_processors/publishing/best_bets_exporter.py --date 2026-02-09

# Current
PYTHONPATH=. python data_processors/publishing/best_bets_exporter.py --date 2026-02-11
```

- [ ] Validate: Current date should now return >0 picks (was 0)
```bash
jq '.total_picks' best-bets/latest.json
```

---

## Sprint 2: Deploy & Validate

- [ ] Run comprehensive tests:
  - [ ] `last_10_lines` length matches other arrays
  - [ ] `prediction.factors` populated for all lined players
  - [ ] Best bets returns picks for current date
  - [ ] No crashes on edge cases

- [ ] Deploy changes
- [ ] Trigger Phase 6 export
- [ ] Frontend validation:
  - [ ] "Why this pick?" reasoning displays correctly
  - [ ] Historical O/U calculations accurate
  - [ ] Best bets section shows picks

---

## Sprint 3: Enhancements (2 hours)

### File: `tonight_all_players_exporter.py`

#### 12. Add date-specific tonight files (15 minutes)
- [ ] Modify `export()` method to write both files:
```python
def export(self, target_date: str) -> str:
    json_data = self.generate_json(target_date)

    # Current: tonight/all-players.json (always latest)
    self.upload_to_gcs(json_data, 'tonight/all-players.json', 'public, max-age=300')

    # New: tonight/YYYY-MM-DD.json (date-specific, cacheable)
    date_path = f'tonight/{target_date}.json'
    self.upload_to_gcs(json_data, date_path, 'public, max-age=86400')

    return date_path
```
- [ ] Test: Verify both files exist after export
```bash
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-11.json
```

### File: `data_processors/publishing/calendar_exporter.py` (NEW)

#### 13. Create calendar game counts exporter (1 hour)

- [ ] Create new file `calendar_exporter.py`:
```python
"""
Calendar Game Counts Exporter for Phase 6 Publishing

Exports game counts per date for calendar widget.
"""

import logging
from typing import Dict
from datetime import date, timedelta

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class CalendarExporter(BaseExporter):
    """
    Export game counts per date for calendar widget.

    Output file:
    - calendar/game-counts.json - Game counts for past N days

    JSON structure:
    {
        "2026-02-11": 14,
        "2026-02-10": 4,
        "2026-02-09": 12,
        ...
    }
    """

    def generate_json(self, days_back: int = 30) -> Dict[str, int]:
        """
        Generate calendar game counts.

        Args:
            days_back: Number of days to include (default 30)

        Returns:
            Dictionary mapping date strings to game counts
        """
        query = """
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as game_count
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days_back DAY)
          AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)  # Include upcoming week
        GROUP BY game_date
        ORDER BY game_date DESC
        """
        params = [
            bigquery.ScalarQueryParameter('days_back', 'INT64', days_back)
        ]
        results = self.query_to_list(query, params)

        # Convert to {date: count} dict
        game_counts = {}
        for row in results:
            date_str = row['game_date'].strftime('%Y-%m-%d')
            game_counts[date_str] = row['game_count']

        return game_counts

    def export(self, days_back: int = 30) -> str:
        """
        Generate and upload calendar game counts.

        Args:
            days_back: Number of days to include

        Returns:
            GCS path of exported file
        """
        logger.info(f"Exporting calendar game counts ({days_back} days)")

        json_data = self.generate_json(days_back)

        # Upload with short cache (schedule can change)
        path = 'calendar/game-counts.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=1800')

        logger.info(f"Exported {len(json_data)} dates to {path}")
        return gcs_path
```

- [ ] Add to `daily_export.py`:
```python
# In imports section
from data_processors.publishing.calendar_exporter import CalendarExporter

# In EXPORT_TYPES list
EXPORT_TYPES = [
    ...,
    'calendar',  # NEW
]

# In export_date() function
if 'calendar' in export_types:
    try:
        exporter = CalendarExporter()
        path = exporter.export(days_back=30)
        result['paths']['calendar'] = path
        logger.info(f"  Calendar: {path}")
    except Exception as e:
        result['errors'].append(f"calendar: {e}")
        logger.error(f"  Calendar error: {e}")
```

- [ ] Test export:
```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-11 --only calendar
```

- [ ] Validate output:
```bash
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json | jq '.'
```

---

## Sprint 3: Deploy & Validate

- [ ] Deploy all changes
- [ ] Trigger Phase 6 export with calendar
- [ ] Test all new endpoints:
  - [ ] `/tonight/2026-02-11.json` works
  - [ ] `/calendar/game-counts.json` shows 30+ dates
  - [ ] Game counts match schedule

- [ ] Frontend integration testing:
  - [ ] Date picker navigation works
  - [ ] Calendar widget shows game indicators
  - [ ] Historical date browsing functional

---

## Final Validation

### Data Completeness
- [ ] All 192 lined players have complete data:
  - [ ] `days_rest` populated
  - [ ] `minutes_avg` populated
  - [ ] `recent_form` computed
  - [ ] `prediction.factors` (4 factors max)
  - [ ] `last_10_lines` matches `last_10_points` length

### Data Quality
- [ ] No odds values >10000
- [ ] No leading whitespace in `game_time`
- [ ] Confidence is 0.0-1.0 range
- [ ] No crashes on NULL/missing data

### Endpoints
- [ ] `/tonight/all-players.json` - Current date
- [ ] `/tonight/{date}.json` - Date-specific
- [ ] `/calendar/game-counts.json` - Calendar widget
- [ ] `/picks/{date}.json` - Has `player_lookup`
- [ ] `/best-bets/latest.json` - Returns picks for current date

### Frontend Integration
- [ ] All TypeScript interfaces satisfied
- [ ] No console errors on page load
- [ ] "Why this pick?" reasoning displays
- [ ] Calendar widget functional
- [ ] Date navigation works
- [ ] Best bets section populated

---

## Rollback Plan

If issues arise post-deployment:

1. **Revert confidence scale:**
```bash
# Change back to 0-100
'confidence': safe_float(p.get('confidence_score'))  # Remove / 100.0
```

2. **Disable factors:**
```python
# Set factors to empty array temporarily
'factors': []
```

3. **Hotfix deployment:**
```bash
./bin/hot-deploy.sh nba-scrapers  # Phase 6 runs on scrapers service
```

---

## Documentation Updates

After completion:

- [ ] Update `CLAUDE.md` with new fields
- [ ] Add API documentation for new endpoints
- [ ] Create frontend integration guide
- [ ] Document factor generation logic
- [ ] Add to Phase 6 export runbook

---

**Session:** 209
**Owner:** Backend team
**Reviewer:** Frontend team
**Status:** Ready for implementation
