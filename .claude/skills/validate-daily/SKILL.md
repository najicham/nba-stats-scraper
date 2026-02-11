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

### Phase 0.1: Deployment Drift Check (Session 81 - CRITICAL)

**IMPORTANT**: Verify all critical services are deployed with latest code.

**Why this matters**: Bug fixes committed but not deployed cause issues to persist. Sessions 82, 81, and 64 had critical bugs that were fixed in code but not deployed for hours/days.

**Real Examples:**
- Session 82: Coordinator fix committed but not deployed
- Session 81: Worker env vars fix committed but not deployed
- Session 64: Backfill ran with OLD code 12 hours after fix was committed (50.4% hit rate vs 58%+)

**What to check**:

```bash
# Run deployment drift check
./bin/check-deployment-drift.sh --verbose
```

**Expected Result:**
- All services show `✓ Up to date` or have acceptable drift (<24 hours)
- No services showing STALE DEPLOYMENT

**If STALE DEPLOYMENT detected**:

| Commits Behind | Severity | Action |
|----------------|----------|--------|
| 1-2 commits | P2 | Deploy when convenient |
| 3-5 commits | P1 | Deploy today |
| 6+ commits | P0 CRITICAL | Deploy immediately |

**Critical Services (must be up-to-date):**
- `prediction-worker` - Generates predictions
- `prediction-coordinator` - Orchestrates predictions
- `nba-grading-service` - Grades predictions
- `nba-phase3-analytics-processors` - Analytics processing
- `nba-scrapers` - Data collection

**Investigation if drift detected**:

```bash
# See what changed since deployment
SERVICE="prediction-worker"
DEPLOYED_SHA=$(gcloud run services describe $SERVICE --region=us-west2 \
  --format="value(metadata.labels.commit-sha)")

git log --oneline $DEPLOYED_SHA..HEAD -- predictions/worker/

# If critical fixes found, deploy immediately
./bin/deploy-service.sh $SERVICE
```

**Reference**: Sessions 82, 81, 64 handoffs

### Phase 0.2: Heartbeat System Health (NEW)

**IMPORTANT**: Check Firestore heartbeat collection for document proliferation.

**Why this matters**: Heartbeat documents should be ONE per processor (one doc gets updated). If processors create NEW documents for each run, the collection grows unbounded (100k+ docs), causing performance degradation and Firestore costs.

**What to check**:

```bash
# Check Firestore heartbeat document count
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())
bad = [d for d in docs if '_None_' in d.id or '_202' in d.id]
total = len(docs)
bad_count = len(bad)

print(f'Total heartbeat documents: {total}')
print(f'Bad format (old pattern): {bad_count}')
print(f'Expected: ~30-50 documents')

if bad_count > 0:
    print(f'\n⚠️  WARNING: {bad_count} old format documents detected!')
    print('Sample bad documents:')
    for doc in bad[:5]:
        print(f'  {doc.id}')
    print('\nAction: Run bin/cleanup-heartbeat-docs.py')

if total > 100:
    print(f'\n⚠️  WARNING: Too many documents ({total})!')
    print('Expected: ~30-50 (one per active processor)')
    print('Possible cause: Heartbeat code creating new docs instead of updating')
    print('Action: Check shared/monitoring/processor_heartbeat.py')
"
```

**Expected result**:
- Total documents: 30-50
- Bad format documents: 0

**If issues detected**:

| Issue | Severity | Action |
|-------|----------|--------|
| Bad format docs > 0 | P2 | Run `bin/cleanup-heartbeat-docs.py` to clean up |
| Total docs > 100 | P1 | Investigate which service creating bad docs, redeploy |
| Total docs > 500 | P0 CRITICAL | Immediate cleanup + service fix |

**Cleanup command**:
```bash
# Preview cleanup
python bin/cleanup-heartbeat-docs.py --dry-run

# Execute cleanup
python bin/cleanup-heartbeat-docs.py
```

**Investigation command** (if proliferation detected):
```bash
# Find which processors created docs in last hour
python3 -c "
from google.cloud import firestore
from datetime import datetime, timedelta
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())
cutoff = datetime.now() - timedelta(hours=1)

recent_bad = []
for doc in docs:
    data = doc.to_dict()
    last_hb = data.get('last_heartbeat')
    if '_None_' in doc.id or '_202' in doc.id:
        if last_hb and hasattr(last_hb, 'replace') and last_hb.replace(tzinfo=None) > cutoff:
            recent_bad.append(doc.id)

if recent_bad:
    print(f'⚠️  {len(recent_bad)} bad documents created in last hour')
    print('Offending processors:')
    for doc_id in set([d.split('_None_')[0].split('_202')[0] for d in recent_bad]):
        print(f'  {doc_id}')
else:
    print('✅ No new bad documents in last hour')
"
```

### Phase 0.3: Deployment Drift Check (Session 87 Addition)

**IMPORTANT**: Check if key services are running the latest code.

**Why this matters**: Code fixes that aren't deployed cause recurring issues. Sessions 58, 64, and 84 all had problems where bug fixes were committed but not deployed, leading to stale code running in production.

**What to check**:

```bash
# Quick deployment status check
./bin/whats-deployed.sh
```

**Expected result**:
- All key services showing "Up to date" or commits behind = 0
- If using labels: `commit-sha` label matches recent commit
- If using env var: `BUILD_COMMIT` env var matches recent commit

**Detailed check for specific service**:

```bash
# Check a specific service with undeployed commits
./bin/whats-deployed.sh prediction-worker --diff
```

**Check if specific feature is deployed**:

```bash
# Check by commit message search
./bin/is-feature-deployed.sh prediction-worker "Session 84"

# Check by file change
./bin/is-feature-deployed.sh prediction-worker --file predictions/worker/worker.py
```

**Severity levels**:

| Commits Behind | Severity | Action |
|----------------|----------|--------|
| 0 | OK | Service up to date |
| 1-3 (docs only) | P3 | OK if only documentation changes |
| 1-3 (code) | P2 | Deploy soon: `./bin/deploy-service.sh <service>` |
| 4+ | P1 | Deploy now - significant drift |
| Unknown (no label/env) | P2 | Deploy with `./bin/deploy-service.sh` to add tracking |

**If drift detected**:

```bash
# 1. See what's not deployed
./bin/whats-deployed.sh <service> --diff

# 2. Deploy the service
./bin/deploy-service.sh <service>

# 3. Verify after deployment
./bin/whats-deployed.sh <service>
```

**Key services to check**:
- `prediction-worker` - Generates predictions (most critical)
- `prediction-coordinator` - Orchestrates prediction batches
- `nba-phase3-analytics-processors` - Game analytics
- `nba-phase4-precompute-processors` - ML features

### Phase 0.4: Grading Completeness Check (Session 68 Fix)

**IMPORTANT**: Check if grading pipeline is up-to-date for all active models.

**Why this matters**: Backfilled predictions may not be graded yet. If `prediction_accuracy` is missing data, model analysis will be wrong.

**Real Example (Session 68)**: V9 had 6,665 predictions but only 94 graded (1.4% coverage). Analysis incorrectly showed 42% hit rate when actual was 79.4%.

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Check grading completeness for all active models (last 7 days)
WITH prediction_counts AS (
  SELECT
    'player_prop_predictions' as source,
    system_id,
    COUNT(*) as record_count
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND current_points_line IS NOT NULL
  GROUP BY system_id

  UNION ALL

  SELECT
    'prediction_accuracy' as source,
    system_id,
    COUNT(*) as record_count
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
)
SELECT
  system_id,
  MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END) as predictions,
  MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) as graded,
  ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
        NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) as coverage_pct,
  CASE
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 50
    THEN '🔴 CRITICAL - Run grading backfill'
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 80
    THEN '🟡 WARNING - Partial grading gap'
    ELSE '✅ OK'
  END as status
