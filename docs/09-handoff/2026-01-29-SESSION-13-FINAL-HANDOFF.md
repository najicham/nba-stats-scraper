# Session 13 Final Handoff - January 29, 2026

## Quick Start for Next Session

```bash
# 1. Read this handoff
# 2. Run daily validation
/validate-daily

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 4. If services are stale, deploy them (see Deployment Plan below)
```

---

## Session 13 Summary

### Completed
- **Data Fixes**: Deactivated 2,174 duplicate predictions, updated Firestore completion
- **Code Fixes**: 3 commits for DNP detection, prediction deduplication, validation script
- **Investigation**: Used agents to analyze 5 pipeline errors and spot check failures

### Pending Deployment
The following code changes are committed but NOT yet deployed:

| File | Change | Service to Deploy |
|------|--------|-------------------|
| `player_game_summary_processor.py` | DNP detection | nba-phase3-analytics-processors |
| `batch_staging_writer.py` | Prediction deduplication | prediction-coordinator |
| `validate_tonight_data.py` | Column names + system_id | N/A (local script) |

---

## Deployment Plan

### Prerequisites

1. **Verify you're on main branch with latest code**:
   ```bash
   git checkout main
   git pull origin main
   git log --oneline -5  # Should show Session 13 commits
   ```

2. **Check current deployment status**:
   ```bash
   ./bin/check-deployment-drift.sh --verbose
   ```

### Deployment Order (Critical!)

Services must be deployed in dependency order:

```
1. nba-phase1-scrapers (if changed)
2. nba-phase2-raw-processors (if changed)
3. nba-phase3-analytics-processors  ← DNP detection fix
4. nba-phase4-precompute-processors (if changed)
5. prediction-coordinator           ← Prediction dedup fix
6. prediction-worker (if changed)
```

### Deploy Commands

**Option A: Use the stale deployment script (Recommended)**

```bash
# Check what's stale
./bin/deploy-all-stale.sh --dry-run

# Deploy all stale services
./bin/deploy-all-stale.sh
```

**Option B: Manual deployment from root directory**

```bash
# Phase 3 Analytics (DNP detection)
gcloud run deploy nba-phase3-analytics-processors \
  --source=. \
  --region=us-west2 \
  --memory=2Gi \
  --timeout=540 \
  --set-env-vars="BUILD_COMMIT=$(git rev-parse --short HEAD),BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --quiet

# Prediction Coordinator (deduplication)
gcloud run deploy prediction-coordinator \
  --source=. \
  --region=us-west2 \
  --memory=2Gi \
  --timeout=540 \
  --set-env-vars="BUILD_COMMIT=$(git rev-parse --short HEAD),BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --quiet
```

**Note**: Deployments from subdirectories fail because they can't access `shared/`. Always deploy from repo root.

### Verify Deployment Success

```bash
# Check new revisions were created
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# Check health endpoints
curl -s https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health | jq .
curl -s https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health | jq .
```

---

## Post-Deployment Validation

### 1. Run Daily Validation

```bash
/validate-daily
# Or manually:
python scripts/validate_tonight_data.py --date $(date -d "yesterday" +%Y-%m-%d)
```

**Expected Results After Deployment**:
- ✓ Field Completeness: 100%
- ✓ Predictions: Should find active predictions
- ✓ No "duplicate predictions" warning (3.2x is expected for multiple lines)

### 2. Verify DNP Detection Working

```bash
# Trigger Phase 3 reprocessing for a test date
SERVICE_URL="https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)

MESSAGE_DATA=$(echo -n '{"output_table": "nba_raw.bdl_player_boxscores", "game_date": "2026-01-28", "status": "success"}' | base64 -w0)

curl -s -X POST "${SERVICE_URL}/process" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"message\": {\"data\": \"${MESSAGE_DATA}\"}}"

# Then verify DNP flags are set
bq query --use_legacy_sql=false "
SELECT player_lookup, is_dnp, dnp_reason, dnp_reason_category, minutes_played
FROM nba_analytics.player_game_summary
WHERE game_date = DATE('2026-01-28')
  AND is_dnp = TRUE
LIMIT 10"
```

