# Gap Detection Guide

Comprehensive guide to detecting and resolving data gaps across all processing phases.

## Quick Start

```bash
# Check all phases for a date range
python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31

# Check specific phase only
python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --phase 3

# Include field-level contamination check
python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --check-contamination

# Output as JSON for automation
python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --json
```

## What the Script Detects

### 1. Missing Dates
Dates where a table has zero records when games were expected.

```
GAP: player_game_summary missing 2021-12-22 (0 records, expected ~150)
```

### 2. Low Record Counts
Dates with significantly fewer records than expected (< 50% of average).

```
WARNING: player_game_summary has low count on 2021-12-25 (45 records, expected ~150)
```

### 3. Field Contamination (with --check-contamination)
Dates where critical fields are NULL or zero when they shouldn't be.

**Critical Fields by Table:**

| Table | Critical Fields | Why Critical |
|-------|----------------|--------------|
| player_game_summary | paint_attempts, paint_makes, universal_player_id | Shot zones needed for PSZA/PCF |
| team_defense_game_summary | opp_paint_attempts, opp_fg_pct | Defense metrics for TDZA |
| team_offense_game_summary | fg_attempts, fg_makes | Offense baseline |
| upcoming_player_game_context | minutes_played_l5, pts_per_game_l10 | Context for predictions |

### 4. Cascade Impact
Shows which downstream processors are blocked by gaps.

```
CASCADE IMPACT:
  player_game_summary gap on 2021-12-22 blocks:
    → player_shot_zone_analysis (Phase 4)
    → player_consistency_factors (Phase 4)
    → ml_feature_store (Phase 5)
```

## Understanding the Output

### Gap Report Structure

```
================================================================================
GAP DETECTION REPORT
================================================================================
Date Range: 2021-12-01 to 2021-12-31
Expected Game Days: 30
Phases Checked: [2, 3, 4]

----------------------------------------
PHASE 3: Analytics
----------------------------------------
Table: player_game_summary
  GAPS FOUND: 2
    2021-12-22: 0 records (MISSING)
    2021-12-27: 0 records (MISSING)

  CASCADE IMPACT:
    These gaps block Phase 4 processors:
    - player_shot_zone_analysis
    - player_consistency_factors

----------------------------------------
SUMMARY
----------------------------------------
Total Gaps Found: 2
Total Days Affected: 2

By Priority:
  HIGH: 2 (blocks downstream processing)

----------------------------------------
RECOVERY COMMANDS
----------------------------------------
# Run in this order (respects dependencies):

# 1. Fix Phase 3 gaps first
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
    --dates 2021-12-22,2021-12-27

# 2. Then Phase 4 (after Phase 3 complete)
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_backfill.py \
    --dates 2021-12-22,2021-12-27
```

### Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | No gaps found | All clear |
| 1 | High priority gaps | Run recovery commands |
| 2 | Critical gaps (multiple downstream impact) | Prioritize immediately |

## Cascade Dependency Map

Understanding which tables feed into others is crucial for recovery ordering:

```
Phase 2 (Raw/Reference)          Phase 3 (Analytics)           Phase 4 (Precompute)
─────────────────────           ──────────────────           ─────────────────────

nbac_player_boxscore ──────────→ player_game_summary ───────→ player_shot_zone_analysis
                                      │                              │
                                      │                              ↓
                                      │                       player_consistency_factors
                                      │                              │
                                      ↓                              ↓
                                upcoming_player_game_context   player_daily_cache
                                                                     │
                                                                     ↓
nbac_team_boxscore ────────────→ team_defense_game_summary ──→ team_defense_zone_analysis
                                      │                              │
                                      ↓                              ↓
                                team_offense_game_summary      ml_feature_store (Phase 5)
```

### Key Dependencies

| If This Is Missing | These Are Blocked |
|-------------------|-------------------|
| player_game_summary | PSZA, PCF, PDC, ML features |
| team_defense_game_summary | TDZA, ML features |
| player_shot_zone_analysis | PCF, PDC |
| team_defense_zone_analysis | ML features |

## Recovery Workflow

### Step 1: Identify Gaps
```bash
python scripts/detect_gaps.py --start-date 2021-11-01 --end-date 2021-12-31 --phase 3
```

### Step 2: Understand Root Cause

Common causes of gaps:

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Missing dates in Phase 3 | Backfill never ran | Run backfill for those dates |
| Low record counts | Partial failure during processing | Re-run with --no-resume |
| NULL critical fields | Source data missing | Check Phase 2 first |
| All zeros in shot zones | BigDataBall PBP unavailable | Use nbac_play_by_play fallback |

### Step 3: Fix in Dependency Order

Always fix upstream gaps before downstream:

```bash
# 1. Phase 2 gaps first (if any)
# Check raw data availability

# 2. Phase 3 gaps
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
    --dates 2021-12-22,2021-12-27 --no-resume

# 3. Phase 4 gaps (only after Phase 3 is complete)
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_backfill.py \
    --dates 2021-12-22,2021-12-27
```

### Step 4: Verify Fix
```bash
# Re-run gap detection to confirm
python scripts/detect_gaps.py --start-date 2021-12-22 --end-date 2021-12-27 --phase 3
```

## Automation Integration

### Scheduled Gap Detection

Add to daily monitoring:

```bash
# In cron or Cloud Scheduler
0 6 * * * python scripts/detect_gaps.py --start-date $(date -d '7 days ago' +%Y-%m-%d) --end-date $(date -d 'yesterday' +%Y-%m-%d) --json > /tmp/gap_report.json
```

### CI/CD Integration

```yaml
# In GitHub Actions or Cloud Build
- name: Check for gaps
  run: |
    python scripts/detect_gaps.py \
      --start-date ${{ env.START_DATE }} \
      --end-date ${{ env.END_DATE }} \
      --phase 3 4
    if [ $? -ne 0 ]; then
      echo "Gaps detected - check report"
      exit 1
    fi
```

### JSON Output for Parsing

```bash
python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --json
```

Output structure:
```json
{
  "date_range": {"start": "2021-12-01", "end": "2021-12-31"},
  "expected_game_days": 30,
  "gaps": [
    {
      "phase": 3,
      "table": "player_game_summary",
      "date": "2021-12-22",
      "type": "missing",
      "record_count": 0,
      "cascade_impact": ["player_shot_zone_analysis", "player_consistency_factors"]
    }
  ],
  "summary": {
    "total_gaps": 1,
    "by_phase": {"3": 1},
    "by_priority": {"high": 1}
  },
  "recovery_commands": [
    "python backfill_jobs/analytics/player_game_summary/... --dates 2021-12-22"
  ]
}
```

## Troubleshooting

### "No expected game dates found"
The script queries the NBA schedule to find game dates. If no dates are found:
- Check that the date range is within an NBA season
- Verify `nba_reference.nba_schedule` table has data

### "Connection error to BigQuery"
- Ensure `GOOGLE_APPLICATION_CREDENTIALS` is set
- Check project ID is correct (`nba-props-platform`)

### "Gaps reported but data exists"
- The script uses a minimum threshold (default 50% of average)
- Low game days (e.g., holidays) may trigger false positives
- Use `--check-contamination` to verify field-level integrity

## Related Documentation

- [Backfill Guide](backfill-guide.md) - Comprehensive backfill procedures
- [Data Integrity Guide](data-integrity-guide.md) - Field validation details
- [Backfill Mode Reference](backfill-mode-reference.md) - Backfill mode specifics
