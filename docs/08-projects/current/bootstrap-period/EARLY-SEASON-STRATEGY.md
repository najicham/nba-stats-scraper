# Early Season Strategy - Phase 4 & Phase 5 Behavior

**Question:** What happens during days 0-6 of the season when we skip early season processing?

**Answer:** Hybrid approach - skip upstream processors, create placeholders in ML Feature Store

---

## Strategy Overview

### Days 0-6 (Early Season - Oct 25 to Oct 31)

**Phase 4 Processors (Upstream):** SKIP - No Records
- `player_daily_cache` → SKIP (no records written)
- `player_shot_zone_analysis` → SKIP (no records written)
- `team_defense_zone_analysis` → SKIP (no records written)
- `player_composite_factors` → SKIP (no records written)

**Phase 4 Processor (Final):** CREATE PLACEHOLDERS
- `ml_feature_store` → Creates placeholder records with:
  - All features = NULL
  - `early_season_flag = TRUE`
  - `insufficient_data_reason = 'early_season_skip_first_7_days'`
  - `feature_quality_score = 0.0`
  - `is_production_ready = FALSE`
  - `backfill_bootstrap_mode = TRUE`

**Phase 5 (Predictions):** SKIP - Returns Empty Predictions
- Loads placeholder record from ml_feature_store
- Validation fails (quality_score 0.0 < 70.0 threshold)
- Returns empty predictions with metadata explaining why

### Days 7+ (Regular Season - Nov 1+)

**Phase 4 Processors:** PROCESS with Partial Windows
- All processors run normally
- Use min_periods=1 for rolling averages
- Track games_used for each rolling window
- Calculate quality scores based on partial data

**Phase 5 (Predictions):** PREDICT Normally
- Loads features with partial windows
- Validates features (quality may be lower but >70%)
- Generates predictions using available data

---

## Code Implementation

### Phase 4 Upstream Processors

**Files:**
- `player_daily_cache_processor.py`
- `player_shot_zone_analysis_processor.py`
- `team_defense_zone_analysis_processor.py`
- `player_composite_factors_processor.py`

**Code Pattern:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def process(self, analysis_date: date, season_year: int = None):
    """Process daily cache for given date"""

    # Determine season year
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    # SKIP early season (days 0-6)
    if is_early_season(analysis_date, season_year, days_threshold=7):
        logger.info(f"Skipping {analysis_date}: early season period (day 0-6)")
        return  # Exit early - NO records written

    # Day 7+: Process normally with partial windows
    logger.info(f"Processing {analysis_date} (day 7+)")
    # ... existing extraction and transformation logic ...
```

---

### ML Feature Store Processor

**File:** `ml_feature_store_processor.py`

**Code Pattern:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def _should_skip_early_season(self, analysis_date: date) -> bool:
    """Check if we should create placeholders due to early season"""
    season_year = get_season_year_from_date(analysis_date)

    if is_early_season(analysis_date, season_year, days_threshold=7):
        self.early_season_flag = True
        self.insufficient_data_reason = 'early_season_skip_first_7_days'
        logger.info(f"Early season detected for {analysis_date}: will create placeholders")
        return True

    return False

def process(self, analysis_date: date, season_year: int = None):
    """Generate features for given date"""

    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    # Check for early season
    if self._should_skip_early_season(analysis_date):
        # CREATE placeholders instead of skipping
        self._create_early_season_placeholders(analysis_date)
        logger.info(f"Created early season placeholders for {analysis_date}")
        return

    # Day 7+: Process normally
    # ... existing feature extraction logic ...

def _create_early_season_placeholders(self, analysis_date: date) -> None:
    """
    Create placeholder records for early season.

    All features set to NULL, early_season_flag = TRUE.
    This allows Phase 5 to detect early season and skip predictions gracefully.
    """
    # Get list of players with games TODAY (from Phase 3)
    players = self.feature_extractor.get_players_with_games(analysis_date)

    self.transformed_data = []

    for player_row in players:
        record = {
            'player_lookup': player_row['player_lookup'],
            'universal_player_id': player_row.get('universal_player_id'),
            'game_date': analysis_date.isoformat(),
            'game_id': player_row['game_id'],

            # NULL feature array (25 NULLs)
            'features': [None] * FEATURE_COUNT,
            'feature_names': FEATURE_NAMES,
            'feature_count': FEATURE_COUNT,
            'feature_version': FEATURE_VERSION,

            # Context (from Phase 3 - still available)
            'opponent_team_abbr': player_row.get('opponent_team_abbr'),
            'is_home': player_row.get('is_home'),
            'days_rest': player_row.get('days_rest'),

            # Quality indicators
            'feature_quality_score': 0.0,  # Zero quality
            'feature_generation_time_ms': None,
            'data_source': 'early_season_placeholder',

            # Early season flags
            'early_season_flag': True,
            'insufficient_data_reason': self.insufficient_data_reason,

            # Completeness metadata
            'expected_games_count': 0,
            'actual_games_count': 0,
            'completeness_percentage': 0.0,
            'missing_games_count': 0,
            'is_production_ready': False,  # NOT ready for production
            'data_quality_issues': ['early_season_insufficient_data'],
            'backfill_bootstrap_mode': True,  # Bootstrap mode signal
            'processing_decision_reason': 'early_season_placeholder',

            # ... source tracking, hashes, timestamps ...
        }

        self.transformed_data.append(record)

    logger.info(f"Created {len(self.transformed_data)} early season placeholder records")
```

