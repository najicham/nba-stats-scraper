# Session 224 Handoff — Master Experiment Plan Complete

**Date:** 2026-02-12
**Session:** 224
**Status:** Planning complete, ready for final review + execution plan

## What This Session Did

Pure planning and documentation session. No code changes. Produced a comprehensive experiment framework for recovering model performance.

### Process

1. Read 3 input docs (Sessions 222, 222B/223 results, model analysis)
2. Launched 7 parallel research agents to deep-dive:
   - Injury report data (star_teammate_out feasibility)
   - Box score / shooting stats (fg_pct, ts_pct availability)
   - Referee data (completely untapped pipeline)
   - Game-level odds data (game totals, spreads)
   - Schedule / rest data (opponent B2B, fatigue metrics)
   - Player profile data (CV, career games, age)
   - Multi-season data quality audit (BigQuery queries across 3 seasons)
3. Synthesized findings into master experiment plan
4. Brainstormed 10 unconventional post-processing approaches
5. Launched 3 expert review agents (quant analyst, ML engineer, professional bettor)
6. Incorporated all feedback into final plan

## Documents Created

All in `docs/08-projects/current/model-improvement-analysis/`:

| Document | Contents | Lines |
|----------|----------|-------|
| `01-SESSION-222-MODEL-ANALYSIS.md` | Updated with cross-references | ~1120 |
| `02-MASTER-EXPERIMENT-PLAN.md` | **56 experiments across 9 waves**, revised priorities, governance gates, expert feedback | ~900+ |
| `03-NEW-FEATURES-DEEP-DIVE.md` | **16 new features** with exact SQL, code, file paths, effort estimates | ~600+ |
| `04-MULTI-SEASON-DATA-AUDIT.md` | 3-season data quality analysis, trainable row counts, recommendations | ~330 |

## Key Findings

### Data Discoveries
- **38K trainable rows** across 3 seasons (only 8.4K currently used — 11% utilization)
- **Features 33-36 are 96-100% populated** everywhere — safe to activate immediately
- **`star_teammates_out` already computed** in Phase 3 — just needs extraction into feature store
- **`ts_pct` and `efg_pct` already computed** per game in Phase 3
- **Referee pipeline 90% built, 0% utilized** — `referee_adj = 0.0` hardcoded, 817-line implementation plan exists
- **Game total line** available at 99.52% coverage, completely unused as feature
- **Vegas coverage dropped** from 60-83% → 31-47% in 2025-26 season (significant training concern)
- **November data always bad** (21-28% clean) — start training from December

### Expert Review Consensus
1. **Direction filter + CLV tracking first** — not multi-season training
2. **Line shopping is free 2-3% edge** — already have multi-book data
3. **The 71.2% peak was probably noise** — realistic target is 55-58%
4. **Monotonic constraints** in CatBoost are a major unexplored parameter
5. **Multi-quantile ensemble (Q30/Q43/Q57)** for confidence-based filtering
6. **Per-game pick limits (2-3 max)** — correlation risk is unaddressed
7. **Replace 60% gate with Wilson confidence interval** — current gate is statistically unsound
8. **Alpha fine-tuning (0.41-0.45) is curve-fitting** — differences are within noise
9. **Per-player calibration is a lagging indicator** — feature-based fixes are better
10. **Referee features may be overhyped** — 5-10 pts game-level = ~0.3 pts per player

### Revised Priority Order (Post-Review)

| # | Action | Type | Expected Impact |
|---|--------|------|-----------------|
| 1 | Direction filter (suppress role UNDER) | Post-processing | IMMEDIATE |
| 2 | CLV tracking | Analytics | CRITICAL for validation |
| 3 | Line shopping (best line per direction) | Post-processing | Free 2-3% |
| 4 | Per-game pick limits (max 2-3) | Post-processing | Variance reduction |
| 5 | V10 activation + star_teammate_out | 1 code change + extraction | Root failure mode fix |
| 6 | Monotonic constraints + regularization | CatBoost params | Prevents overfitting |
| 7 | Multi-quantile ensemble (Q30/Q43/Q57) | Train 3 models | Confidence scoring |
| 8 | Multi-season training (best 2-3 configs) | Training | Data volume test |
| 9 | Calibration (Platt/isotonic on edge) | Post-processing | Better thresholds |
| 10 | New features (shooting, context, profile) | Feature eng. | Incremental signal |

## Next Session: What To Do

### Step 1: Final Review
The next chat should review the 4 documents for completeness, contradictions, and anything missed. Specifically:
- Does the priority order make sense?
- Are there any experiments that should be cut?
- Is the governance gate proposal (Wilson CI) sound?
- Are the dead ends correctly identified?

### Step 2: Build Concrete Test Plan
Convert the master experiment plan into a concrete, session-by-session execution plan:
- Which experiments to run in Session 225 (first execution session)
- Exact commands ready to copy-paste
- Success/failure criteria for each experiment
- Decision tree: "if X, then do Y; if not, do Z"
- Time estimates per experiment

### Step 3 (Optional): Quick Wins Before Full Experiments
Some items require zero training and can be validated immediately:
- Wave 0 SQL analyses (5 queries, 30 minutes)
- Direction filter simulation (1 query)
- CLV tracking query (1 query)
- Line shopping analysis (1 query)
- Per-game correlation analysis (1 query)

These 9 SQL queries could all run in the first 30 minutes of the next session, providing data to inform which experiments to prioritize.

## Commits This Session

```
ef089faf docs: Add Waves 7-9, expert reviews, revised priorities to experiment plan
b890df6a docs: Master experiment plan, features deep dive, multi-season data audit
```

## Infrastructure Status

- Working tree: clean
- Branch: main (4 commits ahead of origin, not pushed)
- No code changes — documentation only
- All existing systems unchanged and running

## Files to Read (For Next Session)

```bash
# Primary documents (read in order):
cat docs/08-projects/current/model-improvement-analysis/02-MASTER-EXPERIMENT-PLAN.md  # THE PLAN
cat docs/08-projects/current/model-improvement-analysis/03-NEW-FEATURES-DEEP-DIVE.md  # FEATURES
cat docs/08-projects/current/model-improvement-analysis/04-MULTI-SEASON-DATA-AUDIT.md # DATA
cat docs/08-projects/current/model-improvement-analysis/01-SESSION-222-MODEL-ANALYSIS.md # ANALYSIS

# Context (if needed):
cat docs/09-handoff/2026-02-12-SESSION-223-HANDOFF.md  # Prior session results
```
