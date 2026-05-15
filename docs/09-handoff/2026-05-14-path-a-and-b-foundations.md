# Session Handoff — 2026-05-14 — Path A + Path B foundations

**Primary work this session:** big bite of "stop the silent failures" (Path A) plus the first two governance fixes from Path B. Also stood up the NBA snapshot CF (Path C kicker). Started with five ops follow-ups from the 2026-05-13 doc + a 20-agent system survey, and the system survey is what drove the path naming below.

**Source-of-truth predecessors (still valid):**
- `docs/09-handoff/2026-05-14-modal-polish-and-zero-picks.md` — frontend modal polish + the 5 ops follow-ups (all closed below)
- `docs/09-handoff/2026-05-13-mlb-grading-and-publish-bugs.md` — MLB grading fix verified live

## TL;DR

1. **All 5 carry-over ops follow-ups closed** (trigger config, MLB snapshot scheduler, BB grading backfill, mlb_pitcher_stats clarification, props-web lint cleanup partial).
2. **Path A — silent failures — fully landed:**
   - `emit_phase_completion()` wired into 7 paths (NBA + MLB Phase 3 + Phase 4, Phase 5 worker FAILED-only, Phase 6 CF, grading CF, Phase 2 raw)
   - Content guard + `safe_export` on `best_bets_all_exporter` (NBA `all.json` history fallback) AND `signal_best_bets_exporter` (date file)
   - Scoped DELETE zero-pick shadow row fix in `signal_best_bets_exporter`
   - `mlb_weather` scraper now hard-fails on missing `OPENWEATHERMAP_API_KEY` instead of silently writing 75 °F mock
   - 9 monitoring scripts swapped from dead `bdl_player_boxscores` to live `nbac_gamebook_player_stats`; 3 BDL-only scripts marked DEPRECATED
   - Signal registry YAML synced 27 → 73 entries + pre-commit hook now catches code→YAML drift in both directions
   - `grading-low-coverage-alert.yaml` stub replaced with a real alert wired to the new `phase_completion{phase=phase5b_grading}` metric
   - Hot-path `insert_rows_json` failures in `run_history`, `coordinator`, `env_monitor` now emit `bq_streaming_insert_failed` instead of logging-and-discarding
3. **Path B Week 1+2 shipped:**
   - `catboost_v9` un-hardcoded in 3 places (`signal_calculator.PRIMARY_ALERT_MODEL` env-overridable, `quick_retrain._detect_best_eval_system_id` raises instead of falling back, `worker.validate_ml_model_availability()` gated behind `ENABLE_LEGACY_V8`)
   - `min_hr_edge5 = 55.0` governance gate added to `weekly_retrain` CF — the money-zone gate Session 487 LGBM-clone fleet collapse would have failed
   - `under_low_rsc` added to `ELIGIBLE_FOR_AUTO_DEMOTE` with per-filter `MIN_PICKS_7D=30` override (closes the documented 12-day UNDER drought failure mode)
   - `friday_over_block` HSE rescue carve-out at edge ≥ 7.0 (HSE OVER is 100% BB HR historically)
4. **Path C started:**
   - NBA snapshot CF (`cloud_functions/nba_snapshot_daily`) shipped + scheduler + IAM + smoke-tested. 5 NBA tables snapshotted to `nba_predictions_backups` (us-west2); `prediction_accuracy` = 478,159 rows, `ml_feature_store_v2` = 147,340 rows. 30-day expiry, 11 AM ET daily.
   - `cloudbuild-precompute.yaml` rewritten with `gcloud run deploy` + `update-traffic --to-latest` (Phase 4 was silently running stale code on every push)
   - MLB scheduler month range `3-10` → `2-11` to cover UTC/ET timezone edges (Mar 31 11 PM ET = Apr 1 UTC; Oct 31 11 PM ET = Nov 1 UTC)
5. **Documentation reconciled:** CLAUDE.md OVER edge floor updated from 5.0 → 6.0 (regime-adaptive) to match MEMORY.md.

## What landed (files touched)

