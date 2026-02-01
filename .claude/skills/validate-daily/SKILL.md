---
name: validate-daily
description: Validate daily orchestration pipeline health
---

# Daily Orchestration Validation

You are performing a comprehensive daily validation of the NBA stats scraper pipeline. This is NOT a rigid script - you should investigate issues intelligently and adapt based on what you find.

## Your Mission

Validate that the daily orchestration pipeline is healthy and ready for predictions. Check all phases (2-5), run data quality spot checks, investigate any issues found, and provide a clear, actionable summary.

## Key Concept: Game Date vs Processing Date

**Important**: For yesterday's results validation, data spans TWO calendar dates:

```
┌─────────────────────────────────────────────────────────────┐
│ Jan 25th (GAME_DATE)           │ Jan 26th (PROCESSING_DATE) │
├────────────────────────────────┼────────────────────────────┤
│ • Games played (7-11 PM)       │ • Box score scrapers run   │
│ • Player performances          │ • Phase 3 analytics run    │
│ • Predictions made (pre-game)  │ • Predictions graded       │
│                                │ • Cache updated            │
│                                │ • YOU RUN VALIDATION       │
└────────────────────────────────┴────────────────────────────┘
```

**Use the correct date for each query:**
- Game data (box scores, stats, predictions): Use `GAME_DATE`
- Processing status (scraper runs, Phase 3 completion): Use `PROCESSING_DATE`

## Interactive Mode (User Preference Gathering)

**If the user invoked the skill without specific parameters**, ask them what they want to check:

Use the AskUserQuestion tool to gather preferences:

```
Question 1: "What would you like to validate?"
Options:
  - "Today's pipeline (pre-game check)" - Check if today's data is ready before games start
  - "Yesterday's results (post-game check)" - Verify yesterday's games processed correctly
  - "Specific date" - Validate a custom date
  - "Quick health check only" - Just run health check script, no deep investigation

Question 2: "How thorough should the validation be?"
Options:
  - "Standard (Recommended)" - Priority 1 + Priority 2 checks
  - "Quick" - Priority 1 only (critical checks)
  - "Comprehensive" - All priorities including spot checks
```

Based on their answers, determine scope:

| Mode | Thoroughness | Checks Run |
|------|--------------|------------|
| Today pre-game | Standard | Health check + validation + spot checks |
| Today pre-game | Quick | Health check only |
| Yesterday results | Standard | P1 (box scores, grading) + P2 (analytics, cache) |
| Yesterday results | Quick | P1 only (box scores, grading) |
| Yesterday results | Comprehensive | P1 + P2 + P3 (spot checks, accuracy) |

- **Today pre-game**: Run standard workflow, note predictions may not exist yet
- **Yesterday post-game**: Run Yesterday's Results Validation Workflow
- **Specific date**: Ask for date, then run validation for that date
- **Quick health check**: Run Phase 1 only (health check script)

**If the user already provided parameters** (e.g., specific date in their message), skip the questions and proceed with those parameters.

## Date Determination

After determining what to validate, set the target dates:

**If "Today's pipeline (pre-game check)"**:
- `GAME_DATE` = TODAY (games scheduled for tonight)
- `PROCESSING_DATE` = TODAY (data should be ready now)

**If "Yesterday's results (post-game check)"**:
- `GAME_DATE` = YESTERDAY (games that were played)
- `PROCESSING_DATE` = TODAY (scrapers ran after midnight)

**If "Specific date"**:
- `GAME_DATE` = USER_PROVIDED_DATE
- `PROCESSING_DATE` = DAY_AFTER(USER_PROVIDED_DATE)

```bash
# Set dates in bash for queries
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)      # For yesterday's results
PROCESSING_DATE=$(date +%Y-%m-%d)               # Today (when processing ran)

# Or for pre-game check
GAME_DATE=$(date +%Y-%m-%d)                     # Today's games
PROCESSING_DATE=$(date +%Y-%m-%d)               # Today
```

**Critical**: Use `GAME_DATE` for game data queries, `PROCESSING_DATE` for processing status queries.

## Current Context & Timing Awareness

**First**: Determine current time and game schedule context
- What time is it now? (Pre-game ~5 PM ET vs Post-game ~6 AM ET next day)
- Are there games today? Check the schedule
- What data should exist by now? (Timing affects expectations)

**Key Timing Rules**:
- **Pre-game (5 PM ET)**: Betting data, game context, ML features should exist. Predictions may not exist yet (games haven't happened).
- **Post-game (6 AM ET)**: Everything including predictions should exist for yesterday's games.
- **Off-day**: No games scheduled is normal, not an error.

## Standard Validation Workflow

### Phase 0: Proactive Quota Check (NEW)

**IMPORTANT**: Check BigQuery quotas FIRST to prevent cascading failures.

```bash
# Check current quota usage for partition modifications
bq show --format=prettyjson nba-props-platform | grep -A 10 "quotaUsed"

# Or check recent quota errors in logs
gcloud logging read "resource.type=bigquery_resource AND protoPayload.status.message:quota" \
  --limit=10 --format="table(timestamp,protoPayload.status.message)"
```

**What to look for**:
- Partition modification quota: Should be < 5000/day (limit varies by project)
- Recent "Quota exceeded" errors in logs
- If quota issues detected → Mark as P1 CRITICAL and recommend batching writes

**Common cause**: `pipeline_logger` writing too many events to partitioned `run_history` table

### Phase 0.5: Orchestrator Health (CRITICAL)

**IMPORTANT**: Check orchestrator health BEFORE other validations. If ANY Phase 0.5 check fails, this is a P1 CRITICAL issue - STOP and report immediately.

**Why this matters**: Orchestrator failures can cause 2+ day silent data gaps. The orchestrator transitions data between phases (2→3, 3→4, 4→5) after all processors complete. If it fails, new data stops flowing even though scrapers keep running.

**What to check**:

#### Check 1: Missing Phase Logs

Verify all expected phase transitions happened yesterday.

**IMPORTANT**: This check handles gracefully when `phase_execution_log` table is empty or doesn't have data for the date.

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

# First check if the table has any data for this date
TABLE_CHECK=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as count
FROM nba_orchestration.phase_execution_log
WHERE game_date = DATE('${GAME_DATE}')" 2>&1)

if echo "$TABLE_CHECK" | grep -q "Not found"; then
    echo "INFO: phase_execution_log table does not exist yet"
    echo "This is expected for new deployments. Use alternative checks below."
else
    ROW_COUNT=$(echo "$TABLE_CHECK" | tail -1)
    if [ "$ROW_COUNT" = "0" ]; then
        echo "WARNING: No phase_execution_log entries for ${GAME_DATE}"
        echo "Possible causes:"
        echo "  - Orchestrators haven't run yet (check timing)"
        echo "  - Logging not enabled in orchestrators"
        echo "  - Cloud Functions failed before logging"
        echo ""
        echo "Fallback: Check Firestore completion records and processor_run_history instead"
    else
        # Table has data, run the full check
        bq query --use_legacy_sql=false "
WITH expected AS (
  SELECT 'phase2_to_phase3' as phase_name UNION ALL
  SELECT 'phase3_to_phase4' UNION ALL
  SELECT 'phase4_to_phase5'
),
actual AS (
  SELECT DISTINCT phase_name
  FROM nba_orchestration.phase_execution_log
  WHERE game_date = DATE('${GAME_DATE}')
)
SELECT e.phase_name,
  CASE WHEN a.phase_name IS NULL THEN 'MISSING' ELSE 'OK' END as status
FROM expected e LEFT JOIN actual a USING (phase_name)"
    fi
fi
```

**Fallback Check (if phase_execution_log is empty)**:

Use `processor_run_history` to verify phases ran:

```bash
bq query --use_legacy_sql=false "
SELECT
  phase,
  COUNT(DISTINCT processor_name) as processors_run,
  MIN(started_at) as first_run,
  MAX(completed_at) as last_complete
FROM nba_orchestration.processor_run_history
WHERE data_date = DATE('${GAME_DATE}')
  AND phase IN ('phase_3_analytics', 'phase_4_precompute', 'phase_5_predictions')
GROUP BY phase
ORDER BY phase" 2>/dev/null || echo "INFO: processor_run_history also unavailable"
```

**Expected**: All phases show 'OK'

**If MISSING**:
- 🔴 P1 CRITICAL: Orchestrator did not run or failed silently
- Impact: Data pipeline stalled, new data not flowing to downstream phases
- Action: Check Cloud Function logs for phase orchestrator errors

**If Table Empty/Missing**:
- Use Firestore completion tracking as fallback
- Check `phase2_completion`, `phase3_completion` documents
- Verify processor_run_history has entries

#### Check 2: Stalled Orchestrators

Check for orchestrators stuck in 'started' or 'running' state:

```bash
bq query --use_legacy_sql=false "
SELECT phase_name, game_date, start_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) as minutes_stalled,
  status