---

### Phase 5 Prediction Worker

**File:** `predictions/worker/worker.py`

**NO CHANGES NEEDED!** Already handles this gracefully.

**Existing code (lines 442-481):**
```python
# Step 1: Load features
features = data_loader.load_features(player_lookup, game_date)

if features is None:
    # No record at all (shouldn't happen with our approach)
    return {'predictions': [], 'metadata': {'skip_reason': 'no_features'}}

# Step 2: Validate features
is_valid, validation_errors = validate_features(features, min_quality_score=70.0)
if not is_valid:
    # Early season placeholders will FAIL here (quality_score = 0.0 < 70.0)
    return {
        'predictions': [],
        'metadata': {
            'skip_reason': 'invalid_features',
            'error_message': f'Invalid features: {validation_errors}',
            'feature_quality_score': 0.0
        }
    }

# Step 3: Check production readiness
completeness = features.get('completeness', {})
if not completeness.get('is_production_ready', False):
    # Early season placeholders will ALSO FAIL here (is_production_ready = False)
    return {
        'predictions': [],
        'metadata': {
            'skip_reason': 'features_not_production_ready',
            'error_message': 'Features incomplete: 0.0%'
        }
    }

# If we get here: features are valid, proceed with predictions
```

**Result:** Early season placeholders are caught by validation and production-readiness checks.

---

## Data Flow Example

### Scenario: Opening Night (Oct 25, 2023)

**1. Phase 3 Analytics (9:00 PM)**
- `player_game_summary` processes today's games ✅
- `upcoming_player_game_context` processes tomorrow's games ✅
- **Result:** Tomorrow's games are known, context available

**2. Phase 4 Upstream Processors (10:00-11:45 PM)**
```python
# player_daily_cache_processor.py
is_early_season(date(2023, 10, 25), 2023, days_threshold=7)  # True (day 0)
# SKIP - no records written

# player_shot_zone_analysis_processor.py
is_early_season(date(2023, 10, 25), 2023, days_threshold=7)  # True (day 0)
# SKIP - no records written

# team_defense_zone_analysis_processor.py
is_early_season(date(2023, 10, 25), 2023, days_threshold=7)  # True (day 0)
# SKIP - no records written
```

**3. Phase 4 ML Feature Store (12:00 AM)**
```python
# ml_feature_store_processor.py
is_early_season(date(2023, 10, 25), 2023, days_threshold=7)  # True (day 0)
# CREATE placeholders

_create_early_season_placeholders(date(2023, 10, 25))
# Writes 450 placeholder records with all features=NULL
```

