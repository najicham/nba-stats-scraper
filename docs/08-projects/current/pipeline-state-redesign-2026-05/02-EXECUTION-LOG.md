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

## Phase B — halt_state foundation (in_progress, 2026-05-09)

### B.1 Schema + table created
- New `schemas/bigquery/nba_orchestration/halt_state.sql` — partitioned by effective_date, clustered by sport + halt_active.
- `bq query` ran the CREATE TABLE; confirmed `nba-props-platform.nba_orchestration.halt_state` exists with all 9 columns.
- Seeded today's rows: NBA halted (off_season, since 2026-04-19); MLB healthy.

### B.2 halt_state_writer Cloud Function (code landed; not yet deployed)
- New `orchestration/cloud_functions/halt_state_writer/{main.py, requirements.txt, __init__.py, deploy.sh}`.
- Inlined the Session 515 edge-collapse logic from `regime_context.py` so the CF doesn't depend on the full ml/signals stack.
- Decision tree per sport: schedule-presence check → off_season; else NBA edge collapse; else NBA fleet_blocked; else healthy.
- Idempotent MERGE; daily 5 AM ET schedule; Slack alert on state change.
- Service account `halt-state-writer@nba-props-platform.iam.gserviceaccount.com` referenced — needs creation before first deploy.

### B.3 BaseExporter.halt_envelope()
- Added to `data_processors/publishing/base_exporter.py` between `get_generated_at()` and `validate_content()`.
- Reads halt_state for (sport, target_date) and returns canonical 4-key envelope.
- Fail-open: if BQ unreachable or row missing, returns `halt_active=False, halt_reason='unknown_state'` so exporters never crash.

### B.4 Wire halt envelope into key exporters
- `best_bets_all_exporter.py` — added halt_active/halt_reason/halt_since fields to JSON output (line ~217 area). Now every `best-bets/all.json` carries the envelope.
- `signal_best_bets_exporter.py` — added envelope to BOTH the no-predictions early-return (line ~157) AND the normal return (line ~447). Existing edge-collapse halt branch (line ~107) was already halt-aware; augmented with halt_since from halt_state.

### B.5 Frontend HaltBanner — pending (separate props-web commit)
- Will read halt_active from any loaded JSON and render explicit halt treatment.
- Replaces today's misleading "Today's picks aren't out yet — check back around 2 PM ET" copy.

---

## Phase C — expected_outputs date-grid (in_progress, 2026-05-09)

### C.1 Schema + table + views created
- New `schemas/bigquery/nba_orchestration/expected_outputs.sql`. Partitioned by game_date, clustered by sport + phase + status.
- Two views also created:
  - `expected_outputs_gaps` — overdue EXPECTED rows (canonical "what's missing now?")
  - `expected_outputs_coverage` — daily completion percentage per phase per sport (powers nba-pipeline-health dashboard)
- BQ create succeeded; `content_hash` chosen instead of `hash` (reserved word in BQ SQL).

### C.2 expected_outputs_planner Cloud Function (code landed, smoke-tested)
- New `orchestration/cloud_functions/expected_outputs_planner/{main.py, requirements.txt, __init__.py, deploy.sh}`.
- OUTPUT_TYPE_REGISTRY centralizes "for sport S phase P, what outputs are expected" — 21 NBA outputs across 6 phases, 6 MLB outputs across 2 phases (initial scope).
- MERGE pattern: idempotent re-runs update timestamps, never revert COMPLETE/EMPTY_OK back to EXPECTED.
- Out-of-window dates (e.g. NBA July) seed as EMPTY_OK rather than EXPECTED — keeps gap_detector quiet during off-season while preserving the contract row.
- Smoke test: 297 rows seeded across 11 (date, sport) pairs in <10s.

### C.3 Historical seed for 2025-26 season (running in background)
- 2025-10-01 → today + 14d for both sports.
- Pre-fix scope: NBA had 109 missing days (Oct 21 - Feb 6). After seed completes, every one of those dates has 21 EXPECTED rows ready for gap_detector to surface.

### C.4 phase_completion_reconciler — pending (Phase D)
- Reconciler will flip EXPECTED → COMPLETE/EMPTY_OK/DEGRADED based on actuals.
- Will be implemented in Phase D alongside the metrics emitter.

---

## Phase D — Unified observability layer (in_progress, 2026-05-09)

### D.1 shared.observability.metrics — Cloud Monitoring custom metrics emitter
- New `shared/observability/__init__.py` + `shared/observability/metrics.py`.
- Single `emit_metric(metric_name, value, labels, kind)` API. Fail-open: if monitoring_v3 is unreachable or not installed, logs and returns rather than crashing the caller.
- Convenience `emit_phase_completion(phase, output_type, status, sport, row_count)` encodes status as a numeric value (COMPLETE/EMPTY_OK=1.0, EXPECTED/RUNNING=0.5, DEGRADED=0.25, FAILED=0.0) so dashboards can graph it directly.
- Custom metric domain: `custom.googleapis.com/nba_pipeline/`.

### D.2 phase_completion_reconciler Cloud Function
- New `orchestration/cloud_functions/phase_completion_reconciler/{main.py, requirements.txt, __init__.py, deploy.sh}`.
- Reads up to 500 EXPECTED rows whose `expected_by < NOW()`, queries the actual partition (BQ COUNT or GCS object), updates status:
  - row_count > 0 → COMPLETE
  - row_count == 0 + halt_active OR no_games → EMPTY_OK
  - row_count == 0 + games scheduled + attempts < 3 → EXPECTED + attempts++
  - row_count == 0 + attempts >= 3 → DEGRADED (gap_detector picks this up)
- Emits `phase_completion` metric per row.
- Smoke test running locally to verify against the seeded rows.

## Phase E — Self-healing gap detector (in_progress, 2026-05-09)

### E.1 gap_detector Cloud Function
- New `orchestration/cloud_functions/gap_detector/{main.py, requirements.txt, __init__.py, deploy.sh}`.
- Reads stale EXPECTED + DEGRADED rows; publishes one `nba-backfill-trigger` Pub/Sub message per row (capped at 50/run).
- Rows past `MAX_BACKFILL_ATTEMPTS` (3) → FAILED status; alert fires.
- Scheduled at :15 and :45 of each hour (offset from reconciler at :00 and :30).

### E.2 Pub/Sub topic created
- `projects/nba-props-platform/topics/nba-backfill-trigger` exists.
- `scraper-gap-backfiller` will be refactored to subscribe in Phase F.

---


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
