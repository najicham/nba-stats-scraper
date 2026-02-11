# Phase 6 Export Fix - Technical Details

## Architecture Overview

Phase 6 is the final stage in the 6-phase NBA prediction pipeline, responsible for exporting data from BigQuery to GCS for frontend consumption.

```
Phase 5 (Predictions) → Pub/Sub → Phase 6 (Export) → GCS → Frontend
                                        ↑
                                   Schedulers
                                   (11 AM, 1 PM, 5 PM ET)
```

## Cloud Function Configuration

**Name:** `phase6-export`  
**Runtime:** Python 3.11  
**Memory:** 1 GiB  
**Timeout:** 540s (9 minutes)  
**Trigger:** Pub/Sub topic `nba-phase6-export-trigger`  
**Region:** us-west2  

### Environment Variables
```
GCP_PROJECT=nba-props-platform
```

### Deployment
```bash
# Auto-deploy via Cloud Build (preferred)
git push origin main
# Watches: orchestration/cloud_functions/phase6_export/**, backfill_jobs/**, shared/**

# Manual deploy (emergency)
./bin/deploy-service.sh phase6-export
```

## Export Types

### Date-Scoped Exports (Safe for Historical Backfill)

| Type | Output Path | Query Filter | Purpose |
|------|-------------|--------------|---------|
| `predictions` | `predictions/{date}.json` | `system_id = 'catboost_v9'` | All predictions for date |
| `best-bets` | `best-bets/{date}.json` | `system_id = 'catboost_v9'` | High-confidence picks |
| `subset-picks` | `picks/{date}.json` | From `current_subset_picks` | Dynamic subset picks |
| `daily-signals` | `signals/{date}.json` | `system_id = 'catboost_v9'` | Daily prediction signal |
| `results` | `results/{date}.json` | `game_date = {date}` | Graded predictions |
| `performance` | `performance/{date}.json` | `game_date = {date}` | Model performance metrics |

### Fixed-Path Exports (DANGEROUS for Historical Backfill)

| Type | Output Path | Risk |
|------|-------------|------|
| `tonight` | `tonight/all-players.json` | Overwrites current day's data |
| `tonight-players` | `tonight/player/{lookup}.json` | Overwrites ~200 player files |
| `streaks` | `streaks/today.json` | Overwrites current streaks |

### Global Exports (Not Date-Specific)

| Type | Output Path | Behavior |
|------|-------------|----------|
| `season-subsets` | `subsets/season.json` | Uses `date.today()` regardless of `target_date` |

## Scheduler Configuration

### phase6-tonight-picks-morning (11 AM ET)
```json
{
  "export_types": [
    "tonight",
    "tonight-players",
    "predictions",
    "best-bets",
    "streaks",
    "subset-picks",
    "season-subsets",
    "daily-signals"
  ],
  "target_date": "today",
  "update_latest": true
}
```

### phase6-tonight-picks-pregame (5 PM ET)
Same as morning.

### phase6-tonight-picks (1 PM ET)
Same as morning.

## Export Orchestration

### Code Flow

```python
# orchestration/cloud_functions/phase6_export/main.py
def main(cloud_event):
    message_data = parse_pubsub_message(cloud_event)
    
    if message_data.get('players'):
        # Player profiles export
        run_player_export(min_games)
    
    elif message_data.get('export_types'):
        # Daily export
        target_date = get_target_date(message_data['target_date'])
        export_types = message_data['export_types']
        
        # Validation (only for 'tonight' types)
        validate_analytics_ready(target_date)
        validate_predictions_exist(target_date)
        
        # Run export
        from backfill_jobs.publishing.daily_export import export_date
        result = export_date(target_date, export_types, update_latest)
```

### Execution Order (After Reordering Fix)

```python
# backfill_jobs/publishing/daily_export.py

def export_date(target_date, export_types, update_latest):
    # === FAST EXPORTS FIRST ===
    if 'results' in export_types: ...           # ~5s
    if 'performance' in export_types: ...       # ~5s
    if 'best-bets' in export_types: ...         # ~10s
    if 'predictions' in export_types: ...       # ~10s
    if 'tonight' in export_types: ...           # ~15s (all players summary)
    if 'streaks' in export_types: ...           # ~10s
    
    # === PHASE 6 SUBSET EXPORTS ===
    if 'subset-picks' in export_types:          # ~20s
        materializer.materialize(target_date)   # Write to BQ
        exporter.export(target_date)            # Export to GCS
    
    if 'daily-signals' in export_types: ...     # ~5s
    if 'subset-performance' in export_types: ...# ~10s
    if 'subset-definitions' in export_types: ...# ~5s
    if 'season-subsets' in export_types: ...    # ~10s
    
    # === SLOW EXPORTS LAST ===
    if 'tonight-players' in export_types:       # 400-600s!
        # Process 200+ individual players
        # Each: BQ query + GCS upload
        for player in players:
            export_player(player)
```

## Timeout Root Cause Analysis

### Before Reordering

```
Total timeout: 540s

results (5s) → performance (5s) → best-bets (10s) → predictions (10s) 
→ tonight (15s) → tonight-players (400-600s) [TIMEOUT!]
→ subset-picks [NEVER REACHED] → daily-signals [NEVER REACHED]
```

### After Reordering

```
Total timeout: 540s

results (5s) → performance (5s) → best-bets (10s) → predictions (10s) 
→ tonight (15s) → streaks (10s) → subset-picks (20s) ✅ → daily-signals (5s) ✅
→ ... → tonight-players (400-600s) [May timeout, but critical exports already done]
```

## Validation Checks

### validate_analytics_ready()

**Purpose:** Ensure Phase 3 analytics data exists before exporting tonight's picks

