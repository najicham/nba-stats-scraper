# Session 510 Handoff — 2026-04-04

**Context:** Session 510 was a GCP cost reduction execution session. Sessions 509+510 together
deployed ~$270-290/mo in savings from a $886/mo baseline (was $994/mo before Session 509).
This handoff is for a verification session — check that changes worked, nothing broke,
and billing is trending down.

---

## What Happened This Session

### Changes Deployed (commit `e4e83e71`, `951686ed`, `d8c85354`, `fc17e08d`)

**GCP (live):**
- Log exclusion `exclude-health-checks` created — filters `GET /health*` logs from Cloud Run
- 8 stale/failing/duplicate scheduler jobs deleted (see list below)
- Canary scheduler `nba-pipeline-canary-trigger` updated → `CANARY_TIER=critical` (15-min)
- New scheduler `nba-pipeline-canary-routine-trigger` created → `CANARY_TIER=routine` (60-min)
- AR cleanup: 168 image tags deleted from Artifact Registry (274→105 tags in `nba-props` repo)

**Code:**
- `data_processors/publishing/player_profile_exporter.py` — 3 more unfiltered `prediction_accuracy`
  queries fixed (lines 221, 282, 547). Session 509 fixed lines 183+262 but missed these.
- `bin/monitoring/pipeline_canary_queries.py` — `CANARY_TIER` env var support. 12 critical
  checks run every 15min; 17 routine checks run every 60min.
- `bin/cleanup-artifact-registry.sh` — fixed 3 bugs found during execution:
  1. Multi-tag comma-separated TAGS column handling
  2. Subshell counter scoping (temp file fix)
  3. Double-path bug in delete command (`IMAGE` already contains full registry path)

**Deleted scheduler jobs:**
| Job | Reason |
|-----|--------|
| `mlb-live-boxscores` | PAUSED, never run |
| `br-rosters-batch-daily` | PAUSED, never run |
| `nba-daily-summary-scheduler` | Duplicate of `nba-daily-summary-prod` |
| `mlb-props-morning` | Duplicate of `mlb-bp-props-morning` (f7p3g7f6ya URL) |
| `mlb-props-pregame` | Duplicate of `mlb-bp-props-pregame` (f7p3g7f6ya URL) |
| `mlb-game-lines-morning` | code=13 FAILING (legacy 756957797294 URL) |
| `mlb-overnight-results` | code=13 FAILING (legacy URL) |
| `mlb-umpire-assignments` | code=13 FAILING (legacy URL) |

---

## Priority 1: Verify Canary Tier Is Working

This is the highest-risk change. The `CANARY_TIER` env var is passed via Cloud Run Jobs v1 API
message body override. If the override isn't being applied, the job runs with `CANARY_TIER="all"`
(safe fallback — no regression, just no savings from tiering).

```bash
# Check recent canary executions
gcloud run jobs executions list --job=nba-pipeline-canary \
  --region=us-west2 --project=nba-props-platform \
  --limit=5 --format="table(name,completionTime,succeeded)"

# Check logs for CANARY_TIER value being applied
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-pipeline-canary" AND textPayload=~"CANARY_TIER"' \
  --project=nba-props-platform --limit=10 --format="value(timestamp,textPayload)"
```

**Expected:** You should see log lines like:
- `Starting pipeline canary queries (CANARY_TIER=critical)` — from 15-min job
- `Starting pipeline canary queries (CANARY_TIER=routine)` — from 60-min job

**If CANARY_TIER=all in both:** The v1 API doesn't support message body env overrides. Fix:
create a second Cloud Run Job `nba-pipeline-canary-routine` with `CANARY_TIER=routine` baked
in as an env var, point the hourly scheduler at it.

---

## Priority 2: Check Billing Trend

The Session 509 changes took 48-72h to show in billing. Changes from both sessions
(deployed 2026-04-01 to 2026-04-03) should now be visible.

