# Cross-Source Reconciliation - Setup Guide

**Created**: 2026-01-27
**Status**: Implementation Complete - Ready for Deployment
**Related**: [Investigation Findings](03-INVESTIGATION-FINDINGS.md)

---

## Overview

This guide walks through deploying the automated cross-source reconciliation system that compares NBA.com official stats against Ball Don't Lie (BDL) stats daily.

## What Was Implemented

### 1. BigQuery View
**File**: `monitoring/bigquery_views/source_reconciliation_daily.sql`

- Compares NBA.com vs BDL stats for yesterday
- Joins on `player_lookup` and `game_date`
- Flags discrepancies in points, rebounds, assists
- Assigns health status: MATCH, MINOR_DIFF, WARNING, CRITICAL

### 2. Scheduled Query
**File**: `monitoring/scheduled_queries/source_reconciliation.sql`

- Runs daily at 8:00 AM ET (after overnight processing)
- Queries the view and writes results to monitoring table
- Stores CRITICAL/WARNING/MINOR_DIFF records + 10% sample of matches
- Enables historical tracking and trend analysis

### 3. Validation Integration
**File**: `.claude/skills/validate-daily/SKILL.md`

- Added **Phase 3C: Cross-Source Reconciliation** section
- Queries reconciliation view during daily validation
- Reports CRITICAL/WARNING discrepancies with actionable guidance
- Documents expected thresholds and investigation procedures

---

## Deployment Steps

### Step 1: Create BigQuery View

```bash
# From project root
bq query --use_legacy_sql=false < monitoring/bigquery_views/source_reconciliation_daily.sql
```

**Verify**:
```bash
bq query --use_legacy_sql=false "
  SELECT health_status, COUNT(*) as count
  FROM \`nba-props-platform.nba_monitoring.source_reconciliation_daily\`
  GROUP BY health_status
"
```

Expected: Should return results (if yesterday had games) or empty (if no games/data).

---

### Step 2: Create Destination Table for Scheduled Query

```bash
bq mk --table \
  --time_partitioning_field=run_timestamp \
  --time_partitioning_type=DAY \
  --time_partitioning_expiration=7776000 \
  --clustering_fields=health_status,game_date,team_abbr \
  --description="Daily source reconciliation results (NBA.com vs BDL)" \
  nba-props-platform:nba_monitoring.source_reconciliation_results \
  run_timestamp:TIMESTAMP,game_date:DATE,game_id:STRING,player_lookup:STRING,player_name:STRING,team_abbr:STRING,starter:BOOLEAN,presence_status:STRING,nbac_points:INT64,nbac_assists:INT64,nbac_rebounds:INT64,bdl_points:INT64,bdl_assists:INT64,bdl_rebounds:INT64,point_diff:INT64,assist_diff:INT64,rebound_diff:INT64,health_status:STRING,discrepancy_summary:STRING,stat_comparison:STRING,checked_at:TIMESTAMP
```

**Verify**:
```bash
bq show nba-props-platform:nba_monitoring.source_reconciliation_results
```

---

### Step 3: Create Scheduled Query

**Option A: Using BigQuery Console** (Recommended for first-time setup)

