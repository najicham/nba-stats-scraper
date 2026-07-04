# Adjudicated Off-Season Plan — 2026-07-03 → Opening Night (~Oct 21)

Product of the 4-fable-agent path-forward review (verifier + measurement architect + restore
curator + chief adjudicator), which followed the 3-agent next-steps review. **This supersedes
the sequencing sections of `2026-07-03-3-GAMEPLAN.md`** (invariants and P4 signal list unchanged;
P4 gate DEFINITIONS are superseded by the pre-registered two-tier gates below).

Companion artifacts produced by the same review:
- `docs/02-operations/scheduler-restore-manifest-2026.md` — curated verdicts for all 65 deleted
  NBA jobs (58 RESTORE in waves A/B/C, 3 skip-superseded, 2 obsolete, 2 decide) + restore-script spec.
- `docs/08-projects/current/measurement-infrastructure/00-SPEC.md` — the July build (5 components,
  ~6-7 days, zero serve-path impact).

## Verified facts this plan stands on (adversarially re-checked, all five claims held)

1. **Volume:** 189 published BB picks / 89 days (58 pick-days) = 3.4/day, 41% UNDER — flat across
   the season, not a March artifact. Use picks-table grading (189) as the gate denominator
   (agrees 175/175 with prediction_accuracy where joinable; the 14-row delta is join fragility —
   manual_override + renamed models).
2. **Promotion clocks:** at ~0.9 UNDER/day published, 3 of 4 shadow-signal gates cannot reach
   live N≥30 this season (b2b corrected to 9/78 fires — still ~300 days). "P4 converts research
   to EV" was arithmetically false as gated.
3. **model_bb_candidates:** worse than first reported — table only CREATED 2026-03-09
   (CREATE_NEVER + swallowed load errors discarded ~2 months of provenance); DELETE-by-date write
   is last-writer-wins lossy (3/10: 2 rows vs 7 published picks).
4. **Weekly retraining is silently dead:** `weekly-retrain-trigger` deleted in the 94-job purge;
   the CF is HTTP-only (`eventTrigger: None`), no other invoker. CLAUDE.md's "fires every Monday"
   is currently false. `season-resume-2026-27.md` falsely says the job is merely PAUSED.
5. **Canary root cause CORRECTED:** the dead `nba-pipeline-canary` Cloud Run job (fails on
   missing `/app/bin/monitoring/pipeline_canary_queries.py`; image built 2026-04-18) is caused by
   **`.gcloudignore` excluding `bin/`** (any Cloud Build silently omits it) — NOT the setup-script
   heredoc, which pushes to gcr.io while the job pulls from Artifact Registry. Fixing only the
   script would rebuild the wrong image path. The P1.2 `closing_line_capture` canary is dead in
   this image until fixed.

## The sequenced plan

### July (weekly; ~2-4 sessions/wk)

**Week 1 — stop the live bleeding, green the net (~2-3 sessions)**
- Fix `nba-monitoring-alerts` (2 bad queries: `ml_nba.`→`nba_predictions.`,
  `is_correct`→`prediction_correct`) AND move its CF source out of the incident-doc heredoc into
  versioned source. It fires broken SQL every 4h right now.
- Fix the canary image THE RIGHT WAY: `.gcloudignore` carve-out (or local docker build) with
  `Dockerfile.canary`, push to the **AR path the job uses**, verify one clean execution. Do not
  resume its paused triggers until green.
- Pause `master-controller-hourly` (resume paired with `execute-workflows` in Oct).
- Green the test suite: 57 stale tests (Session-522 floor fixtures, `_safe_float` move,
  TIER_CONFIG drift) + `pytest.ini` addopts/pytest-cov. It's the only regression net in front of
  auto-deploy-on-push, and July edits the highest-blast-radius code.
- Bookkeeping: mark P1.6 DONE (no-op — jobs exist paused); P1.3 scraper fix DONE (`7d1a3f9b`).

**Week 2 — measurement stream, part 1**
- Spec Component 2: fix `model_bb_candidates` (scoped upsert + type fixes + `export_run_at` +
  persist `book_count` — makes the deferred P1.4 decision queryable in December).
- Spec Component 1: unconditional shadow-tag persistence + `v_bb_candidate_signal_stream` view.
- Owner sign-off: write-path-only deploy, halt active, zero pick impact.

**Week 3 — tracker, gates, paper stakes**
- Component 3: pre-register the two-tier gates (registry YAML + PREREG doc). **Owner sign-off.**
- Component 4: promotion tracker (`signal_weight_report.py` upgrade).
- Component 5: counterfactual paper stakes + persist `win_prob_at_pick`/`calibrator_version`.
- Ultra-tier freeze written into config/docs. Reconcile 175-vs-189 note in the tracker.

**Week 4 — calibrator ship + remaining P1 engineering**
- Ship calibrator pkls to the phase6 runtime (scikit-learn/joblib in requirements-lock, absolute
  CALIBRATOR_DIR, load-path unit test). Consumption stays dormant. **Sign-off.**
