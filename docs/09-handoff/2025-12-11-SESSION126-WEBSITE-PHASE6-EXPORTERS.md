# Session 126: Website UI - Phase 6 Exporters Implementation

**Date:** 2025-12-11
**Status:** In Progress - Schema Fixes Needed
**Next Session:** Fix Tonight exporter schema mismatches, test full export

---

## Summary

Implemented Phase 6 publishing exporters for the website UI project. Created two new exporters (`TonightAllPlayersExporter`, `TonightPlayerExporter`) and enhanced the existing `PlayerProfileExporter` with 50-game logs, splits, and track record data.

### What's Working ✅
- `PlayerProfileExporter` - Enhanced and tested with real data
- `player_full_name` added to index.json and best_bets output
- CLI updated with new export types
- All imports compile correctly

### What Needs Fixing ⚠️
- `TonightAllPlayersExporter` - Schema mismatches with actual BigQuery tables
- `TonightPlayerExporter` - Same schema issues

---

## Files Created

### New Exporters
| File | Purpose | Status |
|------|---------|--------|
| `data_processors/publishing/tonight_all_players_exporter.py` | Homepage initial load (~150KB) | Schema fixes needed |
| `data_processors/publishing/tonight_player_exporter.py` | Tonight tab detail (~3-5KB each) | Schema fixes needed |

### Documentation
| File | Purpose |
|------|---------|
| `docs/08-projects/current/website-ui/MASTER-SPEC.md` | v1.2 - Complete UI/API specification |
| `docs/08-projects/current/website-ui/PHASE6-PUBLISHING-ARCHITECTURE.md` | Backend architecture with Firebase Hosting |
| `docs/08-projects/current/website-ui/TODO.md` | Complete implementation checklist |
| `docs/08-projects/current/website-ui/UI-SPEC-V2.md` | Original UI brainstorm |
| `docs/08-projects/current/website-ui/DATA-INVESTIGATION-RESULTS.md` | Data availability analysis |
| `docs/08-projects/current/website-ui/BRAINSTORM-PROMPT.md` | Prompt used for design chat |

---

## Files Modified

### Enhanced Exporters
| File | Changes |
|------|---------|
| `data_processors/publishing/player_profile_exporter.py` | Added: `_query_game_log` (50 games), `_query_splits` (rest, location, opponents), `_query_track_record` (OVER/UNDER breakdown), `_query_next_game`, `player_full_name` to index and profiles |
| `data_processors/publishing/best_bets_exporter.py` | Added `player_full_name` to query and output |
| `data_processors/publishing/__init__.py` | Added new exporter imports |
| `backfill_jobs/publishing/daily_export.py` | Added `tonight` and `tonight-players` export types |

---

## Schema Issues Discovered

The Tonight exporters reference columns that don't exist or have different names:

### TonightAllPlayersExporter (`tonight_all_players_exporter.py`)

**Line ~107 - `_query_players`:**
```python
# References that may not exist in player_prop_predictions:
pp.opening_points_line  # Need to verify actual column name
```

**Line ~89 - `_query_games` (FIXED):**
```python
# Changed from home_team_abbr to home_team_tricode
home_team_tricode as home_team_abbr
```

### Tables to Verify Column Names

| Table | Need to Check |
|-------|---------------|
| `nba_predictions.player_prop_predictions` | `opening_points_line`, `current_points_line`, column names |
| `nba_precompute.player_composite_factors` | `fatigue_score`, `fatigue_context_json` |
| `nba_raw.nbac_injury_report` | `injury_status`, `reason`, `report_date` |
| `nba_analytics.upcoming_player_game_context` | All column names |

### PlayerProfileExporter Schema Fixes Applied

These were fixed and tested working:

| Original | Fixed To |
|----------|----------|
| `g.home_game` | Derived from `game_id` |
| `g.team_result` | `g.win_flag` |
| `g.fg_made` | `g.fg_makes` |
| `g.fg_attempted` | `g.fg_attempts` |
| `g.three_made` | `g.three_pt_makes` |
| `g.three_attempted` | `g.three_pt_attempts` |
| `g.ft_made` | `g.ft_makes` |
| `g.ft_attempted` | `g.ft_attempts` |
| `g.rebounds` | `offensive_rebounds + defensive_rebounds` |
| `g.season = '2024-25'` | `g.season_year >= 2021` |
| `g.days_rest`, `g.back_to_back` | Calculated from game dates |

---

## Test Results

### PlayerProfileExporter - WORKING ✅

