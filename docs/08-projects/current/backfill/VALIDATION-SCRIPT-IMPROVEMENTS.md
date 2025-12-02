# Validation Script Improvements Required

**Date:** 2025-12-01
**Current Script:** `bin/backfill/validate_and_plan.py`
**Priority:** HIGH - Must complete before production backfill

---

## Current Capabilities (What Works)

1. ✅ Checks data presence by counting distinct dates per table
2. ✅ Checks `processor_run_history` for run status
3. ✅ Distinguishes: never ran, ran but failed, ran with no data
4. ✅ Shows execution plan with copy-paste commands
5. ✅ Handles bootstrap period (but dates are wrong)
6. ✅ Good visual output with status indicators

---

## Critical Gaps

### 1. Run History Only Checks First Date (CRITICAL)

**Problem:**
```python
# Line 163, 252, 340
run_status = get_run_status(run_history, start_date, 'Phase 3', processor_name)
```
For date range Jan 15-28, it only checks Jan 15's run history. If Jan 15 ran but Jan 16-28 didn't, it would show as "ran successfully."

**Fix Required:**
- Check run history for ALL dates in range
- Report: X/Y dates have successful runs
- Flag any dates with failed or missing runs

---

### 2. No Quality Column Validation (CRITICAL)

**Problem:**
The script doesn't verify the new quality tracking system works:
- `quality_tier` - Is it populated?
- `quality_score` - Is it reasonable (0-100)?
- `is_production_ready` - Is it set correctly?
- `data_sources` - Is it tracking which sources were used?

**Fix Required:**
```sql
-- Example validation query
SELECT
  COUNT(*) as total_records,
  COUNTIF(quality_tier IS NOT NULL) as has_quality_tier,
  COUNTIF(quality_score IS NOT NULL) as has_quality_score,
  COUNTIF(is_production_ready IS NOT NULL) as has_production_ready,
  AVG(quality_score) as avg_quality_score,
  COUNTIF(quality_tier = 'gold') as gold_count,
  COUNTIF(quality_tier = 'silver') as silver_count,
  COUNTIF(quality_tier = 'bronze') as bronze_count
FROM nba_analytics.player_game_summary
WHERE game_date = '2021-10-19'
```

---

### 3. No Game Count Validation (HIGH)

**Problem:**
Only checks "does data exist for this date" not "does ALL expected data exist."

**Example:**
- Oct 19, 2021 has 2 games (BKN@MIL, GSW@LAL)
- player_game_summary should have ~67 player records
- team_defense_game_summary should have 4 records (2 games × 2 teams)
- Currently only checks: "is date count > 0"

**Fix Required:**
```sql
-- Compare expected vs actual
SELECT
  COUNT(DISTINCT game_id) as games_processed,
  COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE game_date = '2021-10-19'

-- Compare to Phase 2
SELECT COUNT(DISTINCT game_id) as expected_games
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2021-10-19'
```

---

### 4. Missing ml_feature_store (HIGH)

**Problem:**
Phase 4 validation (lines 311-316) doesn't include `ml_feature_store`:
```python
phase4_tables = {
    'team_defense_zone_analysis': 'analysis_date',
    'player_shot_zone_analysis': 'analysis_date',
    'player_composite_factors': 'game_date',
    'player_daily_cache': 'cache_date',
    # MISSING: 'ml_feature_store_v2': 'game_date'
}
```

`ml_feature_store_v2` is CRITICAL - it's what Phase 5 predictions consume.

**Fix Required:**
Add ml_feature_store_v2 to Phase 4 validation.

---

### 5. Bootstrap Dates Are Wrong (MEDIUM)

**Problem:**
```python
# Line 20-25
BOOTSTRAP_PERIODS = [
    (date(2021, 10, 15), date(2021, 10, 21)),  # WRONG - Oct 15 is preseason
    ...
]
```

Oct 19, 2021 is the regular season opener. Bootstrap should be Oct 19-25.

**Fix Required:**
```python
BOOTSTRAP_PERIODS = [
    (date(2021, 10, 19), date(2021, 10, 25)),  # 2021-22 (Days 0-6)
    (date(2022, 10, 18), date(2022, 10, 24)),  # 2022-23
    (date(2023, 10, 24), date(2023, 10, 30)),  # 2023-24
    (date(2024, 10, 22), date(2024, 10, 28)),  # 2024-25
]
```

