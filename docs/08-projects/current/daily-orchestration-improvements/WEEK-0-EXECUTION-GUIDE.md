# WEEK 0 SECURITY FIXES - EXECUTION GUIDE
## How Many Chats to Create & What Prompts to Use

**Date:** January 19, 2026
**Total Work:** 15.5-19 hours (13 security issues)
**Sessions:** 3 focused sessions recommended
**Status:** Ready to execute

---

## EXECUTIVE SUMMARY

After comprehensive security review, **13 critical issues** were found (not just 6).

**Most Critical Findings:**
- 🔴 **eval() code execution** - Allows arbitrary code execution (RCE)
- 🔴 **Pickle deserialization** - RCE via malicious model files
- ⚠️ **41 SQL injections** (not 8) - Including DELETE queries that can wipe data
- ⚠️ **No authentication** on admin endpoint - DoS vector

**Timeline:** 3 days (3 sessions) to fix all 13 issues

---

## HOW MANY CHAT SESSIONS TO CREATE

### ✅ RECOMMENDED: **3 CHAT SESSIONS**

**Why 3 sessions:**
1. **Session 1 (2.5-3h):** Most critical RCE fixes - short, focused
2. **Session 2 (7-9h):** Bulk of security work - sustained focus needed
3. **Session 3 (6-7h):** Lower-stakes completion - can defer if needed

**Total: ~16-19 hours across 3 sessions**

---

## SESSION-BY-SESSION BREAKDOWN

### SESSION 1: CODE EXECUTION FIXES (2.5-3 hours) ⚠️ HIGHEST PRIORITY

**Create Chat #1 with this prompt:**

```
Complete Week 0 Session 1: Critical Code Execution Fixes

READ THESE DOCUMENTS FIRST:
1. docs/08-projects/current/daily-orchestration-improvements/SESSION-1-CODE-EXECUTION.md (main guide)
2. docs/08-projects/current/daily-orchestration-improvements/WEEK-0-SECURITY-COMPLETE.md (reference)

CRITICAL CONTEXT:
- Remote Code Execution (RCE) vulnerabilities found
- eval() allows arbitrary code execution on your servers
- Pickle allows code execution via malicious model files
- These MUST be fixed before any other security work

SESSION 1 TASKS (2.5-3 hours):

1. Issue #8: Remove eval() Code Execution (30 min) ⚠️ START HERE
   - File: scripts/test_nbac_gamebook_processor.py lines 40-44
   - Replace eval() with ast.literal_eval()
   - Search entire codebase for other eval() usage
   - Test: Code execution attempts should fail

2. Issue #7: Fix Pickle Deserialization (1-2 hours)
   - File: ml/model_loader.py lines 224-230
   - Create scripts/generate_model_hashes.py
   - Add SHA256 hash validation before loading models
   - Generate .sha256 files for all existing models
   - Test: Modified model file should be rejected

3. Issue #1: Remove Hardcoded Secrets (35 min)
   - BettingPros API key (scrapers/utils/nba_header_utils.py line 154)
   - Sentry DSN (scrapers/scraper_base.py line 24)
   - Move both to environment variables
   - Search for other hardcoded secrets

FOLLOW THE STEP-BY-STEP GUIDE in SESSION-1-CODE-EXECUTION.md.

After completing all 3 issues:
1. Run verification commands
2. Ensure all tests pass
3. Create git commit (message template in session doc)
4. Report completion status

Expected outputs:
- eval() completely removed from codebase
- All models have .sha256 hash files
- No hardcoded secrets remain
- Git commit created

This session is CRITICAL - these are Remote Code Execution vulnerabilities.
```

**Expected Duration:** 2.5-3 hours
**Difficulty:** Medium (clear fixes, well-documented)

---

### SESSION 2: HIGH SEVERITY SECURITY (7-9 hours)

**Create Chat #2 with this prompt:**