FROM nba_orchestration.phase_execution_log
WHERE status IN ('started', 'running')
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) > 30
ORDER BY minutes_stalled DESC"
```

**Expected**: Zero results (no stalled orchestrators)

**If stalled**:
- 🔴 P1 CRITICAL: Orchestrator started but never completed
- Threshold: >30 minutes in 'started' or 'running' state
- Impact: Downstream phases blocked, data not progressing
- Action: Check for timeout, deadlock, or Cloud Function timeout issues

#### Check 3: Phase Timing Gaps

Check for abnormal delays between phase completions:

```bash
bq query --use_legacy_sql=false "
WITH phase_times AS (
  SELECT game_date, phase_name, MAX(execution_timestamp) as completed_at
  FROM nba_orchestration.phase_execution_log
  WHERE status = 'complete'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date, phase_name
)
SELECT p1.game_date,
  p1.phase_name as from_phase,
  p2.phase_name as to_phase,
  TIMESTAMP_DIFF(p2.completed_at, p1.completed_at, MINUTE) as gap_minutes,
  CASE
    WHEN TIMESTAMP_DIFF(p2.completed_at, p1.completed_at, MINUTE) > 120 THEN '🔴 CRITICAL'
    WHEN TIMESTAMP_DIFF(p2.completed_at, p1.completed_at, MINUTE) > 60 THEN '🟡 WARNING'
    ELSE 'OK'
  END as status
FROM phase_times p1
JOIN phase_times p2 ON p1.game_date = p2.game_date
WHERE (p1.phase_name = 'phase2_to_phase3' AND p2.phase_name = 'phase3_to_phase4')
   OR (p1.phase_name = 'phase3_to_phase4' AND p2.phase_name = 'phase4_to_phase5')
HAVING gap_minutes > 60
ORDER BY p1.game_date DESC, gap_minutes DESC"
```

**Expected**: Zero results with gap_minutes > 60

**If gaps detected**:
- 🔴 CRITICAL (>120 min): Major orchestration failure
- 🟡 WARNING (60-120 min): Performance degradation
- Typical timing:
  - Phase 2→3: 5-10 minutes
  - Phase 3→4: 10-20 minutes (overnight mode)
  - Phase 4→5: 15-30 minutes
- Action: Investigate Cloud Function performance, check for processor deadlocks

**Firestore Completion State** (Optional Deep Dive):

If orchestrator issues detected, check Firestore completion tracking:

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime, timedelta
db = firestore.Client()

# Check yesterday's completion records
game_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
processing_date = datetime.now().strftime('%Y-%m-%d')

print(f"\nPhase 2 Completion ({game_date}):")
doc = db.collection('phase2_completion').document(game_date).get()
if doc.exists:
    data = doc.to_dict()
    print(f"  Triggered: {data.get('_triggered', False)}")
    print(f"  Trigger reason: {data.get('_trigger_reason', 'N/A')}")
    print(f"  Processors complete: {len([k for k in data.keys() if not k.startswith('_')])}/6")
else:
    print("  ❌ No completion record found")

print(f"\nPhase 3 Completion ({processing_date}):")
doc = db.collection('phase3_completion').document(processing_date).get()
if doc.exists:
    data = doc.to_dict()
    print(f"  Triggered: {data.get('_triggered', False)}")
    print(f"  Trigger reason: {data.get('_trigger_reason', 'N/A')}")
    print(f"  Processors complete: {len([k for k in data.keys() if not k.startswith('_')])}/5")
else:
    print("  ❌ No completion record found")
EOF
```

**Critical Alerts**:

If ANY Phase 0.5 check fails, send alert to critical error channel:

```bash
# Use the critical error Slack webhook
SLACK_WEBHOOK_URL_ERROR="<use env var from GCP Secret Manager>"

curl -X POST "$SLACK_WEBHOOK_URL_ERROR" \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "🚨 P1 CRITICAL: Orchestrator Health Check Failed",
    "blocks": [
      {
        "type": "section",
        "text": {
          "type": "mrkdwn",
          "text": "*Orchestrator Health Check Failed*\n\n*Issue:* [describe issue]\n*Impact:* Data pipeline stalled\n*Action Required:* Immediate investigation"
        }
      }
    ]
  }'
```

**Slack Webhook Configuration**:
- Primary alerts: `SLACK_WEBHOOK_URL` → #daily-orchestration
- Critical errors: `SLACK_WEBHOOK_URL_ERROR` → #app-error-alerts ⚠️ **Use this for Phase 0.5 failures**
- Warnings: `SLACK_WEBHOOK_URL_WARNING` → #nba-alerts

**If ALL Phase 0.5 checks pass**: Continue to Phase 1

**If ANY Phase 0.5 check fails**: STOP, report issue with P1 CRITICAL severity, do NOT continue to Phase 1

### Phase 1: Run Baseline Health Check

```bash
./bin/monitoring/daily_health_check.sh
```

Parse the output intelligently:
- What phases completed successfully?
- What phases failed or are incomplete?
- Are there any errors in recent logs?
- Is this a timing issue (too early) or a real failure?

### Phase 2: Run Main Validation Script

```bash
python scripts/validate_tonight_data.py
```

**Exit Code Interpretation**:
- `0` = All checks passed (no ISSUES)
- `1` = At least one ISSUE found (investigate)

**Classification System**:
- **ISSUES**: Hard failures (ERROR/CRITICAL severity) - block deployment
- **WARNINGS**: Non-blocking concerns - investigate but don't block
- **STATS**: Metrics for monitoring - just note

### Phase 3: Run Data Quality Spot Checks

```bash
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate
```

**Accuracy Threshold**: ≥95% expected
- **100%**: Excellent, data quality is perfect
- **95-99%**: Good, minor issues but acceptable
- **90-94%**: WARNING - investigate specific failures
- **<90%**: CRITICAL - data quality issues need immediate attention

**Common Failure Patterns**:
- Rolling avg failures: Usually cache date filter bugs (`<=` vs `<`)
- Usage rate failures: Missing team stats or join issues
- Specific players failing: Check if known issues (Mo Bamba, Josh Giddey historically)

### Phase 3B: Player Game Coverage Spot Check (NEW)

Check that all players who played yesterday have analytics records:

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
-- Find players who played (have boxscore minutes) but missing from analytics
WITH boxscore_players AS (
    SELECT DISTINCT player_lookup, game_date, team_abbr, minutes
    FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
    WHERE game_date = DATE('${GAME_DATE}')
      AND minutes NOT IN ('00', '0')
),
analytics_players AS (
    SELECT DISTINCT player_lookup, game_date
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date = DATE('${GAME_DATE}')
)
SELECT
    b.player_lookup,
    b.team_abbr,
    b.minutes,
    'ERROR: In boxscore but missing from analytics' as status
