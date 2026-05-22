-- File: schemas/bigquery/nba_orchestration/halt_overrides.sql
-- ============================================================================
-- Halt Overrides - Operator-Set Manual Halts
-- ============================================================================
-- Purpose: Lets an operator force a sustained halt that survives the daily
--          halt_state_writer run. Each daily run writes a fresh halt_state row
--          per (effective_date, sport) from the natural decision tree; without
--          this table a manual halt would be overwritten the next morning.
--
-- Semantics: An override can ONLY force halt_active=TRUE. It can never resume
--          the system. A forgotten/stale override is therefore harmless — it
--          can only keep the system more conservative, never publish picks
--          during a real off-season.
--
-- To halt:  INSERT a row (sport, halt_reason='manual', start_date, end_date,
--           active=TRUE, note, ...).
-- To clear: UPDATE the row SET active=FALSE  (or set end_date < today).
--           The next halt_state_writer run reverts to the natural decision.
--
-- Created: 2026-05-21 (implements the manual-override TODO in the writer).
--
-- Writer:  orchestration/cloud_functions/halt_state_writer/ (_get_active_override)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.halt_overrides` (

  sport STRING NOT NULL,
    -- 'nba' or 'mlb'.

  halt_reason STRING NOT NULL,
    -- Canonical reason written into halt_state.halt_reason when this override
    -- forces a halt. Typically 'manual'.

  start_date DATE NOT NULL,
    -- Inclusive. The override applies from this date onward.

  end_date DATE,
    -- Inclusive. NULL = open-ended (until explicitly cleared via active=FALSE).

  active BOOL NOT NULL,
    -- Soft-delete flag. Set FALSE to retract the override.

  note STRING,
    -- Free-text — why this override exists. Goes into halt_metrics for audit.

  created_at TIMESTAMP NOT NULL,

  created_by STRING
    -- Operator / ticket identifier for the audit trail.

)
OPTIONS(
  description = "Operator-set manual halt overrides. An active row forces halt_active=TRUE in halt_state regardless of the natural decision tree. Read by halt_state_writer CF."
);
