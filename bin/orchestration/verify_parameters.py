#!/usr/bin/env python3
"""
bin/orchestration/verify_parameters.py

Parameter Verification Script - Validates that orchestration system passes correct parameters to scrapers

Compares:
- Parameter resolver output
- Scraper requirements from docs

Usage:
    python bin/orchestration/verify_parameters.py

    # With specific scraper
    python bin/orchestration/verify_parameters.py --scraper nbac_schedule_api

    # Verbose mode
    python bin/orchestration/verify_parameters.py --verbose
"""

import sys
import os
import argparse
from datetime import datetime
from typing import Dict, Any, List
import yaml

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from orchestration.parameter_resolver import ParameterResolver


# Expected parameters for each scraper (from parameter formats documentation)
EXPECTED_PARAMETERS = {
    # NBA.com Scrapers
    'nbac_schedule_api': {
        'required': ['season'],
        'optional': [],
        'format_notes': 'season: 4-digit year (e.g., "2025")'
    },
    'nbac_scoreboard_v2': {
        'required': ['gamedate'],
        'optional': [],
        'format_notes': 'gamedate: YYYYMMDD or YYYY-MM-DD'
    },
    'nbac_play_by_play': {
        'required': ['game_id', 'gamedate'],
        'optional': [],
        'format_notes': 'game_id: 10-char NBA ID, gamedate: YYYYMMDD'
    },
    'nbac_player_boxscore': {
        'required': ['gamedate'],
        'optional': ['season', 'season_type'],
        'format_notes': 'gamedate: YYYYMMDD, season auto-detected'
    },
    'nbac_team_boxscore': {
        'required': ['game_id', 'game_date'],
        'optional': [],
        'format_notes': 'game_date: YYYY-MM-DD (with dashes)'
    },
    'nbac_injury_report': {
        'required': ['gamedate', 'hour', 'period'],
        'optional': [],
        'format_notes': 'hour: 1-12, period: AM/PM'
    },
    'nbac_referee_assignments': {
        'required': ['date'],
        'optional': [],
        'format_notes': 'date: YYYY-MM-DD'
    },
    'nbac_player_list': {
        'required': [],
        'optional': [],
        'format_notes': 'No parameters needed - auto-fetches current season'
    },
    'nbac_gamebook_pdf': {
        'required': ['game_code'],
        'optional': ['version', 'pdf_source'],
        'format_notes': 'game_code: YYYYMMDD/AWYHOM (e.g., "20240410/MEMCLE")'
    },

    # Odds API Scrapers
    'oddsa_events': {
        'required': ['sport', 'game_date'],
        'optional': ['commenceTimeFrom', 'commenceTimeTo'],
        'format_notes': 'sport: "basketball_nba", game_date: YYYY-MM-DD'
    },
    'oddsa_player_props': {
        'required': ['event_id', 'game_date'],
        'optional': ['markets', 'regions', 'bookmakers'],
        'format_notes': 'event_id from oddsa_events, game_date: YYYY-MM-DD'
    },
    'oddsa_game_lines': {
        'required': ['event_id', 'game_date'],
        'optional': ['markets', 'regions', 'bookmakers'],
        'format_notes': 'event_id from oddsa_events, game_date: YYYY-MM-DD'
    },

    # Ball Don't Lie Scrapers
    'bdl_games': {
        'required': [],
        'optional': ['startDate', 'endDate'],
        'format_notes': 'Defaults to yesterday → tomorrow if not provided'
    },
    'bdl_box_scores': {
        'required': ['date'],
        'optional': [],
        'format_notes': 'date: YYYY-MM-DD'
    },
    'bdl_active_players': {
        'required': [],
        'optional': [],
        'format_notes': 'No parameters needed'
    },
    'bdl_standings': {
        'required': [],
        'optional': [],
        'format_notes': 'No parameters needed'
    },
    'bdl_injuries': {
        'required': [],
        'optional': [],
        'format_notes': 'No parameters needed'
    },

    # Basketball Reference
    'br_season_roster': {
        'required': ['teamAbbr', 'year'],
        'optional': [],
        'format_notes': 'teamAbbr: 3-letter code, year: ending year (e.g., "2024")'
    },

    # BigDataBall
    'bigdataball_pbp': {
        'required': ['game_id'],
        'optional': [],
        'format_notes': 'game_id: NBA.com 10-char ID'
    },
}


