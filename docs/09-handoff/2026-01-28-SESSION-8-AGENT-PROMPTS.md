# Agent Prompts for System Hardening Sprint

Use these prompts to spawn parallel agents working on system resilience.

---

## Agent 1: Validation Hardening

### Prompt

```
You are working on the NBA Stats Scraper project. Your mission is to harden the daily validation system so that issues are caught BEFORE they become problems.

## Context

Read the handoff document first:
- /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-28-SESSION-8-WORKSTREAM-1-VALIDATION.md

Also read:
- /home/naji/code/nba-stats-scraper/CLAUDE.md (project instructions)
- /home/naji/code/nba-stats-scraper/.claude/skills/validate-daily/SKILL.md (current validation)

## Problems to Solve

Every morning the user has to manually run validation and discovers issues from overnight processing. We need:

1. **Morning Dashboard** - A single command that shows overnight health in 30 seconds
2. **Pre-flight Checks** - Run at 5 PM before games to verify readiness
3. **Post-processing Alerts** - Automatic Slack notification if overnight processing failed
4. **Better Thresholds** - Catch issues like 63% minutes coverage as CRITICAL

## Your Tasks

1. **Create `bin/monitoring/morning_health_check.sh`**
   - Single script that outputs a clear health summary
   - Shows: games processed, phase completion, data quality metrics
   - Highlights any issues in red
   - Takes < 30 seconds to run

2. **Add pre-flight mode to `scripts/validate_tonight_data.py`**
   - Add `--pre-flight` flag
   - Checks: betting data loaded, game context ready, ML features exist
   - Run before games start (5 PM ET)

3. **Add Slack alerting to `orchestration/cloud_functions/daily_health_check/main.py`**
   - Send to #app-error-alerts for CRITICAL issues
   - Send to #daily-orchestration for daily summary
   - Use existing Slack webhook infrastructure

4. **Update SKILL.md** with morning dashboard instructions

5. **Test everything** against last 3 days of data

## Key Queries to Use

See the handoff doc for:
- Overnight Processing Summary query
- Stuck Phase Detection query
- Scraper Gap Summary query

## Files to Modify/Create

- CREATE: bin/monitoring/morning_health_check.sh
- MODIFY: scripts/validate_tonight_data.py
- MODIFY: orchestration/cloud_functions/daily_health_check/main.py
- MODIFY: .claude/skills/validate-daily/SKILL.md

## Success Criteria

1. Morning check runs in < 30 seconds with clear output
2. Pre-flight mode catches missing betting data
3. Slack alerts work for critical failures
4. Would have caught today's issues (63% minutes, 2/5 phase completion)

## Constraints

- Don't break existing validation
- Use existing Slack webhook environment variables
- Keep scripts simple and readable
- Add comments explaining logic

Commit your changes with clear commit messages. Do NOT push - just commit locally.
```

---

## Agent 2: Orchestration Resilience

### Prompt

```
You are working on the NBA Stats Scraper project. Your mission is to ensure the phase transition orchestrators NEVER fail silently.

## Context

Read the handoff document first:
- /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-28-SESSION-8-WORKSTREAM-2-ORCHESTRATION.md

Also read:
- /home/naji/code/nba-stats-scraper/CLAUDE.md (project instructions)

## Problems to Solve

Today we found:
1. Cloud Functions had import errors causing phase_execution_log gaps (Jan 26-28 missing)
2. Firestore completion tracking only showed 2/5 processors
3. completion_tracker.py had a missing import (firestore.SERVER_TIMESTAMP)
4. Deploy scripts didn't include shared/utils/ in deployment package

These were fixed, but we need to PREVENT similar issues.

## Your Tasks

1. **Audit ALL Cloud Functions for Import Issues**
   - Check every main.py in orchestration/cloud_functions/
   - Look for: missing imports, incorrect import paths, symlink issues
   - Create a report of any issues found
   - Fix any issues you find

2. **Create Deployment Drift Detection**
   - Create `.github/workflows/check-cloud-function-drift.yml`
   - Compare deployed revision timestamp to latest commit
   - Alert if any Cloud Function is > 24 hours behind
   - Run daily at noon UTC

3. **Verify Health Endpoints on All Orchestrators**
   - Check that phase2_to_phase3, phase3_to_phase4, phase4_to_phase5 have /health
   - Health should check: BigQuery, Firestore, Pub/Sub connectivity
   - Add health endpoints where missing

4. **Add Error Alerting to Orchestrators**
   - When a Cloud Function catches an exception, send Slack alert
   - Don't just log - actively notify
   - Use #app-error-alerts webhook

5. **Test the completion_tracker dual-write**
   - Verify Firestore write works
   - Verify BigQuery backup works when Firestore fails
   - Add retry logic if missing

## Key Files

- orchestration/cloud_functions/*/main.py (audit all)
- bin/orchestrators/deploy_*.sh (verify they include shared/utils)
- shared/utils/completion_tracker.py
- shared/utils/phase_execution_logger.py
- shared/endpoints/health.py

## Audit Checklist

For EACH Cloud Function:
- [ ] All imports resolve (no ModuleNotFoundError)
- [ ] No hardcoded paths that break in cloud
- [ ] Health endpoint exists
- [ ] Error handling doesn't swallow exceptions
- [ ] Completion messages published
- [ ] phase_execution_log written

## Success Criteria

1. Audit report shows all Cloud Functions are clean
2. GitHub workflow created and tested
3. Health endpoints verified on all orchestrators
4. Error alerting added
5. Dual-write verified working

## Constraints

- Don't redeploy Cloud Functions (just fix code, commit)
- Focus on the 5 main phase orchestrators first
- Use existing patterns from health.py
- Keep error messages actionable

Commit your changes with clear commit messages. Do NOT push - just commit locally.
```

