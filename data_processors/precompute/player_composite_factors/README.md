# Player Composite Factors Processor

**Path:** `data_processors/precompute/player_composite_factors/`  
**Type:** Phase 4 Precompute Processor  
**Version:** 1.0 (Week 1-4: 4 Active Factors)  
**Output:** `nba_precompute.player_composite_factors`

---

## Overview

Calculates composite adjustment factors for each player's upcoming game by combining multiple contextual elements (fatigue, matchup, pace, usage) into quantified scores. These factors adjust base predictions in Phase 5.

**Week 1-4 Strategy:**
- ✅ **4 Active Factors:** fatigue, shot_zone_mismatch, pace, usage_spike
- ⏸️ **4 Deferred Factors:** referee, look_ahead, matchup_history, momentum (set to 0)
- 📊 **After 3 months:** Analyze XGBoost feature importance to decide which deferred factors to implement

---

## Quick Start

### Run the Processor

```python
from data_processors.precompute.player_composite_factors import PlayerCompositeFactorsProcessor
from datetime import date

processor = PlayerCompositeFactorsProcessor()
result = processor.run({'analysis_date': date.today()})

print(f"Status: {result['status']}")
print(f"Players processed: {len(result['transformed_data'])}")
```

### Run from Command Line

```bash
# Test run
python player_composite_factors_processor.py

# With specific date
python player_composite_factors_processor.py --date 2025-10-30
```

---

## Dependencies

### Upstream Sources (4 Critical)

| Source | Purpose | Fields Used |
|--------|---------|-------------|
| `nba_analytics.upcoming_player_game_context` | Player fatigue, usage, pace | days_rest, minutes, usage rates, pace_differential |
| `nba_analytics.upcoming_team_game_context` | Team context, betting lines | game_total, game_spread |
| `nba_precompute.player_shot_zone_analysis` | Player shot preferences | primary_scoring_zone, zone rates |
| `nba_precompute.team_defense_zone_analysis` | Opponent defense | paint/mid/three_defense_vs_league_avg |

### Must Run After

1. `team_defense_zone_analysis` (11:00 PM)
2. `player_shot_zone_analysis` (11:15 PM)

---

## Factor Calculations

### 1. Fatigue Score (0-100)

**Range:** 0 (exhausted) to 100 (fresh)

**Inputs:**
- days_rest, back_to_back
- games_in_last_7_days, minutes_in_last_7_days
- back_to_backs_last_14_days
- player_age

**Logic:**
```python
score = 100  # Start fresh

# Penalties
if back_to_back: score -= 15
if games_last_7 >= 4: score -= 10
if minutes_last_7 > 240: score -= 10
if avg_mpg > 35: score -= 8
if b2b_last_14 >= 2: score -= 12
if age >= 35: score -= 5
elif age >= 30: score -= 3

# Bonuses
if days_rest >= 3: score += 5

# Clamp to 0-100
score = max(0, min(100, score))
```

**Adjustment:** `(score - 100) × 0.05` → Range: 0.0 to -5.0

**Example:**
- Back-to-back game, 250 minutes last 7 days, age 32
- Score: 68 → Adjustment: -1.6 points

---

### 2. Shot Zone Mismatch Score (-10.0 to +10.0)

**Range:** -10.0 (bad matchup) to +10.0 (favorable matchup)

**Inputs:**
- Player: primary_scoring_zone, zone_rate_last_10
- Opponent: zone_defense_vs_league_avg

**Logic:**
```python
# Get opponent defense in player's primary zone
if primary_zone == 'paint':
    opp_defense = paint_defense_vs_league_avg
    zone_freq = paint_rate_last_10

# Positive defense rating = weak defense = good matchup
score = opp_defense

# Weight by zone usage
zone_weight = min(zone_freq / 50.0, 1.0)
score *= zone_weight

# Extreme matchup bonus
if abs(score) > 5.0:
    score *= 1.2

# Clamp to -10.0 to +10.0
score = max(-10.0, min(10.0, score))
```

**Adjustment:** Direct conversion (score = adjustment)

**Example:**
- Paint-dominant player (65% of shots) vs weak paint defense (+4.3 pp vs league)
- Score: +5.2 → Adjustment: +5.2 points

---

### 3. Pace Score (-3.0 to +3.0)

**Range:** -3.0 (slow game) to +3.0 (fast game)

**Inputs:**
- pace_differential

**Logic:**
```python
# Scale pace differential
score = pace_differential / 2.0

# Clamp to -3.0 to +3.0
score = max(-3.0, min(3.0, score))
```

**Adjustment:** Direct conversion (score = adjustment)

**Example:**
- Fast game expected (pace_differential = +5.2)
- Score: +2.6 → Adjustment: +2.6 points

---

### 4. Usage Spike Score (-3.0 to +3.0)

**Range:** -3.0 (usage drop) to +3.0 (usage spike)

**Inputs:**
- projected_usage_rate, avg_usage_rate_last_7_games
- star_teammates_out

