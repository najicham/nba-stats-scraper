# Session 159 Handoff - Data Freshness Investigation & Root Cause Analysis

**Date:** 2025-12-22
**Focus:** Comprehensive investigation of data freshness issues across all pipeline phases

## Executive Summary

This session conducted a thorough investigation of why analytics and precompute tables are lagging behind raw data. **The root cause is a critical naming mismatch** between Phase 2 processor names and the Phase 2→3 orchestrator's expected processor list, preventing automatic Phase 3 triggering.

## Investigation Findings

### 1. Raw Data (Phase 2) - Current Status

| Table | Latest Date | Status |
|-------|-------------|--------|
| `bdl_player_boxscores` | Dec 21 | ✅ Current |
| `bigdataball_play_by_play` | Dec 21 | ✅ Current |
| `nbac_injury_report` | Dec 22 | ✅ Current |
| `nbac_schedule` | Apr 12, 2026 | ✅ Full season |
| `bettingpros_player_points_props` | Dec 21 | ✅ Current |
| `nbac_gamebook_player_stats` | Dec 20 | ⚠️ Dec 21 not scraped yet |

### 2. Analytics (Phase 3) - 1 Day Behind

| Table | Latest Date | Status |
|-------|-------------|--------|
| `player_game_summary` | Dec 20 | ⚠️ Missing Dec 21 |
| `upcoming_player_game_context` | Dec 20 | ⚠️ Missing Dec 21 |

### 3. Precompute (Phase 4) - 1 Day Behind

| Table | Latest Date | Status |
|-------|-------------|--------|
| `player_daily_cache` | Dec 20 | ⚠️ Missing Dec 21 |
| `daily_game_context` | Empty | ❌ No processor exists |

### 4. Deprecated/Unused Tables

| Table | Latest Date | Notes |
|-------|-------------|-------|
| `bdl_injuries` | Oct 19, 2025 | ~2 months stale |
| `bdl_standings` | Aug 24, 2025 | ~4 months stale |
| `espn_boxscores` | NULL (2025) | No 2025 data |
| `nbac_play_by_play` | Jan 15, 2025 | ~11 months stale |

---

## ROOT CAUSE ANALYSIS

### Critical Issue: Phase 2→3 Orchestrator Naming Mismatch

**Location:** `orchestration/cloud_functions/phase2_to_phase3/main.py`

The orchestrator tracks processor completions in Firestore and requires **21 processors** to complete before triggering Phase 3. However, **processor names don't match**.

#### The Mismatch

Phase 2 processors publish their class name (e.g., `BdlBoxscoresProcessor`), which gets normalized to `bdl_boxscores`. But the orchestrator expects `bdl_player_boxscores`.

| Processor Class | Normalized Name | Expected Name | Match? |
|----------------|-----------------|---------------|--------|
| `BdlBoxscoresProcessor` | `bdl_boxscores` | `bdl_player_boxscores` | ❌ |
| `NbacGamebookProcessor` | `nbac_gamebook` | `nbac_gamebook_player_stats` | ❌ |
| `EspnBoxscoreProcessor` | `espn_boxscore` | `espn_boxscores` | ❌ |
| `EspnTeamRosterProcessor` | `espn_team_roster` | `espn_team_rosters` | ❌ |
| `OddsGameLinesProcessor` | `odds_game_lines` | `odds_api_game_lines` | ❌ |
| `OddsApiPropsProcessor` | `odds_api_props` | `odds_api_player_points_props` | ❌ |
| `BettingPropsProcessor` | `betting_props` | `bettingpros_player_points_props` | ❌ |
| `BigDataBallPbpProcessor` | `big_data_ball_pbp` | `bigdataball_play_by_play` | ❌ |

#### Evidence in Firestore

```
Dec 21 Completion Status:
  - Completed: 2 processors
  - bdl_boxscores (should be bdl_player_boxscores)
  - big_data_ball_pbp (should be bigdataball_play_by_play)
  - Triggered: False

Dec 20 Completion Status:
  - Completed: 2 processors (same issue)
  - Triggered: False
```

### Secondary Issue: Analytics Direct Subscription Also Broken

The Phase 3 analytics service (`main_analytics_service.py`) is also directly subscribed to `nba-phase2-raw-complete`, but has field name mismatches:

1. **Field mismatch:** Phase 2 publishes `output_table`, analytics expects `source_table`
2. **Table name mismatch:** Phase 2 sends `nba_raw.bdl_player_boxscores`, analytics expects `bdl_player_boxscores` (without dataset prefix)

**ANALYTICS_TRIGGERS keys:**
```python
'bdl_player_boxscores': [PlayerGameSummaryProcessor, ...],
'nbac_gamebook_player_stats': [...],
```

**But Phase 2 publishes:**
```python
'output_table': 'nba_raw.bdl_player_boxscores'  # Has dataset prefix!
```

### Why Dec 20 Data Exists

