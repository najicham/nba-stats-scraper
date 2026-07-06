# Session Handoff — 2026-07-05 (Session 4, off-season)

**Branch:** `main`. **System state:** OFF-SEASON, halted; opener ~Oct 21 2026. No serve-path code
changed this session. Two pieces of work: (1) closed the grading-service deploy/trigger loop,
(2) ran an 8-agent future-prediction ideation and wrote a backlog doc.

## 1. nba-grading-service drift + missing trigger — CLOSED

- **Deployed** `nba-grading-service` → now on HEAD (`7a561219`, includes the Session-3
  `distributed_lock` fix `372bd11d`). `check-deployment-drift.sh` reads "All services up to date."
- **Root cause (not what the S3 handoff assumed):** the trigger didn't "fail to fire" — **it never
  existed.** The service was created 2026-02-01 with a manual `deploy-service.sh` path but no Cloud
  Build trigger. Audit logs: zero `DeleteBuildTrigger` for it in 400 days; the off-season purge was
  Cloud *Scheduler* jobs, a different resource. So it had silently accrued drift on every `shared/`
  change since Feb 1.
- **Durable fix:** created `deploy-nba-grading-service` trigger (id `0ec29941`), mirroring
  `deploy-prediction-worker` — `cloudbuild.yaml`, `_SERVICE=nba-grading-service`,
  `_DOCKERFILE=data_processors/grading/nba/Dockerfile`, `_MIN_INSTANCES=0`, branch `^main$`,
  `includedFiles = data_processors/grading/**, predictions/shared/**, shared/**, cloudbuild.yaml`.
  Enabled; NOT test-fired (already on HEAD) — fires on next matching push. CLAUDE.md's auto-deploy
  list is now accurate. Memory: `grading-service-trigger-created-2026-07-05`.

## 2. Future-prediction ideation — 8-agent backlog

Owner asked to brainstorm what ELSE we can predict + what angles, then persist for a future session.
8 parallel agents, one lens each (new player targets, team/game targets, novel data sources, market
microstructure/CLV, player-state/minutes, modeling technique, bet products, adjacent/competitive),
all grounded in the established walls (R²≈0, UNDER-durable, CLV-lever, points-lock, small-N/leakage).

**Backlog doc:** `docs/08-projects/current/future-prediction-ideas/00-IDEAS-BACKLOG.md` — a menu of
hypotheses with feasibility reads + suggested sequence. Nothing built.

**Tier A (backtestable NOW on stored data, no serve-path touch):**
1. Use stored `over_price`/`under_price` for selection (no-vig prob edge + best-number capture) —
   never used to date; all signals are line-value based. THE standout quick win.
2. New targets Rebounds/Assists/3PM UNDER — BettingPros lines backfillable to 2021, actuals in
   `player_game_summary`, lower-variance than points.
3. Distributional tail-prob bet using the p25/p50/p75 the MultiQuantile fleet already serves.
4. Travel/schedule-density feature (continuous `b2b_fatigue_under`, fully backfillable).

**Tier B (build now, gate live):** minutes model + injury-return/shortfall UNDER; confidence
meta-model (learned P(win)); portfolio correlation-aware sizing (N-blocked to ~mid-2026-27);
injury-report timing/velocity (forward-collect). **Tier C:** WNBA thin-fork + Summer League sensor;
referee/derivative-total UNDERs; predict-the-close; operationalize CLV discipline.

**Dead ends flagged in the doc:** steals/blocks, main-market spread/total, altitude, NCAA/international
(data wall), injury-news front-running (latency wall), promo grind (non-scalable), OVER-stacked SGPs.

## Do NOT (unchanged)
Restore/enable weekly-retrain or decay-detection before season open; resume any paused trigger;
attempt a full-suite green as a gate; front-load measurement-infra C4/C5; pause master-controller;
backfill lost model_bb_candidates provenance. **Nothing in the ideas backlog changes live behavior
until explicitly built, validated, and signed off.**

## Next worklist (unchanged from S3, none urgent)
1. Broader test-suite noise (cross-suite pollution + 4 collection-order files) — NOT a gate.
2. Measurement-infra C4/C5 — Sept, do not front-load.
3. October dress-rehearsal — blocked until picks flow.
4. (New, optional) Start on any Tier-A idea from the backlog — all off-season-safe, backtest-only.
