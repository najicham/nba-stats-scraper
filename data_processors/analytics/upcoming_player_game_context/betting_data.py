"""
Path: data_processors/analytics/upcoming_player_game_context/betting_data.py

Betting Data Module - Prop Lines, Game Lines, and Public Betting

Extracted from upcoming_player_game_context_processor.py for maintainability.
Contains functions for extracting and processing betting-related data.
"""

import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded

logger = logging.getLogger(__name__)


class BettingDataExtractor:
    """
    Extractor for betting-related data.

    Handles prop lines, game lines (spreads/totals), and public betting data.
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize the extractor.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id

    def extract_prop_lines_from_odds_api(
        self,
        player_game_pairs: List[Tuple[str, str]],
        target_date: date
    ) -> Dict[Tuple[str, str], Dict]:
        """
        Extract prop lines from Odds API using batch query for efficiency.

        Args:
            player_game_pairs: List of (player_lookup, game_id) tuples
            target_date: Target game date

        Returns:
            Dict mapping (player_lookup, game_id) to prop info dict
        """
        prop_lines = {}

        # Build batch query - get opening and current lines for all players in one query
        player_lookups = list(set([p[0] for p in player_game_pairs]))

        batch_query = f"""
        WITH opening_lines AS (
            SELECT
                player_lookup,
                game_id,
                points_line as opening_line,
                bookmaker as opening_source,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_id
                    ORDER BY snapshot_timestamp ASC
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @game_date
        ),
        current_lines AS (
            SELECT
                player_lookup,
                game_id,
                points_line as current_line,
                bookmaker as current_source,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_id
                    ORDER BY snapshot_timestamp DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @game_date
        )
        SELECT
            COALESCE(o.player_lookup, c.player_lookup) as player_lookup,
            COALESCE(o.game_id, c.game_id) as game_id,
            o.opening_line,
            o.opening_source,
            c.current_line,
            c.current_source
        FROM opening_lines o
        FULL OUTER JOIN current_lines c
            ON o.player_lookup = c.player_lookup AND o.game_id = c.game_id
        WHERE (o.rn = 1 OR o.rn IS NULL) AND (c.rn = 1 OR c.rn IS NULL)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", target_date),
            ]
        )

        try:
            df = self.bq_client.query(batch_query, job_config=job_config).to_dataframe()
            logger.info(f"Odds API batch query returned {len(df)} prop line records")

            # Create lookup dict keyed by (player_lookup, game_id)
            props_lookup = {}
            for _, row in df.iterrows():
                key = (row['player_lookup'], row['game_id'])
                props_lookup[key] = {
                    'opening_line': row['opening_line'],
                    'opening_source': row['opening_source'],
                    'current_line': row['current_line'],
                    'current_source': row['current_source'],
                }

            # Populate prop_lines for each player_game pair
            for player_lookup, game_id in player_game_pairs:
                props = props_lookup.get((player_lookup, game_id), {})

                prop_info = {
                    'opening_line': props.get('opening_line'),
                    'opening_source': props.get('opening_source'),
                    'current_line': props.get('current_line'),
                    'current_source': props.get('current_source'),
                    'line_movement': None
                }

                if prop_info['opening_line'] and prop_info['current_line']:
                    prop_info['line_movement'] = prop_info['current_line'] - prop_info['opening_line']

                prop_lines[(player_lookup, game_id)] = prop_info

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error in batch prop lines query: {e}")
            # Fallback: set empty prop info for all players
            for player_lookup, game_id in player_game_pairs:
                prop_lines[(player_lookup, game_id)] = self._empty_prop_info()
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error in batch prop lines query: {e}")
            for player_lookup, game_id in player_game_pairs:
                prop_lines[(player_lookup, game_id)] = self._empty_prop_info()

        return prop_lines

    def extract_prop_lines_from_bettingpros(
        self,
        player_game_pairs: List[Tuple[str, str]],
        target_date: date
    ) -> Dict[Tuple[str, str], Dict]:
        """
        Extract prop lines from BettingPros as fallback.

        Args:
            player_game_pairs: List of (player_lookup, game_id) tuples
            target_date: Target game date

        Returns:
            Dict mapping (player_lookup, game_id) to prop info dict
        """
        prop_lines = {}

        # Batch query for efficiency - get all players at once
        player_lookups = list(set([p[0] for p in player_game_pairs]))

        batch_query = f"""
        WITH best_lines AS (
            SELECT
                player_lookup,
                points_line as current_line,
                opening_line,
                bookmaker,
                bookmaker_last_update,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY is_best_line DESC, bookmaker_last_update DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @game_date
              AND market_type = 'points'
              AND is_active = TRUE
        )
        SELECT
            player_lookup,
            current_line,
            opening_line,
            bookmaker
        FROM best_lines
        WHERE rn = 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", target_date),
            ]
        )

        try:
            df = self.bq_client.query(batch_query, job_config=job_config).to_dataframe()

            # Create lookup dict
            bp_props = {}
            for _, row in df.iterrows():
                bp_props[row['player_lookup']] = {
                    'current_line': row['current_line'],
                    'opening_line': row['opening_line'],
                    'bookmaker': row['bookmaker']
                }

            # Populate prop_lines for each player_game pair
            for player_lookup, game_id in player_game_pairs:
                bp_data = bp_props.get(player_lookup, {})

                opening_line = bp_data.get('opening_line')
                current_line = bp_data.get('current_line')
                bookmaker = bp_data.get('bookmaker')

                prop_info = {
                    'opening_line': opening_line,
                    'opening_source': bookmaker,
                    'current_line': current_line,
                    'current_source': bookmaker,
                    'line_movement': None
                }

                # Calculate line movement if both lines available
                if opening_line is not None and current_line is not None:
                    prop_info['line_movement'] = current_line - opening_line

                prop_lines[(player_lookup, game_id)] = prop_info

            logger.info(f"BettingPros: Extracted prop lines for {len(bp_props)} players")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting prop lines from BettingPros: {e}")
            for player_lookup, game_id in player_game_pairs:
                prop_lines[(player_lookup, game_id)] = self._empty_prop_info()
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting prop lines from BettingPros: {e}")
            for player_lookup, game_id in player_game_pairs:
                prop_lines[(player_lookup, game_id)] = self._empty_prop_info()

        return prop_lines

    def get_game_line_consensus(
        self,
        game_id: str,
        market_key: str,
        target_date: date,
        schedule_data: Dict[str, Dict]
    ) -> Dict:
        """
        Get consensus line (median across bookmakers) for a market.

        Args:
            game_id: Game identifier (standard format: YYYYMMDD_AWAY_HOME)
            market_key: 'spreads' or 'totals'
            target_date: Target game date
            schedule_data: Dict of game schedule info

        Returns:
            Dict with opening, current, movement, and source
        """
        # Extract teams from standard game_id format (YYYYMMDD_AWAY_HOME)
        # Or get from schedule_data if available
        if game_id in schedule_data:
            home_team = schedule_data[game_id].get('home_team_abbr')
            away_team = schedule_data[game_id].get('away_team_abbr')
        else:
            # Parse from game_id: format is YYYYMMDD_AWAY_HOME
            parts = game_id.split('_')
            if len(parts) == 3:
                away_team = parts[1]
                home_team = parts[2]
            else:
                logger.warning(f"Invalid game_id format: {game_id}, cannot extract teams")
                away_team = None
                home_team = None

        # Get opening line (earliest snapshot, median across bookmakers)
        opening_query = f"""
        WITH earliest_snapshot AS (
            SELECT MIN(snapshot_timestamp) as earliest
            FROM `{self.project_id}.nba_raw.odds_api_game_lines`
            WHERE game_date = @game_date
              AND home_team_abbr = @home_team
              AND away_team_abbr = @away_team
              AND market_key = @market_key
        ),
        opening_lines AS (
            SELECT
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN earliest_snapshot
            WHERE lines.game_date = @game_date
              AND lines.home_team_abbr = @home_team
              AND lines.away_team_abbr = @away_team
              AND lines.market_key = @market_key
              AND lines.snapshot_timestamp = earliest_snapshot.earliest
        ),
        median_calc AS (
            SELECT PERCENTILE_CONT(outcome_point, 0.5) OVER() as median_line
            FROM opening_lines
            LIMIT 1
        ),
        agg_calc AS (
            SELECT
                STRING_AGG(DISTINCT bookmaker_key) as bookmakers,
                COUNT(DISTINCT bookmaker_key) as bookmaker_count
            FROM opening_lines
        )
        SELECT
            median_calc.median_line,
            agg_calc.bookmakers,
            agg_calc.bookmaker_count
        FROM median_calc
        CROSS JOIN agg_calc
        """

        # Get current line (latest snapshot, median across bookmakers)
        current_query = f"""
        WITH latest_snapshot AS (
            SELECT MAX(snapshot_timestamp) as latest
            FROM `{self.project_id}.nba_raw.odds_api_game_lines`
            WHERE game_date = @game_date
              AND home_team_abbr = @home_team
              AND away_team_abbr = @away_team
              AND market_key = @market_key
        ),
        current_lines AS (
            SELECT
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN latest_snapshot
            WHERE lines.game_date = @game_date
              AND lines.home_team_abbr = @home_team
              AND lines.away_team_abbr = @away_team
              AND lines.market_key = @market_key
              AND lines.snapshot_timestamp = latest_snapshot.latest
        ),
        median_calc AS (
            SELECT PERCENTILE_CONT(outcome_point, 0.5) OVER() as median_line
            FROM current_lines
            LIMIT 1
        ),
        agg_calc AS (
            SELECT
                STRING_AGG(DISTINCT bookmaker_key) as bookmakers,
                COUNT(DISTINCT bookmaker_key) as bookmaker_count
            FROM current_lines
        )
        SELECT
            median_calc.median_line,
            agg_calc.bookmakers,
            agg_calc.bookmaker_count
        FROM median_calc
        CROSS JOIN agg_calc
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", target_date),
                bigquery.ScalarQueryParameter("home_team", "STRING", home_team),
                bigquery.ScalarQueryParameter("away_team", "STRING", away_team),
                bigquery.ScalarQueryParameter("market_key", "STRING", market_key),
            ]
        )

        try:
            opening_df = self.bq_client.query(opening_query, job_config=job_config).to_dataframe()
            current_df = self.bq_client.query(current_query, job_config=job_config).to_dataframe()

            prefix = 'spread' if market_key == 'spreads' else 'total'

            opening_line = opening_df['median_line'].iloc[0] if not opening_df.empty else None
            current_line = current_df['median_line'].iloc[0] if not current_df.empty else None

            result = {
                f'opening_{prefix}': opening_line,
                f'game_{prefix}': current_line,
                f'{prefix}_movement': (current_line - opening_line) if (opening_line and current_line) else None,
                f'{prefix}_source': current_df['bookmakers'].iloc[0] if not current_df.empty else None
            }

            return result

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error getting {market_key} consensus for {game_id}: {e}")
            prefix = 'spread' if market_key == 'spreads' else 'total'
            return self._empty_game_line(prefix)
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error getting {market_key} consensus for {game_id}: {e}")
            prefix = 'spread' if market_key == 'spreads' else 'total'
            return self._empty_game_line(prefix)

    def get_spread_public_betting_pct(self, game_id: str) -> Optional[float]:
        """
        Get the percentage of public bets on the spread favorite.

        TODO: Implement when public betting data source is available.

        Args:
            game_id: Game identifier

        Returns:
            Percentage (0-100) of public bets on the spread favorite,
            or None if data is not available.
        """
        return None

    def get_total_public_betting_pct(self, game_id: str) -> Optional[float]:
        """
        Get the percentage of public bets on the OVER for the game total.

        TODO: Implement when public betting data source is available.

        Args:
            game_id: Game identifier

        Returns:
            Percentage (0-100) of public bets on the OVER,
            or None if data is not available.
        """
        return None

    @staticmethod
    def _empty_prop_info() -> Dict:
        """Return empty prop info dict."""
        return {
            'opening_line': None,
            'opening_source': None,
            'current_line': None,
            'current_source': None,
            'line_movement': None
        }

    @staticmethod
    def _empty_game_line(prefix: str) -> Dict:
        """Return empty game line dict for given prefix."""
        return {
            f'opening_{prefix}': None,
            f'game_{prefix}': None,
            f'{prefix}_movement': None,
            f'{prefix}_source': None
        }
