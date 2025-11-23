# Data Completeness Checking Strategy

**Date:** 2025-11-22
**Purpose:** Ensure Phase 4 processors only run when they have ALL required historical data
**User Requirement:** "I want the quality of data to be high and that requires having the proper backfilled data present"

---

## The Real Problem

**Not about**: Detecting if data *changed*
**About**: Verifying data *exists* and is *complete*

### Example Scenario

**Processor**: team_defense_zone_analysis for Nov 22
**Requirement**: Last 15 games for LAL
**Question**: "Do I have all 15 games I need?"

**Current approach**:
```python
games_count = len(games_for_LAL)  # Count rows
if games_count < 15:
    skip_team()
```

**Problem**: Doesn't know if 14 games is correct (only played 14) or incorrect (played 15 but missing 1)

---

## Infrastructure You Have

### 1. Game Schedule (`nba_raw.nbac_schedule`)
```sql
SELECT game_date, home_team_tricode, away_team_tricode, game_status
FROM `nba_raw.nbac_schedule`
WHERE game_date BETWEEN '2024-11-01' AND '2024-11-22'
  AND (home_team_tricode = 'LAL' OR away_team_tricode = 'LAL')
  AND game_status = 3  -- Final (completed games only)
```

**Tells you**: Which games LAL SHOULD have played

### 2. Upstream Data (`nba_analytics.team_defense_game_summary`)
```sql
SELECT game_date, defending_team_abbr
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date BETWEEN '2024-11-01' AND '2024-11-22'
  AND defending_team_abbr = 'LAL'
```

**Tells you**: Which games we ACTUALLY have data for

### 3. Comparison
```sql
-- Games we SHOULD have (from schedule)
expected_games = 17

-- Games we HAVE (from upstream)
actual_games = 15

-- Missing data!
missing_games = 2
```

---

## Three Approaches

### Approach A: Query Schedule Per Entity (Accurate, Slower)

**How it works**:
```python
def verify_data_complete(entity_id, analysis_date) -> tuple[bool, str]:
    """Check if entity has all required historical games."""

    # 1. Query schedule: What games SHOULD exist?
    expected_games = query_schedule(entity_id, analysis_date, lookback=15)
    expected_count = len(expected_games)

    # 2. Query upstream: What games DO exist?
    actual_games = query_upstream(entity_id, analysis_date, lookback=15)
    actual_count = len(actual_games)

    # 3. Compare
    if actual_count < expected_count:
        missing = expected_games - actual_games  # Set difference
        return False, f"Missing {len(missing)} games: {missing}"

    return True, "Complete"
```

**Pros**:
- ✅ Accurate - knows exactly which games missing
- ✅ Works for backfill
- ✅ Can identify specific missing dates

**Cons**:
- ⚠️ 1 extra query per entity (30 teams × 1 = 30 queries)
- ⚠️ Slower processing

**Cost**: ~$0.001 per run

---

### Approach B: Precompute Completeness Table (Fast, Complex)

**How it works**:

**Step 1**: Separate process runs hourly, marks completeness:
```sql
-- Table: nba_orchestration.data_completeness
CREATE TABLE data_completeness (
    dataset STRING,           -- 'team_defense_game_summary'
    entity_id STRING,         -- 'LAL'
    check_date DATE,          -- '2024-11-22'
    lookback_window INT64,    -- 15
    expected_count INT64,     -- 17
    actual_count INT64,       -- 15
    missing_count INT64,      -- 2
    missing_dates ARRAY<DATE>,-- ['2024-11-05', '2024-11-12']
    is_complete BOOLEAN,      -- FALSE
    checked_at TIMESTAMP      -- '2024-11-22T10:00:00Z'
)
PARTITION BY check_date
CLUSTER BY dataset, entity_id;
```

**Step 2**: Processor queries completeness table:
```python
def verify_data_complete(entity_id, analysis_date) -> tuple[bool, str]:
    """Check precomputed completeness."""
    query = """
    SELECT is_complete, missing_count, missing_dates
    FROM `nba_orchestration.data_completeness`
    WHERE dataset = 'team_defense_game_summary'
      AND entity_id = '{entity_id}'
      AND check_date = '{analysis_date}'
      AND lookback_window = 15
    """

    result = run_query(query)
    if result['is_complete']:
        return True, "Complete"
    else:
        return False, f"Missing {result['missing_count']} games"
```

**Pros**:
- ✅ Fast - single query per processor run
- ✅ Centralized completeness checking
- ✅ Can be monitored/alerted on
- ✅ Reusable across all processors

