# Phase 6 API Gaps - Corrected Implementation Plan

**Date:** February 11, 2026
**Status:** ✅ Opus-Reviewed and Approved
**Total Effort:** ~7 hours (down from 10.5h)

---

## 🚀 Sprint 1: Quick Wins (45 minutes)

### File: `tonight_all_players_exporter.py`

#### 1. Add `days_rest` field (5 minutes) ✅ UNCHANGED
```python
# Line ~385
'days_rest': p.get('days_rest'),  # Already queried, just add to output
```

**Test:**
```bash
jq '.games[0].players[] | select(.has_line) | .days_rest' all-players.json
```

---

#### 2. Add `minutes_avg` alias (2 minutes) ✅ UNCHANGED
```python
# Line ~386
'minutes_avg': safe_float(p.get('season_mpg')),  # Alias for frontend compatibility
'season_mpg': safe_float(p.get('season_mpg')),   # Keep for backward compatibility
```

**Opus:** Add both fields, no breaking changes

**Test:**
```bash
jq '.games[0].players[] | {season_mpg, minutes_avg}' all-players.json | head -10
```

---

#### 3. Fix `game_time` leading whitespace (5 minutes) ⚠️ CORRECTED

**OLD (INCORRECT):**
```sql
FORMAT_TIMESTAMP('%-I:%M %p ET', ...)  -- %-I NOT VALID in BigQuery
```

**NEW (CORRECT):**
```sql
-- Line 108
LTRIM(FORMAT_TIMESTAMP('%I:%M %p ET', game_date_est, 'America/New_York')) as game_time
```

**Opus:** %-I is not valid BigQuery syntax. Use LTRIM() to remove leading space.

**Test:**
```bash
jq '.games[].game_time' all-players.json
# Should see: "7:00 PM ET" not " 7:00 PM ET"
```

---

#### 4. Add `recent_form` field (15 minutes) ✅ UNCHANGED
```python
# After line 256, add calculation:
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

# Add to player_data dict:
player_data['recent_form'] = recent_form
```

**Test:**
```bash
jq '[.games[].players[] | select(.has_line) | .recent_form] | group_by(.) | map({key: .[0], count: length})' all-players.json
# Should see distribution: ~20% Hot, ~20% Cold, ~60% Neutral
```

---

### File: `exporter_utils.py`

#### 5. Add `safe_odds()` helper (15 minutes) ✅ UNCHANGED
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

**Test:**
```python
assert safe_odds(199900) is None  # Invalid
assert safe_odds(-110) == -110    # Valid
assert safe_odds(None) is None    # Null
```

---

### File: `tonight_all_players_exporter.py`

#### 6. Apply odds validation (included in #5)
```python
# Line ~259-260
'over_odds': safe_odds(p.get('over_odds')),
'under_odds': safe_odds(p.get('under_odds')),
```

**Test:**
```bash
jq '[.games[].players[] | select(.props) | .props[].over_odds // 0] | max' all-players.json
# Should be <= 10000
```

---

### File: `all_subsets_picks_exporter.py`

#### 7. Add `player_lookup` to picks output (10 minutes) ✅ UNCHANGED
```python
# Check if player_lookup is in the materialized table query
# Add to pick dict in export method:
{
    'player': pick['player_name'],
    'player_lookup': pick['player_lookup'],  # ADD THIS
    'team': pick['team'],
    ...
}
```

**Test:**
```bash
curl https://storage.googleapis.com/nba-props-platform-api/v1/picks/2026-02-11.json | \
  jq '.model_groups[0].subsets[0].picks[0] | {player, player_lookup}'
```

---

### Sprint 1: Deploy & Validate

