# Validation Script V2 Design

## Overview

Redesign the validation script to organize data sources by **fallback chains** (from `fallback_config.yaml`) instead of flat lists. This provides better insight into data availability and which sources are being used.

## Current State

```
PHASE 1: GCS JSON (5 sources, flat list)
PHASE 2: RAW DATA (7 sources, flat list)
```

Problems:
- Only shows ~7 of 15+ data sources
- No visibility into fallback chain status
- No roster/registry tracking for daily orchestration
- Doesn't show which source is primary vs fallback

## Proposed Design

### Phase 1 & 2: Organize by Fallback Chain

```
================================================================================
PHASE 1-2: DATA SOURCES BY CHAIN
================================================================================

Chain: player_boxscores (critical) ─────────────────────── Status: ✓ Complete
  Source                          GCS JSON    BQ Records   Quality   Status
  ────────────────────────────────────────────────────────────────────────────
  ★ nbac_gamebook_player_stats         6          67       gold      ✓ Primary
    bdl_player_boxscores               0          67       silver    ✓ Available
    espn_boxscores                     0           0       silver    ○ Missing

Chain: team_boxscores (critical) ───────────────────────── Status: ✓ Complete
  ★ nbac_team_boxscore                 0           4       gold      ✓ Primary
    reconstructed_from_players         -           -       silver    ⊘ Virtual
    espn_team_boxscore                 0           0       silver    ○ Missing

Chain: player_props (warning) ──────────────────────────── Status: ✓ Complete
  ★ odds_api_player_points_props       0         122       gold      ✓ Primary
    bettingpros_player_points_props    2         248       silver    ✓ Available

Chain: game_schedule (critical) ────────────────────────── Status: ✓ Complete
  ★ nbac_schedule                      0          14       gold      ✓ Primary
    espn_scoreboard                    0           0       silver    ○ Missing

Chain: game_lines (info) ───────────────────────────────── Status: ✓ Complete
  ★ odds_api_game_lines                0         112       gold      ✓ Primary

Chain: shot_zones (info) ───────────────────────────────── Status: △ Partial
  ★ bigdataball_play_by_play           0           0       gold      ○ Missing
    nbac_play_by_play                  0           0       silver    ○ Missing
  └─ Impact: Shot zone analysis will be skipped (-15 quality)

Chain: injury_reports (info) ───────────────────────────── Status: ✓ Complete
  ★ nbac_injury_report                 0          45       gold      ✓ Primary
    bdl_injuries                       0          38       silver    ✓ Available

→ Data Sources: 6/7 chains complete, 1 partial
```

### Daily Maintenance Section (for today/yesterday only)

```
================================================================================
DAILY MAINTENANCE (Roster & Registry)
================================================================================

Chain: player_roster (reference) ───────────────────────── Status: ✓ Current
  Source                          Last Updated    Records   Quality   Status
  ────────────────────────────────────────────────────────────────────────────
  ★ nbac_player_list_current      2024-11-27        612     gold      ✓ Current
    bdl_active_players_current    2024-11-27        598     silver    ✓ Current
    br_rosters_current            2024-11-25        610     silver    △ Stale (2 days)

Registry Status:
  nba_players_registry            2024-11-27      4,823     -         ✓ Updated
  Last sync: 08:15:32 PST

→ Registry: Current, 4,823 players tracked
```

### Progress Bar Update

Add P1 (GCS) indicator merged with P2:

```
Pipeline Progress: [████████████████████████████░░░░░░░░░░░░░░░░░░░░░░] 55%
                   P1-2✓ P3△ P4○ P5○
```

Or keep separate but show chain status:
```
                   GCS✓ BQ✓ P3△ P4○ P5○  (6/7 chains complete)
```

## Implementation Plan

### Step 1: Update Config to Use fallback_config.yaml

```python
# shared/validation/config.py

def load_fallback_chains():
    """Load fallback chain config from YAML."""
    config_path = 'shared/config/data_sources/fallback_config.yaml'
    with open(config_path) as f:
        return yaml.safe_load(f)

FALLBACK_CHAINS = load_fallback_chains()['fallback_chains']
DATA_SOURCES = load_fallback_chains()['sources']
```

### Step 2: Create Chain Validator