### 3. Verify Prediction Deduplication Working

After predictions run for a new game date:

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(is_active = TRUE) as active,
  COUNT(DISTINCT player_lookup) as players,
  ROUND(COUNTIF(is_active = TRUE) * 1.0 / COUNT(DISTINCT player_lookup), 1) as active_per_player
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1
ORDER BY 1 DESC"
```

**Expected**: `active_per_player` should be ~3-5 (multiple lines per player, not 18+)

### 4. Check Error Logs

```bash
# Check for new errors in last hour
bq query --use_legacy_sql=false "
SELECT processor_name, event_type, COUNT(*) as count
FROM nba_orchestration.pipeline_event_log
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY 1, 2
ORDER BY count DESC"
```

---

## Documentation Guide

### Where to Find Docs

```
docs/
├── 00-start-here/           # START HERE - Daily checks, quick references
├── 01-architecture/         # System design, pipeline flow
├── 02-operations/           # Deployment, backfills, troubleshooting
├── 03-phases/               # Phase 1-6 specific documentation
├── 05-development/          # Development guides, patterns
├── 06-testing/              # Testing guides, spot checks
├── 07-monitoring/           # Dashboards, alerts
├── 08-projects/             # Active project tracking
├── 09-handoff/              # Session handoffs (YOU ARE HERE)
└── validation/              # Data validation framework
```

### Reading Order for New Sessions

| Priority | Document | Time | Purpose |
|----------|----------|------|---------|
| 1 | Latest handoff in `docs/09-handoff/` | 10 min | What was done, what's next |
| 2 | `docs/00-start-here/DAILY-SESSION-START.md` | 5 min | Health checks to run |
| 3 | `CLAUDE.md` (repo root) | 5 min | Session philosophy, key commands |
| 4 | `docs/01-architecture/quick-reference.md` | 5 min | Pipeline overview |
| 5 | `docs/02-operations/DEPLOYMENT.md` | 10 min | If deploying |

### Key Reference Documents

| Topic | Document |
|-------|----------|
| Architecture | `docs/01-architecture/pipeline-design.md` |
| Deployment | `docs/02-operations/DEPLOYMENT.md` |
| Backfills | `docs/02-operations/backfill-guide.md` |
| Troubleshooting | `docs/02-operations/troubleshooting-matrix.md` |
| Phase 3 Analytics | `docs/03-phases/phase3/` |
| Phase 4 Precompute | `docs/03-phases/phase4/` |
| Predictions | `docs/03-phases/phase5/` |
| Testing | `docs/06-testing/SPOT-CHECK-SYSTEM.md` |

---

## Using Agents to Study and Improve the System

### Agent Types Available

| Agent Type | Use Case | Example Prompt |
|------------|----------|----------------|
| `Explore` | Research, find patterns | "Find all BigQuery writes in Phase 3" |
| `general-purpose` | Fix bugs, implement features | "Fix the null check in processor.py" |
| `Bash` | Git, gcloud, bq commands | Direct bash execution |

### Investigation Patterns

**Pattern 1: Parallel Investigation**

When facing multiple issues, spawn agents in parallel:

```
# In Claude Code, send a single message with multiple Task calls:

