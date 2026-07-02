# Session Handoff — 2026-05-12 — MLB UNDER shadow rollout + open improvement threads

This session: 6-agent investigation of why MLB ships OVER-only, synthesis into a sequenced plan, and full project documentation. **No code shipped.** Next session picks up the analysis thread — either start executing the plan, or keep studying the open improvement threads listed below.

## What was decided

User chose **(a) ship UNDER in shadow mode for 45 days after sequenced pre-work**, with shared 5/day pick quota and UNDER ranking redesigned from scratch using shadow data.

## Files to read first (in order)

The full project lives at `docs/08-projects/current/mlb-under-shadow-rollout/`. Read in this order:

1. **`00-OVERVIEW.md`** — status, headline findings, file index
2. **`02-AGENT-FINDINGS.md`** — distilled report from all 6 agents (the data behind every decision)
3. **`03-DECISIONS.md`** — what user picked and why
4. **`01-PLAN.md`** — sequenced 7-step execution plan with file paths
5. **`04-RUNBOOK.md`** — graduation gate + flip/rollback procedures
6. **`05-RANKING-REDESIGN.md`** — placeholder for Day-30 empirical ranker design

Predecessor handoff: `docs/09-handoff/2026-05-12-mlb-under-disabled-investigation.md` (the original brief that triggered this investigation).

## Headline finding to keep in mind

**Live 2026 UNDER is in regime collapse RIGHT NOW.** April 59.4% → May 40.9% → most recent week 0/3. Walk-forward 2024/2025 numbers in memory (52.4% / 48.1%) are unreproducible from BQ. Do NOT suggest flipping `MLB_UNDER_ENABLED=true` under any circumstances until Phase 0+1 ship and the 45-day graduation gate passes.

## Two possible next-session shapes

### Shape A — Execute Phase 0 of the plan

If user wants to start shipping: begin Phase 0 Step 1 (UNDER signal pipeline repair, ~6h). All file paths and exact changes are in `01-PLAN.md`. Sequence:

1. Step 1 — promote 3 shadow signals to active, remove 2 dead entries from weights, wire `velocity_change` into `supplemental_loader.py`
2. Step 2 — add `high_line_under_block` + `elite_k9_under_block` filters
3. Step 3 — un-hardcode `recommendation='OVER'` in `mlb_model_performance.py` + `mlb_league_macro.py`, run schema migrations

Each step has rollback noted in plan. Ship one step at a time, verify with the queries in `04-RUNBOOK.md`, move on.

### Shape B — Keep studying improvement threads (probably the better fit)

User said "continue to study ways we can improve things" — so this is open-ended. Specific threads the 6 agents surfaced but didn't fully explore:

