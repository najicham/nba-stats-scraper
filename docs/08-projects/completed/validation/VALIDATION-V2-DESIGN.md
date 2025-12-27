# Validation Script V2 Design

**Created:** 2025-12-01
**Status:** ✓ IMPLEMENTED (2025-12-01) + REFINED (2025-12-02)
**Author:** Claude + User collaboration

---

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

### Current Output Sample (2021-10-19)

```
================================================================================
PHASE 1: GCS JSON
================================================================================

Source                           JSON Files   Expected       Status
────────────────────────────────────────────────────────────────────────────────
gamebook_json                             6          2 ✓ Complete
team_boxscore_json                        0          2 ○ Missing
bettingpros_props_json                    0          2 ○ Missing
schedule_json                             0          2 ○ Missing
bdl_boxscores_json                        0          2 ○ Missing

→ Phase 1: △ Partial - needs attention (6 records)

================================================================================
PHASE 2: RAW DATA (BQ)
================================================================================

Source                                      Records     Status
────────────────────────────────────────────────────────────────────────────────
nbac_gamebook_player_stats                       67 ✓ Complete
nbac_team_boxscore                                8 ✓ Complete
bdl_player_boxscores                             51 ✓ Complete
bettingpros_player_points_props                1666 ✓ Complete
odds_api_player_points_props                      - ○ Missing
nbac_schedule                                     2 ✓ Complete
odds_api_game_lines                              16 △ Partial

→ Phase 2: ✓ Complete (1810 records)
```

**Key insight:** BQ Phase 2 shows "Complete" but GCS Phase 1 shows "Partial" - the chain view will unify this and show that the chain has data available.

---

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
    bdl_player_boxscores               0          51       silver    ✓ Available
    espn_boxscores                     -           0       silver    ○ Missing

Chain: team_boxscores (critical) ───────────────────────── Status: ✓ Complete
  ★ nbac_team_boxscore                 0           8       gold      ✓ Primary
    reconstructed_from_players         -           -       silver    ⊘ Virtual
    espn_team_boxscore                 -           0       silver    ○ Missing

Chain: player_props (warning) ──────────────────────────── Status: ✓ Complete
  ★ odds_api_player_points_props       -           0       gold      ○ Missing
    bettingpros_player_points_props    0        1666       silver    ✓ Fallback
  └─ Note: Using fallback source (silver quality)

Chain: game_schedule (critical) ────────────────────────── Status: ✓ Complete
  ★ nbac_schedule                      0           2       gold      ✓ Primary
    espn_scoreboard                    -           0       silver    ○ Missing

Chain: game_lines (info) ───────────────────────────────── Status: △ Partial
  ★ odds_api_game_lines                -          16       gold      △ Partial

Chain: shot_zones (info) ───────────────────────────────── Status: ○ Missing
  ★ bigdataball_play_by_play           -           0       gold      ○ Missing
    nbac_play_by_play                  -           0       silver    ○ Missing
  └─ Impact: Shot zone analysis will be skipped (-15 quality)

Chain: injury_reports (info) ───────────────────────────── Status: ○ Missing
  ★ nbac_injury_report                 -           0       gold      ○ Missing
    bdl_injuries                       -           0       silver    ○ Missing

→ Data Sources: 4/7 chains complete, 1 partial, 2 missing
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

Keep separate but show chain status:
```
Pipeline Progress: [████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 41%
                   P1-2△ P3○ P4⊘ P5⊘  (4/7 chains complete)
```

---

## Open Questions - RESOLVED

### Q1: Should we keep Phase 1/2 separate or merge into "Data Sources"?
**Decision:** Merge into unified chain view. The chain shows both GCS and BQ columns, making it clear what stage the data is at.

### Q2: How to handle virtual sources (reconstructed_team_from_players)?
**Decision:** Show with status `⊘ Virtual` and dash (`-`) for counts. Virtual sources are "always available" if their input chain has data. Add note in chain status if virtual fallback would be used.

