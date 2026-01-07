#!/usr/bin/env python3
"""
Multi-Layer Pipeline Validation

Validates data completeness across all pipeline layers to catch gaps early.
Prevents issues like the Phase 4 gap that went undetected for 3 months.

Created: Jan 3, 2026
Purpose: Sustainable monitoring infrastructure
"""

import argparse
from datetime import datetime, date, timedelta
from google.cloud import bigquery
from typing import Dict, List, Tuple
import sys

PROJECT_ID = "nba-props-platform"

class PipelineValidator:
    def __init__(self, start_date: str, end_date: str):
        self.client = bigquery.Client(project=PROJECT_ID)
        self.start_date = start_date
        self.end_date = end_date
        self.gaps = []
        self.warnings = []

    def validate_all_layers(self) -> bool:
        """Validate all pipeline layers. Returns True if all pass."""
        print("=" * 80)
        print(" PIPELINE COMPLETENESS VALIDATION")
        print("=" * 80)
        print(f"Date range: {self.start_date} to {self.end_date}")
        print()

        all_passed = True

        # Layer 1: Raw Data
        print("📊 Layer 1: Raw Data (BDL)")
        l1_count = self._validate_layer("nba_raw.bdl_player_boxscores", "L1")
        print(f"   Games: {l1_count}")

        # Layer 3: Analytics
        print("\n📊 Layer 3: Analytics")
        l3_count = self._validate_layer("nba_analytics.player_game_summary", "L3")
        l3_pct = (l3_count / l1_count * 100) if l1_count > 0 else 0
        print(f"   Games: {l3_count} ({l3_pct:.1f}% of L1)")

        if l3_pct < 90:
            self.gaps.append(f"❌ L3 coverage: {l3_pct:.1f}% (target: >= 90%)")
            all_passed = False
        else:
            print(f"   ✅ Coverage OK")

        # Layer 4: Precompute Features (CRITICAL - was missing before!)
        print("\n📊 Layer 4: Precompute Features ⚠️")
        l4_count = self._validate_layer("nba_precompute.player_composite_factors", "L4")
        l4_pct = (l4_count / l1_count * 100) if l1_count > 0 else 0
        print(f"   Games: {l4_count} ({l4_pct:.1f}% of L1)")

        if l4_pct < 80:
            self.gaps.append(f"❌ L4 coverage: {l4_pct:.1f}% (target: >= 80%)")
            all_passed = False
        elif l4_pct < 90:
            self.warnings.append(f"⚠️  L4 coverage: {l4_pct:.1f}% (below ideal 90%)")
        else:
            print(f"   ✅ Coverage OK")

        # Find specific date gaps
        print("\n🔍 Checking for date-level gaps...")
        date_gaps = self._find_date_gaps()

        if date_gaps:
            print(f"\n❌ Found {len(date_gaps)} dates with gaps:")
            for gap in date_gaps[:10]:  # Show first 10
                print(f"   {gap}")
            if len(date_gaps) > 10:
                print(f"   ... and {len(date_gaps) - 10} more")
        else:
            print("   ✅ No date-level gaps found")

        # Summary
        print("\n" + "=" * 80)
        print(" VALIDATION SUMMARY")
        print("=" * 80)

        if all_passed and not date_gaps:
            print("✅ ALL VALIDATIONS PASSED")
            return True
        else:
            if self.gaps:
                print("\n❌ FAILURES:")
                for gap in self.gaps:
                    print(f"   {gap}")
            if self.warnings:
                print("\n⚠️  WARNINGS:")
                for warning in self.warnings:
                    print(f"   {warning}")
            if date_gaps:
                print(f"\n📋 {len(date_gaps)} dates with incomplete data")

            return False

    def _validate_layer(self, table: str, layer_name: str) -> int:
        """Count distinct games in a layer."""
        query = f"""
        SELECT COUNT(DISTINCT game_id) as game_count
        FROM `{PROJECT_ID}.{table}`
        WHERE game_date >= '{self.start_date}'
          AND game_date <= '{self.end_date}'
        """

        try:
            result = list(self.client.query(query).result())
            return result[0]['game_count'] if result else 0
        except Exception as e:
            print(f"   ❌ Error querying {layer_name}: {e}")
            self.gaps.append(f"❌ {layer_name} query failed: {e}")
            return 0

    def _find_date_gaps(self) -> List[str]:
        """Find dates with incomplete Layer 4 coverage."""
        query = f"""
        WITH layer1 AS (
          SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
          FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
          WHERE game_date >= '{self.start_date}'
            AND game_date <= '{self.end_date}'
          GROUP BY date
        ),
        layer4 AS (
          SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
          FROM `{PROJECT_ID}.nba_precompute.player_composite_factors`
          WHERE game_date >= '{self.start_date}'
            AND game_date <= '{self.end_date}'
          GROUP BY date
        )
        SELECT
          l1.date,
          l1.games as l1_games,
          COALESCE(l4.games, 0) as l4_games,
          ROUND(100.0 * COALESCE(l4.games, 0) / l1.games, 1) as coverage_pct
        FROM layer1 l1
        LEFT JOIN layer4 l4 ON l1.date = l4.date
        WHERE COALESCE(l4.games, 0) < l1.games * 0.8  -- Less than 80% coverage
        ORDER BY l1.date DESC
        """

        try:
            results = list(self.client.query(query).result())
            return [
                f"{row['date']}: {row['l4_games']}/{row['l1_games']} games ({row['coverage_pct']}%)"
                for row in results
            ]
        except Exception as e:
            print(f"   ⚠️  Could not check date-level gaps: {e}")
            return []

def main():
    parser = argparse.ArgumentParser(description='Validate pipeline completeness across all layers')
    parser.add_argument('--start-date', default=(date.today() - timedelta(days=30)).isoformat(),
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default=date.today().isoformat(),
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--alert-on-gaps', action='store_true',
                       help='Exit with error code if gaps found (for CI/CD)')

    args = parser.parse_args()

    validator = PipelineValidator(args.start_date, args.end_date)
    passed = validator.validate_all_layers()

    if args.alert_on_gaps and not passed:
        sys.exit(1)  # Fail for automation

    sys.exit(0 if passed else 0)  # Success even if gaps (for manual runs)

if __name__ == "__main__":
    main()
