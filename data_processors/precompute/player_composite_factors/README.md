# Player Composite Factors Processor

**Phase 4 Precompute | Version 1.0 | Production-Ready**

Pre-calculates composite adjustment factors that influence NBA player point predictions by combining multiple contextual signals (fatigue, matchups, pace, usage) into quantified adjustments.

---

## 📊 Quick Stats

| Metric | Value |
|--------|-------|
| **Status** | ✅ Production-Ready |
| **Version** | v1_4factors |
| **Tests** | 54/54 passing (46 unit + 8 integration) |
| **Runtime** | ~10-15 minutes (450 players) |
| **Schedule** | Nightly at 11:30 PM |
| **Output Table** | `nba_precompute.player_composite_factors` |
| **Dependencies** | 4 upstream tables (Phase 3 & 4) |

---

## 🎯 What It Does

### The Problem

Raw player statistics don't account for important contextual factors:
- Is the player exhausted from back-to-back games?
- Does their scoring style match up well against tonight's opponent?
- Will the game pace create more or fewer scoring opportunities?
- Is their usage about to spike because a teammate is injured?

### The Solution

This processor calculates **composite adjustment factors** that quantify these contextual impacts:

```
Base Prediction: 25.0 points (player's recent average)
+ Fatigue Adjustment: -1.0 (slightly tired)
+ Shot Zone Mismatch: +5.2 (favorable matchup)
+ Pace Adjustment: +2.5 (fast game)
+ Usage Spike: +1.8 (teammate out)
= Adjusted Prediction: 33.5 points
```

### Week 1-4 Strategy: 4 Active + 4 Deferred

**Active Factors (Implemented):**
1. ✅ **Fatigue Score** (0-100) → Adjustment (-5.0 to 0.0)
2. ✅ **Shot Zone Mismatch** (-10.0 to +10.0)
3. ✅ **Pace Score** (-3.0 to +3.0)
4. ✅ **Usage Spike** (-3.0 to +3.0)

**Deferred Factors (Set to 0):**
5. ⏳ **Referee Favorability** (0.0) - Implement after 3 months if XGBoost shows >5% importance
6. ⏳ **Look-Ahead Pressure** (0.0) - Implement after 3 months if XGBoost shows >5% importance
7. ⏳ **Travel Impact** (0.0) - Implement after 3 months if XGBoost shows >5% importance
8. ⏳ **Opponent Strength** (0.0) - Implement after 3 months if XGBoost shows >5% importance

**Why defer?** We'll let XGBoost's feature importance tell us which additional factors actually matter before spending engineering time on them.

---

## 🏗️ Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 3: ANALYTICS                           │
│  ┌──────────────────────────┐  ┌──────────────────────────┐   │
│  │ upcoming_player_game_    │  │ upcoming_team_game_      │   │
│  │ context                  │  │ context                  │   │
│  │ (fatigue, usage, pace)   │  │ (betting lines, pace)    │   │
│  └──────────────────────────┘  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 4: PRECOMPUTE                          │
│  ┌──────────────────────────┐  ┌──────────────────────────┐   │
│  │ player_shot_zone_        │  │ team_defense_zone_       │   │
│  │ analysis                 │  │ analysis                 │   │
│  │ (scoring patterns)       │  │ (defensive weaknesses)   │   │
│  └──────────────────────────┘  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│        PLAYER COMPOSITE FACTORS PROCESSOR (THIS ONE!)           │
│                                                                  │
│  1. Extract data from 4 sources                                 │
│  2. Check for early season (insufficient data)                  │
│  3. Calculate 4 active factor scores                            │
│  4. Convert scores to point adjustments                         │
│  5. Sum to total composite adjustment                           │
│  6. Add quality checks & source tracking                        │
│  7. Write to BigQuery                                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                OUTPUT TABLE                                      │
│  nba_precompute.player_composite_factors                        │
│  ~450 players × ~150 days/season = ~67,500 rows/year           │
└─────────────────────────────────────────────────────────────────┘
```

### Processing Strategy

**Normal Season:**
- For each player with an upcoming game:
  - Calculate fatigue score from rest & workload
  - Calculate shot zone mismatch from player patterns vs opponent defense
  - Calculate pace score from expected game tempo
  - Calculate usage spike from projected vs recent usage
  - Convert scores to point adjustments
  - Sum to total composite adjustment
  - Add metadata, quality checks, source tracking

**Early Season:**
- When >50% of players lack historical data:
  - Create placeholder records with NULL scores
  - Set `early_season_flag = TRUE`
  - Document reason for insufficient data

---

## 🧮 Factor Calculations

### 1. Fatigue Score (0-100)

**Higher score = Better rested**

**Inputs:**
- Days rest (0 = back-to-back, 1-2 = normal, 3+ = bonus)
- Recent workload (games & minutes in last 7 days)
- Recent back-to-backs (last 14 days)
- Player age (30+ penalty, 35+ bigger penalty)

**Algorithm:**
```python
score = 100  # Start at baseline