### Q3: Should maintenance section be opt-in or auto for today/yesterday?
**Decision:** Auto-show for today/yesterday. Can add `--hide-maintenance` flag later if needed.

---

## Detailed Implementation Specification

### File Structure

```
shared/
└── validation/
    ├── config.py                      # UPDATE: Add fallback chain loading
    ├── chain_config.py                # NEW: Chain configuration dataclasses
    │
    ├── validators/
    │   ├── chain_validator.py         # NEW: Core chain validation logic
    │   ├── maintenance_validator.py   # NEW: Roster/registry validation
    │   ├── phase1_validator.py        # KEEP: Still used internally by chain_validator
    │   ├── phase2_validator.py        # KEEP: Still used internally by chain_validator
    │   └── ...
    │
    └── output/
        └── terminal.py                # UPDATE: Add chain formatting functions

bin/
└── validate_pipeline.py               # UPDATE: Add --chain-view flag
```

### Step 1: Chain Configuration (chain_config.py)

```python
"""
Chain configuration dataclasses for validation.
Loads from shared/config/data_sources/fallback_config.yaml
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
import yaml


@dataclass
class SourceConfig:
    """Configuration for a single data source."""
    name: str
    description: str
    table: Optional[str]
    dataset: str
    is_primary: bool
    is_virtual: bool
    quality_tier: str  # gold, silver, bronze
    quality_score: int
    gcs_path_template: Optional[str] = None  # From gcs_path_builder mapping
    reconstruction_method: Optional[str] = None
    extraction_method: Optional[str] = None


@dataclass
class ChainConfig:
    """Configuration for a fallback chain."""
    name: str
    description: str
    severity: str  # critical, warning, info
    sources: List[SourceConfig]
    on_all_fail_action: str  # skip, placeholder, fail, continue_without
    on_all_fail_message: str
    quality_impact: int = 0  # Quality penalty when chain fails


@dataclass
class SourceValidation:
    """Validation result for a single source."""
    source: SourceConfig
    gcs_file_count: Optional[int] = None  # None if no GCS path
    bq_record_count: int = 0
    status: str = "missing"  # primary, fallback, available, missing, virtual


@dataclass
class ChainValidation:
    """Validation result for a complete chain."""
    chain: ChainConfig
    sources: List[SourceValidation]
    status: str  # complete, partial, missing
    primary_available: bool = False
    fallback_used: bool = False
    impact_message: Optional[str] = None


# GCS path mapping (from gcs_path_builder.py)
GCS_PATH_MAPPING = {
    'nbac_gamebook_player_stats': 'nba-com/gamebooks-data',
    'nbac_team_boxscore': 'nba-com/team-boxscore',
    'bdl_player_boxscores': 'ball-dont-lie/player-boxscores',
    'bettingpros_player_points_props': 'bettingpros/player-props',
    'odds_api_player_points_props': 'odds-api/player-props',
    'odds_api_game_lines': 'odds-api/game-lines',
    'nbac_schedule': 'nba-com/schedule',  # Note: uses season, not date
    'espn_scoreboard': 'espn/scoreboard',
    'bigdataball_play_by_play': 'big-data-ball',  # Complex path with season
    'nbac_play_by_play': 'nba-com/play-by-play',
    'nbac_injury_report': 'nba-com/injury-report-data',
    'bdl_injuries': 'ball-dont-lie/injuries',
}

# Sources that use season-based paths instead of date-based
SEASON_BASED_GCS_SOURCES = {'nbac_schedule', 'bigdataball_play_by_play'}


def load_chain_configs() -> Dict[str, ChainConfig]:
    """Load fallback chain configs from YAML."""
    config_path = Path(__file__).parent.parent / 'config' / 'data_sources' / 'fallback_config.yaml'

    with open(config_path) as f:
        data = yaml.safe_load(f)

    sources_data = data['sources']
    chains_data = data['fallback_chains']

    chains = {}
    for chain_name, chain_data in chains_data.items():
        # Build source configs
        source_configs = []
        for i, source_name in enumerate(chain_data['sources']):
            source_data = sources_data.get(source_name, {})
            source_configs.append(SourceConfig(
                name=source_name,
                description=source_data.get('description', ''),
                table=source_data.get('table'),
                dataset=source_data.get('dataset', 'nba_raw'),
                is_primary=(i == 0),  # First source is primary
                is_virtual=source_data.get('is_virtual', False),
                quality_tier=source_data.get('quality', {}).get('tier', 'silver'),
                quality_score=source_data.get('quality', {}).get('score', 85),
                gcs_path_template=GCS_PATH_MAPPING.get(source_name),
                reconstruction_method=source_data.get('reconstruction_method'),
                extraction_method=source_data.get('extraction_method'),
            ))

        on_all_fail = chain_data.get('on_all_fail', {})
        chains[chain_name] = ChainConfig(
            name=chain_name,
            description=chain_data.get('description', ''),
            severity=on_all_fail.get('severity', 'info'),
            sources=source_configs,
            on_all_fail_action=on_all_fail.get('action', 'skip'),
            on_all_fail_message=on_all_fail.get('message', ''),
            quality_impact=on_all_fail.get('quality_impact', 0),
        )

    return chains


# Singleton for loaded configs
_CHAIN_CONFIGS: Optional[Dict[str, ChainConfig]] = None

def get_chain_configs() -> Dict[str, ChainConfig]:
    """Get chain configs (cached)."""
    global _CHAIN_CONFIGS
    if _CHAIN_CONFIGS is None:
        _CHAIN_CONFIGS = load_chain_configs()
    return _CHAIN_CONFIGS
```