```bash
# Test locally first
PYTHONPATH=. python -c "
from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
exporter = TonightAllPlayersExporter()
data = exporter.generate_json('2026-02-11')
print(f'Players: {data[\"total_players\"]}')
print(f'Sample player fields: {list(data[\"games\"][0][\"players\"][0].keys())}')
"

# Commit and push
git add .
git commit -m "feat: Add missing fields to tonight API (Sprint 1)

- Add days_rest field (already queried)
- Add minutes_avg alias for season_mpg
- Fix game_time leading whitespace with LTRIM()
- Add recent_form calculation (Hot/Cold/Neutral)
- Add safe_odds() validation
- Add player_lookup to picks endpoint

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin main

# Verify Cloud Build trigger
gcloud builds list --region=us-west2 --limit=1

# Wait for deployment (~5-10 min)
# Trigger Phase 6 export
# Validate output
```

**Validation:**
- [ ] All 7 changes deployed
- [ ] No errors in export logs
- [ ] Fields populated in JSON
- [ ] No odds >10000
- [ ] game_time has no leading space

---

## ⭐ Sprint 2: High-Impact Features (5 hours)

**Opus Reordering:** Do last_10_lines FIRST (simpler, unblocks O/U)

---

### Part A: last_10_lines Array (2 hours)

### File: `tonight_all_players_exporter.py`

#### Step 1: Add query CTE (30 min)
```sql
-- After last_5_stats CTE (line ~196), add:
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

#### Step 2: Join CTE (10 min)
```sql
-- In main query (line ~262), add:
LEFT JOIN last_10_with_lines l10l ON gc.player_lookup = l10l.player_lookup
```

#### Step 3: Update `_query_last_10_results` to return lines (1 hour)
```python
def _query_last_10_results(self, player_lookups: List[str], before_date: str) -> Dict[str, List]:
    """Query last 10 over/under results AND lines for players."""
    if not player_lookups:
        return {}

    query = """
    WITH recent_games AS (
        SELECT
            player_lookup,
            game_date,
            over_under_result,
            points,
            points_line  -- ADD THIS
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date < @before_date
          AND player_lookup IN UNNEST(@player_lookups)
          AND points_line IS NOT NULL  -- Only games with lines
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) <= 10
    )
    SELECT
        player_lookup,
        ARRAY_AGG(
            STRUCT(over_under_result, points, points_line)
            ORDER BY game_date DESC
        ) as last_10
    FROM recent_games
    GROUP BY player_lookup
    """

    # ... existing params ...
    results = self.query_to_list(query, params)

    # Build lookup map
    last_10_map = {}
    for r in results:
        player = r['player_lookup']
        games = r.get('last_10', [])

        results_list = []
        points_list = []
        lines_list = []  # ADD THIS

        for g in games:
            if isinstance(g, dict):
                ou = g.get('over_under_result')
                pts = g.get('points')
                line = g.get('points_line')  # ADD THIS
            else:
                ou = getattr(g, 'over_under_result', None)
                pts = getattr(g, 'points', None)
                line = getattr(g, 'points_line', None)  # ADD THIS

            # O/U result
            if ou == 'OVER':
                results_list.append('O')
            elif ou == 'UNDER':
                results_list.append('U')
            else:
                results_list.append('-')

            # Points
            if pts is not None:
                points_list.append(int(pts))

            # Lines (NEW)
            if line is not None:
                lines_list.append(float(line))

        # Calculate record
        overs = results_list.count('O')
        unders = results_list.count('U')

        last_10_map[player] = {
            'results': results_list,
            'points': points_list,
            'lines': lines_list,  # ADD THIS
            'record': f"{overs}-{unders}" if (overs + unders) > 0 else None
        }

    return last_10_map
```

#### Step 4: Add to output (10 min)
```python
# In _build_games_data, around line 403:
player_data['last_10_points'] = last_10.get('points', [])
player_data['last_10_lines'] = last_10.get('lines', [])   # ADD THIS
player_data['last_10_results'] = last_10.get('results', [])
player_data['last_10_record'] = last_10.get('record')
```

**Opus:** Variable length arrays OK (if player has 5 games with lines, return 5-element arrays)

#### Step 5: Test (30 min)
```bash
# Export and validate
jq '.games[0].players[] | select(.has_line) | {
  name,
  points_len: (.last_10_points | length),
  lines_len: (.last_10_lines | length),
  results_len: (.last_10_results | length)
}' all-players.json | head -20

