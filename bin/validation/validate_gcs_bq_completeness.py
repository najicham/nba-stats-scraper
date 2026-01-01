#!/usr/bin/env python3
"""
GCS → BigQuery Completeness Validator

Validates that Phase 2 processors have correctly processed all Phase 1 GCS JSON files
into BigQuery tables.

Purpose:
- Detect orphaned GCS files (scraped but not processed)
- Detect processing gaps (dates with GCS data but no BQ records)
- Validate record count ratios are within expected ranges
- Provide visibility into Phase 1→2 data flow integrity

Usage:
    # Validate a single date
    python bin/validation/validate_gcs_bq_completeness.py 2021-10-25

    # Validate a date range
    python bin/validation/validate_gcs_bq_completeness.py 2021-10-19 2021-11-15

    # Validate specific sources only
    python bin/validation/validate_gcs_bq_completeness.py 2021-10-25 --sources gamebook,team_boxscore

    # Output as JSON
    python bin/validation/validate_gcs_bq_completeness.py 2021-10-25 --format json

    # Quick mode (skip slow ratio validation)
    python bin/validation/validate_gcs_bq_completeness.py 2021-10-25 --quick

Author: Claude Code
Created: 2025-12-02
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

from google.cloud import storage, bigquery

# Add project root to path
sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

from shared.validation.chain_config import GCS_PATH_MAPPING, GCS_BUCKET, SEASON_BASED_GCS_SOURCES

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class ValidationStatus(Enum):
    """Status of GCS → BQ validation."""
    OK = "ok"                    # Records within expected range
    GCS_ONLY = "gcs_only"        # GCS has data, BQ is empty (Phase 2 never ran)
    BQ_ONLY = "bq_only"          # BQ has data, GCS is empty (GCS cleaned up)
    LOW = "low"                  # BQ records below expected range
    HIGH = "high"                # BQ records above expected range (duplicates?)
    NO_DATA = "no_data"          # Neither GCS nor BQ has data
    NOT_APPLICABLE = "n/a"       # Source not applicable for this date


@dataclass
class SourceExpectation:
    """Expected record ratios for a source."""
    name: str
    bq_table: str
    bq_dataset: str
    gcs_path_template: str
    date_column: str
    # Records per game/folder (min, max)
    records_per_game: Tuple[int, int]
    # Records per file (min, max) - used if we can't count games
    records_per_file: Tuple[int, int]
    # Whether GCS uses game folders or flat files
    has_game_folders: bool
    # Whether this is date-based or season-based
    is_date_based: bool = True
    # Whether 1 file covers all games for the day (vs per-game files)
    is_file_per_day: bool = False


# Expected ratios based on data analysis
SOURCE_EXPECTATIONS = {
    'nbac_gamebook_player_stats': SourceExpectation(
        name='nbac_gamebook_player_stats',
        bq_table='nbac_gamebook_player_stats',
        bq_dataset='nba_raw',
        gcs_path_template='nba-com/gamebooks-data/{date}',
        date_column='game_date',
        records_per_game=(25, 38),   # ~25-38 players per game (incl DNPs)
        records_per_file=(8, 15),    # ~8-15 players per JSON file (3 files per game)
        has_game_folders=True,
    ),
    'nbac_team_boxscore': SourceExpectation(
        name='nbac_team_boxscore',
        bq_table='nbac_team_boxscore',
        bq_dataset='nba_raw',
        gcs_path_template='nba-com/team-boxscore/{date}',
        date_column='game_date',
        records_per_game=(2, 2),     # Always 2 teams per game
        records_per_file=(2, 2),
        has_game_folders=False,
    ),
    'bettingpros_player_points_props': SourceExpectation(
        name='bettingpros_player_points_props',
        bq_table='bettingpros_player_points_props',
        bq_dataset='nba_raw',
        gcs_path_template='bettingpros/player-props/{date}',
        date_column='game_date',
        records_per_game=(8, 20),    # ~8-20 players with props per game
        records_per_file=(50, 200),  # ~50-200 total props per file
        has_game_folders=False,
    ),
    'bigdataball_play_by_play': SourceExpectation(
        name='bigdataball_play_by_play',
        bq_table='bigdataball_play_by_play',
        bq_dataset='nba_raw',
        gcs_path_template='big-data-ball/play-by-play/{season}',
        date_column='game_date',
        records_per_game=(350, 550),  # ~350-550 plays per game
        records_per_file=(350, 550),
        has_game_folders=False,
        is_date_based=False,  # Uses season folders
    ),
    'nbac_injury_report': SourceExpectation(
        name='nbac_injury_report',
        bq_table='nbac_injury_report',
        bq_dataset='nba_raw',
        gcs_path_template='nba-com/injury-report-data/{date}',
        date_column='report_date',
        records_per_game=(30, 100),   # ~30-100 injury records per hourly snapshot (24 hours/day)
        records_per_file=(30, 100),   # Same as per_game since 1 file per hour folder
        has_game_folders=True,        # Uses hourly subfolders (00-23)
    ),
    'odds_api_game_lines': SourceExpectation(
        name='odds_api_game_lines',
        bq_table='odds_api_game_lines',
        bq_dataset='nba_raw',
        gcs_path_template='odds-api/game-lines/{date}',
        date_column='game_date',
        records_per_game=(6, 20),     # 6-20 bookmaker lines per game
        records_per_file=(30, 150),
        has_game_folders=False,
    ),
    'espn_scoreboard': SourceExpectation(
        name='espn_scoreboard',
        bq_table='espn_scoreboard',
        bq_dataset='nba_raw',
        gcs_path_template='espn/scoreboard/{date}',
        date_column='game_date',
        records_per_game=(1, 1),      # 1 scoreboard entry per game
        records_per_file=(1, 15),     # 1 file contains ALL games (1-15 games per day)
        has_game_folders=False,
        is_file_per_day=True,         # New: indicates 1 file covers all games for day
    ),
    'bdl_player_boxscores': SourceExpectation(
        name='bdl_player_boxscores',
        bq_table='bdl_player_boxscores',
        bq_dataset='nba_raw',
        gcs_path_template='ball-dont-lie/boxscores/{date}',
        date_column='game_date',
        records_per_game=(20, 35),    # ~20-35 players per game
        records_per_file=(150, 500),  # All players for all games in one file
        has_game_folders=False,
        is_file_per_day=True,         # New: indicates file(s) cover all games for day
    ),
}


@dataclass
class SourceValidationResult:
    """Result of validating a single source for a date."""
    source_name: str
    game_date: date
    gcs_file_count: int
    gcs_folder_count: int
    bq_record_count: int
    expected_min: int
    expected_max: int
    status: ValidationStatus
    games_detected: int = 0
    records_per_game: float = 0.0
    issues: List[str] = field(default_factory=list)


@dataclass
class DateValidationResult:
    """Result of validating all sources for a date."""
    game_date: date
    sources: Dict[str, SourceValidationResult] = field(default_factory=dict)
    overall_status: str = "unknown"
    issues: List[str] = field(default_factory=list)


@dataclass
class ValidationSummary:
    """Summary of validation across all dates."""
    start_date: date
    end_date: date
    total_dates: int
    dates_ok: int
    dates_with_issues: int
    status_counts: Dict[str, int] = field(default_factory=dict)
    issues_by_source: Dict[str, List[str]] = field(default_factory=dict)


# =============================================================================
# GCS UTILITIES
# =============================================================================

class GCSInventory:
    """Utility for counting GCS files and folders."""

    def __init__(self, bucket_name: str = GCS_BUCKET):
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self._cache: Dict[str, Any] = {}

    def count_files(self, prefix: str, extension: str = '.json') -> int:
        """Count files with given extension under prefix."""
        cache_key = f"files:{prefix}:{extension}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            count = len([b for b in blobs if b.name.endswith(extension)])
            self._cache[cache_key] = count
            return count
        except Exception as e:
            logger.warning(f"Error counting GCS files at {prefix}: {e}")
            return 0

    def count_folders(self, prefix: str) -> int:
        """Count subfolders (game folders) under prefix."""
        cache_key = f"folders:{prefix}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # Ensure prefix ends with /
            if not prefix.endswith('/'):
                prefix = prefix + '/'

            iterator = self.bucket.list_blobs(prefix=prefix, delimiter='/')
            # Must consume iterator to get prefixes
            list(iterator)
            folders = list(iterator.prefixes)
            count = len(folders)
            self._cache[cache_key] = count
            return count
        except Exception as e:
            logger.warning(f"Error counting GCS folders at {prefix}: {e}")
            return 0

    def list_folders(self, prefix: str) -> List[str]:
        """List subfolder names under prefix."""
        try:
            if not prefix.endswith('/'):
                prefix = prefix + '/'

            iterator = self.bucket.list_blobs(prefix=prefix, delimiter='/')
            list(iterator)
            return list(iterator.prefixes)
        except Exception as e:
            logger.warning(f"Error listing GCS folders at {prefix}: {e}")
            return []


# =============================================================================
# BIGQUERY UTILITIES
# =============================================================================

class BQCounter:
    """Utility for counting BigQuery records."""

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.client = bigquery.Client(project=project_id)
        self._cache: Dict[str, int] = {}

    def count_records(
        self,
        table: str,
        dataset: str,
        date_column: str,
        game_date: date
    ) -> int:
        """Count records for a specific date."""
        cache_key = f"{dataset}.{table}:{game_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{dataset}.{table}`
        WHERE {date_column} = '{game_date}'
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            count = result[0].cnt if result else 0
            self._cache[cache_key] = count
            return count
        except Exception as e:
            logger.warning(f"Error counting BQ records in {dataset}.{table}: {e}")
            return -1


# =============================================================================
# VALIDATION LOGIC
# =============================================================================

def validate_source_for_date(
    source_name: str,
    game_date: date,
    gcs: GCSInventory,
    bq: BQCounter,
    expectation: SourceExpectation,
) -> SourceValidationResult:
    """Validate a single source for a single date."""

    # Build GCS path
    if expectation.is_date_based:
        gcs_prefix = expectation.gcs_path_template.format(date=game_date.strftime('%Y-%m-%d'))
    else:
        # Season-based (like bigdataball)
        # Skip for now - complex path logic
        return SourceValidationResult(
            source_name=source_name,
            game_date=game_date,
            gcs_file_count=0,
            gcs_folder_count=0,
            bq_record_count=0,
            expected_min=0,
            expected_max=0,
            status=ValidationStatus.NOT_APPLICABLE,
            issues=["Season-based source - use separate validation"],
        )

    # Count GCS files and folders
    gcs_files = gcs.count_files(gcs_prefix)
    gcs_folders = gcs.count_folders(gcs_prefix) if expectation.has_game_folders else 0

    # Count BQ records
    bq_records = bq.count_records(
        table=expectation.bq_table,
        dataset=expectation.bq_dataset,
        date_column=expectation.date_column,
        game_date=game_date,
    )

    # Calculate expected range
    if expectation.is_file_per_day and gcs_files > 0:
        # For file-per-day sources (espn_scoreboard, bdl_player_boxscores),
        # use records_per_file directly since 1 file = all games for day
        min_ratio, max_ratio = expectation.records_per_file
        games = 0  # Not per-game calculation
        expected_min = min_ratio
        expected_max = max_ratio * gcs_files  # Multiple scrapes = multiple files
    elif expectation.has_game_folders and gcs_folders > 0:
        games = gcs_folders
        min_ratio, max_ratio = expectation.records_per_game
        expected_min = games * min_ratio
        expected_max = games * max_ratio
    elif gcs_files > 0:
        # Estimate games from files (assuming ~3 files per game for gamebook)
        if source_name == 'nbac_gamebook_player_stats':
            games = max(1, gcs_files // 3)
        else:
            games = gcs_files
        min_ratio, max_ratio = expectation.records_per_game
        expected_min = games * min_ratio
        expected_max = games * max_ratio
    else:
        games = 0
        expected_min = 0
        expected_max = 0

    # Determine status
    issues = []

    if gcs_files == 0 and bq_records == 0:
        status = ValidationStatus.NO_DATA
    elif gcs_files == 0 and bq_records > 0:
        status = ValidationStatus.BQ_ONLY
        # Not an issue - expected for old data where GCS was cleaned up
    elif gcs_files > 0 and bq_records == 0:
        status = ValidationStatus.GCS_ONLY
        issues.append(f"GCS has {gcs_files} files but BQ is empty - Phase 2 may not have run")
    elif bq_records < 0:
        status = ValidationStatus.NOT_APPLICABLE
        issues.append("BQ query error")
    elif expected_max == 0:
        # Can't validate ratio, but both have data
        status = ValidationStatus.OK
    elif expected_min <= bq_records <= expected_max:
        status = ValidationStatus.OK
    elif bq_records < expected_min:
        status = ValidationStatus.LOW
        issues.append(
            f"BQ records ({bq_records}) below expected range ({expected_min}-{expected_max})"
        )
    else:
        status = ValidationStatus.HIGH
        issues.append(
            f"BQ records ({bq_records}) above expected range ({expected_min}-{expected_max}) - possible duplicates"
        )

    # Calculate records per game for reporting
    records_per_game = bq_records / games if games > 0 else 0

    return SourceValidationResult(
        source_name=source_name,
        game_date=game_date,
        gcs_file_count=gcs_files,
        gcs_folder_count=gcs_folders,
        bq_record_count=bq_records,
        expected_min=expected_min,
        expected_max=expected_max,
        status=status,
        games_detected=games,
        records_per_game=records_per_game,
        issues=issues,
    )


def validate_date(
    game_date: date,
    sources: List[str],
    gcs: GCSInventory,
    bq: BQCounter,
) -> DateValidationResult:
    """Validate all sources for a date."""

    result = DateValidationResult(game_date=game_date)

    for source_name in sources:
        if source_name not in SOURCE_EXPECTATIONS:
            logger.warning(f"Unknown source: {source_name}")
            continue

        expectation = SOURCE_EXPECTATIONS[source_name]
        source_result = validate_source_for_date(
            source_name=source_name,
            game_date=game_date,
            gcs=gcs,
            bq=bq,
            expectation=expectation,
        )
        result.sources[source_name] = source_result
        result.issues.extend(source_result.issues)

    # Determine overall status
    # BQ_ONLY and NO_DATA are acceptable (old data or no games)
    statuses = [s.status for s in result.sources.values()]
    acceptable = (ValidationStatus.OK, ValidationStatus.BQ_ONLY, ValidationStatus.NOT_APPLICABLE, ValidationStatus.NO_DATA)

    if all(s in acceptable for s in statuses):
        result.overall_status = "ok"
    elif any(s == ValidationStatus.GCS_ONLY for s in statuses):
        result.overall_status = "critical"  # Phase 2 didn't run - this is the main issue we care about
    elif any(s in (ValidationStatus.LOW, ValidationStatus.HIGH) for s in statuses):
        result.overall_status = "warning"  # Ratio issues
    else:
        result.overall_status = "ok"

    return result


def validate_date_range(
    start_date: date,
    end_date: date,
    sources: List[str],
    quick_mode: bool = False,
) -> Tuple[List[DateValidationResult], ValidationSummary]:
    """Validate all sources for a date range."""

    gcs = GCSInventory()
    bq = BQCounter()

    results = []
    status_counts = defaultdict(int)
    issues_by_source = defaultdict(list)

    current = start_date
    total_dates = 0

    while current <= end_date:
        total_dates += 1

        if not quick_mode:
            result = validate_date(current, sources, gcs, bq)
            results.append(result)

            # Track status counts
            for source_name, source_result in result.sources.items():
                status_counts[source_result.status.value] += 1
                if source_result.issues:
                    issues_by_source[source_name].extend(
                        [f"{current}: {issue}" for issue in source_result.issues]
                    )

        current += timedelta(days=1)

    dates_ok = sum(1 for r in results if r.overall_status == "ok")
    dates_with_issues = sum(1 for r in results if r.overall_status != "ok")

    summary = ValidationSummary(
        start_date=start_date,
        end_date=end_date,
        total_dates=total_dates,
        dates_ok=dates_ok,
        dates_with_issues=dates_with_issues,
        status_counts=dict(status_counts),
        issues_by_source=dict(issues_by_source),
    )

    return results, summary


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

STATUS_SYMBOLS = {
    ValidationStatus.OK: ('✅', '\033[92m'),
    ValidationStatus.BQ_ONLY: ('⚠️', '\033[93m'),
    ValidationStatus.GCS_ONLY: ('❌', '\033[91m'),
    ValidationStatus.LOW: ('🔻', '\033[93m'),
    ValidationStatus.HIGH: ('🔺', '\033[93m'),
    ValidationStatus.NO_DATA: ('⬜', '\033[90m'),
    ValidationStatus.NOT_APPLICABLE: ('➖', '\033[90m'),
}
RESET = '\033[0m'


def format_terminal_output(
    results: List[DateValidationResult],
    summary: ValidationSummary,
    verbose: bool = False,
) -> str:
    """Format results for terminal output."""

    lines = []

    # Header
    lines.append('=' * 80)
    lines.append('GCS → BigQuery Completeness Validation')
    lines.append(f"Date Range: {summary.start_date} to {summary.end_date}")
    lines.append('=' * 80)
    lines.append('')

    # Legend
    lines.append('Status Legend:')
    lines.append('  ✅ OK       - Records within expected range')
    lines.append('  ⚠️ BQ_ONLY  - BQ has data, GCS cleaned up (expected for old data)')
    lines.append('  ❌ GCS_ONLY - GCS has data but BQ empty (Phase 2 may not have run)')
    lines.append('  🔻 LOW      - Fewer BQ records than expected')
    lines.append('  🔺 HIGH     - More BQ records than expected (possible duplicates)')
    lines.append('  ⬜ NO_DATA  - Neither GCS nor BQ has data')
    lines.append('')

    # Per-date results
    if results and verbose:
        lines.append('-' * 80)
        lines.append('DETAILED RESULTS')
        lines.append('-' * 80)

        for result in results:
            lines.append(f"\n{result.game_date}:")
            for source_name, source_result in result.sources.items():
                symbol, color = STATUS_SYMBOLS.get(
                    source_result.status,
                    ('?', '')
                )
                lines.append(
                    f"  {symbol} {source_name:35} | "
                    f"GCS: {source_result.gcs_folder_count:2} folders, {source_result.gcs_file_count:3} files | "
                    f"BQ: {source_result.bq_record_count:5} records | "
                    f"Expected: {source_result.expected_min}-{source_result.expected_max}"
                )

    # Summary table by source
    lines.append('')
    lines.append('-' * 80)
    lines.append('SUMMARY BY SOURCE')
    lines.append('-' * 80)

    source_stats = defaultdict(lambda: defaultdict(int))
    for result in results:
        for source_name, source_result in result.sources.items():
            source_stats[source_name][source_result.status.value] += 1

    for source_name in sorted(source_stats.keys()):
        stats = source_stats[source_name]
        total = sum(stats.values())
        # BQ_ONLY is acceptable for old data, NO_DATA means no games
        ok = stats.get('ok', 0) + stats.get('bq_only', 0) + stats.get('no_data', 0) + stats.get('n/a', 0)
        issues = total - ok

        if issues > 0:
            symbol = '⚠️'
        else:
            symbol = '✅'

        lines.append(f"  {symbol} {source_name:35} | OK: {ok:3} | Issues: {issues:3} | Total: {total}")

    # Overall summary
    lines.append('')
    lines.append('=' * 80)
    lines.append('OVERALL SUMMARY')
    lines.append('=' * 80)
    lines.append(f"  Total dates validated: {summary.total_dates}")
    lines.append(f"  Dates OK: {summary.dates_ok}")
    lines.append(f"  Dates with issues: {summary.dates_with_issues}")
    lines.append('')

    # Issues
    if summary.issues_by_source:
        lines.append('ISSUES FOUND:')
        for source_name, issues in summary.issues_by_source.items():
            if issues:
                lines.append(f"\n  {source_name}:")
                for issue in issues[:5]:  # Limit to first 5
                    lines.append(f"    - {issue}")
                if len(issues) > 5:
                    lines.append(f"    ... and {len(issues) - 5} more")

    return '\n'.join(lines)


def format_json_output(
    results: List[DateValidationResult],
    summary: ValidationSummary,
) -> str:
    """Format results as JSON."""

    def serialize(obj):
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, ValidationStatus):
            return obj.value
        if hasattr(obj, '__dict__'):
            return {k: serialize(v) for k, v in obj.__dict__.items()}
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize(v) for v in obj]
        return obj

    output = {
        'summary': serialize(summary),
        'results': [serialize(r) for r in results],
    }

    return json.dumps(output, indent=2)


# =============================================================================
# MAIN
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='Validate GCS → BigQuery completeness for Phase 1 → Phase 2 data flow',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate a single date
  python bin/validation/validate_gcs_bq_completeness.py 2021-10-25

  # Validate a date range
  python bin/validation/validate_gcs_bq_completeness.py 2021-10-19 2021-11-15

  # Validate specific sources
  python bin/validation/validate_gcs_bq_completeness.py 2021-10-25 \\
      --sources nbac_gamebook_player_stats,nbac_team_boxscore

  # JSON output
  python bin/validation/validate_gcs_bq_completeness.py 2021-10-25 --format json
        """
    )

    parser.add_argument(
        'start_date',
        type=str,
        help='Start date (YYYY-MM-DD) or single date to validate'
    )
    parser.add_argument(
        'end_date',
        type=str,
        nargs='?',
        default=None,
        help='End date (YYYY-MM-DD) for range validation'
    )
    parser.add_argument(
        '--sources',
        type=str,
        default=None,
        help='Comma-separated list of sources to validate (default: all)'
    )
    parser.add_argument(
        '--format',
        type=str,
        choices=['terminal', 'json'],
        default='terminal',
        help='Output format'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed per-date results'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Quick mode - skip detailed validation (just show summary)'
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else start_date
    except ValueError as e:
        print(f"Error: Invalid date format. Use YYYY-MM-DD. ({e})")
        sys.exit(1)

    # Parse sources
    if args.sources:
        sources = [s.strip() for s in args.sources.split(',')]
        invalid = [s for s in sources if s not in SOURCE_EXPECTATIONS]
        if invalid:
            print(f"Error: Unknown sources: {', '.join(invalid)}")
            print(f"Valid sources: {', '.join(SOURCE_EXPECTATIONS.keys())}")
            sys.exit(1)
    else:
        # Default: validate main sources (skip season-based ones)
        sources = [
            name for name, exp in SOURCE_EXPECTATIONS.items()
            if exp.is_date_based
        ]

    # Run validation
    logger.info(f"Validating {start_date} to {end_date} for {len(sources)} sources...")

    results, summary = validate_date_range(
        start_date=start_date,
        end_date=end_date,
        sources=sources,
        quick_mode=args.quick,
    )

    # Output results
    if args.format == 'json':
        print(format_json_output(results, summary))
    else:
        print(format_terminal_output(results, summary, verbose=args.verbose))

    # Exit with error code if issues found
    if summary.dates_with_issues > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
