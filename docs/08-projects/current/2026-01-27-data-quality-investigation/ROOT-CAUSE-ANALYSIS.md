# Root Cause Analysis: 2026-01-27 Data Quality Investigation

**Date**: 2026-01-27
**Investigator**: Claude Opus 4.5
**Status**: Complete
**Context**: Following up on a partial Sonnet fix session that resolved `has_prop_line` but failed on prediction coordinator timeout and deployment

---

## Executive Summary

Six data quality issues were identified on Jan 27, 2026. Investigation reveals interconnected systemic problems in:
1. **Processing order** - Phase 3 processors lack dependency enforcement, causing NULL usage_rate
2. **Timing coordination** - Betting line scrapers run AFTER Phase 3, causing 0 predictions
3. **Data integrity** - MERGE operations create duplicates during backfill due to fallback to DELETE+INSERT
4. **Monitoring gaps** - Critical failures occur silently without alerts
5. **Timeout configuration** - Prediction coordinator has sufficient timeout (30 min) but HTTP client times out earlier (5 min curl default)

---

## Issue #1: Prediction Coordinator Timeout

### What Failed
The prediction coordinator `/start` endpoint did not respond within the HTTP client timeout (5 minutes) during the fix session.

### Why It Failed
1. **Cloud Run timeout is actually sufficient**: The service has a 1800-second (30 minute) timeout configured
2. **HTTP client timeout is too short**: curl's default timeout caused the request to appear as a timeout
3. **Long-running operation pattern**: Loading historical games for 300-400 players takes 5-15 minutes, blocking the HTTP response

**Evidence from coordinator.py (lines 839-873)**:
```python
# Use heartbeat logger to track long-running data load (5-min intervals)
with HeartbeatLogger(f"Loading historical games for {len(player_lookups)} players", interval=300):
    batch_historical_games = data_loader.load_historical_games_batch(
        player_lookups=player_lookups,
        game_date=game_date,
        lookback_days=90,
        max_games=30
    )
```

**Cloud Run Config**:
```bash
$ gcloud run services describe prediction-coordinator --region=us-west2 --format="value(spec.template.spec.timeoutSeconds)"
1800  # 30 minutes - SUFFICIENT
```

### Root Cause
The issue is NOT a Cloud Run timeout. It's the synchronous HTTP request pattern where:
1. Caller expects response within 5 minutes (curl default)
2. Coordinator starts long-running batch load (5-15 min)
3. Request appears to timeout from caller's perspective
4. Coordinator may still complete successfully in the background

### Prevention Recommendations

**Immediate Fix**:
- Use fire-and-forget pattern with longer curl timeout: `curl --max-time 900 ...`
- Or use `curl -X POST ... &` to not wait for response

**Architectural Fix** (Medium-term):
1. Make `/start` return 202 Accepted immediately, do work asynchronously
2. Use Pub/Sub trigger instead of HTTP for long-running operations
3. Add a polling `/status` endpoint pattern for callers

**Detection Mechanism**:
- The coordinator already has heartbeat logging every 5 minutes
- Check Cloud Run logs to verify if processing actually completed after HTTP "timeout"

---

## Issue #2: No Processing Order Between Phase 3 Processors

### What Failed
`player_game_summary` processor runs and attempts to calculate `usage_rate` by JOINing to `team_offense_game_summary`, but team stats don't exist yet.

### Why It Failed
**Design gap**: Phase 3 processors are designed to run in parallel with NO ordering enforcement.

**Evidence from orchestration_config.py (lines 52-58)**:
```python
# Phase 3 -> Phase 4: List of expected processors
phase3_expected_processors: List[str] = field(default_factory=lambda: [
    'player_game_summary',
    'team_defense_game_summary',
    'team_offense_game_summary',       # <-- Player depends on this
    'upcoming_player_game_context',
    'upcoming_team_game_context',
])
```

All 5 processors are treated as independent. The phase3_to_phase4 orchestrator simply waits for ALL to complete, with no internal ordering.

**Evidence from phase3_to_phase4/main.py (lines 173-185)**:
```python
if mode == 'overnight':
    return (
        5,  # Expected count
        {   # Critical processors (must have these)
            'player_game_summary',
            'upcoming_player_game_context'
        },
        {   # Optional processors (nice to have)
            'team_defense_game_summary',
            'team_offense_game_summary',  # <-- Considered "optional" not "prerequisite"
            'upcoming_team_game_context'
        }
    )
```

