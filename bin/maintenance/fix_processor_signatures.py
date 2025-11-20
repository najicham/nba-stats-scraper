#!/usr/bin/env python3
"""
Fix processor method signatures to match ProcessorBase pattern.

This script fixes the common signature mismatch issues found in raw processors:
1. transform_data(self, raw_data, file_path) -> transform_data(self)
2. load_data(self, rows, **kwargs) -> save_data(self)  [rename to save_data]

IMPORTANT: This is a one-time migration script.
"""

import re
import sys
from pathlib import Path

# Processors to fix
PROCESSORS_TO_FIX = [
    "data_processors/raw/balldontlie/bdl_boxscores_processor.py",
    "data_processors/raw/balldontlie/bdl_injuries_processor.py",
    "data_processors/raw/balldontlie/bdl_standings_processor.py",
    "data_processors/raw/nbacom/nbac_gamebook_processor.py",
    "data_processors/raw/nbacom/nbac_injury_report_processor.py",
    "data_processors/raw/nbacom/nbac_play_by_play_processor.py",
    "data_processors/raw/nbacom/nbac_player_movement_processor.py",
    "data_processors/raw/nbacom/nbac_referee_processor.py",
    "data_processors/raw/nbacom/nbac_schedule_processor.py",
    "data_processors/raw/nbacom/nbac_scoreboard_v2_processor.py",
    "data_processors/raw/nbacom/nbac_team_boxscore_processor.py",
    "data_processors/raw/bettingpros/bettingpros_player_props_processor.py",
    "data_processors/raw/bigdataball/bigdataball_pbp_processor.py",
    "data_processors/raw/espn/espn_boxscore_processor.py",
    "data_processors/raw/espn/espn_scoreboard_processor.py",
    "data_processors/raw/oddsapi/odds_api_props_processor.py",
    "data_processors/raw/oddsapi/odds_game_lines_processor.py",
]

def fix_transform_data_signature(content: str) -> str:
    """Fix transform_data method signature and body."""

    # Fix method signature
    old_sig = r'def transform_data\(self, raw_data: Dict, file_path: str\) -> List\[Dict\]:'
    new_sig = 'def transform_data(self) -> None:\n        """Transform raw data into transformed data."""\n        raw_data = self.raw_data\n        file_path = self.raw_data.get(\'metadata\', {}).get(\'source_file\', \'unknown\')'

    content = re.sub(old_sig, new_sig, content)

    # Fix return statement at the end of transform_data
    # Look for "return rows" and replace with "self.transformed_data = rows"
    # This is tricky because we need to find it within the transform_data method

    # Pattern: find "return rows" that's likely at the end of transform_data
    # We'll look for the pattern with proper indentation (8 spaces for method body)
    content = re.sub(
        r'(\n        rows\.append\([^)]+\)\n)\s+return rows\n',
        r'\1\n        self.transformed_data = rows\n',
        content
    )

    return content

def fix_load_data_to_save_data(content: str) -> str:
    """Rename load_data to save_data and fix signature."""

    # Fix method signature - rename load_data to save_data
    old_sig = r'def load_data\(self, rows: List\[Dict\], \*\*kwargs\) -> Dict:'
    new_sig = 'def save_data(self) -> None:\n        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""\n        rows = self.transformed_data'

    content = re.sub(old_sig, new_sig, content)

    return content

def fix_processor_file(file_path: str) -> bool:
    """Fix a single processor file."""
    path = Path(file_path)

    if not path.exists():
        print(f"❌ File not found: {file_path}")
        return False

    print(f"Processing: {file_path}")

    # Read file
    with open(path, 'r') as f:
        content = f.read()

    original_content = content

    # Apply fixes
    content = fix_transform_data_signature(content)
    content = fix_load_data_to_save_data(content)

    if content == original_content:
        print(f"  ⚠️  No changes needed")
        return True

    # Write back
    with open(path, 'w') as f:
        f.write(content)

    print(f"  ✅ Fixed")
    return True

def main():
    print("=" * 60)
    print("Processor Signature Fix Script")
    print("=" * 60)
    print()

    success_count = 0
    fail_count = 0

    for processor_path in PROCESSORS_TO_FIX:
        if fix_processor_file(processor_path):
            success_count += 1
        else:
            fail_count += 1

    print()
    print("=" * 60)
    print(f"Summary: {success_count} succeeded, {fail_count} failed")
    print("=" * 60)

    if fail_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
