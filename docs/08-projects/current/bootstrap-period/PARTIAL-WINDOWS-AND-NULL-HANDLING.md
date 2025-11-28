# Partial Windows and NULL Handling - Detailed Policy

**Purpose:** Clarify exactly how we handle insufficient data scenarios
**Created:** 2025-11-27
**Status:** ✅ Current Implementation Documented

---

## Executive Summary

**Key Decision:** Use available games, NOT NULL (with metadata)

**Current Implementation:**
- ✅ L5/L10 averages use `min_periods=1` (calculate from whatever games available)
- ✅ Metadata tracks data quality (`feature_quality_score`, `insufficient_data_reason`)
- ⏳ L30 average not implemented yet
- ⏳ `games_used` fields planned but schema change deferred
- ✅ Downstream processors can distinguish between different failure modes

**How Downstream Knows:**
1. **No record:** Processor didn't run (error)
2. **Placeholder record:** Early season skip (days 0-6)
3. **Real record with low quality:** Ran but limited data (injury, late start, partial window)

---

## The Core Question

### Q: L30 average with only 7 games - use available or set NULL?

**Answer: Use available games (7 of 30) ✅**

**Reasoning:**
- 7 games of signal > no signal at all
- ML model can learn reliability from metadata
- Gradual degradation better than binary NULL
- Consistent with pandas best practices (`min_periods=1`)

**Implementation:**
```python
# Example: Last 30 game average with only 7 games
player_games = get_last_n_games(player, n=30, season=2024)
# Only 7 games available

# Calculate average from available games
points_avg_last_30 = player_games['points'].mean()  # Uses 7 games
points_avg_last_30_games_used = len(player_games)   # = 7
feature_quality = len(player_games) / 30.0          # = 0.23 (23%)

record = {
    'points_avg_last_30': 18.5,  # Real value from 7 games
    'points_avg_last_30_games_used': 7,  # Metadata (schema change deferred)
    'feature_quality_score': 23.0,  # Low quality score
    'insufficient_data_reason': 'partial_window_L30_7_of_30_games'
}
```

---

## Current Implementation Details

### What We Actually Calculate Now

**Currently implemented (player_daily_cache):**
- ✅ L5 average (last 5 games)
- ✅ L10 average (last 10 games)
- ✅ Season average
- ✅ L10 std deviation
- ✅ Team pace (last 10 games)
- ❌ L30 average NOT implemented yet

**How we calculate (existing code):**
```python
# From player_daily_cache_processor.py lines 113-114
self.min_games_required = 10        # Preferred minimum
self.absolute_min_games = 5         # Absolute minimum to write record

# Existing pandas rolling calculation (uses min_periods implicitly)
rolling_avg = player_games['points'].rolling(window=10, min_periods=1).mean()

# This means:
# - 1 game available: Calculate from 1 game
# - 5 games available: Calculate from 5 games
# - 10+ games available: Calculate from 10 games
```

**What happens with 7 games on day 7:**
```python
# player_daily_cache_processor.py calculates:
points_avg_last_5 = last_5_games['points'].mean()   # Uses all 5 (7 available)
points_avg_last_10 = last_10_games['points'].mean() # Uses 7 of 10 ✅
points_avg_season = all_games['points'].mean()      # Uses all 7
```

**Result:** Real values calculated from available games, NOT NULL ✅

---

### Metadata Fields (Current Implementation)

**Level 1: Processor-Level Metadata**

```sql
-- player_daily_cache table
early_season_flag BOOLEAN,           -- TRUE if < 10 games (threshold-based)
insufficient_data_reason STRING,     -- Why insufficient (if any)
```

**Current values:**
```python
# Code from player_daily_cache_processor.py lines 302-306
if dep_check.get('is_early_season'):
    logger.warning("Early season detected - will write partial cache records")
    self.early_season_flag = True
    self.insufficient_data_reason = "Season just started, using available games"
```

**Wait - this is OLD CODE!** Let me check what we actually changed...

Actually, we added SKIP logic that returns early:
```python
# New code we added (lines 304-318)
if is_early_season(analysis_date, season_year, days_threshold=7):
    logger.info(f"⏭️  Skipping {analysis_date}: early season period")
    self.stats['processing_decision'] = 'skipped_early_season'
    self.raw_data = None
    return  # EXIT - no records written
```

So for days 0-6: NO RECORDS AT ALL in player_daily_cache.