- P1.3 remainder: value-sanity canaries in data_source_health_canary; one manual tracking-scraper
  run to confirm drives ≠ 0.0 (its daily scheduler is deleted — verification won't happen passively).
- P1.5 churn guardrail (pre-commit hook on ALGORITHM_VERSION + runtime metric on
  version-change-during-TIGHT).
- Buffer; optionally ONE `matchup_pace_squeeze_under` gate pass (P1.7). Skip `whole_line ×
  high_line` (parent can't reach N).

### August (~6-8 sessions)
1. Build `scripts/nba_offseason_restore_jobs.sh` against the curated manifest (the curation is
   DONE — see the manifest doc). **Owner sign-off on verdicts, esp. the 2 DECIDEs.**
2. Consolidate the three overlapping checklists into `season-resume-2026-27.md` with a T-minus
   schedule; FIX its false "weekly-retrain-trigger PAUSED" claim; fold in the two orphan P3 items
   (fleet diversity; calibrator pkls — done in July).
3. When the official schedule publishes: update the provisional 2026-10-21 in
   `shared/config/nba_season_dates.py` AND re-sync the 6 vendored copies under
   `orchestration/cloud_functions/*/shared/config/`.
4. Fleet-diversity prep: choose the non-v12_noveg family, dry-run training + governance gates,
   document the enable path (`validate_fleet_diversity.py`).
5. Phase 4 latency: TIMEBOX 1 session (BQ job stats / revision compare; pre-regression image
   likely AR-cleaned → rollback off the table; diagnose or accept-and-monitor).
6. Fix `deploy_phase6_scheduler.sh --delete` missing `phase6-clv-reexport-late`.

### September — deliberately light (buffer)
- Late Sept: run the restore script `--paused` (waves A/B/C created paused), deploy
  closing-lines + phase6 schedulers paused, re-verify canary image.
- Train + register the diverse fleet candidate (validates registry/plumbing/governance end-to-end).
- Nothing new starts in September.

### October (pre-open → Oct 21)
- P3 dress rehearsal on preseason games: DK live-format smoke, warmup guard fires, CLV snapshot
  density (mbt < 45), 4:30 vs morning `dk_line_move_direction` differ, `win_prob` populates,
  Odds API quota headroom from the new header logging.
- Resume schedulers per manifest waves (per-job `describe` verification). **Sign-off.**
- Enable the diverse model after governance shadow on preseason traffic. **Sign-off.**
- Confirm auto-halt healthy; run the runbook's first-week shadow-signal SQL pack in game week 1.
- **Expectations memo (write pre-open, owner-acknowledged):** Oct-Nov = accumulation (~1-3
  picks/day UNDER-dominant, ~25-40 total by Dec 1, ZERO promotions resolved); Dec-Jan = first
  stream-level promotion decisions; Feb+ = sizing null-confirmation query. No floor/halt/gate
  touches before Dec 1 absent a bug.

## Rulings (adjudicated; a-g)

- **a. Sequence:** monitors → tests → measurement stream → tracker/gates (July); manifest script
  (Aug — curation already done); Sept = slack. The reports weren't in substantive conflict.
- **b. Two-tier gates: ADOPT WITH CONSTRAINTS** — pre-registered in July before any live row;
  primary evidence = quasi-exchangeable stratum only (published + Class-A capacity/structural
  blocks; filter-blocked rows are sensitivity-only); non-contradiction check vs published subset
  (N≥10); HR thresholds unchanged; stream N≥100; November excluded; every promotion individually
  owner-signed. Re-check published clocks ~Nov 15 (if 10+ picks/day 60%+ UNDER, they compress 4x).
- **c. P1.4 book_count: LEAVE until after open.** Don't ship, don't replay against anomaly-vintage
  data, don't delete the dead guard. DO persist book_count in Week-2 provenance so December's
  decision is a query.
- **d. Ultra freeze: ENDORSED** (anomaly-vintage OVER-edge criteria contradicted by the honest
  calibrator; freeze public-exposure clock, re-prove from zero, re-derive UNDER-side).
  **P2 reframe: ENDORSED** ("+1-1.5pp ROI" retired; paper stakes make it a February query).
  **Calibrator pkls: ship July** (dormant annotation; live verification stays in October).
- **e. Tests: Week 1**, precisely because there is no CI gate. Do NOT build a CI gate this
  off-season (churn); green suite + run-before-push discipline suffices.
- **f. Missed items now carried:** fleet-diversity governance tail (Aug prep → Sept train →
  preseason shadow → pre-open enable); the stale runbook claim on weekly-retrain; season-date
  vendored copies ×6; the first-week shadow-signal SQL pack; grading-service has no Cloud Build
  trigger (runbook note, don't build).
- **g. CUT / DEFER past open:** P1.4 ship (→ Dec, data-driven); P2 as a decision (→ ~Feb 2027);
  14-day retrain-cadence A/B (CUT for season open — confounded during halt-release + aggressive
  retraining; prize is cost not HR); ultra public exposure (frozen); `whole_line × high_line`
  combo (parent can't reach N); all ten-agent Tier-3 research; CI test gate; Pinnacle; news
  scraper; alt-market fork; any OVER research; any new backtest program.

## Top 3 risks

1. **Restore-manifest verdict error** — one wrong skip (weekly-retrain, decay-detection,
   execute-workflows, props kicks) = the 2025-26 root-cause pattern again. Mitigations: paused
   creates in Sept, October rehearsal exercises the chain, week-1 verification pack.
2. **Two-tier-gate contamination → bad December promotion.** Mitigations: July pre-registration,
   Class-B rows sensitivity-only, published non-contradiction check, per-promotion sign-off,
   nothing before Dec 1.
3. **Thin-output impatience at season open** (~1-3 picks/day, possibly zero for weeks while the
   halt holds) — the documented March killer. Mitigations: the expectations memo, the P1.5
   guardrail, the halt releases itself.

**Bottom line:** July = fix what's bleeding, green the net, build the un-backfillable measurement
stream, pre-register the gates. August = restore script + schedule dates + fleet prep. September
= slack, on purpose. October = rehearse and flip runbook switches only. Nothing that changes live
pick behavior ships after Oct 1 except pre-registered runbook items; nothing promotes before December.
