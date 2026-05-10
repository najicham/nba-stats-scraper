-- File: schemas/bigquery/nba_orchestration/halt_state.sql
-- ============================================================================
-- Halt State - Single Source of Truth for "Are We Producing Picks?"
-- ============================================================================
-- Purpose: One row per (effective_date, sport). Replaces ad-hoc halt
--          computation scattered across regime_context.py, aggregator.py,
--          signal_best_bets_exporter.py, and post_grading_export.
--
-- Why:     Pre-redesign, halt mode was inferred ad-hoc — three files, three
--          views of "is the system halted today?". Some exporters wrote
--          halt-aware JSON, others silently skipped writes, and the
--          orchestrator gated unrelated history exports on graded_count.
--
--          This table is written once per day by halt_state_writer CF and
--          read by every Phase 6 exporter via BaseExporter.halt_envelope().
--
-- Created: 2026-05-09 (pipeline-state-redesign)
--
-- Writer:  orchestration/cloud_functions/halt_state_writer/
-- Readers: data_processors/publishing/base_exporter.py (halt_envelope)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.halt_state` (

  -- ==========================================================================
  -- KEY
  -- ==========================================================================

  effective_date DATE NOT NULL,
    -- The date this halt-state row applies to (game_date semantics).

  sport STRING NOT NULL,
    -- 'nba' or 'mlb'. One halt state per sport per date.

  -- ==========================================================================
  -- STATE
  -- ==========================================================================

  halt_active BOOL NOT NULL,
    -- TRUE when the system should produce zero picks for (sport, effective_date).
    -- Causes: off_season, edge_collapse, fleet_blocked, manual.

  halt_reason STRING,
    -- Short canonical reason. Enum (writer/main.py decision tree order):
    --   'off_season'           — no games in schedule within ±21d window
    --                            OR outside the sport's calendar season window
    --   'between_rounds'       — in-season but no future games in next 14d
    --                            (e.g. NBA between playoff rounds)
    --   'edge_collapse'        — Session 515 7d avg edge < 5.0 AND edge-5+ < 50%
    --   'fleet_blocked'        — all enabled models in BLOCKED state
    --   'predictions_inactive' — games scheduled but predictions silent for 3+ days
    --                            (catches operator-paused schedulers, prediction
    --                            worker crashes, season-restart cold start)
    --   'manual'               — operator-set via halt_overrides
    --   NULL                   — not halted
    -- 'tight_market' is reserved but not yet emitted by the writer.

  halt_since DATE,
    -- When the current halt began (inclusive). NULL when halt_active=false.
    -- Allows the frontend / docs to say "halt active for N days".

  halt_metrics JSON,
    -- Diagnostic context: rolling_7d_avg_edge, rolling_7d_pct_edge_5plus,
    -- vegas_mae_7d, fleet_block_count, num_games_on_slate. JSON for forward
    -- compatibility — readers should treat unknown keys gracefully.

  -- ==========================================================================
  -- PROVENANCE
  -- ==========================================================================

  source STRING NOT NULL,
    -- Which writer produced this row. Today: 'halt_state_writer_cf' or
    -- 'manual_override'. Future: backfill jobs.

  written_at TIMESTAMP NOT NULL,
    -- Wall-clock time the row was written. Used by the halt_state_stale
    -- alert policy — if today's row is missing or > 36h old, alert.

  -- Optional: who wrote it (for audit trails when humans flip halt manually)
  actor STRING

)
PARTITION BY effective_date
CLUSTER BY sport, halt_active
OPTIONS(
  description = "Single source of truth for halt status. Written daily by halt_state_writer CF. Read by every Phase 6 exporter via BaseExporter.halt_envelope().",
  labels = [
    ("project", "pipeline-state-redesign"),
    ("phase", "phase-b")
  ]
);
