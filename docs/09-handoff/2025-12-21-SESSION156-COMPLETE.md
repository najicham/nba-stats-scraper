# Session 156: Pipeline Full Restoration + Data Requirements Analysis

**Date:** 2025-12-21
**Status:** Pipeline restored, data gaps identified for frontend features

---

## Executive Summary

This session completed the pipeline restoration started in Session 155 and analyzed data requirements for frontend game log enhancements.

### Accomplishments
1. **Root cause found:** `execute-workflows` scheduler only ran 6 AM - 11 PM, missing 4 AM gamebook window
2. **Gamebook backfill:** 30 games (Dec 16-20), 1,051 players loaded
3. **Scheduler fixed:** Now runs every hour (0-23)
4. **Phase 4 fully working:** All 5 processors succeeded including MLFeatureStoreProcessor
5. **Data requirements analyzed:** Identified gaps for frontend game log enhancements

---

## Pipeline Status

### Data Sources

| Source | Latest Date | Status |
|--------|-------------|--------|
| `nbac_gamebook_player_stats` | 2025-12-20 | ✅ Fixed this session |
| `bdl_player_boxscores` | 2025-12-20 | ✅ OK |
| `ml_feature_store_v2` | 2025-12-20 | ✅ OK |
| `bigdataball_play_by_play` | 2025-12-16 | ⚠️ 5 days behind |
| `nbac_injury_report` | Stale | ❌ Not scraped recently |
| `bettingpros_player_points_props` | Stale | ❌ Not scraped recently |

### Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1 (Scrapers) | ⚠️ Partial | Gamebook working, PBP/injury/props scrapers stale |
| Phase 2 (Raw) | ✅ OK | Processing correctly |
| Phase 3 (Analytics) | ⚠️ Partial | Some processors failing (need investigation) |
| Phase 4 (Precompute) | ✅ OK | All 5 processors succeeded |
| Phase 5 (Predictions) | ⚠️ Issue | "No players found" for Dec 21 |

---

## Root Cause: Gamebook Scraper Failure

### The Problem

The `nbac_gamebook_pdf` scraper is part of the `post_game_window_3` workflow, scheduled for **4 AM ET**.

However, the `execute-workflows` Cloud Scheduler job was configured as:
```
schedule: 5 6-23 * * *   # Only runs 6 AM - 11 PM ET!
```

The `/evaluate` endpoint at 4 AM correctly marked the workflow as "RUN", but `/execute-workflows` wasn't called until 6:05 AM, by which point the decision was stale.

### The Fix

Updated scheduler to run every hour:
```bash
gcloud scheduler jobs update http execute-workflows \
    --location=us-west2 \
    --schedule="5 0-23 * * *" \
    --description="Execute workflows - every hour (includes post-game windows at 1 AM and 4 AM)"
```

---

## Gamebook Backfill Details

### Games Backfilled (Dec 16-20)

```
20251216/SASNYK
20251217/CLECHI, MEMMIN
20251218/LACOKC, WASSAS, ATLCHA, NYKIND, MIABKN, TORMIL, HOUNOP, DETDAL, ORLDEN, GSWPHX, LALUTA, SACPOR
20251219/MIABOS, PHINYK, SASATL, CHICLE, OKCMIN
20251220/HOUDEN, DALPHI, BOSTOR, INDNOP, CHADET, WASMEM, PHXGSW, ORLUTA, PORSAC, LALLAC
```

### Backfill Process

1. **Scrape PDFs** (Phase 1):
```python
# Script at /tmp/gamebook_backfill.py scraped all 30 games
# 4-second rate limit per game
# All succeeded
```

2. **Process to BigQuery** (Phase 2):
```bash
PYTHONPATH=. .venv/bin/python -c "
from datetime import date
from backfill_jobs.raw.nbac_gamebook.nbac_gamebook_raw_backfill import NbacGamebookBackfill
backfill = NbacGamebookBackfill()
backfill.run_backfill(start_date=date(2025, 12, 16), end_date=date(2025, 12, 20))
"
```

Results:
- 30 files processed
- 1,051 player rows loaded
- 0 failures
- Duration: 15 minutes

---

## Frontend Data Requirements Analysis

The frontend team has a data requirements doc at:
`~/code/props-web/docs/06-projects/current/game-log-enhancements/02-data-requirements.md`

### Required Features

1. **Time to Go Over** - When player surpassed their points line
2. **Impact Player Context** - OUT/LIMITED players for game context
3. **Pre-Game Injury Report** - Injury status for tonight's games

### Data Availability

| Feature | Data Needed | Available? | Gap |
|---------|-------------|------------|-----|
| Time to Over | Play-by-play | ⚠️ Partial | BigDataBall PBP 5 days behind (Dec 16) |
| Impact Players | Gamebook + boxscores | ✅ Yes | None - ready to implement |
| Injury Report | `nbac_injury_report` | ❌ No | Scraper not running |
| Prop Lines | `bettingpros_*` or `odds_api_*` | ❌ No | Scrapers not running |

