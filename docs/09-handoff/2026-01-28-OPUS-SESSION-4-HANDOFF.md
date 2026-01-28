# Opus Session 4 Handoff - January 28, 2026

## Session Philosophy

**CRITICAL**: This session established key principles for maintaining system health:

1. **Understand root causes, not just symptoms** - Every error should trigger investigation into WHY it happened
2. **Prevent recurrence** - Add validation, tests, automation to stop issues from happening again
3. **Use agents liberally** - Spawn multiple agents to investigate, fix, and search in parallel
4. **Keep documentation updated** - Every fix should update relevant docs
5. **Fix the system, not just the code** - Schema issues need schema validation, deployment drift needs automation

---

## Quick Start for Next Session

### 1. Read This Document First
This handoff contains critical context about system state and philosophy.

### 2. Run Daily Validation
```bash
# Check system health
/validate-daily

# Check deployment drift (new!)
./bin/check-deployment-drift.sh --verbose
```

### 3. Check for Open Issues
```bash
# GitHub issues created by drift check workflow
gh issue list --label deployment-drift
```

### 4. Use Agents for Investigation
When encountering issues, spawn multiple agents in parallel:
```
Task tool with subagent_type=Explore: "Find all places where X happens"
Task tool with subagent_type=general-purpose: "Fix the issue at Y"
```

---

## Session Summary

This session performed a **comprehensive system audit** fixing 12 issues and implementing 3 major prevention mechanisms.

### Fixes Applied

| Category | Issue | File(s) | Commit |
|----------|-------|---------|--------|
| Schema | teammate_* fields missing | BigQuery ALTER TABLE | Runtime |
| Schema | Feature array mismatch (34 vs 33) | `ml_feature_store_processor.py` | 75d95700 |
| Validation | Fatigue score -1.0 rejected | `data_loaders.py` | 926cbc02 |
| Quota | ExecutionLogger single-row writes | `execution_logger.py` | 926cbc02 |
| Quota | Run history single-row writes | `run_history.py` | 75d95700 |
| Quota | Env monitor single-row writes | `env_monitor.py` | a88b1191 |
| Quota | Registry processor single-row writes | `registry_processor_base.py` | a5a0bdab |
| Quota | Pipeline execution log single-row writes | `pipeline_execution_log.py` | a5a0bdab |
| Bug | Metrics NoneType error | `metrics_utils.py` | 75d95700 |
| Deploy | prediction-worker stale | Cloud Run 00016-pm5 | Runtime |
| Deploy | nba-phase1-scrapers 17 commits behind | Cloud Run 00012-77p | Runtime |
| Deploy | prediction-coordinator stale | Cloud Run 00093-gr2 | Runtime |
| Deploy | nba-phase4-precompute-processors stale | Cloud Run 00061-8c7 | Runtime |
| Data | 36 missing PBP games | BigDataBall backfill | Runtime |

### Prevention Mechanisms Added

| Mechanism | File | Purpose |
|-----------|------|---------|
| Schema validation hook | `.pre-commit-hooks/validate_schema_fields.py` | Blocks commits with schema mismatches |
| Drift check workflow | `.github/workflows/check-deployment-drift.yml` | Daily check + GitHub issues |
| Pre-commit config | `.pre-commit-config.yaml` | Enables schema validation |

---

## Root Causes Identified

### 1. Schema Mismatch
**Issue**: Code added `teammate_*` fields but BigQuery schema wasn't updated.
**Root Cause**: No validation that code fields match BigQuery schema.
**Prevention**: Pre-commit hook + CI/CD check (hook implemented, CI/CD TODO).

### 2. Deployment Drift
**Issue**: nba-phase1-scrapers was 17 commits behind.
**Root Cause**: All deployments are manual, no automation or alerting.
**Prevention**: GitHub workflow creates issues when drift detected. Auto-deploy TODO.

### 3. Scraper Gaps (Jan 20, 22, 23)
**Issue**: BigDataBall PBP scraper had zero attempts on 3 dates.
**Root Cause**:
- Cloud Scheduler URL misconfiguration (pointed to wrong service)
- Missing Python dependency (`googleapiclient`)
**Prevention**: Scheduler health alerts TODO, URL validation in deploy TODO.

### 4. Quota Exhaustion
**Issue**: Hitting BigQuery partition modification quota.
**Root Cause**: `load_table_from_json([single_record])` pattern used widely.
**Prevention**: Migrated to BigQueryBatchWriter. More components TODO.