**Cons**:
- ❌ Requires new table + maintenance process
- ❌ More infrastructure
- ❌ Completeness check might be stale (hourly updates)

**Cost**: ~$0.10/day for completeness checking job

---

### Approach C: Smart Count Comparison (Simple, Good Enough?)

**How it works**:
```python
def verify_data_complete(entity_id, analysis_date, min_games=15) -> tuple[bool, str]:
    """Check if we have EXACTLY the games we expect."""

    # Query schedule: How many games SHOULD entity have?
    schedule_query = """
    SELECT COUNT(*) as expected_games
    FROM `nba_raw.nbac_schedule`
    WHERE game_date <= '{analysis_date}'
      AND game_date >= '{season_start}'
      AND (home_team_tricode = '{entity_id}' OR away_team_tricode = '{entity_id}')
      AND game_status = 3  -- Final only
    """
    expected = run_query(schedule_query)['expected_games']

    # Query upstream: How many games DO we have?
    upstream_query = """
    SELECT COUNT(*) as actual_games
    FROM `nba_analytics.team_defense_game_summary`
    WHERE game_date <= '{analysis_date}'
      AND defending_team_abbr = '{entity_id}'
    """
    actual = run_query(upstream_query)['actual_games']

    # Compare
    if actual < expected:
        return False, f"Have {actual}/{expected} games (missing {expected - actual})"

    if actual < min_games:
        return False, f"Have {actual} games, need {min_games} minimum"

    return True, f"Complete ({actual} games)"
```

**Pros**:
- ✅ Simple - just count comparison
- ✅ Knows what to expect via schedule
- ✅ No new infrastructure
- ✅ Works for backfill

**Cons**:
- ⚠️ Doesn't identify WHICH games missing
- ⚠️ 2 queries per entity (schedule + upstream)

**Cost**: ~$0.002 per run

---

## Recommendation: Start with Approach C

**Why**:
1. **Simple** - no new tables, just smart queries
2. **Accurate enough** - knows if data complete
3. **Works for backfill** - checks against schedule
4. **Low cost** - ~$0.002 per run
5. **Can upgrade later** - If need more detail, add Approach B

**Implementation**:
```python
# Add to each Phase 4 processor

def _check_data_completeness_for_entity(
    self,
    entity_id: str,
    entity_field: str,  # 'home_team_tricode' or 'away_team_tricode'
    analysis_date: date,
    min_games: int
) -> dict:
    """
    Verify entity has complete historical data.

    Returns:
        {
            'is_complete': bool,
            'expected_games': int,
            'actual_games': int,
            'missing_count': int,
            'message': str
        }
    """
    # 1. Query schedule: How many games should exist?
    schedule_query = f"""
    SELECT COUNT(DISTINCT game_date) as expected_games
    FROM `{self.project_id}.nba_raw.nbac_schedule`
    WHERE game_date <= DATE('{analysis_date}')
      AND game_date >= DATE('{self.season_start_date}')
      AND (home_team_tricode = '{entity_id}' OR away_team_tricode = '{entity_id}')
      AND game_status = 3  -- Final games only
    """

    schedule_result = self.bq_client.query(schedule_query).to_dataframe()
    expected_games = int(schedule_result['expected_games'].iloc[0]) if not schedule_result.empty else 0

    # 2. Query upstream: How many games do we have?
    upstream_query = f"""
    SELECT COUNT(DISTINCT game_date) as actual_games
    FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
    WHERE game_date <= DATE('{analysis_date}')
      AND game_date >= DATE('{self.season_start_date}')
      AND defending_team_abbr = '{entity_id}'
    """

    upstream_result = self.bq_client.query(upstream_query).to_dataframe()
    actual_games = int(upstream_result['actual_games'].iloc[0]) if not upstream_result.empty else 0

    # 3. Determine completeness
    missing_count = expected_games - actual_games

    if actual_games < expected_games:
        is_complete = False
        message = f"Missing {missing_count} games ({actual_games}/{expected_games} present)"
    elif actual_games < min_games:
        is_complete = False
        message = f"Only {actual_games} games, need {min_games} minimum"
    else:
        is_complete = True
        message = f"Complete ({actual_games} games)"

    return {
        'is_complete': is_complete,
        'expected_games': expected_games,
        'actual_games': actual_games,
        'missing_count': missing_count,
        'message': message
    }
```

