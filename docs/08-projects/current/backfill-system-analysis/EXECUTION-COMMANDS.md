# Player Game Summary Backfill - Execution Commands
**Date**: 2026-01-02
**Backfill Period**: 2021-10-01 to 2024-05-01 (940 days)
**Estimated Duration**: 6-12 hours

---

## RECOMMENDED: Sequential Execution

Copy-paste ready commands for sequential backfill execution.

---

### Step 1: Pre-Flight Validation (15 minutes)

```bash
# Navigate to project root
cd /home/naji/code/nba-stats-scraper

# Activate virtual environment
source .venv/bin/activate

# Verify script exists
ls -la backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py

# Check raw data availability
bq query --use_legacy_sql=false "
SELECT
  'bdl_boxscores' as source,
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as unique_games,
  SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) as null_minutes,
  ROUND(SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'

UNION ALL

SELECT
  'nbac_gamebook' as source,
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as unique_games,
  SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) as null_minutes,
  ROUND(SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
"

# Expected output:
# bdl_boxscores: null_pct < 1%
# nbac_gamebook: null_pct < 1%
# If null_pct > 5%, STOP and investigate
```

---

### Step 2: Sample Test (30 minutes)

Test on single week to validate processor behavior:

```bash
# Test on one week from January 2022
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-01-10 \
  --end-date 2022-01-16 \
  --no-resume

# Expected output:
# - "✓ Success: XXX records from YY games" messages
# - Processing rate: 5-15 days/hour
# - No errors or exceptions

# Validate sample results
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total_players,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2022-01-10' AND '2022-01-16'
GROUP BY game_date
ORDER BY game_date;
"

# Success criteria:
# - null_pct < 50% for all dates
# - Most dates have null_pct 35-45%
# If null_pct > 80%, STOP and investigate processor

# Spot check actual values
bq query --use_legacy_sql=false "
SELECT
  game_date,
  player_full_name,
  team_abbr,
  points,
  minutes_played,
  primary_source_used
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2022-01-15'
ORDER BY minutes_played DESC NULLS LAST
LIMIT 20;
"

# Verify:
# - Top players have realistic minutes (30-42)
# - DNP players have NULL
# - Values look correct
```

---

### Step 3: Full Backfill Execution (6-12 hours)

**IMPORTANT**: Run in tmux/screen session to prevent interruption

#### Setup Session

```bash
# Start tmux session (recommended)
tmux new-session -s backfill

# OR use screen
screen -S backfill

# Navigate to project
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Create logs directory
mkdir -p logs/backfill
```

#### Execute Backfill

```bash
# Run full backfill with logging
# This will process all 940 days in batches
# Checkpoint allows resume if interrupted

PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  2>&1 | tee logs/backfill/player_game_summary_$(date +%Y%m%d_%H%M%S).log

# Detach from tmux: Ctrl+b, then d
# Reattach later: tmux attach -t backfill

# OR for screen:
# Detach: Ctrl+a, then d
# Reattach: screen -r backfill
```

#### Monitor Progress (Separate Terminal)

```bash
# Terminal 2: Monitor NULL rate improvement
watch -n 300 'bq query --use_legacy_sql=false "
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct,
  MAX(processed_at) as last_update
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '\''2021-10-01'\'' AND game_date < '\''2024-05-01'\''
GROUP BY month
ORDER BY month DESC
LIMIT 12;
"'

# Watch for:
# - null_pct dropping from 95%+ to ~40%
# - last_update advancing
# - Steady progress through months
```

#### Check Checkpoint Status

```bash
# View checkpoint file
cat /tmp/backfill_checkpoints/player_game_summary_checkpoint.json | jq .

# Shows:
# - Last completed date
# - Successful count
# - Failed count
# - Progress percentage
```

---

### Step 4: Post-Backfill Validation (30 minutes)

Once backfill completes, validate results:

```bash
# 1. Overall NULL rate check
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
"

# Success: null_pct < 45%
# Excellent: null_pct < 40%
# Failure: null_pct > 80% (investigate)

# 2. Row count verification
bq query --use_legacy_sql=false "
SELECT
  'Before backfill' as state,
  83534 as expected_rows
UNION ALL
SELECT
  'After backfill' as state,
  COUNT(*) as actual_rows
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
"

# Expected: actual_rows ≈ expected_rows (±2% acceptable)

# 3. Season breakdown
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date >= '2021-10-01' AND game_date < '2022-07-01' THEN '2021-22'
    WHEN game_date >= '2022-07-01' AND game_date < '2023-07-01' THEN '2022-23'
    WHEN game_date >= '2023-07-01' AND game_date < '2024-05-01' THEN '2023-24'
  END as season,
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY season
ORDER BY season;
"

# All seasons should show null_pct < 45%

# 4. Sample game validation (Lakers vs Warriors, Jan 18, 2022)
bq query --use_legacy_sql=false "
SELECT
  player_full_name,
  team_abbr,
  points,
  assists,
  minutes_played,
  primary_source_used
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2022-01-18'
  AND (team_abbr = 'LAL' OR team_abbr = 'GSW')
ORDER BY minutes_played DESC NULLS LAST;
"

# Cross-reference with basketball-reference.com
# https://www.basketball-reference.com/boxscores/202201180LAL.html

# 5. Check for duplicates
bq query --use_legacy_sql=false "
SELECT
  game_date,
  player_lookup,
  team_abbr,
  COUNT(*) as duplicate_count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY game_date, player_lookup, team_abbr
HAVING COUNT(*) > 1
LIMIT 100;
"

# Expected: No results (no duplicates)
# If duplicates found: See rollback plan
```

---

### Step 5: Resume After Failure (If Needed)

If backfill is interrupted:

```bash
# Check last completed date
cat /tmp/backfill_checkpoints/player_game_summary_checkpoint.json | jq '.last_completed_date'

# Resume from checkpoint (automatic)
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Simply re-run the same command - checkpoint handles resume
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  2>&1 | tee -a logs/backfill/player_game_summary_resume_$(date +%Y%m%d_%H%M%S).log

# Script will automatically:
# - Load checkpoint
# - Skip already-processed dates
# - Continue from last successful point
```

---

## ALTERNATIVE: Season-Based Parallel Execution (Emergency Only)

**WARNING**: Use only if time-critical deadline requires <6 hour completion

**Risk**: MEDIUM-HIGH (concurrent write issues possible)

### Setup (One Time)

```bash
# Create 3 separate log directories
mkdir -p logs/backfill/season_2021_22
mkdir -p logs/backfill/season_2022_23
mkdir -p logs/backfill/season_2023_24

cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate
```

### Terminal 1: Worker 1 (2021-22 Season)

```bash
tmux new-session -s worker1

cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Start immediately
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2022-06-30 \
  --no-resume \
  2>&1 | tee logs/backfill/season_2021_22/backfill_$(date +%Y%m%d_%H%M%S).log

# Detach: Ctrl+b, then d
```

### Terminal 2: Worker 2 (2022-23 Season)

```bash
tmux new-session -s worker2

cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Wait 5 minutes to stagger start
sleep 300

PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-07-01 \
  --end-date 2023-06-30 \
  --no-resume \
  2>&1 | tee logs/backfill/season_2022_23/backfill_$(date +%Y%m%d_%H%M%S).log

# Detach: Ctrl+b, then d
```

### Terminal 3: Worker 3 (2023-24 Season)

```bash
tmux new-session -s worker3

cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Wait 10 minutes to stagger start
sleep 600

PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2023-07-01 \
  --end-date 2024-05-01 \
  --no-resume \
  2>&1 | tee logs/backfill/season_2023_24/backfill_$(date +%Y%m%d_%H%M%S).log

# Detach: Ctrl+b, then d
```

### Terminal 4: Monitor All Workers

```bash
# Monitor all 3 tmux sessions
tmux list-sessions

# Attach to any worker to check progress
tmux attach -t worker1  # or worker2, worker3

# Monitor overall progress
watch -n 120 'bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date < '\''2022-07-01'\'' THEN '\''2021-22'\''
    WHEN game_date < '\''2023-07-01'\'' THEN '\''2022-23'\''
    ELSE '\''2023-24'\''
  END as season,
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct,
  MAX(processed_at) as last_update
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '\''2021-10-01'\'' AND game_date < '\''2024-05-01'\''
GROUP BY season
ORDER BY season;
"'

# Watch for:
# - All 3 seasons progressing
# - NULL rates dropping
# - No errors in any worker
# - Completion estimates
```

