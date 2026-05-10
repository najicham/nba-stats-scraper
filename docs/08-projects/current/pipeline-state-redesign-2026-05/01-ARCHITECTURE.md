# Pipeline State Redesign — Architecture

## Problem statement

The 6-phase NBA pipeline (scrape → raw → analytics → precompute → predictions → publishing) has three structural defects that produce silent failures:

1. **Calendar logic is scattered.** `cap_to_pre_late_season`, `cap_to_last_loose_market_date`, edge-based auto-halt, regime classification, and "should this scheduler fire" each compute their own view of season state. They drift.
2. **Halt mode is inferred ad-hoc, not stated.** Some exporters write `halt_active: true` JSON; others silently skip writes; the orchestrator (`post_grading_export`) gates on `graded_count==0` for unrelated reasons. No single source of truth.
3. **Gap detection runs on the present.** Every existing monitor (data-completeness-checker 7d, scraper-gap-backfiller 14d, daily-health-check today/yesterday) looks at recent dates only. When 109 days went missing from Oct 2025 – Feb 2026, no alert fired because the gap was steady-state.

## Two new tables

### `nba_orchestration.halt_state`

Single source of truth for whether the system is producing picks today.

```sql
CREATE TABLE nba_orchestration.halt_state (
  effective_date DATE NOT NULL,            -- the date this state applies to
  sport STRING NOT NULL,                   -- 'nba' or 'mlb'
  halt_active BOOL NOT NULL,
  halt_reason STRING,                      -- 'off_season' | 'edge_collapse' | 'fleet_blocked' | 'manual'
  halt_since DATE,                         -- when current halt started (NULL when active=false)
  halt_metrics JSON,                       -- 7d avg edge, edge-5+ rate, fleet HR — for diagnostics
  source STRING NOT NULL,                  -- which CF wrote this row
  written_at TIMESTAMP NOT NULL
)
PARTITION BY effective_date
CLUSTER BY sport;
```

**Writer:** `halt_state_writer` Cloud Function, runs daily 5 AM ET. Reads `nba_reference.nba_schedule`, `regime_context.compute_regime()`, model registry, prediction stats. Writes one row per (effective_date, sport).

**Readers:** every Phase 6 exporter and the aggregator. They no longer compute halt themselves; they JOIN.

### `nba_orchestration.expected_outputs`

Date-grid contract: for season S, date D, phase P, what output should exist?

```sql
CREATE TABLE nba_orchestration.expected_outputs (
  season STRING NOT NULL,                  -- '2025-26'
  game_date DATE NOT NULL,                 -- the date the output covers
  sport STRING NOT NULL,                   -- 'nba' or 'mlb'
  phase STRING NOT NULL,                   -- 'phase1_scrape' | 'phase2_raw' | 'phase3_analytics' | 'phase4_precompute' | 'phase5_predictions' | 'phase6_publish'
  output_type STRING NOT NULL,             -- e.g. 'nbac_gamebook_player_stats' | 'ml_feature_store_v2' | 'signal-best-bets/{date}.json'
  expected_partition STRING NOT NULL,      -- BQ partition key OR GCS path
  status STRING NOT NULL,                  -- 'EXPECTED' | 'RUNNING' | 'COMPLETE' | 'EMPTY_OK' | 'FAILED' | 'DEGRADED'
  expected_by TIMESTAMP,                   -- SLA: by when should this be COMPLETE?
  attempts INT64 DEFAULT 0,
  last_run_at TIMESTAMP,
  last_error STRING,
  row_count INT64,                         -- actuals; 0 + EMPTY_OK is fine, 0 + EXPECTED is a gap
  hash STRING                              -- content hash for idempotency
)
PARTITION BY game_date
CLUSTER BY sport, phase, status;
```

**Writer (planner):** `expected_outputs_planner` Cloud Function, nightly. Reads `nba_reference.nba_schedule` + `halt_state` + sport calendar. For each (date, phase, output) in next 14d + historical season seed, ensures a row exists.

**Reconciler:** `phase_completion_reconciler` CF. After each phase's run, queries actual partitions, flips status to `COMPLETE` (rows > 0) or `EMPTY_OK` (rows = 0 and halt_state says no games OR halt_active). Stale `EXPECTED` past `expected_by` becomes `DEGRADED`.

`EMPTY_OK` is what makes off-season correctness equal to season correctness. We *expect* empty rows on July 4; they aren't gaps, they're a known-no-games state.

## How this fixes the recurring failures