---

## Agent 3: Data Quality Prevention

### Prompt

```
You are working on the NBA Stats Scraper project. Your mission is to PREVENT data quality issues from occurring, not just detect them.

## Context

Read the handoff document first:
- /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-28-SESSION-8-WORKSTREAM-3-DATA-QUALITY.md

Also read:
- /home/naji/code/nba-stats-scraper/CLAUDE.md (project instructions)

## Problems to Solve

Today we found:
1. Data was processed BEFORE a bug fix was deployed (63% minutes coverage)
2. Backfill was blocked by early_exit_mixin checking if games finished
3. Scraper failures weren't cleared after data was actually backfilled
4. No way to know if data was processed by stale code

## Your Tasks

1. **Add "Processor Version" Tracking**
   - Add `processor_version` field to processor output
   - Include git commit hash or Cloud Run revision
   - Add `processed_at` timestamp
   - This lets us detect stale-code processing

2. **Fix Early Exit for Backfill Mode**
   - Verify the fix in early_exit_mixin.py is correct
   - Test that backfill_mode=True skips problematic checks
   - Add tests if missing

3. **Create Scraper Failure Auto-Cleanup**
   - Script that verifies if data exists for each "failure"
   - Marks backfilled=TRUE if data found
   - Handles postponed games (checks game_status)
   - Run as scheduled job

4. **Add Deployment Freshness Check**
   - Before processing, check if deployment is recent
   - Warn if code is > 24 hours old and there are uncommitted changes
   - Add to processor base class

5. **Enhance Pre-Commit Schema Validation**
   - Check .pre-commit-hooks/validate_schema_fields.py
   - Ensure it catches field mismatches
   - Add test cases for common errors

## Key Files

- shared/processors/patterns/early_exit_mixin.py
- shared/processors/base_processor.py (add version tracking)
- .pre-commit-hooks/validate_schema_fields.py
- scripts/verify_golden_dataset.py
- CREATE: bin/monitoring/cleanup_scraper_failures.py

## Implementation Details

### Processor Version Tracking
```python
# Add to BaseProcessor or similar
def _get_processor_version(self):
    import os
    return os.environ.get('K_REVISION', 'local')[:12]
```

### Scraper Failure Cleanup
```python
# Check if data exists before counting as gap
def cleanup_scraper_failures():
    # Query failures where backfilled=FALSE
    # For each, check if data exists in GCS/BigQuery
    # If exists, UPDATE backfilled=TRUE
    # If game postponed, mark accordingly
```

### Deployment Freshness
```python
# Add to processor initialization
def _check_deployment_freshness(self):
    deployed_at = os.environ.get('K_REVISION_TIMESTAMP')
    if deployed_at and (now - deployed_at) > timedelta(hours=24):
        logger.warning("Processing with deployment > 24 hours old")
```

## Success Criteria

1. Processor version tracked in output records
2. Backfill mode works without early exit blocks
3. Scraper failures auto-cleaned
4. Stale deployment warning works
5. Pre-commit catches schema mismatches

## Constraints

- Don't modify BigQuery schemas (use existing fields or add via ALTER TABLE)
- Keep changes backward compatible
- Test thoroughly before committing
- Focus on prevention, not just detection

Commit your changes with clear commit messages. Do NOT push - just commit locally.
```

---

## How to Use These Prompts

1. **Open 3 new Claude Code sessions** (or use Task tool)
2. **Copy the relevant prompt** into each session
3. **Let them work in parallel**
4. **Review and merge** the commits when done

Each agent will:
- Read the handoff document for full context
- Work on their specific area
- Commit changes locally (not push)
- Report what they accomplished

After all agents complete, review the commits and push together.
