"""
MLB Supplemental Data Loader

Loads umpire K-rate, weather, game context, and catcher framing data
for game-day pitchers.

Provides supplemental_by_pitcher dict consumed by signals:
  - UmpireKFriendlySignal: sup.get('umpire_k_rate')
  - WeatherColdUnderSignal: sup.get('temperature')
  - ColdWeatherKOverSignal: sup.get('temperature'), sup.get('is_dome')
  - GameTotalLowOverSignal: sup.get('game_total_line')
  - HeavyFavoriteOverSignal: sup.get('team_moneyline')
  - CatcherFramingOverSignal: sup.get('catcher_framing_runs')
  - CatcherFramingPoorUnderSignal: sup.get('catcher_framing_runs')

Tables:
  - mlb_raw.mlb_umpire_assignments: game_pk → umpire_name (daily scrape)
  - mlb_raw.mlb_umpire_stats: umpire_name → k_zone_tendency (seasonal)
  - mlb_raw.mlb_weather: team_abbr → temperature_f (daily scrape)
  - mlb_raw.mlb_schedule: game_pk → teams + probable pitchers
  - mlb_raw.oddsa_game_lines: game_pk → moneyline, game total (Session 460)
  - mlb_raw.catcher_framing: team_abbr → framing_runs (Session 465, weekly)

Gracefully returns empty dict if tables have no data (pre-season).

Created: 2026-03-08 (Session 447)
Updated: 2026-03-10 (Session 460) — game context: moneyline, game total
Updated: 2026-03-10 (Session 465) — catcher framing data
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

    # Load game context (moneyline, game total) — Session 460
    game_context_by_game = _load_game_context(client, game_date, proj_id)

    # Load catcher framing by team — Session 465
    framing_by_team = _load_catcher_framing(client, game_date, proj_id)

    # Load schedule to map game_pk → pitchers
    schedule = _load_schedule(client, game_date, proj_id)

    if not schedule:
        logger.info(f"[MLB Supplemental] No schedule data for {game_date}")
        return {}

    # Map game-level data to pitcher-level
    for game in schedule:
        game_pk = game['game_pk']
        home_team = game['home_team_abbr']
        away_team = game['away_team_abbr']

        # Get umpire K-rate for this game
        umpire_data = umpire_by_game.get(game_pk, {})
        umpire_k_rate = umpire_data.get('umpire_k_rate')

        # Get weather for home stadium
        weather_data = weather_by_team.get(home_team, {})
        temperature = weather_data.get('temperature_f')
        is_dome = weather_data.get('is_dome', False)
        k_weather_factor = weather_data.get('k_weather_factor')

        # Get game context (moneyline, game total) — Session 460
        game_ctx = game_context_by_game.get(game_pk, {})
        game_total = game_ctx.get('game_total_line')
        home_ml = game_ctx.get('home_moneyline')
        away_ml = game_ctx.get('away_moneyline')

        # Build per-pitcher supplemental (home vs away get different moneylines)
        for pitcher_key, is_home_pitcher in [
            ('home_pitcher_lookup', True),
            ('away_pitcher_lookup', False),
        ]:
            pitcher_lookup = game.get(pitcher_key)
            if not pitcher_lookup:
                continue
            if pitcher_lookups and pitcher_lookup not in pitcher_lookups:
                continue

            supplemental = {}
            if umpire_k_rate is not None:
                supplemental['umpire_k_rate'] = umpire_k_rate
            if temperature is not None:
                supplemental['temperature'] = temperature
            if is_dome is not None:
                supplemental['is_dome'] = is_dome
            if k_weather_factor is not None:
                supplemental['k_weather_factor'] = k_weather_factor
            # Game context — Session 460
            if game_total is not None:
                supplemental['game_total_line'] = game_total
            team_ml = home_ml if is_home_pitcher else away_ml
            if team_ml is not None:
                supplemental['team_moneyline'] = team_ml
            # Catcher framing — Session 465
            # Map pitcher's team → primary catcher framing runs
            pitcher_team = home_team if is_home_pitcher else away_team
            framing_data = framing_by_team.get(pitcher_team, {})
            if framing_data.get('framing_runs') is not None:
                supplemental['catcher_framing_runs'] = framing_data['framing_runs']
                supplemental['catcher_framing_runs_per_game'] = framing_data.get(
                    'framing_runs_per_game')

            if supplemental:
                result[pitcher_lookup] = supplemental

    n_with_umpire = sum(1 for v in result.values() if 'umpire_k_rate' in v)
    n_with_weather = sum(1 for v in result.values() if 'temperature' in v)
    n_with_context = sum(1 for v in result.values() if 'game_total_line' in v)
    n_with_framing = sum(1 for v in result.values() if 'catcher_framing_runs' in v)
    logger.info(f"[MLB Supplemental] Loaded supplemental for {len(result)} pitchers "
                f"(umpire: {n_with_umpire}, weather: {n_with_weather}, "
                f"game_ctx: {n_with_context}, framing: {n_with_framing})")

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


def _load_game_context(
    client: bigquery.Client, game_date: date, project_id: str
) -> Dict[int, Dict]:
    """Load game context (moneyline, game total) by game_pk.

    Session 460: Game total and moneyline provide game-script context
    for K prop signals. Low totals → deeper outings. Heavy favorites →
    starter stays in longer.

    Prioritizes DraftKings → FanDuel → any other book.

    Returns:
        Dict[game_pk, {game_total_line, home_moneyline, away_moneyline}]
    """
    query = f"""
    WITH ranked_lines AS (
        SELECT
            game_pk,
            total_line,
            home_moneyline,
            away_moneyline,
            bookmaker,
            ROW_NUMBER() OVER (
                PARTITION BY game_pk
                ORDER BY
                    CASE
                        WHEN bookmaker = 'draftkings' THEN 0
                        WHEN bookmaker = 'fanduel' THEN 1
                        WHEN bookmaker = 'betmgm' THEN 2
                        ELSE 3
                    END,
                    snapshot_time DESC
            ) as rn
        FROM `{project_id}.mlb_raw.oddsa_game_lines`
        WHERE game_date = @game_date
          AND total_line IS NOT NULL
    )
    SELECT game_pk, total_line, home_moneyline, away_moneyline
    FROM ranked_lines
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
            result[row['game_pk']] = {
                'game_total_line': row.get('total_line'),
                'home_moneyline': row.get('home_moneyline'),
                'away_moneyline': row.get('away_moneyline'),
            }
        return result

    except Exception as e:
        logger.warning(f"[MLB Supplemental] Game context unavailable: {e}")
        return {}