### Step 2: Chain Validator (chain_validator.py)

```python
"""
Chain Validator - Validates data sources organized by fallback chains.
"""

from datetime import date
from typing import Dict, List, Optional
import logging

from google.cloud import bigquery, storage

from shared.validation.chain_config import (
    ChainConfig,
    ChainValidation,
    SourceConfig,
    SourceValidation,
    get_chain_configs,
    GCS_PATH_MAPPING,
    SEASON_BASED_GCS_SOURCES,
)
from shared.validation.context.schedule_context import ScheduleContext

logger = logging.getLogger(__name__)

GCS_BUCKET = 'nba-scraped-data'


def validate_all_chains(
    game_date: date,
    schedule_context: ScheduleContext,
    bq_client: Optional[bigquery.Client] = None,
    gcs_client: Optional[storage.Client] = None,
) -> Dict[str, ChainValidation]:
    """
    Validate all fallback chains for a given date.

    Returns dict mapping chain_name -> ChainValidation
    """
    if bq_client is None:
        bq_client = bigquery.Client(project='nba-props-platform')
    if gcs_client is None:
        gcs_client = storage.Client()

    chain_configs = get_chain_configs()
    results = {}

    for chain_name, chain_config in chain_configs.items():
        # Skip player_roster chain (handled by maintenance validator)
        if chain_name == 'player_roster':
            continue

        results[chain_name] = validate_chain(
            chain_config=chain_config,
            game_date=game_date,
            schedule_context=schedule_context,
            bq_client=bq_client,
            gcs_client=gcs_client,
        )

    return results


def validate_chain(
    chain_config: ChainConfig,
    game_date: date,
    schedule_context: ScheduleContext,
    bq_client: bigquery.Client,
    gcs_client: storage.Client,
) -> ChainValidation:
    """Validate a single fallback chain."""

    source_validations = []
    primary_available = False
    fallback_used = False
    first_available_source = None

    for source_config in chain_config.sources:
        source_val = validate_source(
            source_config=source_config,
            game_date=game_date,
            bq_client=bq_client,
            gcs_client=gcs_client,
        )
        source_validations.append(source_val)

        # Track which source will be used
        has_data = source_val.bq_record_count > 0 or source_config.is_virtual
        if has_data and first_available_source is None:
            first_available_source = source_config
            if source_config.is_primary:
                primary_available = True
                source_val.status = 'primary'
            else:
                fallback_used = True
                source_val.status = 'fallback'
        elif has_data:
            source_val.status = 'available'

    # Determine chain status
    if first_available_source is not None:
        chain_status = 'complete'
    elif any(sv.bq_record_count > 0 for sv in source_validations):
        chain_status = 'partial'
    else:
        chain_status = 'missing'

    # Build impact message if chain is missing/partial
    impact_message = None
    if chain_status == 'missing' and chain_config.on_all_fail_message:
        impact_message = chain_config.on_all_fail_message
        if chain_config.quality_impact:
            impact_message += f" ({chain_config.quality_impact:+d} quality)"
    elif fallback_used:
        fallback_source = first_available_source
        impact_message = f"Using fallback: {fallback_source.name} ({fallback_source.quality_tier} quality)"

    return ChainValidation(
        chain=chain_config,
        sources=source_validations,
        status=chain_status,
        primary_available=primary_available,
        fallback_used=fallback_used,
        impact_message=impact_message,
    )


def validate_source(
    source_config: SourceConfig,
    game_date: date,
    bq_client: bigquery.Client,
    gcs_client: storage.Client,
) -> SourceValidation:
    """Validate a single data source."""

    # Virtual sources don't have GCS or BQ counts
    if source_config.is_virtual:
        return SourceValidation(
            source=source_config,
            gcs_file_count=None,
            bq_record_count=0,
            status='virtual',
        )

    # Check GCS
    gcs_count = None
    if source_config.gcs_path_template:
        gcs_count = count_gcs_files(
            gcs_client=gcs_client,
            source_name=source_config.name,
            gcs_path_template=source_config.gcs_path_template,
            game_date=game_date,
        )

    # Check BQ
    bq_count = 0
    if source_config.table:
        bq_count = count_bq_records(
            bq_client=bq_client,
            dataset=source_config.dataset,
            table=source_config.table,
            game_date=game_date,
        )

    return SourceValidation(
        source=source_config,
        gcs_file_count=gcs_count,
        bq_record_count=bq_count,
        status='missing' if bq_count == 0 else 'available',
    )


def count_gcs_files(
    gcs_client: storage.Client,
    source_name: str,
    gcs_path_template: str,
    game_date: date,
) -> int:
    """Count JSON files in GCS for a source."""
    try:
        bucket = gcs_client.bucket(GCS_BUCKET)
        date_str = game_date.strftime('%Y-%m-%d')

        # Handle season-based paths differently
        if source_name in SEASON_BASED_GCS_SOURCES:
            # TODO: Handle season-based paths
            return 0

        prefix = f"{gcs_path_template}/{date_str}/"
        blobs = list(bucket.list_blobs(prefix=prefix, max_results=100))
        json_files = [b for b in blobs if b.name.endswith('.json')]
        return len(json_files)

    except Exception as e:
        logger.warning(f"Error counting GCS files for {source_name}: {e}")
        return 0


def count_bq_records(
    bq_client: bigquery.Client,
    dataset: str,
    table: str,
    game_date: date,
) -> int:
    """Count records in BQ table for a date."""
    try:
        # Determine date column based on table
        date_column = 'game_date'  # Default
        if table in ('player_shot_zone_analysis', 'team_defense_zone_analysis'):
            date_column = 'analysis_date'
        elif table == 'player_daily_cache':
            date_column = 'cache_date'

        query = f"""
            SELECT COUNT(*) as cnt
            FROM `nba-props-platform.{dataset}.{table}`
            WHERE {date_column} = @game_date
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
            ]
        )
        result = bq_client.query(query, job_config=job_config).result()
        row = next(iter(result))
        return row.cnt

    except Exception as e:
        logger.warning(f"Error counting BQ records for {dataset}.{table}: {e}")
        return 0
```

