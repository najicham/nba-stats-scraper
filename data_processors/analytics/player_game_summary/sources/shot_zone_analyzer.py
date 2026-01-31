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
        # Track games that need BDB re-run (used fallback)
        self.games_needing_bdb: Dict[str, Dict] = {}  # game_id -> metadata

    def extract_shot_zones(self, start_date: str, end_date: str, game_ids: Optional[list] = None) -> None:
        """
        Extract shot zone data with BigDataBall → NBAC fallback.

        Attempts BigDataBall PBP first (primary source with coordinates),
        falls back to NBAC PBP if BigDataBall fails or returns no data.

        Gracefully handles missing play-by-play data.
        Tracks games that need BDB re-run when fallback is used.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            game_ids: Optional list of game IDs being processed (for tracking)
        """
        # Try BigDataBall first (primary source - has shot coordinates)
        bdb_failed = False
        try:
            result = self._extract_from_bigdataball(start_date, end_date)
            if result:
                self.shot_zones_available = True
                self.shot_zones_source = 'bigdataball_pbp'
                logger.info(f"✅ Using BigDataBall PBP for shot zones: {len(self.shot_zone_data)} player-games")
                return
            bdb_failed = True  # No data returned
        except Exception as e:
            bdb_failed = True
            logger.warning(f"⚠️ BigDataBall shot zone extraction failed: {e}")

        # Fallback to NBAC PBP
        try:
            result = self._extract_from_nbac(start_date, end_date)
            if result:
                self.shot_zones_available = True
                self.shot_zones_source = 'nbac_play_by_play'
                logger.info(f"✅ Using NBAC fallback for shot zones: {len(self.shot_zone_data)} player-games")

                # TRACK: Games need BDB re-run when it becomes available
                if bdb_failed:
                    self._track_games_needing_bdb(start_date, end_date, 'nbac_play_by_play', game_ids)
                    logger.warning(
                        f"⚠️ ALERT: BigDataBall unavailable, using NBAC fallback. "
                        f"Games marked for BDB re-run when data available."
                    )
                return
        except Exception as e:
            logger.warning(f"⚠️ NBAC shot zone extraction also failed: {e}")

        # Both failed - track for later
        self.shot_zones_available = False
        self.shot_zones_source = None
        logger.warning("⚠️ Shot zone extraction failed from both BigDataBall and NBAC sources")

        # TRACK: Games need BDB re-run (no data at all)
        self._track_games_needing_bdb(start_date, end_date, 'none', game_ids)

    def _track_games_needing_bdb(
        self,
        start_date: str,
        end_date: str,
        fallback_source: str,
        game_ids: Optional[list] = None
    ) -> None:
        """
        Track games that were processed without BigDataBall data.

        These games should be re-run when BDB data becomes available.

        Args:
            start_date: Start date
            end_date: End date
            fallback_source: What source was used ('nbac_play_by_play', 'none')
            game_ids: Optional specific game IDs
        """
        try:
            # If we have specific game_ids, use those
            if game_ids:
                for game_id in game_ids:
                    self.games_needing_bdb[game_id] = {
                        'game_date': start_date,
                        'fallback_source': fallback_source,
                        'detected_at': pd.Timestamp.now(tz='UTC').isoformat()
                    }
            else:
                # Query to find what games we're processing
                query = f"""
                SELECT DISTINCT game_id, home_team_tricode, away_team_tricode
                FROM `{self.project_id}.nba_raw.nbac_schedule`
                WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                """
                games_df = self.bq_client.query(query).to_dataframe()

                for _, row in games_df.iterrows():
                    self.games_needing_bdb[row['game_id']] = {
                        'game_date': start_date,
                        'home_team': row['home_team_tricode'],
                        'away_team': row['away_team_tricode'],
                        'fallback_source': fallback_source,
                        'detected_at': pd.Timestamp.now(tz='UTC').isoformat()
                    }

            logger.info(f"Tracked {len(self.games_needing_bdb)} games needing BDB re-run")

        except Exception as e:
            logger.warning(f"Failed to track games needing BDB: {e}")

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
                        # CRITICAL: Store three-point from PBP (not box score) for source consistency
                        'three_attempts_pbp': int(row['three_attempts_pbp']) if pd.notna(row['three_attempts_pbp']) else None,
                        'three_makes_pbp': int(row['three_makes_pbp']) if pd.notna(row['three_makes_pbp']) else None,
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
                COUNT(CASE WHEN zone = 'mid_range' AND shot_made = TRUE THEN 1 END) as mid_range_makes,
                -- Three-point zone (CRITICAL FIX: was missing from NBAC extraction!)
                COUNT(CASE WHEN zone = 'three' THEN 1 END) as three_attempts_pbp,
                COUNT(CASE WHEN zone = 'three' AND shot_made = TRUE THEN 1 END) as three_makes_pbp
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
                        # Three-point zone (CRITICAL FIX: now extracted from NBAC!)
                        'three_attempts_pbp': int(row['three_attempts_pbp']) if pd.notna(row['three_attempts_pbp']) else None,
                        'three_makes_pbp': int(row['three_makes_pbp']) if pd.notna(row['three_makes_pbp']) else None,
                        # NBAC doesn't have these fields - set to None
                        'assisted_fg_makes': None,
                        'unassisted_fg_makes': None,
                        'and1_count': None,
                        'paint_blocks': None,
                        'mid_range_blocks': None,
                        'three_pt_blocks': None,
                    }

                logger.debug(f"NBAC: Extracted {len(self.shot_zone_data)} player-games (all zones)")
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

        IMPORTANT: Validates zone completeness and logs warnings for partial data.
        Incomplete zone data can corrupt downstream rate calculations.

        Args:
            game_id: Game ID
            player_lookup: Player lookup string

        Returns:
            Dictionary with shot zone fields (all None if no data)
        """
        key = (game_id, player_lookup)
        zones = self.shot_zone_data.get(key, {})

        # Validate zone completeness (all three zones should have data or all should be None)
        paint_att = zones.get('paint_attempts')
        mid_att = zones.get('mid_range_attempts')
        # Note: three_pt comes from box score, not PBP, so we track PBP version separately
        three_att_pbp = zones.get('three_attempts_pbp')

        # Check for partial data that could corrupt rate calculations
        zone_values = [paint_att, mid_att, three_att_pbp]
        has_any = any(v is not None and v >= 0 for v in zone_values)
        has_all = all(v is not None for v in zone_values)

        if has_any and not has_all:
            missing_zones = []
            if paint_att is None:
                missing_zones.append('paint')
            if mid_att is None:
                missing_zones.append('mid_range')
            if three_att_pbp is None:
                missing_zones.append('three_pt')
            logger.warning(
                f"⚠️ Incomplete shot zone data for {game_id}/{player_lookup}: "
                f"missing {missing_zones} zones (source: {self.shot_zones_source}). "
                f"This can corrupt rate calculations!"
            )

        return {
            # Shot zones by location
            'paint_attempts': zones.get('paint_attempts'),
            'paint_makes': zones.get('paint_makes'),
            'mid_range_attempts': zones.get('mid_range_attempts'),
            'mid_range_makes': zones.get('mid_range_makes'),
            # CRITICAL: Return three-point from PBP (not box score) for source consistency
            'three_attempts_pbp': zones.get('three_attempts_pbp'),
            'three_makes_pbp': zones.get('three_makes_pbp'),
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

    def persist_pending_bdb_games(self) -> int:
        """
        Persist games that need BDB re-run to BigQuery.

        Called at the end of processing to record which games used fallback
        and should be re-run when BigDataBall data becomes available.

        Returns:
            Number of games persisted
        """
        if not self.games_needing_bdb:
            return 0

        try:
            records = []
            for game_id, metadata in self.games_needing_bdb.items():
                records.append({
                    'game_date': metadata.get('game_date'),
                    'game_id': game_id,
                    'home_team': metadata.get('home_team'),
                    'away_team': metadata.get('away_team'),
                    'fallback_source': metadata.get('fallback_source'),
                    'original_processed_at': pd.Timestamp.now(tz='UTC').isoformat(),
                    'status': 'pending_bdb',
                    'quality_before_rerun': 'silver' if metadata.get('fallback_source') == 'nbac_play_by_play' else 'bronze',
                    'shot_zones_complete_before': metadata.get('fallback_source') == 'nbac_play_by_play',
                    'bdb_check_count': 0,
                })

            # Use MERGE to avoid duplicates
            table_id = f"{self.project_id}.nba_orchestration.pending_bdb_games"

            # Check if table exists
            try:
                self.bq_client.get_table(table_id)
            except Exception:
                logger.warning(f"Table {table_id} doesn't exist - skipping pending BDB tracking")
                return 0

            # Insert records (MERGE would be better but INSERT works for now)
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
            )

            load_job = self.bq_client.load_table_from_json(
                records, table_id, job_config=job_config
            )
            load_job.result(timeout=60)

            logger.info(f"Persisted {len(records)} games to pending_bdb_games table")
            return len(records)

        except Exception as e:
            logger.error(f"Failed to persist pending BDB games: {e}")
            return 0