### BigDataBall PBP Schema (for time_to_over)

The data has everything needed:
```
game_clock, period, event_type, score_home, score_away, player_1_lookup
```

Example row:
```
| 0:03:38 | 1 | foul | 17 | 13 | 1642867/Collin Murray-Boyles |
```

---

## Known Issues

### 1. Phase 3 Processors Failing

When running Phase 3 for Dec 20:
```json
{
  "results": [
    {"processor": "PlayerGameSummaryProcessor", "status": "error"},
    {"processor": "TeamOffenseGameSummaryProcessor", "status": "error"},
    {"processor": "TeamDefenseGameSummaryProcessor", "status": "error"},
    {"processor": "UpcomingPlayerGameContextProcessor", "status": "success"},
    {"processor": "UpcomingTeamGameContextProcessor", "status": "error"}
  ]
}
```

Need to check logs to understand failures.

### 2. Predictions "No Players Found"

```json
{
  "message": "No players found for 2025-12-21",
  "status": "error"
}
```

The prediction coordinator isn't finding players for today's games despite feature store having data up to Dec 20. Likely a query issue in how it identifies upcoming players.

### 3. Other Issues from Session 155

- BigQuery quota exceeded for partition modifications
- OddsApiPropsProcessor path parsing bug (IndexError)
- BasketballRefRosterProcessor SQL injection with special characters

---

## Quick Reference Commands

### Check Data Freshness

```bash
# Gamebook
bq query --use_legacy_sql=false 'SELECT MAX(game_date) FROM nba_raw.nbac_gamebook_player_stats'

# ML Feature Store
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date >= "2025-12-18" GROUP BY game_date ORDER BY game_date'

# Play-by-play
bq query --use_legacy_sql=false 'SELECT MAX(game_date) FROM nba_raw.bigdataball_play_by_play WHERE game_date >= "2025-12-01"'

# Injury report
bq query --use_legacy_sql=false 'SELECT MAX(report_date) FROM nba_raw.nbac_injury_report WHERE report_date >= "2025-12-01"'
```

### Run Pipeline Phases

```bash
TOKEN=$(gcloud auth print-identity-token)

# Phase 3 Analytics
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"start_date": "2025-12-20", "end_date": "2025-12-20", "backfill_mode": true}'

# Phase 4 Precompute (all processors)
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"analysis_date": "2025-12-20", "backfill_mode": true}'

# Phase 5 Predictions
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"game_date": "2025-12-21", "force": true}'
```

### Gamebook Backfill

```bash
PYTHONPATH=. .venv/bin/python -c "
from datetime import date
from backfill_jobs.raw.nbac_gamebook.nbac_gamebook_raw_backfill import NbacGamebookBackfill
backfill = NbacGamebookBackfill()
backfill.run_backfill(start_date=date(2025, 12, 21), end_date=date(2025, 12, 21))
"
```

---

## Immediate Next Steps

### Priority 1: Fix Stale Scrapers

1. **BigDataBall PBP** - Check why it stopped at Dec 16, backfill Dec 17-21
2. **Injury Report** - Check `nbac_injury_report` scraper scheduler
3. **Prop Lines** - Check BettingPros and OddsAPI scrapers

### Priority 2: Debug Pipeline Issues

1. Investigate Phase 3 processor failures
2. Debug prediction coordinator "No players found" issue

### Priority 3: Implement Frontend Features

Once data is flowing:
1. Implement `time_to_over` calculation from PBP data
2. Implement `impact_player_context` from gamebook/boxscore data
3. Add new fields to API response

---

## Files Changed This Session

```
docs/09-handoff/2025-12-21-SESSION155-PIPELINE-DIAGNOSIS.md
  - Updated with Session 156 completion details
```

### Scheduler Change (via gcloud)

```
execute-workflows: 5 6-23 * * * → 5 0-23 * * *
```

---

## Git Commits

```
63ee622 docs: Update Session 155/156 handoff with full restoration
```

---

## Architecture Notes

### Workflow Orchestration

```
Cloud Scheduler (hourly)
    ↓
/evaluate (nba-phase1-scrapers) - Writes RUN decisions
    ↓ (5 min later)
/execute-workflows (nba-phase1-scrapers) - Reads decisions, runs scrapers
    ↓
Pub/Sub notification
    ↓
Phase 2 processors
    ↓
Phase 3 → Phase 4 → Phase 5
```

### Key Config Files

- `config/workflows.yaml` - Workflow definitions including `post_game_window_3`
- `scrapers/registry.py` - Scraper registration
- `orchestration/parameter_resolver.py` - Parameter resolution for scrapers

### Gamebook Scraper Location

- Scraper: `scrapers/nbacom/nbac_gamebook_pdf.py`
- Processor: `data_processors/raw/nbacom/nbac_gamebook_processor.py`
- Backfill: `backfill_jobs/raw/nbac_gamebook/nbac_gamebook_raw_backfill.py`