---

## Current System Status

### Predictions Pipeline ✅
```
Jan 28: 2,629 predictions for 144 players across 9 games
```

### Services Deployed ✅
| Service | Revision | Status |
|---------|----------|--------|
| prediction-worker | 00016-pm5 | Current |
| prediction-coordinator | 00093-gr2 | Current |
| nba-phase1-scrapers | 00012-77p | Current |
| nba-phase4-precompute-processors | 00061-8c7 | Current |

### Schema Status ✅
- `player_prop_predictions`: All 62 fields present
- `ml_feature_store_v2`: 34 features (FEATURE_COUNT fixed)

### Data Backfill ✅
- BigDataBall PBP: 43 games downloaded to GCS
- Will flow to BigQuery when pipeline processes new files

---

## Known Issues Still to Address

### HIGH Priority

| Issue | Location | Description |
|-------|----------|-------------|
| 5 more quota-risk components | See list below | Still using single-row writes |
| Pre-commit hook detected 8 schema gaps | See output | Fields in code but not in schema SQL file |
| Missing test coverage | `predictions/worker/` | No unit tests for prediction pipeline |
| Silent failures in Firestore | `batch_state_manager.py` | Stream operations lack error logging |

### Quota-Risk Components to Migrate

| File | Line | Priority |
|------|------|----------|
| `data_processors/raw/nbacom/nbac_gamebook_processor.py` | 648 | HIGH |
| `shared/utils/player_registry/resolution_cache.py` | 188 | MEDIUM |
| `data_processors/precompute/precompute_base.py` | 1008 | MEDIUM |
| `data_processors/precompute/base/mixins/quality_mixin.py` | 91 | MEDIUM |
| `validation/base_validator.py` | 1284 | LOW |

### Schema Fields to Add to SQL File

The pre-commit hook detected these fields are written in code but missing from `schemas/bigquery/predictions/01_player_prop_predictions.sql`:

```
feature_importance
filter_reason
is_actionable
line_minutes_before_game
model_version
teammate_opportunity_score
teammate_out_starters
teammate_usage_boost
```

Note: These fields EXIST in BigQuery (we added them at runtime) but are missing from the schema SQL file. Update the SQL file to match.

---

## Documentation Locations

### Key Documentation Directories

| Directory | Purpose |
|-----------|---------|
| `docs/01-architecture/` | System architecture, data flow |
| `docs/02-operations/` | Runbooks, deployment, troubleshooting |
| `docs/03-phases/` | Phase-specific documentation |
| `docs/05-development/` | Development guides, best practices |
| `docs/06-testing/` | Test guides, spot check system |
| `docs/08-projects/` | Current and completed projects |
| `docs/09-handoff/` | Session handoff documents (like this one) |

### Critical Files to Know

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Claude-specific context (needs creation - currently missing!) |
| `README.md` | Project overview (update after major changes) |
| `docs/02-operations/MORNING-VALIDATION-GUIDE.md` | Daily validation procedures |
| `docs/02-operations/troubleshooting-matrix.md` | Error → solution mapping |
| `bin/check-deployment-drift.sh` | Check for stale deployments |

### Documentation Gaps Found

1. **CLAUDE.md is missing** - README references it but file doesn't exist
2. **Deployment drift not in morning guide** - Add to daily checklist
3. **Feature array mismatch not documented** - Add to known issues
4. **Schema v4.0 fields not in docs** - Update schema reference

---

## How to Use Agents Effectively

### When to Use Agents

| Scenario | Agent Type | Example Prompt |
|----------|------------|----------------|
| Find code patterns | Explore | "Find all places where load_table_from_json is called with single row" |
| Investigate issue | Explore | "Investigate why predictions aren't being written to BigQuery" |
| Fix specific bug | general-purpose | "Fix the NoneType error in metrics_utils.py" |
| Run commands | Bash | Direct bash for git, gcloud, bq commands |
| Deploy services | general-purpose | "Redeploy these 3 stale services" |

### Parallel Agent Pattern

When facing multiple issues, spawn agents in parallel:

```
<Task: Investigate issue A>
<Task: Fix issue B>
<Task: Search for issue C>
<Task: Check documentation for D>
```

This session used 8 parallel agents to:
- Redeploy stale services
- Backfill PBP data
- Audit schema
- Fix env_monitor
- Investigate 4 root causes

