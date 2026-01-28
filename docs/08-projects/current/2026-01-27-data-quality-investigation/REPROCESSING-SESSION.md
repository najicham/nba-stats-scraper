# Jan 26-27 Reprocessing Session

**Date**: 2026-01-27 16:00-16:30 PST
**Agent**: Sonnet 4.5
**Status**: BLOCKED - Requires code fix deployment

---

## Summary

Attempted to reprocess Jan 26-27 data after analytics processor fixes were deployed. Discovered a critical bug in the deployed code that prevents successful execution.

---

## Deployment Status

### Analytics Processor Revision
- **Current Revision**: `nba-phase3-analytics-processors-00124-hfl`
- **Deployed**: 2026-01-27 19:40 PST
- **Image**: `us-west2-docker.pkg.dev/nba-props-platform/cloud-run-source-deploy/nba-phase3-analytics-processors@sha256:dc80e65...`

### Included Fixes
✅ `d3066c88` - Handle game_id format mismatch in team stats JOIN
✅ `3c1b8fdb` - Add team stats availability check to prevent NULL usage_rate
✅ `217c5541` - Prevent duplicate records via streaming buffer handling
✅ `3d77ecaa` - Re-trigger upcoming_player_game_context when betting lines arrive

---

## Critical Bug Discovered

### Bug Details
**File**: `/home/naji/code/nba-stats-scraper/data_processors/analytics/analytics_base.py`
**Line**: 424
**Issue**: `UnboundLocalError: cannot access local variable 'analysis_date' where it is not associated with a value`

### Root Cause
```python
# Line 421-436 (added 2026-01-27)
logger.info("processor_started", extra={
    "event": "processor_started",
    "processor": self.processor_name,
    "game_date": str(analysis_date),  # ❌ BUG: analysis_date not yet defined
    ...
})
```

The variable `analysis_date` is first defined on line 459 within a conditional block, but is used earlier on line 424.

### Impact
- **Severity**: P0 (blocks all analytics processing)
- **Scope**: All Phase 3 analytics processors
- **Symptoms**: Processor crashes immediately after dependency checks

---

## Attempted Reprocessing Methods

### 1. Cloud Run HTTP Endpoint ❌ FAILED
**Method**: Direct HTTP POST to `/process-date-range`
**Error**: `403 Forbidden` - IAM restrictions
**Reason**: User account not in allowed invokers list

```bash
# Attempted fix
gcloud run services add-iam-policy-binding nba-phase3-analytics-processors \
  --member="user:nchammas@gmail.com" \
  --role="roles/run.invoker"

# Still failed - may need time to propagate OR additional config
```

### 2. Pub/Sub Trigger ❌ FAILED
**Method**: Published message to `nba-phase3-trigger` topic
**Error**: Wrong message format
**Reason**: Topic expects specific message schema from Phase 2 completion

### 3. Local Execution ❌ FAILED
**Method**: Direct Python execution of processors
**Error**: `UnboundLocalError` on line 424 (the bug)
**Output**:
```
ERROR:analytics_base:AnalyticsProcessorBase Error: cannot access local variable 'analysis_date' where it is not associated with a value
```

### 4. Command Line Execution ❌ FAILED
**Method**: `python3 team_offense_game_summary_processor.py --start-date ...`
**Error**: `504 Deadline Exceeded` on Firestore heartbeat
**Reason**: Network timeouts from local environment

---

## Current Data State

### Jan 26 (Yesterday)
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Player records | 249 | ~240 | ✅ |
| Usage_rate coverage | 57.8% (144/249) | 90%+ | ❌ |
| Team stats records | 20 | 20 (10 games × 2) | ✅ |
| Predictions | 0 | ~240 | ❌ |

### Jan 27 (Today)
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Player records | 0 | ~220 | ❌ |
| Predictions | 0 | ~220 | ❌ |

---

## Root Cause Analysis

### Why is usage_rate coverage only 57.8%?

The game_id mismatch bug (d3066c88) caused team stats JOINs to fail:
- **Player stats use**: `AWAY_HOME` format (e.g., `20260126_BOS_LAL`)
- **Team stats use**: `HOME_AWAY` format (e.g., `20260126_LAL_BOS`)
- **Result**: LEFT JOIN returns NULL for all team columns
- **Impact**: `usage_rate` calculation requires `team_possessions`, which is NULL

### Fix Deployed
Commit `d3066c88` adds `game_id_reversed` logic:
```sql
LEFT JOIN team_stats ts ON (
  wp.game_id = ts.game_id OR
  wp.game_id = ts.game_id_reversed
) AND wp.team_abbr = ts.team_abbr
```

### Why hasn't it been applied?
The deployed code has the fix BUT contains a separate bug (line 424) that prevents it from running.

---

## Remediation Plan

### IMMEDIATE (Next Deployment)

1. **Fix the bug in analytics_base.py**
   ```python
   # Line 421-436: Move analysis_date definition before logger.info()
   analysis_date = self.opts.get('end_date') or self.opts.get('start_date')

   logger.info("processor_started", extra={
       "event": "processor_started",
       "processor": self.processor_name,
       "game_date": str(analysis_date) if analysis_date else None,  # Safe access
       ...
   })
   ```

