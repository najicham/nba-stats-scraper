# MLB UNDER shadow rollout

**Date opened:** 2026-05-12
**Investigation:** 6 parallel agents (historical perf, shadow design, model bias, signal coverage, filter coverage, operations)
**Status:** Plan approved, pre-work pending — see `01-PLAN.md`
**Predecessor handoffs:**
- `docs/09-handoff/2026-05-12-mlb-under-disabled-investigation.md`
- `docs/09-handoff/2026-05-12-mlb-modal-polish-vs-nba.md`

## Headline

MLB best bets ships OVER-only today. `MLB_UNDER_ENABLED=false` (default) blocks every UNDER pick at the direction filter. User noticed "all of the recent picks are overs and no unders" and asked for a rigorous review.

**6-agent investigation produced one defensible answer: ship UNDER in shadow mode for 45 days, BUT only after fixing 4 broken pre-conditions.** Flipping the flag today would write zero useful shadow data because the UNDER signal pipeline is hollow and the bookkeeping tables hardcode OVER.

## Why now

- Sessions 469 / handoff 2026-05-12 left UNDER disabled "until OVER HR >= 58% and UNDER walk-forward looks better"
- OVER HR is 60.3% live (38-25, N=63) — gate condition met
- UNDER walk-forward numbers in memory (52.4% / 48.1% / -6.8% ROI) are **not auditable** — they live in script JSON output, never written to BQ
- Live UNDER 2026 data (the only auditable history): 53.4% raw (N=204), but May trending sharply down (40.9% in May, 0/3 week of May 11)

## Critical findings

- **Agent 1**: Live 2026 UNDER is in regime collapse RIGHT NOW (40.9% HR May, 0/3 most recent week). No N>=100 subset clears 56% HR. Walk-forward claims unreproducible from BQ. → Rules out shipping live with filters.
- **Agent 3**: OVER bias is structural — RMSE loss function + asymmetric K distribution. On the *picked subset*, OVER bias is +0.19 K, UNDER bias is **-0.45 K**. UNDER selection systematically under-predicts.
- **Agent 4**: UNDER signal pipeline is hollow. `UNDER_MIN_SIGNALS=3` is **structurally unreachable** today — only 2 of 5 weighted signals actually fire.
- **Agent 5**: Zero UNDER-targeted negative filters exist. Worst UNDER archetypes (high-line + elite K/9 in summer) collapsed cross-season 96.9% → 65.2%.

Full agent findings: `02-AGENT-FINDINGS.md`.

## Decision

User chose (a): shadow rollout with pre-work, shared 5/day quota, ranking redesigned from scratch using shadow data. See `03-DECISIONS.md`.

## Status

| Phase | Status | Owner |
|---|---|---|
| Phase 0 — Pre-work (signals, filters, bookkeeping) | NOT STARTED | TBD |
| Phase 1 — Shadow rollout (table, monitor, backfill) | NOT STARTED | TBD |
| Phase 2 — Graduation gate decision | BLOCKED on Phase 1 + 45d data | TBD |
| Phase 3 — Quantile-loss retrain (deferred) | DEFERRED | TBD |

## Open questions (not blockers — to revisit at graduation)

- Should we tighten `UNDER_MIN_SIGNALS` from 3 to 4 once 5 weighted signals fire?
- Does the shadow-data ranking discovery (`05-RANKING-REDESIGN.md` placeholder) need a separate `feature_scanner.py` analogue for MLB, or can we adapt NBA's?
- Quantile-loss retrain (Agent 3) — should it happen before or after shadow promotion? Currently deferred until shadow has 30d.

## Files in this project

- `00-OVERVIEW.md` — this file
- `01-PLAN.md` — sequenced 7-step plan with file paths and effort estimates
- `02-AGENT-FINDINGS.md` — distilled findings from all 6 review agents
- `03-DECISIONS.md` — user decisions on path/quota/ranking + rationale
- `04-RUNBOOK.md` — promotion + rollback runbook (move to `docs/02-operations/runbooks/` at ship time)
- `05-RANKING-REDESIGN.md` — placeholder for the shadow-data-driven ranker design (populated after 30d of shadow data)
- `06-WALK-FORWARD-AUDITABILITY.md` — proposal for `mlb_predictions.walk_forward_results` BQ table (D6 follow-up, addresses Agent 1 unreproducibility complaint)
