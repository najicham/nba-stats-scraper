# WEEK 0 SECURITY - SESSIONS 2 & 3 GUIDE
## Prompts and Guidance for Remaining Sessions

**Date:** January 19, 2026
**Session 1:** COMPLETE (Code Execution fixes)
**Remaining:** Sessions 2 & 3

---

## SESSION 2: HIGH SEVERITY SECURITY (7-9 hours)

### What to Fix

**Issue #9:** Missing Authentication (1 hour)
**Issue #3:** Fail-Open Errors - 4 locations (2.75 hours)
**Issue #2:** SQL Injection - DELETE queries (2-3 hours)
**Issue #2:** SQL Injection - Original 8 queries (3 hours)

### Prompt for Session 2

```
Complete Session 2 high-severity security fixes from Week 0.

READ FIRST:
- docs/08-projects/current/daily-orchestration-improvements/WEEK-0-SECURITY-COMPLETE.md
- Focus on Issues #9, #3, and #2 (critical SQL injections)

SESSION 2 SCOPE (7-9 hours):

1. Issue #9: Add Authentication (1 hour)
   - File: data_processors/analytics/main_analytics_service.py
   - Add @require_auth decorator to /process-date-range endpoint
   - Prevent unauthorized access and DoS attacks

2. Issue #3: Fix Fail-Open Errors (2.75 hours)
   - Fix 4 locations that return fake "success" on errors:
     * main_analytics_service.py (lines 139-150) - 1 hour
     * upcoming_player_game_context_processor.py (lines 1852-1866) - 45 min
     * upcoming_team_game_context_processor.py (lines 1164-1177) - 45 min
     * roster_registry_processor.py (lines 2122-2125) - 15 min
   - Change all to fail-closed (return error, don't fake success)

3. Issue #2: SQL Injection - DELETE Queries (2-3 hours) PRIORITY
   - Fix 3 DELETE queries that can delete all data:
     * espn_boxscore_processor.py line 468
     * nbac_play_by_play_processor.py line 639
     * analytics_base.py line 2055
   - Convert to parameterized queries

4. Issue #2: SQL Injection - Original 8 (3 hours)
   - main_analytics_service.py: 2 queries (lines 74-80, 90-94)
   - diagnose_prediction_batch.py: 6 queries (lines 99-227)
   - Convert ALL to parameterized queries with BigQuery QueryJobConfig

AFTER EACH FIX:
1. Write/update the code
2. Test with valid input
3. Test with SQL injection attempt (should fail safely)
4. Mark complete

CREATE GIT COMMIT when done:
"security(high): Fix authentication, fail-open, and SQL injection (Session 2)"

Expected outputs:
- 7 files updated with security fixes
- All SQL queries parameterized
- Authentication enforced
- Fail-open patterns eliminated
- Unit tests passing
```

---

## SESSION 3: MEDIUM SEVERITY + VALIDATION (6-7 hours)

### What to Fix

**Issue #2:** SQL Injection - Extended 29 queries (3-4 hours)
**Issue #4:** Input Validation (1.5 hours)
**Issue #5:** Cloud Logging (30 min)
**Issue #10-13:** Medium issues (3 hours)
**Documentation:** Updates (2 hours)

### Prompt for Session 3

```
Complete Session 3 medium-severity security fixes and validation.

READ FIRST:
- docs/08-projects/current/daily-orchestration-improvements/WEEK-0-SECURITY-COMPLETE.md
- Focus on Issues #2 (extended), #4-5, #10-13, plus documentation

SESSION 3 SCOPE (6-7 hours):

1. Issue #2: SQL Injection - Extended Scope (3-4 hours)
   - File: upcoming_player_game_context_processor.py
   - Fix 29 f-string queries throughout file
   - Lines: 583, 659-760, 938
   - Convert to parameterized queries
   - Consider automated refactoring tool

2. Issue #4: Input Validation (1.5 hours)
   - Create shared/utils/validation.py
   - Add validate_game_date() function
   - Add validate_project_id() function with allowlist
   - Apply to main_analytics_service.py and diagnose_prediction_batch.py

3. Issue #5: Cloud Logging (30 min)
   - Fix diagnose_prediction_batch.py lines 223-240
   - Implement actual logging client (not hardcoded return 0)

4. Medium Severity Issues (3 hours):
   - Issue #10: Thread pool exhaustion (1.5h)
   - Issue #12: Pub/Sub message validation (1h)
   - Issue #13: Sensitive data in logs (45min)

5. Documentation Updates (2 hours):
   - Update README.md (Phase 1-2 to DEPLOYED)
   - Update IMPLEMENTATION-TRACKING.md (3/28 → 15/28)
   - Update JITTER-ADOPTION-TRACKING.md (0% → 22%)
   - Create security fix documentation

6. Final Validation (1 hour):
   - Test merge to main
   - All unit tests pass
   - All integration tests pass
   - Security scan (bandit, semgrep)

CREATE GIT COMMIT when done:
"security(complete): Week 0 security fixes complete - 13 issues resolved"

Then create final summary document.
```