# Verify array lengths match
# Verify no players with all-dash results AND empty lines (should all have lines now)
```

---

### Part B: prediction.factors with Directional Logic (2-3 hours)

**⚠️ CRITICAL CHANGE FROM OPUS:** Factors MUST be directional and support the recommendation

### File: `tonight_all_players_exporter.py`

#### Step 1: Join feature store (30 min)
```sql
-- Add CTE after game_context (line ~206):
feature_data AS (
    SELECT
        player_lookup,
        game_date,
        -- Matchup features
        matchup_quality_pct,
        feature_13_value as opponent_def_rating,
        feature_14_value as opponent_pace,
        -- Quality tracking
        feature_quality_score,
        default_feature_count
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date = @target_date
)

-- Join in main query (line ~270):
LEFT JOIN feature_data fd ON gc.player_lookup = fd.player_lookup
```

#### Step 2: Create directional factor builder (1.5 hours)

**CRITICAL:** Pass recommendation, only include factors that support it

```python
def _build_prediction_factors(
    self,
    player_data: Dict,
    feature_data: Dict,
    last_10_record: Optional[str]
) -> List[str]:
    """
    Build up to 4 human-readable DIRECTIONAL factors.

    CRITICAL: Factors must support the recommendation, not contradict it.
    Only include factors that explain WHY the model made this call.

    Opus Priority Order: Edge > Matchup > Trend > Fatigue > Form
    """
    factors = []
    rec = player_data.get('recommendation')  # 'OVER' or 'UNDER'

    if not rec:
        return []  # No recommendation, no factors

    # 1. EDGE FIRST (primary signal - what the model is saying)
    predicted = player_data.get('predicted_points')
    line = player_data.get('current_points_line')
    if predicted and line:
        edge = abs(predicted - line)
        if edge >= 5:
            factors.append(f"Strong model conviction ({edge:.1f} point edge)")
        elif edge >= 3:
            factors.append(f"Solid model edge ({edge:.1f} points)")

    # 2. MATCHUP (explain WHY - only if supports recommendation)
    opp_def_rating = feature_data.get('opponent_def_rating')
    if opp_def_rating:
        # Only mention weak defense if recommending OVER
        if opp_def_rating > 115 and rec == 'OVER':
            factors.append("Weak opposing defense favors scoring")
        # Only mention elite defense if recommending UNDER
        elif opp_def_rating < 105 and rec == 'UNDER':
            factors.append("Elite opposing defense limits scoring")
        # Don't mention defense if it contradicts the recommendation

    # 3. HISTORICAL TREND (directional - only if supports)
    if last_10_record:
        try:
            overs, unders = map(int, last_10_record.split('-'))
            total = overs + unders
            if total >= 5:  # Need at least 5 games
                # Hot over streak supports OVER recommendation
                if overs >= 7 and rec == 'OVER':
                    factors.append(f"Hot over streak: {overs}-{unders} last 10")
                # Cold under streak supports UNDER recommendation
                elif unders >= 7 and rec == 'UNDER':
                    factors.append(f"Cold under streak: {overs}-{unders} last 10")
                # Trending over supports OVER
                elif overs >= 5 and rec == 'OVER':
                    factors.append(f"Trending over: {overs}-{unders} last 10")
                # Trending under supports UNDER
                elif unders >= 5 and rec == 'UNDER':
                    factors.append(f"Trending under: {overs}-{unders} last 10")
        except (ValueError, AttributeError):
            pass

    # 4. FATIGUE (directional)
    fatigue_level = player_data.get('fatigue_level')
    days_rest = player_data.get('days_rest')

    # Well-rested supports OVER (performance boost)
    if (fatigue_level == 'fresh' or (days_rest and days_rest >= 3)) and rec == 'OVER':
        factors.append("Well-rested, favors performance")
    # Fatigue supports UNDER (performance decline)
    elif (fatigue_level == 'tired' or (days_rest is not None and days_rest == 0)) and rec == 'UNDER':
        factors.append("Back-to-back fatigue risk")

    # 5. RECENT FORM (directional)
    recent_form = player_data.get('recent_form')

    # Hot form supports OVER
    if recent_form == 'Hot' and rec == 'OVER':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        if last_5 and season:
            diff = last_5 - season
            factors.append(f"Scoring surge: +{diff:.1f} vs season avg")
    # Cold form supports UNDER
    elif recent_form == 'Cold' and rec == 'UNDER':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        if last_5 and season:
            diff = abs(last_5 - season)
            factors.append(f"Recent slump: -{diff:.1f} vs season avg")

    # Return max 4 factors (UI constraint)
    return factors[:4]
