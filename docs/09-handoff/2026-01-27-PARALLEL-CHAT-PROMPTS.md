# Parallel Chat Prompts - January 27, 2026

Created by Opus to coordinate 3 parallel Sonnet chats for pipeline recovery.

---

# CHAT 1: OPERATIONS - Pipeline Recovery

## Copy Everything Below This Line

---

## Context

You are helping with an NBA Props Platform pipeline that has several critical issues discovered today (Jan 27, 2026). The platform scrapes NBA data, processes it through 5 phases, and generates betting predictions.

**Your role**: Operations/Infrastructure - Restore today's predictions and fix immediate operational issues.

**Important**: Do NOT make code changes. Focus on deployments, triggers, and verification. Another chat is handling code fixes.

---

## Current Critical Issues (Your Responsibility)

### Issue 1: No Predictions for Today (Jan 27)
**Root Cause**: The `nba-scrapers` Cloud Run service was last deployed Jan 24, but a config change was committed Jan 26 that changed `window_before_game_hours` from 6 to 12. The service is using the old 6-hour window, so `betting_lines` workflow hasn't run yet (first game is 7 PM ET, 6-hour window starts at 1 PM, but 12-hour window should have started at 7 AM).

**Evidence**:
```
nba-scrapers last deployed: 2026-01-24T02:17:15Z
Config change committed:    2026-01-26 (f4385d03)
betting_lines workflow: SKIP - First game in 9.0h (window starts 6h before)
Props data for Jan 27: 0 records
```

### Issue 2: Missing Cache for Jan 26
**Root Cause**: Cascading dependency failure. PlayerGameSummaryProcessor failed for Jan 25 at 00:09 AM → PlayerDailyCacheProcessor blocked for Jan 26 at 07:15 AM.

**Evidence**:
```
Jan 26 cache: 0 players
Jan 25 cache: 182 players (working)
Error: "DependencyError: Upstream PlayerGameSummaryProcessor failed for 2026-01-25"
```

### Issue 3: BigQuery Quota Exceeded (Monitoring)
**Root Cause**: Circuit breaker writing too frequently. PlayerGameSummaryProcessor: 743 writes/day. Total: 1,248-2,533 writes/day. This is causing quota errors but NOT blocking the pipeline.

**Note**: A dev chat is fixing the code. Your job is to monitor and verify the immediate impact.

---

## Your Tasks

### Task 1: Redeploy nba-scrapers Service (HIGHEST PRIORITY)

This picks up the 12-hour window config change.

```bash
# Option A: Use deployment script
bash bin/deploy/deploy_scrapers.sh

# Option B: Manual deploy
gcloud run deploy nba-scrapers \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform
```

**Verify deployment**:
```bash
gcloud run services describe nba-scrapers --region=us-west2 --format='value(status.latestCreatedRevisionName)'
```

### Task 2: Trigger betting_lines Workflow

After redeployment, force the workflow to run:

```bash
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"force_workflows": ["betting_lines"]}'
```

**Verify props collected** (wait ~15 minutes):
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as props_count, MIN(created_at) as first, MAX(created_at) as last
FROM \`nba-props-platform.nba_raw.bp_player_props\`
WHERE game_date = '2026-01-27'"
```

### Task 3: Trigger Morning Predictions

After props are collected:

```bash
gcloud scheduler jobs run morning-predictions --location=us-west2
```

**Verify predictions generated** (wait ~5 minutes):
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-27' AND is_active = TRUE"
```

### Task 4: Fix Missing Cache for Jan 26

First, check if Jan 25 PlayerGameSummary data actually exists:

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-25'"
```

**If data exists** (records > 0): The issue is run_history tracking, not actual data. Retry the cache:

```bash
gcloud scheduler jobs run same-day-phase4 --location=us-west2
```

