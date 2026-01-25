# Cascade Impact Tracking

## Overview

When data is missing or incomplete for a given date, downstream dates that depend on that data through rolling windows are also affected. This document explains how to identify and track these cascade impacts.

## The Cascade Problem

### Rolling Window Dependencies

The pipeline uses multiple rolling windows for feature calculations:

| Window | Description | Days Affected |
|--------|-------------|---------------|
| L5 | Last 5 games | ~7-10 calendar days |
| L10 | Last 10 games | ~14-20 calendar days |
| L7d | Last 7 calendar days | 7 days |
| L14d | Last 14 calendar days | 14 days |
| L20 | Last 20 games | ~30 calendar days |

### Cascade Example

If **January 15, 2025** has missing Phase 2 data:

```
Jan 15: MISSING (Phase 2 gap)
├── Jan 15: Phase 3 player_game_summary = 0 records
│   ├── Jan 15: Phase 4 = 0 records (no input)
│   └── Jan 16-24: Phase 3 upcoming_player_game_context degraded (L10 window)
│       └── Jan 16-24: Phase 4 player_composite_factors degraded
│           └── Jan 16-24: Phase 4 ml_feature_store degraded
│               └── Jan 16-24: Phase 5 predictions degraded quality
│
├── Jan 16-24: Phase 4 player_shot_zone_analysis affected (L10 window)
│
└── Jan 16-Feb 3: Phase 4 player_daily_cache affected (L20 window)
    └── Jan 16-Feb 3: Phase 5 ml_feature_store affected
```

## Cascade Impact Calculation

### Algorithm

```python
def calculate_cascade_impact(gap_date: date, gap_phase: int) -> dict:
    """
    Calculate all downstream dates affected by a gap.

    Returns:
        {
            'gap_date': date,
            'gap_phase': int,
            'affected_dates': {
                'phase3': [list of dates],
                'phase4': [list of dates],
                'phase5': [list of dates],
            },
            'total_affected_days': int,
            'severity': 'HIGH' | 'MEDIUM' | 'LOW'
        }
    """

    affected = {
        'phase3': [],
        'phase4': [],
        'phase5': []
    }

    # Get game dates after the gap (from schedule)
    future_game_dates = get_game_dates_after(gap_date, limit=30)

    if gap_phase <= 2:
        # Phase 2 gap affects ALL downstream phases
        # Phase 3: Direct impact + L10 window
        affected['phase3'] = [gap_date] + future_game_dates[:10]

        # Phase 4: L20 window (longest)
        affected['phase4'] = [gap_date] + future_game_dates[:20]

        # Phase 5: Same as Phase 4 (depends on Phase 4)
        affected['phase5'] = [gap_date] + future_game_dates[:20]

    elif gap_phase == 3:
        # Phase 3 gap affects Phase 4 and 5
        affected['phase4'] = [gap_date] + future_game_dates[:20]
        affected['phase5'] = [gap_date] + future_game_dates[:20]

    elif gap_phase == 4:
        # Phase 4 gap affects Phase 5 only
        affected['phase5'] = [gap_date] + future_game_dates[:10]

    # Calculate severity
    total_affected = len(set(
        affected['phase3'] + affected['phase4'] + affected['phase5']
    ))

    if total_affected >= 20:
        severity = 'HIGH'
    elif total_affected >= 10:
        severity = 'MEDIUM'
    else:
        severity = 'LOW'

    return {
        'gap_date': gap_date,
        'gap_phase': gap_phase,
        'affected_dates': affected,
        'total_affected_days': total_affected,
        'severity': severity
    }
```

### Lookback Window Details by Processor

| Processor | Primary Window | Secondary Window | Max Impact Days |
|-----------|---------------|------------------|-----------------|
| **Phase 3** |
| player_game_summary | Current date | None | 0 (direct only) |
| upcoming_player_game_context | L10 games | L14d calendar | 14-20 days |
| **Phase 4** |
| player_shot_zone_analysis | L10 games | L20 games | 30 days |
| team_defense_zone_analysis | L15 games | None | 20-25 days |
| player_composite_factors | L10 games | None | 15-20 days |
| player_daily_cache | L5, L10 | L7d, L14d | 20 days |
| ml_feature_store | All Phase 4 | Combined | 30 days |

## Cascade Impact Queries

### Query 1: Find All Gaps

