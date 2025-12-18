"""
Performance Summary Aggregation Processor

Aggregates prediction_accuracy data into pre-computed summaries for fast API access.
Computes performance slices by:
- Player (track record on specific players)
- Archetype (veteran_star, prime_star, etc.)
- Confidence tier (high, medium, low)
- Situation (bounce_back, home, away, rest_3plus, b2b)
- Time period (rolling_7d, rolling_30d, month, season)

Reads from:
- nba_predictions.prediction_accuracy (Phase 5B)
- nba_analytics.player_archetypes (for archetype classification)

Writes to:
- nba_predictions.prediction_performance_summary
"""

import logging
import hashlib
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Any

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
ACCURACY_TABLE = f'{PROJECT_ID}.nba_predictions.prediction_accuracy'
ARCHETYPES_TABLE = f'{PROJECT_ID}.nba_analytics.player_archetypes'
SUMMARY_TABLE = f'{PROJECT_ID}.nba_predictions.prediction_performance_summary'


class PerformanceSummaryProcessor:
    """
    Aggregates prediction accuracy into multi-dimensional summaries.

    Computes summaries for each prediction system across multiple dimensions
    and time periods to enable fast API queries.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def process(self, as_of_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Generate all performance summaries as of a specific date.

        Args:
            as_of_date: Date to compute summaries for (defaults to yesterday)

        Returns:
            Dict with processing statistics
        """
        if as_of_date is None:
            as_of_date = date.today() - timedelta(days=1)

        logger.info(f"Computing performance summaries as of {as_of_date}")

        # Get all systems that have predictions
        systems = self._get_active_systems(as_of_date)
        if not systems:
            logger.warning("No prediction systems found with graded data")
            return {'status': 'no_data', 'systems': 0, 'summaries': 0}

        logger.info(f"Found {len(systems)} active prediction systems: {systems}")

        all_summaries = []

        for system_id in systems:
            logger.info(f"Processing system: {system_id}")

            # Compute summaries for each time period
            for period_type, period_value, start_date, end_date in self._get_time_periods(as_of_date):
                summaries = self._compute_summaries_for_period(
                    system_id=system_id,
                    period_type=period_type,
                    period_value=period_value,
                    start_date=start_date,
                    end_date=end_date
                )
                all_summaries.extend(summaries)

        # Write all summaries
        if all_summaries:
            written = self._write_summaries(all_summaries, as_of_date)
            logger.info(f"Wrote {written} summary records")
        else:
            written = 0
            logger.warning("No summaries computed")

        return {
            'status': 'success' if written > 0 else 'no_data',
            'as_of_date': as_of_date.isoformat(),
            'systems': len(systems),
            'summaries': written
        }

    def _get_active_systems(self, as_of_date: date) -> List[str]:
        """Get list of prediction systems with graded data."""
        query = f"""
        SELECT DISTINCT system_id
        FROM `{ACCURACY_TABLE}`
        WHERE game_date <= '{as_of_date}'
          AND game_date >= DATE_SUB('{as_of_date}', INTERVAL 90 DAY)
        ORDER BY system_id
        """
        result = self.bq_client.query(query).result()
        return [row.system_id for row in result]

    def _get_time_periods(self, as_of_date: date) -> List[tuple]:
        """
        Get time periods to compute summaries for.

        Returns list of (period_type, period_value, start_date, end_date)
        """
        periods = []

        # Rolling 7 days
        periods.append((
            'rolling_7d',
            as_of_date.isoformat(),
            as_of_date - timedelta(days=7),
            as_of_date
        ))

        # Rolling 30 days
        periods.append((
            'rolling_30d',
            as_of_date.isoformat(),
            as_of_date - timedelta(days=30),
            as_of_date
        ))

        # Current month
        month_start = as_of_date.replace(day=1)
        periods.append((
            'month',
            as_of_date.strftime('%Y-%m'),
            month_start,
            as_of_date
        ))

        # Season (assuming Oct 2024 - Apr 2025 for 2024-25 season)
        if as_of_date.month >= 10:
            season_start = date(as_of_date.year, 10, 1)
            season_value = f"{as_of_date.year}-{str(as_of_date.year + 1)[2:]}"
        else:
            season_start = date(as_of_date.year - 1, 10, 1)
            season_value = f"{as_of_date.year - 1}-{str(as_of_date.year)[2:]}"

        periods.append((
            'season',
            season_value,
            season_start,
            as_of_date
        ))

        return periods

    def _compute_summaries_for_period(
        self,
        system_id: str,
        period_type: str,
        period_value: str,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        Compute all dimension slices for a given system and time period.
        """
        summaries = []

        # 1. Overall (no dimension filtering)
        overall = self._query_aggregation(
            system_id=system_id,
            start_date=start_date,
            end_date=end_date,
            dimension_filter=None
        )
        if overall:
            summaries.append(self._format_summary(
                base=overall,
                system_id=system_id,
                period_type=period_type,
                period_value=period_value,
                start_date=start_date,
                end_date=end_date
            ))

        # 2. By player (top players with >= 5 predictions)
        player_summaries = self._query_by_dimension(
            system_id=system_id,
            start_date=start_date,
            end_date=end_date,
            dimension='player_lookup',
            min_predictions=5
        )
        for ps in player_summaries:
            summaries.append(self._format_summary(
                base=ps,
                system_id=system_id,
                period_type=period_type,
                period_value=period_value,
                start_date=start_date,
                end_date=end_date,
                player_lookup=ps['dimension_value']
            ))

        # 3. By archetype
        archetype_summaries = self._query_by_archetype(
            system_id=system_id,
            start_date=start_date,
            end_date=end_date
        )
        for arch_sum in archetype_summaries:
            summaries.append(self._format_summary(
                base=arch_sum,
                system_id=system_id,
                period_type=period_type,
                period_value=period_value,
                start_date=start_date,
                end_date=end_date,
                archetype=arch_sum['dimension_value']
            ))

        # 4. By confidence tier
        for tier, min_conf, max_conf in [('high', 0.70, 1.0), ('medium', 0.55, 0.70), ('low', 0.0, 0.55)]:
            tier_summary = self._query_aggregation(
                system_id=system_id,
                start_date=start_date,
                end_date=end_date,
                dimension_filter=f"confidence_score >= {min_conf} AND confidence_score < {max_conf}"
            )
            if tier_summary and tier_summary.get('total_predictions', 0) > 0:
                summaries.append(self._format_summary(
                    base=tier_summary,
                    system_id=system_id,
                    period_type=period_type,
                    period_value=period_value,
                    start_date=start_date,
                    end_date=end_date,
                    confidence_tier=tier
                ))

        # 5. By situation (requires additional logic to detect situations)
        # For now, we'll do home vs away
        for situation, condition in [
            ('home', "team_abbr = SPLIT(game_id, '_')[OFFSET(2)]"),
            ('away', "team_abbr != SPLIT(game_id, '_')[OFFSET(2)]")
        ]:
            sit_summary = self._query_aggregation(
                system_id=system_id,
                start_date=start_date,
                end_date=end_date,
                dimension_filter=condition
            )
            if sit_summary and sit_summary.get('total_predictions', 0) > 0:
                summaries.append(self._format_summary(
                    base=sit_summary,
                    system_id=system_id,
                    period_type=period_type,
                    period_value=period_value,
                    start_date=start_date,
                    end_date=end_date,
                    situation=situation
                ))

        return summaries

    def _query_aggregation(
        self,
        system_id: str,
        start_date: date,
        end_date: date,
        dimension_filter: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Query aggregated metrics with optional dimension filter.
        """
        where_clause = f"""
        WHERE system_id = '{system_id}'
          AND game_date BETWEEN '{start_date}' AND '{end_date}'
        """
        if dimension_filter:
            where_clause += f" AND {dimension_filter}"

        query = f"""
        SELECT
            COUNT(*) as total_predictions,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as total_recommendations,
            COUNTIF(recommendation = 'OVER') as over_recommendations,
            COUNTIF(recommendation = 'UNDER') as under_recommendations,
            COUNTIF(recommendation = 'PASS') as pass_recommendations,
            COUNTIF(prediction_correct = TRUE) as hits,
            COUNTIF(prediction_correct = FALSE) as misses,
            SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE),
                       COUNTIF(recommendation IN ('OVER', 'UNDER'))) as hit_rate,
            SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE AND recommendation = 'OVER'),
                       COUNTIF(recommendation = 'OVER')) as over_hit_rate,
            SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE AND recommendation = 'UNDER'),
                       COUNTIF(recommendation = 'UNDER')) as under_hit_rate,
            AVG(absolute_error) as mae,
            AVG(signed_error) as avg_bias,
            SAFE_DIVIDE(COUNTIF(within_3_points = TRUE), COUNT(*)) as within_3_pct,
            SAFE_DIVIDE(COUNTIF(within_5_points = TRUE), COUNT(*)) as within_5_pct,
            AVG(confidence_score) as avg_confidence,
            COUNT(DISTINCT player_lookup) as unique_players,
            COUNT(DISTINCT game_id) as unique_games
        FROM `{ACCURACY_TABLE}`
        {where_clause}
        """

        try:
            result = list(self.bq_client.query(query).result())
            if result and result[0].total_predictions > 0:
                row = result[0]
                return {
                    'total_predictions': row.total_predictions,
                    'total_recommendations': row.total_recommendations,
                    'over_recommendations': row.over_recommendations,
                    'under_recommendations': row.under_recommendations,
                    'pass_recommendations': row.pass_recommendations,
                    'hits': row.hits,
                    'misses': row.misses,
                    'hit_rate': float(row.hit_rate) if row.hit_rate else None,
                    'over_hit_rate': float(row.over_hit_rate) if row.over_hit_rate else None,
                    'under_hit_rate': float(row.under_hit_rate) if row.under_hit_rate else None,
                    'mae': float(row.mae) if row.mae else None,
                    'avg_bias': float(row.avg_bias) if row.avg_bias else None,
                    'within_3_pct': float(row.within_3_pct) if row.within_3_pct else None,
                    'within_5_pct': float(row.within_5_pct) if row.within_5_pct else None,
                    'avg_confidence': float(row.avg_confidence) if row.avg_confidence else None,
                    'unique_players': row.unique_players,
                    'unique_games': row.unique_games
                }
        except Exception as e:
            logger.error(f"Error querying aggregation: {e}")

        return None

    def _query_by_dimension(
        self,
        system_id: str,
        start_date: date,
        end_date: date,
        dimension: str,
        min_predictions: int = 5
    ) -> List[Dict]:
        """
        Query aggregations grouped by a dimension.
        """
        query = f"""
        SELECT
            {dimension} as dimension_value,
            COUNT(*) as total_predictions,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as total_recommendations,
            COUNTIF(recommendation = 'OVER') as over_recommendations,
            COUNTIF(recommendation = 'UNDER') as under_recommendations,
            COUNTIF(recommendation = 'PASS') as pass_recommendations,
            COUNTIF(prediction_correct = TRUE) as hits,
            COUNTIF(prediction_correct = FALSE) as misses,
            SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE),
                       COUNTIF(recommendation IN ('OVER', 'UNDER'))) as hit_rate,
            SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE AND recommendation = 'OVER'),
                       COUNTIF(recommendation = 'OVER')) as over_hit_rate,
            SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE AND recommendation = 'UNDER'),
                       COUNTIF(recommendation = 'UNDER')) as under_hit_rate,
            AVG(absolute_error) as mae,
            AVG(signed_error) as avg_bias,
            SAFE_DIVIDE(COUNTIF(within_3_points = TRUE), COUNT(*)) as within_3_pct,
            SAFE_DIVIDE(COUNTIF(within_5_points = TRUE), COUNT(*)) as within_5_pct,
            AVG(confidence_score) as avg_confidence,
            COUNT(DISTINCT player_lookup) as unique_players,
            COUNT(DISTINCT game_id) as unique_games
        FROM `{ACCURACY_TABLE}`
        WHERE system_id = '{system_id}'
          AND game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY {dimension}
        HAVING COUNT(*) >= {min_predictions}
        ORDER BY COUNT(*) DESC
        LIMIT 200
        """

        try:
            result = list(self.bq_client.query(query).result())
            return [self._row_to_dict(row) for row in result]
        except Exception as e:
            logger.error(f"Error querying by dimension {dimension}: {e}")
            return []

    def _query_by_archetype(
        self,
        system_id: str,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        Query aggregations grouped by player archetype.
        Joins prediction_accuracy to player_archetypes.
        """
        query = f"""
        SELECT
            a.archetype as dimension_value,
            COUNT(*) as total_predictions,
            COUNTIF(pa.recommendation IN ('OVER', 'UNDER')) as total_recommendations,
            COUNTIF(pa.recommendation = 'OVER') as over_recommendations,
            COUNTIF(pa.recommendation = 'UNDER') as under_recommendations,
            COUNTIF(pa.recommendation = 'PASS') as pass_recommendations,
            COUNTIF(pa.prediction_correct = TRUE) as hits,
            COUNTIF(pa.prediction_correct = FALSE) as misses,
            SAFE_DIVIDE(COUNTIF(pa.prediction_correct = TRUE),
                       COUNTIF(pa.recommendation IN ('OVER', 'UNDER'))) as hit_rate,
            SAFE_DIVIDE(COUNTIF(pa.prediction_correct = TRUE AND pa.recommendation = 'OVER'),
                       COUNTIF(pa.recommendation = 'OVER')) as over_hit_rate,
            SAFE_DIVIDE(COUNTIF(pa.prediction_correct = TRUE AND pa.recommendation = 'UNDER'),
                       COUNTIF(pa.recommendation = 'UNDER')) as under_hit_rate,
            AVG(pa.absolute_error) as mae,
            AVG(pa.signed_error) as avg_bias,
            SAFE_DIVIDE(COUNTIF(pa.within_3_points = TRUE), COUNT(*)) as within_3_pct,
            SAFE_DIVIDE(COUNTIF(pa.within_5_points = TRUE), COUNT(*)) as within_5_pct,
            AVG(pa.confidence_score) as avg_confidence,
            COUNT(DISTINCT pa.player_lookup) as unique_players,
            COUNT(DISTINCT pa.game_id) as unique_games
        FROM `{ACCURACY_TABLE}` pa
        JOIN `{ARCHETYPES_TABLE}` a ON pa.player_lookup = a.player_lookup
        WHERE pa.system_id = '{system_id}'
          AND pa.game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY a.archetype
        HAVING COUNT(*) >= 10
        ORDER BY COUNT(*) DESC
        """

        try:
            result = list(self.bq_client.query(query).result())
            return [self._row_to_dict(row) for row in result]
        except Exception as e:
            logger.error(f"Error querying by archetype: {e}")
            return []

    def _row_to_dict(self, row) -> Dict:
        """Convert BigQuery row to dictionary."""
        return {
            'dimension_value': row.dimension_value,
            'total_predictions': row.total_predictions,
            'total_recommendations': row.total_recommendations,
            'over_recommendations': row.over_recommendations,
            'under_recommendations': row.under_recommendations,
            'pass_recommendations': row.pass_recommendations,
            'hits': row.hits,
            'misses': row.misses,
            'hit_rate': float(row.hit_rate) if row.hit_rate else None,
            'over_hit_rate': float(row.over_hit_rate) if row.over_hit_rate else None,
            'under_hit_rate': float(row.under_hit_rate) if row.under_hit_rate else None,
            'mae': float(row.mae) if row.mae else None,
            'avg_bias': float(row.avg_bias) if row.avg_bias else None,
            'within_3_pct': float(row.within_3_pct) if row.within_3_pct else None,
            'within_5_pct': float(row.within_5_pct) if row.within_5_pct else None,
            'avg_confidence': float(row.avg_confidence) if row.avg_confidence else None,
            'unique_players': row.unique_players,
            'unique_games': row.unique_games
        }

    def _format_summary(
        self,
        base: Dict,
        system_id: str,
        period_type: str,
        period_value: str,
        start_date: date,
        end_date: date,
        player_lookup: Optional[str] = None,
        archetype: Optional[str] = None,
        confidence_tier: Optional[str] = None,
        situation: Optional[str] = None
    ) -> Dict:
        """
        Format a summary record for insertion.
        """
        # Build summary key
        key_parts = [
            system_id,
            period_type,
            period_value,
            player_lookup or 'NULL',
            archetype or 'NULL',
            confidence_tier or 'NULL',
            situation or 'NULL'
        ]
        summary_key = '|'.join(key_parts)

        # Compute data hash for change detection
        data_str = f"{base.get('hits')}|{base.get('misses')}|{base.get('total_predictions')}"
        data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]

        return {
            'summary_key': summary_key,
            'system_id': system_id,
            'period_type': period_type,
            'period_value': period_value,
            'period_start_date': start_date.isoformat(),
            'period_end_date': end_date.isoformat(),
            'player_lookup': player_lookup,
            'archetype': archetype,
            'confidence_tier': confidence_tier,
            'situation': situation,
            'total_predictions': base.get('total_predictions'),
            'total_recommendations': base.get('total_recommendations'),
            'over_recommendations': base.get('over_recommendations'),
            'under_recommendations': base.get('under_recommendations'),
            'pass_recommendations': base.get('pass_recommendations'),
            'hits': base.get('hits'),
            'misses': base.get('misses'),
            'hit_rate': base.get('hit_rate'),
            'over_hit_rate': base.get('over_hit_rate'),
            'under_hit_rate': base.get('under_hit_rate'),
            'mae': base.get('mae'),
            'avg_bias': base.get('avg_bias'),
            'within_3_pct': base.get('within_3_pct'),
            'within_5_pct': base.get('within_5_pct'),
            'avg_confidence': base.get('avg_confidence'),
            'unique_players': base.get('unique_players'),
            'unique_games': base.get('unique_games'),
            'computed_at': datetime.now(timezone.utc).isoformat(),
            'data_hash': data_hash
        }

    def _write_summaries(self, summaries: List[Dict], as_of_date: date) -> int:
        """
        Write summaries to BigQuery using batch loading.

        Uses DELETE + INSERT pattern for idempotency.
        """
        if not summaries:
            return 0

        try:
            # Delete existing summaries for today's computation
            delete_query = f"""
            DELETE FROM `{SUMMARY_TABLE}`
            WHERE DATE(computed_at) = '{as_of_date}'
            """
            self.bq_client.query(delete_query).result()

            # Insert using batch loading
            table_ref = self.bq_client.get_table(SUMMARY_TABLE)
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                summaries,
                SUMMARY_TABLE,
                job_config=job_config
            )
            load_job.result()

            return load_job.output_rows or len(summaries)

        except Exception as e:
            logger.error(f"Error writing summaries: {e}")
            return 0


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Compute prediction performance summaries')
    parser.add_argument('--date', type=str, help='Date to compute summaries for (YYYY-MM-DD)')

    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    processor = PerformanceSummaryProcessor()
    result = processor.process(target_date)

    print(f"Result: {result}")
    return result


if __name__ == '__main__':
    main()