**If data missing** (records = 0): Phase 3 needs to run first (this is the reprocessing chat's job, but you can trigger):

```bash
gcloud scheduler jobs run same-day-phase3 --location=us-west2
# Wait 10 minutes, then retry phase4
gcloud scheduler jobs run same-day-phase4 --location=us-west2
```

**Verify cache updated**:
```bash
bq query --use_legacy_sql=false "
SELECT cache_date, COUNT(DISTINCT player_lookup) as players, MAX(created_at) as last_update
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= '2026-01-25'
GROUP BY cache_date
ORDER BY cache_date DESC"
```

### Task 5: Monitor BigQuery Quota

Check current quota usage (informational):

```bash
bq query --use_legacy_sql=false "
SELECT processor_name, COUNT(*) as writes
FROM \`nba-props-platform.nba_orchestration.circuit_breaker_state\`
WHERE DATE(updated_at) = CURRENT_DATE()
GROUP BY processor_name
ORDER BY writes DESC"
```

Check for quota errors:
```bash
gcloud logging read 'resource.type=bigquery_resource AND protoPayload.status.message:quota' \
  --limit=10 \
  --format='table(timestamp,protoPayload.status.message)' \
  --project=nba-props-platform
```

---

## Success Criteria

Before finishing, verify ALL of the following:

- [ ] nba-scrapers redeployed (revision date is today)
- [ ] Props collected for Jan 27 (>1000 records)
- [ ] Predictions generated for Jan 27 (>50 predictions)
- [ ] Cache exists for Jan 26 (>100 players)
- [ ] No new quota errors in last hour

---

## Files to Read for Context

If you need more context:
- `docs/09-handoff/2026-01-27-PIPELINE-INVESTIGATION.md` - Full investigation of issues
- `docs/09-handoff/EXECUTIVE-SUMMARY-2026-01-27.md` - Quick summary
- `config/workflows.yaml` - Workflow configuration

---

## Handoff Notes

When complete, create a short handoff document at:
`docs/09-handoff/2026-01-27-OPS-CHAT-COMPLETE.md`

Include:
- What was deployed/triggered
- Current status of predictions
- Current status of cache
- Any remaining issues

---

**END OF CHAT 1 PROMPT**

---
---
---

# CHAT 2: DATA REPROCESSING - Historical Remediation

## Copy Everything Below This Line

---

## Context

You are helping with an NBA Props Platform pipeline that has data quality issues discovered over Jan 26-27, 2026. The platform processes NBA data through 5 phases: Raw → Analytics → Precompute → ML Features → Predictions.

**Your role**: Data Reprocessing - Fix historical data gaps by reprocessing Phase 3 (Analytics) and Phase 4 (Precompute).

**Important**: Do NOT make code changes. Focus on running backfill scripts and verifying results. Another chat is handling code fixes.

---

## Current Data Quality Issues (Your Responsibility)

### Issue 1: Analytics Coverage Gaps (Jan 1-21)
**Problem**: Only 60-75% of players have analytics records for Jan 1-21.
**Root Cause**:
1. Name normalization mismatches (BDL API names vs registry) - Fixed on Jan 3-4 via registry resolutions
2. Team stats weren't available at original processing time

**Evidence**:
```
Jan 15: 316 raw players → 201 analytics players (63.6% coverage)
Jan 22: 282 raw players → 282 analytics players (100% coverage) ← After registry fixes
```

Missing players include major names: Anthony Davis, Damian Lillard, Austin Reaves

### Issue 2: Usage Rate NULL (Jan 19-25)
**Problem**: 41-59% of active players missing usage_rate
**Root Cause**: team_offense_game_summary wasn't available when player_game_summary was originally processed. Now team data EXISTS and can be joined.

**Evidence**:
```
Jan 22: usage_rate coverage = 0%
Jan 26: usage_rate coverage = 41.4%
Team stats: Exist for all dates (14-22 teams per date)
Manual join: Works (team_fg_attempts = 79, 83, etc.)
```

### Issue 3: Cache Cascade Contamination
**Problem**: Rolling averages (L5, L10) were computed with incomplete upstream data
**Root Cause**: Phase 4 ran before Phase 3 had complete data

---

## Your Tasks

### Task 1: Reprocess Phase 3 for Jan 1-25

This will:
- Pick up registry resolutions added Jan 3-4 (fixes name mismatches)
- Recalculate with now-available team stats (fixes usage_rate)

```bash
# Navigate to project root
cd /home/naji/code/nba-stats-scraper

# Run the backfill (this may take 30-60 minutes)
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2026-01-01 --end-date 2026-01-25

# If the above script doesn't exist, try:
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-01 --end-date 2026-01-25 --backfill
```

**Verify after completion**:
```bash
# Check player coverage improved for Jan 15
bq query --use_legacy_sql=false "
WITH raw AS (
  SELECT DISTINCT player_lookup FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
  WHERE game_date = '2026-01-15'
),
analytics AS (
  SELECT DISTINCT player_lookup FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date = '2026-01-15'
)
SELECT
  (SELECT COUNT(*) FROM raw) as raw_players,
  (SELECT COUNT(*) FROM analytics) as analytics_players,
  ROUND(100.0 * (SELECT COUNT(*) FROM analytics) / (SELECT COUNT(*) FROM raw), 1) as coverage_pct"

# Check usage_rate coverage improved for Jan 22
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(usage_rate IS NOT NULL) as has_usage,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-22'
  AND minutes_played > 0"
```

**Expected Results**:
- Player coverage: 85-95% (up from 60-75%)
- Usage rate coverage: 90%+ (up from 0-41%)

### Task 2: Regenerate Phase 4 Cache (After Phase 3 Complete)

The cache needs to be regenerated for the entire cascade window (10-day lookback affects 10+ days forward).

```bash
# Wait until Phase 3 completes, then run cache regeneration
python backfill_jobs/precompute/player_daily_cache/regenerate_cache.py \
  --start-date 2026-01-01 --end-date 2026-02-13

# If the above script doesn't exist, try:
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
  --start-date 2026-01-01 --end-date 2026-02-13 --backfill
```

**Verify after completion**:
```bash
bq query --use_legacy_sql=false "
SELECT cache_date, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= '2026-01-15' AND cache_date <= '2026-01-27'
GROUP BY cache_date
ORDER BY cache_date"
```

**Expected**: 100-200 players per date

### Task 3: Run Spot Checks to Verify Quality

After reprocessing, validate data accuracy:

```bash
# Run spot check for specific players
python scripts/spot_check_data_accuracy.py --start-date 2026-01-15 --end-date 2026-01-25 --samples 20

# Or use the skill (if available in your session)
# /spot-check-date 2026-01-22
```

**Manual spot check queries**:

```bash
# Check a previously missing player (Anthony Davis)
bq query --use_legacy_sql=false "
SELECT game_date, player_lookup, points, minutes_played, usage_rate
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE player_lookup = 'anthonydavis'
  AND game_date >= '2026-01-15'
ORDER BY game_date"

# Check rolling averages are populated
bq query --use_legacy_sql=false "
SELECT player_lookup, cache_date, points_avg_last_5, points_avg_last_10
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE player_lookup = 'leblonjames'
  AND cache_date >= '2026-01-20'
ORDER BY cache_date"
```

### Task 4: Document Results

Track the before/after metrics:

```bash
# Create a simple results summary
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_rate_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-25'
  AND minutes_played > 0
GROUP BY game_date
ORDER BY game_date"
```

---

## Success Criteria

Before finishing, verify ALL of the following:

- [ ] Player coverage for Jan 15: >85% (was 63.6%)
- [ ] Usage rate coverage for Jan 22: >80% (was 0%)
- [ ] Cache exists for all dates Jan 15-27: >100 players each
- [ ] Anthony Davis has analytics records for Jan 15+
- [ ] Spot check accuracy: >90%

---

## Files to Read for Context

If you need more context:
- `docs/09-handoff/HANDOFF-JAN27-2026-VALIDATION-DIAGNOSTIC-RESULTS.md` - Diagnostic query results
- `docs/09-handoff/HANDOFF-JAN26-2026-HISTORICAL-VALIDATION-FINDINGS.md` - Original validation findings
- `docs/09-handoff/2026-01-26-SPOT-CHECK-HANDOFF.md` - Name normalization root cause
- `backfill_jobs/analytics/player_game_summary/` - Backfill script location
- `backfill_jobs/precompute/player_daily_cache/` - Cache regeneration script location

---

## Important Notes

1. **Long-running processes**: Phase 3 backfill may take 30-60 minutes. Phase 4 may take 1-2 hours.

2. **Order matters**: Phase 3 MUST complete before Phase 4. Don't run them in parallel.

3. **Monitoring**: Watch for errors in the output. Common issues:
   - BigQuery quota errors (non-fatal, will retry)
   - Registry lookup failures (should be minimal after Jan 3-4 fixes)

4. **If scripts don't exist**: Check for alternative locations:
   ```bash
   find . -name "*backfill*" -type f | grep -E "player_game_summary|player_daily_cache"
   ```

---

## Handoff Notes

When complete, create a handoff document at:
`docs/09-handoff/2026-01-27-REPROCESSING-CHAT-COMPLETE.md`

Include:
- Start/end times for each backfill
- Before/after coverage metrics
- Any errors encountered
- Spot check results

---

**END OF CHAT 2 PROMPT**

---
---
---

# CHAT 3: DEVELOPMENT - Bug Fixes & Prevention

## Copy Everything Below This Line

---

## Context

You are helping with an NBA Props Platform pipeline that has several bugs discovered over Jan 26-27, 2026. The platform processes NBA data through 5 phases and generates betting predictions.

**Your role**: Development - Fix bugs in the codebase and deploy prevention mechanisms.

**Important**: This is the only chat making code changes. Be careful with deployments. Other chats are handling operations and data reprocessing.

---

## Current Bugs (Your Responsibility)

### Bug 1: BigQuery Quota Crisis (CRITICAL)
**Problem**: Circuit breaker writing 743 times/day from PlayerGameSummaryProcessor (1,248 total). BigQuery has partition modification limits.

**Root Cause**: The BigQueryBatchWriter batching is ineffective because Cloud Run instances scale to zero. Each instance has its own buffer, and when instances terminate, they flush partial batches (often 1-2 records).

**Evidence**:
```
Jan 27: 1,248 writes (PlayerGameSummaryProcessor: 743)
Jan 25: 2,533 writes (peak!)
Actual records: ~805
Expected with batching: ~8 writes
Actual ratio: ~22 writes per record
```

### Bug 2: Usage Rate Calculation Not Persisting
**Problem**: Team stats exist and can be joined NOW, but usage_rate stored as NULL for historical records.

**Root Cause**: Processing order issue. When player_game_summary records were originally created, team_offense_game_summary data wasn't available yet. The processor attempted the join, found no team data, and set usage_rate = NULL.

**Note**: Reprocessing (Chat 2) will fix historical data. Your job is to prevent this from happening again by ensuring proper processing order.

### Bug 3: Game ID Normalization (MEDIUM)
**Problem**: 3 games have duplicate IDs in both directions (e.g., `20260126_ATL_IND` AND `20260126_IND_ATL`), creating 6 extra team records.

**Root Cause**: Inconsistent game_id format between scrapers.

---

## Your Tasks

### Task 1: Fix BigQuery Quota Issue (CRITICAL - Do First)

**Option A (Recommended): Switch monitoring tables to streaming inserts**

Streaming inserts bypass the load job quota entirely.

```bash
# Find the batch writer
cat shared/utils/bigquery_batch_writer.py | head -100
```

**Changes needed**:
```python
# In BigQueryBatchWriter, change from:
# job = self.client.load_table_from_json(records, table_ref, job_config=job_config)

# To streaming inserts:
# errors = self.client.insert_rows_json(table_ref, records)
```

**Files to modify**:
- `shared/utils/bigquery_batch_writer.py`

**Option B: Migrate circuit breaker to Firestore**

This is a bigger change but more appropriate for high-frequency state.

```python
# New file: shared/state/firestore_circuit_breaker.py
from google.cloud import firestore

class FirestoreCircuitBreaker:
    def __init__(self):
        self.db = firestore.Client()

    def update_state(self, processor_name: str, state: dict):
        doc_ref = self.db.collection('circuit_breakers').document(processor_name)
        doc_ref.set(state, merge=True)
```

### Task 2: Deploy Data Lineage Prevention Layer

The prevention layer was built on Jan 26 but not deployed. It prevents cascade contamination.

**Step 1: Run the migration**
```bash
bq query --use_legacy_sql=false < migrations/add_quality_metadata.sql
```

**Step 2: Review the integration example**
```bash
cat docs/08-projects/current/data-lineage-integrity/INTEGRATION-EXAMPLE.md
```

**Step 3: Integrate ProcessingGate into PlayerGameSummaryProcessor**

```python
# In player_game_summary_processor.py, add:
from shared.validation.processing_gate import ProcessingGate, GateStatus

class PlayerGameSummaryProcessor:
    def __init__(self, ...):
        ...
        self.processing_gate = ProcessingGate(self.bq_client, self.project_id)

    def process(self):
        # Check gate before processing
        result = self.processing_gate.check_can_process(
            processor_name=self.__class__.__name__,
            game_date=self.game_date,
            entity_ids=self.get_players(),
            window_size=10
        )

        if result.status == GateStatus.FAIL:
            raise ProcessingBlockedError(result.message)

        if result.status == GateStatus.WAIT:
            logger.info(f"Data not ready, will retry: {result.message}")
            return

        # Continue with processing...
        # Add quality metadata to output records
        for record in records:
            record.update(result.quality_metadata)
```

### Task 3: Fix Game ID Normalization (MEDIUM)

Standardize game_id format to prevent duplicates.

**Option A: Always use alphabetical order**
```python
def normalize_game_id(game_date: str, team1: str, team2: str) -> str:
    teams = sorted([team1, team2])
    return f"{game_date}_{teams[0]}_{teams[1]}"
```

**Option B: Always use away_home order (consistent with NBA)**
```python
def normalize_game_id(game_date: str, away_team: str, home_team: str) -> str:
    return f"{game_date}_{away_team}_{home_team}"
```

**Files to check/modify**:
```bash
grep -r "game_id" data_processors/raw/ --include="*.py" | head -20
grep -r "game_id" data_processors/analytics/ --include="*.py" | head -20
```

### Task 4: Add Processing Order Enforcement

Ensure team_offense_game_summary is processed BEFORE player_game_summary.

**Option A: Add explicit dependency in processor**
```python
# In player_game_summary_processor.py
HARD_DEPENDENCIES = ['team_offense_game_summary']

def check_dependencies(self):
    for dep in self.HARD_DEPENDENCIES:
        if not self._check_table_has_data(dep, self.game_date):
            raise DependencyNotReadyError(f"{dep} not ready for {self.game_date}")
```

**Option B: Use the SoftDependencyMixin (already exists)**
```bash
cat shared/processors/mixins/soft_dependency_mixin.py | head -50
```

---

## Files to Read for Context

Before making changes, read these:

1. **BigQuery Batch Writer**:
   ```bash
   cat shared/utils/bigquery_batch_writer.py
   ```

2. **Processing Gate (already built)**:
   ```bash
   cat shared/validation/processing_gate.py
   ```

3. **Window Completeness Validator (already built)**:
   ```bash
   cat shared/validation/window_completeness.py
   ```

4. **Integration Example**:
   ```bash
   cat docs/08-projects/current/data-lineage-integrity/INTEGRATION-EXAMPLE.md
   ```

5. **Player Game Summary Processor**:
   ```bash
   cat data_processors/analytics/player_game_summary/player_game_summary_processor.py | head -200
   ```

6. **Investigation findings**:
   - `docs/09-handoff/2026-01-27-PIPELINE-INVESTIGATION.md` - Quota issue details
   - `docs/09-handoff/daily-validation-2026-01-27.md` - Full validation report
   - `docs/08-projects/current/data-lineage-integrity/IMPLEMENTATION-SUMMARY.md` - Prevention layer docs

---

## Testing Your Changes

### Test BigQuery Quota Fix

After modifying the batch writer:
```bash
# Run a quick test
python -c "
from shared.utils.bigquery_batch_writer import BigQueryBatchWriter
writer = BigQueryBatchWriter('nba-props-platform', 'nba_orchestration', 'test_table')
# Check if using streaming inserts
print('Using streaming:', hasattr(writer, 'insert_rows_json'))
"
```

### Test Processing Gate Integration

```bash
# Run unit tests
pytest tests/unit/validation/test_processing_gate.py -v
pytest tests/unit/validation/test_window_completeness.py -v
```

### Test Game ID Normalization

```bash
# Check for duplicates after fix
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as count
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date = '2026-01-26'
GROUP BY game_id
HAVING COUNT(*) > 2"
```

---

## Deployment Checklist

Before deploying any changes:

- [ ] All unit tests pass
- [ ] Changes reviewed (no accidental deletions)
- [ ] Backup strategy if rollback needed

**Deploy Phase 3 processors**:
```bash
# Only after testing
gcloud run deploy nba-phase3-analytics-processors \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform
```

---

## Success Criteria

Before finishing, verify:

- [ ] BigQuery quota fix deployed (streaming inserts OR Firestore)
- [ ] Circuit breaker writes reduced (check in 1 hour)
- [ ] Processing gate migration run
- [ ] Processing gate integrated into at least one processor
- [ ] Game ID normalization fix identified (may not deploy today)
- [ ] All tests pass

---

## Handoff Notes

When complete, create a handoff document at:
`docs/09-handoff/2026-01-27-DEV-CHAT-COMPLETE.md`

Include:
- Code changes made (files + summary)
- Deployments done
- Tests run and results
- Any remaining work

---

**END OF CHAT 3 PROMPT**

---

# Coordination Notes for Human

## Suggested Order

1. Start **Chat 1 (Ops)** first - highest urgency (predictions needed today)
2. Start **Chat 2 (Reprocessing)** shortly after - long-running jobs can run in background
3. Start **Chat 3 (Dev)** - can work in parallel, no dependencies on other chats

## Potential Conflicts

- **Deployments**: Only Chat 3 should deploy code. Chat 1 redeploys scrapers (no code changes).
- **Phase 3 processor**: Chat 2 runs backfills, Chat 3 modifies code. Coordinate if Chat 3 wants to deploy while Chat 2 is running backfills.
- **BigQuery**: All chats query BigQuery. No write conflicts expected.

## Check-in Points

After ~2 hours, check:
1. Chat 1: Predictions generated? Cache restored?
2. Chat 2: Phase 3 backfill complete? Starting Phase 4?
3. Chat 3: Quota fix deployed? Tests passing?

## Final Validation

After all chats complete, run:
```bash
python scripts/validate_tonight_data.py
```

Expected: 0 ISSUES (was 5 ISSUES this morning)
