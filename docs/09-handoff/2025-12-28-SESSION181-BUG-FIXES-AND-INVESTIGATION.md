# Session 181: Frontend Bug Fixes and Root Cause Investigation

**Date:** 2025-12-28 (Evening)
**Duration:** ~2 hours
**Focus:** Critical frontend bugs, upstream data issues

---

## Summary

This session addressed 5 bugs reported by the frontend team. We fixed 2 bugs directly and identified root causes for 3 more that require upstream fixes.

---

## Bugs Status

| Bug | Issue | Status | Fix Location |
|-----|-------|--------|--------------|
| 1 | Duplicate players (5x each) | **FIXED** | tonight_all_players_exporter.py |
| 2 | Missing teams in games | **ROOT CAUSE IDENTIFIED** | ESPN roster scraper stale |
| 3 | Empty DET@LAC game | **ROOT CAUSE IDENTIFIED** | ESPN roster scraper stale |
| 4 | Missing last_10_points | **FIXED** | tonight_all_players_exporter.py |
| 5 | Excessive DNPs | **EXPECTED BEHAVIOR** | O/U only tracks games with lines |

---

## Fixes Applied

### 1. Duplicate Players (Bug 1) - FIXED
**Problem:** Each player appeared 5x in the API response.

**Root Cause:** Prediction worker is inserting 5 duplicate rows per player into `nba_predictions.player_prop_predictions`. All rows have the same `player_lookup`, `game_id`, `system_id='ensemble_v1'`, and same `created_at` timestamp but different `prediction_id` (UUID).

**Fix Applied:** Added `QUALIFY ROW_NUMBER()` to deduplicate in the exporter:
```sql
-- In predictions CTE
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pp.player_lookup, pp.game_id
    ORDER BY pp.created_at DESC
) = 1
```

**File:** `data_processors/publishing/tonight_all_players_exporter.py` line 126-129

**Permanent Fix Needed:** Investigate Phase 5 prediction worker to stop inserting duplicates.

### 2. Missing last_10_points (Bug 4) - FIXED
**Problem:** `last_10_points` field was only included for players WITHOUT lines.

**Fix Applied:** Now exported for ALL players:
```python
# Add last_10_points for ALL players (frontend requested for sparklines)
player_data['last_10_points'] = last_10.get('points', [])
```

**File:** `data_processors/publishing/tonight_all_players_exporter.py` line 388-389

---

## Root Causes Identified

### Missing Teams (Bugs 2 & 3)
**Problem:**
- GSW@TOR only has TOR players (no GSW)
- BOS@POR only has BOS players (no POR)
- SAC@LAL only has LAL players (no SAC)
- DET@LAC has 0 players

**Root Cause:** `espn_team_rosters` table is STALE - last updated **2025-10-18** (October 18)!

**Why:** The ESPN roster scraper exists (`scrapers/espn/espn_roster_api.py`) but:
1. It's NOT included in `config/workflows.yaml`
2. No scheduler job exists for it
3. It was manually run once in October and never again

**Phase 3 Impact:** `UpcomingPlayerGameContextProcessor` uses roster data to identify which players are on which teams. Without fresh roster data, it can only find players who have been in other data sources (boxscores, props).

**Fix Required:**
1. Run `scripts/scrape_espn_all_rosters.py` to backfill roster data
2. Add ESPN roster scraper to `config/workflows.yaml` under `daily_foundation` workflow
3. Re-run Phase 3 for today's date

### Prediction Worker Duplicates
**Problem:** 5 duplicate rows per player in predictions table.

**Investigation:**
```sql
SELECT player_lookup, game_id, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-12-28' AND system_id = 'ensemble_v1'
GROUP BY player_lookup, game_id
HAVING COUNT(*) > 1
-- Shows 5 rows per player!
```

**Fix Required:** Investigate `predictions/worker/worker.py` to understand why multiple rows are being inserted.

---

## Deployments Made

