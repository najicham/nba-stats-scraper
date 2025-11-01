# Player Daily Cache Processor

**Path:** `data_processors/precompute/player_daily_cache/`  
**Version:** 1.0  
**Date:** October 30, 2025  
**Priority:** MEDIUM (Optional optimization for Phase 5)

## Purpose

Cache static daily player data that won't change during the day. This eliminates repeated BigQuery queries during Phase 5 real-time updates when prop lines change throughout the day.

### Performance Impact

- **Cost Savings:** 79% reduction ($27/month savings)
  - Without cache: ~$34/month (repeated queries)
  - With cache: ~$7/month (single nightly query)
- **Speed:** 2000x faster lookups
  - BigQuery query: 2-3 seconds per update
  - Cache lookup: <1 millisecond per update

### Business Value

Enables Phase 5 to provide **fast real-time predictions** when prop lines change:
- Load cache once at 6 AM (450 players)
- Reuse cached data for 10-50 updates throughout the day
- No repeated BigQuery queries needed

---

## Data Flow

```
Phase 3: Analytics Tables
  ├─ player_game_summary (recent performance)
  ├─ team_offense_game_summary (team context)
  └─ upcoming_player_game_context (fatigue metrics)
       ↓
Phase 4: Precompute Tables
  └─ player_shot_zone_analysis (shot tendencies)
       ↓
Phase 4: player_daily_cache ← THIS PROCESSOR
       ↓
Phase 5: Prediction Systems (6 AM load + real-time updates)
```

---

## Dependencies

### Critical Dependencies (All Must Be Present)

1. **nba_analytics.player_game_summary** (Phase 3)
   - Source: Recent performance stats
   - Fields: points, minutes, usage_rate, ts_pct, assisted_fg_makes
   - Requirement: Season to date games (5-82 games per player)

2. **nba_analytics.team_offense_game_summary** (Phase 3)
   - Source: Team context
   - Fields: pace, offensive_rating
   - Requirement: Last 10 games per team

3. **nba_analytics.upcoming_player_game_context** (Phase 3)
   - Source: Fatigue metrics, player age
   - Fields: games_in_last_X_days, minutes_in_last_X_days, back_to_backs, player_age
   - Requirement: Today's context for all scheduled players

4. **nba_precompute.player_shot_zone_analysis** (Phase 4)
   - Source: Shot zone tendencies
   - Fields: primary_scoring_zone, paint_rate_last_10, three_pt_rate_last_10
   - Requirement: Today's analysis for all scheduled players
   - **MUST RUN BEFORE THIS PROCESSOR**

---

## Output Schema

**Table:** `nba_precompute.player_daily_cache`  
**Partitioned By:** `cache_date`  
**Clustered By:** `player_lookup`, `universal_player_id`

### Field Categories (43 total fields)

- **Identifiers** (3): player_lookup, universal_player_id, cache_date
- **Recent Performance** (8): averages, volatility, efficiency
- **Team Context** (3): pace, offensive rating, usage
- **Fatigue Metrics** (7): games/minutes in various windows
- **Shot Zones** (4): primary zone, rates
- **Demographics** (1): player_age
- **Source Tracking** (12): 4 sources × 3 fields each
- **Optional Tracking** (2): early_season_flag, insufficient_data_reason
- **Metadata** (3): cache_version, created_at, processed_at

See: `schemas/bigquery/precompute/player_daily_cache.sql`

---

## Processing Logic

### 1. Data Extraction

```python
# Extract from 4 sources
player_games = query player_game_summary (season to date)
team_games = query team_offense_game_summary (last 10 games)
context = query upcoming_player_game_context (today)
shot_zones = query player_shot_zone_analysis (today)
```

### 2. Player Loop

```python
for each player in context:
    # Check minimum games
    if player_games < 5:
        skip player (insufficient data)
    
    # Check shot zones available
    if no shot_zone_analysis:
        skip player (missing dependency)
    
    # Calculate metrics
    last_5_avg = avg(last 5 games)
    last_10_avg = avg(last 10 games)
    season_avg = avg(all games)
    std_dev = stddev(last 10 games)
    
    # Get team context
    team_pace = avg(team last 10 games)
    team_off_rating = avg(team last 10 games)
    
    # Copy fatigue metrics (already calculated!)
    fatigue_metrics = context[player]
    
    # Copy shot zones (already calculated!)
    shot_zones = shot_zone_analysis[player]
    
    # Calculate assisted rate
    assisted_rate = sum(assisted_makes) / sum(fg_makes)
    
    # Build cache record with source tracking
    cache_record = {
        **metrics,
        **build_source_tracking_fields(),
        'early_season_flag': games < 10,
        'processed_at': now()
    }
```

