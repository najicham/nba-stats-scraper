# /spot-check-gaps - System-Wide Gap Detection

Find ALL players with unexplained gaps in their game history. This is the most comprehensive audit tool for data quality issues.

**Related skills**: See `/spot-check-overview` for workflow and when to use each skill.

## When to Use

- Weekly data quality audit
- After backfills to verify completeness
- When investigating systemic data issues
- Before ML model retraining to ensure data integrity

## Severity Levels

| Severity | Gap Type | Action |
|----------|----------|--------|
| `ERROR` | ERROR_HAS_MINUTES | Fix immediately - player played but missing |
| `WARNING` | ERROR_NOT_IN_BOXSCORE | Investigate - missing from raw data |
| `INFO` | DNP_NO_INJURY | None - coach's decision |
| `OK` | INJURY_REPORT | None - injury explains absence |

## Usage

```
/spot-check-gaps [start_date] [end_date]
```

Examples:
- `/spot-check-gaps` - Check last 30 days (default)
- `/spot-check-gaps 2025-12-19` - From Dec 19 to today
- `/spot-check-gaps 2025-12-19 2026-01-15` - Specific date range

**Note**: Injury report data only available from Dec 19, 2025+. Earlier dates will show more "unexplained" gaps.

## What This Skill Does

### Step 1: Identify All Gaps

Find every case where a team played but a rostered player has no `player_game_summary` record:

```sql
-- Get all team games
WITH team_games AS (
    SELECT DISTINCT game_date, home_team_tricode as team
    FROM nba_raw.v_nbac_schedule_latest
    WHERE game_status = 3 AND game_date BETWEEN @start_date AND @end_date
    UNION ALL
    SELECT DISTINCT game_date, away_team_tricode as team
    FROM nba_raw.v_nbac_schedule_latest
    WHERE game_status = 3 AND game_date BETWEEN @start_date AND @end_date
),

-- Get player team stints
player_stints AS (
    SELECT player_lookup, team_abbr,
           MIN(game_date) as stint_start,
           MAX(game_date) as stint_end
    FROM nba_analytics.player_game_summary
    WHERE game_date >= DATE_SUB(@start_date, INTERVAL 30 DAY)
    GROUP BY player_lookup, team_abbr
),

-- Find gaps: team played during player's stint but no record
gaps AS (
    SELECT ps.player_lookup, tg.game_date, tg.team
    FROM player_stints ps
    JOIN team_games tg ON ps.team_abbr = tg.team
        AND tg.game_date BETWEEN ps.stint_start AND ps.stint_end
    LEFT JOIN nba_analytics.player_game_summary pg
        ON ps.player_lookup = pg.player_lookup AND tg.game_date = pg.game_date
    WHERE pg.game_date IS NULL
)
SELECT * FROM gaps
```

### Step 2: Classify Each Gap

For each gap, determine the cause:

```sql
SELECT
    g.*,
    ir.injury_status,
    ir.reason_category,
    CASE
        WHEN b.minutes IN ('00', '0') THEN 'DNP'
        WHEN b.minutes IS NOT NULL THEN 'HAS_MINUTES'
        ELSE NULL
    END as boxscore_status
FROM gaps g
LEFT JOIN nba_raw.nbac_injury_report ir
    ON g.player_lookup = ir.player_lookup AND g.game_date = ir.game_date
LEFT JOIN nba_raw.bdl_player_boxscores b
    ON g.player_lookup = b.player_lookup AND g.game_date = b.game_date
```

### Step 3: Generate Summary Report

```
=== SPOT CHECK GAPS REPORT ===
Period: 2025-12-19 to 2026-01-26

SUMMARY BY GAP TYPE:
| Type                  | Count | Players | Action Required |
|-----------------------|-------|---------|-----------------|
| INJURY_REPORT         |   826 |     217 | None - Expected |
| DNP_NO_INJURY         |   979 |     296 | None - Coach decision |
| ERROR_NOT_IN_BOXSCORE |    76 |      46 | Investigate |
| ERROR_HAS_MINUTES     |    20 |       7 | FIX REQUIRED |

ERROR_HAS_MINUTES DETAILS (Players who played but missing from analytics):
| Player          | Date       | Team | Minutes | Points |
|-----------------|------------|------|---------|--------|
| jimmybutler     | 2026-01-19 | GSW  | 21      | 17     |
| kasparasjakuionis | 2026-01-20 | MIA | 17      | 1      |
...

ERROR_NOT_IN_BOXSCORE DETAILS (Missing from raw data):
| Player          | Date       | Team | Possible Cause |
|-----------------|------------|------|----------------|
| [sample list]   |            |      | Trade window / Not on roster |
```

