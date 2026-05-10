# Pipeline State Redesign

**Status:** in production from 2026-05-09 (Phases A–E + G + H landed; F + I + J + K + L in progress).
**Driver:** off-season 2026 retrospective audit found 109 days of NBA data silently absent for 9 months.

## Problem

Three structural defects produced silent failures:

1. **Calendar logic was scattered.** `cap_to_pre_late_season`, `cap_to_last_loose_market_date`, edge-based auto-halt, regime classification, and "should this scheduler fire" each computed their own view of season state. They drifted (Oct 2026 retrains would have been capped to Feb 2026 because the cap function never knew the season had rolled over).

2. **Halt mode was inferred ad-hoc.** Some exporters wrote `halt_active: true` JSON. Others silently skipped writes. The orchestrator (`post_grading_export`) gated unrelated history exporters on `graded_count==0`. No single source of truth — `best-bets/all.json` froze for 21 days during NBA halt because of a misplaced gate.

3. **Gap detection ran on the present.** Every existing monitor (`data-completeness-checker` 7d, `scraper-gap-backfiller` 14d, `daily-health-check` today/yesterday) looked at recent dates only. When 109 days went missing from Oct 2025 – Feb 2026, no alert fired because the gap was steady-state.

## Architecture

Two new BigQuery tables make pipeline state a first-class concept.

### `nba_orchestration.halt_state`

One row per `(effective_date, sport)`. Single source of truth for "are we producing picks today?"

| Column | Purpose |
|---|---|
| `effective_date`, `sport` | Composite key. |
| `halt_active` | Boolean. Drives every Phase 6 exporter's halt branch. |
| `halt_reason` | `off_season` \| `edge_collapse` \| `fleet_blocked` \| `tight_market` \| `manual` |
| `halt_since` | When the current halt began. |
| `halt_metrics` | JSON diagnostic context. |
| `source`, `written_at`, `actor` | Provenance. |

**Writer:** `halt_state_writer` Cloud Function — daily 5 AM ET. Inlines the Session 515 edge-collapse logic and a fleet-blocked check. Idempotent MERGE.

**Readers:** every Phase 6 exporter via `BaseExporter.halt_envelope(sport, target_date)`. Returns canonical 4-key envelope (`halt_active`, `halt_reason`, `halt_since`, `halt_source_date`) merged into every published JSON.

**Failure mode:** `halt_envelope` is fail-open. If BQ unreachable or row missing, returns `halt_reason='unknown_state'`. Frontend handles all four states.

### `nba_orchestration.expected_outputs`

One row per `(season, game_date, sport, phase, output_type)`. The contract: "for this date, this phase, this output should exist."

| Column | Purpose |
|---|---|
| `(season, game_date, sport, phase, output_type)` | Composite key. |
| `status` | `EXPECTED` \| `RUNNING` \| `COMPLETE` \| `EMPTY_OK` \| `FAILED` \| `DEGRADED` |
| `expected_partition` | BQ partition or GCS path — where to look for the actual. |
| `expected_by` | SLA. Past this point, EXPECTED rows become candidates for `gap_detector`. |
| `attempts`, `last_run_at`, `last_error` | Backfill audit. |
| `row_count`, `byte_size`, `content_hash` | Actuals. |

**Writer:** `expected_outputs_planner` CF — nightly 4 AM ET. For each `(date, sport)` in next 14 days + historical seed (Oct 1 2025 – today), MERGEs one row per `(phase, output_type)` from `OUTPUT_TYPE_REGISTRY`. Idempotent.

**Reconciler:** `phase_completion_reconciler` CF — every 30 min at `:00`, `:30`. Pulls EXPECTED rows past `expected_by`, queries actuals (BQ COUNT or GCS exists), updates status:
- `row_count > 0` → `COMPLETE`
- `row_count == 0` + halt or no-games → `EMPTY_OK`
- `row_count == 0` + games + attempts < 3 → stay `EXPECTED`, `attempts++`
- `row_count == 0` + attempts ≥ 3 → `DEGRADED`

**Gap detector:** `gap_detector` CF — every 30 min at `:15`, `:45`. Pulls stale EXPECTED + DEGRADED rows; publishes one `nba-backfill-trigger` Pub/Sub message per row (capped at 50/run). Past `MAX_BACKFILL_ATTEMPTS=3` → `FAILED`.

### Self-healing flow

