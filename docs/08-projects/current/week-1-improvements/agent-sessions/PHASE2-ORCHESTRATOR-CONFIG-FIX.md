# Phase 2 Orchestrator Config Fix
**Date:** 2026-01-21
**Issue:** Orchestrator config expects `br_roster` but actual table is `br_rosters_current`
**Priority:** Low (monitoring only, doesn't block pipeline)

---

## The Problem

The Phase 2→3 orchestrator config lists `br_roster` as an expected processor, but the actual BigQuery table is named `br_rosters_current`. This causes validation queries to fail with "Table not found" errors.

**Why it doesn't break the pipeline:**
- Phase 2→3 orchestrator is monitoring-only (since Dec 2025)
- Phase 3 is triggered directly via Pub/Sub subscription
- Phase 3 processors read from fallback_config.yaml which has the correct table name
- The BR roster processor successfully writes data to `br_rosters_current`

---

## Files to Update

### 1. Main Orchestration Config
**File:** `/home/naji/code/nba-stats-scraper/shared/config/orchestration_config.py`

**Line 25-33:**
```python
phase2_expected_processors: List[str] = field(default_factory=lambda: [
    # Core daily processors that reliably publish completion messages
    'bdl_player_boxscores',       # Daily box scores from balldontlie
    'bigdataball_play_by_play',   # Per-game play-by-play
    'odds_api_game_lines',        # Per-game odds
    'nbac_schedule',              # Schedule updates
    'nbac_gamebook_player_stats', # Post-game player stats
    'br_rosters_current',         # Basketball-ref rosters (FIXED: was 'br_roster')
])
```

### 2. Phase 2→3 Orchestrator Fallback List
**File:** `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/phase2_to_phase3/main.py`

**Line 80-88:**
```python
EXPECTED_PROCESSORS: List[str] = [
    # Core daily processors
    'bdl_player_boxscores',      # Daily box scores from balldontlie
    'bigdataball_play_by_play',  # Per-game play-by-play
    'odds_api_game_lines',       # Per-game odds
    'nbac_schedule',             # Schedule updates
    'nbac_gamebook_player_stats', # Post-game player stats
    'br_rosters_current',        # Basketball-ref rosters (FIXED: was 'br_roster')
]
```

---

## Verification After Fix

### 1. Check Table Exists
```bash
bq show nba-props-platform:nba_raw.br_rosters_current
# Should show table details with schema
```

### 2. Run Verification Query
```bash
bq query --use_legacy_sql=false '
SELECT
  "br_rosters_current" as table_name,
  COUNT(*) as row_count,
  COUNT(DISTINCT team_abbrev) as teams,
  MAX(last_scraped_date) as latest_date
FROM `nba-props-platform.nba_raw.br_rosters_current`
WHERE season_year = 2024
'
# Should show ~450 players, 30 teams
```

### 3. Test Orchestrator Config
```bash
cd /home/naji/code/nba-stats-scraper
python3 -c "
from shared.config.orchestration_config import get_orchestration_config
config = get_orchestration_config()
print('Phase 2 expected processors:')
for p in config.phase_transitions.phase2_expected_processors:
    print(f'  - {p}')
"
# Should include 'br_rosters_current'
```

### 4. Verify All Phase 2 Tables
```sql
-- Run in BigQuery
SELECT
  'bdl_player_boxscores' as expected_name,
  (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_player_boxscores` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) as row_count,
  'EXISTS' as status
UNION ALL
SELECT 'bigdataball_play_by_play', COUNT(*), 'EXISTS' FROM `nba-props-platform.nba_raw.bigdataball_play_by_play` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'odds_api_game_lines', COUNT(*), 'EXISTS' FROM `nba-props-platform.nba_raw.odds_api_game_lines` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'nbac_schedule', COUNT(*), 'EXISTS' FROM `nba-props-platform.nba_raw.nbac_schedule` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'nbac_gamebook_player_stats', COUNT(*), 'EXISTS' FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'br_rosters_current', COUNT(*), 'EXISTS' FROM `nba-props-platform.nba_raw.br_rosters_current` WHERE season_year = 2024;
```

---

## Deployment Steps

### Option A: Include in Next Regular Deployment
Since this is monitoring-only and doesn't affect the critical path, you can include it in your next regular deployment.

1. Update both files as shown above
2. Commit changes with message: `fix: Update Phase 2 orchestrator config to use correct BR roster table name`
3. Deploy phase2_to_phase3 Cloud Function when convenient
4. Verify monitoring works

### Option B: Deploy Immediately (if you prefer)
```bash
# 1. Update files
cd /home/naji/code/nba-stats-scraper

# 2. Deploy phase2_to_phase3 function
gcloud functions deploy phase2-to-phase3 \
  --gen2 \
  --runtime=python312 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/phase2_to_phase3 \
  --entry-point=orchestrate_phase2_to_phase3 \
  --trigger-topic=nba-phase2-raw-complete \
  --set-env-vars=GCP_PROJECT=nba-props-platform \
  --timeout=540s \
  --memory=512Mi

# 3. Verify deployment
gcloud functions describe phase2-to-phase3 --gen2 --region=us-west2
```

---

## Testing After Deployment

### 1. Check Cloud Function Logs
```bash
gcloud logging read '
  resource.type="cloud_function"
  AND resource.labels.function_name="phase2-to-phase3"
  AND jsonPayload.message=~"Loaded.*expected Phase 2 processors"
' --limit=5 --format=json
```

Should show: `"Loaded 6 expected Phase 2 processors from config"`

### 2. Simulate Phase 2 Completion
```bash
# Publish a test message
gcloud pubsub topics publish nba-phase2-raw-complete --message='{
  "processor_name": "BasketballRefRosterProcessor",
  "phase": "phase_2_raw",
  "game_date": "2026-01-21",
  "output_table": "nba_raw.br_rosters_current",
  "status": "success",
  "record_count": 450
}'
```

Check logs - should show processor registered successfully.

### 3. Query Firestore Completion State
```bash
# Check that BR roster completions are being tracked
gcloud firestore documents list phase2_completion --limit=5
```

---

## Why This Fix is Low Priority

1. **No impact on data collection** - BR roster processor works fine
2. **No impact on data processing** - Phase 3 reads via fallback chains (correct name)
3. **No impact on predictions** - Phase 5 uses Phase 3/4 outputs
4. **Only affects monitoring** - Orchestrator tracks completion for observability

**Conclusion:** Safe to deploy during next maintenance window or regular deployment.

---

## Related Documentation

- Main investigation report: `MISSING-TABLES-INVESTIGATION.md`
- Orchestrator architecture: `/docs/01-architecture/orchestration/orchestrators.md`
- Fallback chains config: `/shared/config/data_sources/fallback_config.yaml`