```

#### Step 3: Integrate into output (30 min)
```python
# In _build_games_data, after building player_data dict:

# Get feature data for this player
player_feature_data = {
    'opponent_def_rating': p.get('opponent_def_rating'),
    'opponent_pace': p.get('opponent_pace'),
    'matchup_quality_pct': p.get('matchup_quality_pct'),
}

# Build directional factors
if p.get('has_line'):
    factors = self._build_prediction_factors(
        player_data=player_data,
        feature_data=player_feature_data,
        last_10_record=last_10.get('record')
    )

    player_data['prediction'] = {
        'predicted': safe_float(p.get('predicted_points')),
        'confidence': safe_float(p.get('confidence_score')),  # Keep 0-100 (Opus says skip scale change)
        'recommendation': p.get('recommendation'),
        'factors': factors  # NEW - max 4 directional factors
    }
```

#### Step 4: Test directional logic (30 min)

**CRITICAL:** Verify factors support recommendations, no contradictions

```bash
# Export and check sample players
jq '.games[0].players[] | select(.has_line and (.prediction.factors | length > 0)) | {
  name,
  recommendation: .prediction.recommendation,
  factors: .prediction.factors
}' all-players.json | head -100

# Manual spot checks:
# - OVER + "Weak opposing defense" ✅
# - OVER + "Hot over streak" ✅
# - UNDER + "Elite opposing defense" ✅
# - UNDER + "Back-to-back fatigue" ✅

