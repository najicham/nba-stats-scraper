# Creating Missing NBA Monitors

**Date**: 2026-01-28
**Purpose**: Step-by-step guide to create missing NBA monitoring jobs
**Dependencies**: MLB implementations exist and can be adapted

---

## Overview

Based on gap analysis, we need to create:
1. **NBA Gap Detection Job** - Daily monitoring for processing gaps
2. **NBA Schedule Validator Job** - Daily schedule validation

Both exist for MLB and can be adapted for NBA.

---

## 1. Create NBA Gap Detection Job

### Background
- MLB has `mlb-gap-detection-daily` running at 1 PM
- Checks GCS files vs BigQuery records
- Alerts on processing failures
- Source: `monitoring/mlb/mlb_gap_detection.py`

### Steps

#### A. Create NBA Gap Detector

**File**: `monitoring/nba/nba_gap_detection.py`

**Based on**: `monitoring/mlb/mlb_gap_detection.py`

**Changes needed**:
```python
# Replace MLB_SOURCES with NBA_SOURCES
NBA_SOURCES = {
    'odds_api_props': {
        'name': 'Odds API Player Props',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'odds-api/nba/player-props/{date}/',
        'bq_table': 'nba_raw.odds_api_player_points_props',
        'date_field': 'game_date',
        'critical': True,
    },
    'bdl_boxscores': {
        'name': 'Ball Dont Lie Boxscores',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'balldontlie/nba/boxscores/{date}/',
        'bq_table': 'nba_raw.bdl_player_box_scores',
        'date_field': 'game_date',
        'critical': True,
    },
    'nbac_player_boxscores': {
        'name': 'NBA.com Player Boxscores',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'nbacom/player-boxscores/{date}/',
        'bq_table': 'nba_raw.nbac_player_boxscores',
        'date_field': 'game_date',
        'critical': True,
    },
    'nbac_schedule': {
        'name': 'NBA.com Schedule',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'nbacom/schedule/{date}/',
        'bq_table': 'nba_raw.nbac_schedule_source_daily',
        'date_field': 'game_date',
        'critical': True,
    },
    'bigdataball_lineups': {
        'name': 'BigDataBall Lineups',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'bigdataball/lineups/{date}/',
        'bq_table': 'nba_raw.bigdataball_lineups',
        'date_field': 'game_date',
        'critical': False,
    },
    # Add more sources as needed
}
```

**Quick creation**:
```bash
# Copy MLB version as starting point
cp monitoring/mlb/mlb_gap_detection.py monitoring/nba/nba_gap_detection.py

# Edit to replace MLB_SOURCES with NBA_SOURCES
# Update class name from MlbGapDetector to NbaGapDetector
# Update alert category from 'mlb_processing_gap' to 'nba_processing_gap'
```

#### B. Create Dockerfile

**File**: `deployment/cloud-run/nba/monitoring/gap-detection/Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy gap detection code
COPY monitoring/nba/nba_gap_detection.py .
COPY shared/ ./shared/

# Set entry point
ENTRYPOINT ["python", "nba_gap_detection.py"]
```

#### C. Create Cloud Run Job Configuration

**File**: `deployment/cloud-run/nba/monitoring/nba-gap-detection.yaml`

```yaml
apiVersion: run.googleapis.com/v1
kind: Job
metadata:
  name: nba-gap-detection
  labels:
    cloud.googleapis.com/location: us-west2
    sport: nba
    type: monitoring
    component: gap-detection
spec:
  template:
    metadata:
      annotations:
        run.googleapis.com/execution-environment: gen2
    spec:
      taskCount: 1
      template:
        spec:
          maxRetries: 2
          timeoutSeconds: 600  # 10 minutes
          serviceAccountName: nba-monitoring-sa@nba-props-platform.iam.gserviceaccount.com
          containers:
          - image: us-west2-docker.pkg.dev/nba-props-platform/nba-monitoring/gap-detection:latest
            env:
            - name: GCP_PROJECT_ID
              value: "nba-props-platform"
            - name: PYTHONPATH
              value: "."
            - name: ENVIRONMENT
              value: "production"
            resources:
              limits:
                cpu: "1000m"
                memory: "512Mi"
            args:
            - "--lookback-days"
            - "3"
```

