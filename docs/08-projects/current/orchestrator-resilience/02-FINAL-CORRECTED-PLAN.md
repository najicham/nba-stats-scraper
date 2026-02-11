# Orchestrator Health Monitoring - FINAL CORRECTED PLAN

**Session 199 (Final)** | **Date:** 2026-02-11 | **Status:** Corrected Per Opus Investigation

---

## Critical Discovery: What Actually Triggers Phase 3

### Investigation Results

**Opus was right - there was a contradiction in the plan.** After investigating the actual trigger mechanism:

**Phase 3 Trigger Mechanism:**
1. **Primary:** Pub/Sub subscription `nba-phase3-analytics-sub`
   - Subscribes to `nba-phase2-raw-complete`
   - **Every Phase 2 processor completion** triggers Phase 3 `/process` endpoint
   - Phase 3 determines which analytics to run based on trigger source

2. **Backup:** Cloud Scheduler `same-day-phase3`
   - Runs at 10:30 AM ET daily
   - Provides fallback if Pub/Sub fails

**The orchestrator IS truly monitoring-only.** The `_triggered` flag tracks completion for observability, but **does not control Phase 3 triggering**.

---

## What ACTUALLY Happened in Session 198

### The Real Root Cause

```
Timeline:
1. Phase 2 processors complete (5/5 active processors) ✅
2. Each processor publishes to nba-phase2-raw-complete ✅
3. Pub/Sub subscription triggers Phase 3 for each processor ✅
4. When nbac_gamebook_player_stats triggers Phase 3:
   ├─ Phase 3 runs verify_boxscore_completeness() check
   ├─ Bug: Check queries bdl_player_boxscores (empty - BDL disabled)
   ├─ Finds 0 boxscores → completeness check FAILS
   ├─ Returns HTTP 500 → Pub/Sub retries
   └─ Retry loop continues for 3 days (completeness never passes)

Result:
- Orchestrator correctly sets _triggered=False (monitoring only)
- Phase 3 never completes analytics processing
- Phase 4-6 blocked (no analytics data)
```

**From code (data_processors/analytics/main_analytics_service.py:863-898):**

When triggered by `nbac_gamebook_player_stats`, Phase 3 runs a completeness check:
```python
if source_table == 'nbac_gamebook_player_stats' and game_date:
    completeness = verify_boxscore_completeness(game_date, project_id)

    if not completeness.get("complete"):
        # Return 500 to trigger Pub/Sub retry
        return jsonify({
            "status": "delayed",
            "reason": "incomplete_boxscores",
            "game_date": game_date
        }), 500
```

**Session 198 bug:** `verify_boxscore_completeness()` queried `bdl_player_boxscores` which was empty because BDL scrapers are disabled.

**Session 198 fix:** Changed completeness check to query `nbac_gamebook_player_stats` instead of BDL.

---

## What This Means for the Canary

### Opus's Point: Monitor the Right Signal

**Wrong approach (original plan):**
```python
# Check if orchestrator set _triggered=True
if processors >= 5 and not triggered:
    alert("Orchestrator stuck!")
```
↑ **Problem:** This monitors a monitoring flag, not whether Phase 3 actually ran

**Right approach (corrected):**
```python
# Check if Phase 3 actually produced analytics data
if phase2_complete and not phase3_ran:
    alert("Phase 3 failed to run!")
```
↑ **Benefit:** Detects the actual problem (Phase 3 not running)

### Why This Matters

**Scenario 1:** Orchestrator `_triggered=False` but Phase 3 ran successfully
- Monitoring flag out of sync (low impact)
- No user impact (predictions still generated)

**Scenario 2:** Orchestrator `_triggered=True` but Phase 3 failed
- Monitoring says success but actual pipeline failed
- High impact (no predictions generated)

**The canary should detect Scenario 2, not Scenario 1.**

---

## Corrected Solution (2 Layers)

### Layer 1: Enhanced Logging (20 min) - UNCHANGED

**Still valuable for diagnostics.** Checkpoints would have shown:
```
Phase 2 complete: 5/5 processors ✅
Orchestrator set _triggered=True ✅
Phase 3 triggered via Pub/Sub ✅
Phase 3 completeness check failed: 0 boxscores found (querying BDL) ❌
```

**No changes needed to Layer 1.**

---

### Layer 2: Pipeline Canary - CORRECTED (30 min)

**Check if Phase 3 actually ran, not orchestrator flag.**

#### Option A: Check Phase 3 Output Tables (RECOMMENDED)