```sql
-- Find all dates with Phase 2 gaps (missing raw data)
WITH schedule AS (
  SELECT DISTINCT game_date
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
    AND game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
),
phase2_dates AS (
  SELECT DISTINCT game_date
  FROM `nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
)
SELECT
  s.game_date,
  CASE WHEN p.game_date IS NULL THEN 'GAP' ELSE 'OK' END as phase2_status
FROM schedule s
LEFT JOIN phase2_dates p USING (game_date)
WHERE p.game_date IS NULL
ORDER BY s.game_date
```

### Query 2: Calculate Cascade Impact for a Gap

```sql
-- For a specific gap date, find all affected downstream dates
DECLARE gap_date DATE DEFAULT '2025-01-15';

WITH future_games AS (
  SELECT
    game_date,
    ROW_NUMBER() OVER (ORDER BY game_date) as game_number
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
    AND game_date > gap_date
    AND game_date <= DATE_ADD(gap_date, INTERVAL 30 DAY)
)
SELECT
  gap_date as gap_date,
  game_date as affected_date,
  game_number as games_since_gap,
  DATE_DIFF(game_date, gap_date, DAY) as days_since_gap,
  CASE
    WHEN game_number <= 10 THEN 'phase3_l10'
    WHEN game_number <= 20 THEN 'phase4_l20'
    ELSE 'phase4_extended'
  END as impact_window,
  CASE
    WHEN game_number <= 5 THEN 'HIGH'
    WHEN game_number <= 15 THEN 'MEDIUM'
    ELSE 'LOW'
  END as impact_severity
FROM future_games
ORDER BY game_date
```

### Query 3: Aggregate Cascade Impact Across All Gaps

```sql
-- Calculate total cascade contamination across all gaps
WITH gaps AS (
  SELECT game_date as gap_date
  FROM validation_results
  WHERE status = 'FAIL'
    AND phase IN ('phase2', 'phase3')
),
future_games AS (
  SELECT DISTINCT game_date
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
),
cascade_impact AS (
  SELECT
    g.gap_date,
    f.game_date as affected_date,
    DATE_DIFF(f.game_date, g.gap_date, DAY) as days_downstream
  FROM gaps g
  CROSS JOIN future_games f
  WHERE f.game_date > g.gap_date
    AND f.game_date <= DATE_ADD(g.gap_date, INTERVAL 20 DAY)
)
SELECT
  affected_date,
  COUNT(DISTINCT gap_date) as upstream_gaps_count,
  STRING_AGG(CAST(gap_date AS STRING), ', ' ORDER BY gap_date) as upstream_gap_dates,
  CASE
    WHEN COUNT(DISTINCT gap_date) >= 3 THEN 'CRITICAL'
    WHEN COUNT(DISTINCT gap_date) >= 2 THEN 'HIGH'
    ELSE 'MEDIUM'
  END as contamination_severity
FROM cascade_impact
GROUP BY affected_date
HAVING COUNT(DISTINCT gap_date) > 0
ORDER BY affected_date
```

## Cascade Impact Matrix

### When Phase 2 Data is Missing

| Gap Type | Phase 3 Impact | Phase 4 Impact | Phase 5 Impact |
|----------|---------------|----------------|----------------|
| Single date | Date X missing | Date X + next 20 degraded | Date X + next 20 degraded |
| 3 consecutive | Dates X-Z missing | Dates X to X+22 degraded | Dates X to X+22 degraded |
| Week gap | 7 dates missing | Dates X to X+27 degraded | Dates X to X+27 degraded |

### When Phase 3 Data is Missing (but Phase 2 exists)

| Gap Type | Phase 4 Impact | Phase 5 Impact |
|----------|----------------|----------------|
| Single date | Date X + next 20 degraded | Same |
| Processing error | Reprocess Phase 3 only | Then Phase 4-5 |

### When Phase 4 Data is Missing (but Phase 3 exists)

| Gap Type | Phase 5 Impact |
|----------|----------------|
| Single date | Date X + next 10 degraded |
| MLFS missing | Predictions may be skipped |

## Marking Dates for Re-Run

### Decision Tree

```
For each date with a gap:

1. Is Phase 2 data missing?
   YES → Mark for Phase 2 backfill
         Mark downstream dates (X to X+20) for Phase 3-5 re-run

