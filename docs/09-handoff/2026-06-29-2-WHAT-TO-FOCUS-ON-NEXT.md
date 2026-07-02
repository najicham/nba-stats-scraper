# Handoff — What to focus on next (strategic orientation)

**Date:** 2026-06-29 · **Type:** Decision/orientation handoff · **Season state:** OFF-SEASON (system halted `off_season`; no live picks until ~Oct 2026)

## Purpose

Decide where to point effort next. This is a *priorities* question, not a task list — the honest
situation is that the offline-research well is largely dry, so the next chat should pick a direction
**with the owner** rather than invent busywork. Read this, then ask the owner the question at the bottom.

## Where we actually are

- **Mission unchanged:** improve the NBA player-points prediction system (profitable over/under picks).
  The points engine is the asset; the 52-agent strategy verdict was "improve the core, don't expand"
  (all new markets/sports are skip).
- **The research program is CONVERGED.** Many independent waves (see MEMORY.md "Strategic Direction")
  all landed on the same place:
  - **Model features are exhausted.** Held-out R² predicting the model's residual from player/context
    features ≈ +0.004 ≈ 0, confirmed 3 independent ways. **Adding model features cannot help.** The
    edge lives on the **selection / confidence surface**, not point accuracy.
  - **What works (protect this):** UNDER + edge + signals. UNDER edge≥6 ≈ 61% cross-season. **OVER is a
    2025-26 scoring anomaly** — never assume OVER is profitable (high-edge OVER ≈ 39% in the 4 prior
    seasons). Edge-based auto-halt is the vindicated collapse guard.
  - Cache-mining is capped: real best-bets picks only exist from 2026-01-09; pre-2026 needs an edge≥3
    proxy. We've squeezed what this dataset can give.
- **So the remaining value is LIVE EXECUTION, not more backtesting.** Don't open another cache-mining
  wave expecting a new edge.

## DON'T re-litigate (settled — see MEMORY.md)

New point-model features; GBDT/feature-set/algo model diversity (clones); MQ/quantile head; the
retrain-cadence cap; "edge5+ money zone" (it's UNDER-only); NBA feature-leak audit (clean); production
training-leakage claims (false, fixed in `60279b20`); MLB (no edge, externally corroborated — stay
halted, info-product only).

## Staged & inert, waiting for season-open (none affect picks today)

All shadow / zero-impact. They need a clean **live** sample in 2026-27 before any can be promoted:
- `b2b_fatigue_under` — merged to main (shadow). 5-season 63.2%, formal gate PASS.
- `national_tv_under` — **NEW this session, on branch `narrative-national-tv-under-shadow` (NOT merged).**
  54.7% 5-season, additive over high-line. See `2026-06-29-narrative-proxies-and-national-tv-under.md`.
- OVER-layer demotions staged to SHADOW (fast_pace_over, cold_3pt_over, line_rising_over,
  book_disagree_over, b2b_boost_over) — inert during halt; each must earn weight back live.
- Not-yet-wired ideas: CLV `line_converging_under`, `low_variance_under_block`, same-game co-directional
  Kelly haircut.

## The real open levers (ranked — pick WITH the owner)

1. **March-2026 production-collapse diagnostic — the strongest "improve the prediction system" thread.**
   Production BB hit **46.7% in March** while the *clean* walk-forward model held up. Memory's verdict:
   the collapse is **PRODUCTION-side** (selection / signals / live-market), **not the model** — and it
   is NOT fully root-caused. (Caveat: the specific "UNDER 58% / OVER 73% March WF" figures are
   UNVERIFIED; the production-side conclusion stands, the numbers don't.) If we find the production-side
   cause (a selection bug, a stale/leaky live signal, a market-regime gate that misfired), that's a
   **direct, durable pick-quality win** — and it's offline-diagnosable now. Best ROI of the four.

2. **Season-open live-execution playbook.** Make sure the staged shadow items actually fire and can be
   promoted cleanly when games return: merge `national_tv_under` before October; verify every shadow
   signal fires on real picks; lock the promotion gates (e.g. live N≥30 at HR≥55-58%); wire the OVER
   decay-watch so the demoted OVER signals re-earn weight only on evidence. Low-risk, high-leverage
   prep; turns "converged research" into actual improvement when the season opens.

3. **Narrative frontier — forward-collection (the one genuinely NEW modality).** Phase 0/1 done this
   session: backfillable proxies are dead, and the "bad-press/benching" news modality is NOT
   backfillable → forward-collection only. Pursue ONLY if the owner commits to a multi-season build.
   Cheapest start: news PoC = `nbainjuries` package (injury-report snapshots) + ESPN hidden-API probe.
   High effort, payoff deferred to 2027+.

4. **Accept off-season idle / maintenance.** Legitimate. No live data until ~October; deployment-drift
   checks + monitoring are enough. Reconvene at season-open.

## Recommended first move for the new chat

Put the choice to the owner plainly: **"The offline research is converged — adding model features
won't help, the edge is in selection/signals. The highest-value prediction-improvement thread left is
diagnosing why production underperformed the clean model in March (a production-side bug, not the
model). Want me to spend a session on that, prep the season-open live-execution playbook, start the
narrative news build, or just idle until the season?"**

If forced to pick one without the owner: **option 1 (March production-collapse diagnostic)** — it is the
only thread that can still improve live pick quality from offline work, and it's not done.

## Open decision carried over

`national_tv_under` is on a branch, unmerged. No rush (off-season = zero data collected until October).
Merge before season-open so live-tracking auto-starts; until then it changes nothing.
