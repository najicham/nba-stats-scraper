# NEXT SESSION: Review Plan with Opus & Implement Tier 1

**Created:** 2026-02-05 (Session 123)
**For:** Next session (Session 124 or later)
**Priority:** P0 CRITICAL
**Time Required:** 5-6 hours (1h review + 4-5h implementation)

---

## Your Mission (Next Session)

1. **Review the prevention plan with an Opus agent** (1 hour)
2. **If approved: Implement Tier 1 fixes** (4 hours)
3. **Deploy and verify** (30 min)

---

## Step 1: Review with Opus Agent (1 hour)

### What to Review

**Context:** We discovered a race condition where PlayerGameSummaryProcessor ran BEFORE TeamOffenseGameSummaryProcessor on Feb 3, causing 19 players to have impossible usage_rate values (600-1275%).

**Prevention Plan:** 3-tier, 60-hour implementation
- **Tier 1 (4h):** Sequential execution groups + dependency gates
- **Tier 2 (16h):** Verification, retry logic, bypass audit
- **Tier 3 (40h):** DAG orchestration, real-time tracking, chaos tests

**Files to Review:**
1. `docs/08-projects/current/phase3-race-condition-prevention/README.md` - Overview
2. `docs/08-projects/current/phase3-race-condition-prevention/PREVENTION-PLAN.md` - Detailed implementation
3. `docs/09-handoff/2026-02-05-SESSION-123-RACE-CONDITION-FIX.md` - Investigation findings

### Spawn Opus Agent for Review

```
Use Task tool with model="opus":

Task(
  subagent_type="general-purpose",
  model="opus",
  description="Review race condition prevention plan",
  prompt="""
  I need you to review the Phase 3 race condition prevention plan and identify any risks or negative impacts.

  **Context:**
  - Feb 3: PlayerGameSummaryProcessor ran 92 minutes BEFORE TeamOffenseGameSummaryProcessor
  - Cause: Parallel execution via ThreadPoolExecutor with no dependency ordering
  - Impact: 19 players with impossible usage_rate values (1228%)
  - Current status: Data is fixed, but race condition can still happen

  **Proposed Fix (Tier 1 - Deploy Tonight):**

  1. **Sequential Execution Groups** (2 hours)
     - Group processors by dependency level
     - Team processors (Level 1) run first, in parallel
     - Player processors (Level 2) run second, after Level 1 completes
     - Code changes: main_analytics_service.py lines 364-382, 535-544

  2. **Orchestration-Level Dependency Gate** (2 hours)
     - Check dependencies BEFORE launching processors
     - Fail fast if dependencies missing (return 500 for Pub/Sub retry)
     - Add DependencyGate class to main_analytics_service.py

  **Questions for Review:**

  1. **Performance Impact:** Will sequential groups significantly slow Phase 3?
     - Current: All processors run in parallel (~5 min total)
     - Proposed: Groups run sequentially, within groups parallel
     - Estimate impact?

  2. **Risk Assessment:** What could go wrong with this change?
     - Could it cause deadlocks?
     - Could it break existing workflows?
     - Are there edge cases we're missing?

  3. **Alternative Approaches:** Is there a better/safer way?
     - Should we use Cloud Workflows instead?
     - Is there a simpler fix?
     - Should we phase the rollout differently?

  4. **Deployment Strategy:** How should we deploy safely?
     - Deploy to dev first?
     - Canary deployment (10% traffic)?
     - What's the rollback plan?

  5. **Testing Requirements:** What must we test before production?
     - Unit tests needed?
     - Integration tests needed?
     - What scenarios to test?

  **Your Task:**
  1. Read the prevention plan (PREVENTION-PLAN.md)
  2. Analyze the proposed Tier 1 changes
  3. Identify risks, performance impacts, edge cases
  4. Recommend: GO / NO-GO / MODIFY
  5. If MODIFY, suggest specific changes

  **Output Format:**
  ```
  ## REVIEW SUMMARY

  **Recommendation:** [GO / NO-GO / MODIFY]

  **Performance Impact:** [estimate]

  **Risks Identified:**
  1. [Risk 1]
  2. [Risk 2]

  **Edge Cases:**
  1. [Edge case 1]

  **Deployment Recommendations:**
  1. [Recommendation 1]

  **Testing Requirements:**
  1. [Test 1]

  **Overall Assessment:** [2-3 sentences]
  ```

  Be thorough but concise. Focus on ACTIONABLE feedback.
  """
)
```

