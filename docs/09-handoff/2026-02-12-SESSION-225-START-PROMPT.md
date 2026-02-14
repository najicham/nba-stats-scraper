# Session 225 Start Prompt

Copy everything below this line into a new chat:

---

## Context

Session 224 completed a comprehensive planning effort for model recovery. The champion model (`catboost_v9`) has decayed from 71.2% to 38.0% edge 3+ hit rate — well below the 52.4% breakeven. We produced 4 documents containing a master experiment plan (56 experiments across 9 waves), 16 new feature designs, a 3-season data quality audit, and synthesized feedback from 3 expert reviews (quant analyst, ML engineer, professional bettor).

## Your Task

1. **Read all 4 documents thoroughly:**
   ```
   docs/08-projects/current/model-improvement-analysis/02-MASTER-EXPERIMENT-PLAN.md
   docs/08-projects/current/model-improvement-analysis/03-NEW-FEATURES-DEEP-DIVE.md
   docs/08-projects/current/model-improvement-analysis/04-MULTI-SEASON-DATA-AUDIT.md
   docs/08-projects/current/model-improvement-analysis/01-SESSION-222-MODEL-ANALYSIS.md
   ```

2. **Final review** — Look for gaps, contradictions, or anything missed. Specifically:
   - Does the revised priority order make sense?
   - Are there experiments that should be cut or combined?
   - Is the governance gate proposal (Wilson CI replacing 60% threshold) sound?
   - Any contradictions between the documents?
   - Anything the expert reviewers got wrong?

3. **Build a concrete test plan** — Convert the master experiment plan into an actionable, session-by-session execution plan:
   - Which experiments to run first (start with the Wave 0 SQL queries and quick wins)
   - Exact commands ready to copy-paste
   - Success/failure criteria for each step
   - Decision tree: "if result X, then do Y; if not, do Z"
   - Group experiments that can run in parallel

4. **Also read the handoff doc** for additional context:
   ```
   docs/09-handoff/2026-02-12-SESSION-224-HANDOFF.md
   ```

This is a planning + review session. Do NOT run any experiments yet — just produce the final reviewed test plan. We will execute in subsequent sessions.