### Step 3: Terminal Output (terminal.py additions)

```python
def _format_chain_section(
    chain_validations: Dict[str, ChainValidation],
    use_color: bool = True,
) -> str:
    """Format all chains in a unified view."""
    lines = []
    lines.append("=" * 80)
    lines.append("PHASE 1-2: DATA SOURCES BY CHAIN")
    lines.append("=" * 80)
    lines.append("")

    # Sort chains by severity (critical first)
    severity_order = {'critical': 0, 'warning': 1, 'info': 2}
    sorted_chains = sorted(
        chain_validations.items(),
        key=lambda x: (severity_order.get(x[1].chain.severity, 3), x[0])
    )

    complete_count = sum(1 for _, cv in sorted_chains if cv.status == 'complete')
    partial_count = sum(1 for _, cv in sorted_chains if cv.status == 'partial')
    missing_count = sum(1 for _, cv in sorted_chains if cv.status == 'missing')

    for chain_name, chain_val in sorted_chains:
        lines.extend(_format_single_chain(chain_val, use_color))
        lines.append("")

    # Summary
    summary_parts = []
    if complete_count > 0:
        summary_parts.append(f"{complete_count} complete")
    if partial_count > 0:
        summary_parts.append(f"{partial_count} partial")
    if missing_count > 0:
        summary_parts.append(f"{missing_count} missing")

    total = len(sorted_chains)
    lines.append(f"-> Data Sources: {complete_count}/{total} chains complete" +
                 (f", {partial_count} partial" if partial_count else "") +
                 (f", {missing_count} missing" if missing_count else ""))

    return "\n".join(lines)


def _format_single_chain(chain_val: ChainValidation, use_color: bool) -> List[str]:
    """Format a single chain."""
    lines = []

    # Chain header
    status_symbol = {
        'complete': '✓',
        'partial': '△',
        'missing': '○',
    }.get(chain_val.status, '?')

    severity = chain_val.chain.severity
    header = f"Chain: {chain_val.chain.name} ({severity}) "
    header += "─" * (50 - len(header))
    header += f" Status: {status_symbol} {chain_val.status.title()}"
    lines.append(header)

    # Source table header
    lines.append("  Source                          GCS JSON    BQ Records   Quality   Status")
    lines.append("  " + "─" * 76)

    # Sources
    for sv in chain_val.sources:
        src = sv.source
        is_primary = src.is_primary
        prefix = "  ★ " if is_primary else "    "

        name = src.name[:30].ljust(30)

        # GCS column
        if sv.gcs_file_count is not None:
            gcs_str = str(sv.gcs_file_count).rjust(8)
        else:
            gcs_str = "-".rjust(8)

        # BQ column
        if src.is_virtual:
            bq_str = "-".rjust(12)
        else:
            bq_str = str(sv.bq_record_count).rjust(12)

        # Quality
        quality_str = src.quality_tier.ljust(8)

        # Status
        status_symbols = {
            'primary': '✓ Primary',
            'fallback': '✓ Fallback',
            'available': '✓ Available',
            'missing': '○ Missing',
            'virtual': '⊘ Virtual',
        }
        status_str = status_symbols.get(sv.status, sv.status)

        lines.append(f"{prefix}{name} {gcs_str} {bq_str}   {quality_str}  {status_str}")

    # Impact message
    if chain_val.impact_message:
        lines.append(f"  └─ {chain_val.impact_message}")

    return lines
```

