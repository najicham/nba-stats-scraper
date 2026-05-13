# Session Handoff — 2026-05-12 — MLB UNDER picks investigation

**Observation from user:** Every MLB best-bets pick in recent days has been OVER. No UNDER picks at all. This is intentional today (env flag `MLB_UNDER_ENABLED=false`), but worth a fresh, agent-led review of whether/how/when to flip it back on — including a serious look at the walk-forward UNDER performance that triggered the disable.

Predecessors:
- `docs/09-handoff/2026-05-12-mlb-modal-polish-vs-nba.md` — earlier today's modal-polish handoff
- 10-agent MLB review (Agent 5 — Best Bets Strategy lane) flagged UNDER re-enablement as **NO-GO** based on 2025 walk-forward 48.1% HR
- Memory: `/home/naji/.claude/projects/-home-naji-code-nba-stats-scraper/memory/mlb-system.md` — sections on UNDER_ENABLED, Walk-Forward Results, and the May 1 trigger

## The shipped state

`ml/signals/mlb/best_bets_exporter.py:64`:
```python
UNDER_ENABLED = os.environ.get('MLB_UNDER_ENABLED', 'false').lower() == 'true'
UNDER_MIN_SIGNALS = 3  # Higher bar than OVER (which uses 2)
```

Default is `false`. The CF env vars on `mlb-prediction-worker` have no override (verified — only OVER lives in the deployed config). Result: zero UNDER picks reach the published JSON regardless of model output.

The published config and live record (per memory, verified today):
- **OVER 60.3% live (38-25, N=63)** — gate condition "OVER HR ≥ 58%" is structurally met
- **UNDER zero live picks since season start** — no fresh data to validate against

## What the next session should investigate

Spawn 4–6 agents in parallel, each with a distinct lane. **Do not let agents duplicate scope.**

### Agent 1 — UNDER historical performance reality check
Memory says UNDER walk-forward = 53.7% raw / 52.4% 2024 / **48.1% 2025 (-6.8% ROI)**. Reproduce these numbers from the BQ tables before trusting them. Specifically:
- `mlb_predictions.prediction_accuracy` filtered to `recommendation = 'UNDER' AND prediction_correct IS NOT NULL` for 2024 and 2025 separately
- Break down by edge bucket (0.5–1.0, 1.0–1.5, 1.5–2.0, 2.0+)
- Break down by month (April through September)
- Break down by home/away
- Report whether the 48.1% figure is broad collapse or concentrated in a specific bucket that could be filtered around

### Agent 2 — Shadow UNDER design
Read `ml/signals/mlb/best_bets_exporter.py` to understand exactly which gates UNDER picks pass through when enabled (`UNDER_MIN_SIGNALS=3`, `UNDER_SIGNAL_WEIGHTS`, edge floors, rescue logic). Design a **shadow mode**:
- Generate UNDER picks but write them to a shadow table (e.g. `mlb_predictions.shadow_under_picks`) — never publish to GCS
- Need to confirm whether NBA's pattern (separate `shadow_mode_predictions` table, `_shadow=true` column on `signal_best_bets_picks`, or a parallel best_bets_picks_shadow) exists for MLB
- Define graduation criteria: N ≥ 30 shadow UNDER picks at ≥ 56% HR over 30 days
- Outline the rollout: shadow → side-by-side comparison → flip `MLB_UNDER_ENABLED=true`

### Agent 3 — Why is OVER bias structural?
The regressor naturally skews OVER (91%+ per the governance comment we just tightened to 80%). Memory's Session 438b autopsy: "Model predicts OVER 60.8%, actual over-rate is only 44-48%. 14.8pp gap." This isn't just a strategy choice — the model is *built* to lean OVER.
- What feature gradients make this so? Pull feature importance from the current model
- Does the prediction worker have any post-hoc UNDER calibration that could be tightened?
- Would a separate UNDER-specialised model (trained only on UNDER outcomes, with different feature emphasis like rest, opposing-team K-rate decline, recent velocity drops) outperform the universal regressor on UNDER picks?

### Agent 4 — Signal coverage for UNDER specifically
`UNDER_SIGNAL_WEIGHTS` in `best_bets_exporter.py` has only 5 entries (per memory). NBA has 11. Map which UNDER-leaning signals exist (`velocity_drop_under`, `short_rest_under`, `cold_3pt_under`-equivalents, hot_3pt_under conversions, etc.) and which are missing entirely. PLAN.md at `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md` already proposed `book_disagree_under` (61–71% HR cross-season at std≥0.65), `line_drop_under` (currently dead because `opening_line` is never assigned), and `velocity_drift_under`. Rank by expected lift.

