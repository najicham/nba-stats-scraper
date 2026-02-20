# Session 307 Handoff — Phase A Multi-Source + Monitoring Backfill + Bug Fixes

**Date:** 2026-02-20
**Focus:** Best Bets V2 Phase A implementation, monitoring system diagnosis and backfill, production bug fixes

---

## What Was Done

### 1. Phase A: Multi-Source Candidate Generation (DEPLOYED)

Best bets exporter now queries ALL CatBoost model families (not just champion V9) and picks the highest-edge prediction per player.

**Files changed:**
- `ml/signals/supplemental_data.py` — Added `multi_model=True` parameter with multi-source CTE
- `ml/signals/aggregator.py` — Bumped `ALGORITHM_VERSION = 'v307_multi_source'`
- `data_processors/publishing/signal_best_bets_exporter.py` — Passes `multi_model=True`, writes 5 new attribution columns
- `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` — 5 new columns added

**Schema migration:** ALTER TABLE ran successfully adding `source_model_id`, `source_model_family`, `n_models_eligible`, `champion_edge`, `direction_conflict`.

**Backward compat:** `signal_annotator.py` still calls `multi_model=False` (default) — no change to annotation path.

### 2. `/best-bets-config` Diagnostic Skill (NEW)

Created `.claude/skills/best-bets-config/SKILL.md` — 6-section dashboard:
1. Aggregator config (MIN_EDGE, MIN_SIGNAL_COUNT, algorithm version)
2. Active model families (BQ discovery vs MODEL_FAMILIES patterns)
3. Negative filter inventory (all 11 filters with thresholds and HRs)
4. Signal registry & health (cross-ref registry.py with signal_health_daily)
5. Combo registry (signal_combo_registry status)
6. Config sync checks + new model/signal checklists

### 3. Monitoring System Diagnosis

**Root cause found:** `post-grading-export` CF was failing with 403 auth errors since redeployment. Pub/Sub subscription used `processor-sa@` but function only allowed `compute@developer` as invoker.

**Fixed:** Updated subscription `eventarc-us-west2-post-grading-export-846381-sub-882` to use correct service account.

### 4. Monitoring Backfill

| Table | Gap | Backfilled | Result |
|-------|-----|-----------|--------|
| `signal_health_daily` | Feb 12-19 (7 days) | Yes | 20 rows (2 game dates — rest was ASB break) |
| `model_performance_daily` | Feb 12-19 | Partial | 0 rows — registry model names don't match grading system_ids |
| `signal_best_bets_picks` | Feb 2-19 (17 days) | Yes | 6 picks across 4 game dates (Feb 5, 7, 8, 11) |

### 5. Production Bug Fixes (3 commits)

**Commit 1:** `feat: Phase A multi-source candidate generation + Session 306 fixes`
- Phase A implementation + Session 306 threshold changes + skill

**Commit 2:** `fix: numeric precision + edge column reference bugs in exporter`
- Float precision on `edge` (5.600000000000001 → NUMERIC overflow)
- `ABS(edge)` → `ABS(predicted_points - line_value)` in direction_health and blacklist queries

**Commit 3:** `fix: champion_edge precision + is_correct→prediction_correct column names`
- Float precision on `champion_edge`
- `is_correct` → `prediction_correct` (renamed in schema v5)

---

## Bugs Found and Fixed

| Bug | Symptom | Root Cause | Fix |
|-----|---------|-----------|-----|
| post-grading-export auth | signal_health_daily stale 7+ days | Wrong SA on Pub/Sub subscription | Updated subscription SA |
| edge NUMERIC overflow | BQ write 400 error | Float precision (5.600000000000001) | `round(float(x), 1)` |
| confidence_score overflow | BQ write 400 error (shadow models) | Shadow models use 0-100 scale, schema is NUMERIC(4,3) | `min(x, 9.999)` clamp |
| champion_edge overflow | BQ write 400 error | Same float precision | `round(float(x), 1)` |
| `ABS(edge)` in queries | 400 column not found | `edge` doesn't exist in prediction_accuracy | Use `ABS(predicted_points - line_value)` |
| `is_correct` in queries | 400 column not found | Column renamed to `prediction_correct` in schema v5 | Updated column name |

---

## Known Issues (Not Fixed This Session)

1. **model_performance_daily registry mismatch** — Model registry uses full deployment names (`catboost_v9_33f_train20260106-20260205_20260218_223530`) but grading uses runtime `system_id` (`catboost_v9`). The compute function can't find matches. Needs a mapping layer.

2. **Redundant pick storage** — `signal_best_bets_picks` and `current_subset_picks (subset_id='best_bets')` store the same picks. Should consolidate to one source of truth.

3. **Feb 19 best bets = 0 picks** — model_health signal returns `unknown` (no games graded yet post-ASB), so MIN_SIGNAL_COUNT=2 can't be met. This will self-resolve once grading catches up.

4. **Player blacklist/direction_health still non-fatal** — Fixed the column names but these queries still fail silently if other issues arise. Consider promoting to warnings.

---

## Architecture Notes

### How Best Bets Selection Works (Session 307)

1. Query ALL CatBoost models → dedup by highest edge per player
2. Evaluate 17 signals → attach as annotations (not selection)
3. Apply 11 negative filters (edge floor, UNDER blocks, blacklist, etc.)
4. Require MIN_SIGNAL_COUNT=2 (model_health + 1 real signal)
5. Rank by edge descending → natural sizing (no hard cap)
6. Export to BQ + GCS with full provenance

### Monitoring Tables

- `signal_health_daily` — per-signal regime, populated after grading
- `model_performance_daily` — per-model state machine, populated after grading
- `signal_best_bets_picks` — pick provenance (why each pick was made)
- `pick_signal_tags` — signal annotations on ALL predictions

### New Model/Signal Checklists

Available in `/best-bets-config` skill Section 6. Key for model: pattern in MODEL_FAMILIES + auto-discovery. Key for signal: class + registry + CLAUDE.md + health table.

---

## Next Session Priorities

1. **Fix model_performance_daily** — Add mapping from registry names to runtime system_ids so daily state machine works
2. **Verify Phase A in production** — Tonight's games will be first real multi-model best bets run
3. **Consider decision snapshot** — Add `signal_regimes_snapshot` JSON to signal_best_bets_picks for full replay capability
4. **Phase B planning** — Performance-aware model weighting (use model_performance_daily to adjust which model's edge wins dedup)
5. **Weekly report card skill** — Direction-split monitoring, player tier tracking (from Session 306 review chat)

---

## Commits

```
7b2142be fix: champion_edge precision + is_correct→prediction_correct column names
622ef842 fix: numeric precision + edge column reference bugs in exporter
cb7baf1e feat: Phase A multi-source candidate generation + Session 306 fixes
```