For days 7+: Records ARE written with real values from available games.

**Level 2: ML Feature Store Metadata**

```sql
-- ml_feature_store_v2 table (IMPLEMENTED)
feature_quality_score NUMERIC(5,2),    -- 0-100 quality score
early_season_flag BOOLEAN,              -- TRUE if days 0-6
insufficient_data_reason STRING,        -- Detailed explanation
is_production_ready BOOLEAN,            -- FALSE if not ready
expected_games_count INT64,             -- Games expected
actual_games_count INT64,               -- Games actually found
completeness_percentage FLOAT64,        -- 0-100%
missing_games_count INT64,              -- How many missing
```

**Level 3: Games Used Metadata (PLANNED - Not Implemented)**

```sql
-- player_daily_cache table (SCHEMA CHANGE DEFERRED)
points_avg_last_5_games_used INT64,    -- Exactly how many games for L5
points_avg_last_10_games_used INT64,   -- Exactly how many games for L10
points_avg_season_games_used INT64,    -- Same as games_played_season
```

**Status:** Designed but schema migration deferred. Code works without it using `min_periods=1`.

---

## How Downstream Processors Distinguish Scenarios

### Scenario 1: Processor Didn't Run (Error)

**Database state:**
```sql
-- Query player_daily_cache
SELECT * FROM player_daily_cache WHERE cache_date = '2024-11-15' AND player_lookup = 'lebron-james';
-- Result: 0 rows (NO RECORD)

-- Query ml_feature_store_v2
SELECT * FROM ml_feature_store_v2 WHERE game_date = '2024-11-15' AND player_lookup = 'lebron-james';
-- Result: 0 rows (NO RECORD)
```

**How downstream knows:**
- Phase 5 loads features: `features = load_features('lebron-james', '2024-11-15')`
- Returns: `None` (no record found)
- Code: worker.py line 442-447

```python
if features is None:
    logger.error(f"No features available for {player_lookup} on {game_date}")
    metadata['error_message'] = f'No features available for {player_lookup}'
    metadata['error_type'] = 'FeatureLoadError'
    metadata['skip_reason'] = 'no_features'
    return {'predictions': [], 'metadata': metadata}
```

**User sees:** No prediction, error logged

---

### Scenario 2: Early Season Skip (Days 0-6)

**Database state:**
```sql
-- Query player_daily_cache
SELECT * FROM player_daily_cache WHERE cache_date = '2024-10-24';
-- Result: 0 rows (SKIPPED - no records written)

-- Query ml_feature_store_v2
SELECT * FROM ml_feature_store_v2 WHERE game_date = '2024-10-24' AND player_lookup = 'lebron-james';
-- Result: 1 row (PLACEHOLDER)
```

**Placeholder record:**
```json
{
  "player_lookup": "lebron-james",
  "game_date": "2024-10-24",

  // ALL FEATURES NULL
  "features": [null, null, null, ... (25 nulls)],

  // METADATA
  "feature_quality_score": 0.0,
  "early_season_flag": true,
  "insufficient_data_reason": "early_season_skip_first_7_days",
  "is_production_ready": false,
  "data_source": "early_season_placeholder",

  // COMPLETENESS
  "expected_games_count": 0,
  "actual_games_count": 0,
  "completeness_percentage": 0.0
}
```

**How downstream knows:**
```python
# Phase 5 loads features
features = load_features('lebron-james', '2024-10-24')
# Returns: dict with features=[null, null, ...], quality=0.0

# Validation check (worker.py line 451-460)
is_valid, errors = validate_features(features, min_quality_score=70.0)
# Returns: False, ["quality_score too low (0.0 < 70.0)"]

# Also checks production readiness (worker.py line 469-481)
if not completeness.get('is_production_ready', False):
    # Returns empty predictions
    metadata['skip_reason'] = 'features_not_production_ready'
```

**User sees:** No prediction, logged reason: "Early season - insufficient data"

**Key distinction:** Has a record with `early_season_flag=TRUE` ✅

---

### Scenario 3: Regular Season with Partial Windows (Day 7-30)

**Database state:**
```sql
-- Query player_daily_cache
SELECT * FROM player_daily_cache WHERE cache_date = '2024-10-31' AND player_lookup = 'lebron-james';
-- Result: 1 row (REAL DATA)
```