## Gap Types Explained

### INJURY_REPORT (OK)
Player has an injury report entry explaining absence.
- **Action**: None required
- **Example**: LeBron listed OUT with knee injury

### DNP_NO_INJURY (OK)
Player in boxscore with 0 minutes, no injury report.
- **Action**: None required (Coach's Decision)
- **Example**: End-of-bench player sat by coach

### ERROR_NOT_IN_BOXSCORE (Investigate)
Player not in raw boxscore data at all.
- **Possible causes**:
  - Trade window (player between teams)
  - Not on active roster yet
  - G-League assignment
  - Data collection issue
- **Action**: Check player movement, roster status

### ERROR_HAS_MINUTES (Fix Required)
**REAL BUG** - Player played actual minutes but missing from `player_game_summary`.
- **Possible causes**:
  - Player lookup mismatch
  - Processor skipped record
  - Recent trade not reflected
- **Action**: Investigate processor logs, may need manual fix

## Data Coverage Warning

**Injury report data only available from Dec 19, 2025.**

For dates before Dec 19:
- Many gaps will show as "unexplained"
- Use boxscore check as primary classifier
- Cannot distinguish injury from DNP-CD

## Step 6: Check Registry Mismatches

For ERROR_HAS_MINUTES cases, check if players are in the unresolved registry:

```sql
SELECT
    normalized_lookup,
    status,
    occurrences,
    last_seen_date
FROM nba_reference.unresolved_player_names
WHERE normalized_lookup IN (@missing_players)
  AND source_processor = 'player_game_summary'
ORDER BY occurrences DESC
```

**Interpretation**:
- `status = 'resolved'` + old `last_seen_date` → Need to reprocess historical dates
- `status = 'pending'` → Need to add alias to registry
- Not in table → New issue, add to unresolved tracking

## Implementation Notes

1. Run query for date range
2. Classify gaps using injury + boxscore data
3. Focus investigation on ERROR_HAS_MINUTES first (real bugs)
4. **Check registry for name mismatches** - most common root cause
5. ERROR_NOT_IN_BOXSCORE may be legitimate (trades, G-League)
6. DNP_NO_INJURY is normal bench player behavior

## Integration with Other Skills

| Skill | When to Use |
|-------|-------------|
| `/spot-check-gaps` | Weekly audit, find all issues |
| `/spot-check-player` | Deep dive on specific player |
| `/spot-check-date` | Investigate specific game day |
| `/spot-check-team` | Audit one team's roster |

## Cascade Impact Warning

**IMPORTANT**: Finding a gap is only step 1. If data was computed while the gap existed, downstream records are contaminated.

### When You Find Gaps:

1. **ERROR_HAS_MINUTES**: Player played but missing from analytics
   - This is a BUG - fix immediately
   - Run `/spot-check-cascade <player> <date>` to see downstream impact
   - After fixing, may need to reprocess downstream tables

2. **ERROR_NOT_IN_BOXSCORE**: Player missing entirely
   - May be trade window, G-League, or data issue
   - If backfilling, run `/spot-check-cascade` to plan remediation

### Remediation Workflow

```
1. Find gaps         → /spot-check-gaps
2. Analyze impact    → /spot-check-cascade <player> <date>
3. Backfill raw data → Run backfill scripts
4. Reprocess cascade → Run remediation commands from /spot-check-cascade --backfilled
5. Verify fix        → /validate-lineage
6. Track completion  → Update contamination_tracking table
```

### Recording Gaps for Tracking

For systematic tracking, record gaps to BigQuery:

```sql
INSERT INTO nba_orchestration.contamination_tracking
(gap_id, player_lookup, gap_date, discovered_at, discovered_by, remediation_status)
SELECT
    GENERATE_UUID(),
    player_lookup,
    gap_date,
    CURRENT_TIMESTAMP(),
    'spot-check-gaps',
    'pending'
FROM (
    -- Your gap detection results here
)
```

## Success Criteria

After running this check, you should know:
- [ ] Total gaps by type across the system
- [ ] List of ERROR_HAS_MINUTES cases needing fixes
- [ ] List of ERROR_NOT_IN_BOXSCORE cases to investigate
- [ ] Confidence that INJURY_REPORT and DNP_NO_INJURY are working correctly
- [ ] Cascade impact of each gap (via `/spot-check-cascade`)
- [ ] Remediation plan for critical gaps