```python
def check_phase3_completion(game_date: str) -> Tuple[bool, Dict, Optional[str]]:
    """
    Check if Phase 3 analytics actually ran for game_date.

    This checks the actual output (player_game_summary) rather than
    orchestrator monitoring flags.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)

        # Check if Phase 3 produced analytics data
        query = f"""
        SELECT
            COUNT(*) as player_records,
            COUNT(DISTINCT game_id) as games_processed
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date = '{game_date}'
        """

        result = list(client.query(query).result())
        row = result[0]

        player_records = row.player_records
        games_processed = row.games_processed

        # Also check how many games were scheduled
        schedule_query = f"""
        SELECT COUNT(*) as scheduled_games
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = '{game_date}'
          AND game_status_text = 'Final'
        """

        schedule_result = list(client.query(schedule_query).result())
        scheduled_games = schedule_result[0].scheduled_games

        metrics = {
            'game_date': game_date,
            'player_records': player_records,
            'games_processed': games_processed,
            'scheduled_games': scheduled_games
        }

        # PROBLEM: No analytics data despite games being final
        if scheduled_games > 0 and player_records == 0:
            # Wait 30 minutes after last game finishes before alerting
            # (gives time for analytics to process)

            # Check when last game finished
            last_game_query = f"""
            SELECT MAX(game_time_utc) as last_game_time
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date = '{game_date}'
              AND game_status_text = 'Final'
            """

            last_game_result = list(client.query(last_game_query).result())
            last_game_time = last_game_result[0].last_game_time

            if last_game_time:
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                time_since_last_game = (now - last_game_time).total_seconds() / 60

                if time_since_last_game < 30:
                    # Still within grace period
                    metrics['minutes_since_last_game'] = time_since_last_game
                    return (True, metrics, None)

            # Grace period exceeded - Phase 3 failed
            error_msg = (
                f"Phase 3 analytics failed for {game_date}: "
                f"{scheduled_games} games final but 0 analytics records. "
                f"Check Phase 3 service logs for completeness check failures."
            )
            return (False, metrics, error_msg)

        # SUCCESS: Analytics data exists
        if player_records > 0:
            return (True, metrics, None)

        # WAITING: No games scheduled or games not final yet
        return (True, metrics, None)

    except Exception as e:
        logger.error(f"Failed to check Phase 3 completion: {e}", exc_info=True)
        return (False, {}, f"BigQuery check failed: {e}")
```

#### Option B: Check Phase 3 Processor Run History (ALTERNATIVE)

```python
def check_phase3_completion(game_date: str) -> Tuple[bool, Dict, Optional[str]]:
    """Check if Phase 3 processors actually ran for game_date"""
    try:
        client = bigquery.Client(project=PROJECT_ID)

        query = f"""
        SELECT
            COUNT(DISTINCT processor_name) as processors_run,
            COUNTIF(status = 'success') as successful_runs,
            STRING_AGG(processor_name, ', ') as processor_list
        FROM nba_orchestration.processor_run_history
        WHERE data_date = '{game_date}'
          AND phase = 'phase_3_analytics'
        """

        result = list(client.query(query).result())
        row = result[0]

        processors_run = row.processors_run
        successful_runs = row.successful_runs

        # Expected: 5 Phase 3 processors
        # (PlayerGameSummaryProcessor, TeamGameSummaryProcessor, etc.)

        if processors_run == 0:
            # Phase 3 never ran
            return (False, metrics, f"Phase 3 processors never ran for {game_date}")

        return (True, metrics, None)

    except Exception as e:
        # Table might not exist
        return (False, {}, f"processor_run_history check failed: {e}")
```

**Recommendation:** Use Option A (check output tables) because:
1. More reliable (checks actual output, not just logs)
2. Detects silent failures (processor ran but produced no data)
3. Doesn't depend on processor_run_history table existing

---

### Layer 2 Integration

```python
def run_all_canaries():
    """Run all canary checks"""
    client = bigquery.Client()
    failures = []

    # Run BigQuery-based canaries
    for check in CANARY_CHECKS:
        passed, metrics, error = run_canary_query(client, check)
        if not passed:
            failures.append({
                'name': check.name,
                'phase': check.phase,
                'error': error,
                'metrics': metrics
            })

    # Check Phase 3 completion (NEW - CORRECTED)
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    passed, metrics, error = check_phase3_completion(yesterday)
    if not passed:
        failures.append({
            'name': 'Phase 3 Analytics Completion',
            'phase': 'phase3_completion',
            'error': error,
            'metrics': metrics
        })
        logger.error(f"🔴 PHASE 3 COMPLETION FAILED: {error}")

    # Send alerts if failures
    if failures:
        send_canary_failures_alert(failures)
        return False

    logger.info("✅ All canaries passed (including Phase 3 completion)")
    return True
```

---

## Addressing Opus's Second Issue: Hardcoded Processor List

### Problem

Line 263 in the canary hardcodes expected processors:
```python
missing_processors = list(set([
    'p2_bigdataball_pbp',
    'p2_odds_game_lines',
    'p2_odds_player_props',
    'p2_nbacom_gamebook_pdf',
    'p2_nbacom_boxscores'
]) - set(completed_processors))
```

**This is exactly the configuration drift that caused Session 198.**

### Solution

Pull from `shared/config/orchestration_config.py`:

```python
from shared.config.orchestration_config import get_orchestration_config

def check_phase3_completion(game_date: str) -> Tuple[bool, Dict, Optional[str]]:
    """Check if Phase 3 analytics actually ran for game_date"""

    # Get expected processors from shared config (same source as orchestrator)
    config = get_orchestration_config()
    expected_phase2_processors = set(config.phase_transitions.phase2_expected_processors)

    # Rest of check logic...
    # Use expected_phase2_processors instead of hardcoded list
```

