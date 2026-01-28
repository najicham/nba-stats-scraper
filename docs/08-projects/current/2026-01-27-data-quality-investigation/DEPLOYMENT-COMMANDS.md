# Data Quality Fix Deployment Commands

**Date**: 2026-01-27
**Status**: Ready for Deployment

---

## Pre-Deployment Checklist

- [ ] All changes committed to git
- [ ] No active games in progress (check schedule)
- [ ] Phase 3/4 processors not currently running

---

## Step 1: Apply Schema Changes to BigQuery

### 1A. Player Game Summary - New Columns

```bash
bq query --use_legacy_sql=false "
ALTER TABLE \`nba-props-platform.nba_analytics.player_game_summary\`

-- DNP Visibility (3 fields)
ADD COLUMN IF NOT EXISTS is_dnp BOOLEAN,
ADD COLUMN IF NOT EXISTS dnp_reason STRING,
ADD COLUMN IF NOT EXISTS dnp_reason_category STRING,

-- Partial Game Detection (3 fields)
ADD COLUMN IF NOT EXISTS is_partial_game_data BOOLEAN,
ADD COLUMN IF NOT EXISTS game_completeness_pct NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS game_status_at_processing STRING,

-- Usage Rate Validation (4 fields)
ADD COLUMN IF NOT EXISTS usage_rate_valid BOOLEAN,
ADD COLUMN IF NOT EXISTS usage_rate_capped NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS usage_rate_raw NUMERIC(6,2),
ADD COLUMN IF NOT EXISTS usage_rate_anomaly_reason STRING,

-- Duplicate Prevention (3 fields)
ADD COLUMN IF NOT EXISTS dedup_key STRING,
ADD COLUMN IF NOT EXISTS record_version INT64,
ADD COLUMN IF NOT EXISTS first_processed_at TIMESTAMP
"
```

### 1B. Team Offense Game Summary - New Columns

```bash
bq query --use_legacy_sql=false "
ALTER TABLE \`nba-props-platform.nba_analytics.team_offense_game_summary\`

-- Partial Game Detection (3 fields)
ADD COLUMN IF NOT EXISTS is_partial_game_data BOOLEAN,
ADD COLUMN IF NOT EXISTS game_completeness_pct NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS game_status_at_processing STRING
"
```

### 1C. Verify Schema Changes

```bash
# Check player_game_summary
bq show --schema --format=prettyjson nba-props-platform:nba_analytics.player_game_summary | grep -E "(is_dnp|usage_rate_valid|is_partial|dedup_key)"

# Check team_offense_game_summary
bq show --schema --format=prettyjson nba-props-platform:nba_analytics.team_offense_game_summary | grep -E "(is_partial)"
```

---

## Step 2: Deploy Phase 4 Precompute Service

### 2A. Build and Deploy to Cloud Run

```bash
cd /home/naji/code/nba-stats-scraper

# Deploy the updated main_precompute_service.py
gcloud run deploy nba-phase4-precompute-processors \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --allow-unauthenticated=false \
  --service-account=nba-pipeline-sa@nba-props-platform.iam.gserviceaccount.com \
  --memory=2Gi \
  --timeout=540 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=nba-props-platform"
```

### 2B. Verify Deployment

```bash
# Check service is running
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 --format="value(status.url)"

# Check latest revision
gcloud run revisions list --service=nba-phase4-precompute-processors --region=us-west2 --limit=3
```

---

## Step 3: Post-Deployment Verification

### 3A. Trigger a Test Run (Optional - Manual)

```bash
# Manually trigger Phase 4 with trigger_source tracking
curl -X POST "https://nba-phase4-precompute-processors-[hash]-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "AUTO",
    "trigger_source": "test_deployment",
    "correlation_id": "deploy-verify-2026-01-27"
  }'
```

### 3B. Check trigger_source After Next Automated Run

```bash
# Wait for next Phase 3 completion, then check:
bq query --use_legacy_sql=false "
SELECT
  data_date,
  trigger_source,
  COUNT(*) as runs,
  ARRAY_AGG(DISTINCT processor_name) as processors
FROM \`nba-props-platform.nba_orchestration.processor_run_history\`
WHERE phase = 'phase_4_precompute'
  AND data_date >= CURRENT_DATE()
GROUP BY data_date, trigger_source
ORDER BY data_date DESC"
```

**Expected**: `trigger_source = 'orchestrator'` for Pub/Sub triggered runs (not 'manual')

### 3C. Check New Schema Columns Are Queryable

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_dnp IS NOT NULL) as has_dnp,
  COUNTIF(usage_rate_valid IS NOT NULL) as has_usage_valid,
  COUNTIF(is_partial_game_data IS NOT NULL) as has_partial_flag
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
LIMIT 1"
```

**Expected**: All counts = 0 initially (fields are NULL until processors populate them)

---

## Step 4: P2 Cleanup (Optional - Run After Verification)

### 4A. Clear Invalid usage_rate Values

```bash
bq query --use_legacy_sql=false "
UPDATE \`nba-props-platform.nba_analytics.player_game_summary\`
SET usage_rate = NULL
WHERE usage_rate > 100
  AND game_date >= '2025-10-01'"
```

### 4B. Check for November Duplicates (Dry Run)

```bash
bq query --use_legacy_sql=false "
SELECT
  game_id,
  player_lookup,
  COUNT(*) as duplicate_count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2025-11-01' AND '2025-11-30'
GROUP BY game_id, player_lookup
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 20"
```

### 4C. Remove November Duplicates (If Found)

```bash
# Only run if 4B shows duplicates
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2025-11-01' AND '2025-11-30'
  AND (game_id, player_lookup, processed_at) NOT IN (
    SELECT game_id, player_lookup, MAX(processed_at)
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date BETWEEN '2025-11-01' AND '2025-11-30'
    GROUP BY game_id, player_lookup
  )"
```

---

## Rollback Plan

### Rollback Cloud Run (If Needed)

```bash
# List recent revisions
gcloud run revisions list --service=nba-phase4-precompute-processors --region=us-west2 --limit=5

# Rollback to previous revision
gcloud run services update-traffic nba-phase4-precompute-processors \
  --to-revisions=PREVIOUS_REVISION_NAME=100 \
  --region=us-west2
```

### Schema Rollback (Not Needed)

Schema changes are additive (new nullable columns). No rollback needed - columns can remain NULL if not used.

---

## Success Criteria

| Check | Expected | Command |
|-------|----------|---------|
| Schema columns exist | Columns queryable | `bq show --schema ...` |
| Service deployed | New revision active | `gcloud run revisions list ...` |
| trigger_source working | Shows 'orchestrator' | Check processor_run_history |
| No usage_rate > 100% | 0 records | Query player_game_summary |

---

## Next Session Prompt

After deployment, start a new chat with:

```
Continue data quality work from 2026-01-27 session.

Deployment status:
- [ ] Schema changes applied
- [ ] Cloud Run deployed
- [ ] trigger_source verified

Next steps:
1. Run /validate-daily to test new checks
2. Run /validate-historical 7 --anomalies to check for issues
3. Verify usage_rate anomalies are being flagged
4. Consider additional improvements

Reference: docs/08-projects/current/2026-01-27-data-quality-investigation/
```