**Real record (day 7 - only 7 games available):**
```json
{
  "player_lookup": "lebron-james",
  "cache_date": "2024-10-31",

  // REAL VALUES from 7 games ✅
  "points_avg_last_5": 22.4,        // From 5 games (full window)
  "points_avg_last_10": 21.8,       // From 7 games (partial window)
  "points_avg_season": 21.8,        // From 7 games (all available)
  "games_played_season": 7,

  // METADATA
  "early_season_flag": false,       // NOT early season (day 7+)
  "insufficient_data_reason": null, // Or could be set (see below)

  // GAMES USED (when schema updated)
  "points_avg_last_5_games_used": 5,   // Full window
  "points_avg_last_10_games_used": 7,  // Partial window
  "points_avg_season_games_used": 7
}
```

**ML Feature Store aggregates this:**
```json
{
  "player_lookup": "lebron-james",
  "game_date": "2024-10-31",

  // REAL FEATURES ✅
  "features": [22.4, 21.8, 21.8, 3.2, ...],

  // METADATA
  "feature_quality_score": 72.0,    // Lower than ideal but usable
  "early_season_flag": false,       // NOT marked as early season
  "insufficient_data_reason": "partial_window_L10_7_of_10_games",
  "is_production_ready": true,      // ✅ Good enough to use!

  // COMPLETENESS
  "expected_games_count": 10,
  "actual_games_count": 7,
  "completeness_percentage": 70.0
}
```

**How downstream knows:**
```python
# Phase 5 loads features
features = load_features('lebron-james', '2024-10-31')
# Returns: dict with real feature values, quality=72.0

# Validation check
is_valid, errors = validate_features(features, min_quality_score=70.0)
# Returns: True ✅ (72.0 >= 70.0)

# Production readiness check
if completeness.get('is_production_ready', False):
    # Passes! Generate predictions
```

**User sees:** Predictions generated successfully ✅

**Key distinctions:**
- `early_season_flag=FALSE` (not system-wide issue)
- `is_production_ready=TRUE` (usable data)
- `insufficient_data_reason` explains it's partial window
- `completeness_percentage=70%` (7/10 games)

---

### Scenario 4: Player Injury/Late Season Start

**Example: Player injured until game 15 of season**

**Database state on day 20 (when player has only 5 games):**
```sql
-- Most players have 20 games, this player has 5
SELECT * FROM player_daily_cache WHERE cache_date = '2024-11-20' AND player_lookup = 'injured-player';
-- Result: 1 row (REAL DATA from 5 games)
```

**Record:**
```json
{
  "player_lookup": "injured-player",
  "cache_date": "2024-11-20",

  // REAL VALUES from 5 games ✅
  "points_avg_last_5": 18.2,        // From 5 games (full L5 window!)
  "points_avg_last_10": 18.2,       // From 5 games (partial L10 window)
  "points_avg_season": 18.2,        // From 5 games
  "games_played_season": 5,         // ⚠️ Only 5 games (most players have 20)

  // METADATA
  "early_season_flag": false,       // NOT early season (day 20)
  "insufficient_data_reason": null, // Could be set

  // GAMES USED (when implemented)
  "points_avg_last_5_games_used": 5,   // Full L5
  "points_avg_last_10_games_used": 5,  // Partial L10
}
```

**ML Feature Store:**
```json
{
  "player_lookup": "injured-player",
  "game_date": "2024-11-20",

  // REAL FEATURES ✅
  "features": [18.2, 18.2, 18.2, ...],

  // METADATA
  "feature_quality_score": 60.0,    // Lower quality (only 5 games)
  "early_season_flag": false,       // NOT early season
  "insufficient_data_reason": "partial_window_L10_5_of_10_games",
  "is_production_ready": true,      // Still usable (above threshold)

  // COMPLETENESS
  "expected_games_count": 20,       // Expected 20 games by now
  "actual_games_count": 5,          // Only has 5 (injured)
  "completeness_percentage": 25.0   // ⚠️ Very low
}
```

**How downstream knows this is injury, not early season:**
```python
# Phase 5 can distinguish:
if features['early_season_flag']:
    reason = "System-wide early season"
elif features['completeness_percentage'] < 50:
    reason = "Player-specific issue (injury, late start, traded)"
else:
    reason = "Normal data quality variation"

# Validation
is_valid = validate_features(features, min_quality_score=70.0)
# Returns: False (60.0 < 70.0)

# Could be adjusted:
is_valid = validate_features(features, min_quality_score=50.0)
# Returns: True (60.0 >= 50.0) - might accept with lower threshold
```

