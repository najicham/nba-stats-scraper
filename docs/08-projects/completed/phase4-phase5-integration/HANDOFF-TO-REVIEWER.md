# Handoff to Reviewer

**Created:** 2025-11-28 9:10 PM PST
**Purpose:** Quick copy-paste for new Claude instance

---

## Copy This to New Chat

```
I need you to perform a thorough review of a failure analysis document for an event-driven data pipeline system.

Please read this review prompt first:
/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase4-phase5-integration/REVIEW-PROMPT-FAILURE-ANALYSIS.md

Then follow the instructions in that document to:
1. Read the specified documentation
2. Review the failure analysis
3. Identify gaps, edge cases, and missing scenarios
4. Provide findings in the structured format requested

The key documents are all in:
/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase4-phase5-integration/

Start by reading REVIEW-PROMPT-FAILURE-ANALYSIS.md which has complete instructions.
```

---

## What to Expect Back

The reviewer should provide:

1. **Critical Gaps** - Must fix before launch
2. **Important Gaps** - Should fix in v1.0 or early v1.1
3. **Edge Cases** - Document and monitor
4. **Cascading Failures** - Multi-failure scenarios
5. **Silent Failures** - Hard-to-detect issues
6. **Enhanced Recovery Procedures** - Better/additional procedures
7. **Prevention Strategies** - Design improvements

---

## After Review

Once you get the review back:

1. Share it with me in this chat
2. We'll integrate valuable findings into:
   - FAILURE-ANALYSIS-TROUBLESHOOTING.md
   - V1.0-IMPLEMENTATION-PLAN-FINAL.md
   - Create ENHANCEMENTS.md for v1.1 items
3. Update implementation priorities if needed

---

**Estimated Review Time:** 30-45 minutes for thorough analysis
