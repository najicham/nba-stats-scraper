# Next Session Prompt - Phase 6 API Gaps Validation

**Copy-paste this to start the next session:**

---

I need to validate the Phase 6 API gaps deployment from Session 209.

**Context:**
- Session 209 completed ALL 3 sprints (16 fixes, 10/10 endpoints working)
- Code deployed to main (commit 6033075b)
- Cloud Build triggered (ID: 785bd5fa)
- Need to validate endpoints and monitor for issues

**Read these first:**
1. `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-02-12-SESSION-209-HANDOFF.md`
2. `/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase6-api-gaps/08-SESSION-209-COMPLETION-SUMMARY.md`

**Tasks:**
1. Check Cloud Build status (should be SUCCESS)
2. Verify services deployed with commit 6033075b
3. Validate all new endpoints and fields
4. Run comprehensive tests (validation commands in handoff doc)
5. Monitor logs for errors
6. Create validation report

**Critical validations:**
- prediction.factors: No contradictory factors (OVER + "Elite defense" = bug)
- last_10_lines: Arrays match length with last_10_points
- Best bets: Returns >0 picks for current date (was 0)
- Calendar: Returns 30+ dates

**If issues found:** Rollback instructions in handoff doc

Start by checking Cloud Build status and deployment drift.
