# Backfill Documentation Review - Prompt for Review Session

**Purpose:** Critical review of backfill strategy and documentation
**Context:** About to backfill 4 years of NBA data (638 game dates across Phase 3 & 4)
**Your Role:** Expert reviewer - find issues, edge cases, and potential problems

---

## 📋 Review Prompt (Copy This to New Chat)

```
I need you to perform a comprehensive critical review of our historical data
backfill documentation and strategy. We're about to backfill 4 years of NBA data
(2020-2024, 638 game dates) across Phase 3 (Analytics) and Phase 4 (Precompute).

CONTEXT:
- Data pipeline: Phase 1 (Scrapers) → Phase 2 (Raw) → Phase 3 (Analytics)
  → Phase 4 (Precompute) → Phase 5 (Predictions)
- Phase 2 is 100% complete (638/638 dates) - no backfill needed
- Phase 3 has 311/638 dates (need to backfill 327 dates)
- Phase 4 has 0/638 dates (need to backfill all 638 dates)
- Phase 3 & 4 have lookback windows (cross-date dependencies)
- Phase 4 has defensive checks that block if Phase 3 incomplete

STRATEGY CHOSEN:
- Stage-based approach: Complete ALL Phase 3, then ALL Phase 4
- Sequential processing within each stage (chronological order)
- Quality gates between stages (must be 100% before proceeding)
- Use skip_downstream_trigger=true to prevent premature Phase 4 execution
- Comprehensive monitoring with 20 SQL queries
- Resumable design (can pause/resume anytime)

DOCUMENTATION TO REVIEW:
Please read these 5 documents in order:

1. docs/08-projects/current/backfill/README.md
   - Navigation and quick start guide

2. docs/08-projects/current/backfill/BACKFILL-MASTER-EXECUTION-GUIDE.md
   - Primary execution guide (51 pages)
   - Stage-by-stage instructions
   - Exact commands and scripts

3. docs/08-projects/current/backfill/BACKFILL-GAP-ANALYSIS.md
   - 20 SQL queries for monitoring and gap detection
   - Progress tracking and failure detection

4. docs/08-projects/current/backfill/BACKFILL-FAILURE-RECOVERY.md
   - Recovery procedures
   - 7 common failure scenarios
   - Emergency procedures

5. docs/08-projects/current/backfill/BACKFILL-VALIDATION-CHECKLIST.md
   - Quality gates (Gates 0-3)
   - Data quality spot checks
   - Sign-off procedures

SUPPORTING CONTEXT DOCUMENTS:
- docs/09-handoff/2025-11-29-BACKFILL-DOCS-COMPLETE.md (summary)
- docs/09-handoff/2025-11-29-schema-verification-complete.md (prerequisites)
- docs/09-handoff/2025-11-29-v1.0-deployment-complete.md (infrastructure)

YOUR CRITICAL REVIEW TASKS:

1. STRATEGY VALIDATION
   - Is the stage-based approach (all Phase 3, then all Phase 4) sound?
   - Are there better alternatives we haven't considered?
   - Will sequential processing really prevent dependency issues?
   - Are the quality gates sufficient?
   - What happens if we violate the "100% before next stage" rule?

2. FAILURE SCENARIO ANALYSIS
   - Review the 7 failure scenarios - are these realistic?
   - What failure scenarios are MISSING?
   - What could cause catastrophic data corruption?
   - What happens if Phase 3 completes but Phase 4 orchestrator is broken?
   - What if defensive checks have bugs and let bad data through?
   - What if BigQuery quotas are exceeded mid-backfill?

3. EDGE CASES & CORNER CASES
   - What happens during season boundaries? (e.g., June 2022 → Oct 2022)
   - What about playoff vs regular season data differences?
   - What if historical data formats changed over 4 years?
   - What about player trades mid-season affecting lookback windows?
   - What if some dates have partial games (postponed, cancelled)?
   - What about All-Star break (no games for week)?

4. DEPENDENCY & ORDERING ISSUES
   - Are there hidden dependencies we haven't considered?
   - Could processing dates sequentially still cause issues?
   - What if Phase 3 processors have inter-dependencies we don't know about?
   - What about Phase 4 internal processor ordering?
   - Could parallel execution of the 5 Phase 3 processors for ONE date cause issues?

5. DATA QUALITY & VALIDATION
   - Are the quality gates thorough enough?
   - What data quality issues could slip through?
   - Are the spot checks in the validation checklist sufficient?
   - What if data exists but is garbage (wrong values, nulls, etc)?
   - How do we detect silent failures (processor succeeds but writes bad data)?

6. OPERATIONAL CONCERNS
   - Is 16-26 hours realistic? Could it take longer?
   - What if we need to pause for days/weeks mid-backfill?
   - What about timezone issues with dates?
   - What if schema changes during backfill execution?
   - What about cost - will this cost thousands in BigQuery fees?

7. RECOVERY & ROLLBACK
   - Is the resumable design truly safe?
   - What if we need to rollback 200 dates of bad data?
   - What if we discover a bug after Stage 1 complete but before Stage 2?
   - How do we verify data is correct BEFORE enabling production?

8. MONITORING & VISIBILITY
   - Are 20 queries enough for monitoring?
   - What critical metrics are we NOT tracking?
   - How do we know if backfill is "stalled" vs "slow"?
   - What alerts should fire if something goes wrong?

9. SCRIPTS & AUTOMATION
   - Review the script templates in BACKFILL-MASTER-EXECUTION-GUIDE.md
   - Are there bugs in the bash scripts?
   - Are the SQL queries correct?
   - What if the scripts have logic errors?

10. DOCUMENTATION GAPS
    - What's missing from the documentation?
    - What assumptions are made but not stated?
    - What would confuse someone executing this 6 months from now?
    - Are there contradictions between documents?

CRITICAL THINKING QUESTIONS:
- "What's the worst thing that could happen?"
- "What would cause us to completely restart the backfill?"
- "What would cause data corruption we can't detect?"
- "What assumptions could be wrong?"
- "What did we forget to document?"
- "If this was YOUR production system, what would worry you?"

OUTPUT REQUESTED:
Please provide:

1. CRITICAL ISSUES (if any)
   - Issues that could cause major problems
   - Must-fix before execution
   - Ranked by severity

2. EDGE CASES NOT COVERED
   - Scenarios missing from documentation
   - Suggested additions to failure recovery playbook

3. VALIDATION CONCERNS
   - Gaps in quality gates
   - Additional checks needed
   - Data quality risks

4. STRATEGY RECOMMENDATIONS
   - Is the chosen strategy sound?
   - Alternative approaches to consider
   - Improvements or modifications

5. OPERATIONAL RISKS
   - Timeline concerns
   - Resource concerns
   - Cost concerns

6. DOCUMENTATION IMPROVEMENTS
   - Missing information
   - Unclear instructions
   - Contradictions to resolve

7. QUESTIONS FOR CLARIFICATION
   - Things you need to know to complete review
   - Assumptions that need validation

Please be thorough and critical. We want to find problems NOW, not during
execution when we're 15 hours into a 20-hour backfill.

Think like a senior engineer who has to sign off on this going to production.
What would make you uncomfortable? What would you want to know more about?

Take your time to read all documents carefully and think through the approach.
```