| Failure mode | Old behavior | New behavior |
|---|---|---|
| Oct 2025 – Feb 2026 109-day gap | No tool watches historical dates | `expected_outputs` has rows for every Oct 21+ date marked `EXPECTED`; `gap_detector` fires on stale `EXPECTED` rows |
| `best-bets/all.json` frozen 21d | `skip_picks_exports` swallows history exporter | History exporter reads `halt_state.halt_active`; writes daily JSON with halt envelope |
| Dec 27 – Jan 21 silent gap | Monitoring is 7-14 day windows | Historical seed in `expected_outputs` → reconciler diff fires once `gap_detector` sees `EXPECTED + age > SLA` |
| Calendar patch drift | Multiple files compute season state | `halt_state` is the only writer; everyone else reads |
| Skill files reference removed filters | Manual sync | `shared/registry/filters.yaml` is the source; pre-commit hook fails CI if doc references unknown filters |

## Halt envelope (Phase 6 JSON contract)

Every JSON published by `data_processors/publishing/` includes:

```json
{
  "halt_active": false,
  "halt_reason": null,
  "halt_since": null,
  "halt_source_date": "2026-05-09",
  ... existing payload ...
}
```

When `halt_active=true`, payload bodies (`picks`, `players`, etc.) are still emitted as empty arrays — never absent keys. Frontend never crashes on missing keys; it branches on `halt_active`.

`BaseExporter.halt_envelope()` (new method) reads from `halt_state` table once per export run. `safe_export()` (already exists) becomes the only write path; direct `upload_to_gcs` calls are deprecated.

## Self-healing flow

```
expected_outputs_planner (nightly)        ┐
   ↓ writes rows                          │
expected_outputs (BQ)                     │
   ↓ scanned every 30min                  │
gap_detector CF                           │ ───→ Pub/Sub: nba-backfill-trigger
   ↓ pubs message {date, phase, output}   │              ↓
                                          │      scraper-gap-backfiller (subscribes)
                                          │              ↓
                                          │      runs scraper for missing date
                                          │              ↓
phase_completion_reconciler ←─────────────┘      writes data
   updates expected_outputs.status
```

3-attempt cap per (date, phase). Past that, fires `expected_output_overdue` Cloud Monitoring alert.

## Observability layer

One Cloud Monitoring dashboard, three alert policies, one Pub/Sub-routed Slack alerter.

- **Metrics:** `shared/observability/metrics.py` exposes `emit(phase, date, status, latency_ms, row_count)`. Each Phase 2/3/4/5/6 processor calls it. Custom metric `nba/pipeline/phase_completion`.
- **Dashboard:** `nba-pipeline-health` shows phase × date heatmap (sourced from `expected_outputs` view), latency histograms, halt_state timeline, MLB equivalent panel.
- **Alerts (3 policies):**
  - `expected_output_overdue` — any `expected_outputs.status='EXPECTED'` with `expected_by < NOW() - 1h`.
  - `halt_state_stale` — `halt_state.written_at < NOW() - 36h` (writer is broken).
  - `phase_error_rate` — `nba/pipeline/phase_error_rate` > 0.1 over 1h.

Retired CFs: `daily-health-check`, `transition-monitor`, `pipeline-health-summary`, `live-freshness-monitor`, `gcs-freshness-monitor`, `pipeline-reconciliation`, `realtime-completeness-checker`, `historical_completeness_monitor.py` (was never deployed).

Kept (different SLAs / different concerns): `decay-detection`, `weekly-retrain`, `filter-counterfactual-evaluator`, `deployment_drift_alerter`.

## Frontend halt-aware rendering

`props-web/src/components/HaltBanner.tsx` (new). Reads `halt_active` from any loaded JSON; renders explicit "Off-season" or "Picks paused — fleet blocked" treatment. Replaces today's misleading "Today's picks aren't out yet — check back around 2 PM ET" copy on `best-bets/page.tsx:311`.

Single GCP Uptime Check with content matchers: `playerprops.io/`, `/mlb`, `/nba/best-bets`. Asserts non-skeleton body within 10s. Replaces the proposed 5-layer monitoring stack.

## Migration order (re-stated)

1. **Phase A:** point fixes that are still load-bearing (cap_to_pre_late_season, rescue gate, post_grading skip, skill drift). Buys time to do the structural work.
2. **Phase B:** halt_state shadow-writes; readers added behind feature flag; frontend reads `halt_active` from existing JSONs after exporters wire it in.
3. **Phase C:** expected_outputs read-only; nothing depends on it.
4. **Phase D:** observability; reconciler activates expected_outputs.
5. **Phase E:** gap_detector flips on; scraper-gap-backfiller becomes Pub/Sub subscriber.
6. **Phase F:** backfill, driven by gap_detector + expected_outputs.
7. **Phase G:** alert policies live → retire old monitors only after 7 days of clean runs.
8. **Phase H–L:** parallel cleanup tracks.