# Days rest impact
if back_to_back:
    score -= 15  # Heavy penalty
elif days_rest >= 3:
    score += 5   # Bonus

# Recent workload
if games_last_7 >= 4:
    score -= 10  # Playing frequently
if minutes_last_7 > 240:
    score -= 10  # Heavy minutes
if avg_mpg_last_7 > 35:
    score -= 8   # Long stretches

# Recent B2Bs
if back_to_backs_last_14 >= 2:
    score -= 12  # Multiple B2Bs
elif back_to_backs_last_14 == 1:
    score -= 5

# Age penalty
if age >= 35:
    score -= 10  # Veteran
elif age >= 30:
    score -= 5

# Clamp to 0-100
score = max(0, min(100, score))
```

**Conversion to Adjustment:**
```python
adjustment = (fatigue_score - 100) / 20.0
# 100 → 0.0 (no impact)
# 80 → -1.0
# 50 → -2.5
# 0 → -5.0 (maximum penalty)
```

**Examples:**
- Fresh player (100) → 0.0 adjustment
- Normal rest (85) → -0.75 adjustment
- Back-to-back (65) → -1.75 adjustment
- Exhausted (45) → -2.75 adjustment

---

### 2. Shot Zone Mismatch Score (-10.0 to +10.0)

**Positive = Favorable matchup | Negative = Unfavorable matchup**

**Inputs:**
- Player's primary scoring zone (paint/mid-range/perimeter)
- Player's usage rate in that zone (%)
- Opponent's defense rating in that zone (vs league avg)

**Algorithm:**
```python
# Get player's primary zone and usage
primary_zone = 'paint'  # or 'mid_range' or 'perimeter'
zone_usage_pct = 65.0   # Player shoots 65% from paint

# Get opponent's defense in that zone
defense_rating = 4.3    # Opponent allows +4.3 pts/100 in paint (weak)

# Calculate mismatch
base_mismatch = defense_rating  # Positive = weak defense (good for offense)

# Weight by zone usage (50%+ = full weight, lower = reduced)
usage_weight = min(zone_usage_pct / 50.0, 1.0)
weighted_mismatch = base_mismatch * usage_weight

# Apply extreme matchup bonus (20% boost if abs > 5.0)
if abs(weighted_mismatch) > 5.0:
    weighted_mismatch *= 1.2

# Clamp to -10.0 to +10.0
score = max(-10.0, min(10.0, weighted_mismatch))
```

**Direct Conversion:** Score = Adjustment (no transformation needed)

**Examples:**
- Paint scorer vs weak paint defense (+4.3) → +4.3 adjustment
- Perimeter scorer vs strong 3PT defense (-3.2) → -3.2 adjustment
- Mid-range scorer vs average defense (0.0) → 0.0 adjustment
- Paint scorer with low zone usage (+4.3 × 0.6) → +2.6 adjustment

---

### 3. Pace Score (-3.0 to +3.0)

**Positive = Fast game (more possessions) | Negative = Slow game (fewer possessions)**

**Inputs:**
- Pace differential (expected game pace vs league average)

**Algorithm:**
```python
pace_diff = expected_game_pace - league_avg_pace  # e.g., 105.0 - 100.0 = 5.0