2. Is Phase 3 data missing (but Phase 2 exists)?
   YES → Mark for Phase 3 backfill
         Mark downstream dates (X to X+20) for Phase 4-5 re-run

3. Is Phase 4 data missing (but Phase 3 exists)?
   YES → Mark for Phase 4 backfill
         Mark downstream dates (X to X+10) for Phase 5 re-run

4. Is Phase 5 data missing (but Phase 4 exists)?
   YES → Mark for Phase 5 backfill only (no cascade)

5. Is the date within 20 days of an upstream gap?
   YES → Mark as "cascade-affected"
         Will be automatically fixed when upstream is fixed
```

### Backfill Order

When fixing gaps, always process in this order:

```
1. Fix ALL Phase 2 gaps first (oldest to newest)
2. Wait for Phase 2 complete
3. Fix ALL Phase 3 gaps (oldest to newest)
   - Include cascade-affected dates from Phase 2 gaps
4. Wait for Phase 3 complete
5. Fix ALL Phase 4 gaps (in dependency order: TDZA → PSZA → PCF → PDC → MLFS)
   - Include cascade-affected dates from Phase 2-3 gaps
6. Wait for Phase 4 complete
7. Fix ALL Phase 5 gaps
```

## Tracking Cascade Status

### Validation Results Table Extension

Add these columns to track cascade:

```sql
ALTER TABLE validation_results ADD COLUMN IF NOT EXISTS
  is_cascade_affected BOOL,
  upstream_gap_dates ARRAY<DATE>,
  cascade_severity STRING,  -- 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
  needs_rerun_after_upstream BOOL
```

### Example Records

```json
// Direct gap
{
  "game_date": "2025-01-15",
  "phase": "phase2",
  "status": "FAIL",
  "is_cascade_affected": false,
  "upstream_gap_dates": [],
  "cascade_severity": null,
  "needs_rerun_after_upstream": false
}

// Cascade-affected date
{
  "game_date": "2025-01-20",
  "phase": "phase4",
  "status": "WARN",
  "is_cascade_affected": true,
  "upstream_gap_dates": ["2025-01-15"],
  "cascade_severity": "MEDIUM",
  "needs_rerun_after_upstream": true
}
```

## Cascade Resolution Workflow

### Step 1: Identify All Gaps

```bash
python bin/validation/season_validation_scan.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --output validation_gaps.json
```

### Step 2: Calculate Cascade Impact

```bash
python bin/validation/calculate_cascade_impact.py \
  --gaps-file validation_gaps.json \
  --output cascade_impact.json
```

### Step 3: Generate Backfill Queue

```bash
python bin/validation/generate_backfill_queue.py \
  --cascade-file cascade_impact.json \
  --output backfill_queue.json
```

### Step 4: Execute Backfills in Order

```bash
# Phase 2 first
python bin/backfill/run_phase2_backfill.sh --dates-file backfill_queue_phase2.json

# Then Phase 3
python bin/backfill/run_year_phase3.sh --dates-file backfill_queue_phase3.json

# Then Phase 4 (in dependency order)
python bin/backfill/run_phase4_backfill.sh --dates-file backfill_queue_phase4.json

# Finally Phase 5
python bin/backfill/run_phase5_backfill.sh --dates-file backfill_queue_phase5.json
```

### Step 5: Validate Resolution

```bash
python bin/validation/verify_cascade_resolution.py \
  --original-gaps validation_gaps.json \
  --output resolution_report.json
```

## Quick Reference: Cascade Rules

| Gap Phase | Downstream Phases Affected | Window Size | Priority |
|-----------|---------------------------|-------------|----------|
| Phase 2 | 3, 4, 5 | 20-30 days | CRITICAL |
| Phase 3 | 4, 5 | 20 days | HIGH |
| Phase 4 | 5 | 10 days | MEDIUM |
| Phase 5 | None | 0 days | LOW |

## Important Notes

1. **Always fix upstream first** - Fixing Phase 4 when Phase 2 is missing wastes effort
2. **Batch by phase** - Fix all Phase 2 gaps before moving to Phase 3
3. **Oldest first** - Within a phase, fix oldest gaps first (they have largest cascade)
4. **Verify resolution** - After backfill, verify cascade-affected dates are clean
5. **Bootstrap exception** - First 14 days of season (Oct 22 - Nov 5) have expected low quality
