# July Measurement-Infrastructure Build — Implementation Spec

**Produced by the 4-fable-agent path-forward review (2026-07-03). Adjudicated into the
off-season plan (see `docs/09-handoff/2026-07-03-5-adjudicated-plan.md`).**

**Why:** at realized volume (189 published BB picks / 89 days = 3.4/day, 41% UNDER — verified),
the P4 shadow-signal promotion gates (live N≥30 on PUBLISHED picks) mostly cannot resolve in
2026-27 (~150-430-day clocks). The measurement layer that fixes this is broken:
`model_bb_candidates` has 33 rows (created 3/9 only, CREATE_NEVER + swallowed load errors ate
~2 months; DELETE-by-date is last-writer-wins lossy), and `best_bets_filtered_picks` has tags
on only 32% of rows (pre-signal-stage `_record_filtered` call sites pass none).

**Verified enabler:** shadow evaluations ALREADY exist in memory for every candidate —
`run_single_model_pipeline()` (per_model_pipeline.py:1613-1626) evaluates the FULL registry
(incl. SHADOW_SIGNALS) on every prediction BEFORE the aggregator. The tag gap is plumbing, not
evaluation. Honest stream size: ~4-6x published (13 unique graded candidates/day in the observed
collapse-era window; likely 15-25 in a normal regime) — NOT the 18x first reported (that counted
per-model row duplication). Caveat: the filtered-picks table spans only 36 collapse-era days;
filter mix may differ in a healthy regime — the tracker publishes per-class HR side-by-side.

**Serve-path impact: ZERO selection-behavior change** (enforced by a byte-identical golden test
on `aggregate()` picks output). Full diff: aggregator attaches already-computed tag metadata to
counterfactual records; exporter writes more/better rows to two measurement tables + five new
columns on pick rows; everything else is YAML, a view, a monitoring script, docs.

---

## Component 1 — Unconditional shadow-tag persistence (~0.5-1 day)

**Decision:** enrich `best_bets_filtered_picks.signal_tags` (option A) + a canonical VIEW.
No new table.

- `ml/signals/aggregator.py` (~15 lines, metadata-only): after `pred_edge_early` (~line 674),
  look up `_tags_early` from the precomputed `signal_results` dict for the candidate; make
  `_record_filtered`'s `sig_tags=None` default fall back to `_tags_early` so all ~40 pre-signal
  call sites persist full tag lists. NO control-flow change; line-1382 block unmoved.
  Skip recording sub-3-edge `edge_floor` rejects (not the promotion population; keep diff minimal).
- **New view `nba_predictions.v_bb_candidate_signal_stream`** (DDL in
  `schemas/bigquery/nba_predictions/`): grain (game_date, player_lookup, recommendation);
  UNION of signal_best_bets_picks (disposition='published'; `retracted_clv` → 'retracted'),
  best_bets_filtered_picks ('filtered', + terminal block_reason from a static obs-vs-blocking
  classification, `all_filter_reasons` array), model_bb_candidates was_selected=FALSE
  ('merge_rejected'); QUALIFY dedup priority published > merge_rejected > filtered; graded via
  LEFT JOIN prediction_accuracy (Session-493 dedup pattern) with player_game_summary fallback.
- Tests: pre-1382-filter fixture lands in filtered_picks WITH tags; shadow tag appears on
  whole-line fixture; golden byte-identical `aggregate()` picks output; view replay on
  2026-03-25 (7 picks / 12 mbc / ~40 filtered) — grain uniqueness, priority, graded ≥85%.

## Component 2 — Fix `model_bb_candidates` writer (~1 day) — BUILD FIRST

Root causes (verified): (1) full-date DELETE+APPEND → last intraday re-export (post-tip,
candidate-starved) destroys the morning set (e.g. 3/10: 2 rows vs 7 published picks); (2) the
c8f4efb7 collect fn emits list-of-dicts into STRING `qualifying_subsets` (non-empty ⇒ whole
load job fails, swallowed as warning), `[]` into STRING cols, float into INT
`star_teammates_out`; (3) Task-#39 NULLs are mostly key-name mismatches
(`player_tier`→`player_line_tier`, `is_home`→`home_away`, `rest_days`→`is_back_to_back`,
`spread_magnitude` ≠ `spread`).

