"""expected_outputs_planner — materialize the date-grid contract.

For each sport, for each game_date in [history_start, today + lookahead_days],
ensures one row exists in `nba_orchestration.expected_outputs` per
(sport, date, phase, output_type) defined in OUTPUT_TYPE_REGISTRY.

Replaces ad-hoc completeness checks (data-completeness-checker 7d window,
scraper-gap-backfiller 14d window) which all silo by phase and miss historical
gaps. With this table seeded, gap_detector can fire on EXPECTED rows of any
age — including the Oct 2025 - Feb 2026 NBA gap that went 9 months unnoticed.

Status semantics:
  - New rows are written EXPECTED.
  - phase_completion_reconciler flips them to COMPLETE / EMPTY_OK / DEGRADED
    based on actuals.
  - gap_detector escalates stale EXPECTED rows to FAILED after attempts cap.

Triggered by Cloud Scheduler `expected-outputs-planner-nightly` at 4 AM ET
(before halt_state_writer at 5 AM, so today's row is fresh for downstream).

Created: 2026-05-09 (pipeline-state-redesign Phase C).
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import functions_framework
from flask import Request
from google.cloud import bigquery


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
EXPECTED_OUTPUTS_TABLE = f'{PROJECT_ID}.nba_orchestration.expected_outputs'

# Sport season anchors. Used to compute season label and skip out-of-window
# dates with EMPTY_OK rather than EXPECTED.
SEASON_WINDOWS = {
    'nba': {'start_month': 10, 'start_day': 1, 'end_month': 6, 'end_day': 30},
    'mlb': {'start_month': 3, 'start_day': 1, 'end_month': 11, 'end_day': 15},
}

# ---------------------------------------------------------------------------
# OUTPUT_TYPE_REGISTRY
#
# (sport, phase) -> list of (output_type, expected_partition_template, sla_hours)
#
# expected_partition_template is a Python format string:
#   {date} → game_date as YYYY-MM-DD
#
# sla_hours = how long after game_date the output is "due."
#   For pre-game outputs (lineups, projections) this is negative — they're
#   due before tipoff. For post-game outputs (gamebook, predictions
#   re-graded) it's hours after game start.
# ---------------------------------------------------------------------------

OUTPUT_TYPE_REGISTRY: Dict[Tuple[str, str], List[Tuple[str, str, int]]] = {

    # --- NBA: phase1 (scraper output to GCS) -----------------------------
    ('nba', 'phase1_scrape'): [
        ('nbac_gamebook_player_stats',  'gs://nba-scraped-data/nba-com/gamebooks-data/{date}/',  12),
        ('nbac_injury_report',          'gs://nba-scraped-data/nba-com/injury-report-data/{date}/', 6),
        ('nbac_play_by_play',           'gs://nba-scraped-data/nba-com/play-by-play/{date}/',     12),
        ('odds_api_player_points_props', 'gs://nba-scraped-data/odds-api/player-props/{date}/',   2),
        ('bettingpros_player_points_props', 'gs://nba-scraped-data/bettingpros/player-props/points/{date}/', 2),
    ],

    # --- NBA: phase2 (raw BQ tables) -------------------------------------
    ('nba', 'phase2_raw'): [
        ('nbac_gamebook_player_stats',      'nba-props-platform.nba_raw.nbac_gamebook_player_stats|game_date={date}', 14),
        ('nbac_injury_report',              'nba-props-platform.nba_raw.nbac_injury_report|game_date={date}', 8),
        ('nbac_play_by_play',               'nba-props-platform.nba_raw.nbac_play_by_play|game_date={date}', 14),
        ('odds_api_player_points_props',    'nba-props-platform.nba_raw.odds_api_player_points_props|game_date={date}', 4),
        ('bettingpros_player_points_props', 'nba-props-platform.nba_raw.bettingpros_player_points_props|game_date={date}', 4),
    ],

    # --- NBA: phase3 (analytics) -----------------------------------------
    ('nba', 'phase3_analytics'): [
        ('player_game_summary',        'nba-props-platform.nba_analytics.player_game_summary|game_date={date}', 16),
        ('team_offense_game_summary',  'nba-props-platform.nba_analytics.team_offense_game_summary|game_date={date}', 16),
        ('team_defense_game_summary',  'nba-props-platform.nba_analytics.team_defense_game_summary|game_date={date}', 16),
    ],

    # --- NBA: phase4 (precompute / feature store) ------------------------
    ('nba', 'phase4_precompute'): [
        ('ml_feature_store_v2',  'nba-props-platform.nba_predictions.ml_feature_store_v2|game_date={date}', 6),
    ],

    # --- NBA: phase5 (predictions) ---------------------------------------
    ('nba', 'phase5_predictions'): [
        ('player_prop_predictions',  'nba-props-platform.nba_predictions.player_prop_predictions|game_date={date}', 4),
    ],

    # --- NBA: phase6 (publishing — Phase 6 GCS JSON) ---------------------
    ('nba', 'phase6_publish'): [
        ('signal_best_bets_json', 'gs://nba-props-platform-api/v1/signal-best-bets/{date}.json',  3),
        ('picks_json',            'gs://nba-props-platform-api/v1/picks/{date}.json',             3),
        ('results_json',          'gs://nba-props-platform-api/v1/results/{date}.json',          24),
        ('signals_json',          'gs://nba-props-platform-api/v1/signals/{date}.json',           4),
        ('tonight_json',          'gs://nba-props-platform-api/v1/tonight/{date}.json',           2),
        ('live_grading_json',     'gs://nba-props-platform-api/v1/live-grading/{date}.json',      6),
    ],

    # --- MLB: phase1 (scraper output) ------------------------------------
    ('mlb', 'phase1_scrape'): [
        ('mlb_schedule',         'gs://nba-scraped-data/mlbstatsapi/schedule/{date}/', 6),
        ('mlb_box_scores',       'gs://nba-scraped-data/mlbstatsapi/boxscores/{date}/', 12),
        ('bp_mlb_player_props',  'gs://nba-scraped-data/bettingpros/mlb/player-props/{date}/', 4),
        ('mlb_lineups',          'gs://nba-scraped-data/mlb-stats-api/lineups/{date}/', 12),
    ],

    # --- MLB: phase6 (publishing) ----------------------------------------
    ('mlb', 'phase6_publish'): [
        ('mlb_signal_best_bets_json', 'gs://nba-props-platform-api/v1/mlb/signal-best-bets/{date}.json', 4),
        ('mlb_picks_json',            'gs://nba-props-platform-api/v1/mlb/picks/{date}.json',            4),
        ('mlb_tonight_json',          'gs://nba-props-platform-api/v1/mlb/tonight/{date}.json',          2),
    ],
}


# ---------------------------------------------------------------------------
# Historical-path overrides
#
# Some scrapers have a _his variant (e.g. oddsa_player_props_his) that writes
# to a DIFFERENT GCS prefix than the live scraper. For past dates the only
# recoverable source is the historical scraper, so the planner must register
# the historical prefix as expected_partition — otherwise the reconciler will
# never find actuals at the live path and rows stay EXPECTED forever, burning
# Odds API credits on every gap_detector cycle.
#
# Switch happens when game_date is older than HISTORICAL_PATH_AGE_THRESHOLD_DAYS.
# 7 days is the rule of thumb: the live odds-api/player-props/ prefix is
# overwritten by daily live scrapers for ~3 days, so anything older than that
# can only be recovered via the historical endpoint.
# ---------------------------------------------------------------------------

HISTORICAL_PATH_AGE_THRESHOLD_DAYS = 7

HISTORICAL_PATH_OVERRIDES: Dict[str, str] = {
    # Phase 1 GCS paths
    'odds_api_player_points_props': 'gs://nba-scraped-data/odds-api/player-props-history/{date}/',
    # `odds_api_game_lines` would belong here too if registered in Phase 1.
}


def _resolve_partition(output_type: str, partition_template: str, d: date, today: date) -> str:
    """Pick live vs. historical partition template based on game_date age."""
    if output_type in HISTORICAL_PATH_OVERRIDES and (today - d).days >= HISTORICAL_PATH_AGE_THRESHOLD_DAYS:
        return HISTORICAL_PATH_OVERRIDES[output_type].format(date=d.isoformat())
    return partition_template.format(date=d.isoformat())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_bq_client = None


def _get_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        try:
            from shared.clients.bigquery_pool import get_bigquery_client
            _bq_client = get_bigquery_client(project_id=PROJECT_ID)
        except Exception:
            _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _is_in_season_window(d: date, sport: str) -> bool:
    window = SEASON_WINDOWS[sport]
    start_md = (window['start_month'], window['start_day'])
    end_md = (window['end_month'], window['end_day'])
    today_md = (d.month, d.day)
    if start_md <= end_md:
        return start_md <= today_md <= end_md
    return today_md >= start_md or today_md <= end_md


def _compute_season_label(d: date, sport: str) -> str:
    """NBA: 2025-26 spans Oct 2025 - Jun 2026. MLB: 2026 = the calendar year."""
    if sport == 'nba':
        if d.month >= 10:
            return f"{d.year}-{str(d.year + 1)[-2:]}"
        return f"{d.year - 1}-{str(d.year)[-2:]}"
    return str(d.year)


def _compute_expected_by(game_date: date, sla_hours: int) -> datetime:
    """game_date midnight UTC + sla_hours."""
    base = datetime(game_date.year, game_date.month, game_date.day, tzinfo=timezone.utc)
    return base + timedelta(hours=sla_hours)


def _date_range(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


# ---------------------------------------------------------------------------
# Plan one date for one sport
# ---------------------------------------------------------------------------


def plan_date(bq: bigquery.Client, d: date, sport: str, today: Optional[date] = None) -> int:
    """MERGE expected_outputs rows for one (sport, date). Returns rows written.

    Idempotent: existing rows are NOT overwritten beyond expected_partition +
    expected_by + updated_at + source. A planner re-run never reverts a row's
    COMPLETE/EMPTY_OK status.

    `today` is used by `_resolve_partition` to decide live vs. historical
    prefix for output_types in HISTORICAL_PATH_OVERRIDES. Defaults to
    date.today() when called outside the HTTP handler.
    """
    in_window = _is_in_season_window(d, sport)
    season = _compute_season_label(d, sport)
    if today is None:
        today = date.today()

    rows = []
    for (rsport, phase), outputs in OUTPUT_TYPE_REGISTRY.items():
        if rsport != sport:
            continue
        for output_type, partition_template, sla_hours in outputs:
            partition = _resolve_partition(output_type, partition_template, d, today)
            expected_by = _compute_expected_by(d, sla_hours)
            # Out-of-window dates (e.g. NBA July) are EMPTY_OK from the start —
            # planner doesn't expect data, gap_detector won't fire.
            initial_status = 'EXPECTED' if in_window else 'EMPTY_OK'
            rows.append({
                'season': season,
                'game_date': d.isoformat(),
                'sport': sport,
                'phase': phase,
                'output_type': output_type,
                'expected_partition': partition,
                'expected_by': expected_by.isoformat(),
                'initial_status': initial_status,
            })

    if not rows:
        return 0

    # MERGE: insert if missing, update timestamps + source if present (don't
    # touch status — that's the reconciler's job).
    rows_json = json.dumps(rows)
    merge_sql = f"""
        MERGE `{EXPECTED_OUTPUTS_TABLE}` T
        USING (
          SELECT
            JSON_VALUE(r, '$.season') AS season,
            DATE(JSON_VALUE(r, '$.game_date')) AS game_date,
            JSON_VALUE(r, '$.sport') AS sport,
            JSON_VALUE(r, '$.phase') AS phase,
            JSON_VALUE(r, '$.output_type') AS output_type,
            JSON_VALUE(r, '$.expected_partition') AS expected_partition,
            TIMESTAMP(JSON_VALUE(r, '$.expected_by')) AS expected_by,
            JSON_VALUE(r, '$.initial_status') AS initial_status
          FROM UNNEST(JSON_QUERY_ARRAY(@rows)) AS r
        ) S
        ON T.sport = S.sport
           AND T.game_date = S.game_date
           AND T.phase = S.phase
           AND T.output_type = S.output_type
        WHEN MATCHED THEN UPDATE SET
          expected_partition = S.expected_partition,
          expected_by = S.expected_by,
          updated_at = CURRENT_TIMESTAMP(),
          source = 'planner_refresh'
        WHEN NOT MATCHED THEN INSERT (
          season, game_date, sport, phase, output_type,
          status, expected_partition, expected_by,
          attempts, created_at, updated_at, source
        )
        VALUES (
          S.season, S.game_date, S.sport, S.phase, S.output_type,
          S.initial_status, S.expected_partition, S.expected_by,
          0, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 'planner'
        )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('rows', 'STRING', rows_json)]
    )
    job = bq.query(merge_sql, job_config=job_config)
    job.result()
    return len(rows)