### Step 4: CLI Update (bin/validate_pipeline.py)

Add `--chain-view` argument:
```python
parser.add_argument(
    '--chain-view',
    action='store_true',
    help='Show data sources organized by fallback chains (V2 format)',
)
```

In main validation logic:
```python
if args.chain_view:
    # Use chain validator for Phase 1-2
    chain_validations = validate_all_chains(
        game_date=game_date,
        schedule_context=schedule_context,
        bq_client=bq_client,
        gcs_client=gcs_client,
    )
    output_parts.append(format_chain_section(chain_validations))
else:
    # Use existing Phase 1 and Phase 2 validators (backwards compatible)
    output_parts.append(format_phase1(phase1_result))
    output_parts.append(format_phase2(phase2_result))
```

---

## Data Source to GCS Path Mapping

From `gcs_path_builder.py` - verified mapping:

| Source | GCS Path Template | Notes |
|--------|-------------------|-------|
| nbac_gamebook_player_stats | `nba-com/gamebooks-data/{date}/` | Per-game JSONs |
| nbac_team_boxscore | `nba-com/team-boxscore/{date}/{game_id}/` | Per-game JSONs |
| bdl_player_boxscores | `ball-dont-lie/player-boxscores/{date}/` | - |
| bettingpros_player_points_props | `bettingpros/player-props/{market_type}/{date}/` | Has market_type subdir |
| odds_api_player_points_props | `odds-api/player-props/{date}/{event_id}/` | Per-event |
| odds_api_game_lines | `odds-api/game-lines/{date}/{event_id}/` | Per-event |
| nbac_schedule | `nba-com/schedule/{season}/` | Season-based, not date |
| espn_scoreboard | `espn/scoreboard/{date}/` | - |
| bigdataball_play_by_play | `big-data-ball/{season}/{date}/game_{id}/` | Complex path |
| nbac_play_by_play | `nba-com/play-by-play/{date}/game-{id}/` | Per-game |
| nbac_injury_report | `nba-com/injury-report-data/{date}/{hour}/` | Has hour subdir |
| bdl_injuries | `ball-dont-lie/injuries/{date}/` | - |