The Dec 20 analytics data (last_processed: 2025-12-21 18:52:57) was likely processed via:
1. Manual trigger or
2. A scheduler-based fallback that's not documented

---

## Solutions

### Option A: Fix Orchestrator Expected Names (Recommended)

Update `EXPECTED_PROCESSORS` in `phase2_to_phase3/main.py` to match actual normalized names:

```python
EXPECTED_PROCESSORS = [
    'bdl_boxscores',           # was: bdl_player_boxscores
    'bdl_injuries',
    'nbac_gamebook',           # was: nbac_gamebook_player_stats
    'nbac_team_boxscore',
    'nbac_schedule',
    'nbac_injury_report',
    'nbac_play_by_play',
    'espn_boxscore',           # was: espn_boxscores
    'espn_team_roster',        # was: espn_team_rosters
    'espn_scoreboard',
    'odds_game_lines',         # was: odds_api_game_lines
    'odds_api_props',          # was: odds_api_player_points_props
    'betting_props',           # was: bettingpros_player_points_props
    'big_data_ball_pbp',       # was: bigdataball_play_by_play
    # ... etc
]
```

### Option B: Fix Processor Names at Source

Change processor class names to match expected format (more invasive).

### Option C: Improve Normalization Function

Update `normalize_processor_name()` to also check `output_table` without dataset prefix.

### For Analytics Direct Trigger - Fix Field Names

In `main_analytics_service.py`:

```python
# Current:
source_table = message.get('source_table')

# Should be:
output_table = message.get('output_table', '')
# Strip dataset prefix
source_table = output_table.split('.')[-1] if output_table else None
```

---

## Immediate Actions Required

### 1. Trigger Dec 21 Analytics Manually

```bash
# Trigger Phase 3 for Dec 21
curl -X POST "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2025-12-21", "end_date": "2025-12-21"}'
```

### 2. Trigger Dec 21 Precompute Manually

```bash
# Trigger Phase 4 for Dec 21
curl -X POST "https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["PlayerDailyCacheProcessor"], "analysis_date": "2025-12-21"}'
```

### 3. Scrape Dec 21 Gamebooks

Dec 21 gamebook PDFs haven't been scraped yet. Run:

```bash
# Get Dec 21 games and scrape gamebooks
PYTHONPATH=. .venv/bin/python scripts/gamebook_backfill_2025.sh 2025-12-21 2025-12-21
```

---

## Additional Findings

### Empty Table: `daily_game_context`

- **Status:** Table exists but is empty
- **Cause:** No processor was ever implemented
- **Schema exists:** `schemas/bigquery/nba_precompute/daily_game_context.sql`
- **Purpose:** Was intended to hold game-level context (referee stats, pace, rest advantage)
- **Action:** Either implement processor or remove table

### Deprecated Tables

These tables have no recent data and appear to be deprecated:

| Table | Last Data | Recommendation |
|-------|-----------|----------------|
| `bdl_injuries` | Oct 2025 | Consider removal or investigate scraper |
| `bdl_standings` | Aug 2025 | Consider removal or investigate scraper |
| `espn_boxscores` | None 2025 | Consider removal |
| `nbac_play_by_play` | Jan 2025 | Consider removal - using bigdataball_play_by_play instead |

---

## Files That Need Changes

### Priority 1: Fix Orchestrator (breaks Phase 3 automation)

1. `orchestration/cloud_functions/phase2_to_phase3/main.py` - Update EXPECTED_PROCESSORS list
2. `shared/config/orchestration_config.py` - Update centralized config if it exists

### Priority 2: Fix Analytics Direct Trigger

1. `data_processors/analytics/main_analytics_service.py` - Fix field name extraction

### Priority 3: Add Missing Processor

1. Create `data_processors/precompute/daily_game_context/` - If this data is needed

---

## Verification Commands

```bash
# Check Firestore completion status
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase2_completion').document('2025-12-21').get()
print(doc.to_dict() if doc.exists else 'No doc')
"

# Check expected vs actual processor names
PYTHONPATH=. .venv/bin/python -c "
from orchestration.cloud_functions.phase2_to_phase3.main import EXPECTED_PROCESSORS
print(f'Expected {len(EXPECTED_PROCESSORS)} processors')
for p in sorted(EXPECTED_PROCESSORS):
    print(f'  - {p}')
"

# Check analytics data freshness
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date >= "2025-12-19" GROUP BY game_date ORDER BY game_date'
```

---

## Commits This Session

1. `5b466a6` - fix: Handle both date formats in injury report processor

---

## Next Session Priorities

1. **Fix the naming mismatch** - This is blocking automated Phase 3 triggering
2. **Manual trigger for Dec 21** - Catch up analytics and precompute
3. **Scrape Dec 21 gamebooks** - Fill the gap
4. **Deploy orchestrator fix** - Prevent future issues
5. **Consider cleanup of deprecated tables**