### Agent 5 — Filter coverage for UNDER
MLB has 6 active filters and they're all OVER-targeted (`whole_line_over`, etc.). If UNDER re-enables, what *negative* filters should block bad UNDER picks? Memory: 48.1% in 2025 isn't random — there's likely a specific archetype (e.g. high-K pitcher facing weak-contact team) that the model keeps picking UNDER on and getting wrong. Identify those archetypes from `prediction_accuracy` and propose filters.

### Agent 6 — Operational
The shadow rollout needs:
- A new BQ table (or column) for shadow UNDER picks
- A backfill plan if we run shadow on historical data first
- An alert pattern (similar to the missing-name alert pattern we shipped today) that fires when shadow UNDER's HR diverges from expectation
- A clear "promotion" runbook: who decides, what threshold, how is the env flag flipped
- Cost impact: ~5 picks/day more if UNDER ships, ~30% increase in published rows

## Open questions for the user

1. **Risk appetite.** Going live with UNDER at known 48% historical HR is a -EV bet. The model needs to *outperform* baseline before flipping. Is the user comfortable shipping in shadow first (no public impact, ~30 days)? Or do they want to A/B test directly in production with reduced stakes on UNDER picks?

2. **Volume.** If UNDER ships and adds ~2-3 picks/day to the existing OVER-only 3-5/day, the public best-bets card density doubles. Acceptable, or should `MAX_PICKS_PER_DAY` stay at 5 and let UNDER compete with OVER for slots?

3. **UNDER ranking.** OVER uses pure edge ranking. NBA uses signal-quality-weighted ranking for UNDER specifically because raw edge is meaningless. MLB inherited `UNDER_SIGNAL_WEIGHTS` but it's untested in live. Is the next session free to redesign UNDER ranking from scratch, or should we match NBA's pattern?

## Suggested next-session opening

```
/clear
Read docs/09-handoff/2026-05-12-mlb-under-disabled-investigation.md.
Spawn the 6 review agents in parallel. Synthesize and propose either
(a) ship UNDER in shadow mode for 30 days, (b) keep UNDER disabled
indefinitely and document the rationale, or (c) ship UNDER with
specific filters/thresholds already validated against a replay.
```

## Reference: relevant files

- `ml/signals/mlb/best_bets_exporter.py` — UNDER_ENABLED flag, UNDER_MIN_SIGNALS, UNDER_SIGNAL_WEIGHTS, rescue logic
- `data_processors/publishing/mlb/mlb_best_bets_exporter.py` — published JSON shape, picks query
- `predictions/mlb/worker.py` — where predictions are generated (both directions)
- `mlb_predictions.signal_best_bets_picks` (BQ) — current production picks
- `mlb_predictions.prediction_accuracy` (BQ) — graded history for HR computation
- `mlb_predictions.shadow_mode_predictions` (BQ) — if it exists, the right place for shadow UNDER rows
- `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md` — the 23-agent investigation from 2026-05-11 with UNDER signal proposals (`book_disagree_under`, `line_drop_under`)
- Memory: `mlb-system.md` (UNDER strategy section, walk-forward results, Session 438b autopsy)

## Context from today's session

This handoff was written after a long session (2026-05-12) that:
- Fixed the wrong-opponent bug (5,094 row backfill)
- Shipped is_day_game feature plumbing
- Added title-case pitcher_name fallback at the worker
- Surfaced voids in best-bets JSON
- Tightened thresholds (MAX_EDGE 2.0→1.5, MAX_PROB_OVER 0.85→0.70)
- Added permanent April-coverage guard in train_regressor_v2.py
- Retimed the umpire scheduler 11:30 AM → 4:30 PM ET
- Synced blacklist tooling with signals.py source of truth
- Wired MLB best-bets click → PitcherModal, season-aware DEFAULT_SPORT, mobile hamburger drawer
- Redesigned BottomNav active state (text-positive bar instead of orange)

None of these touched UNDER directly, but the threshold tightening + April guard reduce the chance of the OVER side over-firing — which makes the lack of UNDERs more visible to users.

The user explicitly noticed "all of the recent picks are overs and no unders." That's the trigger for this investigation.
