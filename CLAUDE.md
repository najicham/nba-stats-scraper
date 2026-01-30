# Claude Code Instructions

This file contains instructions and context for Claude Code sessions working on the NBA Stats Scraper project.

## Session Philosophy

**Every session should follow these principles:**

1. **Understand root causes, not just symptoms** - When fixing a bug, investigate WHY it happened
2. **Prevent recurrence** - Add validation, tests, or automation to stop issues from happening again
3. **Use agents liberally** - Spawn multiple Task agents in parallel for investigation and fixes
4. **Keep documentation updated** - Update handoff docs, runbooks, and code comments
5. **Fix the system, not just the code** - Schema issues need schema validation, deployment drift needs automation

## Quick Start

### 1. Read the Latest Handoff
```bash
ls -la docs/09-handoff/ | tail -5
# Read the most recent handoff document
```

### 2. Run Daily Validation
```bash
/validate-daily
```

### 3. Check Deployment Drift
```bash
./bin/check-deployment-drift.sh --verbose
```

## Using Agents Effectively

### Parallel Investigation Pattern
When facing multiple issues, spawn agents in parallel:

```
Task(subagent_type="Explore", prompt="Find all places where X happens")
Task(subagent_type="Explore", prompt="Investigate why Y is failing")
Task(subagent_type="general-purpose", prompt="Fix the bug in Z file")
Task(subagent_type="general-purpose", prompt="Migrate component A to use pattern B")
```

### Agent Types and Use Cases

| Agent Type | Use Case | Example |
|------------|----------|---------|
| `Explore` | Research, find patterns, understand code | "Find all BigQuery single-row writes" |
| `general-purpose` | Fix bugs, implement features, run commands | "Fix the NoneType error in metrics_utils.py" |
| `Bash` | Git operations, gcloud, bq queries | Direct bash commands |

### Best Practices

1. **Give detailed prompts** - Include file paths, line numbers, expected behavior
2. **Use Explore for research first** - Understand before changing
3. **Check agent results** - Verify fixes, commit changes
4. **Track in handoff docs** - Document what agents found

## Project Structure

```
nba-stats-scraper/
├── predictions/           # Phase 5 - Prediction worker and coordinator
│   ├── worker/           # Prediction generation
│   └── coordinator/      # Batch orchestration
├── data_processors/      # Phase 2-4 data processing
│   ├── raw/              # Phase 2 - Raw data processors
│   ├── analytics/        # Phase 3 - Analytics processors
│   └── precompute/       # Phase 4 - Precompute processors
├── scrapers/             # Phase 1 - Data scrapers
├── orchestration/        # Phase transition orchestrators
├── shared/               # Shared utilities
├── bin/                  # Scripts and tools
├── schemas/              # BigQuery schema definitions
└── docs/                 # Documentation
```

## Documentation Locations

| Directory | Purpose |
|-----------|---------|
| `docs/01-architecture/` | System architecture, data flow |
| `docs/02-operations/` | Runbooks, deployment, troubleshooting |
| `docs/03-phases/` | Phase-specific documentation |
| `docs/05-development/` | Development guides, best practices |
| `docs/09-handoff/` | Session handoff documents |

## Deployment Patterns

### CRITICAL: Always deploy from repo root

All service Dockerfiles expect to be built from the repository root because they need access to `shared/` modules. Building from within the service directory will fail.

**Correct:**
```bash
./bin/deploy-service.sh prediction-worker
```

**Wrong:**
```bash
cd predictions/worker && gcloud run deploy --source .  # WILL FAIL - no shared/ access
```

### Deployment Script

Use `./bin/deploy-service.sh <service-name>` for all deployments:

| Service | Dockerfile |
|---------|------------|
| prediction-coordinator | predictions/coordinator/Dockerfile |
| prediction-worker | predictions/worker/Dockerfile |
| nba-phase3-analytics-processors | data_processors/analytics/Dockerfile |
| nba-phase4-precompute-processors | data_processors/precompute/Dockerfile |

The script:
1. Builds from repo root with correct Dockerfile
2. Tags with commit hash for traceability
3. Sets BUILD_COMMIT and BUILD_TIMESTAMP env vars
4. Deploys to Cloud Run
5. Shows recent logs for verification

### Startup Verification

Services should use the startup verification utility to log deployment info:

```python
from shared.utils.startup_verification import verify_startup

# At service startup
verify_startup(
    expected_module="coordinator",
    service_name="prediction-coordinator"
)
```

