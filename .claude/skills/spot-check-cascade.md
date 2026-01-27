# /spot-check-cascade - Cascade Impact Analysis

Analyze the downstream impact of a data gap. When raw data is missing or backfilled late, this skill calculates what downstream records are contaminated and need reprocessing.

**Related skills**: See `/spot-check-overview` for workflow and when to use each skill.

## When to Use

- After finding a gap with `/spot-check-player` or `/spot-check-gaps`
- Before backfilling data (to understand remediation scope)
- After backfilling data (to generate reprocessing commands)
- When investigating data quality issues in ML features or predictions

## Usage

```
/spot-check-cascade <player_lookup> <gap_date> [--backfilled]
```

Examples:
- `/spot-check-cascade lebron_james 2026-01-15` - Analyze impact of missing Jan 15 data
- `/spot-check-cascade traeyoung 2025-11-13 --backfilled` - Generate remediation after backfill

## The Cascade Problem

When raw data is missing and computed later:

```
Timeline:
─────────────────────────────────────────────────────────────────────
Jan 15: Game played, data MISSING (scraper failed)
Jan 16: L5 rolling avg computed WITHOUT Jan 15 → CONTAMINATED
Jan 17: L5 rolling avg computed WITHOUT Jan 15 → CONTAMINATED
...
Jan 25: Jan 15 data backfilled → Raw data now correct
        BUT Jan 16-24 rolling averages still WRONG
        AND ML features using those averages → WRONG
        AND predictions using those features → WRONG
─────────────────────────────────────────────────────────────────────
```

**The backfill fixed the source but not the downstream cascade.**

## What This Skill Does

### Step 1: Identify the Gap

Confirm the gap exists and when data was (or will be) backfilled:

```sql
SELECT
    game_date,
    player_lookup,
    -- When was the data actually loaded?
    MIN(loaded_at) as first_loaded,
    -- How late was it?
    TIMESTAMP_DIFF(MIN(loaded_at), TIMESTAMP(game_date), HOUR) as hours_delayed
FROM nba_raw.bdl_player_boxscores
WHERE player_lookup = @player_lookup
  AND game_date = @gap_date
GROUP BY game_date, player_lookup
```

### Step 2: Calculate Contamination Windows

Find all dates whose rolling averages could be affected:

```sql
-- Find the next N games this player played after the gap
WITH player_games_after_gap AS (
    SELECT
        game_date,
        ROW_NUMBER() OVER (ORDER BY game_date) as games_since_gap
    FROM nba_analytics.player_game_summary
    WHERE player_lookup = @player_lookup
      AND game_date > @gap_date
    ORDER BY game_date
)
SELECT
    5 as window_size,
    MIN(game_date) as contamination_start,
    MAX(CASE WHEN games_since_gap <= 5 THEN game_date END) as contamination_end,
    COUNT(CASE WHEN games_since_gap <= 5 THEN 1 END) as affected_records
FROM player_games_after_gap
WHERE games_since_gap <= 5

UNION ALL

SELECT 10, MIN(game_date), MAX(CASE WHEN games_since_gap <= 10 THEN game_date END), COUNT(CASE WHEN games_since_gap <= 10 THEN 1 END)
FROM player_games_after_gap WHERE games_since_gap <= 10

UNION ALL

SELECT 15, MIN(game_date), MAX(CASE WHEN games_since_gap <= 15 THEN game_date END), COUNT(CASE WHEN games_since_gap <= 15 THEN 1 END)
FROM player_games_after_gap WHERE games_since_gap <= 15

UNION ALL

SELECT 20, MIN(game_date), MAX(CASE WHEN games_since_gap <= 20 THEN game_date END), COUNT(CASE WHEN games_since_gap <= 20 THEN 1 END)
FROM player_games_after_gap WHERE games_since_gap <= 20
```

### Step 3: Identify Affected Tables

Map the cascade through the dependency chain:

```
Dependency Chain:
─────────────────
nba_raw.bdl_player_boxscores (SOURCE)
    ↓
nba_analytics.player_game_summary (DIRECT - just gap date)
    ↓
nba_precompute.player_composite_factors (CASCADE - L5/L10/L15/L20 windows)
    ↓
nba_predictions.ml_feature_store_v2 (CASCADE - same window)
    ↓
nba_predictions.player_prop_predictions (CASCADE - predictions made during window)
```

### Step 4: Generate Impact Report

```
=== CASCADE IMPACT ANALYSIS ===
Player: LeBron James (lebron_james)
Gap Date: 2026-01-15
Gap Status: Data backfilled on 2026-01-25 (10 days late)

CONTAMINATION WINDOWS:
| Window | Start      | End        | Affected Records |
|--------|------------|------------|------------------|
| L5     | 2026-01-16 | 2026-01-22 | 5                |
| L10    | 2026-01-16 | 2026-01-26 | 10               |
| L15    | 2026-01-16 | 2026-02-01 | 15               |
| L20    | 2026-01-16 | 2026-02-08 | 20               |

AFFECTED TABLES:
| Table                      | Records | Date Range           |
|----------------------------|---------|----------------------|
| player_game_summary        | 1       | 2026-01-15           |
| player_composite_factors   | 20      | 2026-01-16 to 02-08  |
| ml_feature_store_v2        | 20      | 2026-01-16 to 02-08  |
| player_prop_predictions    | 100     | 2026-01-16 to 02-08  |

CONTAMINATED PREDICTIONS:
- 100 predictions were made using incorrect rolling averages
- These predictions CANNOT be un-made (already graded)
- Impact: Grading accuracy may be affected

REMEDIATION REQUIRED:
1. ✅ Raw data: Already backfilled
2. ⏳ player_game_summary: Needs reprocessing
3. ⏳ player_composite_factors: Needs reprocessing
4. ⏳ ml_feature_store_v2: Needs reprocessing
5. ℹ️ predictions: Cannot fix (historical)
```