```
Testing PlayerProfileExporter with lebronjames...
Player: LeBron James
Summary: games=22, win_rate=0.929

Game log: 50 games
  Latest: 2025-04-30 vs MIN: 22 pts (UNDER)
  Stats: 9/21 FG, 1/5 3PT, 7 REB, 6 AST

Splits:
  B2B: 28.3 ppg (31 games)
  Home: 26.8 ppg (134 games)
  Away: 27.3 ppg (124 games)
  vs Opponents: 29 teams tracked

Track Record:
  Overall: 13-1 (0.929)
  OVER calls: 13-1
  UNDER calls: 0-0

✅ PlayerProfileExporter test passed!
```

### TonightAllPlayersExporter - SCHEMA ERROR ⚠️

```
Error: 400 Name opening_points_line not found inside pp
```

---

## Data Ranges Available

| Table | Date Range |
|-------|------------|
| `nba_predictions.prediction_accuracy` | 2021-11-06 to 2022-01-07 |
| `nba_analytics.upcoming_player_game_context` | 2021-10-19 to 2024-11-25 |
| `nba_analytics.player_game_summary` | Contains multiple seasons |

---

## Next Session Tasks

### Priority 1: Fix Tonight Exporter Schemas

1. **Check `player_prop_predictions` schema:**
```bash
PYTHONPATH=. .venv/bin/python << 'EOF'
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT * FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2021-12-25' LIMIT 1
'''
result = list(client.query(query).result())
if result:
    for key in sorted(result[0].keys()):
        print(f"  {key}")
EOF
```

2. **Update `tonight_all_players_exporter.py` Line ~107** with correct column names

3. **Check other tables** referenced in the Tonight exporters

### Priority 2: Test Full Export

```bash
# Test player profiles export (working)
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --players --min-games 5

# Test tonight export (after schema fix)
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --date 2021-12-25 --only tonight

# Verify GCS upload
gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json | head -100
```

### Priority 3: Update Documentation

After testing, update:
- `docs/08-projects/current/website-ui/TODO.md` - Mark items complete
- `docs/08-projects/current/phase-6-publishing/overview.md` - Add new endpoints

---

## Architecture Reference

### GCS Bucket Structure (Target)
```
gs://nba-props-platform-api/v1/
├── tonight/                          # NEW
│   ├── all-players.json             # Homepage initial load
│   └── player/
│       └── {lookup}.json            # Tonight tab detail
├── best-bets/                        # Existing
├── predictions/                      # Existing
├── results/                          # Existing
├── systems/                          # Existing
└── players/
    ├── index.json                   # Enhanced with player_full_name
    └── {lookup}.json                # Enhanced with splits, game_log
```

### CLI Usage
```bash
# Export types: results, performance, best-bets, predictions, tonight, tonight-players

# Export tonight data
python daily_export.py --date 2024-12-11 --only tonight,tonight-players

# Export player profiles
python daily_export.py --players --min-games 5
```

---

## Key Code Locations

### Exporter Base Pattern
- `data_processors/publishing/base_exporter.py` - Base class with `query_to_list`, `upload_to_gcs`

### Tonight Exporters (Need Schema Fixes)
- `data_processors/publishing/tonight_all_players_exporter.py:107` - `_query_players` method
- `data_processors/publishing/tonight_player_exporter.py` - Similar schema issues likely

### Enhanced Player Profile
- `data_processors/publishing/player_profile_exporter.py:288` - `_query_game_log`
- `data_processors/publishing/player_profile_exporter.py:354` - `_query_splits`
- `data_processors/publishing/player_profile_exporter.py:515` - `_query_track_record`

---

## Related Documentation

- **Master Spec:** `docs/08-projects/current/website-ui/MASTER-SPEC.md`
- **Architecture:** `docs/08-projects/current/website-ui/PHASE6-PUBLISHING-ARCHITECTURE.md`
- **Todo List:** `docs/08-projects/current/website-ui/TODO.md`
- **Original Phase 6 Design:** `docs/08-projects/current/phase-6-publishing/DESIGN.md`
- **Operations Guide:** `docs/08-projects/current/phase-6-publishing/OPERATIONS.md`

---

## Frontend Notes (For Future)

- **Stack:** Next.js 14+, Tailwind, TypeScript
- **Hosting:** Firebase Hosting (not Vercel - staying in GCP)
- **Repo:** Separate repo `nba-props-website` (to be created)
- **Data fetching:** Direct from GCS JSON (no backend needed)

---

**End of Handoff**