**Benefit:** Canary and orchestrator always stay in sync. If expected processors change in config, both update automatically.

---

## Revised Implementation Plan

### Pre-Implementation (5 min)

✅ **DONE** - Investigated Phase 3 trigger mechanism

### Layer 1: Enhanced Logging (20 min)

**No changes from previous plan.** Still valuable for diagnostics.

- [ ] Add checkpoint logging to orchestrator
- [ ] Add transaction visibility
- [ ] Deploy orchestrator

### Layer 2: Canary - CORRECTED (30 min)

**Changed from checking `_triggered` flag to checking Phase 3 output.**

- [ ] Add `check_phase3_completion()` function (checks `player_game_summary` table)
- [ ] Pull expected processors from `orchestration_config.py` (not hardcoded)
- [ ] Integrate into `run_all_canaries()`
- [ ] Update Cloud Scheduler to 15-min frequency
- [ ] Test with yesterday's data

### Testing (30 min)

- [ ] Verify canary detects when Phase 3 didn't run
- [ ] Verify 30-min grace period works
- [ ] Verify Slack alerts fire correctly
- [ ] Test with real Session 198 scenario (no analytics data)

**Total: 85 minutes**

---

## What We're Actually Detecting Now

### Before (Incorrect)

```
Check: Orchestrator _triggered flag
Problem: Monitors a monitoring flag, not actual pipeline health
Miss: Phase 3 could fail even if _triggered=True
```

### After (Correct)

```
Check: Phase 3 analytics output (player_game_summary)
Problem: Detects actual pipeline failures
Catch: Phase 3 completeness check failures (Session 198 scenario)
```

---

## Answers to Opus's Questions

### 1. What actually triggers Phase 3?

**Answer:** **(c) Direct Pub/Sub subscription from Phase 2 completion events**

- Subscription: `nba-phase3-analytics-sub`
- Topic: `nba-phase2-raw-complete`
- Every Phase 2 processor completion triggers Phase 3
- Cloud Scheduler `same-day-phase3` is backup (runs 10:30 AM ET)

**The orchestrator is truly monitoring-only.** It tracks completion for observability but doesn't trigger Phase 3.

### 2. Should the canary check orchestrator flag or Phase 3 output?

**Answer:** **Phase 3 output** (player_game_summary table)

**Reasoning:**
- Orchestrator flag can be out of sync (low impact)
- Phase 3 failure blocks all downstream phases (high impact)
- Session 198 had `_triggered=False` correctly reflecting that Phase 3 failed
- Canary should detect the actual problem (Phase 3 not running)

### 3. Hardcoded processor list?

**Answer:** **Pull from orchestration_config.py**

```python
from shared.config.orchestration_config import get_orchestration_config
config = get_orchestration_config()
expected_processors = config.phase_transitions.phase2_expected_processors
```

**Benefit:** Canary and orchestrator stay in sync automatically.

---

## Success Criteria (Updated)

### Immediate (Post-Implementation)

- [ ] Enhanced logging deployed to orchestrator
- [ ] Canary checks Phase 3 output tables (not orchestrator flag)
- [ ] Canary pulls expected processors from shared config
- [ ] Cloud Scheduler runs every 15 minutes
- [ ] Test detects Session 198 scenario (no player_game_summary data)

### 30 Days (Operational)

- [ ] Phase 3 failures detected within 30 minutes
- [ ] Zero false positives (30-min grace period works)
- [ ] MTTD < 30 minutes for analytics pipeline failures

---

## Files to Modify

| File | Changes |
|------|---------|
| `orchestration/cloud_functions/phase2_to_phase3/main.py` | Add checkpoint logging (Layer 1) |
| `bin/monitoring/pipeline_canary_queries.py` | Add `check_phase3_completion()` (Layer 2) |
| `bin/monitoring/pipeline_canary_queries.py` | Import from `orchestration_config.py` |

**No new tables, no new scripts, no hardcoded lists.**

---

## What Session 198 Taught Us

### The Real Lesson

**Monitor outcomes, not intermediaries.**

- ❌ **Don't monitor:** Orchestrator flags, Firestore state, processor counts
- ✅ **Do monitor:** Actual pipeline output (analytics tables, prediction tables)

**Why:** Intermediaries can be out of sync. Output tables tell the truth.

### How This Plan Reflects That

**Layer 1 (Logging):** Enables diagnosis of *why* failures happen
**Layer 2 (Canary):** Detects *that* failures happen (by checking output)

Together: Fast detection + root cause visibility

---

## Ready for Implementation

✅ Phase 3 trigger mechanism investigated and understood
✅ Canary corrected to check actual output, not monitoring flag
✅ Hardcoded processor list replaced with shared config
✅ All Opus feedback addressed

**Total effort: 85 minutes**
**Complexity: Minimal (2 layers, existing infrastructure)**
**Risk: Low (monitors output, doesn't modify orchestrator logic)**

---

**Status:** Ready for final Opus approval and implementation
