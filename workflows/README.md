# NBA Data Pipeline Workflows

This directory contains Google Cloud Workflows configurations for orchestrating the NBA data collection pipeline.

## Files

### `nba-scraper-workflow.yaml`
Main data collection workflow that orchestrates all NBA data scrapers with proper dependencies and error handling.

**Phases:**
- **Morning Collection** (8-10 AM ET): Rosters, injuries, schedule updates
- **Afternoon Preparation** (12-4 PM ET): Betting events and player props  
- **Evening Results** (6-11 PM ET): Game results, boxscores, play-by-play

**Key Features:**
- Parallel execution where possible
- Critical dependency management (Events API → Player Props)
- Comprehensive error handling and logging
- Graceful failure handling (one scraper failure doesn't stop pipeline)

## Deployment

### Prerequisites
1. **Cloud Run services deployed** for each scraper
2. **Environment variables configured** with scraper service URLs
3. **IAM permissions** for Workflows to call Cloud Run services

### Deploy Workflow
```bash
# Deploy the main workflow
gcloud workflows deploy nba-scraper-workflow \
    --source=nba-scraper-workflow.yaml \
    --location=us-central1

# Verify deployment
gcloud workflows describe nba-scraper-workflow --location=us-central1
```

### Required Environment Variables
Set these in your Cloud Run environment or pass as workflow arguments:

```bash
# ESPN Scrapers
ESPN_ROSTER_URL="https://espn-roster-service-url"
ESPN_SCOREBOARD_URL="https://espn-scoreboard-service-url"  
ESPN_BOXSCORES_URL="https://espn-boxscores-service-url"

# Ball Don't Lie Scrapers
BDL_GAMES_URL="https://bdl-games-service-url"
BDL_INJURIES_URL="https://bdl-injuries-service-url"
BDL_BOXSCORES_URL="https://bdl-boxscores-service-url"

# Odds API Scrapers
ODDS_EVENTS_URL="https://odds-events-service-url"
ODDS_PROPS_URL="https://odds-props-service-url"

# NBA.com Scrapers  
NBA_SCHEDULE_URL="https://nba-schedule-service-url"
NBA_INJURY_URL="https://nba-injury-service-url"
NBA_PLAYER_BOXSCORES_URL="https://nba-player-boxscores-service-url"
NBA_PLAY_BY_PLAY_URL="https://nba-play-by-play-service-url"

# Authentication
CLOUD_RUN_TOKEN="service-account-token"
```

## Scheduling

### Cloud Scheduler Setup
Configure scheduled executions for different times of day:

```bash
# Morning Collection (8:00 AM ET = 1:00 PM UTC)
gcloud scheduler jobs create http morning-scrapers \
    --schedule="0 13 * * *" \
    --time-zone="America/New_York" \
    --uri="https://workflowexecutions.googleapis.com/v1/projects/YOUR_PROJECT/locations/us-central1/workflows/nba-scraper-workflow/executions" \
    --http-method=POST \
    --headers="Content-Type=application/json,Authorization=Bearer $(gcloud auth print-access-token)" \
    --message-body='{"argument": {"phase": "morning"}}'

# Afternoon Preparation (2:00 PM ET = 7:00 PM UTC)  
gcloud scheduler jobs create http afternoon-scrapers \
    --schedule="0 19 * * *" \
    --time-zone="America/New_York" \
    --uri="https://workflowexecutions.googleapis.com/v1/projects/YOUR_PROJECT/locations/us-central1/workflows/nba-scraper-workflow/executions" \
    --http-method=POST \
    --headers="Content-Type=application/json,Authorization=Bearer $(gcloud auth print-access-token)" \
    --message-body='{"argument": {"phase": "afternoon"}}'

# Evening Results (8:00 PM ET = 1:00 AM UTC next day)
gcloud scheduler jobs create http evening-scrapers \
    --schedule="0 1 * * *" \
    --time-zone="America/New_York" \
    --uri="https://workflowexecutions.googleapis.com/v1/projects/YOUR_PROJECT/locations/us-central1/workflows/nba-scraper-workflow/executions" \
    --http-method=POST \
    --headers="Content-Type=application/json,Authorization=Bearer $(gcloud auth print-access-token)" \
    --message-body='{"argument": {"phase": "evening"}}'
```

### Manual Execution
```bash
# Execute entire workflow
gcloud workflows execute nba-scraper-workflow \
    --location=us-central1

# Execute with specific parameters
gcloud workflows execute nba-scraper-workflow \
    --location=us-central1 \
    --data='{"date": "2025-07-15", "phase": "morning"}'
```

## Monitoring

### View Execution History
```bash
# List recent executions
gcloud workflows executions list \
    --workflow=nba-scraper-workflow \
    --location=us-central1 \
    --limit=10

# Get detailed execution info
gcloud workflows executions describe EXECUTION_ID \
    --workflow=nba-scraper-workflow \
    --location=us-central1
```

### Cloud Logging Queries
Use these queries in Cloud Console Logging:

```sql
-- All workflow executions
resource.type="workflows.googleapis.com/Workflow"
resource.labels.workflow_id="nba-scraper-workflow"

-- Failed executions only
resource.type="workflows.googleapis.com/Workflow"
resource.labels.workflow_id="nba-scraper-workflow"
severity="ERROR"

-- Specific scraper performance
resource.type="workflows.googleapis.com/Workflow"
jsonPayload.step_name:"scraper_name"
```

### Key Metrics to Watch
- **Execution success rate**: Percentage of successful workflow runs
- **Step duration**: How long each scraper phase takes  
- **Failure patterns**: Which scrapers fail most frequently
- **Dependency violations**: Events API failures blocking props collection

## Workflow Structure

### Main Workflow Steps
1. **init**: Initialize variables and current date
2. **morning_collection**: Parallel execution of morning scrapers
3. **afternoon_preparation**: Sequential execution (events → props)
4. **evening_results**: Parallel execution of results scrapers
5. **workflow_summary**: Aggregate results and logging

### Subworkflow: `run_scraper`
Reusable pattern for executing individual scrapers with:
- Standardized logging
- Error handling and timeouts
- Consistent response format
- Dependency parameter support

## Troubleshooting

### Common Issues

#### **Workflow Execution Fails**
```bash
# Check execution details
gcloud workflows executions describe EXECUTION_ID \
    --workflow=nba-scraper-workflow \
    --location=us-central1 \
    --format="value(error)"

# Check individual step logs
gcloud logging read 'resource.type="workflows.googleapis.com/Workflow" AND jsonPayload.step_name="step_name"'
```

#### **Scraper Timeouts**
- Check Cloud Run service logs for the specific scraper
- Increase timeout in workflow configuration if needed
- Verify scraper service is healthy and responsive

#### **Authentication Errors**
```bash
# Verify Workflows service account has necessary permissions
gcloud projects get-iam-policy YOUR_PROJECT \
    --flatten="bindings[].members" \
    --format="table(bindings.role)" \
    --filter="bindings.members:workflows-service-account@YOUR_PROJECT.iam.gserviceaccount.com"

# Required roles:
# - roles/run.invoker (to call Cloud Run services)
# - roles/storage.objectCreator (to write to GCS)
# - roles/pubsub.publisher (to publish completion messages)
```

#### **Dependency Issues**
If Events API fails and blocks Player Props:
1. Check Events API service health
2. Review Odds API rate limits and quotas
3. Consider manual retry of just the afternoon phase
4. Monitor for downstream impact on player reports

### Emergency Procedures

#### **Skip Failed Scraper**
To temporarily disable a problematic scraper, comment it out in the workflow:

```yaml
# Temporarily disable problematic scraper
# - problematic_scraper:
#     call: run_scraper
#     args:
#       scraper_name: "problematic-scraper"
```

#### **Partial Re-run**
To re-run just specific phases:

```bash
# Re-run just afternoon phase
gcloud workflows execute nba-scraper-workflow \
    --data='{"phase": "afternoon", "skip_morning": true}'
```

## Development

### Testing Changes
1. **Deploy to dev environment** first
2. **Test with manual execution** before scheduling
3. **Monitor logs** for unexpected behavior
4. **Validate file outputs** in GCS

### Adding New Scrapers
1. Add scraper configuration to appropriate phase
2. Add required environment variable
3. Update this README with new scraper details
4. Test in isolation before adding to workflow

### Workflow Validation
```bash
# Validate workflow syntax before deployment
gcloud workflows deploy nba-scraper-workflow \
    --source=nba-scraper-workflow.yaml \
    --location=us-central1 \
    --validate-only
```

## Related Documentation

- **Scraper Details**: `/docs/scrapers/data-pipeline-reference.md`
- **Daily Schedule**: `/docs/scrapers/daily-schedule.md`  
- **Monitoring Guide**: `/docs/monitoring-guide.md`
- **Processor Architecture**: `/docs/processor-architecture.md`

## Support

### Getting Help
- **Workflow issues**: Check Cloud Console → Workflows → Executions
- **Scraper issues**: Check Cloud Console → Cloud Run → Service Logs  
- **Scheduling issues**: Check Cloud Console → Cloud Scheduler
- **General pipeline**: Refer to monitoring dashboard and alerts

### Useful Commands Reference
```bash
# Quick status check
gcloud workflows executions list --workflow=nba-scraper-workflow --location=us-central1 --limit=5

# View latest execution
LATEST=$(gcloud workflows executions list --workflow=nba-scraper-workflow --location=us-central1 --limit=1 --format="value(name)")
gcloud workflows executions describe $LATEST --workflow=nba-scraper-workflow --location=us-central1

# Emergency stop (if running)
gcloud workflows executions cancel EXECUTION_ID --workflow=nba-scraper-workflow --location=us-central1
```