Task(subagent_type="Explore", prompt="Find all places where is_dnp is set")
Task(subagent_type="Explore", prompt="Find how prediction deduplication works")
Task(subagent_type="general-purpose", prompt="Check error logs for last hour")
```

**Pattern 2: Deep Dive on Error**

```
Task(subagent_type="general-purpose", prompt="""
Investigate this error: [paste error message]

1. Find where it occurs in the codebase
2. Understand the root cause
3. Check if it's a known issue
4. Propose a fix with specific code changes
""")
```

**Pattern 3: System Improvement Discovery**

```
Task(subagent_type="Explore", prompt="""
Analyze the [component] for potential improvements:

1. Find all related files
2. Identify patterns that could be optimized
3. Look for code duplication
4. Check for missing error handling
5. List improvement opportunities with file:line references
""")
```

### Improvement Areas to Investigate

| Area | Investigation Prompt |
|------|---------------------|
| **Spot Check Accuracy** | "Find why spot check usage_rate calculations differ from processor calculations. Check scripts/spot_check_data_accuracy.py vs player_game_summary_processor.py" |
| **Error Noise Reduction** | "Find all places that log 'No data extracted' errors and propose making them INFO level when expected" |
| **Duplicate Team Stats** | "Investigate why team_offense_game_summary has duplicate entries with different game_id formats" |
| **Completion Tracking** | "Find why Firestore completion tracking doesn't update during backfill_mode processing" |
| **Morning Health Check** | "Update bin/monitoring/morning_health_check.sh to exclude DNP players from coverage calculation" |

### Running Validation After Changes

After any code changes, run:

```bash
# 1. Syntax check
python -m py_compile [changed_file.py]

# 2. Run related tests
pytest tests/[related_test].py -v

# 3. Run spot checks
python scripts/spot_check_data_accuracy.py --samples 5

# 4. If deploying, run pre-deployment validation
python bin/validation/pre_deployment_check.py
```

---

## Known Issues & Workarounds

### Issue 1: Deployment from Subdirectory Fails

**Symptom**: `COPY failed: file not found in build context`

**Cause**: Dockerfiles reference `shared/` which isn't in subdirectory context

**Workaround**: Always deploy from repo root with `--source=.`

### Issue 2: "No data extracted" Errors

**Symptom**: PlayerGameSummaryProcessor logs errors for dates with no games

**Cause**: Processor runs before games finish or on off-days

**Status**: Expected behavior, not blocking. Future fix: Change to INFO level.

### Issue 3: Spot Check Accuracy ~60%

**Symptom**: Usage rate spot checks fail for some players

**Cause**: Spot check script doesn't use quality_tier filtering like the processor does

**Status**: False positive. Stored values are correct. Fix needed in spot check script.

### Issue 4: 3.2x Predictions Per Player Warning

**Symptom**: Validation flags "duplicate predictions"

**Cause**: Multiple betting lines per player (17.5, 18.5, 19.5, etc.)

**Status**: Expected behavior. This is points-only predictions with multiple line options.

---

## GCP Resources Reference

| Resource | Value |
|----------|-------|
| Project | nba-props-platform |
| Region | us-west2 |
| Registry | us-west2-docker.pkg.dev/nba-props-platform/nba-props |

### Key Services

| Service | URL |
|---------|-----|
| Phase 1 | nba-phase1-scrapers |
| Phase 2 | nba-phase2-raw-processors |
| Phase 3 | nba-phase3-analytics-processors |
| Phase 4 | nba-phase4-precompute-processors |
| Coordinator | prediction-coordinator |
| Worker | prediction-worker |

### BigQuery Datasets

| Dataset | Purpose |
|---------|---------|
| nba_raw | Raw scraped data |
| nba_analytics | Processed analytics |
| nba_precompute | ML features, cache |
| nba_predictions | Predictions, grading |
| nba_orchestration | Pipeline logs, events |

---

## Session 13 Commits

```
2703e301 fix: Update validation script system_id and improve detection
c553a087 fix: Correct column names in validation script
07684bcb fix: Add DNP detection and prediction deduplication
```

---

## Next Session Checklist

- [ ] Read this handoff
- [ ] Run `/validate-daily`
- [ ] Check deployment drift: `./bin/check-deployment-drift.sh --verbose`
- [ ] If stale, deploy services (see Deployment Plan)
- [ ] Verify DNP detection working (if Phase 3 deployed)
- [ ] Verify prediction dedup working (if coordinator deployed)
- [ ] Check error logs for new issues
- [ ] Use agents to investigate any issues found

---

*Created: 2026-01-29 10:30 AM PT*
*Author: Claude Opus 4.5*
