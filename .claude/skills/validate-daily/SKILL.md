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

Verify box score scrapers ran successfully (they run after midnight):

```bash
PROCESSING_DATE=$(date +%Y-%m-%d)

bq query --use_legacy_sql=false "
SELECT
  scraper_name,
  status,
  records_processed,
  completed_at
FROM \`nba-props-platform.nba_orchestration.scraper_run_history\`
WHERE DATE(started_at) = DATE('${PROCESSING_DATE}')
  AND scraper_name IN ('nbac_gamebook', 'bdl_player_boxscores')
ORDER BY completed_at DESC"
```

**Expected**: Both scrapers show `status = 'success'`

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

#### 2B. Phase 3 Completion Status

Check that Phase 3 processors completed (they run after midnight, so check today's date):

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime
db = firestore.Client()
# Phase 3 runs after midnight, so check TODAY's completion record
processing_date = datetime.now().strftime('%Y-%m-%d')
doc = db.collection('phase3_completion').document(processing_date).get()
if doc.exists:
    data = doc.to_dict()
    print(f"Phase 3 Status for {processing_date}:")
    for processor, status in sorted(data.items()):
        print(f"  {processor}: {status.get('status', 'unknown')}")
else:
    print(f"No Phase 3 completion record for {processing_date}")
EOF
```

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

## Severity Classification

**🔴 P1 CRITICAL** (Immediate Action):
- All predictions missing for entire day
- Data corruption detected (spot checks <90%)
- Pipeline completely stuck (no phases completing)
- Minutes/usage coverage <80%

**🟡 P2 HIGH** (Within 1 Hour):
- Data quality issue 70-89% coverage
- Single phase failing completely
- Spot check accuracy 90-94%
- Significant prediction quality drop

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

## Key Commands Reference

```bash
# Health check
./bin/monitoring/daily_health_check.sh

# Full validation
python scripts/validate_tonight_data.py

# Spot checks (5 samples, fast checks)
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate

# Comprehensive spot checks (slower)
python scripts/spot_check_data_accuracy.py --samples 10

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
