# Next Session Prompt - Phase 6 Follow-Up

Copy this to a new Claude Code session:

---

```
Session 209 Phase 6 API deployed and validated. Need to complete follow-up tasks.

CURRENT STATE:
- All Phase 6 exports working (8/8 validations passed)
- Critical bug fixed: Removed non-existent feature columns (opponent_def_rating, opponent_pace)
- Deployed commit: cd6f912c
- Tonight export: 806KB, Best bets: 22 picks, Calendar: 32 dates

COMPLETED:
✅ Deploy nba-scrapers with bug fix
✅ Run Phase 6 exports successfully
✅ Validate all 8 checks (all passed)
✅ Create validation report

REMAINING TASKS:
1. Notify frontend team about Phase 6 API updates
2. Fix auto-deploy trigger (add publishing paths)
3. Monitor system for 24 hours

Read this first:
/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-02-12-VALIDATION-REPORT.md

Then:
1. Review validation report (all details)
2. Send frontend notification (message draft in report)
3. Fix Cloud Build trigger:
   - Go to Cloud Console → Cloud Build → Triggers
   - Find deploy-nba-scrapers
   - Add to includedFiles:
     * data_processors/publishing/**
     * backfill_jobs/publishing/**
   - Test with trivial change + push
4. Monitor Slack #deployment-alerts for 24h
5. Check exports still working tomorrow

Frontend notification message is in the validation report - ready to copy/paste.

Start by reading the validation report, then notify the frontend team.
```