**4. Phase 5 Predictions (12:15 AM)**
```python
# worker.py
features = load_features('lebron-james', date(2023, 10, 25))
# Gets: {'features': [None, None, ...], 'feature_quality_score': 0.0}

is_valid = validate_features(features, min_quality_score=70.0)
# Returns False (0.0 < 70.0)

# Returns empty predictions
return {
    'predictions': [],
    'metadata': {
        'skip_reason': 'invalid_features',
        'error_message': 'Invalid features: quality_score too low (0.0 < 70.0)',
        'early_season_detected': True
    }
}
```

**5. User Experience**
- No predictions shown
- System logs: "Early season: insufficient data"
- Can show message: "Predictions available after Nov 1"

---

### Scenario: Day 7+ (Nov 1, 2023)

**1. Phase 4 Upstream Processors**
```python
is_early_season(date(2023, 11, 1), 2023, days_threshold=7)  # False (day 7)
# PROCESS normally

# player_daily_cache calculates with partial windows
points_avg_last_10 = calculate_average(last_7_games)  # Only 7 games available
points_avg_last_10_games_used = 7
quality_score = 7 / 10.0 = 0.70 (70%)
```

**2. Phase 4 ML Feature Store**
```python
is_early_season(date(2023, 11, 1), 2023, days_threshold=7)  # False (day 7)
# PROCESS normally

# Aggregates features from upstream processors
# Features have partial windows but non-NULL values
```

**3. Phase 5 Predictions**
```python
features = load_features('lebron-james', date(2023, 11, 1))
# Gets: {'features': [18.5, 17.2, ...], 'feature_quality_score': 72.0}

is_valid = validate_features(features, min_quality_score=70.0)
# Returns True (72.0 >= 70.0)

# Generates predictions!
predictions = [
    {'system': 'moving_average', 'predicted_points': 19.5},
    {'system': 'xgboost', 'predicted_points': 21.2},
    # ... other systems ...
]
```

---

## Benefits of Hybrid Approach

### ✅ Visibility
```sql
-- Can see WHY predictions skipped
SELECT
    game_date,
    COUNT(*) as players,
    AVG(feature_quality_score) as avg_quality,
    COUNT(CASE WHEN early_season_flag THEN 1 END) as early_season_count
FROM ml_feature_store_v2
WHERE game_date BETWEEN '2023-10-25' AND '2023-11-05'
GROUP BY game_date
ORDER BY game_date;

-- Results:
-- 2023-10-25: 450 players, 0.0 quality, 450 early_season
-- 2023-10-26: 450 players, 0.0 quality, 450 early_season
-- ...
-- 2023-11-01: 450 players, 72.5 quality, 0 early_season
```

### ✅ Debugging
```sql
-- Trace why specific player had no prediction
SELECT
    player_lookup,
    game_date,
    early_season_flag,
    insufficient_data_reason,
    feature_quality_score,
    is_production_ready
FROM ml_feature_store_v2
WHERE player_lookup = 'lebron-james'
  AND game_date = '2023-10-25';

-- Result: early_season_flag=TRUE, reason='early_season_skip_first_7_days'
```

### ✅ User Messaging
```python
# Can detect early season in UI
if record.early_season_flag:
    message = "Predictions available after Nov 1 (insufficient historical data)"
elif record.feature_quality_score < 70:
    message = "Low data quality - prediction not recommended"
elif not record.is_production_ready:
    message = "Data incomplete - prediction unavailable"
```

### ✅ Consistency
- Uses existing `_create_early_season_placeholders()` pattern
- No new code needed in Phase 5
- Aligns with current architecture

---

## Summary

**Days 0-6 (Early Season):**
1. Phase 4 upstream processors → SKIP (no records)
2. ML Feature Store → CREATE placeholders (NULL features, early_season_flag=TRUE)
3. Phase 5 → SKIP predictions (validation fails, quality=0.0)
4. User → No predictions, clear messaging

**Days 7+ (Regular Season):**
1. Phase 4 upstream processors → PROCESS (partial windows with min_periods=1)
2. ML Feature Store → PROCESS (aggregate partial features, quality 70-90%)
3. Phase 5 → PREDICT (validation passes, use partial data)
4. User → Predictions available, quality scores shown

**No changes needed in Phase 5!** Existing validation handles everything.