def _load_catcher_framing(
    client: bigquery.Client, game_date: date, project_id: str
) -> Dict[str, Dict]:
    """Load primary catcher framing data by team_abbr.

    Session 465: Maps team → primary catcher (most games) → framing metrics.
    Catcher framing data is scraped weekly; use most recent scrape for the
    current season.

    Returns:
        Dict[team_abbr, {framing_runs, framing_runs_per_game}]
    """
    season = game_date.year
    query = f"""
    WITH latest_scrape AS (
        SELECT MAX(scrape_date) as max_scrape
        FROM `{project_id}.mlb_raw.catcher_framing`
        WHERE season = @season
    ),
    primary_catchers AS (
        SELECT
            cf.team_abbr,
            cf.player_lookup,
            cf.framing_runs,
            cf.framing_runs_per_game,
            cf.games,
            ROW_NUMBER() OVER (
                PARTITION BY cf.team_abbr
                ORDER BY cf.games DESC
            ) as rn
        FROM `{project_id}.mlb_raw.catcher_framing` cf
        CROSS JOIN latest_scrape ls
        WHERE cf.scrape_date = ls.max_scrape
          AND cf.season = @season
    )
    SELECT team_abbr, player_lookup, framing_runs, framing_runs_per_game, games
    FROM primary_catchers
    WHERE rn = 1
    """

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("season", "INT64", season),
            ]
        )
        rows = client.query(query, job_config=job_config).result()

        result = {}
        for row in rows:
            result[row['team_abbr']] = {
                'framing_runs': row.get('framing_runs'),
                'framing_runs_per_game': row.get('framing_runs_per_game'),
            }
        return result

    except Exception as e:
        logger.warning(f"[MLB Supplemental] Catcher framing data unavailable: {e}")
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