**Logic:**
```python
# Calculate usage differential
usage_diff = projected_usage - avg_usage_last_7

# Scale (10% usage change is significant)
score = usage_diff × 0.3

# Boost if stars are out
if star_teammates_out >= 2 and score > 0:
    score *= 1.3
elif star_teammates_out == 1 and score > 0:
    score *= 1.15

# Clamp to -3.0 to +3.0
score = max(-3.0, min(3.0, score))
```

**Adjustment:** Direct conversion (score = adjustment)

**Example:**
- 1 star teammate out, usage up from 24.2% to 28.5%
- Usage diff: +4.3 → Scaled: +1.29 → Boosted: +1.48 → Adjustment: +1.5 points

---

### Deferred Factors (Week 1-4)

All set to 0 (neutral):
- `referee_favorability_score`: 0.0
- `look_ahead_pressure_score`: 0.0
- `matchup_history_score`: 0
- `momentum_score`: 0

---

## Total Composite Adjustment

```python
total_composite_adjustment = (
    fatigue_adjustment +
    shot_zone_adjustment +
    pace_adjustment +
    usage_spike_adjustment +
    0.0 +  # referee
    0.0 +  # look_ahead
    0.0 +  # matchup_history
    0.0    # momentum
)
```

**Typical Range:** -15.0 to +15.0 points

**Interpretation:**
- `> +8.0`: Very favorable game setup
- `+3.0 to +8.0`: Favorable
- `-3.0 to +3.0`: Neutral
- `-8.0 to -3.0`: Unfavorable
- `< -8.0`: Very unfavorable

---

## Output Schema

**Key Fields:**

```python
{
  # Identifiers
  'player_lookup': str,
  'universal_player_id': str,
  'game_date': date,
  'game_id': str,
  
  # Active Scores
  'fatigue_score': int,               # 0-100
  'shot_zone_mismatch_score': float,  # -10.0 to +10.0
  'pace_score': float,                # -3.0 to +3.0
  'usage_spike_score': float,         # -3.0 to +3.0
  
  # Adjustments
  'fatigue_adjustment': float,
  'shot_zone_adjustment': float,
  'pace_adjustment': float,
  'usage_spike_adjustment': float,
  'total_composite_adjustment': float,
  
  # Context (JSON)
  'fatigue_context': json,
  'shot_zone_context': json,
  'pace_context': json,
  'usage_context': json,
  
  # Quality
  'data_completeness_pct': float,
  'has_warnings': bool,
  'warning_details': str,
  
  # v4.0 Source Tracking (12 fields)
  'source_player_context_last_updated': timestamp,
  'source_player_context_rows_found': int,
  'source_player_context_completeness_pct': float,
  # ... (3 fields × 4 sources)
  
  # Early Season
  'early_season_flag': bool,
  'insufficient_data_reason': str
}
```

**See full schema:** `schemas/bigquery/precompute/player_composite_factors.sql`

---

## Configuration

### Processor Settings

```python
# In __init__()
self.table_name = 'player_composite_factors'
self.entity_type = 'player'
self.entity_field = 'player_lookup'

self.calculation_version = "v1_4factors"
self.factors_active = "fatigue,shot_zone,pace,usage_spike"
self.factors_deferred = "referee,look_ahead,matchup_history,momentum"

self.league_avg_pace = 100.0
```

### Dependency Configuration

```python
def get_dependencies(self) -> dict:
    return {
        'nba_analytics.upcoming_player_game_context': {
            'field_prefix': 'source_player_context',
            'check_type': 'date_match',
            'expected_count_min': 50,
            'max_age_hours_warn': 12,
            'max_age_hours_fail': 48,
            'critical': True
        },
        # ... 3 more sources
    }
```

---

## Testing

### Unit Tests

```bash
# Run all unit tests
pytest tests/processors/precompute/player_composite_factors/test_player_composite_factors.py -v

# Run specific test
pytest tests/processors/precompute/player_composite_factors/test_player_composite_factors.py::test_fatigue_calculation -v
```

### Integration Tests

```bash
# Run integration tests
pytest tests/processors/precompute/player_composite_factors/test_integration.py -v
```

### Manual Testing

```python
# test_manual.py
from player_composite_factors_processor import PlayerCompositeFactorsProcessor
import pandas as pd

processor = PlayerCompositeFactorsProcessor()

# Test fatigue calculation
player_row = pd.Series({
    'days_rest': 0,
    'back_to_back': True,
    'games_in_last_7_days': 4,
    'minutes_in_last_7_days': 250,
    'avg_minutes_per_game_last_7': 36.0,
    'back_to_backs_last_14_days': 2,
    'player_age': 32
})

score = processor._calculate_fatigue_score(player_row)
print(f"Fatigue Score: {score}")  # Should be ~65-75 (tired)
```

---

## Monitoring

### Check Daily Success

```sql
SELECT 
  game_date,
  COUNT(*) as players_processed,
  AVG(total_composite_adjustment) as avg_adjustment,
  COUNT(CASE WHEN has_warnings THEN 1 END) as warnings
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;
```

**Expected:**
- Players: 100-150 (on game days)
- Avg adjustment: -1.0 to +1.0
- Warnings: <5%

### Check Data Quality