### Impact Scope
- **Jan 26**: 71% of players (161/226) have NULL usage_rate
- **Jan 15-25**: Similar patterns likely exist (found 29-63% coverage in validation)
- **Cascading effect**: ML feature store receives NULL values, predictions potentially degraded

### Root Cause
1. **Architecture assumption violated**: Original design assumed all Phase 2 data arrives together and Phase 3 processors can run in any order
2. **No soft dependency check**: `player_game_summary` doesn't verify team stats exist before calculating usage_rate
3. **MERGE doesn't fix it**: When player stats are saved first with NULL usage_rate, a later MERGE from team stats won't update the player records

### Prevention Recommendations

**Immediate Fix**:
- Add dependency check in `PlayerGameSummaryProcessor.extract_raw_data()`:
  ```python
  def validate_team_stats_available(self, game_date):
      """Check if team stats exist before calculating usage_rate"""
      query = f"""
      SELECT COUNT(DISTINCT game_id) as team_games
      FROM `{self.project}.{self.dataset}.team_offense_game_summary`
      WHERE game_date = '{game_date}'
      """
      # If 0 games, skip usage_rate calculation or delay processing
  ```

**Architectural Fix** (Medium-term):
1. Define explicit Phase 3 sub-phases:
   - Phase 3a: team_defense_game_summary, team_offense_game_summary
   - Phase 3b: player_game_summary (depends on 3a)
   - Phase 3c: upcoming_* processors
2. Use Pub/Sub topics to enforce ordering within Phase 3
3. Add dependency_config.py entries for Phase 3 internal dependencies

**Detection Mechanism**:
- Alert if `usage_rate IS NULL` for >30% of players on any date
- Add BigQuery scheduled query to check daily

---

## Issue #3: MERGE Created Duplicates During Backfill

### What Failed
93 duplicate records were created in `player_game_summary` during a backfill operation on 2026-01-27 at 20:16 UTC.

### Why It Failed
**Evidence from bigquery_save_ops.py (lines 471-500)**:
```python
# Auto-fallback: If syntax error, use DELETE+INSERT
if "syntax error" in error_msg.lower() or "400" in error_msg:
    logger.warning("MERGE syntax error detected - falling back to DELETE + INSERT")
    # ... notify operators ...
    self._save_with_delete_insert(rows, table_id, table_schema)
    return
```

The MERGE operation failed (likely syntax error due to schema mismatch or missing fields), causing fallback to DELETE+INSERT. However:

1. DELETE runs first, removing records for the date range
2. INSERT runs second, adding new records
3. **Race condition**: If a second backfill request arrives between DELETE and INSERT, duplicates can be created
4. **Streaming buffer issue**: If streaming buffer is active, DELETE fails silently and INSERT adds new records without removing old ones

**Evidence from findings.md (lines 603-607)**:
```
Duplicates on Jan 8 and Jan 13 were created during backfill operation on 2026-01-27 20:16:53:
- Same records inserted twice in same batch
- Identical data_hash confirms exact duplicates
- MERGE operation not properly deduplicating
```

### Root Cause
1. MERGE fallback to DELETE+INSERT is not atomic
2. Concurrent backfill operations can interleave
3. Streaming buffer blocks DELETE but allows INSERT (documented in code comments)
4. No post-save duplicate check with auto-deduplication

### Prevention Recommendations

**Immediate Fix**:
- Add batch-level locking using Firestore distributed lock before any backfill
- Ensure only one backfill operation runs per date at a time

**Code Fix**:
```python
# In _save_with_delete_insert, add check for streaming buffer BEFORE INSERT
def _save_with_delete_insert(self, rows, table_id, table_schema):
    # Check if DELETE actually succeeded
    if delete_job.num_dml_affected_rows == 0 and expected_rows > 0:
        # Streaming buffer may have blocked DELETE - abort INSERT
        raise StreamingBufferActiveError("Cannot INSERT - DELETE was blocked")
```

**Detection Mechanism**:
- `_check_for_duplicates_post_save()` already exists but doesn't auto-fix
- Add scheduled query to detect and alert on duplicates daily
- Add UNIQUE constraint to BigQuery if supported (or use MERGE always)

---

## Issue #4: No Alert for 0 Predictions

### What Failed
Prediction coordinator found 0 eligible players and completed successfully with 0 predictions generated. No alert was sent.