1. Go to [BigQuery Console](https://console.cloud.google.com/bigquery)
2. Click **Scheduled queries** in left navigation
3. Click **+ CREATE SCHEDULED QUERY**
4. Configuration:
   - **Name**: `Source Reconciliation Daily`
   - **Schedule**: `0 8 * * *` (Daily at 8:00 AM)
   - **Time zone**: `America/New_York`
   - **Dataset**: `nba_monitoring`
   - **Table**: `source_reconciliation_results`
   - **Write preference**: `Append to table`
5. Paste query from `monitoring/scheduled_queries/source_reconciliation.sql`
6. Click **Save**

**Option B: Using gcloud CLI**

```bash
# First, read the query into a variable
QUERY=$(cat monitoring/scheduled_queries/source_reconciliation.sql)

# Create the scheduled query
bq query \
  --use_legacy_sql=false \
  --schedule="0 8 * * *" \
  --location=us-west2 \
  --display_name="Source Reconciliation Daily" \
  --destination_table=nba-props-platform:nba_monitoring.source_reconciliation_results \
  --append_table=true \
  --replace=true \
  "$QUERY"
```

**Verify**:
```bash
# List scheduled queries
bq ls --transfer_config --transfer_location=us-west2 --project_id=nba-props-platform

# Or view in console
# https://console.cloud.google.com/bigquery/scheduled-queries
```

---

### Step 4: Test Manually Before Automation

Before letting it run automatically, test manually:

```bash
# Run the query manually to verify it works
bq query --use_legacy_sql=false < monitoring/scheduled_queries/source_reconciliation.sql
```

**Check results**:
```bash
bq query --use_legacy_sql=false "
  SELECT
    health_status,
    COUNT(*) as player_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
  FROM \`nba-props-platform.nba_monitoring.source_reconciliation_results\`
  WHERE DATE(run_timestamp) = CURRENT_DATE()
  GROUP BY health_status
  ORDER BY FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH')
"
```

---

### Step 5: Update `/validate-daily` Skill

✅ **Already complete** - Phase 3C section added to `.claude/skills/validate-daily/SKILL.md`

**Test it**:
```bash
# Run validate-daily and verify Phase 3C appears in output
# (or manually run the queries from Phase 3C section)
```

---

## Health Thresholds

| Status | Criteria | Expected % | Priority |
|--------|----------|-----------|----------|
| **MATCH** | All stats identical | ≥95% | ✅ Good |
| **MINOR_DIFF** | Difference of 1-2 in any stat | <5% | ⚪ Acceptable |
| **WARNING** | Assists/rebounds diff >2 | <1% | 🟡 Investigate |
| **CRITICAL** | Points diff >2 | 0% | 🔴 Immediate |

---

## Monitoring & Alerting

### Daily Validation (Automated via `/validate-daily`)

When you run `/validate-daily` for yesterday's results, Phase 3C will:
1. Query the reconciliation view
2. Show summary by health_status
3. Display CRITICAL/WARNING details if found
4. Provide investigation guidance

### Manual Spot Checks

```bash
# View today's reconciliation summary
bq query --use_legacy_sql=false "
  SELECT health_status, COUNT(*) as count
  FROM \`nba-props-platform.nba_monitoring.source_reconciliation_daily\`
  GROUP BY health_status
"

# View critical issues
bq query --use_legacy_sql=false "
  SELECT player_name, team_abbr, discrepancy_summary, stat_comparison
  FROM \`nba-props-platform.nba_monitoring.source_reconciliation_daily\`
  WHERE health_status = 'CRITICAL'
"

# Historical trend (last 7 days)
bq query --use_legacy_sql=false "
  SELECT
    DATE(run_timestamp) as date,
    health_status,
    COUNT(*) as count
  FROM \`nba-props-platform.nba_monitoring.source_reconciliation_results\`
  WHERE DATE(run_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY date, health_status
  ORDER BY date DESC, health_status
"
```

---

## Investigation Procedures

### If CRITICAL Issues Found (Points Diff >2)

1. **Verify which source is correct**:
   - Check game footage or official play-by-play
   - Compare against third source (ESPN) if available

2. **Determine scope**:
   - Single player or multiple players?
   - Single game or multiple games?
   - Single team or multiple teams?

3. **Check for source updates**:
   - NBA.com sometimes retroactively corrects stats
   - BDL may have stale data or API issues

4. **Remember**: **NBA.com is source of truth** for discrepancies

5. **Impact assessment**:
   - Does this affect prop settlement?
   - Are predictions using the incorrect source?

### If WARNING Issues Found (Assists/Rebounds Diff >2)

1. **Review scoring judgment calls**:
   - Assists and rebounds can be subjective
   - Different official scorers may score differently

2. **Check for patterns**:
   - Specific teams or arenas?
   - Specific types of plays?

3. **Document but likely not blocking**:
   - Minor discrepancies are acceptable
   - NBA.com is still source of truth

### If Match Rate <95%

1. **Check data freshness**:
   - Did both scrapers run successfully?
   - Is one source delayed?

2. **Check player name mappings**:
   - Recent trades or name changes?
   - `player_lookup` normalization issues?

3. **Review recent code changes**:
   - Any changes to player name normalization?
   - Any changes to scraper logic?

---

## Source Priority

When discrepancies exist:

1. **NBA.com** - Official source of truth (authoritative)
2. **BDL** - Primary real-time source (faster, used for most analytics)
3. **ESPN** - Backup validation source

**Use reconciliation to validate BDL reliability**, not to replace it.

---

## Files Created

| File | Purpose |
|------|---------|
| `monitoring/bigquery_views/source_reconciliation_daily.sql` | View comparing yesterday's stats |
| `monitoring/scheduled_queries/source_reconciliation.sql` | Scheduled query configuration |
| `monitoring/scheduled_queries/README.md` | Documentation for scheduled queries |
| `.claude/skills/validate-daily/SKILL.md` (updated) | Added Phase 3C section |
| This file | Setup and deployment guide |

---

## Next Steps

1. ✅ Deploy BigQuery view (Step 1)
2. ✅ Create destination table (Step 2)
3. ✅ Create scheduled query (Step 3)
4. ✅ Test manually (Step 4)
5. ⏳ Wait for first automated run (tomorrow 8 AM)
6. ⏳ Run `/validate-daily` to see Phase 3C in action
7. ⏳ Monitor for first week to establish baseline

---

## Expected Baseline Results

Based on investigation findings:

- **Match rate**: Should be 95%+ (most players have identical stats)
- **Minor differences**: <5% (acceptable 1-2 point differences)
- **Critical issues**: <1% (rare, investigate immediately)

If baseline differs significantly, investigate data quality or scraper issues.

---

## Related Documentation

- [Investigation Findings](03-INVESTIGATION-FINDINGS.md) - Background research
- [Master Action List](../01-MASTER-ACTION-LIST.md) - Full project tracker
- `monitoring/scheduled_queries/README.md` - Scheduled query documentation
- `/validate-daily` skill - Daily validation procedures