---

## RECOMMENDED EXECUTION SEQUENCE

### Day 1: Session 1 (DONE)
✅ Code Execution fixes (2.5-3 hours)
- eval() removal
- Pickle protection
- Hardcoded secrets

### Day 2: Session 2 (7-9 hours)
⏳ High Severity fixes
- Authentication
- Fail-open patterns
- SQL injection (critical paths)

**Decision Point:** If Session 2 takes full 9 hours, consider splitting:
- Day 2: Issues #9, #3 (authentication + fail-open) - 4 hours
- Day 3: Issue #2 (SQL injection) - 5 hours
- Day 4: Session 3 (6-7 hours)

### Day 3-4: Session 3 (6-7 hours)
⏳ Medium Severity + Documentation
- SQL injection extended scope
- Input validation
- Medium issues
- Documentation
- Final validation

---

## CRITICAL NOTES

### SQL Injection Pattern (Use This!)

**BEFORE (Vulnerable):**
```python
query = f"SELECT * FROM `{table}` WHERE game_date = '{game_date}'"
results = bq_client.query(query).result()
```

**AFTER (Secure):**
```python
from google.cloud import bigquery

query = """
SELECT * FROM `your_project.dataset.table`
WHERE game_date = @game_date
"""

job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
    ]
)

results = bq_client.query(query, job_config=job_config).result()
```

### Fail-Open Pattern (Use This!)

**BEFORE (Vulnerable):**
```python
except Exception as e:
    return {"complete": True}  # 🔴 Fake success
```

**AFTER (Secure):**
```python
except Exception as e:
    logger.error(f"Check FAILED: {e}", exc_info=True)
    return {
        "complete": False,  # ✅ Fail-closed
        "is_error_state": True,
        "error": str(e)
    }
```

---

## TESTING STRATEGY

### For Each Security Fix:

**1. Unit Test - Valid Input**
```python
def test_valid_input():
    result = function_under_test(game_date="2026-01-19")
    assert result is not None
```

**2. Unit Test - Invalid Input**
```python
def test_sql_injection_blocked():
    malicious = "2026-01-19' OR '1'='1"
    with pytest.raises(ValueError):
        function_under_test(game_date=malicious)
```

**3. Integration Test**
```python
def test_end_to_end():
    # Valid request → Success
    # Invalid request → Proper error
```

---

## GO/NO-GO DECISION TREE

```
All Session 1 fixes complete? (eval, pickle, secrets)
  ├─ YES → Proceed to Session 2
  └─ NO → STOP, complete Session 1 first

All Session 2 fixes complete? (auth, fail-open, SQL DELETE)
  ├─ YES → Proceed to Session 3
  └─ NO → Can proceed if only extended SQL injection remains

All Session 3 fixes complete?
  ├─ YES → Ready for Phase A deployment
  └─ NO → Assess which issues remain, determine if blocking
```

---

## ABBREVIATED SESSION 2 & 3 DETAILS

Due to context limits, full detailed documents like SESSION-1-CODE-EXECUTION.md would be very long. Instead:

**Use WEEK-0-SECURITY-COMPLETE.md as your reference**
- Has all 13 issues documented
- Has attack scenarios
- Has secure code examples
- Has effort estimates

**Use the prompts above** to start each session

**Agent will read WEEK-0-SECURITY-COMPLETE.md** and follow the documented fixes

---

## FINAL DELIVERABLES

After all 3 sessions complete:

1. **Git Commits (3 total):**
   - Session 1: Code execution fixes
   - Session 2: High severity fixes
   - Session 3: Medium + docs

2. **Documentation Updates:**
   - README.md (env vars, Phase 1-2 status)
   - IMPLEMENTATION-TRACKING.md (progress)
   - Security log (all 13 fixes documented)

3. **Test Results:**
   - All unit tests pass
   - All integration tests pass
   - Security scan clean

4. **Deployment Readiness:**
   - Feature flags configured
   - Environment variables set
   - Rollback procedures documented

---

## NEED MORE DETAIL?

If you want full detailed session docs like SESSION-1-CODE-EXECUTION.md for Sessions 2 & 3:

**Option A:** I can create them (will be 40-50 pages each)
**Option B:** Use WEEK-0-SECURITY-COMPLETE.md + prompts above (leaner)

**My recommendation:** Option B - the master doc has everything, prompts are focused.

---

**Ready to start Session 2?** Use the Session 2 prompt above!