Or better: derive dynamically from season dates.

---

### 6. Missing Important Phase 2 Sources (MEDIUM)

**Problem:**
Only checks 5 sources, missing:
- `nbac_schedule` - Required for game context
- `odds_api_game_lines` - Required for team context (spreads/totals)

**Fix Required:**
Add to phase2_sources list:
```python
('nbac_schedule', 'IMPORTANT', 'Game schedule'),
('odds_api_game_lines', 'IMPORTANT', 'Team spreads/totals'),
```

---

### 7. No Cross-Phase Validation (MEDIUM)

**Problem:**
Doesn't verify data flows correctly between phases:
- Phase 3 should have same game count as Phase 2
- Phase 4 should have same date count as Phase 3 (minus bootstrap)

**Fix Required:**
Add cross-phase comparison:
```
Phase 2 games: 2 games on 2021-10-19
Phase 3 games: 2 games on 2021-10-19 ✓ MATCHES
Phase 4 dates: 0 dates (bootstrap - expected) ✓
```

---

### 8. No Record Count Expectations (LOW)

**Problem:**
Doesn't know expected record counts. For Oct 19, 2021 with 2 games:
- player_game_summary: ~60-70 records (30-35 players × 2 games)
- team_defense_game_summary: 4 records (2 teams × 2 games)
- team_offense_game_summary: 4 records

Would be nice to validate record counts are reasonable.

---

## Proposed Enhanced Output

```
================================================================================
BACKFILL VALIDATION: 2021-10-19 (Bootstrap Day 0)
================================================================================

PHASE 2: RAW DATA
─────────────────────────────────────────────────────────────────────────────────
Source                              Dates   Games   Records   Status
─────────────────────────────────────────────────────────────────────────────────
nbac_gamebook_player_stats          1/1     2       67        ✓ Complete
nbac_team_boxscore                  1/1     2       8         ✓ Complete
bettingpros_player_points_props     1/1     -       1666      ✓ Complete
bigdataball_play_by_play            1/1     2       983       ✓ Complete
bdl_player_boxscores                1/1     2       51        ✓ Complete
nbac_schedule                       1/1     2       2         ✓ Complete
odds_api_game_lines                 0/1     0       0         ⚠ Missing (fallback OK)

→ Phase 2: ✓ Ready (2 games, 6/7 sources)

PHASE 3: ANALYTICS
─────────────────────────────────────────────────────────────────────────────────
Table                               Dates   Games   Records   Quality    Run Status
─────────────────────────────────────────────────────────────────────────────────
player_game_summary                 0/1     0/2     0         -          ○ Never ran
team_defense_game_summary           0/1     0/2     0         -          ○ Never ran
team_offense_game_summary           0/1     0/2     0         -          ○ Never ran
upcoming_player_game_context        0/1     -       0         -          ○ Never ran
upcoming_team_game_context          0/1     -       0         -          ○ Never ran

→ Phase 3: ○ Need backfill (0/5 processors ran)

PHASE 4: PRECOMPUTE (Bootstrap - Expected: 0 records)
─────────────────────────────────────────────────────────────────────────────────
Table                               Dates   Records   Quality    Run Status
─────────────────────────────────────────────────────────────────────────────────
team_defense_zone_analysis          0/0     0         -          ⊘ Bootstrap skip
player_shot_zone_analysis           0/0     0         -          ⊘ Bootstrap skip
player_composite_factors            0/0     0         -          ⊘ Bootstrap skip
player_daily_cache                  0/0     0         -          ⊘ Bootstrap skip
ml_feature_store_v2                 0/0     0         -          ⊘ Bootstrap skip

→ Phase 4: ⊘ Bootstrap period (Day 0) - Phase 4 correctly skips

QUALITY VALIDATION (Post-Backfill)
─────────────────────────────────────────────────────────────────────────────────
After running Phase 3, verify:
  □ All records have quality_tier populated
  □ All records have quality_score (0-100)
  □ is_production_ready set appropriately
  □ data_sources array populated

================================================================================
```

---

## Implementation Options

### Option A: Quick Fixes (1-2 hours)
Fix the most critical issues:
1. Add ml_feature_store_v2 to Phase 4
2. Fix bootstrap dates
3. Add quality column checks (basic)

### Option B: Comprehensive Rewrite (3-4 hours)
Full rewrite with:
1. All gaps addressed
2. Game-level validation
3. Quality column validation
4. Cross-phase validation
5. Better output format