**User sees:**
- Prediction generated if threshold lowered
- Or no prediction with reason: "Insufficient game history for this player"

**Key distinctions:**
- `early_season_flag=FALSE` ✅ (not system-wide)
- `completeness_percentage=25%` ⚠️ (player-specific issue)
- `games_played_season=5` (other players have 20)
- `insufficient_data_reason` could specify player-specific

---

## Summary Table: How Downstream Distinguishes

| Scenario | Record Exists? | early_season_flag | feature_quality | is_production_ready | Interpretation |
|----------|----------------|-------------------|-----------------|---------------------|----------------|
| **Processor Error** | ❌ NO | N/A | N/A | N/A | System failure |
| **Early Season (days 0-6)** | ✅ YES (placeholder) | TRUE | 0.0 | FALSE | System-wide skip |
| **Partial Window (day 7-30)** | ✅ YES (real data) | FALSE | 70-90 | TRUE | Limited but usable |
| **Player Injury** | ✅ YES (real data) | FALSE | 40-70 | TRUE/FALSE | Player-specific issue |
| **Normal Operation** | ✅ YES (real data) | FALSE | 95-100 | TRUE | Full quality |

---

## Code Examples: How to Check

### Check 1: Does record exist?
```python
features = load_features(player, date)
if features is None:
    print("ERROR: Processor didn't run or data not loaded")
else:
    print("OK: Record exists")
```

### Check 2: Is it early season placeholder?
```python
if features and features.get('early_season_flag'):
    print("Early season placeholder (days 0-6)")
    print(f"Reason: {features.get('insufficient_data_reason')}")
```

### Check 3: Is it player-specific issue?
```python
if features and not features.get('early_season_flag'):
    completeness = features.get('completeness_percentage', 100)

    if completeness < 50:
        print(f"Player-specific issue: Only {completeness}% of expected data")
        print("Likely: Injury, late start, or trade")
    elif completeness < 80:
        print(f"Partial data: {completeness}% complete")
        print("Likely: Early in season but past day 7")
    else:
        print(f"Normal: {completeness}% complete")
```

### Check 4: Get games used (when implemented)
```python
if features:
    # When schema updated:
    games_l10 = features.get('points_avg_last_10_games_used', 'unknown')
    print(f"L10 average based on {games_l10} games")

    if games_l10 < 10:
        print(f"Partial window: Only {games_l10} of 10 games available")
```

---

## SQL Queries: Distinguish Scenarios

### Query 1: Find early season placeholders
```sql
SELECT
  player_lookup,
  game_date,
  early_season_flag,
  insufficient_data_reason,
  feature_quality_score
FROM ml_feature_store_v2
WHERE game_date BETWEEN '2024-10-22' AND '2024-10-30'
  AND early_season_flag = TRUE;

-- Shows all early season placeholders
```

### Query 2: Find partial windows (day 7-30)
```sql
SELECT
  player_lookup,
  game_date,
  feature_quality_score,
  completeness_percentage,
  insufficient_data_reason
FROM ml_feature_store_v2
WHERE game_date BETWEEN '2024-10-31' AND '2024-11-20'
  AND early_season_flag = FALSE
  AND completeness_percentage < 80;

-- Shows players with partial data during early season
```

### Query 3: Find player-specific issues (injury)
```sql
SELECT
  p1.player_lookup,
  p1.game_date,
  p1.completeness_percentage as player_completeness,
  AVG(p2.completeness_percentage) as avg_completeness_all_players
FROM ml_feature_store_v2 p1
JOIN ml_feature_store_v2 p2 ON p1.game_date = p2.game_date
WHERE p1.game_date = '2024-11-20'
  AND p1.early_season_flag = FALSE
GROUP BY p1.player_lookup, p1.game_date, p1.completeness_percentage
HAVING p1.completeness_percentage < AVG(p2.completeness_percentage) * 0.5;

-- Shows players with <50% of average completeness (likely injured)
```