- Scoped upsert: DELETE by `(system_id,player_lookup)` keys for the date, then APPEND; add
  `export_run_at TIMESTAMP` column; abort APPEND on DELETE failure (mirror
  `_write_filtered_picks`); move the write above the started-games early return in `export()`.
- Type/name fixes per above; `json.dumps` qualifying_subsets; emit None not `[]`;
  `spread: None` explicitly (don't alias spread_magnitude); stamp `rank_in_pipeline` (enumerate
  by composite DESC in `run_single_model_pipeline`, ~3 lines) and `pipeline_hr_21d/source` from
  `shared_ctx.model_health_map`. **Also persist `book_count`** — makes the deferred P1.4
  decision queryable in December.
- Tests: **load-type round-trip into a scratch table from the schema JSON** (the test that would
  have caught all of this), scoped-upsert survival test, replay 2026-03-10 asserting ≥7 rows.

## Component 3 — Two-tier promotion gates, PRE-REGISTERED (~1 day)

Gates live as structured `promotion` blocks in `shared/registry/signals.yaml` / `filters.yaml`
(git commit = pre-registration timestamp) + verbatim doc `PREREG-promotion-gates-2026-27.md`.

**Bias control = stratification by block class** (N too small for regression adjustment):
- **Class A — selection-orthogonal, INCLUDED in Tier-1:** structural gates independent of a
  shadow signal's mechanism: SC/rsc gates (shadow tags are excluded from real_sc BY CONSTRUCTION
  — cleanest orthogonality argument), quality/confidence floors, merge caps
  (team/game/volume/rescue/dedup), blacklist, model-sanity, edge floors.
- **Class B — outcome-correlated, EXCLUDED (diagnostic only):** cold-shooting blocks, line-move
  blocks (incl. clv_diverge), counter_market, blowout risk, opponent blocks, sanity blocks.

**Tier 1** = published ∪ retracted ∪ Class-A-blocked ∪ merge-rejected, graded, deduped.
**Tier 2** = published-only monitoring; promotion vetoed if published HR grossly contradicts.

**What stream evidence CAN license:** ranking-weight promotion (shadow → UNDER_SIGNAL_WEIGHTS).
**CANNOT license:** rescue activation (needs incremental-zone test, edge 3-5.9, per 2026-07-01
rule); any OVER promotion (frozen). **Power honesty:** N≥100 + Wilson-LCB90 ≥ 52.4% requires
observed HR ≥ ~60.5% — gates resolve only true effects ≥ +6pp.

The six pre-registered gates (weekly tracker checks; every promotion needs user sign-off):
1. `line_converging_under`: T1 N≥100 UNDER, HR≥58%, LCB90≥52.4 → eligible (weight ~1.5,
   non-rescue). T2 N≥15 HR≥50 veto. Kill: N≥100 HR<52.4. DATA_GATED on the CLV re-export +
   intraday snapshot schedulers. Clock ≈ mid-Dec 2026.
2. `whole_line_precision` (UNDER only; OVER frozen): T1 N≥100, HR≥60%, LCB90≥53.5 → eligible
   (weight 1.0-1.5). Kill: N≥100 HR<55. Clock ≈ Jan 2027.
3. `b2b_fatigue_under`: T1 N≥100, HR≥58%, LCB90≥52.4 → eligible (weight ~2.0). Pre-condition:
   rest_days non-NULL ≥90% of stream (the S494 removal was a data bug). Registry's published
   N≥30 gate stays as fallback path. Clock ≈ Feb 2027.
4. `national_tv_under`: **declared UNRESOLVABLE this season** (+1.2pp claimed effect needs
   N≈1,900). Harm gate only: N≥100 HR<50 → remove; else hold + pool with 2027-28; pairing-signal
   path only if additive check passes (line≥22 stratum, HR(fired)−HR(not) ≥ +4pp, N≥60/cell).
5. `low_variance_under_block` (observation filter): ACTIVATE if live CF HR ≤48% @ N≥30;
   DELETE if CF HR ≥58% @ N≥30 (2025-26-style inversion); else hold.