# Scale down to adjustment range
pace_score = pace_diff / 2.0  # 5.0 → +2.5

# Clamp to -3.0 to +3.0
score = max(-3.0, min(3.0, pace_score))
```

**Direct Conversion:** Score = Adjustment

**Examples:**
- Very fast game (+6.0 pace diff) → +3.0 adjustment (capped)
- Fast game (+5.0 pace diff) → +2.5 adjustment
- Normal pace (0.0 pace diff) → 0.0 adjustment
- Slow game (-4.0 pace diff) → -2.0 adjustment

---

### 4. Usage Spike Score (-3.0 to +3.0)

**Positive = More shots expected | Negative = Fewer shots expected**

**Inputs:**
- Projected usage rate (tonight's expected usage)
- Baseline usage rate (recent 7-game average)
- Star teammates out (0, 1, 2+)

**Algorithm:**
```python
projected_usage = 28.5
baseline_usage = 24.2
stars_out = 1

# Calculate differential
usage_diff = projected_usage - baseline_usage  # 4.3

# Scale to adjustment range
base_score = usage_diff * 0.3  # 4.3 × 0.3 = 1.29

# Apply star teammates out boost (only for positive spikes)
if stars_out > 0 and base_score > 0:
    if stars_out >= 2:
        base_score *= 1.30  # 30% boost
    else:
        base_score *= 1.15  # 15% boost

# Clamp to -3.0 to +3.0
score = max(-3.0, min(3.0, base_score))
```

**Direct Conversion:** Score = Adjustment

**Examples:**
- Usage spike with 1 star out (+4.3 → +1.29 → +1.48 after boost)
- Usage spike with 2 stars out (+4.3 → +1.29 → +1.68 after boost)
- Usage drop (-5.0 → -1.5, no boost on negative)
- Stable usage (0.0 → 0.0)

---

## 📦 Dependencies

### Required Upstream Tables

| Table | Dataset | Phase | Update Time | Description |
|-------|---------|-------|-------------|-------------|
| `upcoming_player_game_context` | nba_analytics | 3 | 10:00 PM | Player fatigue, usage, pace indicators |
| `upcoming_team_game_context` | nba_analytics | 3 | 10:05 PM | Team betting lines, pace metrics |
| `player_shot_zone_analysis` | nba_precompute | 4 | 11:15 PM | Player scoring zone patterns |
| `team_defense_zone_analysis` | nba_precompute | 4 | 11:10 PM | Team defensive zone weaknesses |

### Dependency Check

Processor automatically checks dependencies before running:
```python
# Checks performed:
- ✅ All 4 tables exist
- ✅ Data for target date exists
- ✅ Data is <24 hours old
- ✅ Expected row counts met
```

**If dependencies fail:**
- Processor raises `ValueError` with details
- No partial data written
- Clear error message for debugging

---

## ⚙️ Configuration

### Required Options

```python
opts = {
    'analysis_date': '2025-11-01'  # Date to analyze (YYYY-MM-DD)
}
```

### Environment Variables

```bash
# BigQuery project
export GCP_PROJECT_ID="nba-props-platform"

# Service account credentials
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

### Processor Settings

**Table Configuration:**
```python
table_name = "player_composite_factors"
dataset_id = "nba_precompute"
processing_strategy = "MERGE_UPDATE"  # Upsert on (player_lookup, game_date)
```

**League Constants:**
```python
league_avg_pace = 100.0  # Baseline NBA pace
calculation_version = "v1_4factors"
```

---

## 🚀 Usage

### Command Line