### Query 4: Compare early season vs injury
```sql
WITH player_stats AS (
  SELECT
    player_lookup,
    game_date,
    early_season_flag,
    completeness_percentage,
    feature_quality_score,
    CASE
      WHEN early_season_flag = TRUE THEN 'early_season_placeholder'
      WHEN completeness_percentage < 30 THEN 'player_injury_likely'
      WHEN completeness_percentage < 80 THEN 'partial_window_normal'
      ELSE 'full_data'
    END as data_status
  FROM ml_feature_store_v2
  WHERE game_date BETWEEN '2024-10-22' AND '2024-11-30'
)
SELECT
  data_status,
  COUNT(*) as count,
  AVG(feature_quality_score) as avg_quality,
  AVG(completeness_percentage) as avg_completeness
FROM player_stats
GROUP BY data_status
ORDER BY data_status;

-- Categorizes all predictions by data status
```

---

## Implementation Status

### ✅ Currently Working

1. **Partial window calculation**
   - L5/L10 use `min_periods=1`
   - Calculates from available games
   - NOT NULL ✅

2. **Metadata tracking**
   - `early_season_flag` distinguishes days 0-6
   - `feature_quality_score` indicates overall quality
   - `completeness_percentage` shows data availability
   - `insufficient_data_reason` explains issues

3. **Downstream detection**
   - Phase 5 can distinguish all scenarios
   - Validates quality before predictions
   - Checks production readiness
   - Returns appropriate error messages

### ⏳ Planned But Not Implemented

1. **L30 average**
   - Not calculated yet
   - Would use same min_periods=1 approach
   - Would use available games, not NULL

2. **games_used fields**
   - Schema designed but not migrated
   - Code works without it
   - Would enable per-feature quality tracking

3. **More granular insufficient_data_reason**
   - Currently set in some cases
   - Could be more systematic
   - Could distinguish injury vs early season

---

## Recommendations

### For Production

1. **Keep current approach** ✅
   - Use available games with metadata
   - Don't use NULL for partial windows
   - Quality scores guide usage

2. **Add games_used fields** (when convenient)
   - Helpful for debugging
   - Useful for model training
   - Not blocking current implementation

3. **Monitor quality scores**
   - Track quality distribution over time
   - Alert if quality drops unexpectedly
   - Use in model training

### For ML Model

1. **Train with partial windows**
   - Model sees examples with quality=70
   - Learns: "70% quality → X% accuracy"
   - Better than excluding all partial data

2. **Use quality as feature**
   - Include quality_score in training
   - Include completeness_percentage
   - Model learns to adjust confidence

3. **Different thresholds for different scenarios**
   - Early season: Accept quality >= 70
   - Mid-season injury: Maybe accept >= 60
   - Normal operation: Expect quality >= 95

---

## Answer to Your Questions

### Q1: "Will it use the games that are available or leave it as null?"

**Answer: Use available games ✅**

Current implementation:
- L5/L10 calculated from whatever games available (min_periods=1)
- NOT NULL
- Metadata tracks quality and completeness

### Q2: "Will downstream processors know it ran successfully but limited data?"

**Answer: YES ✅**

Multiple ways to distinguish:

**Processor didn't run:**
- No record in database
- `features = None`

**Early season (days 0-6):**
- Placeholder record exists
- `early_season_flag = TRUE`
- `feature_quality_score = 0.0`
- `features = [null, null, ...]`

**Ran with partial data:**
- Real record exists
- `early_season_flag = FALSE`
- `feature_quality_score = 70-90`
- `features = [real values]`
- `insufficient_data_reason` explains why partial
- `completeness_percentage` shows 70-80%

**Player-specific issue (injury):**
- Real record exists
- `early_season_flag = FALSE`
- `completeness_percentage` much lower than league average
- `games_played_season` lower than expected for that date

---

## Conclusion

**Current implementation handles this well:**

1. ✅ Uses available games (not NULL)
2. ✅ Tracks metadata to explain data quality
3. ✅ Downstream can distinguish scenarios
4. ✅ Graceful degradation (not binary failure)
5. ⏳ Could be enhanced with games_used fields

**The key insight:**
> Partial data with metadata > No data with NULL

**ML model benefits:**
> Model learns reliability from quality scores during training

**Everything is trackable:**
> Every scenario has distinct metadata fingerprint

---

## References

- IMPLEMENTATION-PLAN.md - Q1 decision on partial windows
- CROSS-SEASON-DATA-POLICY.md - What data we use when
- worker.py:442-481 - Phase 5 validation logic
- player_daily_cache_processor.py:113-114 - min_periods usage

---

**You were right to ask!** This is critical for production reliability. ✅