FROM boxscore_players b
LEFT JOIN analytics_players a ON b.player_lookup = a.player_lookup AND b.game_date = a.game_date
WHERE a.player_lookup IS NULL
ORDER BY b.team_abbr, b.player_lookup"
```

**Expected**: Zero results (all players who played should have analytics records)

**If issues found**:
- Check if player was recently traded (name lookup mismatch)
- Check if player is new call-up (not in registry)
- Run `/spot-check-player <name>` for deep investigation

**Related skills for deeper investigation**:
- `/spot-check-player <name>` - Deep dive on one player
- `/spot-check-date <date>` - Check all players for a date
- `/spot-check-gaps` - System-wide audit

### Phase 3C: Cross-Source Reconciliation (NEW)

Check data consistency between NBA.com (official source) and BDL stats for yesterday:

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
-- Summary of reconciliation health
SELECT
  health_status,
  COUNT(*) as player_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
FROM \`nba-props-platform.nba_monitoring.source_reconciliation_daily\`
GROUP BY health_status
ORDER BY FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH')
"

# If CRITICAL or WARNING found, get details
bq query --use_legacy_sql=false "
SELECT
  player_name,
  team_abbr,
  health_status,
  discrepancy_summary,
  stat_comparison
FROM \`nba-props-platform.nba_monitoring.source_reconciliation_daily\`
WHERE health_status IN ('CRITICAL', 'WARNING')
ORDER BY health_status, point_diff DESC
LIMIT 20
"
```

**Expected Results**:
- **MATCH**: ≥95% of players (stats identical across sources)
- **MINOR_DIFF**: <5% (acceptable differences of 1-2 points)
- **WARNING**: <1% (assists/rebounds difference >2)
- **CRITICAL**: 0% (point difference >2)

**Health Status Levels**:
- **MATCH**: Stats match exactly (expected behavior)
- **MINOR_DIFF**: Difference of 1-2 points in any stat (acceptable)
- **WARNING**: Difference >2 in assists/rebounds (investigate)
- **CRITICAL**: Difference >2 points (immediate investigation)

**If CRITICAL issues found**:
1. Check which source is correct by spot-checking game footage/play-by-play
2. Determine if systematic issue (all games) or specific team/game
3. Check if NBA.com or BDL had data correction/update
4. Remember: **NBA.com is source of truth** when discrepancies exist
5. Consider if issue affects prop settlement (points more critical than assists)

**If WARNING issues found**:
1. Review assist/rebound scoring differences (judgment calls by official scorers)
2. Check if pattern exists (specific teams, arenas, scorers)
3. Document but likely not blocking issue

**If match rate <95%**:
1. Check if one source had delayed/incomplete data
2. Verify both scrapers ran successfully overnight
3. Check for systematic player name mapping issues
4. Review recent player_lookup normalization changes

**Source Priority**:
1. **NBA.com** - Official, authoritative (source of truth for disputes)
2. **BDL** - Primary real-time source (faster updates)
3. Use reconciliation to validate BDL reliability

**Related Infrastructure**:
- View: `nba_orchestration.bdl_quality_trend` (BDL quality trend with readiness indicator)
- Cloud Function: `data-quality-alerts` (runs daily at 7 PM ET, stores metrics)
- Table: `nba_orchestration.source_discrepancies` (historical tracking)

**BDL Quality Trend Check** (Session 41 addition):
```bash
# Check BDL quality trend and readiness status
bq query --use_legacy_sql=false "
SELECT
  game_date,
  total_players,
  bdl_coverage,
  coverage_pct,
  major_discrepancies,
  major_discrepancy_pct,
  rolling_7d_major_pct,
  bdl_readiness
FROM nba_orchestration.bdl_quality_trend
ORDER BY game_date DESC
LIMIT 7
"
```

**BDL Readiness Levels**:
- **READY_TO_ENABLE**: <5% major discrepancies for 7 consecutive days (safe to re-enable)
- **IMPROVING**: <10% major discrepancies (getting better, keep monitoring)
- **NOT_READY**: >10% major discrepancies (keep BDL disabled)

**Note**: BDL is currently DISABLED as a backup source due to data quality issues.
Monitor this view to determine when it's safe to re-enable by setting `USE_BDL_DATA = True` in `player_game_summary_processor.py`.

### Phase 4: Check Phase Completion Status

**Phase 3 Analytics (Firestore)**:
```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime
import os
db = firestore.Client()
# Use PROCESSING_DATE for completion status (processing happens after midnight)
processing_date = os.environ.get('PROCESSING_DATE', datetime.now().strftime('%Y-%m-%d'))
doc = db.collection('phase3_completion').document(processing_date).get()
if doc.exists:
    data = doc.to_dict()
    print(f"Phase 3 Status for {processing_date}: {data}")
else:
    print(f"No Phase 3 completion record for {processing_date}")
EOF
```

**Phase 4 ML Features (BigQuery)**:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as features, COUNT(DISTINCT game_id) as games
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = DATE('${GAME_DATE}')"
```

**Phase 5 Predictions (BigQuery)**:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT game_id) as games
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('${GAME_DATE}') AND is_active = TRUE"
```

### Phase 5: Investigate Any Issues Found

**If validation script reports ISSUES**:
1. Read the specific error messages
2. Classify by type (missing data, quality issue, timing issue, source blocked)
3. Determine root cause (which phase failed?)
4. Check recent logs for that phase
5. Consult known issues list below
6. Provide specific remediation steps

**If spot checks fail**:
1. Which specific check failed? (rolling_avg vs usage_rate)
2. What players failed? (Check if known issue)
3. Run manual BigQuery validation on one failing sample
4. Determine if cache issue, calculation bug, or data corruption
5. Recommend regeneration or code fix

**If phase completion incomplete**:
1. Which processor(s) didn't complete?
2. Check Cloud Run logs for that processor
3. Look for errors (ModuleNotFoundError, timeout, quota exceeded)
4. Determine if can retry or needs code fix

## Yesterday's Results Validation Workflow

When user selects "Yesterday's results (post-game check)", follow this prioritized workflow:

### Priority 1: Critical Checks (Always Run)

#### 1A. Box Scores Complete

Verify all games from yesterday have complete box score data:

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_id) as games_with_data,
  COUNT(*) as player_records,
  COUNTIF(points IS NOT NULL) as has_points,
  COUNTIF(minutes_played IS NOT NULL) as has_minutes
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')"
```

**Expected**:
- `games_with_data` matches scheduled games for that date
- `player_records` ~= games × 25-30 players per game
- `has_points` and `has_minutes` = 100% of records

#### 1A2. Minutes Played Coverage Check (CRITICAL)

**IMPORTANT**: This check validates that minutes_played field is populated for most players. Coverage below 90% is a CRITICAL issue indicating data extraction failures.

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_players,
  COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) as has_minutes,
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) / NULLIF(COUNT(*), 0), 1) as minutes_coverage_pct,
  CASE
    WHEN ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) / NULLIF(COUNT(*), 0), 1) >= 90 THEN 'OK'
    WHEN ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) / NULLIF(COUNT(*), 0), 1) >= 80 THEN 'WARNING'
    ELSE 'CRITICAL'
  END as status
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')"
```

**Thresholds**:
- **≥90%**: OK - Expected coverage level
- **80-89%**: WARNING - Some data gaps, investigate
- **<80%**: CRITICAL - Major data extraction failure

**Severity Classification**:
- Coverage 63% → **P1 CRITICAL** - Stop and investigate immediately
- Coverage 85% → **P2 WARNING** - Investigate but not blocking

