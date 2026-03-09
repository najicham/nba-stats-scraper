"""
MLB Supplemental Data Loader

Loads umpire K-rate and weather data for game-day pitchers.
Provides supplemental_by_pitcher dict consumed by signals:
  - UmpireKFriendlySignal: sup.get('umpire_k_rate')
  - WeatherColdUnderSignal: sup.get('temperature')

Tables:
  - mlb_raw.mlb_umpire_assignments: game_pk → umpire_name (daily scrape)
  - mlb_raw.mlb_umpire_stats: umpire_name → k_zone_tendency (seasonal)
  - mlb_raw.mlb_weather: team_abbr → temperature_f (daily scrape)
  - mlb_raw.mlb_schedule: game_pk → teams + probable pitchers

Gracefully returns empty dict if tables have no data (pre-season).

Created: 2026-03-08 (Session 447)
"""

import logging
import os
from datetime import date
from typing import Dict, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# K-rate mapping from k_zone_tendency classification
# Based on MLB umpire data analysis — maps tendency to approximate K-rate
K_ZONE_TENDENCY_MAP = {
    'wide': 0.245,          # Wide zone → more called strikes → more Ks
    'above_average': 0.230,
    'average': 0.215,
    'below_average': 0.200,
    'tight': 0.190,         # Tight zone → fewer called strikes → fewer Ks
}
DEFAULT_K_RATE = 0.215  # League average fallback


def load_supplemental_by_pitcher(
    game_date: date,
    pitcher_lookups: Optional[list] = None,
    project_id: str = None,
) -> Dict[str, Dict]:
    """
    Load umpire K-rate and weather for all pitchers on a game date.

    Joins:
      schedule (game_pk, teams, pitchers)
      → umpire_assignments (game_pk → umpire_name)
      → umpire_stats (umpire_name → k_zone_tendency)
      → weather (team_abbr → temperature_f)

    Maps game-level data to pitcher-level via schedule's probable pitchers.

    Args:
        game_date: Target game date
        pitcher_lookups: Optional filter (None = all pitchers)
        project_id: GCP project ID

    Returns:
        Dict[pitcher_lookup, {umpire_k_rate, temperature, is_dome, k_weather_factor}]
        Empty dict if no data available.
    """
    proj_id = project_id or PROJECT_ID
    client = bigquery.Client(project=proj_id)

    result = {}

    # Load umpire data
    umpire_by_game = _load_umpire_k_rates(client, game_date, proj_id)

    # Load weather data
    weather_by_team = _load_weather(client, game_date, proj_id)

    # Load schedule to map game_pk → pitchers
    schedule = _load_schedule(client, game_date, proj_id)

    if not schedule:
        logger.info(f"[MLB Supplemental] No schedule data for {game_date}")
        return {}

    # Map game-level data to pitcher-level
    for game in schedule:
        game_pk = game['game_pk']
        home_team = game['home_team_abbr']

        # Get umpire K-rate for this game
        umpire_data = umpire_by_game.get(game_pk, {})
        umpire_k_rate = umpire_data.get('umpire_k_rate')

        # Get weather for home stadium
        weather_data = weather_by_team.get(home_team, {})
        temperature = weather_data.get('temperature_f')
        is_dome = weather_data.get('is_dome', False)
        k_weather_factor = weather_data.get('k_weather_factor')

        supplemental = {}
        if umpire_k_rate is not None:
            supplemental['umpire_k_rate'] = umpire_k_rate
        if temperature is not None:
            supplemental['temperature'] = temperature
        if is_dome is not None:
            supplemental['is_dome'] = is_dome
        if k_weather_factor is not None:
            supplemental['k_weather_factor'] = k_weather_factor

        if not supplemental:
            continue

        # Map to both home and away pitchers
        for pitcher_lookup in [game.get('home_pitcher_lookup'),
                               game.get('away_pitcher_lookup')]:
            if pitcher_lookup:
                if pitcher_lookups and pitcher_lookup not in pitcher_lookups:
                    continue
                result[pitcher_lookup] = supplemental.copy()

    n_with_umpire = sum(1 for v in result.values() if 'umpire_k_rate' in v)
    n_with_weather = sum(1 for v in result.values() if 'temperature' in v)
    logger.info(f"[MLB Supplemental] Loaded supplemental for {len(result)} pitchers "
                f"(umpire: {n_with_umpire}, weather: {n_with_weather})")

    return result