# SHOULD NOT SEE:
# - OVER + "Elite opposing defense" ❌
# - UNDER + "Weak opposing defense" ❌
# - OVER + "Cold under streak" ❌
```

**Test cases:**
1. High edge OVER → Should see "Strong model conviction" first
2. OVER vs weak defense → Should see both edge + matchup
3. UNDER on back-to-back → Should see fatigue factor
4. OVER with 7-3 O/U record → Should see hot streak
5. Player with NULL features → Should still get edge factor (graceful degradation)

---

### Part C: Best Bets Table Selection Fix (1 hour)

### File: `best_bets_exporter.py`

**Opus:** Use explicit boolean flag, keep UNDER-only filter

#### Step 1: Add date-based table selection (30 min)
```python
def _query_ranked_predictions(self, target_date: str, top_n: int) -> List[Dict]:
    """
    Query predictions using tiered selection.

    CRITICAL: Use different tables for historical vs current/future dates.
    - Historical (< today): prediction_accuracy (graded)
    - Current/Future (>= today): player_prop_predictions (active)

    KEEP UNDER-only filter (intentional methodology, not a bug).
    """
    from datetime import datetime
    target = datetime.strptime(target_date, '%Y-%m-%d').date()
    today = datetime.now().date()

    # Explicit boolean flag (not string matching)
    use_predictions_table = target >= today

    # Build appropriate query based on table
    if use_predictions_table:
        # Current/Future: Use active predictions
        query = """
        WITH player_history AS (
            -- Historical accuracy for weighting (still from accuracy table)
            SELECT
                player_lookup,
                COUNT(*) as sample_size,
                ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END), 3) as historical_accuracy
            FROM `nba-props-platform.nba_predictions.prediction_accuracy`
            WHERE system_id = 'catboost_v9'
              AND game_date < @target_date
              AND recommendation = 'UNDER'
            GROUP BY player_lookup
        ),
        player_names AS (
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        fatigue_data AS (
            SELECT player_lookup, fatigue_score
            FROM `nba-props-platform.nba_precompute.player_composite_factors`
            WHERE game_date = @target_date
        ),
        predictions AS (
            SELECT
                p.player_lookup,
                COALESCE(pn.player_name, p.player_lookup) as player_full_name,
                p.game_id,
                p.team_abbr,
                p.opponent_team_abbr,
                p.predicted_points,
                NULL as actual_points,  -- Not graded yet
                p.current_points_line as line_value,
                p.recommendation,
                NULL as prediction_correct,  -- Not graded yet
                p.confidence_score,
                NULL as absolute_error,  -- Not graded yet
                NULL as signed_error,  -- Not graded yet
                ABS(p.predicted_points - p.current_points_line) as edge,
                h.historical_accuracy as player_historical_accuracy,
                h.sample_size as player_sample_size,
                f.fatigue_score
            FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
            LEFT JOIN player_history h ON p.player_lookup = h.player_lookup
            LEFT JOIN player_names pn ON p.player_lookup = pn.player_lookup
            LEFT JOIN fatigue_data f ON p.player_lookup = f.player_lookup
            WHERE p.game_date = @target_date
              AND p.system_id = 'catboost_v9'
              AND p.is_active = TRUE  -- Only active predictions
              AND p.recommendation IN ('UNDER', 'OVER')  -- KEEP BOTH (UNDER filter is in tier CTE)
              AND p.predicted_points < 25  -- Stars less predictable
              AND NOT (p.confidence_score >= 0.88 AND p.confidence_score < 0.90)  -- Exclude broken tier
              AND p.current_points_line IS NOT NULL
        )
        SELECT * FROM predictions  -- Continue with existing scoring/ranking logic
        """
    else:
        # Historical: Use graded predictions
        query = """
        WITH player_history AS (
            SELECT
                player_lookup,
                COUNT(*) as sample_size,
                ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END), 3) as historical_accuracy
            FROM `nba-props-platform.nba_predictions.prediction_accuracy`
            WHERE system_id = 'catboost_v9'
              AND game_date < @target_date
              AND recommendation = 'UNDER'
            GROUP BY player_lookup
        ),
        player_names AS (
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        fatigue_data AS (
            SELECT player_lookup, fatigue_score
            FROM `nba-props-platform.nba_precompute.player_composite_factors`
            WHERE game_date = @target_date
        ),
        predictions AS (
            SELECT
                p.player_lookup,
                COALESCE(pn.player_name, p.player_lookup) as player_full_name,
                p.game_id,
                p.team_abbr,
                p.opponent_team_abbr,
                p.predicted_points,
                p.actual_points,
                p.line_value,
                p.recommendation,
                p.prediction_correct,
                p.confidence_score,
                p.absolute_error,
                p.signed_error,
                ABS(p.predicted_points - p.line_value) as edge,
                h.historical_accuracy as player_historical_accuracy,
                h.sample_size as player_sample_size,
                f.fatigue_score
            FROM `nba-props-platform.nba_predictions.prediction_accuracy` p
            LEFT JOIN player_history h ON p.player_lookup = h.player_lookup
            LEFT JOIN player_names pn ON p.player_lookup = pn.player_lookup
            LEFT JOIN fatigue_data f ON p.player_lookup = f.player_lookup
            WHERE p.game_date = @target_date
              AND p.system_id = 'catboost_v9'
              AND p.recommendation IN ('UNDER', 'OVER')  -- KEEP BOTH
              AND p.predicted_points < 25
              AND NOT (p.confidence_score >= 0.88 AND p.confidence_score < 0.90)
              AND p.line_value IS NOT NULL
              AND p.line_value != 20  -- Exclude fake data
        )
        SELECT * FROM predictions
        """

    # Rest of query (scored, ranked, filtered CTEs) stays the same
    # Just append to the predictions CTE defined above

    query += """
    ,
    scored AS (
        SELECT
            *,
            LEAST(1.5, 1.0 + edge / 10.0) as edge_factor,
            CASE
                WHEN player_sample_size >= 5 THEN player_historical_accuracy
                ELSE 0.85
            END as hist_factor,
            confidence_score
                * LEAST(1.5, 1.0 + edge / 10.0)
                * CASE
                    WHEN player_sample_size >= 5 THEN player_historical_accuracy
                    ELSE 0.85
                  END as composite_score,
            CASE
                WHEN edge >= 5.0 THEN 'premium'
                WHEN edge >= 3.0 THEN 'strong'
                ELSE 'value'
            END as tier,
            CASE
                WHEN edge >= 5.0 THEN 1
                WHEN edge >= 3.0 THEN 2
                ELSE 3
            END as tier_order
        FROM predictions
    ),
    ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (PARTITION BY tier ORDER BY composite_score DESC) as tier_rank
        FROM scored
    ),
    filtered AS (
        SELECT *
        FROM ranked
        WHERE (tier = 'premium' AND tier_rank <= 5)
           OR (tier = 'strong' AND tier_rank <= 10)
           OR (tier = 'value' AND tier_rank <= 10)
    )
    SELECT *
    FROM filtered
    ORDER BY tier_order ASC, composite_score DESC
    LIMIT @top_n
    """

    params = [
        bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        bigquery.ScalarQueryParameter('top_n', 'INT64', top_n)
    ]

    return self.query_to_list(query, params)
