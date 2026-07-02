# Session 543 Handoff — Scheduler self-heal verification + OIDC audit

**Date:** 2026-04-18 (end of S542)
**Prior sessions:** S541 fixed Apr 17 MLB outage. S542 validated the fix and audited the monitoring/canary layer.

> **Read first:** [S542](./2026-04-18-SESSION-542-HANDOFF.md) for full detail on what was fixed this session.

---

## TL;DR

S542 fixed 8 bugs. The canary now shows 1 remaining failure: `failing_jobs: 4 > 3`. Those 4 jobs have fixes deployed and will self-heal on their next scheduled runs (all by tomorrow afternoon ET). Your first task is to confirm they cleared. Then do the OIDC audit that S539 flagged.

---

## Part 1 — Verify 4 scheduler jobs self-healed (~10 min)

Run this query tomorrow after 1 PM ET:

```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="table(name,lastAttemptTime,status.code,state)" 2>&1 | \
  awk 'NR>1 && $3 != "" && $3 != "0" && $3 != "5" {print}'
```

**Expected:** The 4 jobs below should no longer appear (or appear with code=0):

| Job | Fix deployed | Expected clear time |
|---|---|---|
| `mlb-game-lines-morning` | `date`→`game_date` param + TODAY resolution | ~10:30 AM ET Apr 19 |
| `mlb-umpire-assignments` | `self.download_data`→`self.decoded_data` | ~11:30 AM ET Apr 19 |
| `mlb-props-morning` | OIDC auth added | ~10:30 AM ET Apr 19 |
| `mlb-props-pregame` | OIDC auth added | ~12:30 PM ET Apr 19 |

If any still appear as failing after their scheduled time, check their logs:
```bash
gcloud logging read 'resource.labels.service_name="mlb-phase1-scrapers" AND timestamp>="2026-04-19T14:00:00Z"' \
  --project=nba-props-platform --limit=20 --format="value(timestamp,severity,textPayload)" | head -30
```

Also verify the canary passes:
```bash
gcloud run jobs execute nba-pipeline-canary --region=us-west2 --project=nba-props-platform --wait
gcloud logging read 'resource.labels.job_name="nba-pipeline-canary"' \
  --project=nba-props-platform --limit=30 --format="json" --freshness=5m 2>&1 | python3 -c "
import json,sys; logs=json.load(sys.stdin)
for l in reversed(logs):
    msg=l.get('textPayload','')
    if any(k in msg for k in ['Found','FAIL','PASS','Error']):
        print(l['timestamp'][:19], msg[:200])
"
```

**Expected:** `0 canary failures` or just `failing_jobs: 0 > 3` (which means the check passes).

---

## Part 2 — OIDC audit for remaining MLB schedulers

S539 flagged ~21 MLB schedulers needing OIDC audit. S542 fixed 4 (`mlb-live-boxscores`, `mlb-props-morning`, `mlb-props-pregame`, `nba-playoffs-shadow-activate`). ~17 remain.

### Find all jobs missing OIDC

```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="json" | python3 -c "
import json,sys
jobs = json.load(sys.stdin)
for j in jobs:
    http = j.get('httpTarget', {})
    name = j['name'].split('/')[-1]
    state = j.get('state','')
    uri = http.get('uri','')
    has_oidc = 'oidcToken' in http
    has_run = bool(j.get('lastAttemptTime'))
    if not has_oidc and 'mlb' in name.lower() and state == 'ENABLED' and has_run:
        print(f'NO_OIDC  {name}  →  {uri}')
" 2>&1 | sort
```

For each job targeting a Cloud Run URL (`*.run.app`), add OIDC:
```bash
gcloud scheduler jobs update http JOB_NAME \
  --location=us-west2 --project=nba-props-platform \
  --oidc-service-account-email=756957797294-compute@developer.gserviceaccount.com \
  --oidc-token-audience=TARGET_URL
```

The `audience` should match the job's `uri` exactly. Use the SA `756957797294-compute@developer.gserviceaccount.com` for all Cloud Run targets.

**Exclude** jobs targeting:
- Pub/Sub (not HTTP)
- Cloud Workflows (different auth)
- Non-Cloud Run endpoints

---

## Part 3 — `mlb-live-boxscores` BDL investigation (optional)

The `mlb-live-boxscores` scheduler is PAUSED. It fires every 5 minutes during games but the BDL `/mlb/v1/box_scores/live` endpoint returns 401 despite a valid `BDL_API_KEY` on the service.

**Diagnosis:** Either the BDL key doesn't have MLB live data access (different subscription tier), or the Authorization header format is wrong for this endpoint.

**To investigate:**
```bash
# Test the BDL MLB endpoint directly
BDL_KEY=$(gcloud run services describe mlb-phase1-scrapers --region=us-west2 \
  --project=nba-props-platform --format="json" | \
  python3 -c "import json,sys; envs={e['name']:e.get('value','') for e in json.load(sys.stdin)['spec']['template']['spec']['containers'][0]['env']}; print(envs.get('BDL_API_KEY',''))")
curl -H "Authorization: $BDL_KEY" "https://api.balldontlie.io/mlb/v1/box_scores/live" | head -100
```

If 401: the key lacks MLB live access. Options: upgrade BDL subscription, or replace with `mlb_game_feed` (MLB Stats API) which is already registered and has similar data.

If the fix is straightforward, re-enable the scheduler (`gcloud scheduler jobs resume mlb-live-boxscores ...`).

---

## State at session end (S542)

- **`nba-stats-scraper` main:** `6ce2e715` (includes S542 handoff)
- **Commits this session (S542):** `1dc86ce5`, `60afd7e8`, `fc94d88b`
- **`mlb-phase1-scrapers`:** revision `00017-*` live with all scraper fixes
- **Canary image:** rebuilt 4× this session, latest at ~21:37 UTC Apr 18
- **MLB pipeline:** healthy. Apr 18: 28 preds, 1 BB pick (Sandy Alcantara OVER), 112 filter audits
- **NBA pipeline:** playoffs, auto-halted, 0 picks expected. All models BLOCKED.

### Paused schedulers (DO NOT unpause without reason)
- `mlb-live-boxscores` — BDL 401 unresolved
- `nba-playoffs-shadow-activate` — annual job (April 14 only), ran this year, re-enable before Apr 14, 2027

### Open items from S539/S540 (still untouched)
- S539 cold-start hypothesis for MLB schedulers — deprioritized
- S540 frontend nice-to-haves (`LeaderboardSkeleton`, `PitcherModal` lint)
- `mlb_umpire_assignments` fix verification (same as Part 1 check above)

---

## Quick start for next session

```bash
# 1. Check if the 4 scheduler jobs self-healed
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="table(name,status.code)" | awk '$2 != "" && $2 != "0" && $2 != "5" {print}'

# 2. Run canary
gcloud run jobs execute nba-pipeline-canary --region=us-west2 --project=nba-props-platform --wait

# 3. Check MLB pipeline health
bq query --use_legacy_sql=false --location=US --format=pretty '
SELECT game_date,
  (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` WHERE game_date=d.game_date) preds,
  (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` WHERE game_date=d.game_date) bb
FROM UNNEST([DATE("2026-04-18"), DATE("2026-04-19")]) d(game_date) ORDER BY 1 DESC'
```