```python
# shared/validation/validators/chain_validator.py

@dataclass
class ChainValidation:
    chain_name: str
    description: str
    severity: str  # critical, warning, info
    status: ValidationStatus
    sources: List[SourceValidation]
    primary_available: bool
    fallback_used: bool
    impact_message: Optional[str] = None

def validate_chain(
    chain_name: str,
    chain_config: dict,
    game_date: date,
    client: bigquery.Client,
) -> ChainValidation:
    """Validate a complete fallback chain."""
    ...
```

### Step 3: Merge Phase 1 & 2 into Chain View

Instead of separate Phase 1 (GCS) and Phase 2 (BQ) sections, show unified chain view that includes both:
- GCS file count (from Phase 1 logic)
- BQ record count (from Phase 2 logic)
- Quality tier (from fallback_config.yaml)
- Status (primary/fallback/missing)

### Step 4: Add Daily Maintenance Section

```python
# shared/validation/validators/maintenance_validator.py

def validate_maintenance(
    game_date: date,
    time_context: TimeContext,
    client: bigquery.Client,
) -> MaintenanceValidation:
    """Validate daily maintenance tasks (roster, registry)."""

    if not (time_context.is_today or time_context.is_yesterday):
        return None  # Skip for historical dates

    # Check roster sources
    roster_chain = validate_chain('player_roster', ...)

    # Check registry last update
    registry_status = query_registry_status(client, game_date)

    return MaintenanceValidation(
        roster_chain=roster_chain,
        registry_status=registry_status,
    )
```

### Step 5: Update Terminal Output

```python
# shared/validation/output/terminal.py

def _format_chain_section(chains: List[ChainValidation], use_color: bool) -> str:
    """Format all chains in a unified view."""
    ...

def _format_maintenance_section(maintenance: MaintenanceValidation, use_color: bool) -> str:
    """Format daily maintenance status."""
    ...
```

## Data Source Mapping

From `fallback_config.yaml`:

| Chain | Sources | GCS Path | BQ Table | Severity |
|-------|---------|----------|----------|----------|
| player_boxscores | nbac_gamebook, bdl, espn | nba-com/gamebooks-data, ball-dont-lie/player-boxscores | nbac_gamebook_player_stats, bdl_player_boxscores, espn_boxscores | critical |
| team_boxscores | nbac_team, reconstructed, espn | nba-com/team-boxscore | nbac_team_boxscore | critical |
| player_props | odds_api, bettingpros | bettingpros/player-props | odds_api_player_points_props, bettingpros_player_points_props | warning |
| game_schedule | nbac_schedule, espn | nba-com/schedule | nbac_schedule, espn_scoreboard | critical |
| game_lines | odds_api | odds-api/game-lines | odds_api_game_lines | info |
| shot_zones | bigdataball, nbac_pbp | big-data-ball/play-by-play | bigdataball_play_by_play, nbac_play_by_play | info |
| injury_reports | nbac_injury, bdl | nba-com/injury-report-data | nbac_injury_report, bdl_injuries | info |
| player_roster | nbac_player, bdl, br | - | nbac_player_list_current, bdl_active_players_current, br_rosters_current | critical |

## Benefits

1. **Better visibility**: See which chains are complete vs missing data
2. **Fallback awareness**: Know when fallback sources are being used
3. **Quality tracking**: See quality tier of each source
4. **Impact clarity**: Know what happens when sources are missing
5. **Daily ops**: Track roster/registry updates for orchestration monitoring
6. **Unified view**: GCS + BQ in one place per chain

## Migration Path

1. Keep existing Phase 1-5 structure for backwards compatibility
2. Add new `--chain-view` flag to use new format
3. Once validated, make chain view the default
4. Deprecate flat source lists

## Files to Modify

- `shared/validation/config.py` - Load from fallback_config.yaml
- `shared/validation/validators/chain_validator.py` - New file
- `shared/validation/validators/maintenance_validator.py` - New file
- `shared/validation/validators/phase1_validator.py` - Refactor to use chains
- `shared/validation/validators/phase2_validator.py` - Refactor to use chains
- `shared/validation/output/terminal.py` - New chain formatting
- `bin/validate_pipeline.py` - Add --chain-view flag

## Timeline

- Session 1: Implement chain validator + config loading
- Session 2: Update terminal output + maintenance section
- Session 3: Testing + migration to default

## Open Questions

1. Should we keep Phase 1/2 separate or merge into "Data Sources"?
2. How to handle virtual sources (reconstructed_team_from_players)?
3. Should maintenance section be opt-in (--show-maintenance) or auto for today/yesterday?
