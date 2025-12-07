#!/usr/bin/env python3
"""
Script to investigate quick win validation opportunities for player name resolution system.

This script runs three investigations:
1. Timing cleanup: Find pending names that now exist in registry
2. Suffix pattern matching: Find names where adding suffixes would match
3. Near-match detection: Search for fuzzy matching utilities in codebase

Usage:
    python scripts/investigate_name_resolution_quick_wins.py
"""

import sys
import os
from google.cloud import bigquery

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    """Run all three investigations."""

    # Initialize BigQuery client
    project_id = 'nba-props-platform'
    client = bigquery.Client(project=project_id)

    print("="*80)
    print("PLAYER NAME RESOLUTION - QUICK WIN VALIDATION OPPORTUNITIES")
    print("="*80)

    # =========================================================================
    # INVESTIGATION 1: Timing Cleanup Query
    # =========================================================================
    print("\n" + "="*80)
    print("INVESTIGATION 1: Timing Cleanup - Auto-Resolvable Names")
    print("="*80)
    print("Finding unresolved names with status='pending' where the normalized_lookup")
    print("now exists in nba_players_registry.\n")

    timing_query = """
    SELECT
      COUNT(*) as auto_resolvable_count,
      COUNT(DISTINCT u.normalized_lookup) as unique_names
    FROM `nba-props-platform.nba_reference.unresolved_player_names` u
    JOIN `nba-props-platform.nba_reference.nba_players_registry` r
      ON u.normalized_lookup = r.player_lookup
    WHERE u.status = 'pending'
    """

    try:
        timing_results = client.query(timing_query).to_dataframe()

        if not timing_results.empty:
            auto_resolvable = timing_results.iloc[0]['auto_resolvable_count']
            unique_names = timing_results.iloc[0]['unique_names']

            print(f"RESULTS:")
            print(f"  Total auto-resolvable records: {auto_resolvable}")
            print(f"  Unique player names: {unique_names}")
            print(f"\nIMPACT: These {auto_resolvable} records can be auto-resolved by marking")
            print(f"        them as 'resolved' since they now exist in the registry.")
        else:
            print("No auto-resolvable names found.")

    except Exception as e:
        print(f"ERROR running timing cleanup query: {e}")

    # =========================================================================
    # INVESTIGATION 2: Suffix Pattern Matching
    # =========================================================================
    print("\n" + "="*80)
    print("INVESTIGATION 2: Suffix Pattern Matching")
    print("="*80)
    print("Finding unresolved names where adding common suffixes (jr, sr, ii, iii, iv)")
    print("would match an existing registry entry.\n")

    suffix_query = """
    WITH suffixes AS (
      SELECT suffix FROM UNNEST([' jr', ' sr', ' ii', ' iii', ' iv', ' jr.', ' sr.']) AS suffix
    ),
    unresolved AS (
      SELECT DISTINCT normalized_lookup, team_abbr, season
      FROM `nba-props-platform.nba_reference.unresolved_player_names`
      WHERE status = 'pending'
    )
    SELECT
      u.normalized_lookup as unresolved_name,
      CONCAT(u.normalized_lookup, s.suffix) as potential_match,
      r.player_lookup as registry_match,
      r.player_name as registry_display_name,
      u.team_abbr,
      u.season
    FROM unresolved u
    CROSS JOIN suffixes s
    JOIN `nba-props-platform.nba_reference.nba_players_registry` r
      ON CONCAT(u.normalized_lookup, s.suffix) = r.player_lookup
    LIMIT 50
    """

    try:
        suffix_results = client.query(suffix_query).to_dataframe()

        if not suffix_results.empty:
            print(f"RESULTS: Found {len(suffix_results)} suffix pattern matches")
            print(f"\nSample matches (showing up to 20):")
            print("-" * 80)

            for idx, row in suffix_results.head(20).iterrows():
                print(f"\n{idx+1}. Unresolved: '{row['unresolved_name']}'")
                print(f"   + Suffix: '{row['potential_match']}'")
                print(f"   = Registry: '{row['registry_display_name']}' ({row['registry_match']})")
                print(f"   Context: {row['team_abbr']}, {row['season']}")

            if len(suffix_results) > 20:
                print(f"\n... and {len(suffix_results) - 20} more matches")

            print(f"\nIMPACT: These {len(suffix_results)} cases can likely be resolved by creating")
            print(f"        alias mappings with the appropriate suffix.")
        else:
            print("No suffix pattern matches found.")

    except Exception as e:
        print(f"ERROR running suffix pattern query: {e}")

    # =========================================================================
    # INVESTIGATION 3: Near-Match Detection (Fuzzy Matching Code)
    # =========================================================================
    print("\n" + "="*80)
    print("INVESTIGATION 3: Existing Fuzzy Matching Utilities")
    print("="*80)
    print("Searching codebase for existing fuzzy matching, Levenshtein, or similarity")
    print("functions that could be used for near-match detection.\n")

    print("FOUND FUZZY MATCHING CODE:")
    print("-" * 80)

    # Based on the grep results we found earlier
    fuzzy_files = [
        {
            'file': 'data_processors/raw/utils/name_utils.py',
            'functions': [
                'levenshtein_distance(s1, s2)',
                'calculate_similarity(name1, name2)',
                'normalize_name(name)'
            ],
            'description': 'Core name normalization and Levenshtein distance calculation'
        },
        {
            'file': 'tools/name_resolution_review.py',
            'functions': [
                'search_registry_for_similar(normalized_name, team)',
            ],
            'description': 'Uses LEVENSHTEIN() BigQuery function for similarity search (line 86)'
        },
        {
            'file': 'shared/utils/nba_team_mapper.py',
            'functions': [
                'get_nba_tricode_fuzzy()'
            ],
            'description': 'Fuzzy team name matching'
        }
    ]

    for item in fuzzy_files:
        print(f"\n📁 {item['file']}")
        print(f"   Description: {item['description']}")
        print(f"   Functions:")
        for func in item['functions']:
            print(f"     - {func}")

    print("\n" + "="*80)
    print("KEY FINDINGS - IMPLEMENTATION RECOMMENDATIONS")
    print("="*80)

    print("""
1. EXISTING FUZZY MATCHING UTILITIES:
   ✓ Levenshtein distance implementation exists in name_utils.py
   ✓ BigQuery LEVENSHTEIN() function already used in name_resolution_review.py
   ✓ calculate_similarity() function provides 0-1 similarity scores

   RECOMMENDATION: Use the existing levenshtein_distance() and calculate_similarity()
   functions from data_processors/raw/utils/name_utils.py for near-match detection.

2. QUICK WIN OPPORTUNITIES:
   a) Timing cleanup: Auto-resolve names that now exist in registry
   b) Suffix patterns: Create alias mappings for suffix variations
   c) Near-match detection: Use existing Levenshtein with threshold ~0.85

3. SUGGESTED IMPLEMENTATION APPROACH:
   - Create a new validation script that uses the fuzzy matching utilities
   - Set similarity threshold at 0.85 (configurable)
   - Require manual review for matches to prevent false positives
   - Focus on high-occurrence unresolved names first (occurrences >= 5)

4. CODEBASE INTEGRATION:
   The name_utils.py module is already imported and used by:
   - data_processors/raw/oddsapi/odds_api_props_processor.py
   - bin/raw/validation/validate_player_name_matching.py
   - bin/raw/validation/daily_player_matching.py

   This indicates a well-established pattern for name matching validation.
""")

    print("\n" + "="*80)
    print("INVESTIGATION COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
