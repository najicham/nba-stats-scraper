# Session handoff — review, RUN_NOW audits, slow_pace_under, decay-watch, frame-breaking

**Date:** 2026-06-23 (third+fourth working block of the day; follows
`2026-06-23-SESSION-2-research-HANDOFF.md`)
**Branch:** `offseason-eval-foundation-2026-06`. **3 commits ahead of `origin/main`** (research
tooling + docs only — NOT merged). The season-start fix + b2b shadow WERE merged to main earlier
(commit `5f8eb1cc`) and auto-deployed.

## TL;DR
Continued the off-season arc past the SESSION-2 handoff. A 34-agent review + two RUN_NOW audits +
formal-gate tests + a frame-breaking exploration all converge on one message: **the offline
research is genuinely done.** The model is well-specified (no features to add — triple-confirmed),
the durable UNDER signal slate is finalized, OVER is fragile and fenced, and the single remaining
high-value lever (**true CLV**) is now scoped as a bounded build. Net new edges discovered: a
**new validated UNDER signal (`slow_pace_under`)**; net new dead-ends closed: several.

## What deployed to main this session (via merge `5f8eb1cc`)
- **Season-start fix** (`per_model_pipeline.py` ×5 + `signal_health.py` ×2 → `@season_start`).
  Behavior-preserving for 2025-26; fixes 2026-27 cross-season blending. **Residual TODO:** add
  2026 to `FALLBACK_SEASON_START_DATES` in `shared/config/nba_season_dates.py` once the schedule
  publishes (~Aug-Sep 2026).
- **`b2b_fatigue_under` shadow signal** (registered + `SHADOW_SIGNALS`, NOT in weights → ZERO pick
  impact). Deploys ran: prediction-coordinator/-worker, live-export, phase6-export.

## The 3 unmerged research commits (branch only — no deploy impact)
```
5e1b22d3 research: frame-breaking exploration — model features are DONE; CLV is the next lever
9e948b64 feat(monitoring): OVER decay-watch harness for 2026-27 season resume
97ed2f09 research: slow_pace_under PASSES formal gate (new UNDER signal candidate)
```
(All scripts/docs/monitoring. `bin/` + `scripts/` are not deployed services. Merge at will; no
prod effect.)

## FINALIZED 2026-27 season-open UNDER signal slate (all need live N≥30 + sign-off)
| Signal | Evidence | Action at open |
|---|---|---|
| `b2b_fatigue_under` | 63.2%, 5/5 seasons, formal gate | shadow→active, weight ~2.0 |
| `slow_pace_under` (opp_pace≤99) | 58.7%, 4/4, BH-FDR adj_p=0.039 | shadow→active, weight ~1.5–2.0 |
| `downtrend_under` (slope −1.5..−0.5) | 58.5%, 3/4, adj_p=0.037 — prod predicate MATCHES; removed S471 on N=6 (b2b mistake again) | shadow→active, weight ~1.5 |
| `ft_anomaly_under` (FTA volatility) | 59.9%, 3/3, adj_p=0.037; prod predicate matches | shadow→active, weight ~1.5 |
| `book_disagree_under` | 59.2%, 4/4, adj_p=0.012 — but prod uses `multi_book_line_std` (2023-26 only); my `line_std` is a proxy | verify on multi_book_line_std, then promote |
| `high_line_under` (line≥25) | 59.9% but ⅓ orthogonal; marginal-ROI CI includes 0 | add at **1.0 PAIRING** (not 1.5, not rescue) |
| `under_low_rsc≥2` gate | rsc≥2 robust 5/5; rsc=1 is a 2-season mirage | **KEEP — do not relax** |

*Slate finalized via the shadow-backlog formal gate (`scripts/nba/training/discovery/shadow_backlog_gate.py`,
2026-06-24): of the cache-testable shadow signals, 3 NEW pass (downtrend/ft_anomaly/book_disagree_under),
2 marginal (over_streak_reversion_under, over_trend_over), 4 fail (extended_rest/usage_surge/minutes_load,
mean_reversion). Recurring pattern: the system keeps killing durable UNDER signals on tiny live samples
(b2b_under, now downtrend_under removed on N=6 → actually 58.5% over 5 seasons). The testable boundary
(`coverage_audit.py`): 62/72 cols cross-season; 6 trap cols (game_total/implied_team_total/spread/
star_teammates_out + the all-constant-pre-2025 back_to_back/is_b2b/dnp_rate).*

## Key corrections to carry forward (from the 34-agent review)
- **UNDER-only "+9.4% ROI" → quote as +4.9% ex-2025-26.** Don't let the anomaly carry the narrative.
- **OVER edge≥6 "38.9%" → "unproven, not proven-bad"** (direction robust, magnitude fragile N=18).
- **"58% UNDER / 73% OVER March WF" figure is UNVERIFIED → drop it** (in broad-research doc + memory;
  the production-side March attribution stands on root-cause, not that figure).
- **14d cadence** edge5+ mixed OVER+UNDER → needs a direction-split A/B before adoption (cost-eligible,
  NOT HR-equal).
- **Features: add NONE.** Error-decomposition proved the model well-specified (player/context residual
  R²≈0.004). 3rd independent confirmation; edge is selection/signals.

## Tooling shipped (reusable)
- `bin/monitoring/over_decay_watch.py` — re-grades the 5 fragile OVER signals + raw high-edge OVER
  band on live data (run from ~Dec 2026; presumed-fragile, must clear 58%@N≥30 to KEEP). Smoke-tested.
  Wired into `docs/02-operations/runbooks/season-resume-2026-27.md`.
- `scripts/nba/training/discovery/{high_line_under_overlap, over_scoring_env_gate, runnow_under_audits,
  runnow_worth_trying, error_decomposition, structural_selection_signals}.py` — the session's analyses.

## THE remaining lever — true CLV (scoped, not started)
`docs/08-projects/current/clv-validation/00-SCOPE.md`. Lower-variance validator that would settle
"real edge vs 2025-26 noise" far faster than HR. Closing line is reconstructable from
`nba_raw.odds_api_player_points_props` snapshots (no closing column exists). **Phase 0 = a coverage
feasibility check; STOP if pick→snapshot join <~70%.** Likely a 2024-25+2025-26 result (snapshot
backfill depth unknown). This is the ONLY substantive offline work left.

## DON'Ts (carry-forward)
- Don't relax `cap_to_pre_late_season` or `under_low_rsc≥2`; don't flip cadence without a direction-
  split; don't enable HSE 'active' on thin data; don't `--set-env-vars`; don't `git add -A` (large
  pre-existing dirty tree, unauthored).
- Don't propose model-feature experiments without NEW data — error-decomposition closed that.
- Don't re-run unguarded broad mining — converged; FDR risk. Use the formal gate
  (`scripts/nba/training/discovery/stats_utils.py`) for any new signal.
- Don't trust OVER signals at current weights in 2026-27 — run the decay-watch first.
- Don't project the 63.8% BB record forward. Real breakeven ≈ 53.5%.

## Map of docs created (sessions 3-4)
- `2026-06-23-SESSION-3-gate-and-overlap-RESULT.md` — high_line_under overlap, OVER scoring-env
  gate refuted, RUN_NOW audits, slow_pace_under.
- `2026-06-23-SESSION-4-frame-breaking-RESULT.md` — error-decomposition (features done), price +
  CLV-proxy (dead), CLV feasibility.
- `docs/08-projects/current/clv-validation/00-SCOPE.md` — the CLV build scope.
- This file — consolidated index.
