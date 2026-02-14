# Session 227 Start Prompt

Paste this into a new Claude Code session:

---

## Context

We're rebuilding our NBA player props prediction model (CatBoost, predicts player points scored for over/under betting). The current champion decayed from 71.2% to ~40% hit rate. Last session we ran 9 experiments and got 3 independent expert reviews from Opus web chats.

## Your Task

1. **Read these documents in order:**

```bash
# The 3 independent expert reviews (each ~10-15 pages)
cat docs/08-projects/current/model-improvement-analysis/13-OPUS-CHAT-1-ANALYSIS.md
cat docs/08-projects/current/model-improvement-analysis/14-OPUS-CHAT-2-ARCHITECTURE.md
cat docs/08-projects/current/model-improvement-analysis/15-OPUS-CHAT-3-STRATEGY.md

# The current master plan (synthesizes all 3)
cat docs/08-projects/current/model-improvement-analysis/16-MASTER-IMPLEMENTATION-PLAN.md

# Session handoff (experiment results, what was done, what's next)
cat docs/09-handoff/2026-02-12-SESSION-226B-HANDOFF.md
```

2. **Evaluate the master plan critically:**
   - Do you agree with the consensus diagnosis (Vegas dependency as root cause)?
   - Is the phasing right (diagnostics → Vegas-free model → edge finder)?
   - Are there contradictions or blind spots across the 3 reviews?
   - Would you change the priority order of new features?
   - Is anything missing that the 3 chats didn't consider?

3. **Decide:** Either adopt the current master plan as-is, modify it, or write a new one. Save your final plan to `docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md`.

4. **Create a concrete testing plan** that specifies:
   - Exact experiments to run (with CLI commands where possible)
   - What to measure at each step
   - Decision gates (what results mean proceed vs pivot)
   - Order of operations (what can run in parallel)
   - Save to `docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md`

5. **Then start executing Phase 0 (diagnostics)** from whatever plan you finalized.

## Key Facts

- Model: CatBoost V9, 33 features, quantile regression alpha=0.43
- The same model architecture scored **79.5% on Feb 2025** but **~50% on Feb 2026**
- Vegas features account for 20-45% of feature importance
- All 3 reviews unanimously say: build a Vegas-free points predictor first
- `quick_retrain.py` has a date bug fix from last session (not yet committed)
- Training takes ~2-5 minutes per experiment

## Important

- Use `doc` procedure for any new documents
- Read CLAUDE.md for project conventions
- Don't deploy anything — this is all experimentation
- Commit the date bug fix in quick_retrain.py before running experiments