This helps detect deployment issues where wrong code is deployed.

## Key Commands

### Validation
```bash
# Daily validation skill
/validate-daily

# Historical validation
/validate-historical 2026-01-27 2026-01-28

# Check deployment drift
./bin/check-deployment-drift.sh --verbose
```

### BigQuery
```bash
# Check predictions
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1"

# Check feature store
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT player_lookup) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = CURRENT_DATE()"
```

### Grading Tables

**IMPORTANT:** Use the correct grading table:

| Table | Use For | Data Range |
|-------|---------|------------|
| `prediction_accuracy` | **All grading queries** | Nov 2021 - Present (419K+ records) |
| `prediction_grades` | DEPRECATED - do not use | Jan 2026 only (9K records) |

Always query `prediction_accuracy` for grading validation, accuracy metrics, and ML analysis.

### Deployments
```bash
# Check current revisions
gcloud run services describe SERVICE_NAME --region=us-west2 --format="value(status.latestReadyRevisionName)"

# Deploy a service
gcloud run deploy SERVICE_NAME --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/SERVICE_NAME:latest --region=us-west2
```

### Logs
```bash
# Prediction worker logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker"' --limit=50

# Check for errors
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' --limit=20
```

## Common Issues and Fixes

### Schema Mismatch
**Symptom**: BigQuery writes fail with "Invalid field" error
**Cause**: Code writes fields that don't exist in BigQuery schema
**Fix**:
1. Run `python .pre-commit-hooks/validate_schema_fields.py` to detect
2. Add missing fields with `ALTER TABLE ... ADD COLUMN`
3. Update schema SQL file in `schemas/bigquery/`

### Deployment Drift
**Symptom**: Service missing recent bug fixes
**Cause**: Manual deployments, no automation
**Fix**:
1. Run `./bin/check-deployment-drift.sh --verbose`
2. Rebuild and deploy stale services
3. GitHub workflow will create issues for future drift

### Quota Exceeded
**Symptom**: "Exceeded rate limits: too many partition modifications"
**Cause**: Single-row `load_table_from_json` calls
**Fix**:
1. Use `BigQueryBatchWriter` from `shared/utils/bigquery_batch_writer.py`
2. Or use streaming inserts with `insert_rows_json`
3. Or buffer writes and flush in batches

### Feature Validation Errors
**Symptom**: "fatigue_score=-1.0 outside range"
**Cause**: Validation rejects sentinel values
**Fix**: Update validation in `data_loaders.py` to allow -1 as sentinel

## Prevention Mechanisms

### Pre-commit Hooks
```yaml
# Schema validation - blocks commits with schema mismatches
- id: validate-schema-fields
  entry: python .pre-commit-hooks/validate_schema_fields.py
```

### GitHub Workflows
```yaml
# Deployment drift check - runs daily, creates issues
.github/workflows/check-deployment-drift.yml
```

### Batching Patterns
```python
# Use BigQueryBatchWriter for high-frequency writes
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(record)  # Auto-batches and flushes
```

## Handoff Document Template

When ending a session, create a handoff document at `docs/09-handoff/YYYY-MM-DD-SESSION-N-HANDOFF.md`:

```markdown
# Session N Handoff - [Date]

## Session Summary
[What was accomplished]

## Fixes Applied
[Table of fixes with files and commits]

## Root Causes Identified
[Why issues happened, not just what was fixed]

## Prevention Mechanisms Added
[Validation, automation, tests added]

## Known Issues Still to Address
[What's left for future sessions]

## Next Session Checklist
[Prioritized TODO list]

## Key Learnings
[Insights for future sessions]
```

## Project Conventions

### Commit Messages
```
type: Short description

Longer explanation if needed.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Code Style
- Python 3.11+
- Type hints for public APIs
- Docstrings for classes and complex functions
- Logging with structured fields

### Testing
```bash
# Run tests
pytest tests/

# Run specific test
pytest tests/path/to/test.py -v
```

## GCP Resources

| Resource | Location |
|----------|----------|
| Project | nba-props-platform |
| Region | us-west2 |
| Registry | us-west2-docker.pkg.dev/nba-props-platform/nba-props |
| BigQuery | nba_predictions, nba_analytics, nba_raw, nba_orchestration |

## Contact and Escalation

For issues outside Claude's scope:
- Check `docs/02-operations/troubleshooting-matrix.md`
- Review recent handoff documents
- Check GitHub issues for known problems