6. `clv_diverge_under_block` (ACTIVE): KEEP if CF HR ≤50% @ N≥30 by ~Jan 15; DEMOTE to
   observation if CF HR ≥55% @ N≥30 (add to ELIGIBLE_FOR_AUTO_DEMOTE w/ min-picks 30);
   50-55% → re-check @ N≥60. `retracted_clv` lane measured separately.

## Component 4 — Promotion tracker (~1-1.5 days)

Extend `bin/monitoring/signal_weight_report.py` (80% exists; CF deploys via MONITOR_MAP):
- Kill hardcoded CURRENT_UNDER_WEIGHTS drift (contains removed signals) — import
  UNDER/OVER_SIGNAL_WEIGHTS, SHADOW_SIGNALS, BASE_SIGNALS from `ml.signals.aggregator` (fallback:
  tiny `weights_export.py` module if CF vendoring is painful) + gates from the registry loader.
- New per-signal gate table: T1 N | HR | Wilson LCB90 | gate | distance-to-gate
  (n_remaining / 14d fire rate; render "UNRESOLVABLE (>200d)" honestly) | published N/HR |
  verdict ∈ {READY, ON_TRACK, AT_RISK, KILL, UNRESOLVABLE, DATA_GATED}.
- Reads `v_bb_candidate_signal_stream` ONLY (never raw tables — dedup is the N-inflation
  control). Slack `#nba-alerts` + GCS `v1/systems/promotion-tracker.json` (internal).
- Scheduler `signal-weight-report-weekly` restored via the restore manifest (NOT one-off).
  Until then: manual `--dry-run` runs. Must render "no stream data" gracefully off-season.
- Tests: wilson_lcb known values (60/100 → ≈0.5178); verdict table-driven; import-sync test
  (every weight key renders — permanently kills the drift class).

## Component 5 — Counterfactual paper-stake logging (~0.5-1 day)

Stamp at `signal_best_bets_exporter._write_to_bigquery()` row construction via pure
`ml/signals/paper_stakes.py::compute_paper_stakes(edge, win_prob)`. BQ-only — never in
pick_dict/JSON. Schema: ADD `stake_flat_units, stake_edge_prop_units, stake_winprob_prop_units,
win_prob_at_pick, calibrator_version` to signal_best_bets_picks (also closes the win_prob-not-
persisted gap).

Pre-registered rules (verbatim in `PREREG-staking-2026-27.md`):
1. flat = 1.0 always.
2. edge_prop = clip(0.5 + 0.25×(|edge|−3.0), 0.5, 2.0).
3. winprob_prop = 25 × max(0, (p×1.909 − 1)/0.909) capped 3.0 (quarter-Kelly at −110,
   1u = 1% bankroll; stakes 0 at p≤52.4%; NULL when win_prob unavailable; calibrator version
   stamped per row).
Resolution (pre-registered): at N≥150 graded (~Feb 2027), adopt a non-flat rule only if it
beats flat by ≥ +0.5u/100 picks AND paired-bootstrap 90% CI excludes 0. The winprob arm doubles
as the live test of whether calibrated win_prob carries sizing information at all.
Stakes stamped PRE same-game haircut; `bet_size_units` applied multiplicatively at analysis.

## Build order & effort (~6-7 working days, all replay-testable off-season)

```
Wk 1: C2 (1d, foundation) → C1 (1d, needs C2's merge_rejected leg)
Wk 2: C3 (1d, needs C1 population defs) → C4 (1.5d, reads C3+C1)
Wk 3: C5 (1d, independent) → integration replay on Mar-2026 dates + buffer (1d)
```

External dependencies flagged into the restore manifest: `signal-weight-report-weekly`,
`phase6-clv-reexport` + intraday odds schedulers (gates 1/6 DATA_GATED without), the
`nba-pipeline-canary` image fix (hosts the closing-line canary guarding gate 1's data source).

## What this buys

Resolvable clocks: line_converging ~Dec 2026, whole_line (UNDER) ~Jan 2027, b2b ~Feb 2027,
low_variance + clv_diverge by mid-Jan — vs "March 2027 / next season / never" published-only.
national_tv honestly declared unresolvable. P2 sizing resolves from one pre-registered query at
the February check.
