# Operational Workflows

**Production workflows that run automatically on schedules for daily NBA data collection and processing.**

## Current Workflows

### Core Business Operations
- **`real-time-business.yaml`** ⭐ **MOST CRITICAL**
  - Real-time prop betting data collection
  - Odds API events and player props
  - Runs every 2-4 hours during active periods
  - **Business Impact**: Revenue-critical prop betting data

### Daily Operations  
- **`morning-operations.yaml`**
  - Daily morning setup and data collection
  - Player rosters, schedules, and foundational data
  - Runs every morning at 8 AM ET

- **`post-game-collection.yaml`**  
  - Post-game data collection and processing
  - Box scores, player stats, game results
  - Runs after games complete (9 PM ET)

### System Maintenance
- **`early-morning-final-check.yaml`**
  - Final validation before game day operations
  - Data quality checks and system readiness
  - Runs early morning on game days

- **`late-night-recovery.yaml`**
  - End-of-day cleanup and error recovery
  - Failed job retries and data validation
  - Runs late night after all games complete

## Execution Schedule
- **Total**: 12 daily executions across all workflows
- **Peak Season**: Higher frequency during active NBA season
- **Monitoring**: Production alerts enabled for all workflows

## Deployment
```bash
# Deploy all operational workflows
./bin/deployment/deploy_workflows.sh workflows/operational/

# Deploy specific workflow
gcloud workflows deploy real-time-business \
  --source=./workflows/operational/real-time-business.yaml \
  --location=us-west2
```

## Critical Notes
- **Production System**: These workflows are actively running in production
- **High Availability**: Failures in these workflows directly impact business operations
- **Monitoring Required**: All workflows should have alerting configured
- **Change Control**: Test thoroughly before deploying changes to these workflows

## Migration History
- **2025-08-02**: Migrated from `workflows/` root to `workflows/operational/`
- **Purpose**: Better organization as system scales to include backfill and admin workflows