1. **Scrapers Service** - `e61e2b1` (resolver fixes from previous session)
2. **Phase 6 Export Function** - Deployed with exporter fixes
3. **Live Export Function** - Deployed with scheduler updates

---

## Files Changed

| File | Change |
|------|--------|
| `data_processors/publishing/tonight_all_players_exporter.py` | Deduplication + last_10_points |

---

## Commits

```
811b35c fix: Tonight exporter - deduplicate predictions, add last_10_points
```

---

## Next Session Priorities

### HIGH - Fix Missing Teams
1. Run roster backfill:
   ```bash
   cd /home/naji/code/nba-stats-scraper
   PYTHONPATH=. python scripts/scrape_espn_all_rosters.py --delay 3
   ```

2. Process roster data:
   ```bash
   # Trigger Phase 2 for roster processor
   gcloud pubsub topics publish nba-phase1-scrapers-complete \
     --message='{"scraper_name": "espn_team_roster_api", "target_date": "2025-12-28", "status": "success"}'
   ```

3. Re-run Phase 3:
   ```bash
   curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"analysis_date": "2025-12-28", "processors": ["upcoming_player_game_context"], "backfill_mode": true}'
   ```

4. Re-export tonight API:
   ```bash
   PYTHONPATH=. python -c "
   from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
   exporter = TonightAllPlayersExporter()
   exporter.export('2025-12-28')
   "
   ```

### MEDIUM - Prevent Future Issues
1. Add ESPN roster to workflows.yaml (daily schedule)
2. Add roster freshness to daily health checks
3. Investigate prediction worker duplicates

### LOW - Improvements
1. Add live grading display fields (`pick_display`, `result_display`, etc.)
2. Filter out All-Star/exhibition games from schedule queries

---

## System Improvement Notes

Per user request to document issues and improve robustness:

### Issue: Stale Roster Data
**Detection Gap:** No monitoring for roster data freshness.

**Recommendations:**
1. Add roster freshness check to daily health summary email
2. Add roster table to completeness checker script
3. Create data freshness dashboard showing last update for each critical table

### Issue: Scraper Not in Workflow
**Detection Gap:** Scrapers in registry but not in workflows are invisible.

**Recommendations:**
1. Add validation script that compares scrapers registry vs workflows.yaml
2. Flag scrapers that haven't run in N days
3. Add "last_run" tracking to Firestore for all scrapers

### Issue: Prediction Duplicates
**Detection Gap:** No validation of unique constraints at insert time.

**Recommendations:**
1. Add UNIQUE constraint on `(player_lookup, game_id, system_id)` in BigQuery
2. Use MERGE instead of INSERT to prevent duplicates
3. Add duplicate check to Phase 5 health monitoring

---

## Key Commands Reference

```bash
# Check roster freshness
bq query --use_legacy_sql=false "
SELECT MAX(roster_date) as latest, COUNT(DISTINCT team_abbr) as teams
FROM nba_raw.espn_team_rosters
WHERE roster_date >= '2024-10-01'"

# Check prediction duplicates
bq query --use_legacy_sql=false "
SELECT player_lookup, COUNT(*) as rows
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'ensemble_v1'
GROUP BY player_lookup HAVING COUNT(*) > 1
LIMIT 10"

# Check tonight API
gsutil cat "gs://nba-props-platform-api/v1/tonight/all-players.json" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Players: {d[\"total_players\"]}, Games: {len(d[\"games\"])}')"

# Run roster backfill
PYTHONPATH=. python scripts/scrape_espn_all_rosters.py --delay 3

# Re-run Phase 3 for today
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2025-12-28", "processors": ["upcoming_player_game_context"], "backfill_mode": true}'
```

---

## Frontend Current Status

After today's fixes:
- **Duplicates:** FIXED - No more 5x players
- **last_10_points:** FIXED - Now included for all players
- **Missing Teams:** Still broken - Need roster backfill first
- **Empty Games:** Still broken - Need roster backfill first

The API file has been re-exported with fixes at `gs://nba-props-platform-api/v1/tonight/all-players.json`