```bash
bq query --nouse_legacy_sql '
SELECT DATE(_PARTITIONTIME) as date, ROUND(SUM(cost), 2) as daily_cost
FROM `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
GROUP BY 1 ORDER BY 1 DESC'
```

**Expected trend:**
- Pre-Session 509 (before 2026-04-01): ~$33-47/day
- Post-Session 509 (2026-04-01/02): ~$26-28/day (confirmed)
- Post-Session 510 (2026-04-03+): should be ~$20-24/day

If still ~$26-28/day, the Session 510 code changes (exporter filters) haven't hit the billing
export yet — wait another 24h before diagnosing.

---

## Priority 3: Check Pipeline Health

Verify nothing broke from the scheduler deletions or exporter changes.

```bash
# Any errors in exporter since deploy?
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR AND timestamp>="2026-04-03T22:00:00Z"' \
  --project=nba-props-platform --limit=20 \
  --format="table(timestamp,resource.labels.service_name,textPayload)"

# Verify picks are still flowing (no drought from unintended side effects)
bq query --nouse_legacy_sql '
SELECT game_date, COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1 ORDER BY 1 DESC'

# Check yesterday grading is fresh
bq query --nouse_legacy_sql '
SELECT MAX(game_date) as latest_graded,
       COUNTIF(prediction_correct IS NOT NULL) as graded_count
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= CURRENT_DATE() - 3'
```

---

## Priority 4: Pending Cost Actions (Not Done Yet)

These were identified but NOT executed in Sessions 509/510:

| Action | Est. Savings | Notes |
|--------|-------------|-------|
| **Infinitecase backend downsize** (4Gi/2CPU) | ~$57/mo | One command: `gcloud run services update infinitecase-backend --memory=4Gi --cpu=2 --region=us-central1 --project=infinite-case` — separate project decision |
| **Terraform logging exclusions** | ~$25-35/mo | `terraform` not installed on dev machine. Can apply via REST API (same as health-check exclusion). Or install terraform. |
| **Fix remaining unfiltered exporter queries** | Unknown | Agent 2 found `player_profile_exporter.py` still has `_query_game_log` (line 338) scanning `player_game_summary` with no partition filter. Low priority. |
| **Phase 3 scheduler dedup** | ~$5-10/mo | `overnight-analytics-6am-et` and `daily-yesterday-analytics` fire 30min apart with overlapping processors. Delete one. |
| **Tiered canary 2nd job fix** (if v1 override doesn't work) | ~$32/mo | Create `nba-pipeline-canary-routine` Cloud Run Job with `CANARY_TIER=routine` env var baked in |
| **Schedule weekly AR cleanup** | Prevents regrowth | `gcloud scheduler jobs create http ar-weekly-cleanup --schedule="0 3 * * 0"` targeting a Cloud Run Job that runs `cleanup-artifact-registry.sh --execute` |

---

## Expected Cumulative Savings

| Bucket | Savings | Status |
|--------|---------|--------|
| Session 509 live (Phase 3/4 CPU, player_profile_exporter) | ~$209/mo | ✅ Live |
| Session 510 (log exclusion, canary tier, AR cleanup, 3 more exporter queries) | ~$60-82/mo | ✅ Live |
| **Total deployed** | **~$270-290/mo** | |
| Pending (infinitecase, terraform, P3 dedup) | ~$87-102/mo | ⏳ Not done |
| **Projected bill** | **~$595-615/mo** (from $886) | After all pending |

---

## Key Files Modified This Session

| File | Change |
|------|--------|
| `data_processors/publishing/player_profile_exporter.py` | 730-day filter on 3 queries (lines 221, 282, 547) |
| `bin/monitoring/pipeline_canary_queries.py` | `CANARY_TIER` env var — 12 critical / 17 routine |
| `bin/cleanup-artifact-registry.sh` | 3 bug fixes — now actually works |

## Reference

- **Session 509 handoff:** `docs/09-handoff/2026-04-03-SESSION-509-HANDOFF.md`
- **Full cost reduction plan:** `docs/08-projects/current/gcp-cost-optimization/03-COST-REDUCTION-PLAN-2026-04-02.md`
- **Billing table:** `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
- **Canary code:** `bin/monitoring/pipeline_canary_queries.py` — `CRITICAL_CHECKS` frozenset near line 1537
