"""
Prediction Line Enrichment Processor

Updates predictions with actual betting lines from odds_api_player_points_props.

This processor solves a timing issue where predictions are generated the night before
games (when props don't exist yet), resulting in NULL current_points_line values.
After props are scraped on game day, this processor enriches predictions with actual lines.

Reads from:
- nba_predictions.player_prop_predictions (predictions with NULL lines)
- nba_raw.odds_api_player_points_props (actual betting lines)

Updates:
- nba_predictions.player_prop_predictions (adds current_points_line, has_prop_line, etc.)

Scheduling:
- Should run AFTER props are scraped (after 18:00 UTC on game days)
- Safe to run multiple times (idempotent - only updates NULL values)
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class PredictionLineEnrichmentProcessor:
    """
    Enriches predictions with actual betting lines from odds_api.

    Uses BigQuery MERGE to update predictions that have NULL current_points_line
    with actual lines from the odds_api_player_points_props table.
    """

    def __init__(self, project_id: str = PROJECT_ID, dataset_prefix: str = ''):
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        self.bq_client = bigquery.Client(project=project_id)

        # Construct table names with optional prefix (for testing)
        predictions_dataset = f"{dataset_prefix}_nba_predictions" if dataset_prefix else "nba_predictions"
        raw_dataset = f"{dataset_prefix}_nba_raw" if dataset_prefix else "nba_raw"

        self.predictions_table = f'{project_id}.{predictions_dataset}.player_prop_predictions'
        self.props_table = f'{project_id}.{raw_dataset}.odds_api_player_points_props'

        logger.info(f"Initialized PredictionLineEnrichmentProcessor (dataset_prefix: {dataset_prefix or 'production'})")

    def get_predictions_missing_lines(self, game_date: date) -> List[Dict]:
        """
        Get predictions that are missing betting lines for a game date.

        Returns list of predictions where current_points_line IS NULL.
        """
        query = f"""
        SELECT
            prediction_id,
            player_lookup,
            game_id,
            game_date,
            current_points_line,
            has_prop_line,
            line_source
        FROM `{self.predictions_table}`
        WHERE game_date = '{game_date}'
          AND current_points_line IS NULL
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            logger.info(f"Found {len(result)} predictions missing lines for {game_date}")
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error querying predictions missing lines: {e}")
            return []

    def get_available_props(self, game_date: date) -> Dict[str, Dict]:
        """
        Get available betting props for a game date.

        Returns dict mapping player_lookup -> {points_line, bookmaker, snapshot_timestamp}
        Uses sportsbook priority: DraftKings > FanDuel > BetMGM > PointsBet > Caesars
        """
        query = f"""
        WITH ranked_props AS (
            SELECT
                player_lookup,
                points_line,
                bookmaker,
                snapshot_timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY
                        CASE bookmaker
                            WHEN 'draftkings' THEN 1
                            WHEN 'fanduel' THEN 2
                            WHEN 'betmgm' THEN 3
                            WHEN 'pointsbet' THEN 4
                            WHEN 'caesars' THEN 5
                            ELSE 99
                        END,
                        snapshot_timestamp DESC
                ) as rn
            FROM `{self.props_table}`
            WHERE game_date = '{game_date}'
              AND points_line IS NOT NULL
        )
        SELECT
            player_lookup,
            points_line,
            bookmaker,
            snapshot_timestamp
        FROM ranked_props
        WHERE rn = 1
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            props_dict = {}
            for _, row in result.iterrows():
                props_dict[row['player_lookup']] = {
                    'points_line': float(row['points_line']),
                    'bookmaker': row['bookmaker'].upper() if row['bookmaker'] else 'UNKNOWN',
                    'snapshot_timestamp': row['snapshot_timestamp']
                }
            logger.info(f"Found {len(props_dict)} players with props for {game_date}")
            return props_dict
        except Exception as e:
            logger.error(f"Error querying available props: {e}")
            return {}

    def enrich_predictions(self, game_date: date, dry_run: bool = False) -> Dict:
        """
        Enrich predictions with actual betting lines.

        Args:
            game_date: The game date to process
            dry_run: If True, only report what would be updated without making changes

        Returns:
            Dict with enrichment results:
            - predictions_missing_lines: Count of predictions without lines
            - props_available: Count of players with props data
            - predictions_enriched: Count of predictions that were/would be enriched
            - predictions_still_missing: Count that couldn't be enriched (no props data)
        """
        logger.info(f"Starting line enrichment for {game_date} (dry_run={dry_run})")

        # Get predictions missing lines
        predictions_missing = self.get_predictions_missing_lines(game_date)

        if not predictions_missing:
            logger.info(f"No predictions missing lines for {game_date}")
            return {
                'game_date': str(game_date),
                'predictions_missing_lines': 0,
                'props_available': 0,
                'predictions_enriched': 0,
                'predictions_still_missing': 0,
                'dry_run': dry_run
            }

        # Get available props
        props = self.get_available_props(game_date)

        # Match predictions to props
        enrichable = []
        still_missing = []

        for pred in predictions_missing:
            player_lookup = pred['player_lookup']
            if player_lookup in props:
                enrichable.append({
                    'prediction_id': pred['prediction_id'],
                    'player_lookup': player_lookup,
                    'points_line': props[player_lookup]['points_line'],
                    'bookmaker': props[player_lookup]['bookmaker']
                })
            else:
                still_missing.append(player_lookup)

        logger.info(f"Can enrich {len(enrichable)} predictions, {len(still_missing)} still missing props")

        if still_missing:
            logger.debug(f"Players without props: {still_missing[:10]}...")  # Log first 10

        # Perform the update
        if enrichable and not dry_run:
            updated_count = self._update_predictions(enrichable, game_date)
        else:
            updated_count = len(enrichable) if dry_run else 0

        return {
            'game_date': str(game_date),
            'predictions_missing_lines': len(predictions_missing),
            'props_available': len(props),
            'predictions_enriched': updated_count,
            'predictions_still_missing': len(still_missing),
            'dry_run': dry_run
        }

    def _update_predictions(self, enrichable: List[Dict], game_date: date) -> int:
        """
        Update predictions with actual betting lines using BigQuery MERGE.

        Args:
            enrichable: List of dicts with prediction_id, points_line, bookmaker
            game_date: The game date being processed

        Returns:
            Number of predictions updated
        """
        if not enrichable:
            return 0

        # Build the MERGE statement
        # Create a temp table with the enrichment data
        values_list = []
        for item in enrichable:
            values_list.append(
                f"('{item['prediction_id']}', {item['points_line']}, '{item['bookmaker']}')"
            )

        values_sql = ",\n            ".join(values_list)

        merge_query = f"""
        MERGE `{self.predictions_table}` AS target
        USING (
            SELECT
                prediction_id,
                points_line,
                bookmaker
            FROM UNNEST([
                STRUCT<prediction_id STRING, points_line FLOAT64, bookmaker STRING>
                {values_sql}
            ])
        ) AS source
        ON target.prediction_id = source.prediction_id
        WHEN MATCHED AND target.current_points_line IS NULL THEN
            UPDATE SET
                current_points_line = source.points_line,
                has_prop_line = TRUE,
                line_source = 'ACTUAL_PROP',
                line_source_api = 'ODDS_API',
                sportsbook = source.bookmaker,
                line_margin = ROUND(target.predicted_points - source.points_line, 2),
                -- Recalculate recommendation based on predicted_points vs line
                recommendation = CASE
                    WHEN target.predicted_points > source.points_line THEN 'OVER'
                    WHEN target.predicted_points < source.points_line THEN 'UNDER'
                    ELSE 'PASS'
                END,
                updated_at = CURRENT_TIMESTAMP()
        """

        try:
            # Execute the merge
            job = self.bq_client.query(merge_query)
            job.result()  # Wait for completion

            # Get the number of rows affected
            updated_count = job.num_dml_affected_rows
            logger.info(f"Updated {updated_count} predictions with betting lines")
            return updated_count

        except Exception as e:
            logger.error(f"Error updating predictions: {e}")
            raise

    def fix_recommendations(self, game_date: date) -> int:
        """
        Fix recommendations for predictions that were enriched but still have NO_LINE recommendation.

        This handles predictions that were originally generated without props, got enriched
        with lines, but still have recommendation='NO_LINE'.
        """
        fix_query = f"""
        UPDATE `{self.predictions_table}`
        SET
            recommendation = CASE
                WHEN predicted_points > current_points_line THEN 'OVER'
                WHEN predicted_points < current_points_line THEN 'UNDER'
                ELSE 'PASS'
            END,
            updated_at = CURRENT_TIMESTAMP()
        WHERE game_date = '{game_date}'
          AND current_points_line IS NOT NULL
          AND recommendation = 'NO_LINE'
        """

        try:
            job = self.bq_client.query(fix_query)
            job.result()
            updated_count = job.num_dml_affected_rows
            logger.info(f"Fixed {updated_count} recommendations for {game_date}")
            return updated_count
        except Exception as e:
            logger.error(f"Error fixing recommendations: {e}")
            raise

    def enrich_date_range(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False
    ) -> List[Dict]:
        """
        Enrich predictions for a range of dates.

        Args:
            start_date: First date to process
            end_date: Last date to process (inclusive)
            dry_run: If True, only report what would be updated

        Returns:
            List of enrichment results for each date
        """
        results = []
        current_date = start_date

        while current_date <= end_date:
            result = self.enrich_predictions(current_date, dry_run=dry_run)
            results.append(result)
            current_date += timedelta(days=1)

        # Summary
        total_enriched = sum(r['predictions_enriched'] for r in results)
        total_missing = sum(r['predictions_still_missing'] for r in results)

        logger.info(f"Date range enrichment complete: {total_enriched} enriched, {total_missing} still missing")

        return results


def main():
    """CLI entry point for running the enrichment processor."""
    import argparse
    from datetime import datetime

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Enrich predictions with actual betting lines')
    parser.add_argument('--date', type=str, help='Game date (YYYY-MM-DD). Defaults to today.')
    parser.add_argument('--start-date', type=str, help='Start date for range processing')
    parser.add_argument('--end-date', type=str, help='End date for range processing')
    parser.add_argument('--dry-run', action='store_true', help='Report only, do not update')
    parser.add_argument('--fix-recommendations-only', action='store_true',
                        help='Only fix recommendations for already-enriched predictions')
    parser.add_argument('--dataset-prefix', type=str, default='', help='Dataset prefix for testing')

    args = parser.parse_args()

    processor = PredictionLineEnrichmentProcessor(dataset_prefix=args.dataset_prefix)

    # Parse dates
    if args.start_date and args.end_date:
        start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
    elif args.date:
        dates = [datetime.strptime(args.date, '%Y-%m-%d').date()]
    else:
        dates = [datetime.now(timezone.utc).date()]

    # Fix recommendations only mode
    if args.fix_recommendations_only:
        print("\nFixing Recommendations:")
        print("-" * 60)
        total_fixed = 0
        for game_date in dates:
            fixed = processor.fix_recommendations(game_date)
            print(f"{game_date}: {fixed} recommendations fixed")
            total_fixed += fixed
        print(f"\nTotal fixed: {total_fixed}")
        return

    # Normal enrichment mode
    if len(dates) > 1:
        # Range mode
        results = processor.enrich_date_range(dates[0], dates[-1], dry_run=args.dry_run)

        print("\nEnrichment Results:")
        print("-" * 60)
        total_enriched = 0
        for r in results:
            print(f"{r['game_date']}: {r['predictions_enriched']} enriched, {r['predictions_still_missing']} still missing")
            total_enriched += r['predictions_enriched']

        # Auto-fix recommendations after enrichment (unless dry run)
        if not args.dry_run and total_enriched > 0:
            print("\nFixing Recommendations:")
            print("-" * 60)
            for game_date in dates:
                fixed = processor.fix_recommendations(game_date)
                print(f"{game_date}: {fixed} recommendations fixed")
    else:
        # Single date mode
        game_date = dates[0]
        result = processor.enrich_predictions(game_date, dry_run=args.dry_run)

        print("\nEnrichment Result:")
        print("-" * 40)
        print(f"Game Date: {result['game_date']}")
        print(f"Predictions Missing Lines: {result['predictions_missing_lines']}")
        print(f"Props Available: {result['props_available']}")
        print(f"Predictions Enriched: {result['predictions_enriched']}")
        print(f"Still Missing: {result['predictions_still_missing']}")
        print(f"Dry Run: {result['dry_run']}")

        # Auto-fix recommendations after enrichment (unless dry run)
        if not args.dry_run and result['predictions_enriched'] > 0:
            print(f"\nFixing Recommendations:")
            fixed = processor.fix_recommendations(game_date)
            print(f"  Fixed: {fixed} recommendations")


if __name__ == '__main__':
    main()