```sql
SELECT 
  AVG(data_completeness_pct) as avg_completeness,
  MIN(data_completeness_pct) as min_completeness,
  AVG(source_player_context_completeness_pct) as player_context,
  AVG(source_player_shot_completeness_pct) as player_shot,
  AVG(source_team_defense_completeness_pct) as team_defense
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE();
```

**Expected:**
- All completeness: >95%
- If <85%: Investigate missing data

### Find Issues

```sql
SELECT 
  player_lookup,
  data_completeness_pct,
  missing_data_fields,
  warning_details
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND (data_completeness_pct < 85 OR has_warnings = TRUE)
ORDER BY data_completeness_pct ASC;
```

---

## Troubleshooting

### Problem: No Players Processed

**Possible Causes:**
1. No games scheduled for analysis_date
2. Upstream tables not populated

**Check:**
```sql
-- Are there upcoming games?
SELECT COUNT(*) FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();

-- Did zone analysis run?
SELECT COUNT(*) FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```

---

### Problem: Low Data Completeness

**Possible Causes:**
1. Zone analysis in early season
2. Upstream data missing
3. New players without history

**Check:**
```sql
-- Check for early season flags
SELECT 
  COUNT(*) as total,
  COUNT(CASE WHEN early_season_flag THEN 1 END) as early_season
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```

---

### Problem: Extreme Adjustments

**Possible Causes:**
1. All factors align (rare but valid)
2. Data quality issue

**Check:**
```sql
-- Find extreme adjustments
SELECT 
  player_lookup,
  total_composite_adjustment,
  fatigue_adjustment,
  shot_zone_adjustment,
  pace_adjustment,
  usage_spike_adjustment,
  fatigue_context,
  shot_zone_context
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND ABS(total_composite_adjustment) > 12.0;
```

**Action:**
- Review context JSON to understand why
- Typically valid if all factors align
- Alert if >5% of players have extreme adjustments

---

### Problem: Missing Source Data

**Possible Causes:**
1. Upstream processor failed
2. Upstream processor still running

**Check:**
```sql
-- Check source ages
SELECT 
  MAX(TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(),
    source_player_context_last_updated,
    HOUR
  )) as player_context_age,
  MAX(TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(),
    source_player_shot_last_updated,
    HOUR
  )) as player_shot_age
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE();
```

**Action:**
- If >24 hours: Investigate upstream processor
- If <24 hours but >12 hours: Warning threshold (expected)

---

## Development

### Adding a New Factor

**If XGBoost shows a deferred factor has >5% importance:**

1. **Update calculation_version:**
   ```python
   self.calculation_version = "v2_5factors"
   self.factors_active = "fatigue,shot_zone,pace,usage_spike,referee"
   ```

2. **Implement calculation:**
   ```python
   def _calculate_referee_favorability(self, ...):
       # Your logic here
       return score
   ```

3. **Add to calculate_precompute():**
   ```python
   referee_score = self._calculate_referee_favorability(...)
   referee_adj = referee_score  # or custom conversion
   ```

4. **Update total:**
   ```python
   total_adj = (...existing... + referee_adj)
   ```

5. **Add context:**
   ```python
   referee_context = self._build_referee_context(...)
   ```

6. **Update tests!**

---

### Modifying Factor Weights

To A/B test different weight configurations:

1. **Add weight config:**
   ```python
   self.factor_weights = {
       'fatigue': 0.05,      # Current
       'shot_zone': 1.0,     # Direct
       'pace': 1.0,          # Direct
       'usage_spike': 0.3    # Current
   }
   ```

2. **Apply in calculations:**
   ```python
   fatigue_adj = (fatigue_score - 100) * self.factor_weights['fatigue']
   ```

3. **Track version:**
   ```python
   self.calculation_version = "v1_4factors_weightedA"
   ```

---

## Performance

**Expected Runtime:**
- Players: 450 with upcoming games
- Processing: 2-3 seconds per player
- Total: 10-15 minutes

**BigQuery Costs:**
- 4 source queries: ~50 MB each = 200 MB
- 450 players × 200 MB = 90 GB scanned
- Cost: ~$0.45 per run
- Monthly (30 days): ~$13.50

---

## Related Documentation

- **Data Mapping:** `docs/data_mapping/player_composite_factors_data_mapping.md`
- **Schema:** `schemas/bigquery/precompute/player_composite_factors.sql`
- **Implementation Guide:** `docs/implementation/player_composite_factors_implementation.md`
- **Base Class:** `data_processors/precompute/precompute_base.py`
- **Dependency Tracking:** `docs/architecture/dependency_tracking_v4.md`

---

## Version History

### v1.0 (October 30, 2025)
- Initial implementation
- 4 active factors: fatigue, shot_zone_mismatch, pace, usage_spike
- 4 deferred factors set to 0
- v4.0 dependency tracking
- Early season handling
- Comprehensive data quality checks

---

## Support

**Issues:** File in project issue tracker  
**Questions:** #nba-props-platform-dev Slack channel  
**Owner:** Data Engineering Team

---

## License

Internal use only - NBA Props Platform