### Option C: New Chat Deep Dive
Create prompt for new chat to:
1. Study the current script thoroughly
2. Study processor_run_history schema
3. Design comprehensive validation
4. Implement and test

---

## Files to Study for Improvement

```
bin/backfill/validate_and_plan.py           # Current script
schemas/bigquery/nba_reference/processor_run_history.sql  # Run history schema
schemas/bigquery/nba_analytics/*.sql        # Phase 3 table schemas
schemas/bigquery/nba_precompute/*.sql       # Phase 4 table schemas
shared/processors/patterns/quality_columns.py  # Quality column definitions
docs/05-development/guides/quality-tracking-system.md  # Quality system docs
```

---

## Recommendation

**Option B (Comprehensive Rewrite)** is recommended because:
1. We're about to backfill 4 seasons of data
2. Need confidence the validation is accurate
3. Quality validation is critical for the new system
4. One-time investment saves future debugging

---

## Additional Requirement: Player-Level Completeness

### The Problem

Current validation only checks **date-level** completeness:
- "Does Oct 19, 2021 have data?" ✓

But we also need **player-level** completeness:
- "Do ALL players with games on Oct 19 have predictions?"
- "Is any player missing from processing?"
- "Did any player error out?"

### Why This Matters

For predictions to be complete:
1. Every player with a game should flow through Phase 3 → Phase 4 → Phase 5
2. If a player errors in Phase 3, they won't have Phase 4 features
3. If a player is missing from Phase 4, they won't have predictions
4. We need to catch these gaps BEFORE they become silent failures

### Expected vs Actual Player Counts

**Source of Truth for Expected Players:**
```sql
-- Option A: Players from gamebook (who actually played)
SELECT COUNT(DISTINCT player_lookup) as expected_players
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2021-10-19'
  AND player_status = 'active'

-- Option B: Players from props (who have betting lines)
SELECT COUNT(DISTINCT player_lookup) as expected_players
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = '2021-10-19'
  AND is_active = TRUE

-- Option C: Players from rosters × games (theoretical max)
SELECT COUNT(DISTINCT player_lookup) as expected_players
FROM nba_raw.nbac_schedule s
CROSS JOIN nba_raw.team_rosters r
WHERE s.game_date = '2021-10-19'
  AND r.team_abbr IN (s.home_team_abbr, s.away_team_abbr)
```

**Validation Queries Needed:**
```sql
-- Phase 3: player_game_summary
SELECT
  'player_game_summary' as phase,
  COUNT(DISTINCT player_lookup) as processed_players
FROM nba_analytics.player_game_summary
WHERE game_date = '2021-10-19'

-- Phase 3: upcoming_player_game_context
SELECT
  'upcoming_player_game_context' as phase,
  COUNT(DISTINCT player_lookup) as processed_players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2021-10-19'

-- Phase 4: ml_feature_store_v2
SELECT
  'ml_feature_store_v2' as phase,
  COUNT(DISTINCT player_lookup) as processed_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2021-10-19'

-- Phase 5: predictions
SELECT
  'predictions' as phase,
  COUNT(DISTINCT player_lookup) as processed_players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2021-10-19'
```

### Player Flow Validation

Track player counts through the pipeline:
```
2021-10-19 Player Flow:
─────────────────────────────────────────────────────────────────
Phase 2 (gamebook):           67 players (SOURCE OF TRUTH)
Phase 3 (player_game_summary): 67 players ✓ 100%
Phase 3 (upcoming_context):    22 players (only players with props)
Phase 4 (ml_feature_store):     0 players (bootstrap - expected)
Phase 5 (predictions):          0 players (bootstrap - expected)

Missing Players: None ✓
```

### Finding Missing Players

```sql
-- Find players in Phase 2 but missing from Phase 3
SELECT DISTINCT p2.player_lookup
FROM nba_raw.nbac_gamebook_player_stats p2
LEFT JOIN nba_analytics.player_game_summary p3
  ON p2.player_lookup = p3.player_lookup
  AND p2.game_date = p3.game_date
WHERE p2.game_date = '2021-10-19'
  AND p2.player_status = 'active'
  AND p3.player_lookup IS NULL

-- Find players in Phase 3 but missing from Phase 4 (non-bootstrap)
SELECT DISTINCT p3.player_lookup
FROM nba_analytics.upcoming_player_game_context p3
LEFT JOIN nba_predictions.ml_feature_store_v2 p4
  ON p3.player_lookup = p4.player_lookup
  AND p3.game_date = p4.game_date
WHERE p3.game_date = '2021-10-26'  -- First non-bootstrap date
  AND p4.player_lookup IS NULL
```

