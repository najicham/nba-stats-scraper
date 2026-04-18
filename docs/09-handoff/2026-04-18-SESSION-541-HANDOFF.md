# Session 541 Handoff — MLB post-incident validation + automation review

**Date:** 2026-04-18 (evening, after S540)
**Focus:** Two-part job.
  1. Verify the MLB pipeline has been running cleanly since the Apr 17 incident was patched.
  2. Re-evaluate the automation layer and propose improvements — this outage exposed at least one broken canary and raises the question of what else might be silently dead.

> **Read first:** [S540](./2026-04-16-SESSION-540-HANDOFF.md) (frontend-only, and flagged that S539's scheduler cold-start hypothesis was still open). The S539 cold-start question turned out **not** to be the root cause of the Apr 17 outage — it was application bugs, detailed below. Treat S539's cold-start hypothesis as still open for MLB schedulers generally, but deprioritize it.

---

## TL;DR

Apr 17 MLB pipeline outage: zero best-bets, zero filter audits, zero GCS best-bets output despite 52 successful predictions. Three commits shipped to close it:

| Commit | Fix |
|---|---|
| `3eb6b73b` | Coerce BigQuery `Decimal → float` at the loader layer (`pitcher_loader.py`, `supplemental_loader.py`) — plus module-level `from google.cloud import bigquery` in `worker.py` |
| `0c993a9b` | `MLBBestBetsExporter._safe_evaluate()` wraps all 5 `signal/filt.evaluate()` call sites so one crashing signal cannot kill the whole pipeline |
| `ed5f0168` | Rewrote the "MLB Phase 6 - Best Bets Published" canary (was querying non-existent columns on the wrong table with `min=0` threshold — quietly dead) |

Apr 17 manually backfilled (3 OVER picks). Apr 18 ran cleanly end-to-end (1 pick, Sandy Alcantara OVER, 7 signals including `high_csw_over` — the signal that was crashing).

**Your job:**
- Spend ~15 minutes confirming the last 7 days look healthy in BQ, GCS, and scheduler state.
- Then spend the rest of the session auditing our monitoring/canary layer for any *other* silent-dead checks like the one we just found — this incident proves they exist.

---

## Background: what happened on Apr 17

Compressed timeline:

- **Apr 11:** `mlb_analytics.pitcher_game_summary.season_csw_pct` started populating (was NULL all early season). BQ returns this `NUMERIC(5,4)` column as `decimal.Decimal`.
- **Apr 11–16:** `EliteCSWOverSignal` ran harmlessly. The Decimal-using branch `(csw - 0.25) / 0.10` only executes when a pitcher has both `csw >= 0.30` AND an OVER recommendation — no pitcher matched both on those days. Signal kept returning `_no_qualify()`.
- **Apr 17 16:55 UTC:** first qualifier tripped the arithmetic → `TypeError: unsupported operand type(s) for -: 'decimal.Decimal' and 'float'` → the exception propagated up through `best_bets_exporter.export()`'s signal loop → **entire pipeline aborted on the first iteration** → 0 picks, 0 filter audits, 0 GCS output.
- **Apr 17 17:00 UTC:** `/predict-batch` ran fine (52 predictions written), but was an unrelated codepath.

**Why this lingered without being noticed:** the "MLB Phase 6 - Best Bets Published" canary at `bin/monitoring/pipeline_canary_queries.py:451` was pointing at `pitcher_strikeouts` with columns `recommended_bet`, `confidence`, `ensemble_prediction` that **don't exist on that table**, and threshold `min=0` (i.e., zero picks always passed). Apr 15 and 16 had also produced 0 picks (genuinely — low-edge early-season predictions, not a bug) and the canary cheerfully passed. No page, no alert, no visibility.

The Apr 18 canary run (post-fix) still reports 4 pre-existing failures unrelated to MLB: `scheduler_v1` import error, `signal_health_daily` missing partition filter, and two NBA-playoffs threshold trips (`players < 100`, `avg_points < 8`) — none of which are the MLB check. Those are separate issues worth triaging in the automation review.

---

## Part 1 — Validate the last 7 days

All of these should return "clean" results. Anything unexpected is worth pausing on before moving to Part 2.

### 1a. Scheduler state

```bash
gcloud scheduler jobs describe mlb-best-bets-generate --location=us-west2 --project=nba-props-platform --format="yaml(lastAttemptTime,status,state)"
gcloud scheduler jobs describe mlb-predictions-generate --location=us-west2 --project=nba-props-platform --format="yaml(lastAttemptTime,status,state)"
```

**Expected:** Both `status: {}` (empty = success). Anything with a `code:` key is a failure — pull logs immediately.

### 1b. BQ pipeline counts, last 7 days

```bash
bq query --use_legacy_sql=false --location=US --format=pretty '
SELECT
  game_date,
  (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` p WHERE p.game_date = d.game_date) AS preds,
  (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` b WHERE b.game_date = d.game_date) AS bb,
  (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit` a WHERE a.game_date = d.game_date) AS filter_audit,
  (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.prediction_accuracy` g WHERE g.game_date = d.game_date) AS graded
FROM UNNEST(GENERATE_DATE_ARRAY(DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY), CURRENT_DATE())) AS game_date
CROSS JOIN (SELECT 1) d_anchor
, UNNEST([STRUCT(game_date AS game_date)]) d
ORDER BY game_date DESC
'
```

**Expected shape (as of session end 2026-04-18):**
- Apr 12–16: `bb` small or zero (correct for early season — low-edge predictions don't clear the floor). `preds` > 0 on game days.
- Apr 17: `preds=52, bb=3` (post-backfill), filter_audit non-zero, graded comes later as the day's games complete.
- Apr 18: `preds=28, bb=1, filter_audit=112`.

**Red flag pattern:** any day with `preds > 10 AND bb = 0 AND filter_audit = 0` — that's the exact signature of the Apr 17 bug (signal crash aborts before writes).

### 1c. GCS exports

```bash
gsutil ls -l gs://nba-props-platform-api/v1/mlb/best-bets/ | tail -10
```

**Expected:** One file per date for the past week, sizes ~300 bytes (no picks) to ~2KB (picks present). `all.json` updated in the last ~24h.

### 1d. Worker health

```bash
gcloud run services describe mlb-prediction-worker --region=us-west2 --project=nba-props-platform \
  --format="value(status.latestReadyRevisionName,status.traffic[0].latestRevision,status.url)"
```

**Expected:** `mlb-prediction-worker-00068-qrb` or later, `True` (serving latest), URL unchanged.

### 1e. Fresh error scan

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="mlb-prediction-worker" AND severity>=ERROR AND timestamp>="'"$(date -u -d '-24 hours' +%Y-%m-%dT%H:%M:%SZ)"'"' \
  --project=nba-props-platform --limit=20 --format="value(timestamp,textPayload)"
```

**Expected:** Zero `TypeError` entries. Any `ERROR` lines should be triaged but signal-isolation means they shouldn't be fatal — pipeline would still have written picks.

### 1f. Confirm the `_safe_evaluate` code path actually fired if needed

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="mlb-prediction-worker" AND textPayload=~"\\[MLB BB\\] signal .* raised" AND timestamp>="'"$(date -u -d '-7 days' +%Y-%m-%dT%H:%M:%SZ)"'"' \
  --project=nba-props-platform --limit=30 --format="value(timestamp,textPayload)"
```

A non-empty result here is actually good news — it means our isolation layer caught a signal bug silently and the pipeline continued. But the surfaced errors are now visible instead of swallowed, so they should be investigated.

---

## Part 2 — Automation re-evaluation

The Apr 17 incident proved at least one canary was silently dead. **Assume others are too.** Audit aggressively.

### 2a. Canary integrity sweep

The canary job at `bin/monitoring/pipeline_canary_queries.py` has 20+ checks. Run them all and triage failures:

```bash
gcloud run jobs execute nba-pipeline-canary --region=us-west2 --project=nba-props-platform --wait
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-pipeline-canary" AND timestamp>="'"$(date -u -d '-10 minutes' +%Y-%m-%dT%H:%M:%SZ)"'"' --project=nba-props-platform --limit=200 --format="value(textPayload)" | grep -E "FAIL|ERROR|failures"
```

Known pre-existing failures as of session end that still need someone to look at them:
1. **`scheduler_v1` import error** — `cannot import name 'scheduler_v1' from 'google.cloud'`. Likely a library/requirements drift in the canary image after the 2026-04-18 rebuild.
2. **`signal_health_daily` partition-filter violation** — canary query missing `WHERE game_date >= ...` on a required-partition-filter table.
3. **NBA thresholds tripping in playoffs** — `players < 100` and `avg_points < 8`. Playoff rosters and defense both hit these. Either lower thresholds for playoff dates or segment by `season_type`.

For each check in the file, verify: does the query reference real column names on the real table? Does the threshold actually *fail* on a real outage? The pattern that killed us was a query that returned 0 every day + a threshold that accepted 0.

**Recommended verification:** for every canary, dry-run the SQL against a known-bad date to confirm it fails. If you can't write down a scenario that trips the check, it's not really monitoring anything.

### 2b. "Silent-zero" pattern audit — does it exist elsewhere?

The specific failure mode — *pipeline runs, returns HTTP 200, writes nothing* — is sneaky. Places to audit for the same pattern:

- **NBA best-bets pipeline:** does `nba_predictions.signal_best_bets_picks` have a canary keyed on `preds > N AND picks = 0`? The zero-pick auto-halt (Session 515) is the intended behavior now, so this one's complicated — but the canary should distinguish halt-active vs silent-crash.
- **Phase 6 export:** does any check alert when a `target_date`'s JSON on GCS is `{"best_bets": []}` despite BQ having picks?
- **Phase 5b grading:** does any check alert when `prediction_accuracy` didn't grow yesterday despite games finishing?
- **Scraper health:** scrapers are generally monitored via `bin/validation/validate_workflow_dependencies.py` but a per-scraper "0 rows written today" check is different from "workflow succeeded."

### 2c. Systemic improvement ideas (user wants ideas, not implementation)

The user asked you to *propose* automation improvements. Write a short section recommending what, if anything, you'd change. A few seed ideas to validate or reject:

1. **Wrap every sport's signal evaluator in `_safe_evaluate`-equivalent.** NBA uses `ml/signals/aggregator.py`. Does it isolate per-signal exceptions? If not, same risk.
2. **Canary health meta-check.** A check that validates the canaries themselves — "does this SQL compile?", "do referenced columns exist?". A broken canary's only tell today is silence.
3. **`Decimal` coercion as a shared utility.** `_coerce_decimal` currently lives on the MLB loader. NBA's feature store could hit the exact same bug if a NUMERIC column is ever added. Promote it to `shared/utils/` and apply at every BQ-dict-consumer seam.
4. **Pre-commit hook for "signal body must handle NULL and wrong-type inputs gracefully."** Hard to express as a lint, but at minimum a convention: signals should never let a `features.get(X)` expression reach arithmetic without a type guard.
5. **Auto-detection of latent time-bombs.** A CI check that runs each signal against a synthetic feature dict with a Decimal value for every float-typed field — would have caught the CSW bug before it shipped.

The user said **re-evaluate** — so have a point of view. Two or three strong, specific recommendations > a list of everything you could possibly do.

---

## State at session end

- **`nba-stats-scraper` main:** `ed5f0168`. Three commits on top of S540's `70a1bc28` base:
  - `3eb6b73b` fix(mlb-worker): Decimal→float + module-level bigquery import
  - `0c993a9b` fix(mlb-bb-exporter): `_safe_evaluate` signal isolation
  - `ed5f0168` fix(monitoring): rewrite MLB Phase 6 canary
- **`mlb-prediction-worker`:** revision `00068-qrb` live, 100% traffic.
- **`pipeline-canary` image:** rebuilt 2026-04-18 18:48 UTC at `us-west2-docker.pkg.dev/nba-props-platform/nba-props/pipeline-canary:latest`. Ran once (`nba-pipeline-canary-gssk7`) post-rebuild. Next scheduled runs (`*/15`) pick it up automatically.
- **Apr 17 data restored:** 3 BB picks in `signal_best_bets_picks`, 82 rows in `best_bets_filter_audit`, GCS `best-bets/2026-04-17.json` (1345 bytes, 3 picks) + `all.json` refreshed.
- **Apr 18 data:** Sandy Alcantara OVER (edge 1.4, signals: `high_edge, recent_k_above_line, home_pitcher_over, high_csw_over, pitch_efficiency_depth_over, pitcher_on_roll_over, chase_rate_over`). `high_csw_over` fired cleanly — confirming the Decimal fix.
- **NBA pipeline:** still auto-halted (playoffs, all 7 models BLOCKED per S533 memory). 0 picks expected, unchanged.

---

## Open items carried forward (not touched this session)

From S539 / S540:
- **S539 cold-start hypothesis** — still open but deprioritized. Apr 17 was NOT cold-start; schedulers fired fine. Keep it in mind if both schedulers start returning `code:` on some future day.
- **`mlb_umpire_assignments` scraper bug** — `scrapers/mlb/mlbstatsapi/mlb_umpire_assignments.py:101` calls `.get()` on a function. Small fix.
- **S540 frontend nice-to-haves** — `LeaderboardSkeleton` still sized for the deleted "Best Record" tab; `PitcherModal.tsx:171` pre-existing set-state-in-effect lint; `ModelTrustsHimEntry` type no longer consumed but backend still emits it.
- **~21 remaining MLB schedulers** still need OIDC audit (S539 item).

New from this session:
- **`scheduler_v1` import error** in canary job (pre-existing failure surfaced by today's run, but now more visible).
- **`signal_health_daily` canary query missing partition filter** — also pre-existing.
- **NBA canary thresholds need playoff-season segmentation** — `players < 100` and `avg_points < 8` trip legitimately in playoffs.

---

## Useful one-liners

**Full MLB pipeline snapshot, any date:**
```bash
D=2026-04-18
bq query --use_legacy_sql=false --location=US --format=pretty "
SELECT 'preds' s, COUNT(*) n FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\` WHERE game_date = '$D'
UNION ALL SELECT 'bb', COUNT(*) FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` WHERE game_date = '$D'
UNION ALL SELECT 'filter_audit', COUNT(*) FROM \`nba-props-platform.mlb_predictions.best_bets_filter_audit\` WHERE game_date = '$D'
UNION ALL SELECT 'graded', COUNT(*) FROM \`nba-props-platform.mlb_predictions.prediction_accuracy\` WHERE game_date = '$D'
UNION ALL SELECT 'props', COUNT(*) FROM \`nba-props-platform.mlb_raw.oddsa_pitcher_props\` WHERE game_date = '$D'
"
```

**Manual rerun for a specific date (idempotent):**
```bash
TOKEN=$(gcloud auth print-identity-token)
curl -sS -X POST https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/best-bets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"game_date": "2026-04-XX"}'
gcloud pubsub topics publish nba-phase6-export-trigger --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"2026-04-XX"}'
```

**Rebuild canary image (no auto-deploy trigger — required after edits to `bin/monitoring/pipeline_canary_queries.py`):**
```bash
cat > /tmp/canary-ignore <<'EOF'
.git/
docs/
__pycache__/
*.py[cod]
.venv/
models/
EOF
cat > /tmp/canary-cloudbuild.yaml <<'EOF'
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-t', 'us-west2-docker.pkg.dev/nba-props-platform/nba-props/pipeline-canary:latest', '-f', 'bin/monitoring/Dockerfile.canary', '.']
- name: 'gcr.io/cloud-builders/docker'
  args: ['push', 'us-west2-docker.pkg.dev/nba-props-platform/nba-props/pipeline-canary:latest']
options:
  logging: CLOUD_LOGGING_ONLY
EOF
gcloud builds submit --config=/tmp/canary-cloudbuild.yaml \
  --project=nba-props-platform --region=us-west2 --timeout=600 \
  --ignore-file=/tmp/canary-ignore .
```

---

## Key lessons for future sessions

**"HTTP 200 + 11KB response body" is not the same as "wrote data to BigQuery."** The Apr 17 signature looked like success from the scheduler's perspective. Always validate the downstream table, never just the endpoint.

**Canaries that test the happy path test nothing.** The broken MLB Phase 6 canary returned 0 every day and called it a pass — it was the same as no canary at all. Good canary design: *what would this query look like on the day a real outage happens, and would the threshold fire?*

**BigQuery NUMERIC columns are `decimal.Decimal` in Python.** Most signals `features.get('x')` then do arithmetic with float literals. The bug only reveals itself the first day a qualifying row exists. Coerce at the seam (loader) rather than defensively at every consumer — the one-liner fix in `pitcher_loader.py` covers every signal forever.

**Signal isolation is table stakes.** A pipeline that loops over N signals must not let one raising kill the other N-1. The `_safe_evaluate()` pattern should be applied anywhere there's a plugin-style evaluation loop, not just MLB best-bets.