```bash
# Run for today's date
python -m data_processors.precompute.player_composite_factors.player_composite_factors_processor \
  --analysis_date=$(date +%Y-%m-%d)

# Run for specific date
python -m data_processors.precompute.player_composite_factors.player_composite_factors_processor \
  --analysis_date=2025-11-01

# Run in development mode (with verbose logging)
python -m data_processors.precompute.player_composite_factors.player_composite_factors_processor \
  --analysis_date=2025-11-01 \
  --log_level=DEBUG
```

### Python API

```python
from data_processors.precompute.player_composite_factors.player_composite_factors_processor import (
    PlayerCompositeFactorsProcessor
)
from datetime import date

# Initialize processor
processor = PlayerCompositeFactorsProcessor()

# Set options
processor.opts = {'analysis_date': date(2025, 11, 1)}

# Run full workflow
processor.run()

# Check results
print(f"Processed {len(processor.transformed_data)} players")
print(f"Failed {len(processor.failed_entities)} players")
```

### Scheduling (Cloud Composer / Airflow)

```python
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'start_date': datetime(2025, 10, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'player_composite_factors_nightly',
    default_args=default_args,
    description='Calculate player composite factors',
    schedule_interval='30 23 * * *',  # 11:30 PM daily
    catchup=False,
)

# Wait for upstream processors
wait_player_shot_zone = SensorOperator(
    task_id='wait_player_shot_zone',
    # ... sensor config ...
    dag=dag,
)

wait_team_defense_zone = SensorOperator(
    task_id='wait_team_defense_zone',
    # ... sensor config ...
    dag=dag,
)

# Run processor
run_processor = BashOperator(
    task_id='run_composite_factors',
    bash_command=(
        'python -m data_processors.precompute.player_composite_factors.'
        'player_composite_factors_processor --analysis_date={{ ds }}'
    ),
    dag=dag,
)

# Set dependencies
[wait_player_shot_zone, wait_team_defense_zone] >> run_processor
```

---

## 📊 Output Schema

### Key Fields

```sql
-- Identifiers
player_lookup STRING              -- "lebronjames"
game_date DATE                    -- 2025-11-01
game_id STRING                    -- "20251101LAL_GSW"

-- Active Scores
fatigue_score INT64               -- 0-100
shot_zone_mismatch_score NUMERIC  -- -10.0 to +10.0
pace_score NUMERIC                -- -3.0 to +3.0
usage_spike_score NUMERIC         -- -3.0 to +3.0

-- Total
total_composite_adjustment NUMERIC -- Sum of all factors

-- Context (JSON strings)
fatigue_context_json STRING       -- Detailed fatigue breakdown
shot_zone_context_json STRING     -- Zone matchup details
pace_context_json STRING          -- Pace calculation details
usage_context_json STRING         -- Usage spike details

-- Quality
data_completeness_pct NUMERIC     -- 0.0-100.0
missing_data_fields STRING        -- Comma-separated list
has_warnings BOOLEAN              -- TRUE if issues detected
warning_details STRING            -- Description of warnings

-- Source Tracking (v4.0)
source_player_context_last_updated TIMESTAMP
source_player_context_rows_found INT64
source_player_context_completeness_pct NUMERIC
-- ... (12 total source tracking fields)

-- Early Season
early_season_flag BOOLEAN
insufficient_data_reason STRING

-- Processing
created_at TIMESTAMP
processed_at TIMESTAMP
```

### Sample Output

```json
{
  "player_lookup": "lebronjames",
  "game_date": "2025-11-01",
  "game_id": "20251101LAL_GSW",
  
  "fatigue_score": 100,
  "shot_zone_mismatch_score": 5.2,
  "pace_score": 1.8,
  "usage_spike_score": 0.0,
  
  "total_composite_adjustment": 7.00,
  
  "data_completeness_pct": 100.00,
  "has_warnings": false,
  "early_season_flag": null,
  
  "processed_at": "2025-11-01T23:45:00Z"
}
```

