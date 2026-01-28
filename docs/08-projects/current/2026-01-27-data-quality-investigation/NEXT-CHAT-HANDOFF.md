# Next Chat Handoff - Data Quality Deployment & Validation

**Date**: 2026-01-27
**Commit**: 3417d737

---

## Copy This Prompt to Start Next Chat

```
Continue data quality work from 2026-01-27 session (commit 3417d737).

## What Was Done
- Fixed Phase 4 trigger_source extraction (P0 critical)
- Added 16 new schema columns for data quality tracking
- Created 3 new monitoring queries
- Enhanced /validate-daily and /validate-historical skills
- All changes committed, ready for deployment

## Deployment Needed
1. Apply BigQuery schema changes (ALTER TABLE)
2. Deploy main_precompute_service.py to Cloud Run
3. Optionally run P2 cleanup queries

## Deployment Commands
See: docs/08-projects/current/2026-01-27-data-quality-investigation/DEPLOYMENT-COMMANDS.md

## After Deployment
1. Run /validate-daily to test new checks work
2. Run /validate-historical 7 --anomalies
3. Verify trigger_source shows 'orchestrator' after next game day
4. Consider additional improvements

## Key Files Changed
- data_processors/precompute/main_precompute_service.py (trigger_source fix)
- schemas/bigquery/analytics/player_game_summary_tables.sql (16 new columns)
- schemas/bigquery/analytics/team_offense_game_summary_tables.sql (3 new columns)
- validation/configs/analytics/player_game_summary.yaml (3 new rules)
- .claude/skills/validate-daily/SKILL.md (new checks)
- .claude/skills/validate-historical/SKILL.md (new checks)

## Reference Docs
- docs/08-projects/current/2026-01-27-data-quality-investigation/IMPLEMENTATION-PROGRESS.md
- docs/08-projects/current/2026-01-27-data-quality-investigation/DEPLOYMENT-COMMANDS.md
```

---

## Quick Deploy Commands (Copy-Paste Ready)

### Step 1: Schema Changes

```bash
# Player game summary - 13 new columns
bq query --use_legacy_sql=false "
ALTER TABLE \`nba-props-platform.nba_analytics.player_game_summary\`
ADD COLUMN IF NOT EXISTS is_dnp BOOLEAN,
ADD COLUMN IF NOT EXISTS dnp_reason STRING,
ADD COLUMN IF NOT EXISTS dnp_reason_category STRING,
ADD COLUMN IF NOT EXISTS is_partial_game_data BOOLEAN,
ADD COLUMN IF NOT EXISTS game_completeness_pct NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS game_status_at_processing STRING,
ADD COLUMN IF NOT EXISTS usage_rate_valid BOOLEAN,
ADD COLUMN IF NOT EXISTS usage_rate_capped NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS usage_rate_raw NUMERIC(6,2),
ADD COLUMN IF NOT EXISTS usage_rate_anomaly_reason STRING,
ADD COLUMN IF NOT EXISTS dedup_key STRING,
ADD COLUMN IF NOT EXISTS record_version INT64,
ADD COLUMN IF NOT EXISTS first_processed_at TIMESTAMP"

# Team offense - 3 new columns
bq query --use_legacy_sql=false "
ALTER TABLE \`nba-props-platform.nba_analytics.team_offense_game_summary\`
ADD COLUMN IF NOT EXISTS is_partial_game_data BOOLEAN,
ADD COLUMN IF NOT EXISTS game_completeness_pct NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS game_status_at_processing STRING"
```

### Step 2: Cloud Run Deploy

```bash
cd /home/naji/code/nba-stats-scraper

gcloud run deploy nba-phase4-precompute-processors \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --memory=2Gi \
  --timeout=540
```

### Step 3: Verify

```bash
# Check schema
bq show --schema nba-props-platform:nba_analytics.player_game_summary | grep is_dnp

# Check deployment
gcloud run revisions list --service=nba-phase4-precompute-processors --region=us-west2 --limit=2
```
