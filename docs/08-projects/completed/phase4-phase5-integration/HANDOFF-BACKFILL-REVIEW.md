# Handoff: Backfill Execution Plan Review

**Created:** 2025-11-28 9:20 PM PST
**Purpose:** Quick copy-paste for new Claude instance to review backfill plan

---

## Copy This to New Chat

```
I need you to perform a thorough review of a backfill execution plan for a multi-phase data pipeline.

Please read this review prompt first:
/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase4-phase5-integration/REVIEW-PROMPT-BACKFILL.md

Then review:
/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase4-phase5-integration/BACKFILL-EXECUTION-PLAN.md

Focus on:
1. Script correctness (bash syntax, logic bugs)
2. Strategy soundness (parallelization, sequencing)
3. Failure recovery (what happens when things fail)
4. Resource limits (will we hit quota/capacity)
5. Timeline realism (are estimates accurate)
6. Verification gaps (missing validation)
7. Missing steps (what's not documented)

Provide findings in the 7-part format specified in the review prompt:
1. Critical Issues (must fix)
2. Important Issues (should fix)
3. Script Bugs (actual errors)
4. Missing Steps (gaps)
5. Optimization Opportunities
6. Verification Enhancements
7. Questions & Clarifications

Be critical - we want to find problems NOW, not during execution!
```

---

## What You Should Get Back

The reviewer will provide structured feedback on:

### Critical Issues
- Problems that will prevent execution
- Must fix before running backfill
- Examples: Script bugs, incorrect logic, missing dependencies

### Important Issues
- Problems that reduce robustness
- Should fix but not blockers
- Examples: Inadequate error handling, missing verification

### Script Bugs
- Actual syntax or logic errors in bash scripts
- Line numbers and corrected code
- Examples: Wrong array slicing, incorrect comparisons

### Missing Steps
- Gaps in the execution procedure
- Things not documented
- Examples: Missing cleanup, no progress logging

### Optimizations
- Ways to make it faster or better
- Alternative approaches
- Examples: Better parallelization, reduced wait times

### Verification Enhancements
- Additional checks needed
- Data quality validation
- Examples: Schema validation, cross-phase consistency

### Questions
- Things that need your decision
- Ambiguities to clarify
- Options with recommendations

---

## After Review

Once you get the feedback:

1. **Share it in this chat**
2. **We'll update BACKFILL-EXECUTION-PLAN.md** with fixes
3. **Address critical issues** immediately
4. **Prioritize important issues** for implementation
5. **Document answers** to questions
6. **Update timeline** if needed

---

**Estimated Review Time:** 30-45 minutes for thorough analysis
