# Deployment Drift Prevention Plan

**Created:** 2026-02-03 (Session 98)
**Status:** Implementation Required

## Problem Statement

Deployment drift occurs when code is committed but not deployed, causing:
1. Bug fixes not taking effect in production
2. False confidence that issues are resolved
3. Recurring problems that were "already fixed"

**Examples:**
- Session 97: Slack alerts module added, but Phase 3 service not redeployed
- Session 81-82: Critical edge filter fix not deployed for hours
- Session 64: Backfill ran with 12-hour-old code

## Current State

| Component | Status | Gap |
|-----------|--------|-----|
| `morning_deployment_check.py` | ✅ Exists | Not scheduled as cron job |
| `check-deployment-drift.sh` | ✅ Exists | Manual only |
| `morning-deployment-check` Cloud Function | ✅ Deployed | No scheduler trigger |
| Auto-deploy on commit | ❌ Missing | No CI/CD pipeline |
| Pre-commit deployment reminder | ❌ Missing | No hooks |

## Prevention Layers

### Layer 1: Automated Morning Alert (IMMEDIATE)

**Goal:** Get Slack alert at 6 AM ET if any service is stale

**Implementation:**
```bash
# Create scheduler job to run morning check
gcloud scheduler jobs create http morning-deployment-check-job \
  --location=us-west2 \
  --schedule="0 11 * * *" \
  --uri="https://us-west2-nba-props-platform.cloudfunctions.net/morning-deployment-check" \
  --http-method=POST \
  --oidc-service-account-email=nba-props-platform@nba-props-platform.iam.gserviceaccount.com \
  --description="Daily deployment drift check at 6 AM ET"
```

**Timeline:** Implement today

### Layer 2: Post-Session Deployment Checklist (IMMEDIATE)

**Goal:** Remind to deploy after every session

**Add to CLAUDE.md:**
```markdown
## End of Session Checklist

Before ending a session where code was changed:

1. [ ] Check deployment drift: `./bin/check-deployment-drift.sh`
2. [ ] Deploy any stale services: `./bin/deploy-service.sh <service>`
3. [ ] Verify deployment: `./bin/whats-deployed.sh`
4. [ ] Create handoff document
```

**Timeline:** Add today

### Layer 3: CI/CD Auto-Deploy (MEDIUM TERM)

**Goal:** Automatically deploy services when code changes

**Options:**

| Option | Complexity | Risk | Recommendation |
|--------|------------|------|----------------|
| GitHub Actions | Medium | Low | ✅ Recommended |
| Cloud Build triggers | Medium | Low | Alternative |
| Manual + alerts | Low | Medium | Current state |

**GitHub Actions workflow:**
```yaml
# .github/workflows/auto-deploy.yml
name: Auto Deploy

on:
  push:
    branches: [main]
    paths:
      - 'predictions/worker/**'
      - 'predictions/coordinator/**'
      - 'data_processors/**'
      - 'shared/**'

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      worker: ${{ steps.changes.outputs.worker }}
      coordinator: ${{ steps.changes.outputs.coordinator }}
      phase3: ${{ steps.changes.outputs.phase3 }}
      phase4: ${{ steps.changes.outputs.phase4 }}
    steps:
      - uses: dorny/paths-filter@v2
        id: changes
        with:
          filters: |
            worker:
              - 'predictions/worker/**'
              - 'shared/**'
            coordinator:
              - 'predictions/coordinator/**'
              - 'shared/**'
            phase3:
              - 'data_processors/analytics/**'
              - 'shared/**'
            phase4:
              - 'data_processors/precompute/**'
              - 'shared/**'

  deploy-worker:
    needs: detect-changes
    if: needs.detect-changes.outputs.worker == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - run: ./bin/deploy-service.sh prediction-worker

  # Similar jobs for other services...
```

**Timeline:** Implement this week

### Layer 4: Deployment Verification in Health Check (IMMEDIATE)

**Goal:** `/validate-daily` should check deployment drift first

**Already exists in skill, but make it P0 CRITICAL:**
- If ANY critical service is stale, stop validation and alert
- Don't proceed with other checks until resolved

**Timeline:** Already implemented in validate-daily skill

### Layer 5: Pre-Commit Hook Warning (LOW PRIORITY)

**Goal:** Warn developer before committing if services will be stale

```bash
# .pre-commit-hooks/deployment-reminder.sh
#!/bin/bash

# Check if any service-related files are being committed
changed_files=$(git diff --cached --name-only)

if echo "$changed_files" | grep -qE "^(predictions/|data_processors/|shared/)"; then
    echo ""
    echo "⚠️  REMINDER: You're changing code that affects Cloud Run services."
    echo ""
    echo "After pushing, remember to deploy affected services:"
    echo "  ./bin/check-deployment-drift.sh"
    echo "  ./bin/deploy-service.sh <service-name>"
    echo ""
fi
```

**Timeline:** Nice to have

## Fix for Today's False Alarm

### Phase 3 Firestore Completion Tracking

The Firestore `phase3_completion` document shows 1/5 processors, but BigQuery tables have fresh data. This means:

1. Processors ARE running and writing data
2. Completion tracking in Firestore is NOT being updated

**Root cause investigation needed:**
- Check if Phase 3 processors call `update_phase_completion()`
- Check if Firestore writes are failing silently
- Check if wrong document ID is being used (date format)

**Immediate mitigation:**
- Update `/validate-daily` to also check BigQuery table timestamps
- If tables have recent data, don't flag as critical even if Firestore shows incomplete

## Monitoring Improvements

### Add BigQuery-Based Completion Check

```sql
-- Check if Phase 3 ran by looking at actual data
SELECT
  'player_game_summary' as processor,
  MAX(processed_at) as last_run,
  CASE WHEN MAX(processed_at) > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
       THEN 'HEALTHY' ELSE 'STALE' END as status
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)

UNION ALL

-- Similar for other Phase 3 tables...
```

## Action Items

### Immediate (Today)

1. [ ] Create scheduler job for morning deployment check
2. [ ] Add deployment checklist to CLAUDE.md
3. [ ] Fix Firestore completion tracking (or add BigQuery fallback)
4. [ ] Deploy Phase 3 and coordinator (in progress)

### This Week

1. [ ] Implement GitHub Actions auto-deploy
2. [ ] Add BigQuery-based health check fallback
3. [ ] Document root cause of Firestore tracking gap

### Ongoing

1. [ ] Monitor deployment drift alerts
2. [ ] Review and improve CI/CD pipeline
3. [ ] Track drift incidents and response times
