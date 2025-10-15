#!/usr/bin/env python3
"""
File: monitoring/scrapers/freshness/sync-gcs-paths.py

Utility to sync GCS paths between monitoring config and GCS path builder.
Ensures consistency between scraper paths and monitoring configuration.
"""

import sys
from pathlib import Path
import yaml
import re

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scrapers.utils.gcs_path_builder import GCSPathBuilder


def parse_path_template(template):
    """Parse GCS path builder template to monitoring config pattern."""
    # Convert %(variable)s to {variable} format
    # Example: "odds-api/events/%(date)s/%(timestamp)s.json"
    # Becomes: "odds-api/events/{date}/*.json"
    
    pattern = template
    
    # Replace %(date)s with {date}
    pattern = pattern.replace('%(date)s', '{date}')
    
    # Replace timestamp patterns with wildcard
    pattern = re.sub(r'%\(timestamp\)s', '*', pattern)
    pattern = re.sub(r'%\(hour\d*\)s', '*', pattern)
    pattern = re.sub(r'%\(snap\)s', '*', pattern)
    
    # Replace other variables with wildcards for matching
    pattern = re.sub(r'%\([^)]+\)s', '*', pattern)
    
    return pattern


def map_scraper_to_template():
    """Map monitoring config scraper names to GCS path builder template keys."""
    # Manual mapping where names don't match exactly
    mappings = {
        'bdl_active_players': 'bdl_active_players',
        'bdl_box_scores': 'bdl_box_scores',
        'bdl_standings': 'bdl_standings',
        'bdl_injuries': 'bdl_injuries',
        'odds_api_events': 'odds_api_events',
        'odds_api_player_props': 'odds_api_player_props',
        'odds_api_game_lines': 'odds_api_game_lines',
        'nbacom_player_list': 'nba_com_player_list',
        'nbacom_player_movement': 'nba_com_player_movement',
        'nbacom_scoreboard_v2': 'nba_com_scoreboard_v2',
        'nbacom_play_by_play': 'nba_com_play_by_play',
        'espn_scoreboard': 'espn_scoreboard',
        'espn_team_roster': 'espn_team_roster',
        'bigdataball_pbp': 'bigdataball_pbp',
        'bettingpros_player_props': 'bettingpros_player_props',
    }
    
    return mappings


def sync_paths(config_path, dry_run=True):
    """
    Sync GCS paths from path builder to monitoring config.
    
    Args:
        config_path: Path to monitoring_config.yaml
        dry_run: If True, only show changes without applying
    """
    print("=" * 80)
    print("GCS Path Sync Utility")
    print("=" * 80)
    print()
    
    # Load monitoring config
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    scrapers = config.get('scrapers', {})
    print(f"Loaded {len(scrapers)} scrapers from config")
    print()
    
    # Get mappings
    mappings = map_scraper_to_template()
    
    # Check each scraper
    changes = []
    matched = []
    not_found = []
    
    for scraper_name, scraper_config in scrapers.items():
        current_path = scraper_config.get('gcs', {}).get('path_pattern', '')
        
        # Get template key
        template_key = mappings.get(scraper_name)
        
        if not template_key:
            not_found.append(scraper_name)
            continue
        
        # Get path from builder
        if template_key in GCSPathBuilder.PATH_TEMPLATES:
            builder_template = GCSPathBuilder.PATH_TEMPLATES[template_key]
            suggested_path = parse_path_template(builder_template)
            
            if current_path != suggested_path:
                changes.append({
                    'scraper': scraper_name,
                    'current': current_path,
                    'suggested': suggested_path,
                    'builder_template': builder_template
                })
            else:
                matched.append(scraper_name)
        else:
            not_found.append(scraper_name)
    
    # Report results
    print(f"✓ Matched: {len(matched)}")
    print(f"⚠ Changes suggested: {len(changes)}")
    print(f"✗ Not found in path builder: {len(not_found)}")
    print()
    
    if changes:
        print("=" * 80)
        print("Suggested Changes")
        print("=" * 80)
        print()
        
        for change in changes:
            print(f"Scraper: {change['scraper']}")
            print(f"  Current:   {change['current']}")
            print(f"  Suggested: {change['suggested']}")
            print(f"  Builder:   {change['builder_template']}")
            print()
        
        if not dry_run:
            print("Applying changes...")
            for change in changes:
                config['scrapers'][change['scraper']]['gcs']['path_pattern'] = change['suggested']
            
            # Write back
            with open(config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
            print(f"✓ Updated {len(changes)} scrapers in {config_path}")
        else:
            print("DRY RUN: No changes applied")
            print("Run with --apply to apply changes")
    
    if not_found:
        print("=" * 80)
        print("Not Found in Path Builder")
        print("=" * 80)
        print()
        for scraper in not_found:
            print(f"  - {scraper}")
        print()
        print("These scrapers need manual path configuration or")
        print("need to be added to scrapers/utils/gcs_path_builder.py")
    
    if matched:
        print()
        print(f"✓ {len(matched)} scrapers already match path builder")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Sync GCS paths between monitoring config and path builder'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='config/monitoring_config.yaml',
        help='Path to monitoring config (relative to this script)'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply changes (default is dry-run)'
    )
    
    args = parser.parse_args()
    
    # Get config path
    script_dir = Path(__file__).parent
    config_path = script_dir / args.config
    
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    
    # Run sync
    sync_paths(config_path, dry_run=not args.apply)


if __name__ == "__main__":
    main()