---

## 🧪 Testing

### Test Coverage: 54/54 Passing ✅

**Unit Tests (46 tests):**
```bash
cd tests/processors/precompute/player_composite_factors
python run_tests.py unit

# Expected: 46 passed in ~68 seconds
```

**Integration Tests (8 tests):**
```bash
python run_tests.py integration

# Expected: 8 passed in ~8 seconds
```

**All Tests:**
```bash
python run_tests.py quick

# Expected: 54 passed in ~76 seconds
```

### Test Categories

1. **Fatigue Calculation (7 tests)**
   - Fresh player high score
   - Back-to-back penalty
   - Heavy minutes penalty
   - Age penalty
   - Well-rested bonus
   - Score clamping
   - Missing field defaults

2. **Shot Zone Mismatch (8 tests)**
   - Favorable paint matchup
   - Unfavorable matchup
   - Extreme matchup bonus
   - Low zone usage impact
   - Perimeter scorer
   - Missing data handling
   - Score clamping

3. **Pace Calculation (5 tests)**
   - Fast game positive score
   - Slow game negative score
   - Neutral pace
   - Score clamping
   - Missing data handling

4. **Usage Spike (7 tests)**
   - Usage increase
   - Usage decrease
   - Star out boost (1 star)
   - Star out boost (2+ stars)
   - No boost on negative spike
   - Zero baseline handling
   - Score clamping

5. **Data Quality (8 tests)**
   - Completeness calculation
   - Missing data detection
   - Warning generation
   - Extreme value detection

6. **Integration (8 tests)**
   - Full end-to-end processing
   - Partial data handling
   - Dependency checking
   - Early season handling
   - Error handling
   - Source tracking population

### Running Specific Tests

```bash
# Run only fatigue tests
pytest test_unit.py::TestFatigueCalculation -v

# Run only integration tests
pytest test_integration.py -v

# Run with coverage report
pytest --cov=data_processors.precompute.player_composite_factors \
       --cov-report=html

# Run and stop on first failure
pytest -x
```

---

## 🐛 Troubleshooting

### Common Issues

#### Issue 1: Missing Dependencies

**Error:**
```
ValueError: Missing critical dependencies: nba_analytics.upcoming_player_game_context
```

**Cause:** Upstream Phase 3 processor hasn't run yet

**Solution:**
```bash
# Check if upstream data exists
bq query "SELECT COUNT(*) FROM nba_analytics.upcoming_player_game_context 
          WHERE game_date = '2025-11-01'"

# If count = 0, run upstream processor first
```

#### Issue 2: Stale Data

**Error:**
```
ValueError: Stale data detected: player_shot_zone_analysis is 36 hours old
```

**Cause:** Upstream data is too old (>24 hours)

**Solution:**
```bash
# Re-run upstream processor
python -m data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor \
  --analysis_date=2025-11-01
```

#### Issue 3: Early Season Mode

**Warning:**
```
WARNING: Early season detected - creating placeholder records
```

**Cause:** >50% of players have insufficient historical data (first ~10 games of season)

**Solution:** This is expected behavior. Records will have:
- `early_season_flag = TRUE`
- All scores = NULL
- `total_composite_adjustment = NULL`

#### Issue 4: Low Data Completeness

**Warning:**
```
WARNING: Player kevindurant has data_completeness_pct = 60.0
```

**Cause:** Some required data fields are missing

**Solution:**
```sql
-- Identify which source is incomplete
SELECT 
  player_lookup,
  missing_data_fields,
  source_player_context_completeness_pct,
  source_team_context_completeness_pct,
  source_player_shot_completeness_pct,
  source_team_defense_completeness_pct
FROM nba_precompute.player_composite_factors
WHERE game_date = '2025-11-01'
  AND data_completeness_pct < 85
```

#### Issue 5: Extreme Adjustments

**Warning:**
```
WARNING: Player has extreme total_composite_adjustment: 18.5
```

