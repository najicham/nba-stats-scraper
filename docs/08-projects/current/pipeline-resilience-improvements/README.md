# Pipeline Resilience Improvements

**Status:** In Progress
**Started:** 2026-01-23
**Priority:** P0/P1

## Overview

Following the Jan 22-23 data gap incident, this project implements monitoring and auto-recovery improvements to prevent similar outages.

## Problem Statement

On Jan 22, 2026, a complete data gap occurred for 8 games due to:
1. Scheduler jobs pointing to deleted service
2. Stale schedule data (games still "In Progress")
3. No alerting when data gaps formed
4. Manual intervention required for recovery

## Implemented Improvements

### 1. Enhanced Daily Health Check
**File:** `bin/monitoring/daily_health_check.sh`

Added three new monitoring sections:
- **Data Completeness Check** - Compares raw vs analytics record counts
- **Workflow Execution Check** - Shows post_game_window runs/skips
- **Schedule Staleness Check** - Detects games with stale status

### 2. Stale Schedule Auto-Fix
**File:** `bin/monitoring/fix_stale_schedule.py`

Utility to detect and fix stale schedule data:
- Finds games > 4 hours past start time still showing "In Progress"
- Updates them to Final status
- Integrated into daily health check

### 3. Query Fixes for upcoming_player_game_context_processor
**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

Fixed two query errors:
- `total_rebounds` → `rebounds` (column name mismatch)
- Added partition filters for `espn_team_rosters` queries

### 4. Backfill Endpoint Authentication
**File:** `data_processors/analytics/main_analytics_service.py`

Updated `require_auth` decorator to accept:
- API keys (X-API-Key header)
- GCP identity tokens (Authorization: Bearer header)

This allows internal access via `gcloud auth print-identity-token`.

## Files Changed

```
bin/monitoring/daily_health_check.sh              # Enhanced monitoring
bin/monitoring/fix_stale_schedule.py              # New: auto-fix utility
data_processors/analytics/main_analytics_service.py  # Auth fix
data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py  # Query fixes
docs/09-handoff/2026-01-23-RESILIENCE-IMPROVEMENTS.md  # Incident post-mortem
```

## Usage

### Run Health Check
```bash
./bin/monitoring/daily_health_check.sh
```

### Fix Stale Schedule (Dry Run)
```bash
python bin/monitoring/fix_stale_schedule.py --dry-run
```

### Fix Stale Schedule (Apply)
```bash
python bin/monitoring/fix_stale_schedule.py
```

### Manual Analytics Backfill
```bash
# Using identity token
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"source_table": "bdl_player_boxscores", "start_date": "2026-01-22", "end_date": "2026-01-22"}'
```

## Deployment

Changes require redeployment of:
- `nba-phase3-analytics-processors` (auth + query fixes)

```bash
./bin/deploy/deploy_analytics_processors.sh
```

## Future Improvements (Not Yet Implemented)

See `docs/09-handoff/2026-01-23-RESILIENCE-IMPROVEMENTS.md` for:
- P2: Service health dependency validation
- P2: Schedule auto-refresh during game windows
- P3: Catch-up workflow enhancements