### Path A — silent failures
| File | Change |
|---|---|
| `data_processors/analytics/main_analytics_service.py` | emit_phase_completion at 3 return points + exception; import added |
| `data_processors/precompute/main_precompute_service.py` | Same pattern |
| `data_processors/analytics/mlb/main_mlb_analytics_service.py` | Same pattern; review-fixed to distinguish `success_count==0` → FAILED from partial → DEGRADED |
| `data_processors/precompute/mlb/main_mlb_precompute_service.py` | Same pattern with the same FAILED/DEGRADED fix |
| `orchestration/cloud_functions/phase6_export/main.py` | emit at result-aggregation point + exception. `phase='phase6_publish'` (matches reconciler canonical, was `phase6_publishing`) |
| `data_processors/publishing/best_bets_all_exporter.py` | `validate_content()` override + `safe_export()` swap + guard env `BB_ALL_GUARD_ENABLED`. Halt bypass scoped to canonical reasons only (off_season/edge_collapse/fleet_blocked) |
| `data_processors/publishing/signal_best_bets_exporter.py` | `validate_content()` override (schema check + compare-to-last-good) + guard env `SBB_GUARD_ENABLED`; zero-pick re-export now distinguishes halt-active (DELETE shadow rows) from regression (preserve rows + emit metric) |
| `scrapers/mlb/external/mlb_weather.py` | Raises RuntimeError when `OPENWEATHERMAP_API_KEY` unset; mock path opt-in via `MLB_WEATHER_ALLOW_MOCK=true` for local dev |
| `bin/monitoring/daily_health_check.sh` + 6 other monitoring scripts | `bdl_player_boxscores` → `nbac_gamebook_player_stats` swap; fixed bogus `nbac_gamebook_player_boxscores` reference (table never existed); `min > 0` → `player_status='active' AND minutes_decimal > 0` |
| `bin/monitoring/cross_source_validator.py`, `bdl_quality_alert.py`, `check_bdl_data_quality.py` | DEPRECATED docstring banner — do not schedule; live tables they query are empty |
| `shared/registry/signals.yaml` | 46 entries appended (auto-generated from `ml/signals/*.py` tag declarations); 4 BASE signals reclassified `shadow→active w=0`; `velocity_drift_under` skipped via NOT_TAGS |
| `.pre-commit-hooks/validate_signal_references.py` | `check_code_vs_registry_parity()` walks `ml/signals/*.py` and flags any `tag = "..."` missing from YAML — fails CI on future drift |
| `data_processors/raw/main_processor_service.py` | `_emit_phase2_completion()` helper called at every return point + exception paths; derives output_type from GCS object path; detects sport from path prefix |
| `orchestration/cloud_functions/grading/main.py` | emit at status-derivation point + exception. Maps `success/skipped/auto_heal_pending/auto_heal_failed/failed` → `COMPLETE/EMPTY_OK/RUNNING/FAILED/FAILED` |
| `predictions/worker/worker.py` | emit FAILED on the 500 path of `/predict` (hot-path-safe — success already observable via `predictions-ready` Pub/Sub topic) |
| `predictions/coordinator/run_history.py`, `predictions/coordinator/coordinator.py`, `predictions/worker/env_monitor.py` | emit `bq_streaming_insert_failed` on insert error (preserves streaming-insert design intent per existing comments while making failures observable) |
| `monitoring/alert-policies/grading-low-coverage-alert.yaml` | Replaced no-op stub with real policy: filters `phase_completion{phase=phase5b_grading}`, alerts when 2h mean < 0.7 |

### Path B — fleet + governance
| File | Change |
|---|---|
| `predictions/coordinator/signal_calculator.py` | `PRIMARY_ALERT_MODEL` from env, default `catboost_v12` (was hardcoded `catboost_v9`) |
| `ml/experiments/quick_retrain.py` | `_detect_best_eval_system_id` raises on empty window instead of `catboost_v9` fallback |
| `predictions/worker/worker.py` | V8 startup validate gated behind `ENABLE_LEGACY_V8=true`; default skip with INFO log |
| `orchestration/cloud_functions/weekly_retrain/main.py` | `min_hr_edge5 = 55.0` + `min_n_edge5 = 8` added to `GOVERNANCE`; gate 4 added to `validate_against_governance()` |
| `orchestration/cloud_functions/filter_counterfactual_evaluator/main.py` | `under_low_rsc` added to `ELIGIBLE_FOR_AUTO_DEMOTE`; new `PER_FILTER_MIN_PICKS_7D` override (30 for `under_low_rsc`); post-filter in `main()` after the SQL query |
| `ml/signals/aggregator.py` | `friday_over_block` HSE rescue carve-out at edge ≥ 7.0; new `friday_over_block_hse_exempt` counter for observability |