```

#### Step 2: Test both modes (30 min)
```bash
# Historical date
PYTHONPATH=. python -c "
from data_processors.publishing.best_bets_exporter import BestBetsExporter
exporter = BestBetsExporter()
data = exporter.generate_json('2026-02-09')
print(f'Historical: {data[\"total_picks\"]} picks, {data[\"tier_summary\"]}')"

# Current date
PYTHONPATH=. python -c "
from data_processors.publishing.best_bets_exporter import BestBetsExporter
exporter = BestBetsExporter()
data = exporter.generate_json('2026-02-11')
print(f'Current: {data[\"total_picks\"]} picks, {data[\"tier_summary\"]}')"

# Verify current date now returns >0 picks (was 0)
```

---

### Sprint 2: Deploy & Validate

```bash
git add .
git commit -m "feat: Add prediction factors and fix best bets (Sprint 2)

HIGH IMPACT FEATURES:
- Add last_10_lines array for accurate O/U calculations (fixes 31 players)
- Add prediction.factors with directional logic (supports recommendation)
- Fix best bets table selection (use predictions table for current dates)

CRITICAL: Factors are directional and support the recommendation.
Priority order: Edge > Matchup > Trend > Fatigue > Form

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin main

# Verify deployment
# Trigger Phase 6 export
# Validate outputs
```

**Validation:**
- [ ] `last_10_lines` length matches `last_10_points`
- [ ] No more all-dash O/U results for lined players
- [ ] `prediction.factors` populated for all lined players
- [ ] Factors are directional (support recommendation)
- [ ] No contradictory factors (OVER + "Elite defense" = bug)
- [ ] Best bets returns picks for current date (was 0)
- [ ] Edge factor appears first in factor list

---

## 🎨 Sprint 3: Enhancements (1.5 hours)

### File: `tonight_all_players_exporter.py`

#### Date-specific tonight files (15 min)
```python
def export(self, target_date: str) -> str:
    """
    Generate and upload tonight's all players JSON.

    Outputs TWO files:
    - tonight/all-players.json (always latest, short cache)
    - tonight/YYYY-MM-DD.json (date-specific, long cache)
    """
    logger.info(f"Exporting tonight all players for {target_date}")
    json_data = self.generate_json(target_date)

    # Current: tonight/all-players.json (always latest)
    latest_path = 'tonight/all-players.json'
    self.upload_to_gcs(json_data, latest_path, 'public, max-age=300')

    # New: tonight/YYYY-MM-DD.json (date-specific, cacheable)
    date_path = f'tonight/{target_date}.json'
    gcs_path = self.upload_to_gcs(json_data, date_path, 'public, max-age=86400')

    logger.info(f"Exported to {latest_path} and {date_path}")
    return gcs_path