**Query:**
```sql
SELECT COUNT(DISTINCT player_lookup)
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = @target_date
```

**Threshold:** >= 30 players

**Impact:** Blocks entire export if fails

**Issue for Historical Backfills:** This table may not retain data for dates older than ~1 week, causing historical exports via Pub/Sub to fail validation.

### validate_predictions_exist()

**Purpose:** Ensure predictions exist before exporting

**Query:**
```sql
SELECT COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date = @target_date
  AND is_active = TRUE
  AND system_id = 'catboost_v9'
```

**Threshold:** >= 1 prediction

**Impact:** Blocks entire export if fails

## BigQuery Tables Used

### Source Tables (Read)

| Table | Used By | Filter |
|-------|---------|--------|
| `player_prop_predictions` | predictions, best-bets, daily-signals | `system_id = 'catboost_v9'` |
| `prediction_accuracy` | results, best-bets | `game_date = {date}` |
| `current_subset_picks` | subset-picks | `game_date = {date}` |
| `daily_prediction_signals` | daily-signals | `system_id = 'catboost_v9'` |
| `upcoming_player_game_context` | tonight, tonight-players | `game_date = {date}` |
| `player_game_summary` | tonight-players | `game_date = {date}` |

### Target Tables (Write)

| Table | Written By | Purpose |
|-------|------------|---------|
| `current_subset_picks` | SubsetMaterializer | Materialized subset picks for fast querying |

## GCS Output Structure

```
gs://nba-props-platform-api/v1/
├── picks/
│   ├── 2026-02-03.json
│   ├── 2026-02-04.json
│   └── ...
├── signals/
│   ├── 2026-02-03.json
│   └── ...
├── predictions/
│   ├── 2026-02-03.json
│   └── ...
├── best-bets/
│   ├── 2026-02-03.json
│   ├── latest.json          # Updated when update_latest=true
│   └── ...
├── tonight/
│   ├── all-players.json     # FIXED PATH (today only)
│   └── player/
│       ├── playerA.json     # FIXED PATHS (today only)
│       └── ...
└── streaks/
    └── today.json           # FIXED PATH (today only)
```

## System ID Migration (catboost_v8 → catboost_v9)

### Background

Both `catboost_v8` and `catboost_v9` predictions exist in BigQuery as parallel prediction systems. The production champion model is v9, but exporters were hardcoded to query v8.

### Files Changed (20 occurrences across 10 files)

```python
# BEFORE
WHERE system_id = 'catboost_v8'

# AFTER  
WHERE system_id = 'catboost_v9'
```

### Impact on Historical Data

Files created before 18:52 UTC on Feb 11, 2026 contain catboost_v8 predictions. These required backfilling to serve the correct production model data.

## Dependencies

### requirements.txt
```
functions-framework==3.*
google-cloud-bigquery>=3.0.0
google-cloud-storage>=2.0.0
google-cloud-pubsub>=2.0.0
google-cloud-firestore>=2.0.0      # CRITICAL: Added in this fix
requests>=2.28.0
pandas>=1.5.0
db-dtypes>=1.0.0
google-cloud-secret-manager==2.16.0
```

### Deployment Package (Cloud Build)

```bash
# cloudbuild-functions.yaml
cp orchestration/cloud_functions/phase6_export/main.py /workspace/deploy_pkg/
cp orchestration/cloud_functions/phase6_export/requirements.txt /workspace/deploy_pkg/

cp -r data_processors /workspace/deploy_pkg/
cp -r shared /workspace/deploy_pkg/
cp -r predictions /workspace/deploy_pkg/
cp -r backfill_jobs /workspace/deploy_pkg/     # CRITICAL: Added in this fix
```

## Monitoring

### Cloud Run Request Logs

```bash
# Check execution latency
gcloud logging read \
  'resource.type="cloud_run_revision" 
   AND resource.labels.service_name="phase6-export"' \
  --limit=10 \
  --format="value(timestamp,httpRequest.latency)"
```

### Function Logs

```bash
# Check recent exports
gcloud functions logs read phase6-export \
  --region=us-west2 \
  --limit=100 | grep "Export completed"
```

### File Verification

```bash
# Check if files exist
for date in 2026-02-{03..11}; do
  gsutil ls gs://nba-props-platform-api/v1/picks/$date.json >/dev/null 2>&1 \
    && echo "$date: ✅" \
    || echo "$date: ❌"
done
```

## Troubleshooting

### Export Fails with "analytics_not_ready"

**Cause:** `upcoming_player_game_context` has < 30 players for target date

**Solutions:**
1. Use CLI instead of Pub/Sub (bypasses validation)
2. Wait for Phase 3 to complete
3. Check Phase 3 logs for processing errors

### Export Timeouts

**Symptoms:** Latency exactly 540.000s, some files missing

**Solutions:**
1. Verify export order (fast first, slow last)
2. Increase timeout from 540s to 900s
3. Split tonight-players into separate function

### Files Created with Wrong Model

**Symptom:** Files contain catboost_v8 data instead of catboost_v9

**Solution:** Backfill using CLI with `--only` flag

```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python \
  backfill_jobs/publishing/daily_export.py \
  --date 2026-02-XX \
  --only subset-picks,daily-signals,predictions,best-bets
```

### Scheduler Sends Wrong Message Format

**Symptom:** Logs show "Unrecognized message format, falling back to daily export"

**Check:**
```bash
gcloud scheduler jobs describe phase6-tonight-picks \
  --location=us-west2 \
  --format="value(pubsubTarget.data)" | base64 -d | python -m json.tool
```

**Should contain:**
- `export_types` (plural)
- `target_date`
- `update_latest`