**Cause:** Multiple factors aligned to create unusually large adjustment

**Solution:**
```sql
-- Investigate which factors contributed
SELECT 
  player_lookup,
  total_composite_adjustment,
  fatigue_score,
  shot_zone_mismatch_score,
  pace_score,
  usage_spike_score,
  warning_details
FROM nba_precompute.player_composite_factors
WHERE game_date = '2025-11-01'
  AND ABS(total_composite_adjustment) > 15
```

---

## 📈 Monitoring

### Key Metrics to Track

1. **Processing Volume**
   ```sql
   -- Should be ~100-150 players on game days
   SELECT game_date, COUNT(*) as players_processed
   FROM nba_precompute.player_composite_factors
   WHERE game_date = CURRENT_DATE()
   GROUP BY game_date
   ```

2. **Data Quality**
   ```sql
   -- Average completeness should be >95%
   SELECT 
     game_date,
     AVG(data_completeness_pct) as avg_completeness,
     COUNT(CASE WHEN has_warnings THEN 1 END) as warnings_count
   FROM nba_precompute.player_composite_factors
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY game_date
   ```

3. **Source Staleness**
   ```sql
   -- All sources should be <24 hours old
   SELECT 
     game_date,
     MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), 
         source_player_context_last_updated, HOUR)) as max_age_hours
   FROM nba_precompute.player_composite_factors
   WHERE game_date = CURRENT_DATE()
   GROUP BY game_date
   ```

4. **Adjustment Distribution**
   ```sql
   -- Most adjustments should be between -5 and +5
   SELECT 
     CASE 
       WHEN total_composite_adjustment >= 5 THEN 'Very Favorable'
       WHEN total_composite_adjustment >= 2 THEN 'Favorable'
       WHEN total_composite_adjustment >= -2 THEN 'Neutral'
       WHEN total_composite_adjustment >= -5 THEN 'Unfavorable'
       ELSE 'Very Unfavorable'
     END as category,
     COUNT(*) as count
   FROM nba_precompute.player_composite_factors
   WHERE game_date = CURRENT_DATE()
   GROUP BY category
   ```

### Alert Conditions

Set up alerts if:
- ❌ Players processed <50 (should be ~100-150 on game days)
- ❌ Average completeness <85%
- ❌ Max source age >24 hours
- ❌ >5% of players with extreme adjustments (|adj| > 15)
- ❌ >10% of players with warnings
- ❌ Processing time >20 minutes

---

## 🔄 Development

### Project Structure

```
data_processors/precompute/player_composite_factors/
├── __init__.py
└── player_composite_factors_processor.py   # Main processor (913 lines)

tests/processors/precompute/player_composite_factors/
├── __init__.py
├── conftest.py                             # Test fixtures
├── test_unit.py                            # 46 unit tests
├── test_integration.py                     # 8 integration tests
└── run_tests.py                            # Test runner

schemas/bigquery/precompute/
└── player_composite_factors.sql            # Table schema
```

### Adding a New Factor

**Example: Add "Altitude Impact" factor**

1. **Update calculation method:**
```python
def _calculate_altitude_impact(self, player_row: pd.Series) -> float:
    """
    Calculate altitude impact score (-2.0 to +2.0).
    
    High altitude games (Denver) affect player performance.
    """
    home_altitude = player_row.get('home_team_altitude', 0)
    player_home_altitude = player_row.get('player_home_altitude', 0)
    
    altitude_diff = abs(home_altitude - player_home_altitude)
    
    if altitude_diff > 5000:  # Significant difference
        return -2.0  # Penalty
    elif altitude_diff > 3000:
        return -1.0
    
    return 0.0
```

2. **Add to main calculation flow:**
```python
def _calculate_player_composite(self, player_row: pd.Series) -> dict:
    # ... existing factors ...
    altitude_score = self._calculate_altitude_impact(player_row)
    altitude_adj = altitude_score  # Direct conversion
    
    total_adjustment = (
        fatigue_adj + shot_zone_adj + pace_adj + usage_spike_adj +
        altitude_adj  # Add new factor
    )
```