### Path C — backups + infra hygiene
| File | Change |
|---|---|
| `cloud_functions/nba_snapshot_daily/{main.py,requirements.txt}` | New CF, mirror of `mlb_snapshot_daily/`. Smoke-tested 2026-05-15 03:46 UTC. |
| `bin/operations/deploy_nba_snapshot_daily.sh` | New deploy script with the project-flag fix learned from the MLB deploy (don't trust `gcloud config get-value project`) |
| BQ: `nba-props-platform:nba_predictions_backups` | New dataset in `us-west2` (NOT `US` — must match source `nba_predictions` location for snapshots); OWNER granted to `756957797294-compute@developer` SA |
| `cloudbuild-precompute.yaml` | Added `gcloud run deploy` + `update-traffic --to-latest` step. Previously the file only built+pushed; Phase 4 silently ran stale code on every push. |
| `deployment/scheduler/mlb/monitoring-schedules.yaml`, `validator-schedules.yaml` | Month range `3-10` → `2-11` (7 entries) + header comment explaining UTC/ET edge case |

### Docs + memory
| File | Change |
|---|---|
| `CLAUDE.md:370` | Edge floor 5.0 → 6.0 (regime-adaptive 7.0 in TIGHT markets) |

## What's verified working

- **MLB snapshot CF** end-to-end smoke-tested. 2026-05-14 02:25:32 UTC snapshot landed for all 3 tables.
- **NBA snapshot CF** end-to-end smoke-tested. 2026-05-15 03:46 UTC: 5 tables snapshotted (`prediction_accuracy`=478,159 rows; `signal_best_bets_picks`=203; `best_bets_published_picks`=89; `player_prop_predictions`=615,014; `ml_feature_store_v2`=147,340). One false start required dataset recreation in `us-west2` (was created in `US` — snapshots fail across regions).
- **Phase 2/3/4 services compile** cleanly (Python syntax check passed for all 6 modified `main_*_service.py` + worker).
- **Signal registry loads** 73 signals (28 active + 45 shadow + 6 base equivalent). Pre-commit hook reports zero drift.
- **Worker startup** still imports clean with the V8 gate (`ENABLE_LEGACY_V8` not set → skip with INFO).
- **`filter_counterfactual_evaluator` + `aggregator`** compile clean after Week 2 changes.
- **`weekly_retrain` CF** compiles with the new edge-5 gate (gate 4 in `validate_against_governance`).
- **props-web** TypeScript clean, 558/561 tests passing (3 pre-existing VirtualizedGrid JSDOM failures unrelated to this session).

## What's NOT yet verified

- **`min_hr_edge5` gate** — no live retrain since deploy; the next Monday `weekly-retrain` CF run is the first real test. Walk-forward replay against historical Session 487 LGBM-clone snapshots is a TODO before that fires.
- **Content guards** — no degraded scenario to test against. The guards are wired but their first real fire will be the next regression. `BB_ALL_GUARD_ENABLED=false` / `SBB_GUARD_ENABLED=false` are the emergency kill-switches.
- **`emit_phase_completion` end-to-end** — the metric writes are wired but I haven't pulled Cloud Monitoring to confirm the time-series shows up. Next Phase 3 run will populate.
- **`grading-low-coverage-alert.yaml`** — the YAML is checked in but not deployed. Deploy via `gcloud alpha monitoring policies create --policy-from-file=monitoring/alert-policies/grading-low-coverage-alert.yaml --project=nba-props-platform`.
- **`cloudbuild-precompute.yaml` deploy step** — checked in but won't fire until the next push to main that touches Phase 4 paths. First deploy after merge is the real test.
- **`under_low_rsc` per-filter override** — wired in CF Python but no live `filter_counterfactual_evaluator` run yet; the daily 11:30 AM ET CF will exercise it tomorrow.
- **HSE Friday rescue carve-out** — code is live but no Friday game window between deploy and next session. First test is whichever Friday has an HSE + edge≥7 OVER candidate.

## Path A — fully landed (deferred items now done in-session)

All Path A items from the original survey are now in. Specifically:

- ✅ Phase 2 raw `emit_phase_completion` (`_emit_phase2_completion()` helper at every return + exception)
- ✅ Phase 5 worker `emit_phase_completion` (FAILED-only on 500 path; hot-path safe)
- ✅ `grading-low-coverage-alert.yaml` real policy
- ✅ 3 single-row streamers now emit `bq_streaming_insert_failed` on failure (preserves streaming design intent + makes failures observable)

## Path B — what's left (2 weeks remaining after Week 2 done in-session)

| Week | Items |
|---|---|
| Week 2 (DONE) | ✅ `under_low_rsc` auto-demote eligibility; ✅ `friday_over_block` HSE rescue exemption. **TODO this week:** 2 obs filters with no CF HR (`unreliable_over_low_mins_obs`, `unreliable_under_flat_trend_obs`) — audit + decide promote-or-remove |
| Week 3 | Regime-adaptive `OVER_QUALITY_WEIGHT` (currently 0.3 — edge dominates noisy 1-2pt signal during TIGHT regimes); player dedup conflict tagging (`contending_models` field) — needs `signal_best_bets_picks` schema add |
| Week 4 | MLB auto-retrain CF (clone NBA `weekly_retrain` structure); VSiN sharp_money threshold refresh (book-count-aware after sharp_consensus_under Session 515 reversion) |

**RISK FLAG carried forward from Path B review agent:** the 4 "graduate shadow signals" candidates (`projection_consensus_under`, `dvp_favorable_over`, `predicted_pace_over`, `over_trend_over`) have raw-signal HR numbers cited in aggregator comments that may be N=1 BB-level samples (same pattern that bit `sharp_consensus_under` Session 515). Do NOT flip status to `active` without running a BB-level walk-forward join first:

```sql
SELECT signal_tag, COUNT(*) n, AVG(CAST(prediction_correct AS INT64)) hr
FROM `nba_predictions.signal_best_bets_picks` bb
CROSS JOIN UNNEST(bb.signal_tags) signal_tag
JOIN `nba_predictions.prediction_accuracy` pa
  ON pa.pitcher_lookup = bb.pitcher_lookup  -- (player_lookup for NBA)
  AND pa.game_date = bb.game_date
  AND pa.recommendation = bb.recommendation
  AND pa.line_value = bb.line_value
WHERE signal_tag IN ('projection_consensus_under','dvp_favorable_over',
                     'predicted_pace_over','over_trend_over')
  AND bb.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY 1
```

Need N ≥ 30 BB-level with HR ≥ 60% before flipping.

## Path C — what's left

| Week | Items |
|---|---|
| Week 1 (DONE) | ✅ NBA snapshot CF + dataset + scheduler (smoke-tested); ✅ `cloudbuild-precompute.yaml` deploy step; ✅ MLB scheduler month range 2-11 timezone-edge fix |
| Week 1 remainder | MLB Dockerfile lock files; post-deploy `BUILD_COMMIT` verify step in `bin/deploy-service.sh` |
| Week 2 | Auth + secrets hardening — `data_quality_alerts` remove `--allow-unauthenticated`; Secret Manager migration for Slack webhooks (currently env-var plaintext on 50+ CFs); DR runbook drill against fresh NBA snapshot |
| Week 3 | Paused scheduler triage (60+ jobs); CF source-dir consolidation (4 roots → manifest); parallel `deploy.sh` audit (14 CFs have both auto-deploy + bespoke script — drift hazard) |

**Defer to quarterly:** Compute-default-SA → per-service SAs migration. 60+ CFs touched, high blast radius, needs a dedicated security window.

## Review-agent findings — status after the in-session second pass

The four review agents flagged 5 issues. After the second pass:

1. **`output_type=source_table` is the upstream trigger, not the output table** — STILL OPEN. Need per-processor emit instead of one-per-service. File: same 5 services I touched. ~2-3 hours, design-call territory; deferred to next session.
2. ✅ **`weight` default in `shared/registry/loader.py:66`** — fixed to `0.0` so missing-weight no longer implies active-strength.
3. ✅ **12 ex-shadow signals (Session 514 removals)** — 10 of them now `status: removed` with `deprecated_session` field (9 from Session 514 + sharp_book_lean_under from Session 431). The remaining 2 turned out to be misclassifications of canonical seed entries vs new auto-generated stubs — left alone.
4. **Backfill endpoints (`/process-date`, `/process-date-range`)** — STILL OPEN. 5 endpoint variants across 4 services need emit. Mechanical but spread out; ~1 hour.
5. ✅ **Phase 6 `row_count`** — now uses `len(paths)` as a proxy when no `row_count` field is set (paths dict is populated on success).

**Additional in-session cleanup:**
- ✅ Two obs filters (`unreliable_over_low_mins_obs`, `unreliable_under_flat_trend_obs`) removed entirely after pulling real CF HR from `best_bets_filtered_picks`: both fired N≤3 across 2 months, no path to graduation.
- ✅ Post-deploy `BUILD_COMMIT` verify added to `bin/deploy-service.sh` and `bin/hot-deploy.sh` — catches Sessions 516/520 traffic-routing drift class.
- ✅ Auto-memory updated: new detail file `path-a-b-foundations-2026-05-14.md` captures env knobs / CF state / gates / carry-overs; MEMORY.md `Active Operational State` shortened to a one-line pointer.

## Pre-existing carry-overs (still not blocking session)

- `SLACK_WEBHOOK_URL_SIGNALS` empty on `mlb-regime-monitor` (decision needed: provide URL or remove the alert path)
- `mlb_precompute.lineup_k_analysis` table empty (A1 lineup features vapor; deferred indefinitely)
- 3 VirtualizedGrid tests fail on clean main (JSDOM doesn't parse CSS `min()` — fix is `.skip` with TODO or update test to read computed-style at width-resolved query)
- 1,273 handoff docs in flat `docs/09-handoff/` directory (this one makes 1,274 — the staleness-by-burial problem persists)

## Suggested next session opening

```
/clear
Read docs/09-handoff/2026-05-14-path-a-and-b-foundations.md.

Three reasonable starting points (in order of leverage):

1. Deploy the grading-low-coverage-alert YAML + verify the
   emit_phase_completion metrics are reaching Cloud Monitoring:
      gcloud alpha monitoring policies create \
        --policy-from-file=monitoring/alert-policies/grading-low-coverage-alert.yaml \
        --project=nba-props-platform
   Then in the metrics explorer, filter on
   `custom.googleapis.com/nba_pipeline/phase_completion` — should
   see all 7 phases reporting after the next daily pipeline cycle.
   ~30 min.

2. Path A — review-agent deferred items:
   - output_type=source_table is the UPSTREAM trigger name in 5 emit
     sites; needs per-processor emit using OUTPUT table name. About
     2-3 hours; biggest design-call piece in the deferred bucket.
   - 12 ex-shadow signals (Session 514 removals) still labeled
     "shadow" in signals.yaml — should be "removed".
   - loader.py default weight 1.0 → 0.0 (cosmetic; safe).
   ~1 working day.

3. Path B Week 3:
   - Regime-adaptive OVER_QUALITY_WEIGHT in aggregator.py:213.
   - Audit the 2 obs filters (unreliable_over_low_mins_obs and
     unreliable_under_flat_trend_obs).
   - Player dedup conflict tagging (`contending_models` field +
     schema migration on signal_best_bets_picks).
   ~2 working days.

Monday retrain will be the first real test of min_hr_edge5 = 55%.
If it blocks an otherwise-passing model, that's the gate doing its
job — confirm the failure mode matches Session 487 LGBM-clone HR
pattern before adjusting.

Use Sonnet for routine work; bump to Opus for #2 (the output_type
refactor is design territory) or any "weight rebalance" decision
in #3.
```