### Agent Best Practices

1. **Give detailed prompts** - Include file paths, line numbers, expected behavior
2. **Use Explore for research** - Don't code, just investigate
3. **Use general-purpose for fixes** - Can read, write, execute
4. **Check agent results** - Verify fixes, commit changes
5. **Track with handoff docs** - Document what agents found

---

## Prevention Mechanisms

### Schema Validation (Implemented)

```bash
# Run manually
python .pre-commit-hooks/validate_schema_fields.py

# Runs automatically on commit
pre-commit run validate-schema-fields
```

### Deployment Drift Check (Implemented)

```bash
# Manual check
./bin/check-deployment-drift.sh --verbose

# Automatic: GitHub workflow runs daily at 6 AM UTC
# Creates issues with label "deployment-drift"
```

### Quota Monitoring (Partial)

```bash
# Check current quota usage
gcloud logging read "resource.type=bigquery_resource AND protoPayload.status.message:quota" \
  --project=nba-props-platform --limit=10
```

---

## Improvement Opportunities Found

### Code Quality Issues (21 found)

| Category | Count | Severity |
|----------|-------|----------|
| Error Handling Gaps | 5 | HIGH |
| Missing Logging | 4 | HIGH-MEDIUM |
| Hardcoded Values | 2 | MEDIUM |
| Missing Tests | 1 | HIGH |
| Performance Issues | 2 | MEDIUM |

Top issues to address:
1. Add test coverage for `predictions/worker/` prediction pipeline
2. Add error logging to Firestore stream operations in `batch_state_manager.py`
3. Fix N+1 query pattern in `instance_manager.py`
4. Move hardcoded timeouts to environment variables

### Documentation Gaps (28 found)

Critical gaps:
1. CLAUDE.md missing (README references it)
2. Deployment drift not in morning validation guide
3. Feature array mismatch not documented
4. Session 4 improvements not in main docs

---

## Commits Made This Session

```
a5a0bdab feat: Add prevention mechanisms for schema, deployment, and quota issues
a88b1191 fix: Add buffered writes to env_monitor for quota efficiency
75d95700 fix: Feature array mismatch, metrics bug, and quota issues
926cbc02 fix: Buffer execution logs and allow -1 fatigue score
```

---

## Next Session Checklist

### Immediate

- [ ] Run `/validate-daily` to check system health
- [ ] Run `./bin/check-deployment-drift.sh --verbose` to check deployments
- [ ] Check if PBP data flowed from GCS to BigQuery
- [ ] Review any GitHub issues with `deployment-drift` label

### This Week

- [ ] Create CLAUDE.md file (currently missing, README references it)
- [ ] Update schema SQL file with 8 missing fields
- [ ] Migrate remaining 5 quota-risk components to BigQueryBatchWriter
- [ ] Add deployment drift check to MORNING-VALIDATION-GUIDE.md
- [ ] Add test coverage for prediction pipeline

### Backlog

- [ ] Implement auto-deploy on merge to main (GitHub workflow)
- [ ] Add Scheduler health alerts (for scraper gaps)
- [ ] Add CI/CD schema validation step
- [ ] Document feature array mismatch root cause and fix
- [ ] Consolidate hardcoded timeouts to environment variables

---

## Key Learnings

1. **Single-row BigQuery writes are dangerous** - Use BigQueryBatchWriter or streaming inserts
2. **Manual deployments drift** - Automate with GitHub Actions
3. **Schema changes need validation** - Pre-commit hooks catch mismatches
4. **Agents are powerful** - Use them liberally for parallel investigation
5. **Document everything** - Future sessions need context

---

## Files Changed This Session

### New Files
- `.pre-commit-hooks/validate_schema_fields.py`
- `.github/workflows/check-deployment-drift.yml`

### Modified Files
- `.pre-commit-config.yaml`
- `predictions/worker/execution_logger.py`
- `predictions/worker/data_loaders.py`
- `predictions/worker/env_monitor.py`
- `predictions/coordinator/run_history.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `data_processors/reference/base/registry_processor_base.py`
- `monitoring/pipeline_execution_log.py`
- `shared/utils/metrics_utils.py`

---

*Session ended: 2026-01-28 ~13:00 PST*
*Total commits: 4*
*Issues fixed: 12*
*Prevention mechanisms: 3*
*Agent tasks spawned: 16*
