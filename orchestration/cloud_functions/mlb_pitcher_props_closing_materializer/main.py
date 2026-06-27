"""
MLB Pitcher Props Closing Materializer — Daily Cloud Function

Reads time-series snapshots from `mlb_raw.oddsa_pitcher_props` for a target date
and writes one "closing" row per (game_pk, player_lookup, bookmaker) into
`mlb_raw.pitcher_props_closing`.

"Closing" = latest snapshot within 180 min before first pitch. Rows where the
closest snapshot is > 30 min pre-game are flagged `is_synthetic=TRUE` so that
downstream CLV computation can exclude or weight them differently.

Schedule: 09:00 UTC daily (after all west-coast games finalize).
Trigger: HTTP (Cloud Scheduler). Optional body `{"target_date": "YYYY-MM-DD"}`;
defaults to yesterday in ET.

Idempotent: DELETEs existing rows for the target date before INSERT. Safe to re-run.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import functions_framework
from google.cloud import bigquery
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "nba-props-platform")
ET = ZoneInfo("America/New_York")

# Window for "closing" snapshots: from -180 min to game start.
# Snapshots within 30 min pre-game count as "true" closing; the rest as "synthetic".
LOOKBACK_MINUTES = 180
TRUE_CLOSING_MAX_MINUTES = 30


def _parse_target_date(request_json) -> str:
    """Return target_date as YYYY-MM-DD. Default: yesterday in ET."""
    if request_json and isinstance(request_json, dict):
        if request_json.get("target_date"):
            return str(request_json["target_date"])
    yesterday_et = datetime.now(ET) - timedelta(days=1)
    return yesterday_et.strftime("%Y-%m-%d")


def _materialize_query(target_date: str) -> str:
    """Build the SELECT-as-CTE that picks the closing snapshot per (game_pk, player_lookup, bookmaker).

    Logic:
      - Filter `oddsa_pitcher_props` to target_date, market_key='pitcher_strikeouts'
      - Restrict to snapshots within [-LOOKBACK_MINUTES, 0] relative to game_start_time
      - Pick the latest snapshot per (player_lookup, bookmaker) via ROW_NUMBER
      - Join `mlb_raw.mlb_schedule` to attach `game_pk` (LEFT JOIN on
        (game_date, home/away_team_abbr) — falls back to NULL when match fails)
    """
    return f"""
    WITH oddsa AS (
      SELECT
        opp.game_date,
        opp.event_id,
        opp.player_name,
        opp.player_lookup,
        opp.team_abbr,
        opp.home_team_abbr,
        opp.away_team_abbr,
        opp.bookmaker,
        opp.market_key,
        opp.point AS closing_line,
        opp.over_price AS closing_over_price,
        opp.under_price AS closing_under_price,
        opp.over_implied_prob AS closing_over_implied,
        opp.under_implied_prob AS closing_under_implied,
        opp.snapshot_time AS closing_snapshot_time,
        opp.game_start_time,
        opp.source_file_path AS source_snapshot_path,
        TIMESTAMP_DIFF(opp.game_start_time, opp.snapshot_time, MINUTE)
          AS minutes_before_first_pitch,
        ROW_NUMBER() OVER (
          PARTITION BY opp.player_lookup, opp.bookmaker
          ORDER BY opp.snapshot_time DESC
        ) AS rn
      FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props` opp
      WHERE opp.game_date = @target_date
        AND opp.market_key = 'pitcher_strikeouts'
        AND opp.point IS NOT NULL
        AND opp.snapshot_time IS NOT NULL
        AND opp.game_start_time IS NOT NULL
        AND opp.snapshot_time <= opp.game_start_time
        AND TIMESTAMP_DIFF(opp.game_start_time, opp.snapshot_time, MINUTE)
            <= {LOOKBACK_MINUTES}
    ),
    schedule AS (
      SELECT
        game_date,
        game_pk,
        home_team_abbr,
        away_team_abbr
      FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
      WHERE game_date = @target_date
    )
    SELECT
      o.game_date,
      s.game_pk,
      o.game_start_time,
      o.event_id,
      o.player_lookup,
      o.player_name,
      o.team_abbr,
      o.home_team_abbr,
      o.away_team_abbr,
      o.bookmaker,
      o.market_key,
      o.closing_line,
      o.closing_over_price,
      o.closing_under_price,
      o.closing_over_implied,
      o.closing_under_implied,
      o.closing_snapshot_time,
      o.minutes_before_first_pitch,
      o.minutes_before_first_pitch > {TRUE_CLOSING_MAX_MINUTES} AS is_synthetic,
      o.source_snapshot_path,
      CURRENT_TIMESTAMP() AS materialized_at
    FROM oddsa o
    LEFT JOIN schedule s
      ON s.game_date = o.game_date
      AND s.home_team_abbr = o.home_team_abbr
      AND s.away_team_abbr = o.away_team_abbr
    WHERE o.rn = 1
    """


def _delete_existing(client: bigquery.Client, target_date: str) -> int:
    """Idempotent: drop any rows already materialized for this date."""
    job = client.query(
        f"""
        DELETE FROM `{PROJECT_ID}.mlb_raw.pitcher_props_closing`
        WHERE game_date = @target_date
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            ]
        ),
    )
    job.result()
    return job.num_dml_affected_rows or 0


def _insert_closing(client: bigquery.Client, target_date: str) -> int:
    """Run the SELECT and INSERT in a single statement."""
    insert_sql = f"""
    INSERT INTO `{PROJECT_ID}.mlb_raw.pitcher_props_closing` (
      game_date, game_pk, game_start_time, event_id,
      player_lookup, player_name, team_abbr, home_team_abbr, away_team_abbr,
      bookmaker, market_key, closing_line,
      closing_over_price, closing_under_price,
      closing_over_implied, closing_under_implied,
      closing_snapshot_time, minutes_before_first_pitch, is_synthetic,
      source_snapshot_path, materialized_at
    )
    {_materialize_query(target_date)}
    """
    job = client.query(
        insert_sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            ]
        ),
    )
    job.result()
    return job.num_dml_affected_rows or 0


def _row_summary(client: bigquery.Client, target_date: str) -> dict:
    """Audit summary: counts by is_synthetic, distinct pitchers + bookmakers."""
    row = list(
        client.query(
            f"""
            SELECT
              COUNT(*) AS total_rows,
              COUNTIF(is_synthetic = FALSE) AS true_closing_rows,
              COUNTIF(is_synthetic = TRUE) AS synthetic_rows,
              COUNT(DISTINCT player_lookup) AS distinct_pitchers,
              COUNT(DISTINCT bookmaker) AS distinct_books,
              MIN(minutes_before_first_pitch) AS min_minutes_before,
              MAX(minutes_before_first_pitch) AS max_minutes_before
            FROM `{PROJECT_ID}.mlb_raw.pitcher_props_closing`
            WHERE game_date = @target_date
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
                ]
            ),
        ).result()
    )
    if not row:
        return {"total_rows": 0}
    r = row[0]
    return {
        "total_rows": int(r.total_rows or 0),
        "true_closing_rows": int(r.true_closing_rows or 0),
        "synthetic_rows": int(r.synthetic_rows or 0),
        "distinct_pitchers": int(r.distinct_pitchers or 0),
        "distinct_books": int(r.distinct_books or 0),
        "min_minutes_before": int(r.min_minutes_before) if r.min_minutes_before is not None else None,
        "max_minutes_before": int(r.max_minutes_before) if r.max_minutes_before is not None else None,
    }


@functions_framework.http
def materialize_pitcher_props_closing(request):
    """Daily entry point. Idempotent on target_date."""
    try:
        request_json = request.get_json(silent=True) if request else None
        target_date = _parse_target_date(request_json)
        logger.info("Materializing pitcher_props_closing for %s", target_date)

        client = bigquery.Client(project=PROJECT_ID)
        deleted = _delete_existing(client, target_date)
        inserted = _insert_closing(client, target_date)
        summary = _row_summary(client, target_date)

        response = {
            "status": "success",
            "target_date": target_date,
            "deleted_rows": int(deleted),
            "inserted_rows": int(inserted),
            "summary": summary,
        }
        logger.info("Materializer result: %s", json.dumps(response))
        return (json.dumps(response), 200, {"Content-Type": "application/json"})

    except Exception as exc:
        logger.exception("Materializer failed")
        return (
            json.dumps({"status": "error", "message": str(exc)}),
            500,
            {"Content-Type": "application/json"},
        )


# Gen2 entry-point alias — keeps the configured CF entry point stable even if
# the Python function name changes.
main = materialize_pitcher_props_closing
