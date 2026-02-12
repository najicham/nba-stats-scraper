# Next Session Start Prompt — 2026-02-13

## What Happened (Sessions 215–219 on Feb 12)

Six sessions of infrastructure recovery and scheduler triage:

- **Session 215**: Recovered Feb 11 pipeline (14 games stuck due to SAS@GSW status bug)
- **Session 216**: Fixed enrichment-trigger + daily-health-check Cloud Functions
- **Session 216B**: Found and fixed **23 Cloud Run services missing IAM**, deployed 6 Cloud Functions
- **Session 217**: Fixed game_id format mismatch in boxscore completeness check
- **Session 218**: Morning checklist — confirmed Phase 3/4 data healthy, discovered IAM fixes did NOT reduce scheduler failures
- **Session 219**: **Triaged all 15 failing scheduler jobs, fixed 7 (15 → 8).** Key pattern: reporter functions returning 400/500 for data findings. Added 6 Cloud Functions to deployment drift checker.

## Morning Checklist

### 1. Check scheduler jobs (was 15, now 8 failing)

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
print(f"Failing: {len(failing)} (was 8 on Feb 12)")
for name, code in sorted(failing):
    print(f"  {name}: code {code}")
EOF
```

### 2. Verify Phase 4 populated all games

```bash
bq query --nouse_legacy_sql "
SELECT game_date, COUNT(DISTINCT game_id) as games, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY 1 ORDER BY 1 DESC"
```

Feb 12 had 3 games (MIL@OKC, POR@UTA, DAL@LAL). All 3 should have Phase 4 data now.

### 3. Check predictions and grading

```bash
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) as predictions FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1 DESC"
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) as graded FROM nba_predictions.prediction_accuracy WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1 ORDER BY 1 DESC"
```

### 4. Run daily validation

```bash
/validate-daily
```

## Primary Task — Fix Remaining 8 Failing Scheduler Jobs

### Remaining Failures (Priority Order)

| Job | Code | Root Cause | Recommended Fix |
|-----|------|-----------|-----------------|
| `bigquery-daily-backup` | 13 | gsutil not in container | Rewrite `cloud_functions/bigquery_backup/main.py` to use Python GCS client |
| `live-freshness-monitor` | 13 | `No module named 'shared'` | Redeploy as Gen2 with shared/ module included |
| `nba-grading-alerts-daily` | 14 | Service can't start (malformed response) | Check logs, rebuild from source |
| `registry-health-check` | 13 | Old gcr.io image for nba-reference-service | Rebuild nba-reference-service from repo |
| `firestore-state-cleanup` | 13 | transition-monitor endpoint error | Check /cleanup endpoint implementation |
| `same-day-phase3` | 8 | Resource exhausted / timeout | Increase memory to 2Gi, timeout to 600s |
| `same-day-predictions-tomorrow` | 5 | /start returns 404 on prediction-coordinator | Check if /start route still exists |
| `self-heal-predictions` | 4 | SSL retry loop exceeds 600s | Known issue — may need to pause or rewrite |

### Also Pending

- Wire Slack secrets to `daily-health-check` (already deployed with secrets from Secret Manager)
- `grading-readiness-monitor` Cloud Function in FAILED state
- `br-rosters-batch-daily` year param 2025 → 2026
- Cloud Build triggers for: transition-monitor, pipeline-health-summary, nba-grading-alerts, live-freshness-monitor, nba-reference-service
- Q43 shadow model monitoring (48.3% edge 3+ HR at n=29, needs 50+ for promotion decision)
- Monthly retrain consideration (champion 35+ days stale)
- Add scheduler health phase to `/validate-daily` skill
- Document Cloud Function deploy pattern (always include shared/ in deploy package)

## Session Handoffs

- `docs/09-handoff/2026-02-12-SESSION-219-HANDOFF.md` — Scheduler job triage (15→8)
- `docs/09-handoff/2026-02-12-SESSION-218-HANDOFF.md` — Morning checklist + scheduler audit
- `docs/09-handoff/2026-02-12-SESSION-217-HANDOFF.md` — game_id format mismatch fix
- `docs/09-handoff/2026-02-12-SESSION-216B-HANDOFF.md` — IAM sweep + Cloud Function deploys
- `docs/09-handoff/2026-02-12-SESSION-215-HANDOFF.md` — Pipeline recovery
