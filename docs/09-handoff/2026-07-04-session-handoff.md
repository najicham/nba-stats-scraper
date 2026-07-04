# Session Handoff — 2026-07-04 (off-season execution)

**Branch:** `main` (all work committed + pushed). **System state:** OFF-SEASON, halted; opening
night provisional ~Oct 21, 2026. Nothing here changes live pick behavior — exports are halted, so
the writer/monitor changes take effect at season resume.

## What this session was

An **8-agent adversarial review** of the adjudicated off-season plan
(`docs/09-handoff/2026-07-03-5-adjudicated-plan.md`), then execution of the top of the resulting
worklist. Each reviewer verified plan claims against live GCP/BQ/code. Full findings + corrections:
`memory/offseason-plan-8agent-review-2026-07-04.md` (read this first).

**Verdict:** the plan's 5 "verified facts" ALL HOLD. But three plan claims were wrong and reorder
the work (details below). The adjudicated worklist is in that memory file.

## Commits shipped this session (4, all on `main`, pushed)

| Commit | What |
|--------|------|
| `f3540261` | Session-1 triage: de-landmine weekly-retrain docs, unblock pytest, fix 3 espn SyntaxErrors, extend syntax hook |
| `9010833c` | `nba-monitoring-alerts` CF: versioned from deployed zip + fixed 4 BQ errors, deployed rev 00007, verified 0 errors |
| `8449f4e3` | C2: `model_bb_candidates` writer repair (un-backfillable provenance) + tests + live round-trip verified |

(`d33c205b`, the adjudicated-plan docs, was also pushed this session — it had been an unpushed local commit.)

### Detail — `f3540261` (Session-1)
- **De-landmined weekly-retrain docs** (the exact 2025-26 root-cause trap: docs claimed a DELETED
  season-killer was merely "PAUSED, just resume it"). Fixed `docs/02-operations/runbooks/season-resume-2026-27.md`
  (3 spots) + `CLAUDE.md` ("fires every Monday" → "DEAD until restored"; removed it from the false
  cloudbuild-functions.yaml auto-deploy list).
- **Unblocked pytest** — bare `pytest` could not collect (addopts had `--cov` but pytest-cov
  uninstalled → aborted at arg-parse; hypothesis/psutil/responses/dotenv missing). Stripped `--cov`
  from `pytest.ini` (now opt-in), added `requirements-test.txt`, installed into `.venv`.
  **6619 tests now collect, 0 errors** (was 0 collected).
- **Fixed 3 committed SyntaxErrors on main**: `scrapers/espn/{espn_game_boxscore,espn_roster,espn_scoreboard_api}.py`
  (a botched notify-stub fallback left orphan `):`).
- **Extended `validate_python_syntax` hook** (+ config regex) to cover `scrapers/`+`orchestration/`
  (the scope hole that let those in), made it symlink-safe. 1221 files validated clean.

### Detail — `9010833c` (`nba-monitoring-alerts`)
- Source existed ONLY in an incident-doc markdown heredoc (never in the repo). Exhumed the deployed
  `function-source.zip` (gcf-v2-sources gen `1768621716807390`) → versioned at
  `orchestration/cloud_functions/nba_monitoring_alerts/` (main.py + requirements + deploy.sh + README).
