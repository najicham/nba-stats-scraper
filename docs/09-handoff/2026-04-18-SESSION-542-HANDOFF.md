# Session 542 Handoff — MLB validation + canary/scheduler audit

**Date:** 2026-04-18 (evening)
**Focus:** Part 1 — validate MLB pipeline post S541 fixes. Part 2 — audit monitoring/canary layer, fix everything actionable.

---

## TL;DR

MLB pipeline is healthy. Canary went from 4 broken checks → 1 legitimate alert (4 scheduler jobs self-healing by tomorrow). Found and fixed 7 distinct bugs across canary, scrapers, and scheduler config.

| Commit | Fix |
|---|---|
| `1dc86ce5` | Canary: `google-cloud-scheduler` missing from requirements (scheduler check silently dead), `signal_health_daily` partition filter, playoff thresholds `players:100→20`, `avg_points:8→6`, exclude never-ran jobs from failing count. Scrapers: `mlb_umpire_assignments` `self.download_data → self.decoded_data`, `mlb_game_lines` TODAY sentinel + `date→game_date` param. |
| `60afd7e8` | Fix `last_attempt_time is not None` check — was using `.seconds` on a `DatetimeWithNanoseconds` object. |
| `fc94d88b` | Register `mlb_live_box_scores` in `MLB_SCRAPER_REGISTRY` (scraper existed but was never registered → 400 on every scheduler run). |

---

## Part 1 — MLB validation (all clean)

**BQ pipeline counts (Apr 11–18):**

| Date | preds | bb | filter_audit | graded |
|---|---|---|---|---|
| Apr 18 | 28 | 1 | 112 | NULL (games in progress) |
| Apr 17 | 52 | 3 | 82 | 23 |
| Apr 16 | 17 | 0 | 47 | 12 |
| Apr 15 | 25 | 0 | 63 | 16 |
| Apr 14 | 27 | 0 | 0 | 16 |
| Apr 13 | 17 | 0 | 0 | 10 |
| Apr 12 | 26 | 0 | 0 | 17 |
| Apr 11 | 25 | 0 | 0 | 20 |

Apr 14–earlier: no filter_audit because all preds were below edge floor (nobody reached signal evaluation). Apr 15–16: filter_audit rows but 0 picks = pipeline ran to completion, edges just below floor. Expected behavior.

**Red flag check:** No day with `preds > 10 AND bb = 0 AND filter_audit = 0` post-fix. The Apr 17 bug signature is gone.

**Worker:** `mlb-prediction-worker-00068-qrb`, `True` (latest), URL unchanged.

**GCS:** All dates present Apr 6–18. Apr 18: 713 bytes (Sandy Alcantara OVER). `all.json` updated 18:39 UTC.

**Errors:** Zero `TypeError` entries. Zero `[MLB BB] signal * raised` fires — no signals crashed.

**Both schedulers:** `status: {}` (last attempt success). Both `ENABLED`.

---

## Part 2 — Automation audit results

### Canary state after all fixes

Previous: 4 failures (scheduler import error, signal_health_daily 400, NBA playoff thresholds × 2)
After: 1 failure — `failing_jobs: 4 > 3` — these are the 4 scheduler jobs with stale last-failure status

The 4 still-alerting scheduler jobs and their status:

| Job | Error | Fix deployed? | Will clear |
|---|---|---|---|
| `mlb-game-lines-morning` | code 13 (param `date`→`game_date` mismatch) | ✅ | Tomorrow 10:30 AM ET |
| `mlb-umpire-assignments` | code 13 (`self.download_data` bug) | ✅ | Tomorrow 11:30 AM ET |
| `mlb-props-morning` | code 2 (no OIDC auth) | ✅ OIDC added | Tomorrow 10:30 AM ET |
| `mlb-props-pregame` | code 2 (no OIDC auth) | ✅ OIDC added | Tomorrow 12:30 PM ET |

By tomorrow afternoon, the scheduler canary should drop to 0 failures.

**Additional scheduler actions:**
- `mlb-live-boxscores`: PAUSED. BDL `/mlb/v1/box_scores/live` returns 401 despite valid `BDL_API_KEY`. Registry gap also fixed (`mlb_live_box_scores` was never registered). Investigate BDL MLB subscription access separately. Not critical for batch predictions.
- `nba-playoffs-shadow-activate`: PAUSED. Annual one-time job (April 14 only). OIDC added. Already ran this year. Re-enable before April 14, 2027.

### Bugs found during audit

1. **`google-cloud-scheduler` missing from canary `requirements.txt`** — the scheduler health check was importing `scheduler_v1` which wasn't installed. Import silently failed → scheduler check always raised an exception → was counted as "error" not "real failures". Fixed.

2. **`signal_health_daily` canary missing partition filter** — query threw 400 every run. Added `WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)`. Fixed.

3. **NBA playoff thresholds** — `Phase 3 Analytics` had `players: {'min': 100}` and `avg_points: {'min': 8}`. Playoffs: 62 players, 7.85 avg_points. Changed to 20 and 6 respectively. `Phase 4 Precompute` same `players: 100` → 20.

4. **Canary `check_scheduler_health()` counting never-ran jobs** — code: `-1` jobs (one-time reminders, future-dated seasonal jobs) inflated count from 6 real failures to 14. Fixed: `has_run = job.last_attempt_time is not None`.

5. **`mlb_umpire_assignments.py:101` uses `self.download_data`** — should be `self.decoded_data`. Every other MLB Stats API scraper uses `decoded_data`. Bug: `AttributeError: 'function' object has no attribute 'get'`. Fixed.

6. **`mlb_game_lines.py` scheduler body sends `date` but scraper requires `game_date`** — `required_opts = ["game_date"]` validated before `set_additional_opts` ran. Also: `set_additional_opts` didn't resolve `TODAY` for `game_date` (ConfigMixin only resolves `opts["date"]`). Fixed both.