---

## 📊 What This Review Should Catch

The review session should identify:

- **Missing failure scenarios** we haven't documented
- **Hidden dependencies** in the data or processors
- **Edge cases** with dates, seasons, or data formats
- **Data quality risks** that quality gates might miss
- **Script bugs** in the documented bash/SQL
- **Timeline unrealistic** - could take 2x longer
- **Cost concerns** - BigQuery query costs
- **Operational gaps** - what if we pause for a week?
- **Documentation contradictions** or unclear sections

---

## 🎯 Expected Output from Review

The reviewing chat should provide:

1. **Critical Issues List** (ranked by severity)
2. **Missing Edge Cases** (scenarios to add to docs)
3. **Quality Gate Gaps** (additional validations needed)
4. **Strategy Validation** (is approach sound?)
5. **Operational Risks** (timeline, cost, resource concerns)
6. **Documentation Improvements** (clarifications needed)
7. **Questions** (things needing clarification)

---

## 📝 How to Use Review Results

When you return with review results:

1. **Critical Issues:** We'll fix immediately
2. **Edge Cases:** Add to BACKFILL-FAILURE-RECOVERY.md
3. **Quality Gaps:** Add to BACKFILL-VALIDATION-CHECKLIST.md
4. **Strategy Concerns:** Revise BACKFILL-MASTER-EXECUTION-GUIDE.md
5. **Documentation:** Update relevant docs

---

## ✅ Checklist for Review Session

Before starting review chat:

- [ ] Copy the review prompt above to new chat
- [ ] Ensure reviewer has access to all 5 backfill docs
- [ ] Ensure reviewer has context docs (schema verification, v1.0 deployment)
- [ ] Ask reviewer to be thorough and critical
- [ ] Request specific, actionable feedback

---

**Ready to copy the review prompt to a new chat session!**

**After review, bring results back here and we'll incorporate all feedback.**