def verify_scraper_parameters(
    resolver: ParameterResolver,
    scraper_name: str,
    context: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Verify parameters for a single scraper.

    Returns:
        Dict with verification results
    """
    if scraper_name not in EXPECTED_PARAMETERS:
        return {
            'scraper': scraper_name,
            'status': 'skipped',
            'reason': 'Not in expected parameters list'
        }

    expected = EXPECTED_PARAMETERS[scraper_name]

    try:
        # Resolve parameters
        resolved_params = resolver.resolve_parameters(scraper_name, context)

        # Handle multi-entity scrapers (returns list of parameter sets)
        if isinstance(resolved_params, list):
            if not resolved_params:
                return {
                    'scraper': scraper_name,
                    'status': 'WARNING',
                    'reason': 'Multi-entity scraper returned empty list (no entities to process)',
                    'resolved_params': [],
                    'expected_required': expected['required'],
                    'expected_optional': expected['optional'],
                    'format_notes': expected['format_notes']
                }

            # Check first parameter set as representative
            first_params = resolved_params[0]

            # Check required parameters
            missing_required = []
            for param in expected['required']:
                if param not in first_params:
                    missing_required.append(param)

            # Check for unexpected parameters
            all_expected = set(expected['required'] + expected['optional'])
            unexpected_params = [p for p in first_params.keys() if p not in all_expected]

            # Determine status
            if missing_required:
                status = 'FAIL'
                reason = f"Missing required: {missing_required}"
            elif unexpected_params:
                status = 'WARNING'
                reason = f"Unexpected params: {unexpected_params}"
            else:
                status = 'PASS'
                reason = f'Multi-entity: {len(resolved_params)} parameter sets - all required present'

            result = {
                'scraper': scraper_name,
                'status': status,
                'reason': reason,
                'resolved_params': f"List of {len(resolved_params)} parameter sets",
                'expected_required': expected['required'],
                'expected_optional': expected['optional'],
                'format_notes': expected['format_notes']
            }

            if verbose:
                print(f"\n{'='*70}")
                print(f"Scraper: {scraper_name}")
                print(f"Status: {status}")
                print(f"Reason: {reason}")
                print(f"\nMulti-Entity Scraper: {len(resolved_params)} parameter sets")
                print(f"First parameter set:")
                for k, v in first_params.items():
                    print(f"  {k}: {v}")
                print(f"\nExpected Required: {expected['required']}")
                print(f"Expected Optional: {expected['optional']}")
                print(f"Format Notes: {expected['format_notes']}")

            return result

        # Single parameter set (dict)
        # Check required parameters
        missing_required = []
        for param in expected['required']:
            if param not in resolved_params:
                missing_required.append(param)

        # Check for unexpected parameters
        all_expected = set(expected['required'] + expected['optional'])
        unexpected_params = [p for p in resolved_params.keys() if p not in all_expected]

        # Determine status
        if missing_required:
            status = 'FAIL'
            reason = f"Missing required: {missing_required}"
        elif unexpected_params:
            status = 'WARNING'
            reason = f"Unexpected params: {unexpected_params}"
        else:
            status = 'PASS'
            reason = 'All required parameters present'

        result = {
            'scraper': scraper_name,
            'status': status,
            'reason': reason,
            'resolved_params': resolved_params,
            'expected_required': expected['required'],
            'expected_optional': expected['optional'],
            'format_notes': expected['format_notes']
        }

        if verbose:
            print(f"\n{'='*70}")
            print(f"Scraper: {scraper_name}")
            print(f"Status: {status}")
            print(f"Reason: {reason}")
            print(f"\nResolved Parameters:")
            for k, v in resolved_params.items():
                print(f"  {k}: {v}")
            print(f"\nExpected Required: {expected['required']}")
            print(f"Expected Optional: {expected['optional']}")
            print(f"Format Notes: {expected['format_notes']}")

        return result

    except Exception as e:
        return {
            'scraper': scraper_name,
            'status': 'ERROR',
            'reason': str(e),
            'resolved_params': {},
            'expected_required': expected['required'],
            'expected_optional': expected['optional']
        }


def main():
    parser = argparse.ArgumentParser(description='Verify orchestration parameter resolution')
    parser.add_argument('--scraper', help='Verify specific scraper only')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🔍 Parameter Verification Script")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    # Initialize resolver
    resolver = ParameterResolver()

    # Build test context
    context = resolver.build_workflow_context(
        workflow_name='test_verification',
        target_games=None
    )

    print(f"Test Context:")
    print(f"  Date: {context['execution_date']}")
    print(f"  Season: {context['season']}")
    print(f"  Games Today: {context['games_count']}")
    print()

    # Determine which scrapers to test
    if args.scraper:
        scrapers_to_test = [args.scraper]
    else:
        # Get all scrapers from config
        simple_scrapers = resolver.config.get('simple_scrapers', {}).keys()
        complex_scrapers = resolver.config.get('complex_scrapers', [])
        scrapers_to_test = list(simple_scrapers) + complex_scrapers

    # Verify each scraper
    results = []
    for scraper_name in scrapers_to_test:
        result = verify_scraper_parameters(resolver, scraper_name, context, verbose=args.verbose)
        results.append(result)

    # Summary
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📊 Verification Summary")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    passed = [r for r in results if r['status'] == 'PASS']
    warnings = [r for r in results if r['status'] == 'WARNING']
    failed = [r for r in results if r['status'] == 'FAIL']
    errors = [r for r in results if r['status'] == 'ERROR']
    skipped = [r for r in results if r['status'] == 'skipped']

    print(f"Total Scrapers: {len(results)}")
    print(f"✅ PASS: {len(passed)}")
    print(f"⚠️  WARNING: {len(warnings)}")
    print(f"❌ FAIL: {len(failed)}")
    print(f"🔥 ERROR: {len(errors)}")
    print(f"⏭️  SKIPPED: {len(skipped)}")

    # Show failures
    if failed:
        print("\n❌ FAILED:")
        for r in failed:
            print(f"  - {r['scraper']}: {r['reason']}")

    # Show warnings
    if warnings:
        print("\n⚠️  WARNINGS:")
        for r in warnings:
            print(f"  - {r['scraper']}: {r['reason']}")

    # Show errors
    if errors:
        print("\n🔥 ERRORS:")
        for r in errors:
            print(f"  - {r['scraper']}: {r['reason']}")

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    # Exit code
    if failed or errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