- Fixed **4 errors firing every 4h, 24/7** (the review's log sample caught only the first 2):
  1. `feature_quality`: dataset `ml_nba` (doesn't exist) → `nba_predictions`.
  2. `prediction_accuracy`: column `is_correct` → `prediction_correct`.
  3. `feature_quality`: `COUNTIF/COUNT` = 0/0 division-by-zero on empty days + a NULL-row false
     "quality degraded" alert → `SAFE_DIVIDE` + `total_rows==0 → NO_DATA` guard.
  4. `model_loading`: Cloud Logging `timestamp>"..."` used a naive isoformat (no tz) → append `Z`.
- Parameterized the retired `system_id='catboost_v8'` via env `MONITOR_SYSTEM_ID` (the
  `validate-model-references` hook blocks hardcoded `catboost_v*`). Behavior unchanged (still NO_DATA
  on the retired model).
- **Deployed** gen2/python311 (rev 00007), env vars + `SLACK_WEBHOOK_URL` secret preserved, scheduler
  untouched. Verified: all 5 checks run with **zero errors**.

### Detail — `8449f4e3` (C2 — the un-backfillable one)
Repaired the `model_bb_candidates` writer (had only 33 rows / 13 dates from 2026-03-09 — ~2 months of
silent provenance loss). Files: `data_processors/publishing/signal_best_bets_exporter.py`
(`_collect_all_model_candidates`, `_write_model_bb_candidates`, `export()`) + `ml/signals/per_model_pipeline.py`.
1. **List-into-STRING load failures (the silent killer)** — `qualifying_subsets`, `filters_passed`,
   `filters_failed`, `observation_flags`, `pipeline_agreement_models` are STRING columns; the writer
   emitted Python lists → any non-empty one fails the WHOLE load job, swallowed as a warning. Now
   JSON-serialized in collect (empty → NULL) + a defensive writer pass.
2. `star_teammates_out` float → INTEGER coercion.
3. Key-name mismatches → silent NULLs: pipeline sets `is_home`/`rest_days`; schema wants `home_away`
   (STRING) / `is_back_to_back` (BOOLEAN). Mapped (b2b = 0 days rest, per `nba_team_mapper`).
4. Last-writer-wins full-date DELETE → **scoped `(system_id, player_lookup)` upsert + abort-on-DELETE**.
5. Moved the candidate write **above** the started-games early return (candidate-starved re-exports
   were recording nothing).
6. Added `export_run_at TIMESTAMP` + `book_count INTEGER` (live table ALTERed + `schemas/model_bb_candidates.json`);
   persist `book_count` for December's P1.4. Stamp `rank_in_pipeline` (composite DESC).
- **Tests:** `tests/unit/publishing/test_model_bb_candidates_writer.py` (7 pass) incl. a
  type-conformance test vs the schema JSON — the test that catches the whole list-into-STRING class.
- **Verified via a live BQ scratch round-trip:** the load that was silently failing now succeeds;
  scoped delete preserves other players.
- **Left NULL on purpose (out of scope):** `player_line_tier`/`spread`/`over_rate_last_10` (not set on
  the per-model candidate dict — separate plumbing) and `pipeline_hr_21d` (didn't stamp the
  semantically-different 7d health value into a "21d" column).

## Corrections to the plan (verified live — carry these forward)

- **"57 stale tests" is REFUTED — actually ~733 red in `tests/unit`, ~1828 full**, and bare `pytest`
  couldn't even collect (now fixed). "Green the suite" must be **scoped** to `tests/unit/{publishing,signals}`
  (~450, where July edits land) + delete tests for removed modules; `xfail` the ~512 `tests/processors/*`
  GCP-cred-mock harness failures. It is NOT a Week-1 checkbox.
- **Only 1 of 3 "bleeding monitors" was actually firing** (`nba-monitoring-alerts`, now fixed). The
  canary triggers are already PAUSED (dormant-broken image). `master-controller-hourly` is a benign
  no-op — do NOT pause it (adds a season-open re-enable obligation).
- **kalshi "ZERO consumers" is REFUTED** — `predictions/coordinator/player_loader.py:137,430` consumes
  it for `line_discrepancy`. Restore-manifest DECIDE#1 → RESTORE PAUSED.
- **"175-vs-189 = join fragility" is wrong** — it's exactly the 14 voided picks (`is_voided=TRUE`).
- **model_bb_candidates provenance loss ~4-5 months, not 2**, and the Task #39 fix had NEVER run live
  (all 33 rows had NULL context cols). C2 now fixes the writer; non-NULL population should be an
  October dress-rehearsal check.
- **`.gcloudignore:2 = bin/`** may silently omit `bin/` from EVERY Cloud Build — needs a one-command
  blast-radius audit (see Next).

## Next worklist (ranked, for the taking-over session)

1. **Canary image fix + `.gcloudignore` audit** (P1, ~1 session). The `nba-pipeline-canary` Cloud Run
   job pulls image `us-west2-docker.pkg.dev/nba-props-platform/nba-props/pipeline-canary:latest` but
   the image is missing `/app/bin/monitoring/pipeline_canary_queries.py` because `.gcloudignore` line 2
   excludes `bin/`. Fix with a **targeted `!bin/monitoring/` negation** (NOT a blanket un-ignore — that
   bloats every Cloud Build context) or a dedicated `Dockerfile.canary`; rebuild → push to that AR path;
   run ONE execution to green; **leave both triggers PAUSED** (`nba-pipeline-canary-trigger`,
   `...-routine-trigger`). Then audit which other Cloud Builds `COPY`/import `bin/` and may be shipping
   incomplete images. This also unblocks the P1.2 closing-line canary.
2. **C1 — shadow-tag persistence + `v_bb_candidate_signal_stream` view** (P1, ~1 session). Builds on C2
   (its merge_rejected leg). Spec: `docs/08-projects/current/measurement-infrastructure/00-SPEC.md`
   Component 1. Metadata-only aggregator edit (~15 lines at `ml/signals/aggregator.py` ~line 674) +
   view DDL. Keep the byte-identical `aggregate()` golden test as the zero-serve-path guarantee.
3. **Scoped test-greening** (P1, multi-session) — `tests/unit/{publishing,signals}` first (the 15 stale
   failures in `test_best_bets_exporter.py` are `_safe_float`→`safe_float` move + `TIER_CONFIG` drift),
   delete tests for removed modules, `xfail` the processors GCP-cred harness.
4. **C3 pre-registration** (two-tier gates → `shared/registry/*.yaml` + `PREREG-*.md`), then **C4/C5**
   → Sept slack (NOT July-critical; not un-backfillable).

**Do NOT:** restore/enable weekly-retrain or decay-detection live before season open (inert while
halted; early restore risks training on anomaly-vintage data — Wave C in the restore manifest);
resume any paused trigger; attempt a full-suite green as a gate; build a CI test gate; front-load
C4/C5; pause master-controller; backfill lost model_bb_candidates provenance.

## Gotchas for the next session

- **Working on `main` with auto-deploy-on-push.** Push deploys changed services. Off-season this is
  safe (exports halted), but keep code deployable. `shared/` edits deploy ALL 7 services.
- **Pre-commit hooks that will block you:** `validate-model-references` (no hardcoded `catboost_v*`
  system_ids), `validate-python-syntax` (now incl. scrapers/+orchestration/), `validate-schema-fields`.
  Run before committing.
- **`nba-monitoring-alerts` is NOT in `cloudbuild-functions.yaml`** → it deploys via its own
  `orchestration/cloud_functions/nba_monitoring_alerts/deploy.sh`, not auto-deploy. Same for its
  season-open follow-up (point `MONITOR_SYSTEM_ID` at an active model / make the 2 checks fleet-wide).
- **Test deps** live in `requirements-test.txt` (installed in `.venv`). Bare `.venv/bin/pytest` works
  now; coverage is opt-in (`pytest --cov=.`).
- **`gcloud scheduler jobs list` HANGS in this env** — use `describe` per job.

## Verification commands

```bash
# monitor is clean (should show no "Error in" lines):
gcloud scheduler jobs run nba-monitoring-alerts --location=us-west2 --project=nba-props-platform
gcloud functions logs read nba-monitoring-alerts --gen2 --region=us-west2 --project=nba-props-platform --limit=12

# C2 writer tests:
.venv/bin/pytest tests/unit/publishing/test_model_bb_candidates_writer.py -q

# hooks:
.venv/bin/python .pre-commit-hooks/validate_python_syntax.py
.venv/bin/python .pre-commit-hooks/validate_model_references.py

# model_bb_candidates (will only grow once exports resume at season open):
bq query --use_legacy_sql=false 'SELECT COUNT(*) rows, MIN(game_date) min_d, MAX(game_date) max_d,
  COUNTIF(export_run_at IS NOT NULL) has_run_at FROM `nba-props-platform.nba_predictions.model_bb_candidates`'
```

## Key references
- Plan: `docs/09-handoff/2026-07-03-5-adjudicated-plan.md`
- Measurement-infra spec: `docs/08-projects/current/measurement-infrastructure/00-SPEC.md`
- Restore manifest: `docs/02-operations/scheduler-restore-manifest-2026.md`
- Season-resume runbook: `docs/02-operations/runbooks/season-resume-2026-27.md` (corrected this session)
- Review findings + running status: `memory/offseason-plan-8agent-review-2026-07-04.md`
