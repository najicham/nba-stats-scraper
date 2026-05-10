# Session Handoff — 2026-05-09 — Pipeline State Redesign

**Status at end of session:** 8 of 12 phases shipped (A–E + G + H + K-partial). Phase F (backfill execution), I + J (frontend), L (verification) remain. Massive structural improvement: pipeline state is now first-class via two BQ tables; single observability layer; halt mode is no longer inferred ad-hoc.

**Demo readiness:** 3+ weeks runway. The architecture story is presentable today; the live demo needs Cloud Function deployments + notification channel attachment + Phase F backfill execution.

---

## What shipped this session

### Phase A — Bug fixes + scaffolding (commit `543a4be1`)
- `weekly_retrain.cap_to_pre_late_season` only fires for Mar/Apr train_ends. Fixes the latent Oct 2026 retrain failure mode (would have rewrote train_end Feb 2026, 5 mo stale).
- `post_grading_export` split: `BestBetsAllExporter` + `BestBetsRecordExporter` always run (history files), gated only `tonight` re-export on `graded_count > 0`. Fixes `best-bets/all.json` freezing 21 days during halt.
- `aggregator.py` rescue gate raised 5.0 → 6.0 to align with Session 522 OVER block floor.
- `best-bets-config` skill: dropped 3 stale filters (`away_noveg`, `starter_v12_under`, `line_dropped_over`); demoted `opponent_under_block` + `model_profile_would_block` to observation.
- New project directory: `docs/08-projects/current/pipeline-state-redesign-2026-05/`.

### Phase B — halt_state foundation (commit `bbbcefeb`)
- `nba_orchestration.halt_state` table created and seeded with today's rows (NBA halted off_season since 2026-04-19; MLB healthy).
- `halt_state_writer` Gen2 CF (code, requirements, deploy script). Inlines Session 515 edge-collapse logic. Daily 5 AM ET.
- `BaseExporter.halt_envelope(sport, target_date)` — fail-open. Reads halt_state and returns canonical 4-key envelope.
- Wired into `best_bets_all_exporter` + `signal_best_bets_exporter` (both no-predictions and normal paths).

### Phase C — expected_outputs date-grid (commit `909e0498` + bnomqlry7 seed)
- `nba_orchestration.expected_outputs` table + 2 views (`expected_outputs_gaps`, `expected_outputs_coverage`).
- `expected_outputs_planner` Gen2 CF. `OUTPUT_TYPE_REGISTRY` with 21 NBA outputs across 6 phases + 6 MLB outputs across 2 phases (initial scope).
- **Seeded 6,345 rows across 235 dates (Oct 1 2025 → May 23 2026).** All 109 previously-silent missing NBA dates now have 21 EXPECTED rows.

### Phases D + E — Observability + gap detector (commit `5c5b7c6e`)
- `shared/observability/metrics.py`: single `emit_metric()` API + `emit_phase_completion()` convenience. Fail-open.
- `phase_completion_reconciler` CF (every :00, :30): EXPECTED → COMPLETE/EMPTY_OK/DEGRADED.
- `gap_detector` CF (every :15, :45): publishes `nba-backfill-trigger` Pub/Sub messages for stale EXPECTED + DEGRADED rows; FAILED at MAX_BACKFILL_ATTEMPTS=3.
- Pub/Sub topic `projects/nba-props-platform/topics/nba-backfill-trigger` created.

### Phase H — Registry + drift prevention (commit `37adb797`)
- `shared/registry/{signals,filters}.yaml` — 27 signals + 35 filters with status, weight, direction, sessions.
- `shared/registry/loader.py` — `is_known_signal/is_known_filter` API.
- `.pre-commit-hooks/validate_signal_references.py` — wired into `.pre-commit-config.yaml`. Validates CLAUDE.md, .claude/skills/, docs/01-architecture/, docs/02-operations/. Allowlists handoffs + research drafts. Passes clean.

### Phase G — Cloud Monitoring alerts (commit `a3180afa`)
- 3 alert policy YAMLs: `expected-output-overdue`, `halt-state-stale`, `phase-error-rate`.
- `deploy-alert-policies.sh` to create them.
- Notification channel attachment is a one-time UI step.
- Old monitor retirement (8 of 10 CFs) is a follow-up sub-task — wait 7 days clean.