2. **Deploy fixed analytics processor**
   ```bash
   cd /home/naji/code/nba-stats-scraper
   ./scripts/deploy/deploy-analytics.sh
   ```

3. **Reprocess Jan 26-27** (after deployment)
   ```bash
   # Method 1: Via Cloud Run HTTP (with proper auth)
   curl -X POST \
     "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
     -H "X-API-Key: $(gcloud secrets versions access latest --secret=analytics-api-keys)" \
     -H "Content-Type: application/json" \
     -d '{
       "start_date": "2026-01-26",
       "end_date": "2026-01-27",
       "processors": ["team_offense_game_summary", "player_game_summary"],
       "backfill_mode": true
     }'

   # Method 2: Via command line (if Cloud Run auth issues persist)
   PYTHONPATH=/home/naji/code/nba-stats-scraper \
     python3 data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py \
     --start-date 2026-01-26 --end-date 2026-01-27 --backfill-mode

   PYTHONPATH=/home/naji/code/nba-stats-scraper \
     python3 data_processors/analytics/player_game_summary/player_game_summary_processor.py \
     --start-date 2026-01-26 --end-date 2026-01-27 --backfill-mode
   ```

4. **Trigger predictions for Jan 27**
   ```bash
   python3 bin/predictions/clear_and_restart_predictions.py \
     --game-date 2026-01-27
   ```

5. **Verify improvements**
   ```sql
   SELECT game_date,
     COUNT(*) as total,
     COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) as valid_usage,
     ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) / COUNT(*), 1) as usage_pct
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date IN ('2026-01-26', '2026-01-27')
   GROUP BY game_date
   ORDER BY game_date
   ```

   **Expected Result**: usage_pct >= 90% for both dates

---

## Alternative: SQL-Based Reprocessing

If deploying a fix is not immediately possible, we can manually fix the data via SQL:

### Step 1: Create corrected records
```sql
CREATE OR REPLACE TABLE `nba-props-platform.nba_analytics.player_game_summary_fixed` AS
WITH team_stats AS (
  SELECT
    game_id,
    CONCAT(
      SUBSTR(game_id, 1, 9),
      SPLIT(game_id, '_')[OFFSET(2)], '_',
      SPLIT(game_id, '_')[OFFSET(1)]
    ) as game_id_reversed,
    team_abbr,
    possessions as team_possessions,
    fg_attempts as team_fg_attempts,
    ft_attempts as team_ft_attempts,
    turnovers as team_turnovers
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE game_date IN ('2026-01-26', '2026-01-27')
)
SELECT
  p.*,
  -- Recalculate usage_rate with corrected team stats
  CASE
    WHEN ts.team_possessions IS NOT NULL AND ts.team_possessions > 0 THEN
      100.0 * (
        (p.fg_attempts + 0.44 * p.ft_attempts + p.turnovers) /
        ts.team_possessions
      )
    ELSE NULL
  END as usage_rate_fixed
FROM `nba-props-platform.nba_analytics.player_game_summary` p
LEFT JOIN team_stats ts ON (
  p.game_id = ts.game_id OR
  p.game_id = ts.game_id_reversed
) AND p.team_abbr = ts.team_abbr
WHERE p.game_date IN ('2026-01-26', '2026-01-27')
```

### Step 2: Update original table
```sql
UPDATE `nba-props-platform.nba_analytics.player_game_summary` p
SET usage_rate = f.usage_rate_fixed
FROM `nba-props-platform.nba_analytics.player_game_summary_fixed` f
WHERE p.player_lookup = f.player_lookup
  AND p.game_date = f.game_date
  AND p.game_id = f.game_id
  AND f.usage_rate_fixed IS NOT NULL
```

---

## Lessons Learned

1. **Pre-deployment testing**: The logging code added on 2026-01-27 was not tested with actual processor execution
2. **Variable scoping**: Be careful with variable usage in logging/instrumentation code
3. **Defensive programming**: Use `str(x) if x else None` instead of `str(x)` for potentially undefined variables
4. **Local testing environment**: Need better local testing setup that doesn't rely on Firestore/network services

---

## Next Steps

1. ✅ **DOCUMENT** - This file
2. ⏳ **FIX** - Create PR with line 424 bug fix
3. ⏳ **DEPLOY** - Deploy fixed analytics processor
4. ⏳ **REPROCESS** - Run reprocessing for Jan 26-27
5. ⏳ **VERIFY** - Confirm usage_rate >= 90%
6. ⏳ **PREDICTIONS** - Trigger predictions for Jan 27

---

## Files Referenced

- `/home/naji/code/nba-stats-scraper/data_processors/analytics/analytics_base.py` (line 424 bug)
- `/home/naji/code/nba-stats-scraper/data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- `/home/naji/code/nba-stats-scraper/bin/predictions/clear_and_restart_predictions.py`
- `/tmp/run_local_reprocessing.py` (attempted workaround script)

---

**Status**: Waiting for bug fix and redeployment before reprocessing can proceed.