FROM prediction_counts
GROUP BY system_id
ORDER BY coverage_pct ASC"
```

**Expected**: All models show ≥80% grading coverage

**Thresholds**:
- **<50% coverage** → 🔴 CRITICAL - Grading backfill needed immediately
- **50-80% coverage** → 🟡 WARNING - Partial gap, may affect analysis
- **≥80% coverage** → ✅ OK

**If CRITICAL or WARNING**:

1. Run grading backfill:
   ```bash
   PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
     --start-date <first-date> --end-date <last-date>
   ```

2. **Until grading is complete**, use this query for accurate model analysis:
   ```sql
   -- Correct approach when prediction_accuracy is incomplete
   SELECT
     p.system_id,
     CASE WHEN ABS(p.predicted_points - p.current_points_line) >= 5 THEN 'High Edge' ELSE 'Other' END as tier,
     COUNT(*) as bets,
     ROUND(100.0 * COUNTIF(
       (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
       (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
     ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
   FROM nba_predictions.player_prop_predictions p
   JOIN nba_analytics.player_game_summary pgs
     ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
   WHERE p.system_id = 'catboost_v9'
     AND p.current_points_line IS NOT NULL
     AND p.game_date >= '2026-01-09'
   GROUP BY 1, 2
   ```

### Phase 0.45: Edge Filter Verification (Session 102 - Updated Architecture)

**IMPORTANT**: Verify edge filtering via `is_actionable` field is working correctly.

**Architecture Change (Session 102)**: Edge filtering moved from write-time (MERGE exclusion) to query-time (is_actionable field). All predictions are now stored, but low-edge ones are marked `is_actionable = FALSE`.

**Why this matters**: Low-edge predictions (edge < 3) have ~50% hit rate and lose money after vig. The `is_actionable` field marks which predictions are safe to bet on.

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Verify edge filter via is_actionable (Session 102 architecture)
-- Expected: Low-edge predictions have is_actionable = FALSE
SELECT
  CASE
    WHEN line_source = 'NO_PROP_LINE' THEN 'NO_LINE'
    WHEN ABS(predicted_points - current_points_line) >= 5 THEN 'HIGH (5+)'
    WHEN ABS(predicted_points - current_points_line) >= 3 THEN 'MEDIUM (3-5)'
    ELSE 'LOW (<3)'
  END as edge_tier,
  is_actionable,
  COUNT(*) as count,
  CASE
    WHEN is_actionable = TRUE
      AND line_source != 'NO_PROP_LINE'
      AND ABS(predicted_points - current_points_line) < 3
    THEN '❌ FAIL'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
GROUP BY 1, 2
HAVING edge_tier = 'LOW (<3)' AND is_actionable = TRUE
ORDER BY 1, 2
"
```

**Expected Result**:
- Zero rows returned (no actionable low-edge predictions)
- All `LOW (<3)` predictions should have `is_actionable = FALSE`

**Check filter_reason distribution**:

```bash
bq query --use_legacy_sql=false "
-- Check filter reasons are being applied
SELECT
  filter_reason,
  COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_actionable = FALSE
GROUP BY filter_reason
ORDER BY count DESC
"
```

**Expected filter_reasons**:
- `low_edge`: Edge < 3 predictions
- `confidence_tier_88_90`: 88-90% confidence tier (lower hit rate)
- `star_under_bias_suspect`: High-edge UNDERs on star players

**If FAIL (actionable low-edge predictions found)**:

| Issue | Severity | Action |
|-------|----------|--------|
| Actionable low-edge found | P1 CRITICAL | Check if predictions created before deployment |

**Investigation steps**:

1. **Check when predictions were created vs deployment**:
   ```bash
   # Get worker deployment time
   gcloud run revisions list --service=prediction-worker --region=us-west2 --limit=3

   # Check prediction creation times
   bq query --use_legacy_sql=false "
   SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', created_at) as created,
     COUNTIF(is_actionable AND line_source != 'NO_PROP_LINE' AND ABS(predicted_points - current_points_line) < 3) as bad
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
   GROUP BY 1 ORDER BY 1"
   ```

2. **If predictions created before deployment** (common cause):
   ```sql
   -- Fix: Mark low-edge predictions as non-actionable
   UPDATE nba_predictions.player_prop_predictions
   SET is_actionable = FALSE, filter_reason = 'low_edge_backfill'
   WHERE game_date = 'YYYY-MM-DD'
     AND system_id = 'catboost_v9'
     AND line_source != 'NO_PROP_LINE'
     AND ABS(predicted_points - current_points_line) < 3
     AND is_actionable = TRUE
   ```

3. **Verify filter code is deployed**:
   ```bash
   # Check if Session 102 commit is in deployed version
   DEPLOYED_SHA=$(gcloud run services describe prediction-worker --region=us-west2 \
     --format="value(metadata.labels.commit-sha)")
   git merge-base --is-ancestor c04be05a $DEPLOYED_SHA && echo "Edge filter deployed" || echo "NOT deployed"
   ```

**Correct Query for Betting** (filters properly):
```sql
SELECT * FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
  AND is_actionable = TRUE  -- Session 102: Use this field!
```

**Reference**: `docs/08-projects/current/edge-filter-investigation/SESSION-106-INVESTIGATION.md`

### Phase 0.46: Prediction Deactivation Logic Validation (Session 81 - CRITICAL)

**IMPORTANT**: Verify `is_active` deactivation logic is working correctly.

**Why this matters**: Session 78 bug caused 85% of predictions to be marked `is_active=FALSE`, excluding them from grading. This led to false "low hit rate" conclusions and required data repair.

**Root Cause (Session 78)**: Deactivation query missing `system_id` in PARTITION BY, causing all but ONE prediction per player/game to be deactivated (regardless of system_id).

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Verify is_active distribution is correct (Session 81)
-- Expected: ACTUAL_PROP predictions should be mostly TRUE
--          NO_PROP_LINE predictions should be mostly FALSE
SELECT
  game_date,
  line_source,
  is_active,
  COUNT(*) as cnt,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(PARTITION BY game_date, line_source), 1) as pct,
  CASE
    WHEN line_source = 'ACTUAL_PROP' AND is_active = FALSE AND
         100.0 * COUNT(*) / SUM(COUNT(*)) OVER(PARTITION BY game_date, line_source) > 20
      THEN '🚨 BUG DETECTED - Too many ACTUAL_PROP deactivated'
    WHEN line_source = 'NO_PROP_LINE' AND is_active = TRUE AND
         100.0 * COUNT(*) / SUM(COUNT(*)) OVER(PARTITION BY game_date, line_source) > 20
      THEN '⚠️ UNEXPECTED - Too many NO_PROP_LINE active'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
  AND system_id = 'catboost_v9'
GROUP BY 1, 2, 3
HAVING status != '✅ OK'
ORDER BY 1, 2, 3
"
```

**Expected Result:**
- No rows returned (all status = ✅ OK)
- ACTUAL_PROP: >80% should be `is_active=TRUE`
- NO_PROP_LINE: >80% should be `is_active=FALSE`

**If BUG DETECTED**:

| Issue | Severity | Action |
|-------|----------|--------|
| >20% ACTUAL_PROP have is_active=FALSE | P0 CRITICAL | Deactivation logic broken, needs immediate fix + data repair |
| >20% NO_PROP_LINE have is_active=TRUE | P2 | Unexpected but not blocking |

**Investigation steps**:

1. **Check deactivation query code**:
   ```bash
   # Verify system_id is in PARTITION BY clause
   grep -A10 "ROW_NUMBER.*PARTITION BY" predictions/shared/batch_staging_writer.py | grep -i system_id

   # Expected: PARTITION BY game_id, player_lookup, system_id
   ```

2. **Sample affected predictions**:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT
     player_lookup,
     system_id,
     line_source,
     is_active,
     created_at
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
     AND line_source = 'ACTUAL_PROP'
     AND is_active = FALSE
   ORDER BY player_lookup, created_at DESC
   LIMIT 20
   "
   ```

**Data Repair** (if bug recurs):

```sql
-- Re-activate predictions that should be active
UPDATE `nba_predictions.player_prop_predictions` T
SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP()
WHERE game_date >= DATE('YYYY-MM-DD')
  AND is_active = FALSE
  AND line_source IN ('ACTUAL_PROP', 'ESTIMATED_AVG')
  AND prediction_id IN (
    SELECT prediction_id FROM (
      SELECT prediction_id,
        ROW_NUMBER() OVER (
          PARTITION BY game_id, player_lookup, system_id
          ORDER BY created_at DESC
        ) as rn
      FROM `nba_predictions.player_prop_predictions`
      WHERE game_date >= DATE('YYYY-MM-DD')
    ) WHERE rn = 1
  )
```

**Reference**: Session 78 handoff, Session 80 data repair

### Phase 0.465: Orphan Superseded Predictions Check (Session 102 - CRITICAL)

**IMPORTANT**: Verify there are no orphan superseded predictions (superseded with no active replacement).

**Why this matters**: Session 102 discovered that regeneration batches with edge filtering can cause "orphan" superseded predictions. When corrected features produce predictions with edge < 3, they get filtered during MERGE, leaving old superseded predictions with no active replacement. This leaves players without usable predictions.

**Root Cause**:
1. Old predictions marked `superseded=TRUE` during overnight batch
2. Regeneration creates new predictions with corrected features
3. Corrected features → different predictions → some have edge < 3.0
4. Edge filter blocks new predictions during MERGE
5. Old superseded predictions remain unchanged → orphan

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Check for orphan superseded predictions (superseded with no active replacement)
WITH orphan_check AS (
  SELECT
    game_date,
    player_lookup,
    system_id,
    MAX(CASE WHEN superseded IS NOT TRUE THEN 1 ELSE 0 END) as has_active,
    MAX(CASE WHEN superseded IS TRUE THEN 1 ELSE 0 END) as has_superseded
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    AND system_id = 'catboost_v9'
  GROUP BY 1, 2, 3
)
SELECT
  game_date,
  COUNTIF(has_active = 1) as players_with_active,
  COUNTIF(has_active = 0 AND has_superseded = 1) as orphan_superseded,
  CASE
    WHEN COUNTIF(has_active = 0 AND has_superseded = 1) = 0 THEN '✅ PASS'
    ELSE '❌ FAIL - Orphan superseded predictions found!'
  END as status
FROM orphan_check
GROUP BY game_date
ORDER BY game_date DESC"
```

**Expected Result**:
- `orphan_superseded = 0` for all dates
- `status = ✅ PASS`

**If FAIL (orphan_superseded > 0)**:

| Issue | Severity | Action |
|-------|----------|--------|
| Orphan superseded predictions | P0 CRITICAL | Players missing usable predictions |

**Investigation steps**:

1. **Identify affected players**:
   ```bash
   bq query --use_legacy_sql=false "
   WITH orphan_check AS (
     SELECT
       game_date, player_lookup, system_id,
       MAX(CASE WHEN superseded IS NOT TRUE THEN 1 ELSE 0 END) as has_active
     FROM nba_predictions.player_prop_predictions
     WHERE game_date = 'YYYY-MM-DD' AND system_id = 'catboost_v9'
     GROUP BY 1, 2, 3
   )
   SELECT player_lookup
   FROM orphan_check
   WHERE has_active = 0
   ORDER BY player_lookup"
   ```

2. **Check if recent regeneration ran**:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision"
     AND resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"regenerat"
     AND timestamp>="2026-02-03T00:00:00Z"' \
     --limit=10 --format="table(timestamp,textPayload)"
   ```

3. **Verify Session 102 fix is deployed** (edge filter skip for regen batches):
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision"
     AND resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"Session 102: Edge filtering DISABLED"' \
     --limit=5 --format="table(timestamp,textPayload)"
   # Expected: Recent log showing edge filter disabled for regen batch
   ```

**Resolution**:

If orphan superseded predictions found:
```bash
# Trigger regeneration with Session 102 fix (skips edge filter)
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "${COORDINATOR_URL}/regenerate-with-supersede" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "YYYY-MM-DD", "reason": "orphan_superseded_fix"}'
```

**Reference**: Session 102 handoff, `docs/09-handoff/2026-02-03-SESSION-102-HANDOFF.md`

### Phase 0.466: Model Bias Check (Session 102, fixed Session 162)

**IMPORTANT**: Verify model predictions are not systematically biased by player tier.

**CRITICAL METHODOLOGY NOTE (Session 161)**: Always tier players by their **season average** (what the player IS), never by `actual_points` (what they scored in one game). Using `actual_points` creates survivorship bias — selecting players who scored high and then noting the model predicted lower is circular reasoning. See `docs/08-projects/current/session-161-model-eval-and-subsets/00-PROJECT-OVERVIEW.md`.

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Check model bias by player tier using SEASON AVERAGE (correct methodology)
-- Tiers by what the player IS (season avg), not what they scored (actual_points)
WITH player_avgs AS (
  SELECT player_lookup, AVG(actual_points) as season_avg
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v9' AND game_date >= '2025-11-01'
  GROUP BY 1
)
SELECT
  CASE
    WHEN pa.season_avg >= 25 THEN '1_Stars (25+ avg)'
    WHEN pa.season_avg >= 15 THEN '2_Starters (15-24 avg)'
    WHEN pa.season_avg >= 8 THEN '3_Role (8-14 avg)'
    ELSE '4_Bench (<8 avg)'
  END as tier,
  COUNT(*) as n,
  ROUND(AVG(p.predicted_points - p.actual_points), 1) as bias,
  CASE WHEN ABS(AVG(p.predicted_points - p.actual_points)) > 3 THEN '❌ FAIL' ELSE '✅ OK' END as status
FROM nba_predictions.prediction_accuracy p
JOIN player_avgs pa USING (player_lookup)
WHERE p.system_id = 'catboost_v9'
  AND p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1"
```

**Expected Result**:
- All tiers should have bias < 3 pts (Session 161 showed -0.3 for stars with correct methodology)
- If using season_avg tiers shows high bias, it's a real model issue (not measurement artifact)

**If FAIL (any tier has bias > 3 pts)**:

| Tier | Bias Direction | Root Cause |
|------|----------------|------------|
| Stars (25+ avg) | Under-predicted | Real regression-to-mean in model |
| Bench (<8 avg) | Over-predicted | Model over-predicting low-usage players |

**Resolution**:
1. Check `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`
2. Consider adding tier recalibration in worker.py
3. Plan model retraining with tier features

**Reference**: Session 161 model eval methodology, Session 102 handoff

### Phase 0.47: Session 97 Quality Gate Check (CRITICAL)

**IMPORTANT**: Verify the ML Feature Store quality gate is functioning correctly.

**Why this matters**: Session 97 implemented a quality gate that prevents ML Feature Store from running when Phase 4 hasn't completed. This prevents the Feb 2, 2026 issue where stale Phase 4 data caused 49.1% hit rate (vs expected 55%+). The quality gate requires sufficient records in `player_daily_cache` and `player_composite_factors`.

**What to check**:

```bash
# Check if quality gate has been triggered recently (indicates it's working)
gcloud logging read 'textPayload=~"QUALITY_GATE"' --limit=5 --freshness=6h \
  --format="table(timestamp,textPayload)" 2>/dev/null
```

**Expected Result**:
- If Phase 4 incomplete: Should see `QUALITY_GATE FAILED` messages
- If Phase 4 complete: No quality gate failures (or PASSED messages)

**Check Phase 4 data sufficiency**:

```bash
GAME_DATE=$(date +%Y-%m-%d)
bq query --use_legacy_sql=false "
SELECT
  'player_daily_cache' as table_name,
  COUNT(*) as records,
  CASE
    WHEN COUNT(*) >= 50 THEN '✅ OK'
    WHEN COUNT(*) > 0 THEN '🟡 LOW'
    ELSE '🔴 EMPTY'
  END as status
FROM nba_precompute.player_daily_cache
WHERE cache_date = DATE('${GAME_DATE}')"
```

**Thresholds**:
- **≥50 records**: OK - Sufficient data for predictions
- **1-49 records**: WARNING - Partial data, investigate
- **0 records**: CRITICAL - Phase 4 hasn't run for today yet

**Check phase trigger status** (Session 98 finding):

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime, timedelta

db = firestore.Client(project='nba-props-platform')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
today = datetime.now().strftime('%Y-%m-%d')

# Check Phase 3 Analytics Output (validates Phase 2→3 transition)
print(f"Phase 3 Analytics Output for {yesterday}:")
# Direct validation: Check if Phase 3 actually generated data
query = f"""
SELECT COUNT(*) as players, COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date = '{yesterday}'
"""
result = list(bq_client.query(query))
if result:
    players = result[0]['players']
    games = result[0]['games']
    print(f"  Players: {players}, Games: {games}")
    if games == 0:
        print(f"  🔴 P0 CRITICAL: No Phase 3 analytics data for {yesterday}!")
        print(f"  Action: Check Phase 3 service logs, may need manual trigger")
    elif players < 50:
        print(f"  ⚠️  WARNING: Low player count (expected 100+)")
else:
    print(f"  🔴 P0 CRITICAL: Unable to query Phase 3 analytics!")

# Check Phase 3 → Phase 4 trigger
print(f"\nPhase 3 Completion for {today}:")
doc = db.collection('phase3_completion').document(today).get()
if doc.exists:
    data = doc.to_dict()
    completed = len([k for k in data.keys() if not k.startswith('_')])
    triggered = data.get('_triggered', False)
    print(f"  Processors: {completed}/5, Phase 4 triggered: {triggered}")
    if completed >= 5 and not triggered:
        print(f"  🔴 BUG: Phase 3 complete but Phase 4 NOT triggered!")
else:
    print("  No record found")
EOF
```

**If trigger issue detected** (processors complete but `_triggered = False`):
- 🔴 P1 CRITICAL: Orchestrator not triggering next phase
- Impact: Pipeline stalls, downstream phases don't run
- Immediate action: Manually trigger the next phase
- Root cause: Check Cloud Function orchestrator logs

**Manual Phase Triggers**:
```bash
# Trigger Phase 3
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Trigger Phase 4
gcloud scheduler jobs run same-day-phase4 --location=us-west2

# Trigger Phase 5 (predictions)
gcloud scheduler jobs run same-day-phase5 --location=us-west2
```

**Reference**: Session 97 handoff, Session 98 validation findings

### Phase 0.475: Phase 3 Orchestration Reliability

Session 116/117 prevention - verify Firestore completion tracking is accurate.

**Run health check:**
```bash
./bin/monitoring/phase3_health_check.sh --verbose
```

**Expected:** All checks pass (Firestore accurate, no duplicates, scrapers on time)

**If issues found:**
```bash
python bin/maintenance/reconcile_phase3_completion.py --days 3 --fix
```

**Reference:** docs/08-projects/current/prevention-and-monitoring/phase3-orchestration-reliability/

### Phase 0.476: Realtime Completeness Checker Health (Session 128)

**IMPORTANT**: Verify the realtime completeness checker is working correctly.

**Why this matters**: Session 128 made the completeness checker time-aware - before 6 AM ET, it only checks BDL/boxscore sources (gamebook isn't available yet). This prevents false alerts during evening analytics.

**What to check**:

```bash
# Check recent completeness checker logs
gcloud logging read 'resource.labels.function_name="realtime-completeness-checker"' \
  --limit=10 --format="table(timestamp,textPayload)"
```

**Expected behavior by time**:
- **Before 6 AM ET**: Logs should show "Gamebook NOT expected (before 6 AM ET) - only checking BDL"
- **After 6 AM ET**: Logs should show "Gamebook expected (after 6 AM ET) - checking both sources"

**Check for false alerts**:
```bash
# Check missing_games_log for today
bq query --use_legacy_sql=false "
SELECT game_date, matchup, gamebook_missing, bdl_missing, discovered_at
FROM nba_orchestration.missing_games_log
WHERE discovered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY discovered_at DESC
LIMIT 10"
```

**If gamebook_missing = true during evening hours (before 6 AM)**:
- This is expected behavior - gamebook arrives at ~6 AM
- Session 128 fix should prevent alerts for this

**If bdl_missing = true**:
- This is a real data gap - investigate BDL scraper

### Phase 0.48: Feature Quality Visibility Check (Sessions 99, 139)

**IMPORTANT**: Verify feature data quality using the per-category quality fields (Session 139 upgrade).

**Why this matters**: The aggregate `feature_quality_score` masks component failures (Session 134 insight). Use category-level quality and alert levels for actionable diagnostics.

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Quality readiness and alert level distribution
SELECT
  COUNTIF(is_quality_ready = TRUE) as quality_ready,
  ROUND(COUNTIF(is_quality_ready = TRUE) * 100.0 / COUNT(*), 1) as ready_pct,
  COUNTIF(quality_alert_level = 'green') as green,
  COUNTIF(quality_alert_level = 'yellow') as yellow,
  COUNTIF(quality_alert_level = 'red') as red,
  ROUND(AVG(matchup_quality_pct), 1) as matchup_q,
  ROUND(AVG(player_history_quality_pct), 1) as history_q,
  ROUND(AVG(vegas_quality_pct), 1) as vegas_q,
  ROUND(AVG(game_context_quality_pct), 1) as game_ctx_q,
  ROUND(AVG(default_feature_count), 1) as avg_defaults,
  ROUND(COUNTIF(cache_miss_fallback_used) * 100.0 / NULLIF(COUNT(*), 0), 1) as cache_miss_pct
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date = CURRENT_DATE()"
```

**Expected Results**:

| Metric | Good | Warning | Action |
|--------|------|---------|--------|
| `ready_pct` | >= 80% | < 60% | 🔴 Check which processor didn't run |
| `red` alerts | < 5% | > 15% | 🔴 Investigate `quality_alerts` array |
| `matchup_q` | >= 70 | < 50 | 🔴 Session 132 recurrence! Check composite factors |
| `history_q` | >= 80 | < 60 | ⚠️ Check player_daily_cache |
| `vegas_q` | >= 40 | < 30 | ⚠️ Normal for early morning (lines not yet set) |
| `avg_defaults` | < 3 | > 6 | ⚠️ Multiple features using fallback values |
| `cache_miss_pct` | 0% | > 0% | ⚠️ Cache/feature store player list mismatch (Session 147) |

**If `matchup_q < 50` (Session 132 pattern)**:
1. 🔴 P1 CRITICAL: Matchup data missing for significant portion of players
2. Check if `player-composite-factors-upcoming` job ran at 5 AM ET
3. Manually trigger composite factors processor:
   ```bash
   curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"processors": ["PlayerCompositeFactorsProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'
   ```
4. Then refresh ML Feature Store:
   ```bash
   curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"processors": ["MLFeatureStoreProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'
   ```

**Check matchup data status (legacy) + quality in predictions**:

```bash
bq query --use_legacy_sql=false "
-- Verify predictions quality tracking
SELECT
  COALESCE(matchup_data_status, 'NULL') as status,
  COUNT(*) as predictions,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(low_quality_flag = TRUE) as low_quality_count
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
GROUP BY status"
```

**Check prediction timing and quality gate enforcement (Session 139/140)**:

```bash
bq query --use_legacy_sql=false "
-- Verify prediction_made_before_game is populated and quality gate blocks
SELECT
  prediction_made_before_game,
  prediction_run_mode,
  COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
GROUP BY 1, 2"
```

**Expected Results**:
- `prediction_made_before_game = TRUE`: All pre-game predictions
- `prediction_made_before_game = FALSE`: Only if BACKFILL mode ran for this date
- If `prediction_made_before_game` is NULL: deployment hasn't landed yet -- check prediction-worker

**Quality Gate Hard Floor (Session 139)**:
- The quality gate now blocks predictions for `quality_alert_level = 'red'` or `matchup_quality_pct < 50` in ALL modes (including LAST_CALL)
- If players are blocked, check `#nba-alerts` for `PREDICTIONS_SKIPPED` alerts with root cause and BACKFILL instructions
- The `QualityHealer` module automatically re-triggers Phase 4 processors on quality failure before giving up

**Reference**: Session 99 handoff, Session 134 quality insight, Session 139 field adoption, Session 140 deployment

### Phase 0.485: Betting Line Source Validation (Session 152)

**IMPORTANT**: Verify that betting line scrapers collected data for all scheduled games and that lines flow into the feature store.

**Why this matters**: `check_vegas_line_coverage.sh` checks player-level % in the feature store but can't distinguish "sportsbook doesn't offer this line" from "our scraper failed." This check validates at the game level that our scrapers ran and collected lines from both sources (Odds API + BettingPros).

**When to run**: Pre-game validation (confirms lines are ready before predictions run).

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Game-level betting line source coverage
WITH scheduled AS (
  SELECT DISTINCT home_team_tricode, away_team_tricode
  FROM \`nba-props-platform.nba_reference.nba_schedule\`
  WHERE game_date = CURRENT_DATE() AND game_status IN (1, 2, 3)
),
odds_api AS (
  SELECT home_team_abbr, away_team_abbr,
         COUNT(DISTINCT player_lookup) as player_count
  FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
  WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL AND points_line > 0
  GROUP BY 1, 2
),
bettingpros AS (
  SELECT player_team, COUNT(DISTINCT player_lookup) as player_count
  FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
  WHERE game_date = CURRENT_DATE() AND market_type = 'points'
    AND points_line IS NOT NULL AND points_line > 0
  GROUP BY 1
)
SELECT
  CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup,
  COALESCE(oa.player_count, 0) as odds_api_players,
  COALESCE(bp_home.player_count, 0) + COALESCE(bp_away.player_count, 0) as bettingpros_players,
  CASE WHEN COALESCE(oa.player_count, 0) > 0 OR COALESCE(bp_home.player_count, 0) + COALESCE(bp_away.player_count, 0) > 0
       THEN 'OK' ELSE 'MISSING' END as status
FROM scheduled s
LEFT JOIN odds_api oa ON s.home_team_tricode = oa.home_team_abbr AND s.away_team_tricode = oa.away_team_abbr
LEFT JOIN bettingpros bp_home ON s.home_team_tricode = bp_home.player_team
LEFT JOIN bettingpros bp_away ON s.away_team_tricode = bp_away.player_team
ORDER BY status DESC, matchup"
```

**Pipeline flow check** (players with raw lines but missing from feature store):

```bash
bq query --use_legacy_sql=false "
WITH raw_players AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
  WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL AND points_line > 0
),
fs AS (
  SELECT player_lookup, feature_25_quality
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
  WHERE game_date = CURRENT_DATE()
)
SELECT
  COUNT(r.player_lookup) as raw_players_with_lines,
  COUNTIF(fs.player_lookup IS NOT NULL) as in_feature_store,
  COUNTIF(fs.player_lookup IS NULL) as dropped_in_pipeline
FROM raw_players r
LEFT JOIN fs ON r.player_lookup = fs.player_lookup"
```

**Expected Results**:

| Metric | Good | Warning | Action |
|--------|------|---------|--------|
| Games with either source | 100% | < 100% | Check scraper logs for missing games |
| Odds API game coverage | >= 80% | < 60% | Check Odds API scraper + quota |
| BettingPros game coverage | >= 80% | < 60% | Check BettingPros scraper |
| Pipeline drops | 0 | > 0 | Check Phase 4 player roster — dropped players not in upcoming game context |

**If games MISSING from all sources**:
1. Check if scraper ran: look for recent scraper logs for `odds_api_player_props` and `bettingpros_props`
2. Check if lines exist for that game at sportsbooks (new/obscure matchups may not have props yet)
3. If scraper ran but no data: check for API errors, rate limits, or changed endpoints

**If pipeline drops > 0**:
1. Players with raw lines but not in feature store are likely not in the upcoming game context
2. Check if the dropped players are on the schedule (traded, G-League, inactive)
3. This is normal for a small number of fringe players

**Standalone script** (for deeper investigation or multi-day checks):
```bash
python bin/monitoring/check_betting_line_sources.py --days 7
```

**Reference**: Session 152, complements `check_vegas_line_coverage.sh`

### Phase 0.487: Training Data Contamination Check (Session 158 - CRITICAL)

**IMPORTANT**: Verify the V9 training window has low default contamination.

**Why this matters**: Session 157 discovered 33.2% of V9 training data was contaminated with default feature values due to upstream processor failures. This silent contamination degraded model accuracy. Three prevention layers were added in Sessions 157-158.

**Quick check** (< 5 seconds):
```bash
./bin/monitoring/check_training_data_quality.sh
```

**Expected Results**:
| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Contamination % | < 5% | 5-15% | > 15% |
| Quality-ready % | > 60% | 40-60% | < 40% |
| Avg defaults | < 2 | 2-5 | > 5 |

**If contamination > 5%**:
1. Check which months have highest contamination (monthly breakdown in script output)
2. Run backfill for affected date range:
   ```bash
   ./bin/backfill/run_phase4_backfill.sh --start-date YYYY-MM-DD --end-date YYYY-MM-DD --no-resume
   ```
3. After backfill, re-run the check to verify improvement

**If contamination > 15%**:
- CRITICAL: This will significantly impact model accuracy
- Check Phase 4 processor logs for failures
- Verify deployment drift hasn't reintroduced old code without quality scoring

**Reference**: Session 157 contamination discovery, Session 158 prevention mechanisms

### Phase 0.49: Duplicate Team Record Detection (Session 103 - CRITICAL)

**IMPORTANT**: Check for duplicate team_offense_game_summary records with conflicting stats.

**Why this matters**: Session 103 discovered that duplicate team records with different game_id formats cause usage_rate calculation errors. When evening processing (partial data) and morning processing (full data) create records with different game_ids, the MERGE creates duplicates instead of updating. This caused 51% of duplicate cases to have different stats, with some FGA differences as high as 82.

**Root Cause**:
- PRIMARY_KEY_FIELDS = ['game_id', 'team_abbr']
- Different processing runs use different game_id formats (AWAY_HOME vs HOME_AWAY)
- MERGE sees different keys → creates new records instead of updating

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Check for duplicate team records with different stats (Session 103)
WITH duplicates AS (
  SELECT
    game_date,
    team_abbr,
    COUNT(*) as record_count,
    COUNT(DISTINCT fg_attempts) as unique_fga_values,
    MAX(fg_attempts) - MIN(fg_attempts) as fga_spread,
    STRING_AGG(DISTINCT game_id ORDER BY game_id) as game_ids
  FROM nba_analytics.team_offense_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date, team_abbr
  HAVING COUNT(*) > 1
)
SELECT
  game_date,
  team_abbr,
  record_count,
  fga_spread,
  game_ids,
  CASE
    WHEN fga_spread > 20 THEN '🔴 CRITICAL'
    WHEN fga_spread > 5 THEN '🟡 WARNING'
    WHEN fga_spread > 0 THEN '⚠️ MINOR'
    ELSE '✅ OK (identical)'
  END as status
FROM duplicates
WHERE fga_spread > 0
ORDER BY fga_spread DESC"
```

**Expected Result**:
- No rows returned (no duplicates with different stats)
- Or only rows with `status = ✅ OK (identical)`

**Alert Thresholds**:

| FGA Spread | Severity | Impact |
|------------|----------|--------|
| 0 | OK | Duplicates exist but have same stats |
| 1-5 | MINOR | Small rounding differences |
| 6-20 | WARNING | Partial vs full game data |
| >20 | CRITICAL | Major data quality issue, usage_rate will be wrong |

**If CRITICAL or WARNING detected**:

1. **Immediate**: The usage_rate values for affected teams' players may be incorrect
2. **Check player_game_summary**: See if players on those teams have wrong usage_rate
   ```bash
   bq query --use_legacy_sql=false "
   SELECT player_lookup, usage_rate, minutes_played
   FROM nba_analytics.player_game_summary
   WHERE game_date = 'YYYY-MM-DD'
     AND team_abbr = 'AFFECTED_TEAM'
     AND usage_rate > 50  -- Suspiciously high values indicate wrong team stats used
   ORDER BY usage_rate DESC"
   ```
3. **Root cause**: Check which processing run created partial data
4. **Fix**: Run cleanup script to remove duplicates (keep highest possessions)

**Cleanup Command** (if needed):
```bash
# Preview duplicates to remove
PYTHONPATH=. python bin/maintenance/cleanup_team_duplicates.py --dry-run

# Execute cleanup
PYTHONPATH=. python bin/maintenance/cleanup_team_duplicates.py --execute
```

**Prevention**: Session 103 changed PRIMARY_KEY_FIELDS to ['game_date', 'team_abbr'] to prevent future duplicates.

**Reference**: Session 103 handoff, investigation of usage_rate spot check failures

### Phase 0.495: Team Stats Completeness Check (Session 105 - NEW)

**IMPORTANT**: Verify all teams that played have team_offense_game_summary records.

**Why this matters**: Session 105 discovered that some teams were missing from team_offense_game_summary even after duplicate cleanup. This caused usage_rate to be NULL for those teams' players, degrading prediction quality.

**What to check**:

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
-- Compare expected teams (from schedule) vs actual teams (from team_offense)
WITH expected_teams AS (
  SELECT game_date, away_team_tricode as team_abbr FROM nba_reference.nba_schedule
  WHERE game_date = DATE('${GAME_DATE}') AND game_status = 3
  UNION ALL
  SELECT game_date, home_team_tricode FROM nba_reference.nba_schedule
  WHERE game_date = DATE('${GAME_DATE}') AND game_status = 3
),
actual_teams AS (
  SELECT game_date, team_abbr FROM nba_analytics.team_offense_game_summary
  WHERE game_date = DATE('${GAME_DATE}')
)
SELECT
  e.game_date,
  COUNT(DISTINCT e.team_abbr) as expected,
  COUNT(DISTINCT a.team_abbr) as actual,
  COUNT(DISTINCT e.team_abbr) - COUNT(DISTINCT a.team_abbr) as missing,
  STRING_AGG(DISTINCT CASE WHEN a.team_abbr IS NULL THEN e.team_abbr END ORDER BY e.team_abbr) as missing_teams
FROM expected_teams e
LEFT JOIN actual_teams a ON e.game_date = a.game_date AND e.team_abbr = a.team_abbr
GROUP BY e.game_date"
```

**Expected Result**:
- `missing = 0` (all teams have records)
- `missing_teams` is NULL

**If missing teams found**:

| Missing | Severity | Action |
|---------|----------|--------|
| 1-2 teams | P2 WARNING | Reprocess team_offense for that date |
| 3+ teams | P1 CRITICAL | Major processing failure |

**Fix Command**:
```bash
# Reprocess team_offense_game_summary for the affected date
ANALYTICS_URL="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app"
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "${ANALYTICS_URL}/process-date-range" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "processors": ["TeamOffenseGameSummaryProcessor"],
    "backfill_mode": true,
    "trigger_reason": "missing_team_stats_fix"
  }'
```

**Reference**: Session 105 handoff - fixed MEM, MIN, NOP missing for Feb 2

### Phase 0.5: Pre-Game Signal Check (NEW - Session 70)

**IMPORTANT**: Check daily prediction signals for model performance indicators.

**Why this matters**: The pct_over signal (% of predictions recommending OVER) correlates with model performance. When pct_over <25% (UNDER_HEAVY), historical hit rate drops from 82% → 54% on high-edge picks (p=0.0065).

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Check today's pre-game signals for V9
SELECT
  game_date,
  system_id,
  total_picks,
  high_edge_picks,
  pct_over,
  pct_under,
  skew_category,
  volume_category,
  daily_signal,
  signal_explanation
FROM \`nba-props-platform.nba_predictions.daily_prediction_signals\`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
ORDER BY system_id"
```

**Expected**: Signal data exists for today

**Signal Interpretation**:

| Signal | pct_over | Meaning | Historical Performance |
|--------|----------|---------|----------------------|
| 🟢 **GREEN** | 25-40% | Balanced predictions | 82% hit rate on high-edge picks |
| 🟡 **YELLOW** | >40% OR <3 high-edge picks | Unusual skew or low volume | Monitor closely |
| 🔴 **RED** | <25% | Heavy UNDER skew | 54% hit rate - barely above breakeven |

**Thresholds**:
- **GREEN**: Normal operation, full confidence in picks
- **YELLOW**: Caution - monitor performance closely
- **RED**: Warning - reduce bet sizing or skip day

**If RED signal detected**:
1. ⚠️ P2 WARNING: Model showing heavy UNDER skew
2. Impact: High-edge picks historically 54% vs 82% on balanced days
3. Recommendation: Reduce bet sizing by 50% or skip high-edge picks today
4. Note: This is a pre-game indicator, not a hard failure
5. Track actual performance tonight to validate signal

**If signal data missing**:
1. Check if predictions exist for today: `bq query "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'"`
2. If predictions exist but no signal → Signal calculation may need manual run
3. Run signal calculation: See `docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md` for INSERT query

**Output Format**:

```
### Pre-Game Signal Check
| Metric | Value | Status |
|--------|-------|--------|
| pct_over | 35.5% | 🟢 BALANCED |
| high_edge_picks | 8 | ✅ OK |
| Daily Signal | GREEN | Full confidence |

Signal: Balanced signals - historical 82% hit rate on high-edge picks
```

Or if RED:

```
### Pre-Game Signal Check
| Metric | Value | Status |
|--------|-------|--------|
| pct_over | 10.6% | 🔴 UNDER_HEAVY |
| high_edge_picks | 4 | ✅ OK |
| Daily Signal | RED | ⚠️ CAUTION |

⚠️ WARNING: Heavy UNDER skew detected
   - Historical performance: 54% hit rate vs 82% on balanced days
   - Statistical significance: p=0.0065
   - Recommendation: Reduce bet sizing by 50% or skip high-edge picks
   - This is Day 1 analysis - validate signal tonight

Signal: Heavy UNDER skew - historically 54% hit rate vs 82% on balanced days
```

**Related Documentation**:
- Signal discovery: `docs/08-projects/current/pre-game-signals-strategy/README.md`
- System design: `docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md`
- Statistical validation: Session 70 findings (23 days, p=0.0065)

### Phase 0.55: Model Bias Check (Session 101, fixed Session 162)

**IMPORTANT**: If RED signal detected, check for underlying model bias.

**CRITICAL METHODOLOGY NOTE (Session 161)**: Use **season average** tiers, not `actual_points` tiers. Tiering by actual_points is survivorship bias. See Phase 0.466 note above.

**When to run**: Only if RED signal detected in Phase 0.5, OR if high-edge picks have been losing consistently.

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Check model bias by player tier using SEASON AVERAGE (correct methodology)
WITH player_avgs AS (
  SELECT player_lookup, AVG(actual_points) as season_avg
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v9' AND game_date >= '2025-11-01'
  GROUP BY 1
)
SELECT
  CASE
    WHEN pa.season_avg >= 25 THEN '1_Stars (25+ avg)'
    WHEN pa.season_avg >= 15 THEN '2_Starters (15-24 avg)'
    WHEN pa.season_avg >= 8 THEN '3_Role (8-14 avg)'
    ELSE '4_Bench (<8 avg)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(p.predicted_points), 1) as avg_predicted,
  ROUND(AVG(p.actual_points), 1) as avg_actual,
  ROUND(AVG(p.predicted_points - p.actual_points), 1) as bias,
  CASE
    WHEN ABS(AVG(p.predicted_points - p.actual_points)) > 5 THEN '🔴 CRITICAL'
    WHEN ABS(AVG(p.predicted_points - p.actual_points)) > 3 THEN '🟡 WARNING'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.prediction_accuracy p
JOIN player_avgs pa USING (player_lookup)
WHERE p.system_id = 'catboost_v9'
  AND p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND p.actual_points IS NOT NULL
GROUP BY 1
ORDER BY 1"
```

**Expected**: Bias < ±3 points for all tiers (Session 161 showed -0.3 for stars with correct methodology)

**Alert Thresholds**:

| Tier | Acceptable Bias | Warning | Critical |
|------|-----------------|---------|----------|
| Stars (25+ avg) | ±3 pts | ±3-5 pts | >±5 pts |
| Starters | ±2 pts | ±2-4 pts | >±4 pts |
| Role/Bench | ±3 pts | ±3-5 pts | >±5 pts |

**If CRITICAL bias detected**:

| Finding | Root Cause | Action |
|---------|------------|--------|
| Stars bias < -5 | Model regression-to-mean | Consider recalibration or retrain |
| Bench bias > +5 | Model over-predicting low scorers | Add tier features to model |
| All tiers biased same direction | Global model drift | Retrain immediately |

**Investigation if bias found**:

1. Check recent high-edge pick performance:
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as high_edge_picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND ABS(predicted_points - line_value) >= 5
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC"
```

2. Check if bias is getting worse over time (using season_avg tiers):
```bash
bq query --use_legacy_sql=false "
WITH player_avgs AS (
  SELECT player_lookup, AVG(actual_points) as season_avg
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v9' AND game_date >= '2025-11-01'
  GROUP BY 1
)
SELECT
  DATE_TRUNC(p.game_date, WEEK) as week,
  ROUND(AVG(CASE WHEN pa.season_avg >= 25 THEN p.predicted_points - p.actual_points END), 1) as star_bias,
  ROUND(AVG(CASE WHEN pa.season_avg < 8 THEN p.predicted_points - p.actual_points END), 1) as bench_bias
FROM nba_predictions.prediction_accuracy p
JOIN player_avgs pa USING (player_lookup)
WHERE p.system_id = 'catboost_v9'
  AND p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY 1
ORDER BY 1 DESC"
```

**Recommended Fixes** (reference `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`):
- **Quick**: Post-prediction recalibration by tier
- **Proper**: Retrain with tier features
- **Best**: Switch to quantile regression

**Reference**: Session 161 model eval methodology, Session 101 handoff

### Phase 0.6: Orchestrator Health (CRITICAL)

**IMPORTANT**: Check orchestrator health BEFORE other validations. If ANY Phase 0.6 check fails, this is a P1 CRITICAL issue - STOP and report immediately.

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

#### Check 4: Firestore Trigger Status (Session 198 - CRITICAL)

**MANDATORY CHECK**: Detects silent orchestrator failures where processors complete but orchestrator never triggers.

**Note (Session 205):** The phase2-to-phase3-orchestrator has been REMOVED. Phase 2→3 transitions via direct Pub/Sub subscription (`nba-phase3-analytics-sub`), no orchestrator needed. Only Phase 3→4, 4→5, and 5→6 orchestrators remain.

**The Problem**: Session 198 discovered orchestrator failure went undetected for 3 days. All processors completed but orchestrator never set `_triggered: true` in Firestore, blocking downstream data flow.

**What to check**:

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime, timedelta
import sys

db = firestore.Client(project='nba-props-platform')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
today = datetime.now().strftime('%Y-%m-%d')

critical_issues = []

# NOTE: Phase 2→3 orchestrator has been REMOVED (Session 205).
# Phase 3 is triggered directly by Pub/Sub subscription, not an orchestrator.
# We only check Phase 3→4 orchestrator (the first FUNCTIONAL orchestrator).

print(f"\n=== Phase 2→3 Transition ({yesterday}) ===")
print(f"  ℹ️  No orchestrator (direct Pub/Sub). Checking Phase 3 data instead...")
# Verify Phase 3 actually ran by checking for data
from google.cloud import bigquery
bq = bigquery.Client(project='nba-props-platform')
result = list(bq.query(f"""
    SELECT COUNT(DISTINCT player_lookup) as players, COUNT(DISTINCT game_id) as games
    FROM nba_analytics.player_game_summary
    WHERE game_date = '{yesterday}'
""").result())
if result and result[0].players > 0:
    print(f"  ✅ Phase 3 ran: {result[0].players} players, {result[0].games} games")
else:
    # Check if there were games yesterday
    sched = list(bq.query(f"""
        SELECT COUNT(*) as games FROM nba_reference.nba_schedule
        WHERE game_date = '{yesterday}' AND game_status = 3
    """).result())
    if sched and sched[0].games == 0:
        print(f"  ℹ️  No completed games yesterday - Phase 3 data not expected")
    else:
        print(f"  ⚠️  WARNING: No Phase 3 data for {yesterday} but games were played!")
        print(f"     Check Phase 3 service logs for errors")

# Check Phase 3→4 orchestrator (today's processing date)
print(f"\n=== Phase 3→4 Orchestrator ({today}) ===")
doc = db.collection('phase3_completion').document(today).get()

if doc.exists:
    data = doc.to_dict()
    processors_complete = len([k for k in data.keys() if not k.startswith('_')])
    triggered = data.get('_triggered', False)
    trigger_reason = data.get('_trigger_reason', 'N/A')

    print(f"  Processors complete: {processors_complete}/5")
    print(f"  Triggered: {triggered}")
    print(f"  Trigger reason: {trigger_reason}")

    # CRITICAL: All processors complete but not triggered
    if processors_complete >= 5 and not triggered:
        critical_issues.append({
            'phase': 'Phase 3→4',
            'date': today,
            'processors': processors_complete,
            'triggered': triggered
        })
        print(f"  🔴 P0 CRITICAL: Orchestrator stuck!")
        print(f"     {processors_complete}/5 processors complete but _triggered=False")
        print(f"     Manual trigger: gcloud scheduler jobs run phase3-to-phase4")
    elif triggered:
        print(f"  ✅ Orchestrator triggered successfully")
    else:
        print(f"  ⏳ Waiting for processors ({processors_complete}/5)")
else:
    print("  ⚠️  No completion record found")

# Report critical issues
if critical_issues:
    print("\n" + "="*60)
    print("🚨 ORCHESTRATOR FAILURES DETECTED 🚨")
    print("="*60)
    for issue in critical_issues:
        print(f"\nPhase: {issue['phase']}")
        print(f"Date: {issue['date']}")
        print(f"Status: {issue['processors']} processors complete, NOT TRIGGERED")
        print(f"Impact: Downstream data pipeline BLOCKED")
        print(f"Action: gcloud scheduler jobs run phase3-to-phase4 --location=us-west2")
    print("\nRefer to: docs/02-operations/ORCHESTRATOR-HEALTH.md")
    sys.exit(1)
else:
    print("\n✅ All orchestrator trigger checks passed")

EOF

if [ $? -ne 0 ]; then
    echo ""
    echo "🔴 P0 CRITICAL: Orchestrator Health Check FAILED"
    echo "See output above for manual trigger commands"
    exit 1
fi
```

**Expected Output**:
```
=== Phase 2→3 Transition (2026-02-10) ===
  ℹ️  No orchestrator (direct Pub/Sub). Checking Phase 3 data instead...
  ✅ Phase 3 ran: 280 players, 6 games

=== Phase 3→4 Orchestrator (2026-02-11) ===
  Processors complete: 5/5
  Triggered: True
  Trigger reason: all_processors_complete
  ✅ Orchestrator triggered successfully

✅ All orchestrator trigger checks passed
```

**If orchestrator stuck** (Session 198 scenario):
```
=== Phase 3→4 Orchestrator (2026-02-09) ===
  Processors complete: 5/5
  Triggered: False
  Trigger reason: N/A
  🔴 P0 CRITICAL: Orchestrator stuck!
     6/6 processors complete but _triggered=False
     Manual trigger: gcloud scheduler jobs run same-day-phase3

🚨 ORCHESTRATOR FAILURES DETECTED 🚨
============================================================

Phase: Phase 2→3
Date: 2026-02-09
Status: 6 processors complete, NOT TRIGGERED
Impact: Downstream data pipeline BLOCKED
Action: gcloud scheduler jobs run same-day-phase3 --location=us-west2
```

**Critical thresholds**:
- Phase 2→3: Alert if processors >= 5 and `_triggered=False`
- Phase 3→4: Alert if processors >= 5 and `_triggered=False`

**Why 5 processors instead of 6**:
- Provides early warning even if one processor hasn't reported yet
- Session 198 had 6/6 complete but still failed, so we want to catch it early

**Manual trigger commands**:
```bash
# Phase 2→3 (same-day analytics)
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Phase 3→4 (precompute)
gcloud scheduler jobs run phase3-to-phase4 --location=us-west2

# Phase 4→5 (predictions)
gcloud scheduler jobs run phase4-to-phase5 --location=us-west2
```

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
    procs = len([k for k in data.keys() if not k.startswith('_')])
    print(f"  Processors complete: {procs}")
    print(f"  Note: Phase 2→3 orchestrator REMOVED (Session 205). _triggered not expected.")
else:
    print("  ℹ️  No completion record found (may be normal)")

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

If ANY Phase 0.6 check fails, send alert to critical error channel:

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
- Critical errors: `SLACK_WEBHOOK_URL_ERROR` → #app-error-alerts ⚠️ **Use this for Phase 0.6 failures**
- Warnings: `SLACK_WEBHOOK_URL_WARNING` → #nba-alerts

#### Check 5: Orchestrator IAM Permissions (Session 205 - CRITICAL)

**MANDATORY CHECK**: Verify all orchestrators have required IAM permissions to be invoked by Pub/Sub.

**Note (Session 205):** The phase2-to-phase3-orchestrator has been REMOVED. Only 3 orchestrators remain.

**The Problem**: Session 205 discovered orchestrators lacked `roles/run.invoker` permission, causing 7+ days of silent failures. Pub/Sub published messages but Cloud Run rejected invocations due to missing permissions.

**Root Cause**: `gcloud functions deploy` does not preserve IAM policies. Redeployments can wipe IAM bindings.

**What to check**:

```bash
# Check all 3 remaining orchestrators for IAM permissions
python3 << 'EOF'
import subprocess
import sys

orchestrators = [
    'phase3-to-phase4-orchestrator',
    'phase4-to-phase5-orchestrator',
    'phase5-to-phase6-orchestrator'
]

missing_permissions = []
service_account = '756957797294-compute@developer.gserviceaccount.com'

print("\n=== Orchestrator IAM Permission Check ===\n")

for orch in orchestrators:
    try:
        result = subprocess.run(
            ['gcloud', 'run', 'services', 'get-iam-policy', orch,
             '--region=us-west2', '--project=nba-props-platform',
             '--format=json'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"  ❌ {orch}: Failed to get IAM policy")
            missing_permissions.append(orch)
            continue

        # Check if roles/run.invoker exists for service account
        if 'roles/run.invoker' in result.stdout and service_account in result.stdout:
            print(f"  ✅ {orch}: IAM permissions OK")
        else:
            print(f"  🔴 {orch}: MISSING roles/run.invoker permission!")
            missing_permissions.append(orch)

    except Exception as e:
        print(f"  ❌ {orch}: Error checking IAM - {e}")
        missing_permissions.append(orch)

if missing_permissions:
    print(f"\n🔴 P0 CRITICAL: {len(missing_permissions)} orchestrator(s) missing IAM permissions!")
    print(f"   Affected: {', '.join(missing_permissions)}")
    print(f"\n   Impact: Pub/Sub cannot invoke these orchestrators")
    print(f"           Pipeline will stall when processors complete")
    print(f"\n   Fix command:")
    for orch in missing_permissions:
        print(f"   gcloud run services add-iam-policy-binding {orch} \\")
        print(f"     --region=us-west2 \\")
        print(f"     --member='serviceAccount:{service_account}' \\")
        print(f"     --role='roles/run.invoker' \\")
        print(f"     --project=nba-props-platform")
        print()
    sys.exit(1)
else:
    print(f"\n✅ All orchestrators have correct IAM permissions")
    sys.exit(0)
EOF
```

**Expected Result**: All 3 orchestrators show `✅ IAM permissions OK`

**If MISSING**:
- 🔴 P0 CRITICAL: Orchestrators cannot be invoked by Pub/Sub
- Impact: Silent pipeline failures - processors complete but orchestrators never trigger
- Symptoms: Firestore shows processors complete but `_triggered=False`
- Action: Run fix command above immediately

**Prevention**: Deployment scripts now auto-set IAM permissions (Session 205 fix), but verify after any manual deployments.

**Note**: phase2-to-phase3-orchestrator was REMOVED in Session 205 (was monitoring-only, not needed).

**Reference**: Session 205 handoff

**If ALL Phase 0.6 checks pass**: Continue to Phase 0.7

**If ANY Phase 0.6 check fails**: STOP, report issue with P1 CRITICAL severity, do NOT continue to Phase 1

### Phase 0.7: Vegas Line Coverage Check (Session 77)

**Purpose**: Monitor Vegas line availability to detect coverage regressions early.

**When to run**: Every day, checks last 1 day of data

**What to check**:

```bash
./bin/monitoring/check_vegas_line_coverage.sh --days 1
```

**Expected result**:
- Coverage: ≥80% (healthy)
- Status: ✅ PASS

**Alert thresholds**:
- <80%: 🟡 WARNING
- <50%: 🔴 CRITICAL

**If issues detected**:

| Issue | Severity | Action |
|-------|----------|--------|
| Coverage <50% | P1 CRITICAL | Investigate BettingPros scraper, check recent logs |
| Coverage 50-79% | P2 WARNING | Monitor for trend, may be temporary |
| Coverage ≥80% | OK | No action needed |

**Common causes**:
- BettingPros scraper failures
- BettingPros API changes
- Temporary unavailability of betting lines

**Investigation commands**:
```bash
# Check recent BettingPros scrapes
bq query --use_legacy_sql=false "
  SELECT game_date, COUNT(*) as records, COUNT(DISTINCT player_lookup) as players
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date >= CURRENT_DATE() - 3
  GROUP BY game_date
  ORDER BY game_date DESC"

# Check scraper logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="nba-phase1-scrapers"
  AND jsonPayload.scraper="bettingpros"' \
  --limit=20 --format=json
```

### Phase 0.8: Grading Completeness Check (Session 77)

**Purpose**: Ensure predictions are being graded consistently across all models.

**When to run**: Every day, checks last 3 days of data

**What to check**:

```bash
./bin/monitoring/check_grading_completeness.sh --days 3
```

**Expected result**:
- All models: ≥80% graded
- Status: ✅ PASS

**Alert thresholds**:
- Model <80%: 🟡 WARNING
- Model <50%: 🔴 CRITICAL

**If issues detected**:

| Issue | Severity | Action |
|-------|----------|--------|
| Any model <50% | P1 CRITICAL | Investigate prediction-grader service |
| Any model 50-79% | P2 WARNING | Monitor for trend |
| All models ≥80% | OK | No action needed |

**Common causes**:
- Grader service not running
- Pub/Sub subscription issues
- Feature store data unavailable for grading

**Investigation commands**:
```bash
# Check grader service logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-grader"' \
  --limit=20 --format=json

# Check Pub/Sub subscription backlog
gcloud pubsub subscriptions describe prediction-grader-sub \
  --format="value(numUndeliveredMessages)"

# Manual grading trigger (if needed)
curl -X POST https://prediction-grader-f7p3g7f6ya-wl.a.run.app/grade \
  -H "Content-Type: application/json" \
  -d '{"game_date": "YYYY-MM-DD"}'
```

### Phase 0.9: Kalshi Data Health (Session 79)

**Purpose**: Monitor Kalshi prediction market data availability.

**When to run**: Every day after 7 AM UTC (2 AM ET scrape should complete by then)

**What to check**:

```sql
-- Check Kalshi data for today
SELECT
  game_date,
  COUNT(*) as total_props,
  COUNT(DISTINCT player_lookup) as players,
  COUNTIF(prop_type = 'points') as points_props,
  COUNTIF(liquidity_score = 'HIGH') as high_liquidity
FROM `nba-props-platform.nba_raw.kalshi_player_props`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;
```

**Expected result**:
- Total props: 200-400 (depends on games scheduled)
- Players: 40-60
- Points props: ≥40 (for prediction enrichment)
- High liquidity: ≥50%

**Alert thresholds**:
- 0 props: 🔴 CRITICAL (scraper failed)
- <50 props: 🟡 WARNING (partial data)
- ≥100 props: ✅ OK

**If issues detected**:

| Issue | Severity | Action |
|-------|----------|--------|
| 0 props for today | P2 WARNING | Check Kalshi scraper logs, may be no games or API issue |
| <50 props | P3 LOW | May be limited Kalshi coverage, not critical |

**Note**: Kalshi coverage is supplementary - predictions work fine without it. This is monitoring only.

**Investigation commands**:
```bash
# Check Kalshi scraper logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="nba-scrapers"
  AND textPayload=~"kalshi"' \
  --limit=20 --freshness=6h

# Manual trigger if needed
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper":"kalshi_player_props","date":"TODAY","group":"prod"}'
```

### Phase 0.95: Execution Logger Health (Session 85)

**Purpose**: Detect BigQuery write failures in prediction worker execution logging.

**Why this matters**: Session 85 discovered that NULL values in REPEATED fields (like `line_values_requested`) cause BigQuery writes to fail. Failed entries get re-queued and fail forever, creating a perpetual retry loop and log data loss.

**What to check**:

```bash
# Check for execution logger errors in last 6 hours
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND textPayload=~"execution_logger.*ERROR"' \
  --limit=10 --freshness=6h \
  --format="table(timestamp,textPayload)"
```

**Expected result**: Zero errors (or only old errors from before the fix)

**Known error patterns**:

| Error Pattern | Cause | Status |
|---------------|-------|--------|
| `line_values_requested.*NULL` | NULL in REPEATED field | ✅ Fixed (Session 85) |
| `JSON table encountered too many errors` | Schema mismatch | Investigate |
| `Error flushing execution log buffer` | BigQuery write failure | Investigate |

**Alert thresholds**:
- 0 errors: ✅ OK
- 1-5 errors: 🟡 WARNING - May be transient or old errors
- >5 errors: 🔴 CRITICAL - Active issue, logs being lost

**If errors detected**:

1. Check if errors are recent (after latest deployment):
   ```bash
   gcloud run services describe prediction-worker --region=us-west2 \
     --format="value(status.latestReadyRevisionName)"
   ```

2. Check specific error details:
   ```bash
   gcloud logging read 'resource.labels.service_name="prediction-worker"
     AND textPayload=~"BigQuery errors:"' --limit=3 --freshness=6h
   ```

3. If NULL field errors persist, verify fix is deployed (Session 85 commit: `409e819e`)

**Root cause reference**: `predictions/worker/execution_logger.py` - REPEATED fields must be empty arrays `[]`, never JSON `null`.

### Phase 0.96: Model Attribution Check (Session 91)

**Purpose**: Verify model attribution fields (model_file_name, model_training_start_date, etc.) are populated for predictions.

**Why this matters**: NULL model attribution makes it impossible to track which model version generated predictions, preventing proper model performance analysis and debugging.

**What to check**:

```bash
bq query --use_legacy_sql=false "
-- Check model attribution for recent predictions
SELECT
  DATE(created_at) as created_date,
  model_file_name,
  COUNT(*) as predictions,
  CASE
    WHEN model_file_name IS NULL THEN '🔴 NULL'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1, 2
ORDER BY 1 DESC"
```

**Expected result**:
- `model_file_name` should be populated (e.g., `catboost_v9_feb_02_retrain.cbm`)
- No NULL values for predictions created after Session 88 fix (2026-02-03 03:08 UTC)

**Alert thresholds**:
- All populated: ✅ OK - Model attribution working correctly
- Some NULL (before fix): 🟡 INFO - Expected for pre-deployment predictions
- All NULL (after fix): 🔴 CRITICAL - Model attribution broken

**If CRITICAL (all NULL after fix deployment)**:

1. Check if fix is deployed:
   ```bash
   gcloud run services describe prediction-worker --region=us-west2 \
     --format="value(metadata.labels.commit-sha)"
   # Expected: 4ada201f or later
   ```

2. Check metadata structure in worker logs:
   ```bash
   gcloud logging read 'resource.labels.service_name="prediction-worker"
     AND textPayload=~"catboost_meta"' --limit=5 --freshness=6h
   ```

3. If fix is deployed but still NULL, investigate:
   - Check if CatBoostV9.predict() is returning metadata correctly
   - Check if worker.py is extracting nested metadata correctly
   - Reference: `predictions/worker/worker.py:1815-1834`

**Fix reference**: Commit `4ada201f` - Access nested `catboost_result.get('metadata', {})` for model attribution fields.

### Phase 0.97: Phase 6 Export Health (Session 91)

**Purpose**: Verify Phase 6 subset exporters are running and producing valid outputs.

**Why this matters**: Phase 6 exports power the public API. Missing or stale exports mean users see outdated predictions.

**What to check**:

```bash
# Check if today's exports exist
GAME_DATE=$(date +%Y-%m-%d)
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

echo "=== Phase 6 Export Health ==="

# Check picks files
gsutil ls -lh gs://nba-props-platform-api/v1/picks/${YESTERDAY}.json 2>/dev/null && \
  echo "✅ Yesterday picks exist" || echo "🔴 Yesterday picks MISSING"

gsutil ls -lh gs://nba-props-platform-api/v1/signals/${YESTERDAY}.json 2>/dev/null && \
  echo "✅ Yesterday signals exist" || echo "🔴 Yesterday signals MISSING"

# Check performance file freshness
PERF_TIME=$(gsutil stat gs://nba-props-platform-api/v1/subsets/performance.json 2>/dev/null | grep "Update time" | cut -d: -f2-)
echo "Performance file updated: ${PERF_TIME:-NOT FOUND}"

# Check definitions file exists
gsutil ls gs://nba-props-platform-api/v1/systems/subsets.json 2>/dev/null && \
  echo "✅ Subset definitions exist" || echo "🔴 Subset definitions MISSING"
```

**Expected result**:
- Yesterday's picks and signals files exist
- Performance file updated within last 2 hours (during active hours)
- Subset definitions file exists

**Alert thresholds**:
- All files present and fresh: ✅ OK
- Missing files: 🔴 CRITICAL
- Stale performance (>3 hours during 6 AM - 11 PM): 🟡 WARNING

**If files missing**:
1. Check phase5-to-phase6 orchestrator logs:
   ```bash
   gcloud functions logs read phase5-to-phase6 --region=us-west2 --limit=20
   ```

2. Check if exports can run manually:
   ```bash
   PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
     --date $(date -d "yesterday" +%Y-%m-%d) \
     --only subset-picks,daily-signals
   ```

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

### Phase 3D: Cache DNP Pollution Check (Session 123)

**Purpose**: Detect DNP players polluting the player_daily_cache

**Context**: Session 123 discovered that 78% of February caches were polluted with DNP players (players with no meaningful stats). This check prevents recurrence by validating yesterday's cache generation.

```bash
# Check yesterday's cache for DNP pollution
CACHE_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
-- DNP Pollution Check (Session 123 Corrected Query)
-- Checks for players with ONLY DNP games and no active games

WITH player_game_stats AS (
  SELECT
    player_lookup,
    COUNT(*) as total_games,
    COUNTIF(is_dnp = TRUE) as dnp_games,
    COUNTIF(is_dnp = FALSE) as active_games
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= DATE_SUB('${CACHE_DATE}', INTERVAL 30 DAY)
    AND game_date < '${CACHE_DATE}'
  GROUP BY player_lookup
)
SELECT
  pdc.cache_date,
  COUNT(DISTINCT pdc.player_lookup) as cached_players,
  COUNT(DISTINCT CASE
    WHEN pgs.active_games = 0 AND pgs.dnp_games > 0
    THEN pdc.player_lookup
  END) as dnp_only_players,
  ROUND(100.0 * COUNT(DISTINCT CASE
    WHEN pgs.active_games = 0 AND pgs.dnp_games > 0
    THEN pdc.player_lookup
  END) / NULLIF(COUNT(DISTINCT pdc.player_lookup), 0), 1) as dnp_pct
FROM \`nba-props-platform.nba_precompute.player_daily_cache\` pdc
LEFT JOIN player_game_stats pgs ON pdc.player_lookup = pgs.player_lookup
WHERE pdc.cache_date = '${CACHE_DATE}'
GROUP BY pdc.cache_date
"
```

**Expected Results**:
- **0 DNP-only players**: ✅ PASS (cache is clean)
- **1-2 DNP-only players**: ⚠️ WARNING (edge cases, investigate)
- **>2 DNP-only players**: 🔴 CRITICAL (DNP filter not working)

**DNP Pollution Thresholds**:
- **0%**: Excellent, cache is clean
- **<1%**: Acceptable (likely edge cases)
- **1-5%**: WARNING - investigate specific players
- **>5%**: CRITICAL - DNP filter broken, regenerate cache

**If DNP pollution found**:
1. Check if DNP filter is deployed in Phase 4:
   ```bash
   grep "is_dnp = FALSE" data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
   # Should show line 435 with DNP filter
   ```

2. Check Phase 4 deployment status:
   ```bash
   gcloud run services describe nba-phase4-precompute-processors \
     --region=us-west2 \
     --format="value(metadata.labels.commit-sha)"
   # Should be on commit ede3ab89 or later (contains DNP fix from 94087b90)
   ```

3. If filter is deployed but pollution exists, regenerate cache:
   ```bash
   python bin/regenerate_cache_bypass_bootstrap.py ${CACHE_DATE}
   ```

4. If filter is NOT deployed, deploy Phase 4:
   ```bash
   ./bin/deploy-service.sh nba-phase4-precompute-processors
   ```

**Important Note** (Session 123 Learning):
- DNP filter excludes DNP **games** from stats calculation
- It does NOT exclude players who have mixed DNP + active games
- This check only flags players with ONLY DNP games (no active games)
- Players with some DNP games and some active games are VALID

**Reference**: Session 123 DNP validation emergency, commit 94087b90

### Phase 3E: Cache Miss Rate Check (Session 147)

**Purpose**: Detect cache misses in the ML Feature Store pipeline

**Context**: Session 146 added `cache_miss_fallback_used` tracking to `ml_feature_store_v2`. When the PlayerDailyCacheProcessor doesn't have data for a player, the feature extractor falls back to computing values from `last_10_games`. For daily predictions, cache miss rate should be 0% since both cache and feature store use the same player list (`upcoming_player_game_context`). Any misses indicate a pipeline issue.

```bash
bq query --use_legacy_sql=false "
-- Cache Miss Rate Check (Session 147)
-- For daily predictions: expect 0% miss rate
-- For backfill dates: 5-15% is expected
SELECT
  game_date,
  COUNTIF(cache_miss_fallback_used) as cache_misses,
  COUNT(*) as total,
  ROUND(COUNTIF(cache_miss_fallback_used) / COUNT(*) * 100, 1) as miss_rate_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1
ORDER BY 1 DESC
"
```

**Expected Results**:
- **0% miss rate (today)**: ✅ PASS (cache and feature store in sync)
- **1-5% miss rate (today)**: ⚠️ WARNING (player list mismatch between cache and feature store)
- **>5% miss rate (today)**: 🔴 CRITICAL (cache processor may have failed)
- **5-15% miss rate (past dates)**: ✅ OK for backfill (expected behavior)

**If cache misses found for today's date**:
1. Check if `PlayerDailyCacheProcessor` ran successfully:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND \
     resource.labels.service_name=nba-phase4-precompute-processors AND \
     severity>=WARNING AND textPayload=~'cache' AND \
     timestamp>='$(date -u +%Y-%m-%dT00:00:00Z)'" \
     --limit=20 --format='table(timestamp,textPayload)'
   ```

2. Compare player lists between cache and feature store:
   ```bash
   bq query --use_legacy_sql=false "
   WITH cache_players AS (
     SELECT DISTINCT player_lookup
     FROM nba_precompute.player_daily_cache
     WHERE cache_date = CURRENT_DATE()
   ),
   feature_players AS (
     SELECT DISTINCT player_lookup
     FROM nba_predictions.ml_feature_store_v2
     WHERE game_date = CURRENT_DATE()
   )
   SELECT f.player_lookup as missing_from_cache
   FROM feature_players f
   LEFT JOIN cache_players c ON f.player_lookup = c.player_lookup
   WHERE c.player_lookup IS NULL
   ORDER BY 1
   "
   ```

3. If systematic: check `upcoming_player_game_context` for gaps

**Post-Game Reconciliation** (next-day check):
```bash
# Compare who played vs who was cached (run day after games)
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
WITH played AS (
  SELECT DISTINCT player_lookup
  FROM nba_analytics.player_game_summary
  WHERE game_date = '${YESTERDAY}' AND is_dnp = FALSE
),
cached AS (
  SELECT DISTINCT player_lookup
  FROM nba_precompute.player_daily_cache
  WHERE cache_date = '${YESTERDAY}'
)
SELECT
  COUNT(DISTINCT p.player_lookup) as players_who_played,
  COUNT(DISTINCT c.player_lookup) as players_cached,
  COUNT(DISTINCT CASE WHEN c.player_lookup IS NULL THEN p.player_lookup END) as played_not_cached,
  COUNT(DISTINCT CASE WHEN p.player_lookup IS NULL THEN c.player_lookup END) as cached_not_played
FROM played p
FULL OUTER JOIN cached c ON p.player_lookup = c.player_lookup
"
```

**Reference**: Session 146 cache miss tracking, Session 144 cache miss fallback

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

#### 1A3. Usage Rate Coverage Check (CRITICAL - Session 96)

**IMPORTANT**: This check was added after Feb 2, 2026 when 0% usage_rate coverage went undetected. usage_rate is a critical ML feature - low coverage degrades prediction quality.

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
SELECT
  game_id,
  COUNTIF(is_dnp = FALSE) as active_players,
  COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) as has_usage_rate,
  ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) /
    NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) as usage_rate_pct,
  CASE
    WHEN ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) /
      NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) >= 80 THEN 'OK'
    WHEN ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) /
      NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) >= 50 THEN 'WARNING'
    ELSE 'CRITICAL'
  END as status
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')
GROUP BY game_id
ORDER BY usage_rate_pct ASC"
```

**Thresholds (per-game)**:
- **≥80%**: OK - Expected coverage level
- **50-79%**: WARNING - Some games missing team data
- **<50%**: CRITICAL - Major data quality issue

**What to check if CRITICAL**:
1. Check if team_offense_game_summary has data: `bq query "SELECT game_id, COUNT(*) FROM nba_analytics.team_offense_game_summary WHERE game_date = '${GAME_DATE}' GROUP BY 1"`
2. Check data quality history: `bq query "SELECT * FROM nba_analytics.data_quality_history WHERE check_date = '${GAME_DATE}' ORDER BY check_timestamp DESC LIMIT 5"`
3. Check processor logs for DATA_QUALITY_CRITICAL alerts

**Root Cause Investigation**:
- If team_offense_game_summary missing for a game → Team processor didn't run
- If team data exists but usage_rate NULL → Player processor ran before team data was ready
- If 0% for ALL games → Check if global threshold blocked calculation (should be fixed in Session 96)

**Related Monitoring**:
- Cloud Function `analytics-quality-check` runs at 7:30 AM ET and sends Slack alerts
- Processor now emits DATA_QUALITY_OK/WARNING/CRITICAL logs after each run
- Historical data available in `nba_analytics.data_quality_history` table

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

Check that Phase 3 processors completed.

**Timing Note (Session 128)**: Phase 3 now runs same-evening using boxscore fallback when gamebook isn't available yet. Check today's date for completion status.

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

#### 2B.1: Evening Analytics Validation (Session 128)

**NEW**: Phase 3 can now run same-night using boxscore fallback (doesn't wait for gamebook).

**When to run this check**: Only during evening hours (6 PM - 6 AM ET) when games have finished but before morning gamebook processing.

```bash
python3 << 'EOF'
from datetime import datetime
import pytz

# Check if we're in evening analytics window
et_tz = pytz.timezone('America/New_York')
now_et = datetime.now(et_tz)
hour = now_et.hour

# Evening window: 6 PM (18) to 6 AM (6)
is_evening = hour >= 18 or hour < 6

if not is_evening:
    print(f"⏭️  Skipping evening analytics check (current hour: {hour} ET)")
    print("  This check only applies during 6 PM - 6 AM ET window")
    exit(0)

print(f"🌙 Evening Analytics Check (current hour: {hour} ET)")

# Check if tonight's games have player_game_summary records
from google.cloud import bigquery
bq = bigquery.Client()

game_date = now_et.strftime('%Y-%m-%d')
if hour < 6:
    # After midnight, check yesterday's games
    from datetime import timedelta
    game_date = (now_et - timedelta(days=1)).strftime('%Y-%m-%d')

query = f"""
SELECT
    COUNT(*) as total_records,
    COUNTIF(primary_source_used = 'nbac_boxscores') as boxscore_source,
    COUNTIF(primary_source_used = 'nbac_gamebook') as gamebook_source,
    COUNTIF(primary_source_used IS NULL) as null_source
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '{game_date}'
"""

result = list(bq.query(query).result())[0]

print(f"\n  Game Date: {game_date}")
print(f"  Total Records: {result.total_records}")
print(f"  Source: nbac_boxscores: {result.boxscore_source}, nbac_gamebook: {result.gamebook_source}")

if result.total_records == 0:
    print(f"\n  ⚠️  WARNING: No player_game_summary records for {game_date}")
    print("  Possible causes:")
    print("    1. Games haven't finished yet")
    print("    2. Phase 3 hasn't triggered")
    print("    3. Same-night analytics not working")
elif result.boxscore_source > 0:
    print(f"\n  ✅ Same-night analytics WORKING!")
    print(f"     Using boxscore fallback ({result.boxscore_source} records)")
elif result.gamebook_source > 0:
    print(f"\n  ℹ️  Records using gamebook source (morning recovery ran)")
else:
    print(f"\n  ⚠️  Records exist but source is NULL - check processor")
EOF
```

**Expected during evening (after games finish)**:
- Records exist with `primary_source_used = 'nbac_boxscores'`
- This confirms same-night analytics is working

**If no records during evening**:
1. Check if games have actually finished: `SELECT game_status FROM nba_reference.nba_schedule WHERE game_date = CURRENT_DATE()`
2. Check Phase 2 completion in Firestore
3. Check nba-phase3-analytics-processors logs for errors
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

### Priority 2D: BigDataBall Coverage Monitoring (NEW - Session 53, Updated Session 94)

Check BDB play-by-play data coverage for shot zone analytics.

**⚠️ IMPORTANT - BDB Release Timing (Session 94)**:
BigDataBall releases play-by-play files **6+ hours AFTER games end**, typically the next morning:
- Games end: ~10-11 PM PT
- BDB uploads: ~4-7 AM PT the next day
- Our scraper retries every 4-5 minutes until files appear

**Timing-Aware Validation**:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ When Validating             │ BDB Expectation          │ Missing = ?        │
├─────────────────────────────┼──────────────────────────┼────────────────────┤
│ Evening/Night (6 PM-5 AM)   │ NOT expected yet         │ ℹ️ INFO (awaiting) │
│ Morning (6 AM-12 PM)        │ SHOULD be available      │ ⚠️ WARNING         │
│ Afternoon+ (after 12 PM)    │ MUST be available        │ 🔴 CRITICAL        │
└─────────────────────────────┴──────────────────────────┴────────────────────┘
```

**Check current time before flagging issues**:
```bash
# Get current hour (PT timezone for game context)
CURRENT_HOUR=$(TZ='America/Los_Angeles' date +%H)
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

if [ "$CURRENT_HOUR" -lt 6 ]; then
  echo "ℹ️ BDB CHECK SKIPPED: It's before 6 AM PT"
  echo "   BDB files for yesterday's games are NOT expected until ~6 AM PT"
  echo "   Run validation again after 6 AM for BDB coverage check"
elif [ "$CURRENT_HOUR" -lt 12 ]; then
  echo "⚠️ BDB CHECK: Morning window - files SHOULD be available"
  echo "   If missing, check scraper logs for retry status"
else
  echo "🔴 BDB CHECK: Afternoon - files MUST be available"
  echo "   If missing, this is a critical issue"
fi
```

**Standard BDB Coverage Query** (run after timing check):

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

**Expected**: Coverage ≥90% (when checking in morning or later)

**Thresholds (TIME-DEPENDENT - Session 94)**:

| Coverage | Before 6 AM PT | 6 AM - 12 PM PT | After 12 PM PT |
|----------|----------------|-----------------|----------------|
| ≥90% | ✅ Great | ✅ OK | ✅ OK |
| 50-89% | ℹ️ Awaiting | ⚠️ WARNING | ⚠️ WARNING |
| <50% | ℹ️ Awaiting | ⚠️ WARNING | 🔴 CRITICAL |
| 0% | ℹ️ Expected | ⚠️ Check scraper | 🔴 CRITICAL |

**Key Insight**: BDB releases files 6+ hours after games end. If validating before 6 AM PT for yesterday's games, 0% coverage is NORMAL and NOT an error.

**If coverage is low AND it's after 6 AM PT**:
1. First check scraper retry logs: Games should be retrying automatically
   ```bash
   gcloud logging read 'textPayload=~"bigdataball" AND textPayload=~"Found game file"' \
     --limit=10 --freshness=6h --project=nba-props-platform
   ```
2. Check pending_bdb_games table: `bq query "SELECT COUNT(*) FROM nba_orchestration.pending_bdb_games WHERE status = 'pending_bdb'"`
3. If files still not on Google Drive after 12+ hours, contact BigDataBall support
4. Run BDB retry processor: `PYTHONPATH="$PWD" .venv/bin/python bin/monitoring/bdb_retry_processor.py`
5. Reference: Session 53 BDB investigation found Jan 17-24 outage

**If coverage is 0% AND it's before 6 AM PT**:
- This is NORMAL - BDB hasn't uploaded files yet
- Do NOT flag as critical
- Re-run validation after 6 AM PT to verify files arrived

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

**IMPORTANT**: Check ALL active models. As of Jan 31, 2026:
- `catboost_v8`: Historical model (ended Jan 28, 2026)
- `catboost_v9`: Current production model (Jan 31+)
- `ensemble_v1_1`: Active ensemble model

#### Weekly Hit Rate Trend

Check model performance over the past 4 weeks to detect drift:

```bash
bq query --use_legacy_sql=false "
-- Weekly hit rate check for model drift detection (ALL MODELS)
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  pa.system_id,
  DATE_TRUNC(pa.game_date, WEEK) as week_start,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(pa.predicted_points - pa.actual_points), 2) as bias,
  CASE
    WHEN ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) < 55 THEN '🔴 CRITICAL'
    WHEN ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) < 60 THEN '🟡 WARNING'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.prediction_accuracy pa
WHERE pa.system_id IN (SELECT system_id FROM active_models)
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND pa.prediction_correct IS NOT NULL
GROUP BY pa.system_id, week_start
ORDER BY pa.system_id, week_start DESC"
```

**Model Version Notes**:
- **catboost_v9**: Current production model (use for predictions after Jan 30, 2026)
- **catboost_v8**: Legacy model (use for historical analysis Jan 18-28, 2026)
- **ensemble models**: Check alongside primary models for comparison

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

Check if degradation is uniform or tier-specific (shows ALL active models).

**CRITICAL (Session 161)**: Uses season_avg tiers, NOT actual_points tiers. See Phase 0.466 methodology note.

```bash
bq query --use_legacy_sql=false "
-- Performance by player tier using SEASON AVERAGE (correct methodology)
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
),
player_avgs AS (
  SELECT player_lookup, system_id, AVG(actual_points) as season_avg
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= '2025-11-01'
    AND system_id IN (SELECT system_id FROM active_models)
  GROUP BY 1, 2
)
SELECT
  pa.system_id,
  DATE_TRUNC(pa.game_date, WEEK) as week,
  CASE
    WHEN pav.season_avg >= 25 THEN '1_stars_25+_avg'
    WHEN pav.season_avg >= 15 THEN '2_starters_15-25_avg'
    WHEN pav.season_avg >= 8 THEN '3_rotation_8-15_avg'
    ELSE '4_bench_<8_avg'
  END as tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(pa.predicted_points - pa.actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy pa
JOIN player_avgs pav ON pa.player_lookup = pav.player_lookup AND pa.system_id = pav.system_id
WHERE pa.system_id IN (SELECT system_id FROM active_models)
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND pa.prediction_correct IS NOT NULL
GROUP BY pa.system_id, week, tier
ORDER BY pa.system_id, week DESC, tier"
```

**What to look for**:
- **Star tier (25+ avg) hit rate < 60%**: Real model weakness on high-usage players
- **Bench tier bias > +5**: Model over-predicting low-minute players
- **Tier divergence > 20%**: Different failure modes by tier

**If tier-specific issues detected**:
- Stars under-predicted: Add player trajectory features (pts_slope_10g, breakout_flag)
- Bench over-predicted: Reduce model confidence for low-usage players
- Reference: `MODEL-DEGRADATION-ROOT-CAUSE-ANALYSIS.md` for detailed analysis

#### Model vs Vegas Comparison

Check if our edge over Vegas is eroding (compares ALL active models):

```bash
bq query --use_legacy_sql=false "
-- Our MAE vs Vegas MAE (last 4 weeks, ALL MODELS)
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  pa.system_id,
  DATE_TRUNC(pa.game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(pa.predicted_points - pa.actual_points)), 2) as our_mae,
  ROUND(AVG(ABS(pa.line_value - pa.actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(pa.line_value - pa.actual_points)) - AVG(ABS(pa.predicted_points - pa.actual_points)), 2) as our_edge
FROM nba_predictions.prediction_accuracy pa
WHERE pa.system_id IN (SELECT system_id FROM active_models)
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND pa.line_value IS NOT NULL
  AND pa.prediction_correct IS NOT NULL
GROUP BY pa.system_id, week
ORDER BY pa.system_id, week DESC"
```

**Expected**: `our_edge` > 0 (we're more accurate than Vegas)

**Alert if**:
- `our_edge` < 0 for 2+ consecutive weeks → Model no longer competitive
- `our_edge` trending downward → Model drift in progress

### Priority 2H: Scraper Health Monitoring (Session 70 - NEW)

**Purpose**: Detect stale scrapers, failed scheduler jobs, and missing data sources.

**When to run**: Daily (part of standard validation)

**Why this matters**: Session 70 discovered player_movement data was 5+ months stale because no scheduler job existed. This check prevents similar issues.

#### Scraper Freshness Check

Query BigQuery to find scrapers with stale data:

```bash
bq query --use_legacy_sql=false "
-- Critical scrapers with data staleness check
WITH scraper_freshness AS (
  SELECT 'nbac_player_movement' as scraper, MAX(transaction_date) as last_date,
    DATE_DIFF(CURRENT_DATE(), MAX(transaction_date), DAY) as days_stale
  FROM \`nba-props-platform.nba_raw.nbac_player_movement\`

  UNION ALL

  SELECT 'nbac_injury_report' as scraper, MAX(report_date) as last_date,
    DATE_DIFF(CURRENT_DATE(), MAX(report_date), DAY) as days_stale
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`

  UNION ALL

  SELECT 'nbac_roster' as scraper, MAX(roster_date) as last_date,
    DATE_DIFF(CURRENT_DATE(), MAX(roster_date), DAY) as days_stale
  FROM \`nba-props-platform.nba_raw.nbac_roster\`

  UNION ALL

  SELECT 'bdl_injuries' as scraper, MAX(scrape_date) as last_date,
    DATE_DIFF(CURRENT_DATE(), MAX(scrape_date), DAY) as days_stale
  FROM \`nba-props-platform.nba_raw.bdl_injuries\`
)
SELECT
  scraper,
  last_date,
  days_stale,
  CASE
    WHEN days_stale <= 2 THEN '✅ HEALTHY'
    WHEN days_stale <= 7 THEN '🟡 STALE'
    WHEN days_stale <= 30 THEN '🟠 WARNING'
    ELSE '🔴 CRITICAL'
  END as status
FROM scraper_freshness
ORDER BY days_stale DESC"
```

**Alert Thresholds**:
- **≤2 days**: HEALTHY - Normal operations
- **3-7 days**: STALE - Monitor, may be weekend gap
- **8-30 days**: WARNING - Investigate scheduler/scraper
- **>30 days**: CRITICAL - Scraper broken or not scheduled

**If CRITICAL status found**:
1. Check if scheduler job exists: `gcloud scheduler jobs list --location=us-west2 | grep <scraper>`
2. Check recent logs: `gcloud logging read 'resource.labels.service_name="nba-scrapers" AND jsonPayload.scraper_name="<scraper>"' --limit=10`
3. Verify scraper is registered: Check `scrapers/registry.py`
4. See comprehensive audit: `docs/08-projects/current/scraper-health-audit/COMPREHENSIVE-AUDIT-2026-02-01.md`

#### Scheduler Job Failures

Check for scheduled jobs that failed in last 24 hours:

```bash
# Check failed scheduler jobs
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND severity>=ERROR' \
  --limit=10 \
  --freshness=24h \
  --format="table(timestamp, resource.labels.job_name, jsonPayload.message)"
```

**Alert if any jobs failed** - These are critical for data freshness.

#### Known Issues Tracker

**Current known stale scrapers** (as of Session 70):
- `br_season_roster`: 9 days stale (scheduled but failing)
- `espn_roster`: 3 days stale (scheduled but failing)
- `bdl_player_box_scores`: 7 days stale (catchup logic broken)

**Deprecated scrapers** (ignore if stale):
- `bdl_games`: Replaced by bdl_box_scores (to be confirmed)
- `bp_player_props`: Replaced by oddsa_player_props (to be confirmed)

**For updates**: See scraper health audit document for latest status.

### Priority 2I: Session 113+ Data Quality Checks (NEW - Session 113+)

**CRITICAL**: Catch DNP pollution and Phase 4 cache issues before they impact predictions.
Session 113+ discovered massive data quality issues affecting 67% of Nov-Jan training data.

#### 2I.1: Deployment Drift Check

**Run FIRST** - Validate services before checking data:

```bash
./bin/whats-deployed.sh
```

**Expected**: All data processing services up-to-date
**If drift found**: Deploy stale services immediately

**Critical services**:
- `nba-phase4-precompute-processors` - Phase 4 cache & ML features
- `nba-phase3-analytics-processors` - player_game_summary
- `prediction-worker` - Predictions

**Why this matters**: Sessions 64, 81, 82, 97, 113+ had fixes committed but not deployed. Always deploy before validating data.

#### 2I.2: DNP Pollution in Phase 4 Cache

**Check if player_daily_cache includes DNP games incorrectly**:

```sql
-- Quick check: Are DNP players in cache?
SELECT
  COUNT(*) as dnp_players_cached,
  ROUND(100.0 * COUNT(*) / (
    SELECT COUNT(*)
    FROM nba_precompute.player_daily_cache
    WHERE cache_date = CURRENT_DATE() - 1
  ), 1) as dnp_pct
FROM nba_precompute.player_daily_cache pdc
JOIN nba_analytics.player_game_summary pgs
  ON pdc.player_lookup = pgs.player_lookup
  AND pdc.cache_date = pgs.game_date
WHERE pdc.cache_date = CURRENT_DATE() - 1
  AND pgs.is_dnp = TRUE
```

**Expected**: 0 DNP players (0%)
**Warning**: >0% indicates DNP filter broken
**Critical**: >5% indicates severe pollution

#### 2I.3: ML Feature Store vs Cache Match Rate

**Verify L5 values match between ml_feature_store_v2 and player_daily_cache**:

```sql
-- Check last 7 days match rate
SELECT
  COUNT(*) as total_records,
  COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) < 0.1) as matches,
  ROUND(100.0 * COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) < 0.1) / COUNT(*), 1) as match_pct,
  COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) > 3.0) as large_mismatches
FROM nba_precompute.player_daily_cache c
JOIN nba_predictions.ml_feature_store_v2 m
  ON c.cache_date = m.game_date
  AND c.player_lookup = m.player_lookup
WHERE c.cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

**Expected**: >95% match rate, <1% large mismatches
**Warning**: 90-95% match rate (investigate top mismatches)
**Critical**: <90% match rate (DNP pollution likely)

#### 2I.4: Team Pace Outlier Detection

**Check for team_pace corruption**:

```sql
-- Detect pace outliers (normal range: 80-120)
SELECT
  cache_date,
  COUNT(*) as total_records,
  COUNTIF(team_pace_last_10 < 80 OR team_pace_last_10 > 120) as outliers,
  ROUND(100.0 * COUNTIF(team_pace_last_10 < 80 OR team_pace_last_10 > 120) / COUNT(*), 1) as outlier_pct,
  MIN(team_pace_last_10) as min_pace,
  MAX(team_pace_last_10) as max_pace
FROM nba_precompute.player_daily_cache
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY cache_date
HAVING outliers > 0
ORDER BY cache_date DESC
```

**Expected**: 0 outliers (all pace 80-120)
**Critical**: Any outliers found (data corruption or Phase 3 bug)

#### 2I.5: Unmarked DNPs in Phase 3

**Check for games that look like DNPs but aren't marked**:

```sql
-- Find unmarked DNPs in last 7 days
SELECT
  game_date,
  COUNT(*) as unmarked_dnps,
  ARRAY_AGG(STRUCT(player_lookup, team_abbr) LIMIT 5) as examples
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND (points = 0 AND minutes_played IS NULL AND is_dnp IS NULL)
GROUP BY game_date
HAVING COUNT(*) > 0
ORDER BY game_date DESC
```

**Expected**: 0 unmarked DNPs
**Warning**: 1-5 unmarked (upstream data issue)
**Critical**: >5 unmarked (scraper or Phase 3 bug)

#### 2I.6: Silent Write Failure Pattern

**Check for suspicious write patterns (save_precompute bug pattern)**:

```sql
-- Check if yesterday had normal write volume
SELECT
  COUNT(*) as records_written,
  COUNT(DISTINCT player_lookup) as unique_players,
  CASE
    WHEN COUNT(*) = 0 THEN 'CRITICAL - No writes'
    WHEN COUNT(*) < 50 THEN 'WARNING - Very low writes'
    WHEN COUNT(*) > 500 THEN 'WARNING - Unusually high writes'
    ELSE 'OK'
  END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() - 1
```

**Expected**: 200-400 records (varies by game schedule)
**Warning**: <50 or >500 records (unusual day or write issue)
**Critical**: 0 records (total write failure)

**Action if issues found**:
1. Check service logs for false "FAILED" messages
2. Verify BigQuery streaming inserts completed
3. Check if save_precompute() return bug recurred

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

8. **DNP Pollution in Phase 4 Cache (Session 113+)** ✅ FIXED 2026-02-04
   - Symptom: L5/L10 values in player_daily_cache include DNP games
   - Impact: 44-67% mismatch rate in Nov-Jan 2025, affecting ML training data
   - Root cause: Phase 4 DNP filter only checked points > 0, not minutes_played
   - Fix: Updated DNP filter in feature_extractor.py (commit dd225120)
   - Status: Deployed 2026-02-04, cache regenerated for 73/106 dates
   - Detection: Run Priority 2I checks (DNP pollution, match rate)

9. **Save Precompute Return Bug (Session 113+)** ✅ FIXED 2026-02-04
   - Symptom: Logs show "FAILED" but BigQuery writes succeeded
   - Impact: Misleading errors cause unnecessary re-runs
   - Root cause: save_precompute() returned None instead of bool
   - Fix: Fixed return type in bigquery_save_ops.py (commit 241153d3)
   - Status: Deployed 2026-02-04
   - Detection: Run Priority 2I.6 (silent write failure check)

10. **Shot Zone Early Season Coverage (Session 113+)** ✅ FIXED 2026-02-04
    - Symptom: 0% shot_zone coverage in first 3 weeks of season
    - Impact: ML feature store failures, November 2025 at 68% quality
    - Root cause: Hard 10-game requirement when players had 4-7 games
    - Fix: Dynamic 3-10 game threshold based on days into season (commit e06043b9)
    - Status: Deployed 2026-02-04, needs historical regeneration
    - Detection: Run Priority 2I checks or /spot-check-features #17

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
| **DNP Pollution (Session 113+)** | 0% | 0.1-1% | >1% |
| **ML Feature Match Rate (Session 113+)** | ≥95% | 90-94% | <90% |
| **Team Pace Outliers (Session 113+)** | 0 | 1-5 | >5 |
| **Unmarked DNPs (Session 113+)** | 0 | 1-5 | >5 |
| **Phase 4 Daily Cache** | ≥50 records | 1-49 records | 0 records |
| **Phase Trigger Status** | _triggered=True | N/A | _triggered=False when complete |
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
- Phase trigger failure (_triggered=False when processors complete)
- Phase 4 daily cache empty for today (0 records)

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
| Session 97 Quality Gate | ✅/⚠️/❌ | Working/Blocked/Bypassed |
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

# Model drift monitoring (Session 28) - Updated for multi-model support
# Check ALL active models (catboost_v8, catboost_v9, ensemble_v1_1)
bq query --use_legacy_sql=false "
WITH active_models AS (
  SELECT DISTINCT system_id FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT system_id, DATE_TRUNC(game_date, WEEK) as week,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id IN (SELECT system_id FROM active_models)
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY system_id, week ORDER BY system_id, week DESC"

# Manual triggers (if needed)
gcloud scheduler jobs run same-day-phase3
gcloud scheduler jobs run same-day-phase4
gcloud scheduler jobs run same-day-phase5

# Check specific date
python scripts/validate_tonight_data.py --date 2026-01-26
```

## Cloud Function Quick Checks (Session 97)

For instant validation without running full scripts:

```bash
# Check deployment drift (all services healthy?)
curl -s -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/morning-deployment-check" | jq
# Expected: {"status": "healthy", "stale_count": 0, "healthy_count": 5}

# Check analytics quality for yesterday
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/analytics-quality-check?game_date=$(date -d yesterday +%Y-%m-%d)" | jq
# Expected: {"status": "OK", "metrics": {"usage_rate_coverage_pct": 95+}}

# Check data quality history (trend tracking)
bq query --use_legacy_sql=false "SELECT * FROM nba_analytics.data_quality_history ORDER BY check_timestamp DESC LIMIT 5"
```

**Automated Schedules:**
- `morning-deployment-check`: 6 AM ET daily (alerts on stale services)
- `analytics-quality-check-morning`: 7:30 AM ET daily (alerts on low usage_rate)

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