### Review Criteria

**Proceed with Tier 1 implementation IF:**
- ✅ Opus recommendation is "GO" or minor "MODIFY"
- ✅ Performance impact < 20% (acceptable trade-off for correctness)
- ✅ No critical risks identified
- ✅ Testing requirements are reasonable (can complete tonight)
- ✅ Rollback plan is clear

**Do NOT proceed IF:**
- ❌ Opus recommendation is "NO-GO"
- ❌ Performance impact > 50% (too slow)
- ❌ Critical risks identified (data corruption, deadlocks, etc.)
- ❌ Testing requirements are extensive (>2 hours)
- ❌ Unclear rollback plan

---

## Step 2: Implement Tier 1 (If Approved - 4 hours)

### Prerequisites

1. **Backup current code:**
   ```bash
   git checkout -b session-124-tier1-implementation
   cp data_processors/analytics/main_analytics_service.py \
      data_processors/analytics/main_analytics_service.py.backup
   ```

2. **Read the implementation guide:**
   - File: `docs/08-projects/current/phase3-race-condition-prevention/PREVENTION-PLAN.md`
   - Section: "Tier 1: Immediate Fixes"

### Implementation Checklist

#### Fix 1.1: Sequential Execution Groups (2 hours)

**File:** `data_processors/analytics/main_analytics_service.py`

**Changes:**

1. **Replace ANALYTICS_TRIGGERS dict** (lines 364-382)
   ```python
   # OLD: Simple list of processors
   ANALYTICS_TRIGGERS = {
       'nbac_gamebook_player_stats': [
           PlayerGameSummaryProcessor,
           TeamOffenseGameSummaryProcessor,
           TeamDefenseGameSummaryProcessor
       ]
   }

   # NEW: Grouped by dependency level
   ANALYTICS_TRIGGER_GROUPS = {
       'nbac_gamebook_player_stats': [
           {
               'level': 1,
               'processors': [
                   TeamOffenseGameSummaryProcessor,
                   TeamDefenseGameSummaryProcessor
               ],
               'parallel': True,
               'description': 'Team stats - foundation for player calculations'
           },
           {
               'level': 2,
               'processors': [PlayerGameSummaryProcessor],
               'parallel': False,
               'dependencies': ['TeamOffenseGameSummaryProcessor'],
               'description': 'Player stats - requires team possessions'
           }
       ]
   }
   ```

2. **Update run_analytics_processors()** (lines 535-544)
   - See PREVENTION-PLAN.md for full implementation
   - Add group-based sequential execution
   - Maintain parallel execution within groups

3. **Add DependencyFailureError exception:**
   ```python
   class DependencyFailureError(Exception):
       """Raised when a critical dependency processor fails."""
       pass
   ```

**Testing:**
```bash
# Test in dev
curl -X POST "${DEV_URL}/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"start_date": "2026-02-03", "end_date": "2026-02-03", "processors": ["TeamOffenseGameSummaryProcessor", "PlayerGameSummaryProcessor"]}'

# Verify logs show:
# "Level 1: Running 1 processors - Team stats"
# "✅ TeamOffenseGameSummaryProcessor completed"
# "✅ Level 1 complete"
# "Level 2: Running 1 processors - Player stats"
```

#### Fix 1.2: Orchestration-Level Dependency Gate (2 hours)

**File:** `data_processors/analytics/main_analytics_service.py`

**Changes:**

1. **Add DependencyGate class** (before /process endpoint)
   - See PREVENTION-PLAN.md for full implementation
   - Checks if dependencies have data for game_date
   - Returns (can_run, missing_deps, details)