### Proposed Enhanced Output

```
================================================================================
PLAYER-LEVEL COMPLETENESS: 2021-10-19
================================================================================

Expected Players (from gamebook): 67 active players across 2 games

Phase                           Players   Expected   Status
─────────────────────────────────────────────────────────────────────────────────
Phase 2: nbac_gamebook          67        67         ✓ Complete (source)
Phase 3: player_game_summary    67        67         ✓ Complete
Phase 3: upcoming_player_ctx    22        22*        ✓ Complete (*props only)
Phase 4: ml_feature_store       0         0          ⊘ Bootstrap (expected)
Phase 5: predictions            0         0          ⊘ Bootstrap (expected)

Missing Players: None

* Note: upcoming_player_game_context only includes players with prop lines
  (22 players had props on this date)
```

### Error Tracking

Also need to track players who ERRORED during processing:
```sql
-- Check processor_run_history for player-level errors
SELECT
  game_date,
  processor_name,
  error_details,
  COUNT(*) as error_count
FROM nba_reference.processor_run_history
WHERE status = 'failed'
  AND game_date = '2021-10-19'
GROUP BY game_date, processor_name, error_details
```

### Summary: What Validation Should Check

| Level | Current | Needed |
|-------|---------|--------|
| Date exists | ✓ | ✓ |
| Game count matches | ✗ | ✓ |
| Player count matches | ✗ | ✓ |
| Record count reasonable | ✗ | ✓ |
| Quality columns populated | ✗ | ✓ |
| No missing players | ✗ | ✓ |
| No errored players | ✗ | ✓ |

---

## Additional Requirement: Reference Data Validation

### 1. Player Registry Must Be Populated

**What It Is:**
- `nba_reference.nba_players_registry` - Master table of all known players
- Contains: player_lookup, universal_player_id, team_abbr, season, games_played
- Populated by `GamebookRegistryProcessor` from gamebook data

**How It Gets Populated:**
```
Phase 2: nbac_gamebook_player_stats scraped
    ↓
Reference Phase: GamebookRegistryProcessor runs
    ↓
nba_reference.nba_players_registry updated
```

**File:** `data_processors/reference/player_reference/gamebook_registry_processor.py`

**Why It Matters:**
- Later phases use `RegistryReader` to get `universal_player_id`
- If a player isn't in registry, they can't be processed correctly
- For backfill: registry needs to be built from historical gamebook data first

**Validation Required:**
```sql
-- Check registry has players for this date
SELECT
  COUNT(DISTINCT player_lookup) as registry_players,
  COUNT(DISTINCT universal_player_id) as with_universal_id
FROM nba_reference.nba_players_registry
WHERE first_game_date <= '2021-10-19'
  AND last_game_date >= '2021-10-19'

-- Compare to gamebook
SELECT COUNT(DISTINCT player_lookup) as gamebook_players
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2021-10-19'
  AND player_status = 'active'

-- Find players in gamebook but missing from registry
SELECT DISTINCT g.player_lookup, g.player_name
FROM nba_raw.nbac_gamebook_player_stats g
LEFT JOIN nba_reference.nba_players_registry r
  ON g.player_lookup = r.player_lookup
WHERE g.game_date = '2021-10-19'
  AND g.player_status = 'active'
  AND r.player_lookup IS NULL
```

---

### 2. Rosters - Historical vs Live

**For Historical Backfill (Past Data):**
- Boxscores ARE the source of truth for who played
- `nbac_gamebook_player_stats` tells us exactly who was on the roster that day
- No separate roster validation needed - gamebook IS the roster

**For Live/Future Data:**
- `nba_reference.team_rosters_current` needs to be fresh
- Updated each morning before predictions
- File: `data_processors/reference/player_reference/roster_registry_processor.py`

**Validation for Historical:**
```sql
-- For historical dates, gamebook IS the roster
-- Just verify gamebook has reasonable player counts per team
SELECT
  team_abbr,
  COUNT(DISTINCT player_lookup) as players_on_roster
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2021-10-19'
  AND player_status = 'active'
GROUP BY team_abbr
HAVING COUNT(DISTINCT player_lookup) < 8  -- Flag if too few players
```