#### D. Deploy Cloud Run Job

```bash
# Build and push image
cd deployment/cloud-run/nba/monitoring/gap-detection
docker build -t us-west2-docker.pkg.dev/nba-props-platform/nba-monitoring/gap-detection:latest .
docker push us-west2-docker.pkg.dev/nba-props-platform/nba-monitoring/gap-detection:latest

# Deploy job
gcloud run jobs create nba-gap-detection \
  --region=us-west2 \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-monitoring/gap-detection:latest \
  --service-account=nba-monitoring-sa@nba-props-platform.iam.gserviceaccount.com \
  --max-retries=2 \
  --task-timeout=10m \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform,ENVIRONMENT=production" \
  --args="--lookback-days=3"
```

#### E. Create Cloud Scheduler

```bash
gcloud scheduler jobs create http nba-gap-detection-daily \
  --location=us-west2 \
  --schedule="0 13 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/nba-gap-detection:run" \
  --http-method=POST \
  --oauth-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --description="Daily NBA processing gap detection (runs 1 PM PT)"
```

#### F. Test

```bash
# Manual execution
gcloud run jobs execute nba-gap-detection --region=us-west2 --wait

# Check logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=nba-gap-detection" \
  --limit=20 \
  --format=json

# Verify output
# Should see summary of gaps found/not found for each source
```

---

## 2. Create NBA Schedule Validator Job

### Background
- MLB has `mlb-schedule-validator-daily` running at 11 AM
- Validates schedule completeness and quality
- Source: `deployment/cloud-run/mlb/validators/mlb-schedule-validator.yaml`

### Steps

#### A. Create NBA Schedule Validator Script

**File**: `monitoring/nba/nba_schedule_validator.py`

**Purpose**: Validate workflow-generated NBA schedules

**Key Checks**:
```python
def validate_schedule(game_date: str) -> Dict:
    """
    Validate NBA schedule for a given date.

    Checks:
    1. Schedule exists for date
    2. Game count matches expected (typically 0-15 games/day)
    3. No duplicate game_ids
    4. All teams have valid abbreviations
    5. Game times are reasonable (not in past, not too far future)
    6. Home/away teams don't match
    7. Required fields present (game_id, game_date, home_team, away_team)
    """
    checks = {
        'schedule_exists': False,
        'game_count_valid': False,
        'no_duplicates': False,
        'valid_teams': False,
        'valid_times': False,
        'no_team_conflicts': False,
        'required_fields': False,
    }

    # Query schedule
    query = f"""
    SELECT *
    FROM `nba-props-platform.nba_raw.nbac_schedule_source_daily`
    WHERE game_date = '{game_date}'
    """

    # Run validation checks
    # ... (implementation)

    return {
        'game_date': game_date,
        'checks': checks,
        'status': 'PASS' if all(checks.values()) else 'FAIL',
        'games_found': game_count,
        'errors': errors
    }
```

#### B. Create Dockerfile

Similar to gap detection, create Docker image for schedule validator.

#### C. Deploy Cloud Run Job

```bash
gcloud run jobs create nba-schedule-validator \
  --region=us-west2 \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-validators/schedule-validator:latest \
  --service-account=nba-monitoring-sa@nba-props-platform.iam.gserviceaccount.com \
  --max-retries=1 \
  --task-timeout=10m \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform,ENVIRONMENT=production" \
  --args="--date=today"
```

#### D. Create Cloud Scheduler

```bash
gcloud scheduler jobs create http nba-schedule-validator-daily \
  --location=us-west2 \
  --schedule="0 11 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/nba-schedule-validator:run" \
  --http-method=POST \
  --oauth-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --description="Daily NBA schedule validation (runs 11 AM PT)"
```

#### E. Test

```bash
# Manual execution
gcloud run jobs execute nba-schedule-validator --region=us-west2 --wait

# Check logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=nba-schedule-validator" \
  --limit=20
```

---

## 3. Verification Checklist

After creating both jobs:

