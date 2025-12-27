# Pipeline Validation Script - Comprehensive Design

**Created:** 2025-12-01
**Status:** ✓ IMPLEMENTED + V2 CHAIN VIEW DEFAULT
**Author:** Claude + User collaboration
**Updated:** 2025-12-02 - V2 refinements (32 tests, centralized PROJECT_ID)

---

## Table of Contents

1. [Vision & Goals](#vision--goals)
2. [Key Concepts](#key-concepts)
3. [Data Flow Understanding](#data-flow-understanding)
4. [Validation Architecture](#validation-architecture)
5. [Player Universe Definition](#player-universe-definition)
6. [Phase-by-Phase Validation](#phase-by-phase-validation)
7. [Time-Aware Monitoring](#time-aware-monitoring)
8. [Edge Cases & Known Gaps](#edge-cases--known-gaps)
9. [Output Formats](#output-formats)
10. [CLI Interface](#cli-interface)
11. [Implementation Plan](#implementation-plan)
12. [Open Questions](#open-questions)

---

## Critical Findings from System Analysis

### Finding 1: Prediction Scope - ALL PLAYERS (IMPLEMENTED)

**Status:** ✓ COMPLETE - Implemented 2025-12-01

**What Changed:**
- `upcoming_player_game_context_processor.py` now uses gamebook as DRIVER (not props)
- ALL active players are processed, not just those with prop lines
- Added `has_prop_line` field to track which players have betting context
- Line source tracking (`line_source`, `estimated_line_value`, `estimation_method`)

**See:** `docs/08-projects/current/predictions-all-players/ALL-PLAYERS-PREDICTIONS-COMPLETE.md`

**Schema Migrations Required:**
```sql
-- Run before deployment:
ALTER TABLE `nba-props-platform.nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS has_prop_line BOOLEAN;

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS has_prop_line BOOLEAN,
ADD COLUMN IF NOT EXISTS line_source STRING,
ADD COLUMN IF NOT EXISTS estimated_line_value NUMERIC(4,1),
ADD COLUMN IF NOT EXISTS estimation_method STRING;
```

### Finding 2: Error Logging Architecture

**Error Storage Locations:**

| Location | Purpose | Query Pattern |
|----------|---------|---------------|
| `processor_run_history.errors` | Primary processor errors (JSON) | `SAFE.PARSE_JSON(errors)` |
| `processor_run_history.warnings` | Warnings (JSON) | Same pattern |
| `validation.validation_results` | Data quality checks | `WHERE passed = FALSE` |
| `scraper_execution_log` | Phase 1 scraper errors | `WHERE status = 'failed'` |

**Alert Tracking:**
- `alert_sent BOOLEAN` - Whether notification was sent
- `alert_type STRING` - 'error', 'warning', 'info'
- Rate-limited to 15-minute windows

### Finding 3: Firestore Orchestration State

**Collections:**
- `phase2_completion/{game_date}` - 21 processors
- `phase3_completion/{game_date}` - 5 processors

**Document Structure:**
```json
{
  "ProcessorName": {
    "completed_at": Timestamp,
    "status": "success",
    "record_count": 150
  },
  "_completed_count": 18,
  "_triggered": false,
  "_stall_alert_sent": false
}
```

**Query Pattern:**
```python
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase2_completion').document('2025-12-01').get()
data = doc.to_dict()
completed = len([k for k in data if not k.startswith('_')])
# Result: "18/21 complete"
```

### Finding 4: Fallback Source Validation

Validation should check fallback availability, not just primary:
- If `nbac_gamebook` missing → check `bdl_player_boxscores`
- If `odds_api_player_points_props` missing → check `bettingpros_player_points_props`
- Processor can succeed with fallback; validation should reflect this

---

## Vision & Goals

### Primary Goals

1. **Pre-backfill validation**: "Is Phase 2 data complete? Can I run Phase 3?"
2. **Post-backfill validation**: "Did all processors run successfully? Any gaps?"
3. **Quality assessment**: "What's the quality distribution? Any low-quality data?"
4. **Player completeness**: "Which players are missing from processing?"
5. **Live monitoring**: "Is today's orchestration running on schedule?"

### Long-term Vision

The validation script will serve as the **source of truth** for data quality checks. Eventually, processors themselves will use the same validation logic to:
- Pre-check dependencies before processing
- Validate their own outputs
- Report quality metrics consistently

### Use Cases

| Use Case | Command Example |
|----------|-----------------|
| Check historical date | `python3 bin/validate_pipeline.py 2021-10-19` |
| Verify backfill completed | `python3 bin/validate_pipeline.py 2021-10-19 --verbose` |
| Find missing players | `python3 bin/validate_pipeline.py 2021-10-19 --show-missing` |
| Monitor today's processing | `python3 bin/validate_pipeline.py today` |
| Validate date range | `python3 bin/validate_pipeline.py 2021-10-19 2021-10-31 --format=json` |

---

## Key Concepts

### Terminology

| Term | Definition |
|------|------------|
| **Game Date** | The date games were played (partition key for most tables) |
| **Analysis Date** | The date Phase 4 precompute runs for (typically game_date for historical) |
| **Bootstrap Period** | Days 0-6 of each season; Phase 4/5 skip due to insufficient history |
| **Season Year** | Year the season starts (e.g., 2024 for 2024-25 season) |
| **Player Universe** | Set of players expected to be processed for a given date |
| **Prop Line Players** | Subset of players with betting lines (flow to predictions) |

### Quality Tiers

| Tier | Score | Production Ready | Meaning |
|------|-------|------------------|---------|
| Gold | 95-100 | ✓ Yes | Primary source, complete data |
| Silver | 75-94 | ✓ Yes | Backup source used |
| Bronze | 50-74 | ✓ Yes | Reconstructed or thin sample |
| Poor | 25-49 | ✗ No | Below threshold, consider re-run |
| Unusable | 0-24 | ✗ No | Missing critical data, must re-run |

### Bootstrap Period Dates

Derived dynamically from `shared/config/nba_season_dates.py`:

| Season | Opener | Bootstrap End | Source |
|--------|--------|---------------|--------|
| 2021-22 | Oct 19, 2021 | Oct 25, 2021 | Schedule DB |
| 2022-23 | Oct 18, 2022 | Oct 24, 2022 | Schedule DB |
| 2023-24 | Oct 24, 2023 | Oct 30, 2023 | Schedule DB |
| 2024-25 | Oct 22, 2024 | Oct 28, 2024 | Schedule DB |

---

## Data Flow Understanding

### Complete Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PHASE 1: SCRAPERS                               │
│ Runs: 5-6 AM ET (schedule locker), 6 AM - 11 PM ET (hourly scrapers)        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                            PHASE 2: RAW PROCESSORS                           │
│ Triggered: Pub/Sub from Phase 1                                              │
│ Waits: Orchestrator waits for all 21 processors                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ nbac_gamebook_player_stats  │ PRIMARY: All players who played               │
│ nbac_team_boxscore          │ Team-level stats                              │
│ bdl_player_boxscores        │ FALLBACK: Player stats                        │
│ bettingpros_player_props    │ Prop lines (99.7% historical coverage)        │
│ nbac_schedule               │ Game schedule                                 │
│ odds_api_game_lines         │ Team spreads/totals                           │
│ ... (15 more)               │                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 3: ANALYTICS                                 │
│ Triggered: Pub/Sub after all Phase 2 complete                               │
│ Runs: All 5 processors in parallel                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────┐    ┌─────────────────────────────┐        │
│  │ player_game_summary        │    │ team_offense_game_summary   │        │
│  │ (ALL players who played)    │    │ (4 records for 2 games)     │        │
│  │ 67 players → 67 records     │    └─────────────────────────────┘        │
│  └─────────────────────────────┘                                           │
│                                     ┌─────────────────────────────┐        │
│  ┌─────────────────────────────┐    │ team_defense_game_summary   │        │
│  │ upcoming_player_game_context│    │ (4 records for 2 games)     │        │
│  │ (ONLY players with props)   │    └─────────────────────────────┘        │
│  │ 22 players → 22 records     │                                           │
│  └─────────────────────────────┘    ┌─────────────────────────────┐        │
│                                     │ upcoming_team_game_context  │        │
│                                     │ (4 records for 2 games)     │        │
│                                     └─────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PHASE 4: PRECOMPUTE                                 │
│ Triggered: Pub/Sub + CASCADE scheduler (11:00 PM PT)                        │
│ Bootstrap: SKIPPED during days 0-6 of season                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ team_defense_zone_analysis   │ L15 game rolling stats                       │
│ player_shot_zone_analysis    │ L10 game rolling stats                       │
│ player_composite_factors     │ Adjustment factors                           │
│ player_daily_cache           │ Cached player features                       │
│ ml_feature_store_v2          │ 25-feature vector per player (CRITICAL)      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 5: PREDICTIONS                               │
│ Triggered: Cloud Scheduler at 6:15 AM ET                                    │
│ Bootstrap: SKIPPED during days 0-6 (no ml_feature_store data)               │
├─────────────────────────────────────────────────────────────────────────────┤
│ ml_feature_store_v2 → 22 players with features                              │
│                      ↓                                                       │
│ Coordinator fans out to workers                                              │
│                      ↓                                                       │
│ player_prop_predictions: 22 players × 5 systems = 110 rows                  │
│                                                                             │
│ Prediction Systems:                                                          │
│   1. moving_average        - Weighted historical average                     │
│   2. zone_matchup_v1       - Shot zone vs opponent defense                   │
│   3. similarity_balanced_v1 - Similar game comparisons                       │
│   4. xgboost_v1            - ML model                                        │
│   5. ensemble_v1           - Confidence-weighted combination                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Player Flow Summary

**Current System (Props-Only Predictions):**
```
67 players in gamebook (all rostered)
       │
       ├──→ 67 in player_game_summary (all who played or were rostered)
       │
       └──→ 22 with prop lines
             │
             ├──→ 22 in upcoming_player_game_context  ← LIMITATION HERE
             │
             ├──→ 22 in ml_feature_store_v2 (non-bootstrap)
             │
             └──→ 110 rows in player_prop_predictions (22 × 5 systems)
```

**Desired System (All-Player Predictions):**
```
67 players in gamebook (all rostered)
       │
       ├──→ 67 in player_game_summary
       │
       ├──→ 67 in upcoming_player_game_context  ← CHANGE: All players
       │         │
       │         └──→ 22 have prop lines (flagged)
       │
       ├──→ 67 in ml_feature_store_v2
       │
       └──→ 335 rows in player_prop_predictions (67 × 5 systems)
                 │
                 └──→ 22 have prop line context for OVER/UNDER recommendations
```

**Validation Should Track Both:**
- "All players processed" (current goal: 67/67)
- "Prop-line players" (subset: 22 with betting context)
- "Prediction systems complete" (5/5 per player)

---

## Validation Architecture

### Module Structure

```
bin/
└── validate_pipeline.py              # Main CLI entry point

shared/
└── validation/
    ├── __init__.py
    ├── config.py                     # Thresholds, timeouts, table mappings
    │
    ├── context/
    │   ├── __init__.py
    │   ├── schedule_context.py       # Games, teams, bootstrap detection
    │   ├── player_universe.py        # Who should be processed
    │   └── time_context.py           # Time-aware expectations
    │
    ├── validators/
    │   ├── __init__.py
    │   ├── base.py                   # Common validation logic
    │   ├── phase2_validator.py       # Raw data validation
    │   ├── phase3_validator.py       # Analytics validation
    │   ├── phase4_validator.py       # Precompute validation
    │   └── phase5_validator.py       # Predictions validation
    │
    ├── player_flow.py                # Track players through pipeline
    ├── quality_analyzer.py           # Quality tier analysis
    ├── run_history.py                # processor_run_history queries
    │
    └── output/
        ├── terminal.py               # Terminal formatter
        └── json_output.py            # JSON formatter
```

### Core Classes

```python
@dataclass
class ValidationContext:
    """Everything we know about the date being validated."""
    game_date: date
    season_year: int
    season_day: int                   # Days since season opener
    is_bootstrap: bool                # Days 0-6
    is_today: bool
    is_historical: bool
    games: List[GameInfo]             # Games scheduled
    teams_playing: Set[str]
    expected_game_count: int

@dataclass
class PlayerUniverse:
    """All players relevant to this date."""
    rostered_players: Set[str]        # All in gamebook
    active_players: Set[str]          # player_status = 'active'
    dnp_players: Set[str]             # Did not play
    inactive_players: Set[str]        # Inactive/injured
    players_with_props: Set[str]      # Have betting lines

@dataclass
class PhaseValidationResult:
    """Result of validating a single phase."""
    phase: int
    status: str                       # 'complete', 'partial', 'missing', 'bootstrap_skip'
    tables: Dict[str, TableValidation]
    run_history: Dict[str, RunHistoryInfo]
    quality_distribution: QualityDistribution
    missing_players: Set[str]
    issues: List[str]
    warnings: List[str]

@dataclass
class PipelineValidationResult:
    """Complete validation result for a date."""
    context: ValidationContext
    player_universe: PlayerUniverse
    phases: Dict[int, PhaseValidationResult]
    player_flow: PlayerFlowAnalysis
    overall_status: str
    recommended_actions: List[str]
```

---

## Player Universe Definition

### Determining Expected Players

For a given date, we need to know:

1. **Who was rostered?** → `nbac_gamebook_player_stats` (all rows)
2. **Who actually played?** → `player_status = 'active'`
3. **Who has prop lines?** → `bettingpros_player_points_props`

```sql
-- Player Universe Query
WITH rostered AS (
    SELECT DISTINCT
        player_lookup,
        player_status,
        team_abbr
    FROM nba_raw.nbac_gamebook_player_stats
    WHERE game_date = @date
),
with_props AS (
    SELECT DISTINCT player_lookup
    FROM nba_raw.bettingpros_player_points_props
    WHERE game_date = @date
      AND is_active = TRUE
)
SELECT
    COUNT(DISTINCT r.player_lookup) as total_rostered,
    COUNTIF(r.player_status = 'active') as active_players,
    COUNTIF(r.player_status = 'dnp') as dnp_players,
    COUNTIF(r.player_status = 'inactive') as inactive_players,
    COUNT(DISTINCT p.player_lookup) as with_props
FROM rostered r
LEFT JOIN with_props p ON r.player_lookup = p.player_lookup
```

### Expectation by Phase

**After All-Player Predictions Change (Target State):**

| Phase | Table | Expected Players |
|-------|-------|------------------|
| 3 | player_game_summary | All active (67) |
| 3 | upcoming_player_game_context | All active (67) |
| 4 | ml_feature_store_v2 | All active (67) |
| 5 | player_prop_predictions | All active (67 × 5 = 335 rows) |

**Additional Tracking:**
- `has_prop_line = TRUE`: 22 players (have betting lines)
- `has_prop_line = FALSE`: 45 players (no betting lines, still predicted)

**Until Architectural Change (Current State):**
- Validation will show: "22/67 players have predictions (LIMITATION: props-only)"
- This flags the system limitation that needs to be fixed

### Registry Validation

For each date, verify players are properly registered:

```sql
-- Check players in gamebook are in registry
SELECT
    g.player_lookup,
    g.team_abbr,
    r.universal_player_id,
    r.player_lookup IS NULL as missing_from_registry
FROM nba_raw.nbac_gamebook_player_stats g
LEFT JOIN nba_reference.nba_players_registry r
    ON g.player_lookup = r.player_lookup
    AND g.team_abbr = r.team_abbr
    AND r.season = @season_string
WHERE g.game_date = @date
  AND g.player_status = 'active'
  AND r.player_lookup IS NULL
```

**Registry Issues to Flag:**
- Player in gamebook but not in registry → "Registry needs update"
- Player has no universal_player_id → "Missing ID assignment"
- Player on multiple teams without team_abbr filter → "Traded player - specify team"

---

## Phase-by-Phase Validation

### Phase 2: Raw Data

**Tables to check:**

| Table | Priority | Expected |
|-------|----------|----------|
| nbac_gamebook_player_stats | CRITICAL | Players for all games |
| nbac_team_boxscore | CRITICAL | 2 rows per game (home/away) |
| bdl_player_boxscores | FALLBACK | Same as gamebook |
| bettingpros_player_points_props | IMPORTANT | Prop lines |
| nbac_schedule | IMPORTANT | Game count |
| odds_api_game_lines | OPTIONAL | Spreads/totals |

**Validation checks:**
1. Game count matches schedule
2. Player count reasonable (8-15 per team per game)
3. All CRITICAL sources present
4. Record run history status

### Phase 3: Analytics

**Tables and expectations:**

| Table | Date Field | Expected Records |
|-------|------------|------------------|
| player_game_summary | game_date | All rostered players |
| team_defense_game_summary | game_date | 2 × game_count |
| team_offense_game_summary | game_date | 2 × game_count |
| upcoming_player_game_context | game_date | Players with props |
| upcoming_team_game_context | game_date | 2 × game_count |

**Validation checks:**
1. Record counts match expectations
2. All expected players present
3. Quality tier distribution
4. Run history status
5. No failed runs with errors

### Phase 4: Precompute

**Bootstrap handling:**
- Days 0-6: ALL Phase 4 tables should be empty (expected)
- Day 7+: All tables should have data

**Tables:**

| Table | Date Field | Expected Records |
|-------|------------|------------------|
| team_defense_zone_analysis | analysis_date | 2 × game_count |
| player_shot_zone_analysis | analysis_date | Players with history |
| player_composite_factors | analysis_date | Players with props |
| player_daily_cache | cache_date | Players with props |
| ml_feature_store_v2 | game_date | Players with props |

**Validation checks:**
1. If bootstrap: verify empty (not error)
2. If non-bootstrap: verify populated
3. Feature quality scores
4. Source tracking completeness

### Phase 5: Predictions

**Expected output:**
- 5 rows per player (one per prediction system)
- All 5 systems should generate predictions

**Validation checks:**
1. Player count matches ml_feature_store
2. All 5 systems generated per player
3. Confidence score distribution
4. No NULL predicted_points

```sql
-- Check all systems ran for each player
SELECT
    player_lookup,
    COUNT(DISTINCT system_id) as systems_count,
    ARRAY_AGG(DISTINCT system_id) as systems
FROM nba_predictions.player_prop_predictions
WHERE game_date = @date
GROUP BY player_lookup
HAVING COUNT(DISTINCT system_id) < 5
```

---

## Time-Aware Monitoring

### Orchestration Timeline (All times ET)

```
5:00 AM    Phase 1: Schedule Locker generates daily plan
6:00 AM    Phase 1: Master Controller first check
6:05 AM    Phase 1: Scrapers begin
           ↓ (runs until games complete, typically midnight)
~12:00 AM  Phase 1: Games complete, final scraper runs
~12:30 AM  Phase 2: All 21 processors triggered
~1:00 AM   Phase 2: Complete → Phase 3 triggered
~1:30 AM   Phase 3: Complete → Phase 4 (Pub/Sub processors) triggered
2:00 AM    Phase 4: CASCADE processors run (11 PM PT = 2 AM ET)
~3:00 AM   Phase 4: ml_feature_store complete
6:15 AM    Phase 5: Coordinator triggered
~6:20 AM   Phase 5: All predictions complete
```

### Time-Based Expectations

```python
def get_expected_status(game_date: date, current_time: datetime) -> dict:
    """Determine what should be complete based on current time."""

    if game_date == today:
        hour = current_time.hour  # ET
        if hour < 6:
            return {"phase5": "pending", "reason": "Runs at 6:15 AM"}
        elif hour < 7:
            return {"phase5": "in_progress_or_complete"}
        else:
            return {"phase5": "should_be_complete"}

    elif game_date == yesterday:
        if current_time.hour < 3:
            return {"phase4": "in_progress", "reason": "CASCADE running"}
        elif current_time.hour < 7:
            return {"phase5": "pending", "reason": "Runs at 6:15 AM"}
        else:
            return {"all": "should_be_complete"}

    else:  # Historical
        return {"all": "should_be_complete_or_never_ran"}
```

### Monitoring Mode Output

```
================================================================================
LIVE MONITORING: 2024-12-01 (Today) - Current Time: 2:30 PM ET
================================================================================

ORCHESTRATION STATUS
────────────────────────────────────────────────────────────────────────────────
Phase 1 (Scrapers):    ⏳ In Progress (games tonight at 7 PM)
Phase 2 (Raw):         ⏳ Waiting (after games complete ~midnight)
Phase 3 (Analytics):   ⏳ Waiting (after Phase 2 ~1 AM)
Phase 4 (Precompute):  ⏳ Waiting (CASCADE at 2 AM)
Phase 5 (Predictions): ✓ Complete (ran 6:15 AM, 437 players)

YESTERDAY (2024-11-30)
────────────────────────────────────────────────────────────────────────────────
All phases: ✓ Complete

ISSUES DETECTED
────────────────────────────────────────────────────────────────────────────────
None

NEXT EXPECTED RUNS
────────────────────────────────────────────────────────────────────────────────
Phase 2: ~12:30 AM (after games)
Phase 3: ~1:00 AM
Phase 4: ~2:00 AM (CASCADE)
Phase 5: 6:15 AM tomorrow
================================================================================
```

---

## Edge Cases & Known Gaps

### Handled Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Playoff games | Classified separately, included in validation |
| Postponed/cancelled | Filtered out (never happened) |
| All-Star games | Skipped by processors |
| Traded players | Query with team_abbr filter |
| Multiple teams/season | Use most recent activity date |
| Offseason dates | Show "No games scheduled" (not error) |
| Preseason dates | Show "Preseason - not processed" (expected) |
| All-Star break | Show "All-Star break - no regular games" |

### Special Date Handling

```python
def get_date_context(game_date: date) -> str:
    """Determine what kind of date this is."""

    # Check schedule for games
    games = query_schedule(game_date)

    if not games:
        # Check if it's offseason
        if game_date.month in [7, 8, 9]:
            return "offseason"
        # Check if near All-Star (mid-February)
        if game_date.month == 2 and 14 <= game_date.day <= 20:
            return "all_star_break"
        return "no_games"

    # Check game types
    if all(g.game_type == 'preseason' for g in games):
        return "preseason"
    if any(g.game_type == 'all_star' for g in games):
        return "all_star_game"

    return "regular_or_playoffs"
```

**Validation Output for Special Dates:**
```
================================================================================
PIPELINE VALIDATION: 2024-07-15 (Offseason)
================================================================================

DATE CONTEXT
────────────────────────────────────────────────────────────────────────────────
Status:     Offseason (no games scheduled)
Games:      0
Note:       NBA offseason runs July-September

→ No validation needed for this date.
================================================================================
```

### Known Data Gaps

| Gap | Impact | Resolution |
|-----|--------|------------|
| 6 Play-In games 2025 | No team boxscore data | Accepted, documented |
| Play-by-play sparse | Shot zones NULL | Accepted, quality=bronze |
| Historical odds limited | 40% coverage pre-2023 | BettingPros fallback (99.7%) |

### Bootstrap Period Behavior

| Phase | Bootstrap (Days 0-6) | Post-Bootstrap (Day 7+) |
|-------|---------------------|------------------------|
| Phase 2 | ✓ Runs normally | ✓ Runs normally |
| Phase 3 | ✓ Runs normally | ✓ Runs normally |
| Phase 4 | ⊘ Skips (expected) | ✓ Runs normally |
| Phase 5 | ⊘ Skips (expected) | ✓ Runs normally |

---

## Output Formats

### Terminal Output (Default)

See proposed output in main design section above.

Key features:
- Color-coded status indicators
- Quality distribution summary (48G 15S 4B)
- Missing player counts
- Actionable recommendations

### Verbose Mode (`--verbose`)

Adds:
- Full run history details (run_id, duration, record counts)
- Source tracking information
- Dependency check results
- Alert history

### JSON Output (`--format=json`)

```json
{
  "validation_date": "2021-10-19",
  "validation_timestamp": "2025-12-01T14:30:00Z",
  "context": {
    "season_year": 2021,
    "season_day": 0,
    "is_bootstrap": true,
    "games": [
      {"game_id": "0022100001", "home": "MIL", "away": "BKN"},
      {"game_id": "0022100002", "home": "LAL", "away": "GSW"}
    ]
  },
  "player_universe": {
    "total_rostered": 67,
    "active": 54,
    "dnp": 8,
    "inactive": 5,
    "with_props": 22
  },
  "phases": {
    "2": {
      "status": "complete",
      "tables": {...},
      "issues": []
    },
    "3": {...},
    "4": {...},
    "5": {...}
  },
  "overall_status": "complete",
  "quality_summary": {
    "gold": 48,
    "silver": 15,
    "bronze": 4,
    "poor": 0,
    "unusable": 0
  },
  "missing_players": [],
  "recommended_actions": []
}
```

---

## CLI Interface

### Basic Commands

```bash
# Single date validation
python3 bin/validate_pipeline.py 2021-10-19

# Today (time-aware monitoring)
python3 bin/validate_pipeline.py today

# Yesterday
python3 bin/validate_pipeline.py yesterday
```

### Options

```bash
# Verbose output (run history details)
--verbose, -v

# Show missing players explicitly
--show-missing

# Output format
--format=terminal (default)
--format=json

# Specific phase only
--phase=3

# Date range
python3 bin/validate_pipeline.py 2021-10-19 2021-10-31
```

### Examples

```bash
# Quick check: did backfill work?
python3 bin/validate_pipeline.py 2021-10-19

# Deep dive: what went wrong?
python3 bin/validate_pipeline.py 2021-10-19 --verbose --show-missing

# Automation: JSON for downstream processing
python3 bin/validate_pipeline.py 2021-10-19 --format=json > validation.json

# Range check: entire first week
python3 bin/validate_pipeline.py 2021-10-19 2021-10-25 --format=json

# Live monitoring
python3 bin/validate_pipeline.py today
```

---

## Implementation Status

### ✓ Phase 1: Core Single-Date Validation (COMPLETE)

**Files Created:**
- `bin/validate_pipeline.py` - CLI entry point
- `shared/validation/config.py` - Configuration
- `shared/validation/context/schedule_context.py` - Game/schedule detection
- `shared/validation/context/player_universe.py` - Player set determination
- `shared/validation/validators/base.py` - Common validation logic
- `shared/validation/validators/phase{2,3,4,5}_validator.py` - Per-phase checks
- `shared/validation/output/terminal.py` - Terminal formatter

**Capabilities:**
- ✓ Single date validation
- ✓ All 5 phases checked
- ✓ Quality distribution (G/S/B/P/U)
- ✓ Missing player counts
- ✓ Bootstrap period detection

### ✓ Phase 2: Verbose and Show-Missing (COMPLETE)

**Files Created:**
- `shared/validation/run_history.py` - Run history queries

**Capabilities:**
- ✓ `--verbose` flag with run history details
- ✓ Processor errors, dependency failures, alerts sent
- ✓ `--show-missing` flag with explicit player lists
- ✓ Per-processor duration and record counts

### ✓ Phase 3: Time-Aware Monitoring (COMPLETE)

**Files Created:**
- `shared/validation/time_awareness.py` - Time context
- `shared/validation/firestore_state.py` - Orchestration state

**Capabilities:**
- ✓ "today" and "yesterday" special handling
- ✓ Expected phase status based on time of day
- ✓ Firestore orchestration state ("18/21 complete")
- ✓ "Next expected run" predictions

### ✓ Phase 4: JSON Output (COMPLETE)

**Files Created:**
- `shared/validation/output/json_output.py` - JSON formatter

**Capabilities:**
- ✓ `--format=json` for machine-readable output
- ✓ Complete validation data in structured format
- ✓ Quality summary across all phases

### ✓ Phase 5: V2 Refinements (COMPLETE - 2025-12-02)

**Changes Made:**
- Centralized PROJECT_ID (no more hardcoded strings)
- Added missing GCS path for `espn_boxscores`
- Improved test coverage: 24 → 32 tests
- Tests for `_build_impact_message()`, `_get_date_column()`, `get_chain_summary()`
- Guard test to catch missing GCS paths for future sources

### Remaining (Future)

- Date range validation with chain view summary
- Alert integration (Slack/email on validation failures)
- Phase 6 (Publishing) validation support
- Consolidate PHASE2_SOURCES (config.py) to YAML only

---

## Error Display in Validation

### Error Sources to Query

The validation script should surface errors from multiple sources:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ERROR DISPLAY                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. PROCESSOR ERRORS (processor_run_history)                                │
│     └─ JSON array in `errors` field                                         │
│     └─ Query: WHERE data_date = @date AND status = 'failed'                │
│                                                                             │
│  2. VALIDATION FAILURES (validation.validation_results)                     │
│     └─ Data quality check failures                                          │
│     └─ Includes remediation_commands                                        │
│                                                                             │
│  3. SCRAPER ERRORS (scraper_execution_log)                                  │
│     └─ Phase 1 failures                                                     │
│     └─ Fields: error_type, error_message                                    │
│                                                                             │
│  4. DEPENDENCY FAILURES (processor_run_history)                             │
│     └─ missing_dependencies, stale_dependencies (JSON arrays)               │
│     └─ dependency_check_passed = FALSE                                      │
│                                                                             │
│  5. ALERTS SENT (processor_run_history)                                     │
│     └─ alert_sent = TRUE, alert_type                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Sample Error Output

```
================================================================================
ERRORS & ISSUES: 2021-10-19
================================================================================

PROCESSOR ERRORS (1)
────────────────────────────────────────────────────────────────────────────────
✗ TeamDefenseGameSummaryProcessor
  Status:    failed
  Error:     KeyError: 'points_allowed' not found in row
  Time:      2025-12-01 02:15:43 UTC
  Run ID:    tdgs_20211019_021543_abc123

DEPENDENCY FAILURES (1)
────────────────────────────────────────────────────────────────────────────────
⚠ PlayerCompositeFactorsProcessor
  Missing:   ['player_shot_zone_analysis']
  Stale:     []
  Action:    Run player_shot_zone_analysis first

ALERTS SENT (2)
────────────────────────────────────────────────────────────────────────────────
  [ERROR] TeamDefenseGameSummaryProcessor - 02:15:43
  [WARNING] UpcomingPlayerContext - thin_sample - 01:45:22

VALIDATION WARNINGS (3)
────────────────────────────────────────────────────────────────────────────────
  ⚠ player_game_summary: 4 records with quality_tier='bronze'
  ⚠ bdl_player_boxscores: Using as fallback (primary source missing)
  ⚠ Phase 5: Only 22/67 players have predictions (props-only limitation)
================================================================================
```

---

## Identified System Improvements

During analysis, we identified several system improvement opportunities:

### Improvement 1: All-Player Predictions (HIGH PRIORITY)

**Current:** Only players with prop lines get predictions (22/67)
**Desired:** All players get predictions (67/67)

**Changes Required:**
1. `upcoming_player_game_context_processor.py`: Change DRIVER query from props to gamebook
2. Add `has_prop_line BOOLEAN` field to track which players have betting context
3. `ml_feature_store_processor.py`: Process all players from upcoming_player_game_context
4. Phase 5 coordinator: Process all players, generate predictions for all
5. Predictions: Can still provide OVER/UNDER recommendations only for prop-line players

**Validation Impact:**
- Validation should track both "all players" and "prop-line players"
- Flag when current system limitation is active

### Improvement 2: Document Prediction System Changes

**Issue:** If prediction systems change (add/remove systems), validation needs to know.

**Recommendation:** Create config file that documents expected systems:
```python
# shared/validation/config.py
EXPECTED_PREDICTION_SYSTEMS = [
    'moving_average',
    'zone_matchup_v1',
    'similarity_balanced_v1',
    'xgboost_v1',
    'ensemble_v1',
]
```

Validation checks this list, alerts if systems added/removed.

### Improvement 3: Fallback Source Transparency

**Issue:** Validation should clearly show when fallback sources are used.

**Current:** Processors use fallbacks silently (quality_tier reflects this)
**Desired:** Validation explicitly shows:
```
Phase 2 Sources:
  nbac_gamebook_player_stats:     ✓ Primary (67 records)
  bdl_player_boxscores:           ✓ Available (fallback ready)
  bettingpros_player_points_props: ✓ Primary (1,247 records)
  odds_api_player_points_props:   ○ Empty (BettingPros fallback used)
```

### Improvement 4: Centralized Bootstrap Detection

**Issue:** Bootstrap dates are hardcoded in multiple places.

**Current State:** Already have `shared/config/nba_season_dates.py` with dynamic detection.
**Validation Should:** Use this centralized source, not hardcode dates.

---

## Open Questions

### Resolved

1. **Q: Which players should have predictions?**
   A: User wants ALL players (system currently limits to prop-line only - architectural change needed)

2. **Q: How many prediction rows per player?**
   A: 5 rows (one per prediction system)

3. **Q: What about bootstrap periods?**
   A: Phase 4/5 correctly skip; Phase 2/3 still run

4. **Q: Firestore state checking?**
   A: YES - Include Firestore queries to show "18/21 processors complete"

5. **Q: Error display?**
   A: YES - Query processor_run_history, validation_results, scraper_execution_log

### Decisions Made

1. **Re-run recommendations**: Include basic guidance (not full commands) in Phase 1
   - "Run Phase 3 backfill for player_game_summary"
   - Full copy-paste commands in Phase 2

2. **Output format**: Terminal default, JSON with `--format=json`

3. **Date range**: Support single date first, add range in Phase 2

### Still Open

1. **Alerting integration**: Should validation failures trigger Slack/email alerts?
   - Could be Phase 3 feature
   - Would integrate with existing ProcessorAlerting class

2. **Phase 6 (Publishing)**: Future support for validating published predictions
   - User mentioned this as future goal
   - Design should accommodate extensibility

3. **System architecture change**: When to implement all-player predictions?
   - Separate project from validation script
   - Validation will highlight the limitation until fixed

---

## Appendix: SQL Query Templates

### A1: Game Context Query
```sql
SELECT
    game_id,
    game_date,
    home_team_tricode,
    away_team_tricode,
    game_status_text
FROM nba_raw.nbac_schedule
WHERE game_date = @date
ORDER BY game_id
```

### A2: Player Universe Query
```sql
WITH gamebook AS (
    SELECT DISTINCT
        player_lookup,
        player_status,
        team_abbr
    FROM nba_raw.nbac_gamebook_player_stats
    WHERE game_date = @date
),
props AS (
    SELECT DISTINCT player_lookup
    FROM nba_raw.bettingpros_player_points_props
    WHERE game_date = @date AND is_active = TRUE
)
SELECT
    g.player_lookup,
    g.player_status,
    g.team_abbr,
    p.player_lookup IS NOT NULL as has_props
FROM gamebook g
LEFT JOIN props p ON g.player_lookup = p.player_lookup
```

### A3: Phase 3 Completeness Query
```sql
SELECT
    'player_game_summary' as table_name,
    COUNT(*) as records,
    COUNT(DISTINCT player_lookup) as players,
    COUNTIF(quality_tier = 'gold') as gold,
    COUNTIF(quality_tier = 'silver') as silver,
    COUNTIF(quality_tier = 'bronze') as bronze,
    COUNTIF(quality_tier = 'poor') as poor,
    COUNTIF(quality_tier = 'unusable') as unusable
FROM nba_analytics.player_game_summary
WHERE game_date = @date
```

### A4: Prediction Systems Check
```sql
SELECT
    player_lookup,
    COUNT(DISTINCT system_id) as systems,
    STRING_AGG(system_id, ', ') as system_list
FROM nba_predictions.player_prop_predictions
WHERE game_date = @date
GROUP BY player_lookup
HAVING COUNT(DISTINCT system_id) < 5
```

### A5: Run History Query
```sql
SELECT
    processor_name,
    status,
    duration_seconds,
    records_processed,
    records_created,
    dependency_check_passed,
    alert_sent,
    started_at,
    processed_at
FROM nba_reference.processor_run_history
WHERE data_date = @date
ORDER BY phase, processor_name
```

---

## Ready for Implementation Checklist

### Research Complete

- [x] All 5 phases documented with tables, columns, expectations
- [x] Player universe definition (all players + prop-line flag)
- [x] Quality tier system understood and documented
- [x] Error logging architecture mapped (4 sources)
- [x] Firestore orchestration state documented
- [x] Time-aware monitoring timeline established
- [x] Bootstrap period handling using centralized config
- [x] Edge cases identified (playoffs, offseason, All-Star, traded players)
- [x] Registry validation queries defined
- [x] Prediction systems documented (5 systems, 5 rows per player)

### Design Complete

- [x] Module architecture defined (`shared/validation/`)
- [x] Core classes specified (ValidationContext, PlayerUniverse, etc.)
- [x] CLI interface designed with flags
- [x] Terminal output format designed
- [x] JSON output structure defined
- [x] SQL query templates provided

### Dependencies Identified

- [x] All-player predictions architectural change (separate handoff created)
- [x] Prediction system config should be centralized (improvement noted)
- [x] Fallback source transparency (improvement noted)

### Implementation Phases Defined

1. **Phase 1**: Core single-date validation (all phases, terminal output)
2. **Phase 2**: Verbose mode, show-missing, re-run commands
3. **Phase 3**: Time-aware monitoring for "today"
4. **Phase 4**: JSON output, date ranges

---

## Related Documents

| Document | Purpose |
|----------|---------|
| `docs/08-projects/current/validation/VALIDATION-SCRIPT-DESIGN.md` | This document |
| `docs/08-projects/current/predictions-all-players/ALL-PLAYERS-PREDICTIONS-HANDOFF.md` | Architectural change handoff |
| `docs/08-projects/current/backfill/VALIDATION-SCRIPT-IMPROVEMENTS.md` | Original requirements |
| `bin/backfill/validate_and_plan.py` | Current (limited) validation script |

---

*Document version: 2.0*
*Last updated: 2025-12-01*
*Status: READY FOR IMPLEMENTATION*