**Validation for Live:**
```sql
-- Check roster freshness
SELECT
  team_abbr,
  most_recent_game,
  CURRENT_DATE() - most_recent_game as days_stale
FROM nba_reference.team_rosters_current
WHERE days_stale > 7  -- Flag stale rosters
```

---

### 3. Schedule Freshness

**What It Is:**
- `nba_raw.nbac_schedule` - Game schedule from NBA.com
- Contains: game_id, game_date, home_team, away_team, game_status
- Processed by `NbacScheduleProcessor`

**For Historical Backfill:**
- Schedule should be complete for past seasons
- Verify schedule exists for the date range

**For Live/Future Data:**
- Schedule needs to be scraped fresh each day
- New games, postponements, etc. need to be captured

**Validation Required:**
```sql
-- Check schedule exists for date
SELECT
  game_date,
  COUNT(*) as games_scheduled,
  COUNT(CASE WHEN game_status = 'Final' THEN 1 END) as games_final
FROM nba_raw.nbac_schedule
WHERE game_date = '2021-10-19'
GROUP BY game_date

-- Compare schedule to actual games played
SELECT
  'schedule' as source,
  COUNT(DISTINCT game_id) as games
FROM nba_raw.nbac_schedule
WHERE game_date = '2021-10-19'

UNION ALL

SELECT
  'gamebook' as source,
  COUNT(DISTINCT game_id) as games
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2021-10-19'
```

**For Live Data - Freshness Check:**
```sql
-- Check when schedule was last updated
SELECT
  MAX(processed_at) as last_schedule_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_ago
FROM nba_raw.nbac_schedule
WHERE game_date = CURRENT_DATE()
```

---

### 4. Reference Phase Processors

**Processors That Must Run:**
| Processor | Table Updated | When to Run |
|-----------|---------------|-------------|
| `GamebookRegistryProcessor` | `nba_players_registry` | After gamebook backfill |
| `RosterRegistryProcessor` | `team_rosters_current` | Daily for live data |
| `NbacScheduleProcessor` | `nbac_schedule` | Daily for live data |

**Backfill Order:**
```
1. Scraper backfill (Phase 1 → Phase 2)
2. Registry backfill (Reference Phase)  ← IMPORTANT: Before Phase 3!
3. Phase 3 analytics backfill
4. Phase 4 precompute backfill
```

**Validation - Did Reference Phase Run?**
```sql
-- Check registry processor ran
SELECT
  processor_name,
  data_date,
  status,
  rows_processed
FROM nba_reference.processor_run_history
WHERE processor_name LIKE '%Registry%'
  AND data_date = '2021-10-19'
ORDER BY created_at DESC
```

---

### Proposed Enhanced Output - Reference Data Section

```
================================================================================
REFERENCE DATA VALIDATION: 2021-10-19
================================================================================

Schedule:
  Games scheduled:        2
  Games in gamebook:      2         ✓ Matches
  Schedule freshness:     Historical (OK)

Player Registry:
  Players in gamebook:    67
  Players in registry:    67        ✓ All registered
  With universal_id:      67        ✓ All have IDs
  Missing from registry:  0         ✓ None missing

Registry Processor:
  Last run:              2024-11-15 (historical backfill)
  Status:                ✓ Complete

→ Reference Data: ✓ Ready for Phase 3 processing
```

---

### Summary: Complete Validation Checklist

| Category | Check | Current | Needed |
|----------|-------|---------|--------|
| **Phase 2** | Date exists | ✓ | ✓ |
| **Phase 2** | Game count | ✗ | ✓ |
| **Reference** | Schedule exists | ✗ | ✓ |
| **Reference** | Registry populated | ✗ | ✓ |
| **Reference** | All players have universal_id | ✗ | ✓ |
| **Phase 3** | Date exists | ✓ | ✓ |
| **Phase 3** | Player count matches | ✗ | ✓ |
| **Phase 3** | Quality columns populated | ✗ | ✓ |
| **Phase 4** | Date exists | ✓ | ✓ |
| **Phase 4** | ml_feature_store included | ✗ | ✓ |
| **Cross-Phase** | No missing players | ✗ | ✓ |
| **Cross-Phase** | No errored players | ✗ | ✓ |

---

*Ready for implementation or new chat handoff.*