```
Complete Week 0 Session 2: High Severity Security Fixes

READ FIRST:
- docs/08-projects/current/daily-orchestration-improvements/WEEK-0-SECURITY-COMPLETE.md
- docs/08-projects/current/daily-orchestration-improvements/SESSIONS-2-3-PROMPTS.md

CONTEXT:
- Session 1 completed: RCE vulnerabilities eliminated
- Session 2 focuses on: Authentication, SQL injection, Fail-open errors
- These are high-severity issues but not RCE

SESSION 2 TASKS (7-9 hours):

1. Issue #9: Add Authentication (1 hour) - START HERE
   - File: data_processors/analytics/main_analytics_service.py
   - Add @require_auth decorator to /process-date-range endpoint
   - Prevent unauthorized access and DoS attacks
   - Test: Requests without API key should return 401

2. Issue #3: Fix Fail-Open Errors (2.75 hours)
   - Fix 4 locations that return fake "success" on errors:
   Location 1: main_analytics_service.py lines 139-150 (1 hour)
   Location 2: upcoming_player_game_context_processor.py lines 1852-1866 (45 min)
   Location 3: upcoming_team_game_context_processor.py lines 1164-1177 (45 min)
   Location 4: roster_registry_processor.py lines 2122-2125 (15 min)
   - Change all to fail-closed (return error instead of fake success)
   - Add degraded mode escape hatch to Location 1

3. Issue #2: SQL Injection - DELETE Queries (2-3 hours) PRIORITY
   - Fix 3 DELETE queries that can delete all data:
   File 1: espn_boxscore_processor.py line 468
   File 2: nbac_play_by_play_processor.py line 639
   File 3: analytics_base.py line 2055
   - Convert to parameterized queries with BigQuery QueryJobConfig
   - Test: SQL injection attempts should fail safely

4. Issue #2: SQL Injection - Original 8 Queries (3 hours)
   - main_analytics_service.py: 2 queries (lines 74-80, 90-94)
   - diagnose_prediction_batch.py: 6 queries (lines 99-227)
   - Convert ALL to parameterized queries
   - Pattern in SESSIONS-2-3-PROMPTS.md

REFERENCE PATTERN (SQL Injection Fix):
```python
# BEFORE (vulnerable):
query = f"SELECT * FROM table WHERE game_date = '{game_date}'"

# AFTER (secure):
from google.cloud import bigquery
query = "SELECT * FROM table WHERE game_date = @game_date"
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
    ]
)
results = bq_client.query(query, job_config=job_config).result()
```

After completing all issues:
1. Test each fix with valid and invalid input
2. Ensure SQL injection attempts are blocked
3. Create git commit
4. Report completion

Expected outputs:
- Authentication enforced on admin endpoints
- 4 fail-open patterns fixed
- 11 SQL injection points fixed (3 DELETE + 8 queries)
- All tests passing
```

**Expected Duration:** 7-9 hours
**Difficulty:** High (many files, repetitive fixes)
**Can Split Into 2 Days:** If needed, break after Issue #3

---

### SESSION 3: MEDIUM SEVERITY + VALIDATION (6-7 hours)

**Create Chat #3 with this prompt:**

```
Complete Week 0 Session 3: Medium Severity Fixes and Final Validation

READ FIRST:
- docs/08-projects/current/daily-orchestration-improvements/WEEK-0-SECURITY-COMPLETE.md
- docs/08-projects/current/daily-orchestration-improvements/SESSIONS-2-3-PROMPTS.md

CONTEXT:
- Sessions 1-2 complete: All critical/high issues fixed
- Session 3: Complete remaining security + documentation
- Lower stakes - can defer some issues if time-constrained

SESSION 3 TASKS (6-7 hours):

1. Issue #2: SQL Injection - Extended Scope (3-4 hours)
   - File: upcoming_player_game_context_processor.py
   - Fix 29 f-string queries throughout file
   - Lines: 583, 659-760, 938
   - Convert to parameterized queries (use pattern from Session 2)

2. Issue #4: Input Validation (1.5 hours)
   - Create shared/utils/validation.py module
   - Add validate_game_date(game_date) function
   - Add validate_project_id(project_id) function with allowlist
   - Apply to main_analytics_service.py
   - Apply to diagnose_prediction_batch.py
   - Test: Invalid inputs should be rejected

3. Issue #5: Cloud Logging (30 min)
   - Fix diagnose_prediction_batch.py lines 223-240
   - Implement actual logging client (replace hardcoded return 0)
   - Test: Should return actual error count

4. Medium Severity Issues (3 hours total):
   Issue #10: Thread pool exhaustion (1.5 hours)
   Issue #12: Pub/Sub message validation (1 hour)
   Issue #13: Sensitive data in logs (45 min)
   - See WEEK-0-SECURITY-COMPLETE.md for details
   - Can defer to post-deployment if time-constrained

5. Documentation Updates (2 hours):
   - Update README.md (Phase 1-2 status to DEPLOYED)
   - Update IMPLEMENTATION-TRACKING.md (3/28 → 15/28 progress)
   - Update JITTER-ADOPTION-TRACKING.md (0% → 22%)
   - Document all 13 security fixes
   - Update .env.example with new env vars

6. Final Validation (1 hour):
   - Test merge session-98-docs-with-redactions to main
   - Run all unit tests
   - Run all integration tests
   - Run security scanners (bandit, semgrep)
   - Verify no hardcoded secrets: trufflehog

After completing all tasks:
1. Ensure all 13 issues resolved
2. All tests passing
3. Documentation complete
4. Create final git commit
5. Create summary of all fixes

Expected outputs:
- All 13 security issues resolved
- 41 SQL injection points fixed (total)
- Input validation implemented
- Documentation updated
- Ready for Phase A deployment
```

**Expected Duration:** 6-7 hours
**Difficulty:** Medium (documentation + testing)
**Can Defer:** Issues #10-13 if time-constrained

---

## DOCUMENTS YOU HAVE