---

## Implementation Tasks

### Session 1: Core Chain Infrastructure
1. Create `shared/validation/chain_config.py` with dataclasses and YAML loading
2. Create `shared/validation/validators/chain_validator.py` with validation logic
3. Add GCS and BQ counting helpers
4. Test with `python -c "from shared.validation.chain_config import get_chain_configs; print(get_chain_configs())"

### Session 2: Terminal Output & CLI
1. Add `_format_chain_section()` and `_format_single_chain()` to terminal.py
2. Add `--chain-view` flag to bin/validate_pipeline.py
3. Wire up chain validation to main script
4. Test: `python3 bin/validate_pipeline.py 2021-10-19 --chain-view`

### Session 3: Maintenance Section & Polish
1. Create `shared/validation/validators/maintenance_validator.py`
2. Add maintenance section formatting
3. Update progress bar to show chain status
4. Test with today's date: `python3 bin/validate_pipeline.py today --chain-view`

### Session 4: Migration
1. Test chain view across multiple dates (bootstrap, regular, today)
2. Compare output with existing flat view for consistency
3. Make `--chain-view` the default (rename to `--legacy-view` for old format)
4. Update documentation

---

## Benefits

1. **Better visibility**: See which chains are complete vs missing data
2. **Fallback awareness**: Know when fallback sources are being used
3. **Quality tracking**: See quality tier of each source
4. **Impact clarity**: Know what happens when sources are missing
5. **Daily ops**: Track roster/registry updates for orchestration monitoring
6. **Unified view**: GCS + BQ in one place per chain
7. **Single source of truth**: Chain configs come from `fallback_config.yaml`

---

## Migration Path

1. ✓ Keep existing Phase 1-5 structure for backwards compatibility
2. Add new `--chain-view` flag to use new format
3. Once validated, make chain view the default
4. Rename old format to `--legacy-view`
5. Eventually remove legacy view

---

## Related Files

| File | Purpose |
|------|---------|
| `shared/config/data_sources/fallback_config.yaml` | Source of truth for chains |
| `scrapers/utils/gcs_path_builder.py` | GCS path templates |
| `shared/validation/config.py` | Current validation config |
| `shared/validation/validators/phase1_validator.py` | Current GCS validation |
| `shared/validation/validators/phase2_validator.py` | Current BQ validation |
| `shared/validation/output/terminal.py` | Terminal formatting |

---

---

## Implementation Notes (2025-12-02)

### Changes Made During Implementation

1. **Chain view is now the default** - No `--chain-view` flag needed; use `--legacy-view` for old format
2. **GCS_PATH_MAPPING** - Added `espn_boxscores` path mapping
3. **PROJECT_ID** - Centralized via `config.py` import (no more hardcoded `nba-props-platform`)
4. **Test coverage** - 32 unit tests covering config loading, chain validation logic, and output formatting

### Current CLI Interface

```bash
# Default: Chain view (V2)
python3 bin/validate_pipeline.py 2021-10-19