7. **`mlb_live_box_scores` not in `MLB_SCRAPER_REGISTRY`** — scheduler job `mlb-live-boxscores` fired every 5 minutes getting HTTP 400 (unknown scraper). After adding OIDC, error changed from code 3 → code 2. After adding to registry, service returns 500 (BDL 401 on the API call). Paused scheduler pending BDL investigation.

8. **3 MLB scheduler jobs missing OIDC auth** (`mlb-live-boxscores`, `mlb-props-morning`, `mlb-props-pregame`) — added `oidcToken` with SA `756957797294-compute@developer.gserviceaccount.com`.

### Silent-zero pattern assessment

The handoff asked to check for other "HTTP 200 but wrote nothing" scenarios:

| Area | Status |
|---|---|
| **NBA BB pipeline** | `check_bb_candidates_today()` + `check_pick_drought()` + `check_filter_audit_jammed()` cover this. Halt-active detection noted as gap — doesn't distinguish halt vs. silent crash. |
| **Phase 6 export** | No check that BQ has picks but GCS JSON is empty. `mlb_phase6_best_bets` canary covers the MLB side via `pick_ratio_with_floor`. NBA equivalent is `bb_pick_drought` (but it checks picks table, not GCS). |
| **Phase 5b grading** | `check_grading_freshness()` covers this. |
| **Scraper health** | `validate_workflow_dependencies.py` checks scheduled workflows. Per-scraper "0 rows written" gap still exists. |

### Systemic recommendations (Part 2c)

Three high-confidence changes:

**1. `_safe_evaluate` pattern in NBA aggregator.** The MLB `_safe_evaluate()` wraps each signal so one crash can't kill the pipeline. `ml/signals/aggregator.py` doesn't do this — a crashing signal kills NBA best bets too. Medium risk: NBA signals are older and less likely to have type bugs, but same architecture. One-line fix per signal call site.

**2. Canary self-validation.** Add a startup check in `pipeline_canary_queries.py` that validates all `CANARY_CHECKS` queries compile (dry run with `--dry_run=True`) and reference real tables. The `mlb_phase6_best_bets` bug was undetectable because a broken query that returns 0 with a `min=0` threshold has no external tell. A weekly "canary health check" that tests canaries against known-bad dates would catch this class of bug.

**3. `_coerce_decimal` promotion to `shared/utils/`**. The fix in `pitcher_loader.py` adds `float()` coercion for BQ `NUMERIC` columns. NBA's `ml_feature_store_v2` doesn't use NUMERIC currently, but the pattern should be a shared utility (`shared/utils/bq_type_coercion.py`) so any future NUMERIC column gets automatic coercion rather than requiring a per-loader fix. Low urgency but high defensive value.

---

## State at session end

- **`nba-stats-scraper` main:** `fc94d88b`. 3 commits on top of S541 base (`ed5f0168`):
  - `1dc86ce5` fix(monitoring): canary + 3 scheduler bugs
  - `60afd7e8` fix(monitoring): DatetimeWithNanoseconds check
  - `fc94d88b` fix(scrapers): register mlb_live_box_scores
- **`mlb-phase1-scrapers`:** revision `00017-*` live (2 manual deploys this session: `mlb_umpire_assignments` fix + registry fix).
- **Canary image:** rebuilt 4× this session. Latest at ~21:37 UTC.
- **Paused schedulers:** `mlb-live-boxscores` (BDL 401), `nba-playoffs-shadow-activate` (annual, already ran).
- **OIDC-fixed schedulers:** `mlb-live-boxscores`, `mlb-props-morning`, `mlb-props-pregame`, `nba-playoffs-shadow-activate`.
- **Canary failures:** 1 — `failing_jobs: 4 > 3` (all self-healing by tomorrow).

---

## Open items carried forward

From S539 / S540 (unchanged):
- **S539 cold-start hypothesis** — still open but deprioritized.
- **`mlb_umpire_assignments`** — deployed fix, will clear tomorrow.
- **S540 frontend nice-to-haves** — `LeaderboardSkeleton`, `PitcherModal` lint, `ModelTrustsHimEntry` type.

From S541 (OIDC audit):
- **~17 remaining MLB schedulers need OIDC audit** — S539 said ~21, we fixed 4 this session. Pattern: jobs targeting Cloud Run services without `oidcToken`. Can batch-fix with gcloud.

New from this session:
- **`mlb-live-boxscores` BDL 401** — scraper registered, OIDC added, job paused. Need to verify BDL MLB subscription includes `/mlb/v1/box_scores/live`. If not, update to use MLB Stats API live data (`mlb_game_feed` with live game IDs) or remove job entirely.
- **NBA `_safe_evaluate` gap** — `ml/signals/aggregator.py` has no per-signal exception isolation. Low priority during off-season but should be done before next season.
- **Canary halt-detection gap** — `check_pick_drought` reports zero picks but can't tell if it's an intentional edge-based auto-halt or a silent crash. Could add `halt_active` field check from Phase 6 JSON.

---

## Useful one-liners

**Check which scheduler jobs are still failing tomorrow:**
```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="table(name,lastAttemptTime,status.code)" 2>&1 | \
  awk 'NR>1 && $3 != "" && $3 != "0" && $3 != "5" {print}'
```

**Force-run a scheduler job to test OIDC fix:**
```bash
gcloud scheduler jobs run JOB_NAME --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs describe JOB_NAME --location=us-west2 --project=nba-props-platform \
  --format="yaml(lastAttemptTime,status)"
```

**Rebuild canary image (required after edits to `bin/monitoring/pipeline_canary_queries.py`):**
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