**Master Reference:**
- `WEEK-0-SECURITY-COMPLETE.md` - All 13 issues documented (use this as reference)

**Session Guides:**
- `SESSION-1-CODE-EXECUTION.md` - Detailed step-by-step for Session 1
- `SESSIONS-2-3-PROMPTS.md` - Prompts and patterns for Sessions 2-3

**Supporting Docs:**
- `FINAL-IMPLEMENTATION-PLAN-2026-01-19.md` - Overall deployment plan
- `SECURITY-REVIEW-FEEDBACK.md` - Security review that found 7 new issues

---

## EXECUTION TIMELINE

### Recommended Schedule

**Day 1:**
- Session 1 (2.5-3 hours)
- Break/review

**Day 2:**
- Session 2 Part 1: Issues #9, #3 (4 hours)
- Break
- Session 2 Part 2: Issue #2 SQL injection (4-5 hours)

**Day 3:**
- Session 3 (6-7 hours)
- Final validation and review

**Alternative (3 Full Days):**
- Day 1: Session 1 only
- Day 2: Session 2 only
- Day 3: Session 3 only

---

## GO/NO-GO DECISION POINTS

### After Session 1:
✅ **MUST BE COMPLETE** - RCE vulnerabilities are blocking
- eval() removed? → YES required
- Pickle protected? → YES required
- Secrets moved to env? → YES required

### After Session 2:
⚠️ **HIGH PRIORITY** - Should complete before Phase A
- Authentication added? → STRONGLY RECOMMENDED
- Fail-open fixed? → REQUIRED
- DELETE query SQL injection fixed? → REQUIRED
- Other SQL injection? → Recommended

### After Session 3:
📊 **MEDIUM PRIORITY** - Can defer some with mitigation
- Extended SQL injection? → Recommended
- Input validation? → Recommended
- Medium issues? → Can defer if mitigated
- Documentation? → REQUIRED

---

## SUCCESS CRITERIA

### Session 1 Success:
- [ ] No eval() in codebase (grep verification)
- [ ] All models have .sha256 files
- [ ] No hardcoded secrets (trufflehog verification)
- [ ] 1 git commit created

### Session 2 Success:
- [ ] Authentication enforced on /process-date-range
- [ ] 4 fail-open patterns fixed
- [ ] 3 DELETE query SQL injections fixed
- [ ] 8 original SQL injections fixed
- [ ] 1 git commit created

### Session 3 Success:
- [ ] 29 extended SQL injections fixed (total 41/41)
- [ ] Input validation implemented
- [ ] Cloud logging implemented
- [ ] Documentation updated
- [ ] All tests passing
- [ ] 1 git commit created

### Overall Success (Ready for Phase A):
- [ ] All 13 security issues resolved
- [ ] 3 git commits created
- [ ] Security scan clean
- [ ] Documentation complete
- [ ] Feature flags configured
- [ ] Environment variables documented

---

## COMMON PATTERNS TO USE

### SQL Injection Fix Pattern:
```python
# See SESSIONS-2-3-PROMPTS.md for full pattern
from google.cloud import bigquery
query = "SELECT * FROM table WHERE date = @date"
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("date", "DATE", date_value),
    ]
)
```

### Fail-Closed Pattern:
```python
except Exception as e:
    logger.error(f"FAILED: {e}", exc_info=True)
    return {"complete": False, "is_error_state": True, "error": str(e)}
```

### Validation Pattern:
```python
is_valid, error = validate_game_date(game_date)
if not is_valid:
    raise ValueError(f"Invalid input: {error}")
```

---

## IF YOU NEED HELP

**Stuck on a fix?** Check WEEK-0-SECURITY-COMPLETE.md for:
- Exact file locations
- Attack scenarios
- Secure code examples
- Testing procedures

**Need more detail?** Session docs have:
- Step-by-step checklists
- Verification commands
- Test procedures
- Git commit templates

**Want to split sessions differently?** Flexible! Just ensure:
- Session 1 (RCE fixes) completes first
- DELETE query SQL injections fixed before extended scope
- All critical issues fixed before Phase A deployment

---

## FINAL NOTES

**Total Effort:** 15.5-19 hours (vs original 9.5-11 hours)

**Why More Work:**
- 7 new critical issues found (eval, pickle, etc.)
- SQL injection scope 5x larger (41 points vs 8)
- Fail-open patterns more widespread (4 vs 1)

**This Is Worth It:**
- Prevents Remote Code Execution attacks
- Prevents data deletion via SQL injection
- Prevents DoS attacks
- Protects credentials
- Ensures data integrity

**You're eliminating 13 critical security vulnerabilities before deploying new features. This is the right approach.**

---

## READY TO START?

**Step 1:** Create Chat #1
**Step 2:** Copy/paste Session 1 prompt (from above)
**Step 3:** Let agent work through fixes
**Step 4:** Review results, create git commit
**Step 5:** Create Chat #2 for Session 2

**Good luck! These fixes will dramatically improve your security posture.** 🛡️