# Legacy view (V1)
python3 bin/validate_pipeline.py 2021-10-19 --legacy-view

# JSON output
python3 bin/validate_pipeline.py 2021-10-19 --format json

# Verbose with run history
python3 bin/validate_pipeline.py today --verbose

# No color (for piping)
python3 bin/validate_pipeline.py 2021-10-19 --no-color
```

---

## Implementation Notes (2025-12-02 Session 2)

### Fixes and Improvements

#### 1. Bootstrap Days Display Fix
**Issue:** Display showed "Days 0-6" but `BOOTSTRAP_DAYS` was changed to 14.
**Fix:** Updated `schedule_context.py` to use `BOOTSTRAP_DAYS-1` dynamically:
```python
lines.append(f"Bootstrap:          Yes (Days 0-{BOOTSTRAP_DAYS-1} - Phase 4/5 skip)")
```

#### 2. Player Universe BDL Fallback
**Issue:** If `nbac_gamebook_player_stats` has no data for a date, player universe returns 0 players, causing false "complete" status (0/0 = 100%).

**Fix:** Added fallback to `bdl_player_boxscores` in `player_universe.py`:
- Primary: `nbac_gamebook_player_stats` (gold - has DNP/inactive tracking)
- Fallback: `bdl_player_boxscores` (silver - active players only)

**Display:**
```
PLAYER UNIVERSE
────────────────────────────────────────────────────────────────────────────────
Total Rostered:     68 players across 4 teams  ⚠️ BDL fallback
  Active (played):  52
  DNP:              — (unavailable)
  Inactive:         — (unavailable)
```

**Key fields added to PlayerUniverse:**
- `source: str` - "gamebook" or "bdl_fallback"
- `has_dnp_tracking: bool` - False when using BDL fallback

#### 3. Virtual Source Chain Dependencies
**Issue:** Virtual sources like `reconstructed_team_from_players` were always marked as "available" even when their input chain was missing. This caused false "complete" status for chains.

**Fix:** Added dependency checking in `chain_validator.py`:

1. **New config in `chain_config.py`:**
```python
VIRTUAL_SOURCE_DEPENDENCIES = {
    'reconstructed_team_from_players': 'player_boxscores',
    'espn_team_boxscore': 'player_boxscores',
}

CHAIN_VALIDATION_ORDER = [
    'game_schedule',
    'player_boxscores',  # Validated first
    'team_boxscores',    # Depends on player_boxscores
    ...
]
```

2. **New statuses for virtual sources:**
- `virtual` - Defined but not used
- `virtual_used` - Being used as fallback (input chain has data)
- `virtual_unavailable` - Cannot be used (input chain missing)

3. **Chains validated in dependency order** so input chains are available when checking virtual sources.

### Files Modified

| File | Changes |
|------|---------|
| `shared/validation/context/schedule_context.py` | Bootstrap days dynamic display |
| `shared/validation/context/player_universe.py` | BDL fallback, source tracking |
| `shared/validation/chain_config.py` | Virtual source dependencies, validation order |
| `shared/validation/validators/chain_validator.py` | Virtual source dependency checking |

### Testing

All 32 existing tests pass. New behavior verified:
- Bootstrap shows "Days 0-13"
- BDL fallback triggers when gamebook empty
- Virtual sources check input chain status

---

*Document version: 2.2*
*Last updated: 2025-12-02*
*Status: IMPLEMENTED*