### 3. Save to BigQuery

```python
# MERGE strategy (update or insert)
save_precompute()  # From base class
```

---

## Early Season Handling

### Detection
- **Early Season:** Player has < 10 games played
- **Absolute Minimum:** Must have 5+ games to write record

### Behavior
- **5-9 games:** Write cache record with available data
  - Set `early_season_flag = TRUE`
  - Set `insufficient_data_reason = "Only X games played, need 10 minimum"`
  - All metrics calculated from available games
  
- **< 5 games:** Skip player entirely
  - Add to `failed_entities` list
  - Reason: "Insufficient data"

### Example

```python
# Rookie with 7 games
points_avg_last_10 = avg(7 games)  # Not 10
points_std_last_10 = stddev(7 games)
early_season_flag = TRUE
insufficient_data_reason = "Only 7 games played, need 10 minimum"
```

---

## Usage

### Manual Execution

```bash
# Activate environment
source .venv/bin/activate
export GCP_PROJECT_ID="nba-props-platform"

# Run for specific date
python data_processors/precompute/player_daily_cache/player_daily_cache_processor.py \
  --analysis_date 2025-01-21
  
# With explicit season year
python data_processors/precompute/player_daily_cache/player_daily_cache_processor.py \
  --analysis_date 2025-01-21 \
  --season_year 2024
```

### Scheduled Execution (Production)

- **Schedule:** Nightly at 12:00 AM
- **Trigger:** After all Phase 4 processors complete
- **Duration:** 5-10 minutes for ~450 players
- **Priority:** Low (can skip if time-constrained)

### Cloud Run Job Configuration

```yaml
name: player-daily-cache-processor
schedule: "0 0 * * *"  # Daily at midnight
timeout: 900s  # 15 minutes
memory: 2Gi
cpu: 2
environment:
  - GCP_PROJECT_ID: nba-props-platform
command:
  - python
  - data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
  - --analysis_date
  - "{{date}}"
```

---

## Integration with Phase 5

### Morning Load (6 AM)

```python
# Phase 5 loads cache at startup
def load_daily_cache():
    """Load all player cache data into memory."""
    query = """
    SELECT * 
    FROM nba_precompute.player_daily_cache 
    WHERE cache_date = CURRENT_DATE()
    """
    df = bigquery_client.query(query).to_dataframe()
    
    # Convert to dictionary for fast lookup
    cache = df.set_index('player_lookup').to_dict('index')
    
    logger.info(f"Loaded daily cache for {len(cache)} players")
    return cache

# Called once at 6 AM
DAILY_CACHE = load_daily_cache()
```

### Real-Time Updates (Throughout Day)

```python
# Fast lookup from in-memory cache
def generate_realtime_prediction(player_lookup, new_prop_line):
    """Update prediction when line changes."""
    
    # Get cached data (instant!)
    player_cache = DAILY_CACHE[player_lookup]
    
    # Only recalculate line-dependent factors
    line_factor = calculate_line_factor(new_prop_line, player_cache)
    
    # Generate prediction using cached data + new line
    prediction = predict(
        base_stats=player_cache,
        line_factor=line_factor
    )
    
    return prediction

# No BigQuery queries needed! All data in memory.
```

---

## Monitoring

### Key Metrics

```sql
-- Cache completeness
SELECT 
  COUNT(DISTINCT player_lookup) as players_cached,
  AVG(source_player_game_completeness_pct) as avg_completeness,
  SUM(CASE WHEN early_season_flag THEN 1 ELSE 0 END) as early_season_count
FROM nba_precompute.player_daily_cache
WHERE cache_date = CURRENT_DATE();
```

### Alert Conditions

1. **Too Few Players:** < 400 players cached (expect ~450)
2. **Stale Sources:** Any source > 24 hours old
3. **Low Completeness:** Any source < 85% complete
4. **Processing Time:** > 15 minutes duration

