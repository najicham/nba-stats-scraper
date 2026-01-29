"""
Shot Zone Analyzer for Player Game Summary

Extracts shot zone data from BigDataBall play-by-play with NBAC PBP fallback.

Extracted from: player_game_summary_processor.py::_extract_player_shot_zones()
"""

import logging
from typing import Dict, Tuple, Optional
import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class ShotZoneAnalyzer:
    """
    Analyze player shot zones from play-by-play data.

    Extracts per-player:
    - Shot attempts and makes by zone (paint, mid-range, three)
    - Assisted vs unassisted field goals
    - And-1 counts (made shot + shooting foul)
    - Blocks by zone (paint, mid-range, three) - tracks the BLOCKER

    Zone definitions:
    - Paint: shot_distance <= 8 feet
    - Mid-range: shot_distance > 8 AND NOT 3pt
    - Three-point: event_subtype contains '3pt' OR shot_distance >= 23.75
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize shot zone analyzer.

        Args:
            bq_client: BigQuery client
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.shot_zone_data: Dict[Tuple[str, str], Dict] = {}
        self.shot_zones_available: bool = False
        self.shot_zones_source: Optional[str] = None

    def extract_shot_zones(self, start_date: str, end_date: str) -> None:
        """
        Extract shot zone data with BigDataBall → NBAC fallback.

        Attempts BigDataBall PBP first (primary source with coordinates),
        falls back to NBAC PBP if BigDataBall fails or returns no data.

        Gracefully handles missing play-by-play data.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        """
        # Try BigDataBall first (primary source - has shot coordinates)
        try:
            result = self._extract_from_bigdataball(start_date, end_date)
            if result:
                self.shot_zones_available = True
                self.shot_zones_source = 'bigdataball_pbp'
                logger.info(f"✅ Using BigDataBall PBP for shot zones: {len(self.shot_zone_data)} player-games")
                return
        except Exception as e:
            logger.warning(f"⚠️ BigDataBall shot zone extraction failed: {e}")

        # Fallback to NBAC PBP
        try:
            result = self._extract_from_nbac(start_date, end_date)
            if result:
                self.shot_zones_available = True
                self.shot_zones_source = 'nbac_play_by_play'
                logger.info(f"✅ Using NBAC fallback for shot zones: {len(self.shot_zone_data)} player-games")
                return
        except Exception as e:
            logger.warning(f"⚠️ NBAC shot zone extraction also failed: {e}")

        # Both failed
        self.shot_zones_available = False
        self.shot_zones_source = None
        logger.warning("⚠️ Shot zone extraction failed from both BigDataBall and NBAC sources")

    def _extract_from_bigdataball(self, start_date: str, end_date: str) -> bool:
        """
        Extract shot zones from BigDataBall PBP (primary source, has coordinates).

        NOTE: NBA.com fallback handling
        When data_source = 'nbacom_fallback', the following fields are NULL:
        - away_player_1_lookup through away_player_5_lookup
        - home_player_1_lookup through home_player_5_lookup

        This query does NOT use lineup fields - it only uses action event fields
        (player_1_lookup, player_2_lookup, player_2_role) which ARE populated
        for NBA.com fallback data. No special handling needed for fallback.

        Returns:
            True if extraction succeeded and returned data, False otherwise
        """
        try:
            # Query BigDataBall play-by-play for player shot zones, shot creation, and blocks
            # NOTE: This query works correctly for both 'bigdataball' and 'nbacom_fallback'
            # data sources because it only uses action event fields, NOT lineup fields.
            query = f"""
            WITH player_shots AS (
                SELECT
                    game_id,
                    -- Strip player_id prefix (format changed in Oct 2024: "1630552jalenjohnson" -> "jalenjohnson")
                    REGEXP_REPLACE(player_1_lookup, r'^[0-9]+', '') as player_lookup,
                    -- Classify shot zone
                    CASE
                        WHEN shot_distance <= 8.0 THEN 'paint'
                        WHEN event_subtype LIKE '%3pt%' OR shot_distance >= 23.75 THEN 'three'
                        ELSE 'mid_range'
                    END as zone,
                    shot_made,
                    player_2_role,  -- 'assist' or 'block' or NULL
                    data_source  -- Track source for quality metadata
                FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
                WHERE event_type = 'shot'
                    AND shot_made IS NOT NULL
                    AND shot_distance IS NOT NULL
                    AND player_1_lookup IS NOT NULL
                    AND game_date BETWEEN '{start_date}' AND '{end_date}'
            ),
            -- And-1 counts from free throw 1/1 events (indicates made shot + foul)
            and1_events AS (
                SELECT
                    game_id,
                    REGEXP_REPLACE(player_1_lookup, r'^[0-9]+', '') as player_lookup,
                    COUNT(*) as and1_count
                FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
                WHERE event_type = 'free throw'
                    AND event_subtype = 'free throw 1/1'
                    AND player_1_lookup IS NOT NULL
                    AND game_date BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY game_id, player_1_lookup
            ),
            -- Block aggregates by zone - tracks the BLOCKER (player_2), not the shooter
            block_aggregates AS (
                SELECT
                    game_id,
                    REGEXP_REPLACE(player_2_lookup, r'^[0-9]+', '') as blocker_lookup,
                    COUNT(CASE WHEN zone = 'paint' THEN 1 END) as paint_blocks,
                    COUNT(CASE WHEN zone = 'mid_range' THEN 1 END) as mid_range_blocks,
                    COUNT(CASE WHEN zone = 'three' THEN 1 END) as three_pt_blocks
                FROM (
                    SELECT
                        game_id,
                        REGEXP_REPLACE(player_2_lookup, r'^[0-9]+', '') as player_2_lookup,
                        CASE
                            WHEN shot_distance <= 8.0 THEN 'paint'
                            WHEN event_subtype LIKE '%3pt%' OR shot_distance >= 23.75 THEN 'three'
                            ELSE 'mid_range'
                        END as zone
                    FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
                    WHERE event_type = 'shot'
                        AND player_2_role = 'block'
                        AND shot_distance IS NOT NULL
                        AND player_2_lookup IS NOT NULL
                        AND game_date BETWEEN '{start_date}' AND '{end_date}'
                )
                GROUP BY game_id, player_2_lookup
            ),
            shot_aggregates AS (
                SELECT
                    game_id,
                    player_lookup,
                    -- Paint zone
                    COUNT(CASE WHEN zone = 'paint' THEN 1 END) as paint_attempts,
                    COUNT(CASE WHEN zone = 'paint' AND shot_made = TRUE THEN 1 END) as paint_makes,
                    -- Mid-range zone
                    COUNT(CASE WHEN zone = 'mid_range' THEN 1 END) as mid_range_attempts,
                    COUNT(CASE WHEN zone = 'mid_range' AND shot_made = TRUE THEN 1 END) as mid_range_makes,
                    -- Three-point (for validation against box score)
                    COUNT(CASE WHEN zone = 'three' THEN 1 END) as three_attempts_pbp,
                    COUNT(CASE WHEN zone = 'three' AND shot_made = TRUE THEN 1 END) as three_makes_pbp,
                    -- Assisted vs unassisted field goals
                    -- NULL player_2_role is treated as unassisted (defensive for NBA.com fallback)
                    COUNT(CASE WHEN shot_made = TRUE AND player_2_role = 'assist' THEN 1 END) as assisted_fg_makes,
                    COUNT(CASE WHEN shot_made = TRUE AND COALESCE(player_2_role, '') NOT IN ('assist', 'block') THEN 1 END) as unassisted_fg_makes,
                    -- Track data source mix for quality monitoring
                    SUM(CASE WHEN data_source = 'nbacom_fallback' THEN 1 ELSE 0 END) as fallback_count,
                    COUNT(*) as total_events
                FROM player_shots
                GROUP BY game_id, player_lookup
            )
            SELECT
                s.game_id,
                s.player_lookup,
                s.paint_attempts,
                s.paint_makes,
                s.mid_range_attempts,
                s.mid_range_makes,
                s.three_attempts_pbp,
                s.three_makes_pbp,
                s.assisted_fg_makes,
                s.unassisted_fg_makes,
                COALESCE(a.and1_count, 0) as and1_count,
                b.paint_blocks,
                b.mid_range_blocks,
                b.three_pt_blocks,
                -- Data source quality indicator
                s.fallback_count,
                s.total_events
            FROM shot_aggregates s
            LEFT JOIN and1_events a ON s.game_id = a.game_id AND s.player_lookup = a.player_lookup
            LEFT JOIN block_aggregates b ON s.game_id = b.game_id AND s.player_lookup = b.blocker_lookup
            """

            shot_zones_df = self.bq_client.query(query).to_dataframe()

            if not shot_zones_df.empty:
                # Convert to dict keyed by (game_id, player_lookup)
                blocks_found = 0
                fallback_player_games = 0
                for _, row in shot_zones_df.iterrows():
                    key = (row['game_id'], row['player_lookup'])
                    self.shot_zone_data[key] = {
                        'paint_attempts': int(row['paint_attempts']) if pd.notna(row['paint_attempts']) else None,
                        'paint_makes': int(row['paint_makes']) if pd.notna(row['paint_makes']) else None,
                        'mid_range_attempts': int(row['mid_range_attempts']) if pd.notna(row['mid_range_attempts']) else None,
                        'mid_range_makes': int(row['mid_range_makes']) if pd.notna(row['mid_range_makes']) else None,
                        'assisted_fg_makes': int(row['assisted_fg_makes']) if pd.notna(row['assisted_fg_makes']) else None,
                        'unassisted_fg_makes': int(row['unassisted_fg_makes']) if pd.notna(row['unassisted_fg_makes']) else None,
                        'and1_count': int(row['and1_count']) if pd.notna(row['and1_count']) else None,
                        # Block tracking by zone (tracks the BLOCKER)
                        'paint_blocks': int(row['paint_blocks']) if pd.notna(row['paint_blocks']) else None,
                        'mid_range_blocks': int(row['mid_range_blocks']) if pd.notna(row['mid_range_blocks']) else None,
                        'three_pt_blocks': int(row['three_pt_blocks']) if pd.notna(row['three_pt_blocks']) else None,
                    }
                    # Count players with any blocks
                    if pd.notna(row['paint_blocks']) or pd.notna(row['mid_range_blocks']) or pd.notna(row['three_pt_blocks']):
                        blocks_found += 1
                    # Track NBA.com fallback usage
                    fallback_count = int(row.get('fallback_count', 0) or 0)
                    if fallback_count > 0:
                        fallback_player_games += 1

                # Log if any fallback data detected
                if fallback_player_games > 0:
                    logger.warning(
                        f"BigDataBall: {fallback_player_games}/{len(self.shot_zone_data)} player-games "
                        f"contain NBA.com fallback data (lineup fields are NULL for those records)"
                    )

                logger.debug(f"BigDataBall: Extracted {len(self.shot_zone_data)} player-games, {blocks_found} with blocks")
                return True
            else:
                logger.debug("BigDataBall query returned no shot zones")
                return False

        except Exception as e:
            logger.debug(f"BigDataBall extraction failed: {e}")
            return False

    def _extract_from_nbac(self, start_date: str, end_date: str) -> bool:
        """
        Extract shot zones from NBAC PBP (fallback source, simpler structure).

        NBAC PBP uses:
        - event_type = 'fieldgoal' (vs BigDataBall's 'shot')
        - shot_type = '2PT'/'3PT' (vs BigDataBall's event_subtype)
        - No player_2_role, so no assisted/unassisted tracking
        - No blocks tracking

        Returns:
            True if extraction succeeded and returned data, False otherwise
        """
        try:
            # Query NBAC play-by-play for basic shot zones only
            # (no assisted/unassisted, no and1s, no blocks - those require richer data)
            query = f"""
            WITH player_shots AS (
                SELECT
                    game_id,
                    -- NBAC uses different player ID format, extract player name/lookup
                    LOWER(REGEXP_REPLACE(COALESCE(player_name, player_id), r'[^a-z]', '')) as player_lookup,
                    -- Classify shot zone (NBAC has shot_type and shot_distance)
                    CASE
                        WHEN shot_type = '2PT' AND shot_distance <= 8.0 THEN 'paint'
                        WHEN shot_type = '2PT' AND shot_distance > 8.0 THEN 'mid_range'
                        WHEN shot_type = '3PT' THEN 'three'
                        ELSE NULL
                    END as zone,
                    shot_made
                FROM `{self.project_id}.nba_raw.nbac_play_by_play`
                WHERE event_type = 'fieldgoal'
                    AND shot_made IS NOT NULL
                    AND shot_distance IS NOT NULL
                    AND game_date BETWEEN '{start_date}' AND '{end_date}'
            )
            SELECT
                game_id,
                player_lookup,
                -- Paint zone
                COUNT(CASE WHEN zone = 'paint' THEN 1 END) as paint_attempts,
                COUNT(CASE WHEN zone = 'paint' AND shot_made = TRUE THEN 1 END) as paint_makes,
                -- Mid-range zone
                COUNT(CASE WHEN zone = 'mid_range' THEN 1 END) as mid_range_attempts,
                COUNT(CASE WHEN zone = 'mid_range' AND shot_made = TRUE THEN 1 END) as mid_range_makes
            FROM player_shots
            WHERE player_lookup IS NOT NULL
            GROUP BY game_id, player_lookup
            """

            shot_zones_df = self.bq_client.query(query).to_dataframe()

            if not shot_zones_df.empty:
                # Convert to dict keyed by (game_id, player_lookup)
                for _, row in shot_zones_df.iterrows():
                    key = (row['game_id'], row['player_lookup'])
                    self.shot_zone_data[key] = {
                        'paint_attempts': int(row['paint_attempts']) if pd.notna(row['paint_attempts']) else None,
                        'paint_makes': int(row['paint_makes']) if pd.notna(row['paint_makes']) else None,
                        'mid_range_attempts': int(row['mid_range_attempts']) if pd.notna(row['mid_range_attempts']) else None,
                        'mid_range_makes': int(row['mid_range_makes']) if pd.notna(row['mid_range_makes']) else None,
                        # NBAC doesn't have these fields - set to None
                        'assisted_fg_makes': None,
                        'unassisted_fg_makes': None,
                        'and1_count': None,
                        'paint_blocks': None,
                        'mid_range_blocks': None,
                        'three_pt_blocks': None,
                    }

                logger.debug(f"NBAC: Extracted {len(self.shot_zone_data)} player-games (basic zones only)")
                return True
            else:
                logger.debug("NBAC query returned no shot zones")
                return False

        except Exception as e:
            logger.debug(f"NBAC extraction failed: {e}")
            return False

    def get_shot_zone_data(self, game_id: str, player_lookup: str) -> Dict:
        """
        Get shot zone data for a specific player-game.

        Returns dict with all shot zone fields, using None for missing data.
        This allows using **analyzer.get_shot_zone_data() in record building.

        Args:
            game_id: Game ID
            player_lookup: Player lookup string

        Returns:
            Dictionary with shot zone fields (all None if no data)
        """
        key = (game_id, player_lookup)
        zones = self.shot_zone_data.get(key, {})

        return {
            # Shot zones by location
            'paint_attempts': zones.get('paint_attempts'),
            'paint_makes': zones.get('paint_makes'),
            'mid_range_attempts': zones.get('mid_range_attempts'),
            'mid_range_makes': zones.get('mid_range_makes'),
            # Shot creation (assisted vs self-created)
            'assisted_fg_makes': zones.get('assisted_fg_makes'),
            'unassisted_fg_makes': zones.get('unassisted_fg_makes'),
            # And-1 (made shot + shooting foul)
            'and1_count': zones.get('and1_count'),
            # Blocks by zone (BLOCKER perspective)
            'paint_blocks': zones.get('paint_blocks'),
            'mid_range_blocks': zones.get('mid_range_blocks'),
            'three_pt_blocks': zones.get('three_pt_blocks'),
        }