def _load_umpire_k_rates(
    client: bigquery.Client, game_date: date, project_id: str
) -> Dict[int, Dict]:
    """Load umpire K-rate by game_pk for a given date.

    Joins umpire_assignments (who's the umpire?) with umpire_stats
    (what's their K tendency?).

    Returns:
        Dict[game_pk, {umpire_name, umpire_k_rate}]
    """
    query = f"""
    SELECT
        ua.game_pk,
        ua.umpire_name,
        us.k_zone_tendency,
        us.accuracy
    FROM `{project_id}.mlb_raw.mlb_umpire_assignments` ua
    LEFT JOIN (
        SELECT umpire_name, k_zone_tendency, accuracy,
               ROW_NUMBER() OVER (
                   PARTITION BY umpire_name
                   ORDER BY scrape_date DESC
               ) as rn
        FROM `{project_id}.mlb_raw.mlb_umpire_stats`
        WHERE season = EXTRACT(YEAR FROM @game_date)
    ) us ON LOWER(ua.umpire_name) = LOWER(us.umpire_name) AND us.rn = 1
    WHERE ua.game_date = @game_date
    """

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        rows = client.query(query, job_config=job_config).result()

        result = {}
        for row in rows:
            tendency = row.get('k_zone_tendency')
            k_rate = K_ZONE_TENDENCY_MAP.get(
                tendency.lower() if tendency else '', DEFAULT_K_RATE
            )
            result[row['game_pk']] = {
                'umpire_name': row['umpire_name'],
                'umpire_k_rate': k_rate,
            }
        return result

    except Exception as e:
        logger.warning(f"[MLB Supplemental] Umpire data unavailable: {e}")
        return {}


def _load_weather(
    client: bigquery.Client, game_date: date, project_id: str
) -> Dict[str, Dict]:
    """Load weather by home team_abbr for a given date.

    Uses most recent scrape for the game date (weather scraped morning-of).

    Returns:
        Dict[team_abbr, {temperature_f, is_dome, k_weather_factor}]
    """
    query = f"""
    SELECT
        team_abbr,
        temperature_f,
        is_dome,
        k_weather_factor,
        humidity_pct,
        wind_speed_mph
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY team_abbr
                   ORDER BY created_at DESC
               ) as rn
        FROM `{project_id}.mlb_raw.mlb_weather`
        WHERE scrape_date = @game_date
    )
    WHERE rn = 1
    """

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        rows = client.query(query, job_config=job_config).result()

        result = {}
        for row in rows:
            result[row['team_abbr']] = {
                'temperature_f': row.get('temperature_f'),
                'is_dome': row.get('is_dome', False),
                'k_weather_factor': row.get('k_weather_factor'),
                'humidity_pct': row.get('humidity_pct'),
                'wind_speed_mph': row.get('wind_speed_mph'),
            }
        return result

    except Exception as e:
        logger.warning(f"[MLB Supplemental] Weather data unavailable: {e}")
        return {}


def _load_schedule(
    client: bigquery.Client, game_date: date, project_id: str
) -> list:
    """Load schedule with probable pitchers for a given date.

    Normalizes pitcher names to player_lookup format for matching.

    Returns:
        List[{game_pk, home_team_abbr, away_team_abbr,
              home_pitcher_lookup, away_pitcher_lookup}]
    """
    query = f"""
    SELECT
        game_pk,
        home_team_abbr,
        away_team_abbr,
        home_probable_pitcher_name,
        away_probable_pitcher_name,
        LOWER(REGEXP_REPLACE(
            NORMALIZE(home_probable_pitcher_name, NFD),
            r'[^a-zA-Z]', ''
        )) as home_pitcher_lookup,
        LOWER(REGEXP_REPLACE(
            NORMALIZE(away_probable_pitcher_name, NFD),
            r'[^a-zA-Z]', ''
        )) as away_pitcher_lookup
    FROM `{project_id}.mlb_raw.mlb_schedule`
    WHERE game_date = @game_date
      AND home_probable_pitcher_name IS NOT NULL
    """

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        rows = client.query(query, job_config=job_config).result()
        return [dict(row) for row in rows]

    except Exception as e:
        logger.warning(f"[MLB Supplemental] Schedule data unavailable: {e}")
        return []