### Step 5: Generate Remediation Commands

If `--backfilled` flag is set, generate reprocessing commands:

```bash
# 1. Reprocess player_game_summary for gap date
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
    --start-date 2026-01-15 \
    --end-date 2026-01-15 \
    --player-filter lebron_james

# 2. Reprocess player_composite_factors for contamination window
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_backfill.py \
    --start-date 2026-01-16 \
    --end-date 2026-02-08 \
    --player-filter lebron_james

# 3. Reprocess ml_feature_store for contamination window
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_backfill.py \
    --start-date 2026-01-16 \
    --end-date 2026-02-08 \
    --player-filter lebron_james

# 4. Mark remediation complete
# Update contamination_tracking table with remediation status
```

## Tracking Contamination

### Three-Table Architecture

We use three tables to track the full lifecycle:

```
┌─────────────────────────────────────────────────────────────────────┐
│  backfill_events (Immutable event log)                             │
│  - What was backfilled, when, how late                             │
│  - Computed contamination windows                                   │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  contamination_records (Downstream impact tracking)                │
│  - Links backfill to affected downstream records                   │
│  - Tracks quality scores before/after                              │
│  - Remediation status per record                                   │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  remediation_log (Audit trail of fixes)                            │
│  - Detailed log of each remediation run                            │
│  - Results: records processed, quality improvement                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Schema**: `migrations/backfill_tracking_schema.sql`

### Recording a Backfill Event

When data is backfilled, record the event:

```sql
INSERT INTO nba_orchestration.backfill_events
(backfill_id, table_name, entity_type, entity_id, game_date,
 hours_delayed, backfill_source, l5_contamination_end, l10_contamination_end,
 l15_contamination_end, l20_contamination_end)
VALUES
(GENERATE_UUID(), 'nba_raw.bdl_player_boxscores', 'player', 'lebron_james',
 '2026-01-15', 240, 'manual',
 '2026-01-22', '2026-01-26', '2026-02-01', '2026-02-08');
```

### Recording Contaminated Records

After computing the cascade, record each affected downstream record:

```sql
INSERT INTO nba_orchestration.contamination_records
(contamination_id, backfill_id, downstream_table, entity_id, game_date,
 affected_windows, contaminated_quality_score, remediation_status)
SELECT
    GENERATE_UUID(),
    @backfill_id,
    'nba_precompute.player_composite_factors',
    @player_lookup,
    game_date,
    ['L5', 'L10'],  -- which windows were incomplete
    0.8,            -- quality score with incomplete data
    'pending'
FROM UNNEST(GENERATE_DATE_ARRAY(@gap_date + 1, @l10_contamination_end)) as game_date;
```

### Checking Pending Remediations

```sql
SELECT * FROM nba_orchestration.v_pending_remediations
WHERE downstream_table = 'nba_precompute.player_composite_factors'
ORDER BY days_since_contamination DESC;
```

### Recording Remediation

After running remediation scripts:

```sql
INSERT INTO nba_orchestration.remediation_log
(remediation_id, remediation_type, target_table, player_lookup,
 start_date, end_date, records_processed, records_updated,
 avg_quality_before, avg_quality_after, triggered_by_backfill_id, status)
VALUES
(GENERATE_UUID(), 'player_range', 'nba_precompute.player_composite_factors',
 'lebron_james', '2026-01-16', '2026-02-08', 20, 20, 0.8, 1.0,
 @backfill_id, 'completed');

-- Then update contamination records
UPDATE nba_orchestration.contamination_records
SET
    remediation_status = 'completed',
    remediated_at = CURRENT_TIMESTAMP(),
    final_quality_score = 1.0
WHERE backfill_id = @backfill_id;
```

## Integration with Other Skills

| After | Use | Purpose |
|-------|-----|---------|
| `/spot-check-gaps` finds issues | `/spot-check-cascade` | Understand full impact |
| Backfill raw data | `/spot-check-cascade --backfilled` | Get remediation commands |
| Run remediation | `/validate-lineage` | Verify fix is correct |

## Important Considerations

### 1. Prediction Accuracy Impact

Contaminated predictions CANNOT be fixed - they were made and graded. But:
- Track how many predictions were affected
- May need to exclude from model training data
- May affect reported accuracy metrics

### 2. Window Overlap

Multiple gaps can have overlapping contamination windows:
- Gap on Jan 15 affects Jan 16-Feb 8
- Gap on Jan 20 affects Jan 21-Feb 13
- Overlapping region needs ONE reprocessing, not multiple

### 3. Cascade Depth

Quality scores propagate through the chain:
```
Raw data quality = 1.0 (after backfill)
player_game_summary quality = 1.0 (reprocessed)
player_composite_factors quality = 0.95 (if 19/20 games were clean)
ml_feature_store quality = 0.95 (inherits from composite)
predictions quality = 0.95 (inherits from features)
```

### 4. When NOT to Remediate

Skip remediation if:
- Gap is old (> 60 days) and predictions already graded
- Player is inactive (no future predictions needed)
- Cost of reprocessing > value of correction

## Related Documentation

| Document | Purpose |
|----------|---------|
| [DESIGN-DECISIONS.md](../../../docs/08-projects/current/data-lineage-integrity/DESIGN-DECISIONS.md) | Architecture overview |
| [IMPLEMENTATION-REQUEST.md](../../../docs/08-projects/current/data-lineage-integrity/IMPLEMENTATION-REQUEST.md) | Technical specs |
| `/validate-lineage` | Verify correctness after remediation |