### Why It Failed
**Monitoring exists but is reactive**: `MissingPredictionDetector` (prediction_monitoring/missing_prediction_detector.py) exists and would alert on missing predictions, BUT:

1. It only detects players with betting lines who didn't get predictions
2. When ALL players have `has_prop_line = FALSE`, the query returns 0 "eligible" players
3. Summary shows 0 eligible, 0 predicted, 100% coverage - looks like success!

**Evidence from missing_prediction_detector.py (lines 66-72)**:
```python
AND (
    avg_minutes_per_game_last_7 >= 15
    OR current_points_line IS NOT NULL  # <-- Relies on this being set
)
AND is_production_ready = TRUE
```

When `has_prop_line = FALSE` for all players (due to timing issue), AND `is_production_ready = FALSE` for some, the eligible set becomes very small or empty.

**Evidence from fix-log.md**:
```
2026-01-26 23:06:03 - player_loader - WARNING - No players found for 2026-01-27
2026-01-26 23:06:03 - coordinator - ERROR - No prediction requests created for 2026-01-27
```

The coordinator logs an ERROR but doesn't send an alert.

### Root Cause
1. **0 predictions treated as valid state**: Code handles "no players found" as an error response (404) but doesn't trigger notification
2. **Missing absolute check**: No alert for "predictions = 0 on game day with scheduled games"
3. **Eligible player query depends on has_prop_line**: If timing issue causes has_prop_line = FALSE, system thinks no one is eligible

### Prevention Recommendations

**Immediate Fix in coordinator.py (around line 809)**:
```python
if not requests:
    logger.error(f"No prediction requests created for {game_date}")
    # ADD CRITICAL ALERT
    notify_error(
        title=f"CRITICAL: Zero Predictions for {game_date}",
        message=f"Prediction coordinator found 0 eligible players on a game day!",
        details={
            'game_date': game_date.isoformat(),
            'summary': summary_stats,
            'action_required': 'Check if Phase 3 ran before betting lines were scraped'
        },
        processor_name='PredictionCoordinator'
    )
    return jsonify({'status': 'error', 'message': f'No players found for {game_date}'...
```

**Scheduled Alert**:
Add Cloud Scheduler job to call `/check-missing` after prediction coordinator scheduled run time

**Detection Mechanism**:
- Alert if `COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = TODAY AND is_active = TRUE` = 0 after 8 PM on game days
- Alert if `has_prop_line = FALSE` for 100% of players on game day

---

## Issue #5: Partial Team Stats Cause Impossible Usage Rates

### What Failed
Some players have usage rates >100% (e.g., Luka Doncic at 239.1%), which is mathematically impossible.

### Why It Failed
**Two game_id records exist for same game** in `team_offense_game_summary`:
- `20260124_LAL_DAL` with 10 FG attempts (partial, early scrape)
- `20260124_DAL_LAL` with 90 FG attempts (complete, later scrape)

The player record uses one format, matches to the partial record, and calculates usage_rate with incorrect denominator.

### Root Cause
1. **team_offense_game_summary saves partial data**: Early scrape during live game creates record
2. **No "completeness" check before save**: Processor doesn't verify game is final
3. **MERGE doesn't replace**: Because game_id format differs, it creates new record instead of updating
4. **game_id_reversed fix not deployed**: Commit d3066c88 exists but wasn't deployed to production

### Prevention Recommendations

**Immediate Fix**:
1. Deploy commit d3066c88 (game_id_reversed JOIN logic)
2. Clean up partial records: DELETE from team_offense_game_summary where game is complete but record has low FG attempts

**Code Fix**:
```python
# In team_offense_game_summary_processor.py
def validate_completeness(self, game_data):
    """Verify game is complete before saving"""
    if game_data['game_status'] != 'Final':
        logger.warning(f"Skipping non-final game {game_data['game_id']}")
        return False
    if game_data['fg_attempts'] < 50:  # Sanity check for full game
        logger.warning(f"Suspiciously low FG attempts for {game_data['game_id']}")
        return False
    return True
```

**Detection Mechanism**:
- Alert if any usage_rate > 50% (impossible in normal play)
- Add validation constraint in processor: reject records with usage_rate > 50

---

## Issue #6: Deployment Process Not Clear

### What Failed
Sonnet fix session couldn't deploy code changes to Cloud Run.

