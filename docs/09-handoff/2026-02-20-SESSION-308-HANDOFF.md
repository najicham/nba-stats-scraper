# Session 308 Handoff — Full System Review + Bug Fixes + Dead Code Cleanup

**Date:** 2026-02-20
**Focus:** Comprehensive Best Bets V2 system review, V12 pattern bug fix, dead code removal

---

## What Was Done

### 1. Full System Review (5 Parallel Research Agents)

Comprehensive review of the entire Best Bets V2 system — all docs, code, schemas, signals, and multi-model architecture. Key finding: **the architecture is sound and should NOT be rebuilt from scratch.** The confusion about "signals having subsets" was a misread of the `01-REVISED-STRATEGY.md` doc, which actually recommends signal *graduation tracking* (a monitoring table), not signal *subsets*.

Full findings documented in `docs/08-projects/current/best-bets-v2/03-SESSION-308-REVIEW.md`.

### 2. V12 MAE Pattern Bug Fix (CRITICAL)

`cross_model_subsets.py` used exact match `'catboost_v12'` for V12 MAE family. But monthly models use system_id `'catboost_v12_noveg_train1102_0205'` (from `catboost_monthly.py`). The monthly V12 MAE model was **invisible** to cross-model scoring and Phase A multi-source candidate generation.

**Fix:** Changed v12_mae from exact match to prefix match. Reordered MODEL_FAMILIES so v12_q43/v12_q45 (more specific patterns) are checked before the broader v12_mae catch-all. Verified all 6 model name patterns classify correctly.

### 3. Confidence Angle Removal

Removed `_confidence_angle()`, `CONFIDENCE_HR_MAP`, and the 0.92 confidence warning from `pick_angle_builder.py`. Session 306 proved confidence doesn't separate good from bad for V9 — all tiers cluster 46-55% HR.

### 4. Dead Code Cleanup (-1,780 lines)

Deleted 14 dead signal files (removed Sessions 275-296 but never deleted) plus stale `signal_system_audit.py` (used old consensus formula with `diversity_mult=1.3`). No live code imported any of them.

### 5. CLAUDE.md Signal Table Update

Added `book_disagreement` signal (Session 303, was registered in code but missing from doc). Updated active signal count from 15/17 to 18. Documented dead code cleanup.

---

## Commit

```
2fee8ca3 refactor: Session 308 system review — V12 pattern fix, dead code cleanup, confidence removal
```

---

## Known Issues (Not Fixed This Session)

1. **model_performance_daily registry mismatch** — Model registry uses full deployment names but grading uses runtime `system_id` (`catboost_v9`). The daily state machine can't compute. Blocks Phase B trust-weighted scoring.

2. **Redundant pick storage** — `signal_best_bets_picks` and `current_subset_picks (subset_id='best_bets')` store the same picks with two grading paths.

3. **consensus_bonus is dead weight** — Computed by `cross_model_scorer.py`, stored in BQ, but NOT used for ranking (Session 297). Kept for audit trail but misleading.

---

## What's Missing (Prioritized)

| Priority | Feature | What It Is | Effort |
|---|---|---|---|
| **HIGH** | Signal graduation tracking table | BQ table tracking each signal's N, HR, lift at each edge bucket. Updated weekly. | 1 session |
| **HIGH** | `/weekly-report-card` skill | Performance cube: model x direction x edge x tier x signal. | 1-2 sessions |
| **HIGH** | Fix model_performance_daily | Add mapping from registry names to runtime system_ids. | 1 session |
| **MEDIUM** | Direction-split model monitoring | OVER vs UNDER HR per model in validate-daily Phase 0.58. | Small change |
| **MEDIUM** | Season lifecycle in aggregator | Cold-start edge floor (7.0), signal gate disable for new models. | 1 session |
| **MEDIUM** | Verify Phase A in production | Check tonight's games for non-V9 picks. | Manual check |
| **LOW** | Consolidate pick storage | Drop one of signal_best_bets_picks or current_subset_picks. | 1 session |

---

## Decisions Pending Data

| Decision | Data Needed | Current State | When |
|---|---|---|---|
| Graduate combo_he_ms to selection influence | N >= 50 at edge 5+ | N=33/50, HR=78.8% | ~2 weeks |
| Bench OVER priority within same edge | N >= 100 at edge 5+ | HR=85.7% but need more N | ~4 weeks |
| Raise UNDER edge floor to 6.0 | UNDER HR at 5-7 drops below 55% | Currently 59.3% — profitable | Monitor |
| Phase B trust-weighted scoring | 60+ days multi-model grading | Phase A just deployed | ~60 days |

---

## Next Session Priorities

1. **Fix model_performance_daily** — Add mapping from registry names to runtime system_ids
2. **Build signal graduation tracking** — Small BQ table, weekly computation
3. **Build `/weekly-report-card` skill** — Performance cube from `01-REVISED-STRATEGY.md`
4. **Verify Phase A** — Check production for non-V9 picks after tonight's games