### Validation Queries

See schema file for complete validation queries:
- `schemas/bigquery/precompute/player_daily_cache.sql`

---

## Testing

### Unit Tests

```bash
# Run unit tests
pytest tests/processors/precompute/player_daily_cache/test_player_daily_cache_processor.py
```

### Integration Tests

```bash
# Test with real data
python data_processors/precompute/player_daily_cache/player_daily_cache_processor.py \
  --analysis_date 2025-01-21
```

### Validation

```sql
-- Check output
SELECT * 
FROM nba_precompute.player_daily_cache 
WHERE cache_date = '2025-01-21'
LIMIT 10;

-- Verify completeness
SELECT 
  AVG(source_player_game_completeness_pct) as avg_pgs_completeness,
  AVG(source_team_offense_completeness_pct) as avg_tgs_completeness,
  AVG(source_upcoming_context_completeness_pct) as avg_ctx_completeness,
  AVG(source_shot_zone_completeness_pct) as avg_zone_completeness
FROM nba_precompute.player_daily_cache
WHERE cache_date = '2025-01-21';
```

---

## Troubleshooting

### Issue: No players cached

**Check:**
1. Is `upcoming_player_game_context` populated for today?
2. Is `player_shot_zone_analysis` populated for today?
3. Do players have 5+ games in `player_game_summary`?

### Issue: Low completeness

**Check:**
1. Which source has low completeness?
2. Is that source processor running successfully?
3. Check source processor logs for errors

### Issue: Players missing from cache

**Query:**
```sql
-- Find missing players
SELECT 
  upg.player_lookup,
  upg.player_full_name,
  COUNT(DISTINCT pgs.game_id) as games_played
FROM nba_analytics.upcoming_player_game_context upg
LEFT JOIN nba_precompute.player_daily_cache pdc
  ON upg.player_lookup = pdc.player_lookup
  AND upg.game_date = pdc.cache_date
LEFT JOIN nba_analytics.player_game_summary pgs
  ON upg.player_lookup = pgs.player_lookup
WHERE upg.game_date = CURRENT_DATE()
  AND pdc.player_lookup IS NULL
GROUP BY 1, 2;
```

---

## Files

```
data_processors/precompute/player_daily_cache/
├── __init__.py                          # Package initialization
├── player_daily_cache_processor.py      # Main processor (625 lines)
└── README.md                            # This file

schemas/bigquery/precompute/
└── player_daily_cache.sql               # BigQuery schema with views

docs/
├── player_daily_cache_data_mapping.md   # Data mapping document
└── Phase_4_Processor_Quick_Start.md     # Creation guide

tests/processors/precompute/player_daily_cache/
├── test_player_daily_cache_processor.py # Unit tests (25-50 tests)
└── test_integration.py                  # Integration tests (8+ tests)
```

---

## Success Criteria

✅ **Completeness:** 95%+ of scheduled players have cache records  
✅ **Freshness:** All source tables < 24 hours old  
✅ **Quality:** 90%+ of cache records have 100% completeness across all sources  
✅ **Timeliness:** Processor completes by 12:15 AM (15 minutes max)  
✅ **Accuracy:** Spot-check 10 random players shows calculations match manual verification  
✅ **Phase 5 Integration:** Cache loads successfully at 6 AM, lookups < 1ms  

---

## Next Steps

1. **Create Unit Tests** - See unit test writing guide
2. **Create Integration Tests** - See integration test writing guide
3. **Deploy to Cloud Run** - Schedule for nightly execution
4. **Integrate with Phase 5** - Modify Phase 5 to load cache at startup
5. **Monitor Performance** - Track cost savings and speed improvements

---

## References

- **Data Mapping:** `docs/player_daily_cache_data_mapping.md`
- **Schema:** `schemas/bigquery/precompute/player_daily_cache.sql`
- **Quick Start Guide:** `docs/Phase_4_Processor_Quick_Start.md`
- **Dependency Tracking:** `docs/Dependency_Tracking_v4_Design.md`
- **Base Class:** `data_processors/precompute/precompute_base.py`

---

## Document Version

- **Version:** 1.0
- **Created:** October 30, 2025
- **Last Updated:** October 30, 2025
- **Status:** Ready for testing and deployment
