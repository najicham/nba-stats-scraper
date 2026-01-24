# predictions/shared/injury_filter.py

"""
Injury Report Filter for Inference-Time Prediction Filtering

Checks player injury status before generating predictions to:
1. Skip predictions for players listed as OUT (prevents DNP errors)
2. Flag predictions for QUESTIONABLE/DOUBTFUL players (high uncertainty)
3. Pass through all other players normally
4. Calculate teammate injury impact for usage adjustments (v2.0)

Data Sources (v2.0):
- nba_raw.nbac_injury_report: NBA.com official injury reports (primary)
- nba_raw.bdl_injuries: Ball Don't Lie backup source (validation)

Based on analysis of 2024-25 season:
- 28.6% of DNPs (1,833) were catchable by checking OUT status
- 8.8% of DNPs (567) were QUESTIONABLE (flag but don't skip)
- 58.6% of DNPs had no injury report entry (late scratches, can't catch)

Usage:
    from predictions.shared.injury_filter import InjuryFilter

    filter = InjuryFilter()
    status = filter.check_player(player_lookup, game_date)

    if status.should_skip:
        # Don't generate prediction
    elif status.has_warning:
        # Generate prediction but flag uncertainty

    # v2.0: Get teammate impact for usage adjustments
    impact = filter.get_teammate_impact(player_lookup, team_abbr, game_date)
    if impact.has_significant_impact:
        adjusted_usage = base_usage * impact.usage_boost_factor
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Dict, List, Tuple
from google.cloud import bigquery
import logging

logger = logging.getLogger(__name__)


@dataclass
class InjuryStatus:
    """Result of injury check for a player"""
    player_lookup: str
    game_date: date
    injury_status: Optional[str]  # 'out', 'doubtful', 'questionable', 'probable', 'available', None
    reason: Optional[str]
    should_skip: bool  # True if prediction should be skipped
    has_warning: bool  # True if prediction should be flagged
    message: str  # Human-readable status message


class InjuryFilter:
    """
    Filter predictions based on injury report status

    Queries the injury report table to check player status before predictions.
    """

    # Status levels that should skip prediction entirely
    SKIP_STATUSES = {'out'}

    # Status levels that should flag uncertainty (but still predict)
    WARNING_STATUSES = {'doubtful', 'questionable'}

    def __init__(self, project_id: str = "nba-props-platform"):
        """
        Initialize injury filter

        Args:
            project_id: GCP project ID for BigQuery
        """
        self.project_id = project_id
        self._client = None
        self._cache: Dict[str, InjuryStatus] = {}  # Cache for batch operations

    @property
    def client(self) -> bigquery.Client:
        """Lazy-load BigQuery client"""
        if self._client is None:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def check_player(
        self,
        player_lookup: str,
        game_date: date
    ) -> InjuryStatus:
        """
        Check injury status for a single player

        Args:
            player_lookup: Player identifier (e.g., 'lebron-james')
            game_date: Date of the game

        Returns:
            InjuryStatus with skip/warning flags
        """
        cache_key = f"{player_lookup}_{game_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        query = """
        SELECT
            player_lookup,
            game_date,
            injury_status,
            reason
        FROM `nba-props-platform.nba_raw.nbac_injury_report`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY report_hour DESC
        ) = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = self.client.query(query, job_config=job_config).result()
            rows = list(result)

            if not rows:
                status = InjuryStatus(
                    player_lookup=player_lookup,
                    game_date=game_date,
                    injury_status=None,
                    reason=None,
                    should_skip=False,
                    has_warning=False,
                    message="OK: No injury report entry"
                )
            else:
                row = rows[0]
                injury_status = row.injury_status.lower() if row.injury_status else None

                should_skip = injury_status in self.SKIP_STATUSES
                has_warning = injury_status in self.WARNING_STATUSES

                if should_skip:
                    message = f"SKIP: Player listed as {injury_status.upper()}"
                elif has_warning:
                    message = f"WARNING: Player listed as {injury_status.upper()}"
                else:
                    message = f"OK: Player status is {injury_status or 'unknown'}"

                status = InjuryStatus(
                    player_lookup=player_lookup,
                    game_date=game_date,
                    injury_status=injury_status,
                    reason=row.reason,
                    should_skip=should_skip,
                    has_warning=has_warning,
                    message=message
                )

            self._cache[cache_key] = status
            return status

        except Exception as e:
            logger.error(f"Error checking injury status for {player_lookup}: {e}")
            # Fail-open: if we can't check, allow prediction
            return InjuryStatus(
                player_lookup=player_lookup,
                game_date=game_date,
                injury_status=None,
                reason=None,
                should_skip=False,
                has_warning=False,
                message=f"OK: Error checking injury status (fail-open): {e}"
            )

    def check_players_batch(
        self,
        player_lookups: List[str],
        game_date: date
    ) -> Dict[str, InjuryStatus]:
        """
        Check injury status for multiple players efficiently

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the game

        Returns:
            Dict mapping player_lookup to InjuryStatus
        """
        # Filter out already cached players
        uncached = [p for p in player_lookups if f"{p}_{game_date}" not in self._cache]

        if uncached:
            query = """
            SELECT
                player_lookup,
                game_date,
                injury_status,
                reason
            FROM `nba-props-platform.nba_raw.nbac_injury_report`
            WHERE game_date = @game_date
              AND player_lookup IN UNNEST(@player_lookups)
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY report_hour DESC
            ) = 1
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                    bigquery.ArrayQueryParameter("player_lookups", "STRING", uncached),
                ]
            )

            try:
                result = self.client.query(query, job_config=job_config).result()

                # Process results
                found_players = set()
                for row in result:
                    player = row.player_lookup
                    found_players.add(player)
                    injury_status = row.injury_status.lower() if row.injury_status else None

                    should_skip = injury_status in self.SKIP_STATUSES
                    has_warning = injury_status in self.WARNING_STATUSES

                    if should_skip:
                        message = f"SKIP: Player listed as {injury_status.upper()}"
                    elif has_warning:
                        message = f"WARNING: Player listed as {injury_status.upper()}"
                    else:
                        message = f"OK: Player status is {injury_status or 'unknown'}"

                    self._cache[f"{player}_{game_date}"] = InjuryStatus(
                        player_lookup=player,
                        game_date=game_date,
                        injury_status=injury_status,
                        reason=row.reason,
                        should_skip=should_skip,
                        has_warning=has_warning,
                        message=message
                    )

                # Players not in injury report
                for player in uncached:
                    if player not in found_players:
                        self._cache[f"{player}_{game_date}"] = InjuryStatus(
                            player_lookup=player,
                            game_date=game_date,
                            injury_status=None,
                            reason=None,
                            should_skip=False,
                            has_warning=False,
                            message="OK: No injury report entry"
                        )

            except Exception as e:
                logger.error(f"Error batch checking injury status: {e}")
                # Fail-open for all uncached players
                for player in uncached:
                    self._cache[f"{player}_{game_date}"] = InjuryStatus(
                        player_lookup=player,
                        game_date=game_date,
                        injury_status=None,
                        reason=None,
                        should_skip=False,
                        has_warning=False,
                        message=f"OK: Error checking (fail-open): {e}"
                    )

        # Return all requested players
        return {p: self._cache[f"{p}_{game_date}"] for p in player_lookups}

    def clear_cache(self):
        """Clear the internal cache"""
        self._cache.clear()

    def get_stats(self) -> Dict:
        """Get statistics about cached injury checks"""
        if not self._cache:
            return {"cached_checks": 0}

        statuses = list(self._cache.values())
        return {
            "cached_checks": len(statuses),
            "skip_count": sum(1 for s in statuses if s.should_skip),
            "warning_count": sum(1 for s in statuses if s.has_warning),
            "ok_count": sum(1 for s in statuses if not s.should_skip and not s.has_warning),
        }


# Singleton instance for convenience
_default_filter: Optional[InjuryFilter] = None


def get_injury_filter() -> InjuryFilter:
    """Get the default injury filter instance"""
    global _default_filter
    if _default_filter is None:
        _default_filter = InjuryFilter()
    return _default_filter


def check_injury_status(player_lookup: str, game_date: date) -> InjuryStatus:
    """
    Convenience function to check injury status

    Args:
        player_lookup: Player identifier
        game_date: Date of the game

    Returns:
        InjuryStatus with skip/warning flags
    """
    return get_injury_filter().check_player(player_lookup, game_date)
