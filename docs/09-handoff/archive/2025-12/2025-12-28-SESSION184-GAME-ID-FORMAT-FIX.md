# Session 184: game_id Format Mismatch Fix

**Date**: 2025-12-28 (late evening)
**Focus**: Fix game_id format inconsistency causing live grading player matching failures

## Problem Identified

Live grading was showing `home_team: null` and `away_team: null` for some players (Dec 28: 33 players in GSW @ TOR game).

**Root Cause**: Two different game_id formats in use:
| Format | Example | Used By |
|--------|---------|---------|
| NBA Official | `0022500441` | nbac_schedule |
| Date-based | `20251228_GSW_TOR` | odds_api_player_points_props, nbac_gamebook_player_stats |

When live_grading_exporter JOINed predictions with schedule on `game_id`, the mismatch caused NULLs.

## Solution Implemented

### Fix 1: nbac_gamebook_processor.py
Added `_lookup_official_game_id()` method that:
- Queries schedule service for the official NBA game_id
- Normalizes team codes using `get_nba_tricode()`
- Falls back to date-based format only if schedule lookup fails

```python
def _lookup_official_game_id(self, game_date_str, away_team, home_team):
    games = self.schedule_service.get_games_for_date(game_date_str)
    for game in games:
        if game.away_team == away_team and game.home_team == home_team:
            return game.game_id
    return None
```

### Fix 2: odds_api_props_processor.py
Same approach as gamebook processor:
- Added schedule service initialization
- Added `_lookup_official_game_id()` with caching
- Updated game_id generation to use official format first

### Fix 3: live_grading_exporter.py (Backward Compatibility)
Modified query to handle BOTH formats for existing data:
```sql
game_info AS (
    SELECT DISTINCT
        game_id,
        CONCAT(REPLACE(CAST(game_date AS STRING), '-', ''), '_', away_team_tricode, '_', home_team_tricode) as date_based_game_id,
        home_team_tricode, away_team_tricode
    FROM nbac_schedule
)
-- Join on both formats
LEFT JOIN game_info gi ON predictions.game_id = gi.game_id
LEFT JOIN game_info gi2 ON predictions.game_id = gi2.date_based_game_id
```

## Commits
- `176df39` - fix: Use official NBA game_id format in gamebook and Odds API processors

## Deployments Needed
1. **Phase 2 Raw Processors** - for gamebook and Odds API fixes
2. **Live Export Function** - for live grading backward compatibility

```bash
./bin/raw/deploy/deploy_processors_simple.sh
./bin/deploy/deploy_live_export.sh
```

## Verification Commands

```bash
# Check if new gamebook data uses official game_id
bq query --use_legacy_sql=false "
SELECT DISTINCT game_id
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= CURRENT_DATE('America/New_York')
LIMIT 10"

# Check if live grading has home/away teams now
gsutil cat 'gs://nba-props-platform-api/v1/live-grading/latest.json' | jq '.predictions | map(select(.home_team == null)) | length'
```

## Verification Results

After deploying fixes and triggering live export for Dec 28:

| Metric | Before | After |
|--------|--------|-------|
| Predictions with null home_team | 3 | **0** |
| All predictions matched | No | **Yes** (51 official + 5 date-based) |

**Fix confirmed working!**

## Additional Fix: Message Format

Fixed `normalize_message_format()` in `main_processor_service.py` to handle messages with only `gcs_path` field (no `scraper_name`). This resolves the "Unrecognized message format" error for `ball-dont-lie/player-box-scores`.

## Known Issues

1. **Historical data unchanged**: Older data in BigQuery still has date-based game_id format
   - Live grading handles this via dual-format JOIN
   - New data going forward will use official NBA format

## Files Changed
1. `data_processors/raw/nbacom/nbac_gamebook_processor.py`
   - Added `_lookup_official_game_id()` method
   - Updated `extract_game_info()` to use official format

2. `data_processors/raw/oddsapi/odds_api_props_processor.py`
   - Added schedule service and caching
   - Added `_lookup_official_game_id()` method
   - Updated game_id generation

3. `data_processors/publishing/live_grading_exporter.py`
   - Modified `_query_predictions()` to JOIN on both formats
