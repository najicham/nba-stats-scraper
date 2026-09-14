# MacBook session prompt — 2026-09-13

Paste the block below into a fresh Claude Code session on the laptop. It is self-contained;
it assumes nothing about the previous session's context.

State at the time of writing: `802e0742` on `main`, working tree clean, nothing unpushed,
all 24 services and functions deployed and verified. NBA opener is 2026-10-20, so nothing
here is urgent.

---

```
Continue the NBA props work. I'm on a MacBook, not the usual WSL box.

FIRST: read docs/02-operations/runbooks/working-from-a-second-machine.md and set the laptop
up before anything else. The one real trap is that this repo's bin/ scripts assume GNU
coreutils — timeout, grep -P, sed -i, date -d and readlink -f are all absent or different on
macOS, and bin/check-deployment-drift.sh (a Quick Start command) uses date -d. §2 of that
runbook is one brew install plus four PATH lines. Also needs: python3 -m venv .venv,
pip install -r requirements.txt -r requirements-test.txt, brew install libomp for xgboost on
Apple Silicon, and gcloud auth login + gcloud auth application-default login.

Then read, in order:
  docs/09-handoff/2026-09-08-MEASUREMENT-CI-GATES-TOPOLOGY.md   most recent session
  docs/09-handoff/2026-09-07-NEXT-SESSION-MENU.md               menu; C/A/D/E are done
  CLAUDE.md                                                     troubleshooting matrix

## Where things stand

Everything is committed, pushed and deployed as of 2026-09-13. HEAD is 802e0742. All 24
services and functions serve BUILD_COMMIT 851f811, verified by reading each one's SERVING
revision, and latestReady == latestCreated everywhere. CI is green: 2,930 passed, 0 failed.
Do not re-verify the deploy unless something looks wrong.

Live in GCP, applied directly and needing no deploy:
  - signal_best_bets_picks has bet_key + is_backfilled, backfilled for all 203 rows.
    Genuinely live picks are 46.8% HR (n=69); the 134 retro rows read 64.6%. Any hit rate
    off that table needs `is_backfilled = FALSE`.
  - prediction-worker containerConcurrency 1 -> 5 (maxScale is capped by the regional Cloud
    Run quota and cannot be raised; concurrency is the lever that costs nothing).
  - prediction-request-prod retryPolicy 30s-600s, maxDeliveryAttempts 20.

## Sanity check before starting work (offline, ~2.5 min, no network needed)

  env CLOUDSDK_CONFIG=/nonexistent/gcloud GOOGLE_APPLICATION_CREDENTIALS=/nonexistent/adc.json \
    PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -q --tb=line \
    --ignore=tests/unit/scrapers/ --ignore=tests/unit/services/ --timeout=60

Expect 2930 passed, 24 skipped, 0 failed. Those env vars are the faithful CI emulation, and
they also guarantee the suite is not quietly doing real work against my account.

## Open work — show me the options and let me choose, don't just pick one

  - The open half of menu item C: the PUBLIC 2025-26 record still shows the contaminated
    64.6%. The record exporters are already guarded, but filtering the public site makes it
    retroactively show 46.8%. That is my product decision, not a bug fix.
  - Get tests/cloud_functions/ into CI. It is not collected by .github/workflows/test.yml
    today. One blocker: a collection-time GCP client in test_phase3_orchestrator.py, which
    no fixture can intercept.
  - Menu item B — prove the signal_best_bets_picks INSERT. Option 3 (a direct writer test
    against a scratch dataset) is cheapest and does not touch frozen ml/signals/. Nobody has
    done it, and it is the last unproven link in the money path.
  - Menu items F (scheduler Wave C + never-invoked functions — add auto_backfill_orchestrator
    to that list), G (prediction-coordinator is allUsers-invocable and accepts any string
    after "Bearer "), H (observability), I (small leftovers, including the unpartitioned
    ml_feature_store_v2).
  - Housekeeping: MEMORY.md is over its 24.4KB load limit, so part of the index is silently
    truncated at session start. Worth a compaction pass.

## Standing rules

  - CODE FREEZE on ml/signals/ until 100 graded 2026-27 picks exist. Bug fixes and
    observability are fine; anything that changes selection is not. The freeze is a count,
    not a date — check signal_best_bets_picks first.
  - A success report on this system is weak evidence. Require a positive artifact: run the
    thing and read the data. Absence of an error is not evidence of success — /process-date
    returns 200 {"stats":{}} while writing nothing, logger.info is discarded in every Gen2
    CF, a sink exclusion drops severity=INFO for ~30 services, and emit_metric fails open.
    region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT is immune to all four.
  - A push to main auto-deploys every changed service from HEAD. A push touching
    shared/utils/** fans out to ~25 triggers at once and will hit the regional Cloud Run CPU
    quota — that happened on 2026-09-13. If builds fail quota-blocked, re-run the individual
    trigger (gcloud builds triggers run <trigger> --branch=main --region=us-west2), ONE AT A
    TIME, and never re-push. Verify by serving-revision BUILD_COMMIT, never by
    `gcloud builds list` (it paginates misleadingly).
  - Never --set-env-vars; it wipes everything. Always --update-env-vars.
  - Never trigger a Phase 6 signal-best-bets export for a historical date; it deletes picks.
  - Always pass --project=nba-props-platform / --project_id=. The local gcloud default has
    been wrong before (jett-prod, dmhr-platform, urcwest), and that is the real cause of the
    "bq hangs" myth — it was bq's interactive setup prompt.
  - Opener 2026-10-20; first publishable pick ~2026-11-17. Nothing is urgent.
  - Ask me before committing or pushing. No workflows or multi-agent orchestration unless I
    ask for them.
```