```

**Test:**
```bash
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | jq '.game_date'
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-11.json | jq '.game_date'
# Both should return same data
```

---

### File: `data_processors/publishing/calendar_exporter.py` (NEW FILE)

#### Create calendar game counts exporter (1 hour)
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
          AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
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

---

### File: `backfill_jobs/publishing/daily_export.py`

#### Add calendar to export types (15 min)
```python
# In imports section (line ~80)
from data_processors.publishing.calendar_exporter import CalendarExporter

# In EXPORT_TYPES list (line ~91)
EXPORT_TYPES = [
    'results', 'performance', 'best-bets', 'predictions',
    'tonight', 'tonight-players', 'streaks',
    'calendar',  # NEW
    ...
]

# In export_date() function (line ~400+)
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

---

### Sprint 3: Deploy & Validate

```bash
git add .
git commit -m "feat: Add date navigation and calendar (Sprint 3)

ENHANCEMENTS:
- Export date-specific tonight files for historical browsing
- Add calendar/game-counts.json for calendar widget

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin main

# Verify deployment
# Trigger Phase 6 export with calendar
# Test all new endpoints
```

**Validation:**
- [ ] `/tonight/2026-02-11.json` accessible
- [ ] `/calendar/game-counts.json` shows 30+ dates
- [ ] Game counts match schedule table
- [ ] Frontend date picker works
- [ ] Calendar widget displays

---

## ✅ Final Validation

### Comprehensive Testing
```bash
# 1. Data completeness
jq '.games[0].players[] | select(.has_line) | {
  days_rest,
  minutes_avg,
  recent_form,
  last_10_lines: (.last_10_lines | length),
  factors: (.prediction.factors | length)
}' all-players.json | head -20

# 2. No contradictory factors
jq '.games[0].players[] | select(.has_line) | {
  name,
  rec: .prediction.recommendation,
  factors: .prediction.factors
}' all-players.json | grep -A3 "OVER" | head -40

# Should NOT see: OVER + "Elite defense" or UNDER + "Weak defense"

# 3. Best bets current date
curl https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/latest.json | jq '.total_picks'
# Should be >0 (was 0)

# 4. Historical date browsing
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-10.json | jq '.game_date'

# 5. Calendar
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json | jq 'keys | length'
# Should be 30+
```

---

## 📊 Success Metrics

**Data Quality:**
- [ ] 0 fields missing for lined players (was 31 with missing O/U)
- [ ] 0 invalid odds values >10000
- [ ] 0 contradictory factors (directional logic enforced)

**Feature Completeness:**
- [ ] 100% of lined players have prediction factors
- [ ] Best bets shows 10-25 picks for current dates (was 0)
- [ ] Historical O/U calculations accurate (last_10_lines available)

**Endpoints:**
- [ ] 10/10 endpoints functional (was 6/10)
- [ ] Date-specific files for historical browsing
- [ ] Calendar widget data available

---

## 📝 Documentation Updates

After deployment:

- [ ] Update `CLAUDE.md` with new fields
- [ ] Document factor generation logic
- [ ] Add API documentation for new endpoints
- [ ] Create frontend integration guide
- [ ] Update Phase 6 export runbook

---

**Status:** ✅ Ready for Implementation
**Total Effort:** ~7 hours (Opus-optimized)
**Critical Corrections Applied:** ✅ All Opus recommendations integrated