**Usage in processor**:
```python
def calculate_precompute(self) -> None:
    """Calculate team defense zone metrics."""

    for team_abbr in all_teams:
        # Check data completeness
        completeness = self._check_data_completeness_for_entity(
            entity_id=team_abbr,
            entity_field='home_team_tricode',  # or 'away_team_tricode'
            analysis_date=self.opts['analysis_date'],
            min_games=self.min_games_required  # 15
        )

        if not completeness['is_complete']:
            logger.warning(
                f"{team_abbr}: {completeness['message']} - skipping"
            )
            self.failed_entities.append({
                'entity_id': team_abbr,
                'reason': completeness['message'],
                'category': 'INCOMPLETE_DATA',
                'can_retry': True
            })
            continue

        # Process team (we know we have all required data)
        logger.info(f"{team_abbr}: {completeness['message']} - processing")
        # ... rest of processing
```

---

## For Backfill Scenario

**Nov 22 processing (need L15 games)**:

### Without Completeness Check (Current)
```
LAL: Found 14 games
Decision: Skip (need 15)
Problem: Don't know if 14 is correct or data is missing
```

### With Completeness Check (Proposed)
```
LAL: Schedule shows 17 games should exist
LAL: Upstream has 14 games
LAL: Missing 3 games (incomplete)
Decision: Skip with clear reason: "Missing 3 games (14/17 present)"
```

**Benefits**:
- ✅ Know WHY skipping (missing data vs early season)
- ✅ Can track which entities need backfill
- ✅ Clear data quality signal

---

## Implementation Plan

### Phase 1: Add to team_defense_zone_analysis (2 hours)

1. Add `_check_data_completeness_for_entity()` method
2. Call before processing each team
3. Log completeness status
4. Skip if incomplete

### Phase 2: Add to player processors (3 hours)

Same pattern but:
- Need to map player_lookup to teams (which teams did player play for?)
- Query schedule for player's teams
- More complex but same concept

### Phase 3: Monitor completeness (ongoing)

Add queries:
```sql
-- Which entities have incomplete data today?
SELECT
    entity_id,
    expected_games,
    actual_games,
    missing_count,
    message
FROM failed_entities
WHERE failure_date = CURRENT_DATE()
  AND category = 'INCOMPLETE_DATA'
ORDER BY missing_count DESC;
```

---

## Alternative: Simpler "Good Enough" Approach

**If schedule checking is too complex**, just enhance current checks:

```python
def verify_sufficient_games(entity_id, games_found, min_required) -> tuple[bool, str]:
    """Check if we have enough games, with better messaging."""

    if games_found < min_required:
        # Check if early season
        days_since_season_start = (analysis_date - season_start).days

        if days_since_season_start < 14:
            return False, f"Early season (Day {days_since_season_start}): Only {games_found} games"
        else:
            # Mid-season but insufficient - likely missing data
            return False, f"Insufficient data: {games_found} games (need {min_required}, possible data gap)"

    return True, f"Sufficient ({games_found} games)"
```

**Pros**:
- ✅ Very simple - no schedule queries
- ✅ Fast
- ✅ Differentiates early season vs data gaps

**Cons**:
- ❌ Doesn't know EXACTLY how many games should exist
- ❌ Can't identify specific missing dates

---

## Your Decision

**Option 1: Schedule-Based Completeness (Recommended)** ⭐
- Checks against schedule to know exactly what's missing
- Implementation: 5 hours across all processors
- Cost: ~$0.06/month
- Accuracy: High

**Option 2: Precomputed Completeness Table**
- Separate process marks completeness
- Implementation: 8 hours (table + job + processor updates)
- Cost: ~$3/month
- Accuracy: High
- Complexity: High

**Option 3: Enhanced Count Check (Simple)**
- Just better messaging on current approach
- Implementation: 2 hours
- Cost: $0
- Accuracy: Medium

---

## My Recommendation

**Start with Option 1 (Schedule-Based)** for these reasons:

1. **Your requirement**: "ensure all underlying data is present" - this does that
2. **Backfill-ready**: Works perfectly for historical backfill
3. **No new infrastructure**: Uses existing schedule table
4. **Clear signals**: Know exactly what's missing
5. **Upgrade path**: Can add Option 2 later if needed

**Next step**: Implement for team_defense_zone_analysis first, test with one team, verify logic works.

**Questions for you**:
1. Does checking against schedule sound right?
2. Should we identify specific missing dates or just counts?
3. Want to see code for one processor before implementing all?
