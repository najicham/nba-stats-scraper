# Next Session Start Prompt — 2026-02-13

## What Happened (Sessions 215–218 on Feb 12)

Five sessions of infrastructure recovery and cleanup:

- **Session 215**: Recovered Feb 11 pipeline (14 games stuck due to SAS@GSW status bug). Fixed boxscore trigger, Phase 3→4 format, race condition.
- **Session 216**: Fixed enrichment-trigger + daily-health-check Cloud Functions, paused BDL scheduler jobs, created 2 Cloud Build triggers.
- **Session 216B**: Found and fixed **23 Cloud Run services missing IAM** (`roles/run.invoker`), deployed 6 Cloud Functions, increased overnight-analytics deadline.
- **Session 217**: Fixed game_id format mismatch in boxscore completeness check (commit `3b7f0ab9`).
- **Session 218**: Morning checklist — confirmed Phase 3/4 data healthy, discovered IAM fixes did NOT reduce scheduler failures (still 15 failing, code 13 = service-level bugs).

## Morning Checklist

### 1. Verify Phase 4 populated all games yesterday

```bash
bq query --nouse_legacy_sql "
SELECT game_date, COUNT(DISTINCT game_id) as games, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY 1 ORDER BY 1 DESC"
```

Feb 12 had 3 games (MIL@OKC, POR@UTA, DAL@LAL). All 3 should have Phase 4 data now.

### 2. Check predictions and grading

```bash
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) as predictions FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1 DESC"
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) as graded FROM nba_predictions.prediction_accuracy WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1 ORDER BY 1 DESC"
```

### 3. Run daily validation

```bash
/validate-daily
```

### 4. Check scheduler failures

```bash
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2 --format=json > /tmp/sched.json && python3 << 'EOF'
import json
with open("/tmp/sched.json") as f:
    jobs = json.load(f)
failing = []
for j in jobs:
    if j.get("state") != "ENABLED": continue
    c = j.get("status",{}).get("code",0)
    if c != 0:
        failing.append((j.get("name","").split("/")[-1], c))
print(f"Failing: {len(failing)} (was 15 on Feb 12)")
for name, code in sorted(failing):
    print(f"  {name}: code {code}")
EOF
```

## Primary Task — Triage 15 Failing Scheduler Jobs

The IAM fixes from Session 216B passed auth but the services themselves return errors (code 13 = INTERNAL). For each failing job:

1. `gcloud scheduler jobs describe JOB_NAME --project=nba-props-platform --location=us-west2` — find target service URL
2. Check if target service has current code: `./bin/check-deployment-drift.sh --verbose`
3. Check Cloud Run logs for the actual error
4. Fix (redeploy, fix import, update container)

### Failing Jobs (as of Feb 12, 10:35 AM ET)

| Job | Code | Notes |
|-----|------|-------|
| `bigquery-daily-backup` | 13 | Known — gsutil not in container, rewrite to Python GCS client |
| `daily-health-check-8am-et` | 13 | Needs investigation |
| `daily-pipeline-health-summary` | 13 | Known — container startup import error |
| `daily-reconciliation` | 13 | Needs investigation |
| `firestore-state-cleanup` | 13 | Needs investigation |
| `live-freshness-monitor` | 13 | Known — stale deploy, missing `shared` module |
| `nba-grading-alerts-daily` | 14 | Redeployed in 216B, may self-resolve |
| `nba-grading-gap-detector` | 13 | Needs investigation |
| `registry-health-check` | 13 | Known — nba-reference-service old gcr.io image |
| `same-day-phase3` | 8 | Timeout on 600s deadline, non-critical (data arrives via overnight) |
| `same-day-predictions-tomorrow` | 5 | Needs investigation |
| `self-heal-predictions` | 4 | Known — SSL retry loop exhausts 600s timeout |
| `validate-freshness-check` | 3 | Redeployed in 216B, may have bug |
| `validation-post-overnight` | 13 | Needs investigation |
| `validation-pre-game-prep` | 13 | Needs investigation |

### Also Pending

- Wire Slack secrets to `daily-health-check` (see Session 216B handoff for command)
- `grading-readiness-monitor` Cloud Function in FAILED state
- `br-rosters-batch-daily` year param 2025 → 2026
- Cloud Build triggers for: transition-monitor, pipeline-health-summary, nba-grading-alerts, live-freshness-monitor, nba-reference-service
- Q43 shadow model monitoring (48.3% edge 3+ HR at n=29, needs 50+ for promotion decision)
- Monthly retrain consideration (champion 35+ days stale)

## Session Handoffs

- `docs/09-handoff/2026-02-12-SESSION-215-HANDOFF.md` — Pipeline recovery
- `docs/09-handoff/2026-02-12-SESSION-216-HANDOFF.md` — Enrichment + health check fixes
- `docs/09-handoff/2026-02-12-SESSION-216B-HANDOFF.md` — IAM sweep + Cloud Function deploys
- `docs/09-handoff/2026-02-12-SESSION-217-HANDOFF.md` — game_id format mismatch fix
- `docs/09-handoff/2026-02-12-SESSION-218-HANDOFF.md` — Morning checklist + scheduler audit
