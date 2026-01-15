#!/usr/bin/env python3
"""
Validate Player Matching Between Predictions and Odds

CRITICAL VALIDATION SCRIPT

Tests whether player names from the historical odds backfill will correctly
match with player names in the predictions table.

The Problem:
- Predictions use underscore format: logan_webb (from MLB Stats API)
- Historical odds use no-underscore format: loganwebb (from Odds API normalizer)

The Solution:
- Normalize both sides by removing underscores before matching:
  REPLACE(pitcher_lookup, '_', '') = player_lookup

This script validates that the matching logic will work correctly.

Usage:
    # Full validation (when backfill has some data)
    python scripts/mlb/historical_odds_backfill/validate_player_matching.py

    # Quick check (mock data)
    python scripts/mlb/historical_odds_backfill/validate_player_matching.py --mock

    # Test specific pitcher
    python scripts/mlb/historical_odds_backfill/validate_player_matching.py --pitcher "Logan Webb"
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import bigquery
from shared.utils.player_name_normalizer import normalize_name_for_lookup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class PlayerMatchingValidator:
    """Validates player name matching between predictions and odds."""

    def __init__(self):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.issues = []
        self.successes = []

    def get_prediction_pitchers(self) -> List[Dict]:
        """Get unique pitchers from predictions table."""
        query = """
        SELECT DISTINCT
            pitcher_lookup,
            pitcher_name,
            REPLACE(pitcher_lookup, '_', '') as normalized
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        ORDER BY pitcher_name
        """
        return [dict(row) for row in self.bq_client.query(query).result()]

    def get_odds_players(self) -> List[Dict]:
        """Get unique players from historical odds data (if available)."""
        query = """
        SELECT DISTINCT
            player_lookup,
            player_name,
            REPLACE(player_lookup, '_', '') as normalized
        FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
        WHERE source_file_path LIKE '%pitcher-props-history%'
          AND market_key = 'pitcher_strikeouts'
        ORDER BY player_name
        """
        try:
            results = list(self.bq_client.query(query).result())
            return [dict(row) for row in results]
        except Exception as e:
            logger.warning(f"Could not query odds data: {e}")
            return []

    def normalize_for_matching(self, name: str) -> str:
        """
        Apply the same normalization as the SQL TRANSLATE function.
        Removes: underscores, hyphens, and accented characters.
        """
        # Map of accented characters to ASCII equivalents
        accent_map = str.maketrans(
            'áàâäãåéèêëíìîïóòôöõúùûüñç',
            'aaaaaaeeeeiiiiooooouuuunc'
        )
        result = name.lower()
        result = result.replace('_', '').replace('-', '')
        result = result.translate(accent_map)
        return result

    def test_normalization_equivalence(self) -> Dict:
        """Test that normalization produces matching results."""
        test_cases = [
            # (display_name, expected_prediction_format, expected_odds_format)
            ("Logan Webb", "logan_webb", "loganwebb"),
            ("Gerrit Cole", "gerrit_cole", "gerritcole"),
            ("Corbin Burnes", "corbin_burnes", "corbinburnes"),
            ("Shohei Ohtani", "shohei_ohtani", "shoheiohtani"),
            ("Yu Darvish", "yu_darvish", "yudarvish"),
            ("Jacob deGrom", "jacob_degrom", "jacobdegrom"),
            ("Carlos Rodón", "carlos_rodón", "carlosrodon"),  # With accent
            ("Dylan Cease", "dylan_cease", "dylancease"),
            ("Freddy Peralta", "freddy_peralta", "freddyperalta"),
            ("Zack Wheeler", "zack_wheeler", "zackwheeler"),
            ("AJ Smith-Shawver", "aj_smith-shawver", "ajsmithshawver"),  # With hyphen
            ("Roddery Muñoz", "roddery_muñoz", "rodderymuñoz"),  # Spanish ñ (not in our TRANSLATE)
        ]

        results = {
            'passed': [],
            'failed': [],
        }

        for display_name, pred_format, odds_format in test_cases:
            # Normalize prediction format using the same logic as SQL
            pred_normalized = self.normalize_for_matching(pred_format)

            # Use our normalizer for odds format (what the processor produces)
            odds_normalized = normalize_name_for_lookup(display_name)

            # Check if they match
            if pred_normalized == odds_normalized:
                results['passed'].append({
                    'name': display_name,
                    'pred_format': pred_format,
                    'pred_normalized': pred_normalized,
                    'odds_format': odds_format,
                    'odds_normalized': odds_normalized,
                })
            else:
                results['failed'].append({
                    'name': display_name,
                    'pred_format': pred_format,
                    'pred_normalized': pred_normalized,
                    'odds_format': odds_format,
                    'odds_normalized': odds_normalized,
                    'issue': f"Mismatch: '{pred_normalized}' != '{odds_normalized}'"
                })

        return results

    def check_actual_matching(self) -> Dict:
        """Check actual matching between predictions and odds tables."""
        # Query to find matches and mismatches
        # Uses TRANSLATE to normalize: remove underscores, hyphens, and accented characters
        query = """
        WITH prediction_pitchers AS (
            SELECT DISTINCT
                pitcher_lookup,
                pitcher_name,
                LOWER(TRANSLATE(
                    REPLACE(REPLACE(pitcher_lookup, '_', ''), '-', ''),
                    'áàâäãåéèêëíìîïóòôöõúùûüñç',
                    'aaaaaaeeeeiiiiooooouuuunc'
                )) as normalized
            FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        ),
        odds_players AS (
            SELECT DISTINCT
                player_lookup,
                player_name,
                LOWER(TRANSLATE(
                    REPLACE(REPLACE(player_lookup, '_', ''), '-', ''),
                    'áàâäãåéèêëíìîïóòôöõúùûüñç',
                    'aaaaaaeeeeiiiiooooouuuunc'
                )) as normalized
            FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
            WHERE source_file_path LIKE '%pitcher-props-history%'
              AND market_key = 'pitcher_strikeouts'
        )
        SELECT
            p.pitcher_name as prediction_name,
            p.pitcher_lookup as prediction_lookup,
            p.normalized as prediction_normalized,
            o.player_name as odds_name,
            o.player_lookup as odds_lookup,
            o.normalized as odds_normalized,
            CASE WHEN o.normalized IS NOT NULL THEN 'MATCHED' ELSE 'UNMATCHED' END as status
        FROM prediction_pitchers p
        LEFT JOIN odds_players o ON p.normalized = o.normalized
        ORDER BY status DESC, p.pitcher_name
        """

        try:
            results = list(self.bq_client.query(query).result())

            matched = [dict(r) for r in results if r.status == 'MATCHED']
            unmatched = [dict(r) for r in results if r.status == 'UNMATCHED']

            return {
                'total': len(results),
                'matched': len(matched),
                'unmatched': len(unmatched),
                'match_rate': len(matched) / len(results) * 100 if results else 0,
                'matched_details': matched[:10],  # First 10
                'unmatched_details': unmatched[:20],  # First 20
            }
        except Exception as e:
            logger.warning(f"Could not check actual matching: {e}")
            return None

    def run(self, mock: bool = False, pitcher: str = None) -> Dict:
        """Run validation checks."""
        logger.info("=" * 70)
        logger.info("PLAYER MATCHING VALIDATION")
        logger.info("=" * 70)

        results = {}

        # Test 1: Normalization equivalence
        logger.info("\n1. Testing normalization equivalence...")
        norm_results = self.test_normalization_equivalence()
        results['normalization'] = norm_results

        logger.info(f"   Passed: {len(norm_results['passed'])}")
        logger.info(f"   Failed: {len(norm_results['failed'])}")

        for fail in norm_results['failed']:
            logger.warning(f"   ❌ {fail['name']}: {fail['issue']}")

        # Test 2: Check prediction pitcher formats
        logger.info("\n2. Checking prediction table formats...")
        pred_pitchers = self.get_prediction_pitchers()
        results['prediction_pitchers'] = len(pred_pitchers)

        if pred_pitchers:
            logger.info(f"   Found {len(pred_pitchers)} unique pitchers")
            logger.info("   Sample formats:")
            for p in pred_pitchers[:5]:
                logger.info(f"     {p['pitcher_name']}: {p['pitcher_lookup']} -> {p['normalized']}")

        # Test 3: Check odds player formats (if data exists)
        logger.info("\n3. Checking odds table formats...")
        odds_players = self.get_odds_players()
        results['odds_players'] = len(odds_players)

        if odds_players:
            logger.info(f"   Found {len(odds_players)} unique players in historical odds")
            logger.info("   Sample formats:")
            for o in odds_players[:5]:
                logger.info(f"     {o['player_name']}: {o['player_lookup']} -> {o['normalized']}")
        else:
            logger.info("   No historical odds data yet (backfill still running)")

        # Test 4: Check actual matching
        if odds_players:
            logger.info("\n4. Checking actual matching between tables...")
            match_results = self.check_actual_matching()
            results['matching'] = match_results

            if match_results:
                logger.info(f"   Total pitchers: {match_results['total']}")
                logger.info(f"   Matched: {match_results['matched']}")
                logger.info(f"   Unmatched: {match_results['unmatched']}")
                logger.info(f"   Match rate: {match_results['match_rate']:.1f}%")

                if match_results['unmatched_details']:
                    logger.warning("\n   Unmatched pitchers (no odds data):")
                    for u in match_results['unmatched_details'][:10]:
                        logger.warning(f"     {u['prediction_name']}: {u['prediction_normalized']}")
        else:
            logger.info("\n4. Skipping actual matching (no odds data yet)")

        # Test specific pitcher if requested
        if pitcher:
            logger.info(f"\n5. Testing specific pitcher: {pitcher}")
            self.test_specific_pitcher(pitcher)

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 70)

        all_passed = len(norm_results['failed']) == 0

        if all_passed:
            logger.info("✅ All normalization tests PASSED")
            logger.info("   The matching logic should work correctly.")
        else:
            logger.warning("❌ Some normalization tests FAILED")
            logger.warning("   Review failed cases above and update normalizer if needed.")

        if odds_players and results.get('matching'):
            mr = results['matching']
            if mr['match_rate'] >= 90:
                logger.info(f"✅ Match rate is {mr['match_rate']:.1f}% (good)")
            elif mr['match_rate'] >= 70:
                logger.warning(f"⚠️ Match rate is {mr['match_rate']:.1f}% (acceptable)")
            else:
                logger.error(f"❌ Match rate is {mr['match_rate']:.1f}% (needs investigation)")

        logger.info("\nKey Format Information:")
        logger.info("  - Predictions: underscore format (logan_webb)")
        logger.info("  - Odds: no-underscore format (loganwebb)")
        logger.info("  - Matching: REPLACE(pitcher_lookup, '_', '') = player_lookup")

        return results

    def test_specific_pitcher(self, name: str):
        """Test matching for a specific pitcher name."""
        # Show all format variations
        normalized = normalize_name_for_lookup(name)
        underscore_format = name.lower().replace(' ', '_')

        logger.info(f"   Display name: {name}")
        logger.info(f"   Prediction format (underscore): {underscore_format}")
        logger.info(f"   Odds format (normalizer): {normalized}")
        logger.info(f"   Normalized prediction: {underscore_format.replace('_', '')}")

        if underscore_format.replace('_', '') == normalized:
            logger.info("   ✅ These will MATCH")
        else:
            logger.warning(f"   ❌ These will NOT match!")
            logger.warning(f"      '{underscore_format.replace('_', '')}' != '{normalized}'")


def main():
    parser = argparse.ArgumentParser(
        description='Validate player matching between predictions and odds',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--mock',
        action='store_true',
        help='Run with mock data only (no database)'
    )
    parser.add_argument(
        '--pitcher',
        help='Test specific pitcher name (e.g., "Logan Webb")'
    )

    args = parser.parse_args()

    validator = PlayerMatchingValidator()

    try:
        results = validator.run(mock=args.mock, pitcher=args.pitcher)

        # Exit code based on validation
        norm_failures = len(results.get('normalization', {}).get('failed', []))
        if norm_failures > 0:
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Validation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