**Thread 1 — Quantile-loss retrain feasibility (Agent 3's recommendation, deferred to Phase 3)**

Agent 3 found the structural OVER bias traces to RMSE loss in `scripts/mlb/training/train_regressor_v2.py:83`. Single-line fix: `'RMSE'` → `'Quantile:alpha=0.5'`. Worth doing a walk-forward simulation BEFORE shadow ships:
- Branch off main, change the loss function, retrain with `--training-start 2024-04-01`
- Run `walk_forward_simulation.py` (note: this currently writes JSON to `results/mlb_walkforward_2025/`, not BQ — Agent 1's complaint)
- Compare OVER HR (must stay >= 58%) and UNDER walk-forward (target >= 53% raw at edge 0.75)
- If both pass, the Quantile retrain could replace shadow entirely — UNDER might be live-shippable without 45 days of shadow

**Thread 2 — Walk-forward output into BigQuery (Agent 1's complaint)**

Memory has UNDER walk-forward claims (52.4% / 48.1% HR, -6.8% ROI) that cannot be reproduced from BQ. They live only in `scripts/mlb/training/walk_forward_simulation.py` JSON output. Add a BQ write step to that script:
- New table: `mlb_predictions.walk_forward_results` (partitioned by simulation_date, clustered by model_id + recommendation)
- Columns: every column from `prediction_accuracy` plus `simulation_config_json`, `model_window_days`, `retrain_cadence_days`
- Backfill all historical walk-forward runs we still have JSON for

Without this, every future decision about UNDER (or any other strategic question) repeats today's pattern: claims in memory, unauditable in BQ, agents have to reproduce from scratch.

**Thread 3 — `model_raw_predictions` table (mentioned in `mlb-improvements-2026-05/PLAN.md:90`)**

Reviewer 5 flagged this as "single highest-leverage move not in original plan." Write every prediction with full feature snapshot + signal/filter evaluations to a new table, regardless of BB eligibility. Currently we lose signal-evaluation history for filtered/edge-floor-blocked picks. With this table, every future "which signals would have fired" question is a BQ query, not a code spelunk.

Worth scoping: schema, write path (extend `_evaluate_shadow_picks`?), retention policy.

**Thread 4 — Calendar fragility on MLB filters**

`mlb-system.md` memory line 216: "July drift. Likely All-Star break + trade deadline disruption. 14-day retrain cadence self-corrects." Agent 5's proposed `summer_elite_under_block` filter was deferred as "calendar-fragile." Investigate:
- Is the May 2026 UNDER collapse Agent 1 found a calendar effect (e.g. roster volatility, mid-May call-ups)?
- Could a calendar-aware filter help, OR is calendar variance just noise and the auto-halt should handle it?
- Look at NBA's `regime_context.py` adoption pattern — it ported similar calendar awareness for NBA, was it useful?

**Thread 5 — Cross-model fleet for MLB**

MLB runs a single CatBoost regressor. NBA runs 7+ models with cross-model signals (`combo_3way`, `book_disagreement`). Per memory `mlb-system.md:5-7`, LightGBM V1 + XGBoost V1 are "ready, opt-in via MLB_ACTIVE_SYSTEMS." If activated:
- Would `book_disagree_under` finally work? (Currently blocked on `oa_std` plumbing, not model count.)
- Are LightGBM/XGBoost predictions actually different enough from CatBoost to produce useful disagreement signals?
- What's the deployment cost of running a 3-model fleet for MLB?

Note: NBA Session 487 found that all-LGBM fleet (r >= 0.95 clones) makes cross-model signals fire incorrectly. MLB shouldn't repeat that mistake — diversity matters.

**Thread 6 — Backfill the BettingPros multi-book data**

Memory: BettingPros API works now (Session 517 fix), gives 12-book pricing. But historical `oddsa_pitcher_props` had only 4-5 books. Agent 4's `book_disagree_under` proposal references `oa_std >= 0.65` thresholds from PLAN.md, but those thresholds were calibrated on 4-5 book regime. Same lesson as NBA Session 515 — book count scaling breaks std thresholds.

Worth: scan `mlb_raw.oddsa_pitcher_props` and `bettingpros_pitcher_props` (if it exists), compute the book-count distribution per date, decide if a `_get_min_std(book_count, market_id)` scaffolding is needed before promoting `book_disagree_under`.

## Recommended approach for the next session

If you have ~half a day, **start with Thread 2 (walk-forward → BQ)**. It's the smallest, the highest leverage, and unblocks everything else. Without it, future agents will keep producing analysis that can't be re-validated 3 months later.

If you have a full day, **add Thread 1 (Quantile retrain walk-forward)**. If Quantile loss actually fixes the UNDER bias, the entire shadow rollout might be unnecessary — but you need walk-forward output to know.

If user wants to ship code now, **execute Phase 0 Step 1**. Concrete, low-risk, 6h.

## What NOT to do without re-checking with user

- Flip `MLB_UNDER_ENABLED=true` — locked behind the graduation gate
- Trigger `signal-best-bets` historical re-export for MLB — deletes picks (memory: `sessions-472-488.md`)
- Train and DEPLOY a new model — only train, deployment needs explicit approval (CLAUDE.md governance rules)
- Touch the OVER pipeline — it's 60.3% HR live, don't disturb

## Open questions that came up but weren't resolved

- Should `UNDER_MIN_SIGNALS` graduate from 3 → 4 once 5 weighted signals fire reliably? (Deferred to Day 47 graduation analysis.)
- Where does `pitcher_blacklist_under` live in the priority order? Agent 5 listed it last but symmetric blacklisting (pitchers with >70% OVER hit rate) is a clean idea — could ship earlier.
- Does `bottom_up_agrees_over` signal (referenced in `_build_pick_angles`) have an UNDER analogue? Memory and PLAN.md are silent.

## File pointers for quick orientation

- Main exporter: `ml/signals/mlb/best_bets_exporter.py` (1162 lines — every UNDER decision flows through this)
- Signal/filter classes: `ml/signals/mlb/signals.py`
- Registry: `ml/signals/mlb/registry.py`
- Training: `scripts/mlb/training/train_regressor_v2.py`
- Walk-forward: `scripts/mlb/training/walk_forward_simulation.py` (the unauditable one)
- Worker: `predictions/mlb/worker.py`
- Supplemental: `predictions/mlb/supplemental_loader.py` (where `velocity_change` and `opening_line` need wiring)
- Existing project docs: `docs/08-projects/current/mlb-under-shadow-rollout/` (THIS investigation) and `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md` (yesterday's 23-agent broader MLB investigation — substantial overlap with today's signal/filter findings)

## Auto-memory pointers

- `mlb-system.md` line 80 updated with project doc pointer — future sessions will find it on memory load
- MEMORY.md is at 225 lines (cap 200) — consider trimming during next session's cleanup pass if it's getting cited as a problem

## End-of-session state

- No code changes
- 6 new docs in `docs/08-projects/current/mlb-under-shadow-rollout/`
- 1 line edited in `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md` (cross-reference)
- 1 line edited in `mlb-system.md` memory (project pointer)
- Working tree has substantial uncommitted changes from prior sessions (see `git status`) — not from this session