2. **Update /process endpoint**
   - Add dependency check loop before processing
   - Return 500 if dependencies missing (triggers Pub/Sub retry)
   - Log dependency status

**Testing:**
```bash
# Test 1: Missing dependency (should fail)
bq query "DELETE FROM nba_analytics.team_offense_game_summary WHERE game_date = '2026-02-06'"

curl -X POST "${URL}/process" -d '{"source_table": "nbac_gamebook_player_stats", "game_date": "2026-02-06"}'

# Expected: 500 error with "dependency_not_ready"

# Test 2: Dependency ready (should succeed)
# Run team processor first, then player
# Expected: 200 success
```

### Code Quality Checklist

- [ ] Code follows existing style
- [ ] Docstrings added for new classes/methods
- [ ] Error handling for edge cases
- [ ] Logging at appropriate levels (INFO for success, WARNING for retries, ERROR for failures)
- [ ] No hardcoded values (use constants)

---

## Step 3: Deploy and Verify (30 min)

### Deployment Steps

1. **Run pre-deployment checks:**
   ```bash
   # Lint check
   flake8 data_processors/analytics/main_analytics_service.py

   # Validate imports
   python -c "import data_processors.analytics.main_analytics_service"

   # Check deployment drift
   ./bin/check-deployment-drift.sh
   ```

2. **Deploy to dev first:**
   ```bash
   # Build and push dev image
   gcloud builds submit --config cloudbuild.yaml \
     --substitutions=_SERVICE_NAME=nba-phase3-analytics-processors-dev

   # Test with Feb 3 data
   # (see testing commands above)
   ```

3. **Deploy to production (canary):**
   ```bash
   # Deploy with traffic split
   ./bin/deploy-service.sh nba-phase3-analytics-processors --traffic=10

   # Monitor for 1 hour
   gcloud logging read "resource.labels.service_name=nba-phase3-analytics-processors" --limit=100

   # If successful, route 100% traffic
   gcloud run services update-traffic nba-phase3-analytics-processors \
     --to-latest --region=us-west2
   ```

4. **Verify deployment:**
   ```bash
   # Check deployed commit
   ./bin/whats-deployed.sh

   # Trigger test processing
   # Monitor logs for "Level 1 complete" → "Level 2" sequence
   ```

### Verification Checklist

- [ ] Logs show correct level progression (Level 1 → Level 2)
- [ ] Team processors complete before player processor starts
- [ ] No performance regression >20%
- [ ] No errors in logs
- [ ] Dependency gate blocks when dependencies missing
- [ ] Pub/Sub retry works (500 triggers retry)

### Rollback Plan

**If issues detected:**
```bash
# Immediate rollback
git revert HEAD
./bin/deploy-service.sh nba-phase3-analytics-processors

# Verify rollback
./bin/whats-deployed.sh

# Check logs for normal operation
```

---

## Success Criteria

### Must Have (Required)
- ✅ Player processor CANNOT start before team processors complete
- ✅ Dependency gate blocks processing when dependencies missing
- ✅ Clear error messages in logs
- ✅ No data corruption

### Should Have (Important)
- ✅ Performance degradation <20%
- ✅ Logs clearly show level progression
- ✅ Pub/Sub retry works automatically

### Nice to Have (Optional)
- ✅ Performance degradation <10%
- ✅ Comprehensive error diagnostics
- ✅ Monitoring dashboard updated

---

## If You Encounter Issues

### Issue 1: Performance Regression >20%

**Diagnosis:**
```bash
# Compare execution times
# Before: Check cloud logs for Phase 3 duration
# After: Check cloud logs for Phase 3 duration
```

**Solutions:**
- Reduce level granularity (combine more processors in Level 1)
- Increase parallelism within levels
- Profile slow processors, optimize

### Issue 2: Deployment Fails

**Diagnosis:**
```bash
# Check build logs
gcloud builds list --limit=5

# Check import errors
python -c "import data_processors.analytics.main_analytics_service"
```