### Gap Detection
- [ ] Cloud Run Job deployed: `nba-gap-detection`
- [ ] Scheduler created: `nba-gap-detection-daily`
- [ ] Schedule: 1 PM PT daily
- [ ] Test execution successful
- [ ] Alerts configured
- [ ] Sources cover: props, boxscores, schedule, lineups

### Schedule Validator
- [ ] Cloud Run Job deployed: `nba-schedule-validator`
- [ ] Scheduler created: `nba-schedule-validator-daily`
- [ ] Schedule: 11 AM PT daily
- [ ] Test execution successful
- [ ] Validation checks comprehensive
- [ ] Alerts configured

### Documentation
- [ ] Operational runbook updated
- [ ] README in deployment directory
- [ ] Alert playbook created
- [ ] Monitoring dashboard updated

---

## 4. Quick Reference Commands

### List All NBA Schedulers
```bash
gcloud scheduler jobs list --location=us-west2 \
  --format="table(name,schedule,state)" | grep nba
```

### Check Job Execution History
```bash
# Gap detection
gcloud run jobs executions list --job=nba-gap-detection --region=us-west2 --limit=10

# Schedule validator
gcloud run jobs executions list --job=nba-schedule-validator --region=us-west2 --limit=10
```

### Manual Job Execution
```bash
# Gap detection with specific date
gcloud run jobs execute nba-gap-detection \
  --region=us-west2 \
  --args="--date=2026-01-28" \
  --wait

# Schedule validator with dry run
gcloud run jobs execute nba-schedule-validator \
  --region=us-west2 \
  --args="--date=2026-01-28,--dry-run" \
  --wait
```

### View Recent Logs
```bash
# Gap detection logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=nba-gap-detection" \
  --limit=50 \
  --format=json

# Schedule validator logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=nba-schedule-validator" \
  --limit=50 \
  --format=json
```

---

## 5. Alert Configuration

### Slack Channels
- Critical gaps → `#app-error-alerts`
- Warnings → `#nba-alerts`
- Daily summaries → `#daily-orchestration`

### Alert Templates

**Gap Detection Alert**:
```
🔴 CRITICAL: NBA Processing Gap Detected

Date: {game_date}
Gaps Found: {gap_count}
Critical: {critical_count}

Sources with gaps:
- {source_1}: {gap_type}
- {source_2}: {gap_type}

Remediation commands in logs.
```

**Schedule Validation Alert**:
```
⚠️ WARNING: NBA Schedule Validation Failed

Date: {game_date}
Failed Checks: {failed_check_count}

Issues:
- {check_1}: {error}
- {check_2}: {error}

Action: Review schedule generation workflow
```

---

## 6. Maintenance

### Weekly Review
- Review gap detection results
- Check false positive rate
- Update source configurations as needed
- Verify alert routing

### Monthly Review
- Audit scheduler coverage
- Update validation checks
- Review and tune alert thresholds
- Compare with MLB for new gaps

### Quarterly Audit
```bash
# Compare MLB vs NBA schedulers
comm -23 \
  <(gcloud scheduler jobs list --format="value(name)" | grep "^mlb-" | sed 's/mlb-//' | sort) \
  <(gcloud scheduler jobs list --format="value(name)" | grep "^nba-" | sed 's/nba-//' | sort)

# Expected output: List of MLB schedulers without NBA equivalents
# Evaluate each one for necessity
```

---

## Related Files

- **MLB Gap Detection**: `monitoring/mlb/mlb_gap_detection.py`
- **MLB Validators**: `deployment/cloud-run/mlb/validators/`
- **Generic Gap Detection**: `monitoring/processors/gap_detection/`
- **Analysis**: `NBA-SCHEDULER-GAP-ANALYSIS.md`
- **Summary**: `INVESTIGATION-COMPLETE-SUMMARY.md`

---

## Next Steps

1. Create `monitoring/nba/` directory
2. Implement `nba_gap_detection.py` (adapt from MLB)
3. Implement `nba_schedule_validator.py` (new)
4. Create Dockerfiles for both
5. Deploy Cloud Run Jobs
6. Create schedulers
7. Test and verify
8. Update documentation

---

**Status**: Ready for implementation