**If CRITICAL**:
1. Check if BDL scraper ran successfully: `bq query "SELECT * FROM nba_orchestration.scraper_execution_log WHERE scraper_name='bdl_player_boxscores' AND DATE(started_at) = CURRENT_DATE()"`
2. Check if minutes field was extracted: `bq query "SELECT minutes, COUNT(*) FROM nba_raw.bdl_player_boxscores WHERE game_date = '${GAME_DATE}' GROUP BY 1"`
3. Verify BDL API response contains minutes data
4. Check for field extraction bugs in the processor

**Root Cause Investigation**:
- If raw data has minutes but analytics doesn't → Processor bug
- If raw data missing minutes → Scraper extraction bug
- If API not returning minutes → Source data issue

#### 1B. Prediction Grading Complete

Verify predictions were graded against actual results:

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNTIF(actual_value IS NOT NULL) as graded,
  COUNTIF(actual_value IS NULL) as ungraded,
  ROUND(COUNTIF(actual_value IS NOT NULL) * 100.0 / COUNT(*), 1) as graded_pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = DATE('${GAME_DATE}')
  AND is_active = TRUE"
```

**Expected**:
- `graded_pct` = 100% (all predictions should have actual values)
- If `ungraded` > 0, check if games were postponed or data source blocked

#### 1C. Scraper Runs Completed

Verify box score scrapers ran successfully (they run after midnight).

**IMPORTANT**: The `scraper_run_history` table may not exist. This check gracefully falls back to checking raw data tables directly.

```bash
PROCESSING_DATE=$(date +%Y-%m-%d)
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

# Try scraper_run_history first
SCRAPER_CHECK=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT
  scraper_name,
  status,
  records_processed,
  completed_at
FROM \`nba-props-platform.nba_orchestration.scraper_run_history\`
WHERE DATE(started_at) = DATE('${PROCESSING_DATE}')
  AND scraper_name IN ('nbac_gamebook', 'bdl_player_boxscores')
ORDER BY completed_at DESC" 2>&1)

if echo "$SCRAPER_CHECK" | grep -q "Not found"; then
    echo "INFO: scraper_run_history table does not exist"
    echo "Using fallback: checking raw data tables directly"
    echo ""

    # Fallback: Check raw data tables have data
    echo "=== Fallback: Raw Data Verification ==="

    # Check BDL boxscores
    BDL_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT COUNT(*) FROM nba_raw.bdl_player_boxscores
    WHERE game_date = DATE('${GAME_DATE}')" 2>/dev/null | tail -1)
    echo "bdl_player_boxscores for ${GAME_DATE}: ${BDL_COUNT:-0} records"

    # Check NBAC gamebook
    NBAC_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT COUNT(*) FROM nba_raw.nbac_gamebook_player_boxscores
    WHERE game_date = DATE('${GAME_DATE}')" 2>/dev/null | tail -1)
    echo "nbac_gamebook_player_boxscores for ${GAME_DATE}: ${NBAC_COUNT:-0} records"

    # Determine status based on data presence
    if [ "${BDL_COUNT:-0}" -gt 0 ] && [ "${NBAC_COUNT:-0}" -gt 0 ]; then
        echo ""
        echo "STATUS: OK - Both data sources have records (scrapers likely ran)"
    elif [ "${BDL_COUNT:-0}" -gt 0 ] || [ "${NBAC_COUNT:-0}" -gt 0 ]; then
        echo ""
        echo "STATUS: WARNING - Only one data source has records"
    else
        echo ""
        echo "STATUS: CRITICAL - No raw data found for ${GAME_DATE}"
    fi
else
    echo "$SCRAPER_CHECK"
fi
```

**Expected**: Both scrapers show `status = 'success'`, OR fallback shows both raw tables have records

**Fallback Logic**:
- If `scraper_run_history` doesn't exist → Check raw data tables directly
- BDL records > 0 AND NBAC records > 0 → Scrapers ran successfully
- Only one source has data → WARNING, investigate
- No data in either → CRITICAL, scrapers failed

### Priority 2: Pipeline Completeness (Run if P1 passes)

#### 2A. Analytics Generated

```bash
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as records
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')
UNION ALL
SELECT
  'team_offense_game_summary',
  COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')"
```

**Expected**:
- `player_game_summary`: ~200-300 records per night (varies by games)
- `team_offense_game_summary`: 2 × number of games (home + away)

#### 2B. Phase 3 Completion Status (MUST BE 5/5)

