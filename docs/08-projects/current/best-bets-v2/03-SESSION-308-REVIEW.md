# Best Bets V2: Session 308 Full System Review

**Session:** 308
**Date:** 2026-02-20
**Status:** REVIEW COMPLETE — architecture is sound, incremental fixes applied

---

## Review Scope

Comprehensive review of the entire Best Bets V2 system triggered by confusion about whether signals should have their own subsets. Five parallel research agents studied:
1. Best bets pipeline code (aggregator, supplemental_data, exporter)
2. Subset/grading system (37 subsets, materializer, grading processor)
3. Signal system (18 active signals, registry, health, combos)
4. Database schemas (10 tables, relationships, data flow)
5. Multi-model architecture (cross-model scorer, model families, discovery)

---

## Key Finding: Signals vs Subsets

### The confusion
Session 306's `01-REVISED-STRATEGY.md` recommended "signal graduation tracking" — a monitoring table that tracks each signal's N, HR, and lift at each edge bucket. This was misread as "signals should have their own subsets."

### The answer: Signals should NOT be subsets

| Concept | Subsets | Signals |
|---------|--------|---------|
| **What they are** | Slices of a model's predictions | Cross-cutting pattern annotations |
| **Example** | "V9's top 5 OVER picks" | "This player has a minutes surge" |
| **Storage** | `current_subset_picks` (per-model) | `pick_signal_tags` (per-prediction) |
| **Count** | 37 subsets (30 model + 2 curated + 5 cross-model) | 18 active signals |
| **Grading** | `SubsetGradingProcessor` | JOINs: `pick_signal_tags` + `prediction_accuracy` |

Making signals into subsets would create 18 signals x 6 models = 108+ new subsets, mixing conceptual levels for little gain.

### What the doc actually recommends (and what's missing)

1. **Signal graduation tracking table** — BQ table updated weekly tracking each signal's N, HR, lift at each edge bucket. Alerts when a signal crosses graduation thresholds (N >= 50, HR >= 65%, +10pp lift).
2. **`/weekly-report-card` skill** — Performance cube across model x direction x edge x tier x signal.
3. **Direction-split model monitoring** — OVER vs UNDER HR per model in validate-daily.

These are monitoring improvements, NOT architectural changes.

---

## Bugs Found and Fixed

### 1. V12 MAE pattern mismatch (CRITICAL)

**Bug:** `cross_model_subsets.py` used exact match `'catboost_v12'` for V12 MAE family. But monthly models use system_id `'catboost_v12_noveg_train1102_0205'` (from `catboost_monthly.py:507`). The monthly V12 MAE model was invisible to cross-model scoring and multi-source candidate generation.

**Root cause:** Two V12 code paths exist:
- Legacy `catboost_v12.py` → `system_id = 'catboost_v12'` (exact match worked)
- Monthly `catboost_monthly.py` → `system_id = 'catboost_v12_noveg_train1102_0205'` (exact match failed)

**Fix:** Changed v12_mae from exact match to prefix match (`'catboost_v12'`), reordered MODEL_FAMILIES so v12_q43/v12_q45 (more specific) are checked before v12_mae (broader catch-all).

### 2. Confidence angle was useless noise

**Bug:** `pick_angle_builder.py` generated confidence tier angles for every pick despite Session 306 proving confidence doesn't separate good from bad for V9. All tiers cluster 46-55% HR.

**Fix:** Removed `_confidence_angle()`, `CONFIDENCE_HR_MAP`, and the 0.92 confidence warning.

### 3. Dead code accumulation

**Bug:** 14 dead signal files + `signal_system_audit.py` (with stale consensus formula) cluttering the codebase.

**Fix:** Deleted all 15 files. No live code imported any of them.

### 4. CLAUDE.md signal count wrong

**Bug:** Listed 15/17 active signals, missing `book_disagreement` (Session 303).

**Fix:** Updated to 18 active signals, added `book_disagreement` row.

---

## Architecture Assessment

### What's working well (don't change)
- **Edge-first selection** — Session 297 proved edge-first > signal-scored (71.1% vs 59.8% HR)
- **11 negative filters** — Well-calibrated with data-backed HR thresholds
- **Multi-model candidate generation (Phase A)** — Correctly deduplicates by highest edge per player
- **Signal registry** — Clean 18-signal architecture with `evaluate()` contract
- **Database schema** — Modular, well-partitioned, proper separation of concerns
- **3-phase roadmap** — A (deployed) → B (deferred 60d) → C (deferred 6mo)

### What's computed but unused (consider simplifying)
- **`consensus_bonus`** in `cross_model_scorer.py` — Computed and stored in BQ but NOT used for ranking (Session 297). Kept for audit trail only. Consider removing computation if it never proves useful.

### What's redundant (consider consolidating)
- **`signal_best_bets_picks`** vs **`current_subset_picks (subset_id='best_bets')`** — Same picks stored in two tables with two grading paths. The handoff doc acknowledges this. Consider consolidating to one source of truth.

---

## What's Missing (From Revised Strategy Doc)

| Missing Feature | Doc Section | Priority | Effort |
|---|---|---|---|
| **Signal graduation tracking** | Signal graduation framework | HIGH | 1 session |
| **`/weekly-report-card` skill** | Systematic Performance Monitoring | HIGH | 1-2 sessions |
| **Direction-split model monitoring** | Level 1 daily automated | MEDIUM | Small change to validate-daily |
| **Season lifecycle system** | Season Lifecycle | MEDIUM | 1 session |
| **Source attribution monitoring** | Phase A validation | MEDIUM | After 2 weeks of Phase A data |
| **Signal x model validation** | +4 weeks roadmap | LOW | After more non-V9 grading data |

---

## Naming Recommendations

| Current Name | Assessment | Suggested |
|---|---|---|
| `cross_model_subsets.py` | Misleading — does model discovery/classification | Consider `model_families.py` |
| `CrossModelScorer` | Misleading — doesn't score anymore (bonus unused) | Could be `CrossModelAnalyzer` |
| `consensus_bonus` | Dead weight — computed but not used | Either use it or rename to `consensus_audit_data` |
| `signal_best_bets_exporter.py` | Legacy name from signal-scored era | Acceptable for now |

---

## Decision Log for Next Sessions

### Decisions confirmed by data
1. **Edge-first > signal-scored** — 71.1% vs 59.8% HR. Do not revert.
2. **V9+V12 agreement is anti-correlated** — diversity_mult correctly removed.
3. **Confidence score is useless for V9** — All tiers 46-55% HR. Correctly removed.
4. **Signals add value at edge 5-7** — +14.5pp HR with signal vs without. Real value.

### Decisions pending more data
1. **Should combo_he_ms graduate to selection influence?** — N=33/50 at edge 5+, HR=78.8%. Need 17 more graded picks.
2. **Should bench OVER get priority within same edge?** — 85.7% HR at edge 5+, but need N >= 100.
3. **Should UNDER edge floor be raised to 6.0?** — 59.3% HR at edge 5-7 is profitable. Don't change unless it drops below 55%.
4. **Is Phase A producing non-V9 picks?** — Deploy just happened, need 2 weeks of data.

### Next session priorities
1. Fix `model_performance_daily` registry name mismatch (blocks Phase B)
2. Build signal graduation tracking table
3. Build `/weekly-report-card` skill
4. Verify Phase A is producing multi-model picks in production