### Phase K — Documentation (in progress, this commit)
- `docs/01-architecture/pipeline-state-redesign.md` — full architecture spec.
- `docs/02-operations/runbooks/halt-mode-operations.md` — operate halt_state.
- `docs/02-operations/runbooks/expected-outputs.md` — operate the date-grid.
- `docs/02-operations/runbooks/backfill-a-date.md` — recover a missing date.
- `docs/02-operations/runbooks/observability-alerts.md` — alert response runbook.
- `CLAUDE.md` — new "Pipeline State" section.
- This handoff doc.

---

## What's pending

### Phase F — Backfill Oct 2025 – Feb 2026 NBA (109 days)
- Service accounts must be created: `halt-state-writer@`, `expected-outputs-planner@`, `phase-completion-reconciler@`, `gap-detector@`.
- `scraper-gap-backfiller` needs refactor to subscribe to `nba-backfill-trigger` Pub/Sub.
- Backfill execution will run in batches; document recovered/lost in `docs/08-projects/current/pipeline-state-redesign-2026-05/03-BACKFILL-MANIFEST.md`.
- Paid sources (`odds_api_*`, `bettingpros_*`, projections) will likely fail; FAILED status documents the loss.
- For bulk backfill, raise `gap_detector.MAX_PUBLISHES_PER_RUN` from 50 → 200 temporarily.

### Phase I — Frontend monitoring (props-web)
- Single GCP uptime check on `playerprops.io/`, `/mlb`, `/nba/best-bets` with content matchers.
- Un-suppress 4 risky Sentry patterns (`Failed to fetch`, `Load failed`, `NetworkError`, `ChunkLoadError`).
- Add stuck-loading watchdog custom Sentry event.
- Demote Vercel cron to heartbeat-only.

### Phase J — Frontend bug fixes (props-web)
- Issue B (banner re-shows) — sessionStorage persistence. Real culprit is Mode 1 `activeBreak.last_game_date` toggle, NOT just Mode 3 (per skeptic agent's correction).
- Issue C (Top Scorers grid) — `VirtualizedGrid:77` `minmax(min(100%, 340px), 1fr)` fixes sub-640px overflow.
- Issue A (Best Bets stuck loading) — already addressed by Phase A `post_grading_export` split. Verify after CF redeploys.

### Phase L — Pre-presentation verification
- Deploy all 4 new CFs (halt_state_writer, expected_outputs_planner, phase_completion_reconciler, gap_detector).
- Build the `nba-pipeline-health` Cloud Monitoring dashboard.
- Attach notification channels to alert policies.
- Run end-to-end synthetic gap test (delete one expected output, watch detector fire, watch backfill complete).
- Update demo script in `04-DEMO-SCRIPT.md`.

---

## Key state to verify before demo

1. `nba_orchestration.halt_state` has a row written within last 24h:
   ```sql
   SELECT * FROM `nba-props-platform.nba_orchestration.halt_state`
   WHERE effective_date = CURRENT_DATE() ORDER BY sport
   ```

2. `nba_orchestration.expected_outputs` has the 6,345 seeded rows + new daily seeds:
   ```sql
   SELECT sport, status, COUNT(*) AS n
   FROM `nba-props-platform.nba_orchestration.expected_outputs`
   GROUP BY sport, status ORDER BY sport, status
   ```

3. The 4 new CFs are deployed and their schedulers are ENABLED.

4. The 3 alert policies exist in Cloud Monitoring and have notification channels.

5. `best-bets/all.json` is being refreshed daily (no longer 21d stale). Once `post_grading_export` next runs (post-MLB grading), this will start.

---

## Carry-forwards from prior session (2026-05-09 morning audit)

- 109-day NBA gap (Oct 21 2025 – Feb 6 2026) acknowledged as recovery target. The new architecture supports the recovery; execution is Phase F.
- `nba_reference.nba_schedule` actually has data through 2026-06-19 (skeptic agent corrected the prior claim).
- `scraper-gap-backfiller` was wrongly flagged as broken; project-level editor IAM works (skeptic correction).
- 49 services still bound to `allUsers` — out of scope for this project; separate IAM cleanup.