**Solutions:**
- Fix import errors
- Verify all dependencies in requirements.txt
- Check Dockerfile changes

### Issue 3: Tests Fail

**Diagnosis:**
```bash
# Check error logs
gcloud logging read "severity>=ERROR" --limit=50
```

**Solutions:**
- Review test data (Feb 3 should have team stats)
- Check dependency logic (is threshold too strict?)
- Verify table references

### Issue 4: Unclear If Safe to Proceed

**Action:** STOP and document concerns
- Create issue in GitHub
- Document blocking concerns in handoff
- Schedule team review
- DO NOT deploy if uncertain

---

## Context for Next Session

### Current Status (End of Session 123)

**Problem:** SOLVED
- Data is correct (max usage_rate = 45.7%)
- Root cause identified (race condition)
- Prevention plan designed

**Documentation:** COMPLETE
- Project README
- Prevention plan (3 tiers, 60 hours)
- Session handoff

**Code Changes:** NONE YET
- Investigation and planning only
- Implementation starts next session

### What Session 123 Accomplished

1. ✅ Multi-agent investigation (3 agents, ~4 hours)
2. ✅ Root cause identified (parallel execution race condition)
3. ✅ Data verified as correct
4. ✅ Prevention plan designed (60 hours, 3 tiers)
5. ✅ Comprehensive documentation created

### Key Files

**Documentation:**
- `docs/08-projects/current/phase3-race-condition-prevention/README.md`
- `docs/08-projects/current/phase3-race-condition-prevention/PREVENTION-PLAN.md`
- `docs/09-handoff/2026-02-05-SESSION-123-RACE-CONDITION-FIX.md`

**Code to Modify (Tier 1):**
- `data_processors/analytics/main_analytics_service.py` (lines 364-382, 535-544)

### Timeline

- **Feb 3:** Race condition occurs (92-min gap)
- **Feb 4:** Session 122 detects anomaly, adds validation
- **Feb 5:** Session 123 investigates, designs prevention
- **Tonight:** Session 124 reviews and implements Tier 1 (if approved)

---

## Quick Start Commands

### 1. Read Context
```bash
# Read project README
cat docs/08-projects/current/phase3-race-condition-prevention/README.md

# Read prevention plan
cat docs/08-projects/current/phase3-race-condition-prevention/PREVENTION-PLAN.md

# Read Session 123 handoff
cat docs/09-handoff/2026-02-05-SESSION-123-RACE-CONDITION-FIX.md
```

### 2. Spawn Opus Review
```python
# Use Task tool with model="opus" and the prompt from Step 1 above
```

### 3. Proceed Based on Review
```bash
# If GO: Start implementation
git checkout -b session-124-tier1-implementation

# If NO-GO: Document concerns and wait
# If MODIFY: Apply suggested changes, then implement
```

---

## Estimated Timeline

| Activity | Duration | Can Skip? |
|----------|----------|-----------|
| Read context | 15 min | No |
| Opus review | 30 min | No |
| Decision | 15 min | No |
| **Implementation** | **4 hours** | If NO-GO |
| Testing | 30 min | No (if implementing) |
| Deployment | 30 min | No (if implementing) |
| **Total** | **6 hours** | - |

**Best Case:** 1 hour (review says NO-GO, document concerns)
**Typical Case:** 6 hours (review approves, implement and deploy)
**Worst Case:** 8 hours (issues during deployment, rollback, retry)

---

## Final Checklist

Before ending session, verify:

- [ ] Opus review completed
- [ ] Decision documented (GO/NO-GO/MODIFY)
- [ ] If GO: Tier 1 implemented and deployed
- [ ] If GO: Verification tests passed
- [ ] If NO-GO: Concerns documented
- [ ] Session handoff created
- [ ] All code committed
- [ ] Deployment status clear

---

**Created:** 2026-02-05 (Session 123)
**Status:** Ready for Session 124
**Priority:** P0 CRITICAL

**Good luck! The prevention plan is solid - just need Opus to verify safety before deploying.**