```
expected_outputs_planner (4 AM ET)
   │
   ▼
expected_outputs (BQ table) ◀────── phase_completion_reconciler (every :00/:30)
   │                                 (queries actuals, flips status)
   │
   │ stale EXPECTED rows
   ▼
gap_detector (every :15/:45)
   │
   ▼ Pub/Sub: nba-backfill-trigger
   │
   ▼
scraper-gap-backfiller (subscriber — Phase F)
   │
   ▼
runs scraper / processor for missing date → updates actuals → reconciler closes the loop
```

3-attempt cap per `(date, phase)`. Past that, `FAILED` status fires the `expected_output_overdue` alert.

## Observability

- **Single emitter:** `shared/observability/metrics.py::emit_metric()` writes to `custom.googleapis.com/nba_pipeline/*`. Fail-open (telemetry failure never crashes the caller).
- **Three custom metrics:**
  - `phase_completion` — gauge 0–1 per `(phase, output_type, status, sport)`.
  - `phase_row_count` — gauge of actual row counts.
  - `halt_state_age_hours` — gauge per sport (writer health).
- **Three alert policies** (`monitoring/alert-policies/`):
  - `expected-output-overdue` — > 5 overdue rows for 30 min.
  - `halt-state-stale` — `halt_state_age_hours` > 36.
  - `phase-error-rate` — `phase_completion` 1h mean < 0.7.
- **Dashboard** (deferred to Phase L): `nba-pipeline-health` Cloud Monitoring dashboard sourced from `expected_outputs_coverage` view + the three custom metrics.

## Phase 6 publishing contract

Every NBA + MLB Phase 6 JSON now carries:

```json
{
  "halt_active": false,
  "halt_reason": null,
  "halt_since": null,
  "halt_source_date": "2026-05-09",
  ...payload...
}
```

When `halt_active=true`, payload bodies (`picks`, `players`, etc.) are still emitted as empty arrays — never absent keys. Frontend never crashes on missing keys; it branches on `halt_active`.

The `post_grading_export` orchestrator no longer gates `BestBetsAllExporter` and `BestBetsRecordExporter` on `graded_count > 0`. Those are history files, not today's picks; they always run. This fixes the "all.json frozen 21 days during halt" bug.

## Registry-driven docs

`shared/registry/{signals,filters}.yaml` is the source of truth for signal + filter tags. Code consumers import via `shared.registry.{is_known_signal, is_known_filter}`. Docs are validated by `.pre-commit-hooks/validate_signal_references.py` — any `tag` reference in `CLAUDE.md`, `.claude/skills/`, or active architecture/operations docs that isn't in the YAML fails CI.

## Files reference

| File | Role |
|---|---|
| `schemas/bigquery/nba_orchestration/halt_state.sql` | Schema |
| `schemas/bigquery/nba_orchestration/expected_outputs.sql` | Schema + 2 views |
| `orchestration/cloud_functions/halt_state_writer/` | Daily writer |
| `orchestration/cloud_functions/expected_outputs_planner/` | Nightly planner |
| `orchestration/cloud_functions/phase_completion_reconciler/` | Every-30-min reconciler |
| `orchestration/cloud_functions/gap_detector/` | Every-30-min detector + Pub/Sub publisher |
| `data_processors/publishing/base_exporter.py` | `halt_envelope()` method |
| `shared/observability/metrics.py` | `emit_metric()` + `emit_phase_completion()` |
| `shared/registry/{signals,filters}.yaml` | Source of truth |
| `monitoring/alert-policies/{expected-output-overdue,halt-state-stale,phase-error-rate}.yaml` | The 3 alerts |
| `.pre-commit-hooks/validate_signal_references.py` | Drift hook |

## Migration order (recap)

1. **A:** Bug fixes (load-bearing: cap_to_pre_late_season, post_grading_export, rescue gate, skill drift). Done 2026-05-09.
2. **B:** halt_state shadow-writes + BaseExporter.halt_envelope; readers added behind feature flag. Done 2026-05-09.
3. **C:** expected_outputs read-only; nothing depends on it yet. Done 2026-05-09 with 6,345-row seed.
4. **D:** Observability + reconciler activates expected_outputs. Done 2026-05-09.
5. **E:** gap_detector flips on; scraper-gap-backfiller becomes Pub/Sub subscriber. Code done 2026-05-09; subscriber refactor pending Phase F.
6. **F:** Backfill (109-day NBA recovery) — uses gap_detector + reconciler.
7. **G:** Cloud Monitoring alerts. Done 2026-05-09. Notification channels attach manually.
8. **H:** Registry + drift hook. Done 2026-05-09.
9. **I + J:** Frontend monitoring + bug fixes (props-web).
10. **K:** Docs (this document is part of K).
11. **L:** Pre-presentation verification.