### Parallel Execution Notes

**Expected Wall-Clock Time**: 2-4 hours (vs 6-12 sequential)

**Monitor Continuously**:
- Check all 3 log files for errors
- If any worker fails, STOP all workers immediately
- Validate each season independently after completion

**Higher Risk**:
- Concurrent DELETE operations
- More complex error recovery
- Harder to debug issues

---

## TROUBLESHOOTING

### Issue 1: BigQuery 413 Error (Request Too Large)

**Symptom**: "Request payload size exceeds the limit"

**Solution**:
```bash
# Script already processes day-by-day to avoid this
# If still occurring, check batch size in code

# This shouldn't happen with current implementation
```

### Issue 2: Streaming Buffer Error

**Symptom**: "UPDATE/DELETE blocked by streaming buffer"

**Solution**:
```bash
# Wait 90 minutes for streaming buffer to clear
# Then resume from checkpoint

# Check if streaming buffer is active
bq show --format=prettyjson nba-props-platform:nba_analytics.player_game_summary | grep streamingBuffer
```

### Issue 3: Registry Lookup Failures

**Symptom**: High "players not found in registry" count

**Solution**:
```bash
# Check unresolved players
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as occurrences,
  MIN(game_date) as first_seen,
  MAX(game_date) as last_seen
FROM \`nba-props-platform.nba_reference.unresolved_player_names\`
WHERE source_name = 'player_game_summary'
GROUP BY player_lookup
ORDER BY occurrences DESC
LIMIT 50;
"

# Add missing aliases to player registry
# Then re-run backfill for affected dates
```

### Issue 4: Slow Processing Rate

**Symptom**: Processing rate < 3 days/hour

**Potential Causes**:
- BigQuery quota limits
- Network issues
- Large number of players per day

**Solution**:
```bash
# Check BigQuery quota
gcloud monitoring dashboards list --filter="displayName:BigQuery"

# Verify network connectivity
ping -c 5 bigquery.googleapis.com

# Check system resources
htop

# If all clear, processing may just be slow
# Let it run - checkpoint will preserve progress
```

---

## SUCCESS CHECKLIST

After backfill completes:

- [ ] NULL rate < 45% (target: 40%)
- [ ] Row count unchanged (±2%)
- [ ] No duplicate records
- [ ] Sample games have correct values
- [ ] All 3 seasons processed successfully
- [ ] Checkpoint shows 100% complete
- [ ] No errors in final logs
- [ ] Validation queries pass

**If all checked**: SUCCESS! Document results and proceed to ML training.

**If any unchecked**: See PLAYER-GAME-SUMMARY-BACKFILL.md rollback plan.

---

## NEXT STEPS AFTER SUCCESS

```bash
# 1. Document results
# Create completion report in docs/08-projects/current/backfill-system-analysis/

# 2. Update ML project status
# Edit docs/08-projects/current/ml-model-development/00-PROJECT-MASTER.md
# Change status from BLOCKED to READY

# 3. Notify team
# Post to Slack/email with results summary

# 4. Begin ML training
# Follow docs/08-projects/current/ml-model-development/03-TRAINING-PLAN.md
```

---

## ESTIMATED TIMELINE

| Task | Duration | Cumulative |
|------|----------|------------|
| Pre-flight validation | 15 min | 0.25 hr |
| Sample test | 30 min | 0.75 hr |
| Full backfill execution | 6-12 hr | 7-13 hr |
| Post-backfill validation | 30 min | 7.5-13.5 hr |

**Total**: 7.5-13.5 hours (mostly unattended)

**Recommended Schedule**:
- **Day 1, 5:00 PM**: Pre-flight + sample test (Steps 1-2)
- **Day 1, 6:00 PM**: Start full backfill (Step 3)
- **Day 2, 6:00 AM**: Check progress (should be complete)
- **Day 2, 9:00 AM**: Validation (Step 4)
- **Day 2, 10:00 AM**: Resume ML work

---

## CONTACTS

**Questions or Issues**: See project documentation

**Emergency Stop**: Kill tmux/screen session, document state, contact team

**Post-Completion**: Update handoff docs with actual results
