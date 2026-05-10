# Execution Log

Running log of code changes per phase. Update as work lands.

---

## Phase A — Bug fixes + scaffolding (started 2026-05-09)

### A.1 Project scaffolding (2026-05-09)
- Created `docs/08-projects/current/pipeline-state-redesign-2026-05/` with `00-PROJECT-PLAN.md`, `01-ARCHITECTURE.md`, this `02-EXECUTION-LOG.md`, `03-BACKFILL-MANIFEST.md`, `04-DEMO-SCRIPT.md`.

### A.2 cap_to_pre_late_season — Oct rollover fix
- File: `orchestration/cloud_functions/weekly_retrain/main.py`
- Function: `cap_to_pre_late_season(train_end)`
- Before: cap fired for all `train_end > date(train_end.year, 2, 28)`. For Oct 2026 train_end → cap to Feb 28, 2026 (5 mo stale).
- After: cap fires only when `train_end.month in (3, 4)` — the actual late-season window. Oct/Nov/Dec/Jan/Feb pass through unchanged.

### A.3 post_grading_export — split history exporter from picks gate
- File: `orchestration/cloud_functions/post_grading_export/main.py`
- Issue: `skip_picks_exports = (graded_count == 0)` was returning at line 572 BEFORE step 7 (`BestBetsAllExporter`) and step 8 (`BestBetsRecordExporter`). Both write *history* files, not today's picks; they should run regardless of today's grading.
- After: only steps 6 (re-export tonight with actuals) and 9 (admin/diagnostic) gated on `skip_picks_exports`. Steps 7/8 always run.

### A.4 Rescue gate edge floor align — 5.0 → 6.0
- File: `ml/signals/aggregator.py:536`
- Issue: OVER block floor raised to 6.0 in Session 522, but rescue eligibility still gated at `pred_edge < 5.0`. Picks at edge 5.0–6.0 were blocked but never offered rescue.
- After: rescue gate raised to `pred_edge < 6.0` to align with block floor.

### A.5 best-bets-config skill drift cleanup
- File: `.claude/skills/best-bets-config/SKILL.md`
- Removed/marked stale (3 filters per audit + Session 422b note): `away_noveg` (removed), `starter_v12_under` (removed), `line_dropped_over` (removed).
- Marked `opponent_under_block` as observation (Session 488).
- Adjusted (27 filters) header to actual count.

### A.6 IAM lockdown — DEFERRED to follow-up sub-task
- Locking down `prediction-coordinator` + `prediction-worker` requires auditing every caller (orchestrators, schedulers, dashboards). Done badly, this breaks production.
- Captured as a blocking sub-task; will tackle after Phase B exposes halt_state-aware traffic.

---

## Phase B — halt_state foundation (pending)

(Will fill in as work lands.)

---

## Phase C — expected_outputs date-grid (pending)

---

## Phase D — Unified observability layer (pending)

---

## Phase E — Self-healing gap detector (pending)

---

## Phase F — Backfill Oct 2025 - Feb 2026 (pending)

See `03-BACKFILL-MANIFEST.md` for per-date status.

---

## Phase G — Alerts + retire monitors (pending)

---

## Phase H — Registry + drift prevention (pending)

---

## Phase I — Frontend monitoring (pending)

---

## Phase J — Frontend bug fixes (pending)

---

## Phase K — Documentation refresh (pending)

---

## Phase L — Pre-presentation verification (pending)