3. **Add to output record:**
```python
record = {
    # ... existing fields ...
    'altitude_impact_score': altitude_score,
    'altitude_context_json': json.dumps(
        self._build_altitude_context(player_row, altitude_score)
    ),
}
```

4. **Update schema:**
```sql
ALTER TABLE nba_precompute.player_composite_factors
ADD COLUMN altitude_impact_score NUMERIC(3,1);
```

5. **Add unit tests:**
```python
class TestAltitudeCalculation:
    def test_high_altitude_penalty(self, processor):
        # Test Denver game from sea level team
        pass
    
    def test_no_altitude_difference(self, processor):
        # Test same altitude game
        pass
```

6. **Update documentation:**
- Add to "Factor Calculations" section
- Add to field summary
- Add example outputs

---

## 📚 Additional Resources

### Related Processors

- **Phase 3: Upcoming Player Game Context** - Provides fatigue, usage, pace inputs
- **Phase 3: Upcoming Team Game Context** - Provides betting lines, team pace
- **Phase 4: Player Shot Zone Analysis** - Provides scoring zone patterns
- **Phase 4: Team Defense Zone Analysis** - Provides defensive weaknesses

### Documentation

- **BigQuery Schema:** `schemas/bigquery/precompute/player_composite_factors.sql`
- **Test Guide:** `tests/processors/precompute/player_composite_factors/README.md`
- **API Docs:** Generated via `pdoc` (run `pdoc --html player_composite_factors_processor`)

### Support

- **Slack:** #nba-props-data-team
- **Email:** data-team@company.com
- **On-Call:** PagerDuty rotation

---

## 📝 Version History

### v1.0 (November 1, 2025) - Initial Release

**Features:**
- ✅ 4 active factors implemented (fatigue, shot zone, pace, usage spike)
- ✅ 4 deferred factors (set to 0 for now)
- ✅ Early season handling (placeholder records)
- ✅ v4.0 source tracking (12 fields)
- ✅ Data quality checks (completeness, warnings)
- ✅ 54/54 tests passing
- ✅ Production-ready

**Deferred to v2.0:**
- ⏳ Referee favorability factor
- ⏳ Look-ahead pressure factor
- ⏳ Travel impact factor
- ⏳ Opponent strength factor

**Timeline:** Implement deferred factors after 3 months if XGBoost shows >5% feature importance

---

## ✅ Pre-Deployment Checklist

- [ ] All tests passing (54/54)
- [ ] BigQuery schema created
- [ ] Table partitioned by game_date
- [ ] Service account has write permissions
- [ ] Upstream dependencies verified
- [ ] Monitoring queries configured
- [ ] Alert thresholds set
- [ ] Documentation reviewed
- [ ] Smoke test completed (10 players)
- [ ] Full test run completed (450 players)
- [ ] Scheduled job configured (11:30 PM)
- [ ] On-call team notified
- [ ] Rollback plan documented

---

## 🎯 Success Criteria

**Week 1:**
- ✅ Processor runs successfully nightly
- ✅ All 4 factors calculating correctly
- ✅ >95% data completeness
- ✅ <5% warning rate
- ✅ Runtime <15 minutes

**Month 1:**
- ✅ Zero manual interventions needed
- ✅ XGBoost training includes composite factors
- ✅ Initial feature importance analysis complete

**Month 3:**
- ✅ XGBoost feature importance stable (>100 training runs)
- ✅ Decision on deferred factors (implement if >5% importance)
- ✅ v2.0 planning based on feature importance

---

## 📄 License

Copyright © 2025 NBA Props Platform. All rights reserved.

---

**Last Updated:** November 1, 2025  
**Maintained By:** Data Engineering Team  
**Status:** ✅ Production-Ready