Check that Phase 3 processors completed (they run after midnight, so check today's date).

**CRITICAL**: Phase 3 has **5 expected processors**. Anything less than 5/5 is a WARNING or CRITICAL.

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime
import sys

EXPECTED_PROCESSORS = 5  # Phase 3 has 5 processors
EXPECTED_PROCESSOR_NAMES = [
    'player_game_summary',
    'team_offense_game_summary',
    'team_defense_game_summary',
    'upcoming_player_game_context',
    'upcoming_team_game_context'
]

db = firestore.Client()
# Phase 3 runs after midnight, so check TODAY's completion record
processing_date = datetime.now().strftime('%Y-%m-%d')
doc = db.collection('phase3_completion').document(processing_date).get()

if doc.exists:
    data = doc.to_dict()
    # Count completed processors (exclude metadata fields starting with _)
    completed = [k for k in data.keys() if not k.startswith('_')]
    completed_count = len(completed)
    triggered = data.get('_triggered', False)

    print(f"Phase 3 Status for {processing_date}:")
    print(f"  Processors complete: {completed_count}/{EXPECTED_PROCESSORS}")
    print(f"  Phase 4 triggered: {triggered}")

    # Show completed processors
    for proc in completed:
        status_info = data.get(proc, {})
        status = status_info.get('status', 'unknown') if isinstance(status_info, dict) else str(status_info)
        print(f"    - {proc}: {status}")

    # Check for missing processors
    missing = set(EXPECTED_PROCESSOR_NAMES) - set(completed)
    if missing:
        print(f"\n  MISSING PROCESSORS: {', '.join(missing)}")

    # Severity classification
    if completed_count < EXPECTED_PROCESSORS:
        if completed_count <= 2:
            print(f"\n  STATUS: CRITICAL - Only {completed_count}/{EXPECTED_PROCESSORS} processors complete")
            sys.exit(1)
        else:
            print(f"\n  STATUS: WARNING - {completed_count}/{EXPECTED_PROCESSORS} processors complete")
    else:
        print(f"\n  STATUS: OK - All {EXPECTED_PROCESSORS} processors complete")
else:
    print(f"No Phase 3 completion record for {processing_date}")
    print("  STATUS: CRITICAL - No completion record found")
    sys.exit(1)
EOF
```

**Expected**: **5/5 processors complete** and `_triggered = True`

**Severity Thresholds**:
- **5/5 complete**: OK
- **3-4/5 complete**: WARNING - Phase 4 may have incomplete data
- **0-2/5 complete**: CRITICAL - Major pipeline failure

**If incomplete (e.g., 2/5)**:
1. Check which processors are missing from the list
2. Check Cloud Run logs for those processors: `gcloud run services logs read nba-phase3-analytics-processors --limit=50`
3. Look for errors: timeout, quota exceeded, ModuleNotFoundError
4. If processors failed, check if they need manual retry

#### 2C. Cache Updated

Verify player_daily_cache was refreshed (needed for today's predictions):

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT player_lookup) as players_cached,
  MAX(updated_at) as last_update
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date = DATE('${GAME_DATE}')"
```

**Expected**: `last_update` should be within last 12 hours

### Priority 2D: BigDataBall Coverage Monitoring (NEW - Session 53)

Check BDB play-by-play data coverage for shot zone analytics:

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

echo "=== BDB Coverage Check ==="
bq query --use_legacy_sql=false "
WITH schedule AS (
  SELECT game_date, game_id
  FROM nba_reference.nba_schedule
  WHERE game_date = DATE('${GAME_DATE}')
),
bdb_games AS (
  SELECT DISTINCT game_date, LPAD(CAST(bdb_game_id AS STRING), 10, '0') as bdb_game_id
  FROM nba_raw.bigdataball_play_by_play
  WHERE game_date = DATE('${GAME_DATE}')
)
SELECT
  s.game_date,
  COUNT(DISTINCT s.game_id) as scheduled,
  COUNT(DISTINCT b.bdb_game_id) as bdb_has,
  ROUND(100.0 * COUNT(DISTINCT b.bdb_game_id) / NULLIF(COUNT(DISTINCT s.game_id), 0), 0) as coverage_pct,
  CASE
    WHEN ROUND(100.0 * COUNT(DISTINCT b.bdb_game_id) / NULLIF(COUNT(DISTINCT s.game_id), 0), 0) >= 90 THEN '✅ OK'
    WHEN ROUND(100.0 * COUNT(DISTINCT b.bdb_game_id) / NULLIF(COUNT(DISTINCT s.game_id), 0), 0) >= 50 THEN '🟡 WARNING'
    ELSE '🔴 CRITICAL'
  END as status
FROM schedule s
LEFT JOIN bdb_games b ON s.game_date = b.game_date AND s.game_id = b.bdb_game_id
GROUP BY s.game_date"
```

**Expected**: Coverage ≥90%

**Thresholds**:
- **≥90%**: OK - Normal BDB coverage
- **50-89%**: WARNING - Partial BDB data, shot zones may be incomplete
- **<50%**: CRITICAL - BDB outage, investigate immediately

**If coverage is low**:
1. Check pending_bdb_games table: `bq query "SELECT COUNT(*) FROM nba_orchestration.pending_bdb_games WHERE status = 'pending_bdb'"`
2. Check BDB scraper status in scraper service logs
3. Run BDB retry processor: `PYTHONPATH="$PWD" .venv/bin/python bin/monitoring/bdb_retry_processor.py`
4. Reference: Session 53 BDB investigation found Jan 17-24 outage

**BDB Retry System Status**:
```bash
bq query --use_legacy_sql=false "
SELECT
  status,
  COUNT(*) as games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM nba_orchestration.pending_bdb_games
GROUP BY status
ORDER BY status"
```

**BDB Coverage Trend (last 7 days)**:
```bash
bq query --use_legacy_sql=false "
WITH schedule AS (
  SELECT game_date, game_id
  FROM nba_reference.nba_schedule
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND game_date < CURRENT_DATE()
),
bdb_games AS (
  SELECT DISTINCT game_date, LPAD(CAST(bdb_game_id AS STRING), 10, '0') as bdb_game_id
  FROM nba_raw.bigdataball_play_by_play
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  s.game_date,
  COUNT(DISTINCT s.game_id) as scheduled,
  COUNT(DISTINCT b.bdb_game_id) as bdb_has,
  ROUND(100.0 * COUNT(DISTINCT b.bdb_game_id) / NULLIF(COUNT(DISTINCT s.game_id), 0), 0) as pct
FROM schedule s
LEFT JOIN bdb_games b ON s.game_date = b.game_date AND s.game_id = b.bdb_game_id
GROUP BY s.game_date
ORDER BY s.game_date DESC"
```

**Known Issue**: BDB had an outage Jan 17-24, 2026 with 0-57% coverage. Games from that period have been marked as failed in pending_bdb_games. Current coverage (Jan 25+) is 100%.

### Priority 2E: Scraped Data Coverage (Session 60)

Quick check for raw odds data gaps in the last 7 days:

```bash
bq query --use_legacy_sql=false "
-- Quick scraped data coverage check (last 7 days)
WITH schedule AS (
  SELECT game_date, COUNT(*) as games
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND game_date < CURRENT_DATE()
    AND game_status_text = 'Final'
  GROUP BY 1
),
game_lines AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games_with_lines
  FROM \`nba-props-platform.nba_raw.odds_api_game_lines\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND market_key = 'spreads'
  GROUP BY 1
),
player_props AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as players_with_props
  FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1
)
SELECT
  s.game_date,
  s.games as scheduled,
  COALESCE(gl.games_with_lines, 0) as game_lines,
  COALESCE(pp.players_with_props, 0) as player_props,
  CASE
    WHEN COALESCE(gl.games_with_lines, 0) = 0 THEN '🔴 MISSING LINES'
    WHEN COALESCE(gl.games_with_lines, 0) < s.games * 0.9 THEN '🟡 PARTIAL LINES'
    ELSE '✅'
  END as lines_status,
  CASE
    WHEN COALESCE(pp.players_with_props, 0) = 0 THEN '🔴 MISSING PROPS'
    WHEN COALESCE(pp.players_with_props, 0) < 200 THEN '🟡 LOW PROPS'
    ELSE '✅'
  END as props_status
FROM schedule s
LEFT JOIN game_lines gl ON s.game_date = gl.game_date
LEFT JOIN player_props pp ON s.game_date = pp.game_date
ORDER BY s.game_date DESC"
```

**Expected**: All dates show ✅ for both lines and props

**Thresholds**:
- **Game lines**: ≥90% of scheduled games should have spreads
- **Player props**: ≥200 players per game day expected

**If gaps found**:
1. Run `/validate-scraped-data` for full analysis (checks GCS vs BigQuery)
2. Determine if data exists in GCS but wasn't processed → run processor
3. Determine if data needs scraping from historical API → run backfill scraper

**Note**: This is a quick check. For historical gap analysis or determining if gaps need scraping vs processing, use `/validate-scraped-data`.

### Priority 2F: Feature Store Vegas Line Coverage (Session 62 - CRITICAL)

Check that Vegas line feature is populated in the feature store. Low coverage (<80%) directly causes hit rate degradation.

```bash
bq query --use_legacy_sql=false "
-- Feature Store Vegas Line Coverage Check
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct,
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as days,
  CASE
    WHEN ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) >= 80 THEN '✅ OK'
    WHEN ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) >= 50 THEN '🟡 WARNING'
    ELSE '🔴 CRITICAL'
  END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33"
```

**Thresholds**:
- **≥80%**: OK - Normal coverage (baseline is 99%+ from last season)
- **50-79%**: WARNING - Possible data extraction issue
- **<50%**: CRITICAL - Feature store likely generated in backfill mode without betting data join

**If CRITICAL or WARNING**:
1. Check if backfill mode was used without the Session 62 fix
2. Compare to Phase 3 coverage: `SELECT ROUND(100.0 * COUNTIF(current_points_line > 0) / COUNT(*), 1) FROM nba_analytics.upcoming_player_game_context WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)`
3. Run `/validate-feature-drift` for detailed analysis
4. Consider re-running feature store backfill with fixed code

**Root Cause (Session 62 discovery)**:
Backfill mode includes ALL players (300-500/day) but previously didn't join with betting tables.
Production mode only includes expected players (130-200/day) who mostly have Vegas lines.

### Priority 2G: Model Drift Monitoring (Session 28)

#### Weekly Hit Rate Trend

Check model performance over the past 4 weeks to detect drift:

```bash
bq query --use_legacy_sql=false "
-- Weekly hit rate check for model drift detection
SELECT
  DATE_TRUNC(game_date, WEEK) as week_start,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias,
  CASE
    WHEN ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) < 55 THEN '🔴 CRITICAL'
    WHEN ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) < 60 THEN '🟡 WARNING'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC"
```

**Expected**: Hit rate ≥60% each week

**Alert Thresholds**:
- **≥60%**: OK - Normal performance
- **55-59%**: WARNING - Monitor closely
- **<55%**: CRITICAL - Model drift detected, investigate

**If 2+ consecutive weeks < 55%**:
1. 🔴 P1 CRITICAL: Model has degraded significantly
2. Check root cause analysis in `docs/08-projects/current/catboost-v8-performance-analysis/MODEL-DEGRADATION-ROOT-CAUSE-ANALYSIS.md`
3. Consider retraining with recency weighting
4. Review player tier breakdown (below)

#### Player Tier Performance Breakdown

Check if degradation is uniform or tier-specific:

```bash
bq query --use_legacy_sql=false "
-- Performance by player scoring tier (last 4 weeks)
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  CASE
    WHEN actual_points >= 25 THEN '1_stars_25+'
    WHEN actual_points >= 15 THEN '2_starters_15-25'
    WHEN actual_points >= 5 THEN '3_rotation_5-15'
    ELSE '4_bench_<5'
  END as tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 2"
```

**What to look for**:
- **Star tier (25+) hit rate < 60%**: Model under-predicting breakout performances
- **Bench tier bias > +5**: Model over-predicting low-minute players
- **Tier divergence > 20%**: Stars at 55%, bench at 75% = different failure modes

**If tier-specific issues detected**:
- Stars under-predicted: Add player trajectory features (pts_slope_10g, breakout_flag)
- Bench over-predicted: Reduce model confidence for low-usage players
- Reference: `MODEL-DEGRADATION-ROOT-CAUSE-ANALYSIS.md` for detailed analysis

#### Model vs Vegas Comparison

Check if our edge over Vegas is eroding:

```bash
bq query --use_legacy_sql=false "
-- Our MAE vs Vegas MAE (last 4 weeks)
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as our_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)), 2) as our_edge
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND line_value IS NOT NULL
  AND prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC"
```

**Expected**: `our_edge` > 0 (we're more accurate than Vegas)

**Alert if**:
- `our_edge` < 0 for 2+ consecutive weeks → Model no longer competitive
- `our_edge` trending downward → Model drift in progress

### Priority 3: Quality Verification (Run if issues suspected)

#### 3A. Spot Check Accuracy

```bash
python scripts/spot_check_data_accuracy.py \
  --start-date ${GAME_DATE} \
  --end-date ${GAME_DATE} \
  --samples 10 \
  --checks rolling_avg,usage_rate
```

**Expected**: ≥95% accuracy

#### 3A2. Golden Dataset Verification (Added 2026-01-27)

Verify rolling averages against manually verified golden dataset records:

```bash
python scripts/verify_golden_dataset.py
```

**Purpose**:
- Verifies calculation correctness against known-good values
- Catches regression in rolling average calculation logic
- Higher confidence than spot checks (uses manually verified expected values)

**Exit Code Interpretation**:
- `0` = All golden dataset verifications passed
- `1` = At least one verification failed or error occurred

**Accuracy Threshold**: 100% expected (these are manually verified)
- **100%**: PASS - All golden dataset records match expected values
- **<100%**: FAIL - Calculation logic error or data corruption

**When to run**:
- After cache regeneration (to verify correctness)
- Weekly as part of comprehensive validation
- When spot check accuracy is borderline (90-95%)
- After code changes to stats_aggregator.py or player_daily_cache logic

**Verbose mode** (for investigation):
```bash
python scripts/verify_golden_dataset.py --verbose
```

**Note**: Golden dataset is small (10-20 player-date combinations) but high-confidence. If this fails, it's a strong signal of calculation issues.

#### 3B. Usage Rate Anomaly Check (Added 2026-01-27)

Check for invalid usage_rate values that indicate partial game data issues:

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  game_id,
  usage_rate,
  CASE
    WHEN usage_rate > 100 THEN 'INVALID (>100%)'
    WHEN usage_rate > 50 THEN 'SUSPICIOUS (>50%)'
    ELSE 'OK'
  END as status
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')
  AND usage_rate > 50
ORDER BY usage_rate DESC
LIMIT 20"
```

**Expected**: Zero records with usage_rate > 100% (indicates partial team data was processed)
**Investigate if**: Any usage_rate > 50% (typical max is ~40-45% for high-usage players)

#### 3C. Partial Game Detection (Added 2026-01-27)

Check for games that may have incomplete data:

```bash
bq query --use_legacy_sql=false "
SELECT
  game_id,
  team_abbr,
  SUM(CAST(minutes_played AS FLOAT64)) as total_minutes,
  COUNT(*) as players,
  CASE WHEN SUM(CAST(minutes_played AS FLOAT64)) < 200 THEN 'PARTIAL' ELSE 'OK' END as status
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')
  AND is_active = TRUE
GROUP BY game_id, team_abbr
HAVING SUM(CAST(minutes_played AS FLOAT64)) < 200
ORDER BY total_minutes ASC"
```

**Expected**: Zero partial games (all teams should have ~240 total minutes per game)
**Note**: Total team minutes < 200 indicates incomplete data

#### 3D. Phase Transition SLA Check (Added 2026-01-27)

Verify Phase 4 was auto-triggered by orchestrator (not manual):

```bash
bq query --use_legacy_sql=false "
SELECT
  data_date,
  trigger_source,
  COUNT(*) as runs,
  MIN(started_at) as first_run
FROM \`nba-props-platform.nba_orchestration.processor_run_history\`
WHERE phase = 'phase_4_precompute'
  AND data_date = DATE('${GAME_DATE}')
GROUP BY data_date, trigger_source"
```

**Expected**: `trigger_source = 'orchestrator'` (not 'manual')
**Issue if**: All Phase 4 runs show 'manual' - indicates Pub/Sub trigger not working

#### 3E. Prediction Accuracy Summary

```bash
bq query --use_legacy_sql=false "
SELECT
  prop_type,
  COUNT(*) as predictions,
  COUNTIF(
    (predicted_value > line_value AND actual_value > line_value) OR
    (predicted_value < line_value AND actual_value < line_value)
  ) as correct,
  ROUND(COUNTIF(
    (predicted_value > line_value AND actual_value > line_value) OR
    (predicted_value < line_value AND actual_value < line_value)
  ) * 100.0 / COUNT(*), 1) as accuracy_pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = DATE('${GAME_DATE}')
  AND is_active = TRUE
  AND actual_value IS NOT NULL
GROUP BY prop_type
ORDER BY predictions DESC"
```

**Note**: This is informational, not pass/fail. Prediction accuracy varies.

#### 3F. Deployment Drift Detection (Added 2026-01-28)

**PURPOSE**: Detect when data was processed BEFORE the latest code deployment. This helps identify cases where:
- A bug fix was deployed but data was already processed with the buggy code
- Data may need reprocessing with the corrected code

```bash
# Get deployment times for key services
echo "=== Service Deployment Times ==="

# Phase 3 Analytics Processors
PHASE3_DEPLOY=$(gcloud run revisions list --service="nba-phase3-analytics-processors" \
  --region=us-west2 --limit=1 --format='value(metadata.creationTimestamp)' 2>/dev/null)
echo "Phase 3 Processors deployed: ${PHASE3_DEPLOY:-UNKNOWN}"

# Phase 4 Precompute Processors
PHASE4_DEPLOY=$(gcloud run revisions list --service="nba-phase4-precompute-processors" \
  --region=us-west2 --limit=1 --format='value(metadata.creationTimestamp)' 2>/dev/null)
echo "Phase 4 Processors deployed: ${PHASE4_DEPLOY:-UNKNOWN}"

# Prediction Worker
PRED_DEPLOY=$(gcloud run revisions list --service="prediction-worker" \
  --region=us-west2 --limit=1 --format='value(metadata.creationTimestamp)' 2>/dev/null)
echo "Prediction Worker deployed: ${PRED_DEPLOY:-UNKNOWN}"

echo ""
echo "=== Data Processing Times ==="

# Get latest data processing time for yesterday's data
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name,
  MAX(processed_at) as last_processed
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')
  AND processed_at IS NOT NULL
UNION ALL
SELECT
  'player_daily_cache',
  MAX(updated_at)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date = DATE('${GAME_DATE}')" 2>/dev/null

echo ""
echo "=== Full Drift Check ==="
./bin/check-deployment-drift.sh 2>/dev/null || echo "Drift check script not available - run manually"
```

**Interpretation**:
- If `last_processed < deployment_time` → Data was processed with NEW code (good)
- If `last_processed > deployment_time` → Data was processed BEFORE deployment (may need reprocessing)

**If Drift Detected**:
1. Compare the bug fix commit date vs data processing date
2. Determine if the bug affected the data
3. If affected, consider reprocessing: `./bin/maintenance/reprocess_date.sh ${GAME_DATE}`
4. Document in handoff which dates may need reprocessing

**Common Scenario**:
- Bug fix deployed at 10:00 AM
- Data was processed at 7:00 AM (before fix)
- Resolution: Reprocess data with the fixed code

**When to Run**:
- After deploying bug fixes
- When investigating data quality issues
- As part of comprehensive validation

## Investigation Tools

**Cloud Run Logs** (if needed):
```bash
# Phase 3 logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50

# Phase 4 logs
gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 --limit=50
```

**Manual BigQuery Validation** (if spot checks fail):
```bash
bq query --use_legacy_sql=false "
-- Example: Validate rolling average for specific player
SELECT
  game_date,
  player_lookup,
  points,
  points_avg_last_5
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'lebronjames'
  AND game_date >= '2026-01-01'
ORDER BY game_date DESC
LIMIT 10"
```

## BigQuery Schema Reference (NEW)

**Key Tables and Fields** - Use these for manual validation queries:

### `nba_analytics.player_game_summary`
```
Key fields:
- player_lookup (STRING) - NOT player_name! (e.g., 'lebronjames')
- game_id (STRING)
- game_date (DATE)
- points, assists, rebounds (INT64)
- minutes_played (INT64) - decimal format, NOT "MM:SS"
- usage_rate (FLOAT64) - can be NULL if team stats missing
- points_avg_last_5, points_avg_last_10 (FLOAT64)

Data quality fields (added 2026-01-27):
- is_dnp (BOOLEAN) - Did Not Play flag
- dnp_reason (STRING) - Raw DNP reason text
- is_partial_game_data (BOOLEAN) - TRUE if incomplete data at processing
- game_completeness_pct (NUMERIC) - % of expected data available
- usage_rate_valid (BOOLEAN) - FALSE if usage_rate > 50% or team data incomplete
- usage_rate_anomaly_reason (STRING) - 'partial_team_data', 'exceeds_max'
```

### `nba_precompute.player_daily_cache`
```
Key fields:
- player_lookup (STRING)
- cache_date (DATE) - the "as of" date for cached features
- game_date (DATE) - upcoming game date
- points_avg_last_5, points_avg_last_10 (FLOAT64)
- minutes_avg_last_10 (FLOAT64)
```

### `nba_predictions.ml_feature_store_v2`
```
Key fields:
- player_lookup (STRING)
- game_id (STRING)
- game_date (DATE)
- features (ARRAY<FLOAT64>) - ML feature vector
```

### `nba_analytics.team_offense_game_summary`
```
Key fields:
- game_id (STRING)
- team_abbr (STRING)
- game_date (DATE)
- fg_attempts, ft_attempts, turnovers (INT64)
- possessions (INT64) - needed for usage_rate calculation
```

**Common Schema Gotchas**:
- Use `player_lookup` NOT `player_name` (lookup is normalized: 'lebronjames' not 'LeBron James')
- `cache_date` in player_daily_cache is the "as of" date (game_date - 1)
- `minutes_played` is INT64 decimal (32), NOT string "32:00"
- `usage_rate` can be NULL if team_offense_game_summary is missing

## Known Issues & Context

### Known Data Quality Issues

1. **Phase 4 SQLAlchemy Missing**
   - Symptom: `ModuleNotFoundError: No module named 'sqlalchemy'`
   - Impact: ML feature generation fails
   - Fix: Deploy updated requirements.txt

2. **Phase 3 Stale Dependency False Positives**
   - Symptom: "Stale dependencies" error but data looks fresh
   - Impact: False failures in processor completion
   - Fix: Review dependency threshold logic (may be too strict)

3. **Low Prediction Coverage**
   - Symptom: Expected ~90%, seeing 32-48%
   - Context: If early season OR source-blocked games, this is normal
   - Fix: Only flag if mid-season AND no source blocks

4. **Rolling Average Cache Bug**
   - Symptom: Spot checks failing for rolling averages
   - Known players: Mo Bamba, Josh Giddey, Justin Champagnie
   - Root cause: Fixed 2026-01-26 (cache date filter bug)
   - Action: If failures still occurring, regenerate cache

5. **Betting Workflow Timing**
   - Symptom: No betting data at 5 PM ET
   - Expected: Workflow starts at 8 AM ET (not 1 PM)
   - Fix: Check workflow schedule in orchestrator

6. **PlayerGameSummaryProcessor Registry Bug** ✅ FIXED 2026-01-26
   - Symptom: `'PlayerGameSummaryProcessor' object has no attribute 'registry'`
   - Impact: Phase 3 processor fails during finalize()
   - Root cause: Code referenced `self.registry` instead of `self.registry_handler`
   - Fix: Fixed in player_game_summary_processor.py (lines 1066, 1067, 1667)
   - Status: Deployed 2026-01-26

7. **BigQuery Quota Exceeded** ⚠️ WATCH FOR THIS
   - Symptom: `403 Quota exceeded: Number of partition modifications`
   - Impact: Blocks all Phase 3 processors from writing results
   - Root cause: Too many inserts to partitioned `run_history` table
   - Fix: Batching writes in pipeline_logger (commit c07d5433)
   - Action: Check quota proactively in Phase 0

### Expected Behaviors (Not Errors)

1. **Source-Blocked Games**: NBA.com not publishing data for some games
   - Don't count as failures
   - Note in output for transparency

2. **No Predictions Pre-Game**: Normal if games haven't happened yet
   - Only error if checking yesterday's games

3. **Early Season Lower Quality**: First 2-3 weeks of season
   - 50-70% PASS predictions expected
   - 60-80% early_season_flag expected

4. **Off-Day Validation**: No games scheduled
   - Not an error, just informational

## Data Quality Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| **Spot Check Accuracy** | ≥95% | 90-94% | <90% |
| **Minutes Played Coverage** | ≥90% | 80-89% | <80% |
| **Usage Rate Coverage** | ≥90% | 80-89% | <80% |
| **Prediction Coverage** | ≥90% | 70-89% | <70% |
| **Game Context Coverage** | 100% | 95-99% | <95% |
| **Phase 3 Completion** | 5/5 | 3-4/5 | 0-2/5 |
| **Phase Execution Logs** | All phases logged | 1-2 missing | No logs found |
| **Weekly Hit Rate** | ≥65% | 55-64% | <55% |
| **Model Bias** | ±2 pts | ±3-5 pts | >±5 pts |
| **Vegas Edge** | >0.5 pts | 0-0.5 pts | <0 pts |
| **BDB Coverage** | ≥90% | 50-89% | <50% |
| **Game Lines Coverage** | ≥90% | 70-89% | <70% |
| **Player Props Coverage** | ≥200/day | 100-199/day | <100/day |

**Key Thresholds to Remember**:
- **63% minutes coverage** → CRITICAL (not WARNING!)
- **2/5 Phase 3 processors** → CRITICAL (not just incomplete)
- **Missing phase_execution_log** → Investigate, may need fallback checks

## Severity Classification

**🔴 P1 CRITICAL** (Immediate Action):
- All predictions missing for entire day
- Data corruption detected (spot checks <90%)
- Pipeline completely stuck (no phases completing)
- Minutes/usage coverage <80% (e.g., 63% is CRITICAL)
- Phase 3 completion 0-2/5 processors
- Phase execution log completely empty for a date
- BDB coverage <50% for multiple consecutive days

**🟡 P2 HIGH** (Within 1 Hour):
- Data quality issue 70-89% coverage
- Single phase failing completely
- Spot check accuracy 90-94%
- Significant prediction quality drop
- BDB coverage 50-89% (partial shot zone data)

**🟠 P3 MEDIUM** (Within 4 Hours):
- Spot check accuracy 95-99%
- Single processor failing (others working)
- Timing delays (late completion)
- Non-critical data gaps

**🟢 P4 LOW** (Next Business Day):
- Non-critical data missing (prop lines, old roster)
- Performance degradation
- Documentation issues

**ℹ️  P5 INFO** (No Action):
- Source-blocked games noted
- Off-day (no games scheduled)
- Pre-game checks on data not yet expected

## Output Format

Provide a clear, concise summary structured like this:

```
## Daily Orchestration Validation - [DATE]

### Summary: [STATUS]
[One-line overall health status with emoji]

| Phase | Status | Details |
|-------|--------|---------|
| Phase 2 (Betting) | ✅/⚠️/❌ | [metrics] |
| Phase 3 (Analytics) | ✅/⚠️/❌ | [completion %] |
| Phase 4 (Precompute) | ✅/⚠️/❌ | [feature count] |
| Phase 5 (Predictions) | ✅/⚠️/❌ | [prediction count] |
| Spot Checks | ✅/⚠️/❌ | [accuracy %] |
| Model Drift | ✅/⚠️/❌ | [4-week trend, tier breakdown] |
| BDB Coverage | ✅/⚠️/❌ | [X]% (pending: [Y] games) |

### Issues Found
[List issues with severity emoji]
- 🔴/🟡/🟠/🟢 [Severity]: [Issue description]
  - Impact: [what's affected]
  - Root cause: [if known]
  - Recommendation: [specific action]

### Unusual Observations
[Anything notable but not critical]

### Recommended Actions
[Numbered list of specific next steps]
1. [Action with command if applicable]
2. [Action with reference to runbook if complex]
```

### Output Format (Yesterday's Results)

When validating yesterday's results, use this format:

```
## Yesterday's Results Validation - [GAME_DATE]

### Summary: [STATUS]
Processing date: [PROCESSING_DATE] (scrapers/analytics ran after midnight)

### Priority 1: Critical Checks

| Check | Status | Details |
|-------|--------|---------|
| Box Scores | ✅/❌ | [X] games, [Y] player records |
| Prediction Grading | ✅/❌ | [X]% graded ([Y] predictions) |
| Scraper Runs | ✅/❌ | nbac_gamebook: [status], bdl: [status] |

### Priority 2: Pipeline Completeness

| Check | Status | Details |
|-------|--------|---------|
| Analytics | ✅/❌ | player_game_summary: [X] records |
| Phase 3 | ✅/❌ | [X]/5 processors complete |
| Cache Updated | ✅/❌ | Last update: [timestamp] |
| BDB Coverage | ✅/⚠️/❌ | [X]% (pending: [Y] games) |

### Priority 3: Quality (if run)

| Check | Status | Details |
|-------|--------|---------|
| Spot Check Accuracy | ✅/⚠️/❌ | [X]% |
| Prediction Accuracy | ℹ️ | Points: [X]%, Rebounds: [Y]%, ... |

### Issues Found
[List any issues with severity]

### Recommended Actions
[Prioritized list of fixes]
```

## Important Guidelines

1. **Be Concise**: Don't dump raw output - summarize and interpret
2. **Be Specific**: "Phase 3 incomplete" is less useful than "Phase 3: upcoming_player_game_context failed due to stale dependencies"
3. **Provide Context**: Is this a known issue? Expected behavior? New problem?
4. **Be Actionable**: Every issue should have a recommended action
5. **Classify Severity**: Use P1-P5 system, don't treat everything as critical
6. **Distinguish Failures from Expectations**: Source-blocked games, off-days, timing issues
7. **Investigate Don't Just Report**: If something fails, dig into why
8. **Reference Knowledge**: Use the known issues list and thresholds above

## Reference Documentation

For deeper investigation, consult:
- `docs/02-operations/daily-operations-runbook.md` - Standard procedures
- `docs/02-operations/troubleshooting-matrix.md` - Decision trees for failures
- `docs/06-testing/SPOT-CHECK-SYSTEM.md` - Spot check details
- `docs/09-handoff/` - Recent session findings and fixes

## Morning Workflow (RECOMMENDED)

**NEW (2026-01-28): Start your morning validation with the fast dashboard:**

```bash
# Step 1: Quick health check (< 30 seconds)
./bin/monitoring/morning_health_check.sh

# If issues detected, run full validation
python scripts/validate_tonight_data.py --date $(date -d "yesterday" +%Y-%m-%d)
```

**Morning dashboard shows:**
- Overnight processing summary (games, phases, data quality)
- Phase 3 completion status (must be 5/5)
- Stuck phase detection
- Recent errors
- Clear action items if issues found

**When to use each tool:**
- **Morning dashboard** (`morning_health_check.sh`): Run first thing every morning for quick overview
- **Full validation** (`validate_tonight_data.py`): Run when dashboard shows issues or for comprehensive checks
- **Pre-flight checks** (`validate_tonight_data.py --pre-flight`): Run at 5 PM before games start

## Key Commands Reference

```bash
# Morning health dashboard (NEW - run first!)
./bin/monitoring/morning_health_check.sh

# Pre-flight checks (run at 5 PM ET before games)
python scripts/validate_tonight_data.py --pre-flight

# Full validation
python scripts/validate_tonight_data.py

# Legacy health check (more verbose)
./bin/monitoring/daily_health_check.sh

# Spot checks (5 samples, fast checks)
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate

# Comprehensive spot checks (slower)
python scripts/spot_check_data_accuracy.py --samples 10

# Golden dataset verification (high-confidence validation)
python scripts/verify_golden_dataset.py
python scripts/verify_golden_dataset.py --verbose  # With detailed calculations

# Model drift monitoring (Session 28)
bq query --use_legacy_sql=false "SELECT DATE_TRUNC(game_date, WEEK) as week, ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate FROM nba_predictions.prediction_accuracy WHERE system_id = 'catboost_v8' AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK) GROUP BY 1 ORDER BY 1 DESC"

# Manual triggers (if needed)
gcloud scheduler jobs run same-day-phase3
gcloud scheduler jobs run same-day-phase4
gcloud scheduler jobs run same-day-phase5

# Check specific date
python scripts/validate_tonight_data.py --date 2026-01-26
```

## Player Spot Check Skills Reference

For investigating player-level data issues:

| Skill | Command | Use Case |
|-------|---------|----------|
| `/spot-check-player` | `/spot-check-player lebron_james 20` | Deep dive on one player |
| `/spot-check-date` | `/spot-check-date 2026-01-25` | Check all players for one date |
| `/spot-check-team` | `/spot-check-team LAL 15` | Check team roster completeness |
| `/spot-check-gaps` | `/spot-check-gaps 2025-12-19 2026-01-26` | System-wide gap audit |

**When to use**:
- ERROR_HAS_MINUTES found in daily check → `/spot-check-player` for deep dive
- Multiple players missing for one date → `/spot-check-date` for that day
- Team with roster changes → `/spot-check-team` to verify coverage
- Weekly audit → `/spot-check-gaps` for comprehensive review

---

**Remember**: You are not a rigid script. Use your judgment, investigate intelligently, and adapt based on what you find. The goal is actionable insights, not just command execution.