# ---------------------------------------------------------------------------
# HTTP entry point
# ---------------------------------------------------------------------------


@functions_framework.http
def expected_outputs_planner(request: Request):
    """Plan upcoming dates for both sports.

    Query params:
      target_date        — anchor date (default: today)
      lookahead_days     — days into the future to plan (default: 14)
      history_seed_date  — also plan from this date forward (default: skip;
                           used in Phase C bootstrap to seed 2025-26 season)
      sport              — 'nba' | 'mlb' | 'all' (default: 'all')
    """
    args = request.args or {}
    target_date_str = args.get('target_date')
    lookahead = int(args.get('lookahead_days', '14'))
    history_seed_str = args.get('history_seed_date')
    sport_arg = args.get('sport', 'all')

    today = (
        date.fromisoformat(target_date_str) if target_date_str else date.today()
    )
    end = today + timedelta(days=lookahead)
    if history_seed_str:
        start = date.fromisoformat(history_seed_str)
    else:
        start = today

    sports = ['nba', 'mlb'] if sport_arg == 'all' else [sport_arg]

    bq = _get_bq_client()
    summary: Dict[str, Any] = {
        'start': start.isoformat(),
        'end': end.isoformat(),
        'sports': sports,
        'rows_written': 0,
        'dates_planned': 0,
        'errors': [],
    }

    for d in _date_range(start, end):
        for sport in sports:
            try:
                n = plan_date(bq, d, sport, today=today)
                summary['rows_written'] += n
                summary['dates_planned'] += 1
            except Exception as e:
                msg = f"plan_date failed for {sport} {d.isoformat()}: {e}"
                logger.error(msg, exc_info=True)
                summary['errors'].append(msg)

    summary['written_at'] = datetime.now(timezone.utc).isoformat()
    logger.info(
        f"planner: {summary['rows_written']} rows merged across "
        f"{summary['dates_planned']} (date,sport) pairs"
    )
    return summary, 200


# Gen2 entrypoint alias
main = expected_outputs_planner