### Why It Failed
**Evidence from fix-log.md**:
```
Attempt 1 - Source-based deploy:
gcloud run deploy analytics-processor --source=. --region=us-west2 ...
Error: unrecognized arguments

Attempt 2 - Image-based deploy:
gcloud run deploy analytics-processor --image=gcr.io/nba-props-platform/analytics-processor:latest ...
Error: Image 'gcr.io/nba-props-platform/analytics-processor:latest' not found
```

### Root Cause
1. **No documented deployment procedure**: The repo lacks clear deployment documentation
2. **Image registry location unclear**: Images are in Artifact Registry (us-west2-docker.pkg.dev), not Container Registry (gcr.io)
3. **CI/CD not mentioned**: No GitHub Actions or Cloud Build triggers apparent in investigation

### Prevention Recommendations

**Immediate Documentation** (in DEPLOYMENT.md):
```markdown
# Deployment Procedure

## Build and Deploy Analytics Processor
cd /home/naji/code/nba-stats-scraper
docker build -f data_processors/analytics/Dockerfile -t analytics-processor .
docker tag analytics-processor us-west2-docker.pkg.dev/nba-props-platform/nba-processors/analytics-processor:latest
docker push us-west2-docker.pkg.dev/nba-props-platform/nba-processors/analytics-processor:latest
gcloud run deploy analytics-processor \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-processors/analytics-processor:latest \
  --region=us-west2 --timeout=600 --memory=2Gi
```

**Automation**:
- Add GitHub Actions workflow for automated deployment on merge to main
- Add deployment scripts in `bin/deploy/`

---

## Monitoring Gaps Summary

| Gap | Current State | Recommended Fix |
|-----|---------------|-----------------|
| 0 predictions on game day | Silent failure | Add critical alert in coordinator |
| Low usage_rate coverage | No monitoring | Alert if NULL usage_rate >30% |
| Duplicate records | Post-save check exists but no alert | Add daily scheduled query |
| has_prop_line all FALSE | Not monitored | Alert if 100% FALSE on game day |
| Impossible usage rates | Not monitored | Reject/alert if >50% |
| Phase 3 timing issues | Not monitored | Add dependency checks |

---

## Architecture Improvements Needed

### 1. Processing Order Enforcement
**Problem**: Phase 3 processors run in parallel with hidden dependencies
**Solution**: Define Phase 3 sub-phases or add dependency validation in each processor

### 2. Data Quality Gates Between Phases
**Problem**: Phases proceed even with incomplete/corrupt data
**Solution**: Enhanced PhaseBoundaryValidator (exists but not comprehensive enough)

### 3. Automatic Reprocessing
**Problem**: When team stats arrive late, player stats don't get updated
**Solution**:
- Trigger player_game_summary reprocessing when team_offense_game_summary completes
- Or use eventual consistency with scheduled "fill gaps" job

### 4. Circuit Breakers
**Problem**: One failure cascades to downstream systems
**Solution**: CircuitBreakerConfig exists (orchestration_config.py:152-172) - ensure it's used at Phase boundaries

---

## Action Priority Matrix

| Priority | Issue | Effort | Impact | Recommended Action |
|----------|-------|--------|--------|-------------------|
| P0 | 0 predictions | Low | Critical | Add alert in coordinator for 0 eligible players |
| P1 | Usage rate NULL | Medium | High | Enforce team stats before player stats |
| P1 | Deployment docs | Low | High | Create DEPLOYMENT.md with clear instructions |
| P2 | Duplicate records | Medium | Medium | Add distributed lock for backfill |
| P2 | Impossible usage rates | Low | Medium | Add validation constraint (reject >50%) |
| P3 | HTTP timeout pattern | High | Medium | Convert to async pattern or use Pub/Sub |

---

## Conclusion

The data quality issues stem from systemic gaps in:
1. **Dependency management** between processors in the same phase
2. **Timing coordination** between scrapers and processors
3. **Alerting thresholds** that don't catch edge cases (0 players, 100% NULL)
4. **Deployment documentation** for emergency fixes

The codebase has many defensive patterns already (coverage monitors, heartbeat logging, circuit breakers) but they're not uniformly applied or configured for these specific failure modes.

**Next Steps**:
1. Implement P0/P1 alerts immediately
2. Deploy game_id_reversed fix with proper deployment procedure
3. Schedule tech debt sprint to address Phase 3 dependency ordering
4. Create runbook for "0 predictions" incident response
