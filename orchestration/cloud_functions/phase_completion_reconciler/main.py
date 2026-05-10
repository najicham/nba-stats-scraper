"""phase_completion_reconciler — flip EXPECTED rows to COMPLETE/EMPTY_OK/DEGRADED.

Reads the EXPECTED rows from `nba_orchestration.expected_outputs`, queries the
actual data partitions / GCS objects, and updates status accordingly.

Status transitions (this CF only writes these — gap_detector handles FAILED):
    EXPECTED  → COMPLETE       row_count > 0
    EXPECTED  → EMPTY_OK       row_count == 0 AND (halt_active OR no_games_today)
    EXPECTED  → EXPECTED       row_count == 0 AND games scheduled (attempts+=1, last_run_at)
    EXPECTED  → DEGRADED       row_count == 0 AND attempts >= 3 AND games scheduled

Triggered by Cloud Scheduler `phase-completion-reconciler-30min` every 30 min.
Idempotent — re-runs are safe.

Created: 2026-05-09 (pipeline-state-redesign Phase D).
"""

import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import functions_framework
from flask import Request
from google.cloud import bigquery, storage


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
EXPECTED_OUTPUTS_TABLE = f'{PROJECT_ID}.nba_orchestration.expected_outputs'
HALT_STATE_TABLE = f'{PROJECT_ID}.nba_orchestration.halt_state'

# How many EXPECTED rows to reconcile per invocation (cap to control cost).
DEFAULT_BATCH_SIZE = 500

# Attempts past which a stuck EXPECTED row escalates to DEGRADED.
DEGRADED_ATTEMPT_THRESHOLD = 3

_bq_client = None
_gcs_client = None


def _get_bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        try:
            from shared.clients.bigquery_pool import get_bigquery_client
            _bq_client = get_bigquery_client(project_id=PROJECT_ID)
        except Exception:
            _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _get_gcs() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client(project=PROJECT_ID)
    return _gcs_client


# ---------------------------------------------------------------------------
# Row parsing — expected_partition format encodes "where to look for actuals"
# ---------------------------------------------------------------------------


def _parse_partition(expected_partition: str) -> Dict[str, str]:
    """Parse expected_partition string into a structured locator.

    Two formats:
      BQ partition:
          'nba-props-platform.nba_raw.nbac_gamebook_player_stats|game_date=2026-04-15'
      GCS path:
          'gs://nba-scraped-data/nba-com/gamebooks-data/2026-04-15/'
          'gs://nba-props-platform-api/v1/signal-best-bets/2026-04-15.json'
    """
    if expected_partition.startswith('gs://'):
        return {'kind': 'gcs', 'path': expected_partition}
    # BQ format: <table>|<predicate>
    if '|' in expected_partition:
        table, predicate = expected_partition.split('|', 1)
        return {'kind': 'bq', 'table': table, 'predicate': predicate}
    return {'kind': 'unknown', 'raw': expected_partition}


# ---------------------------------------------------------------------------
# Actuals lookups
# ---------------------------------------------------------------------------


def check_bq_partition(
    bq: bigquery.Client,
    table: str,
    predicate: str,
) -> Tuple[Optional[int], Optional[str]]:
    """Returns (row_count, error). Cheap COUNT(*) with the predicate's filter."""
    # predicate is e.g. 'game_date=2026-04-15'. We embed it directly. The
    # writer (planner) constructs this; not user input. We add quoting for DATE.
    if '=' in predicate:
        col, val = predicate.split('=', 1)
        # Quote DATE values; INT/STRING values are written by us so are safe.
        if val and not val.startswith("'"):
            val_q = f"DATE '{val}'"
        else:
            val_q = val
        where_clause = f"{col} = {val_q}"
    else:
        where_clause = predicate

    query = f"SELECT COUNT(*) AS row_count FROM `{table}` WHERE {where_clause}"
    try:
        rows = list(bq.query(query).result(timeout=30))
        return (int(rows[0].row_count) if rows else 0, None)
    except Exception as e:
        return (None, str(e)[:200])


def check_gcs_path(gcs: storage.Client, path: str) -> Tuple[Optional[int], Optional[str]]:
    """Returns (row_count_or_object_count, error). For a directory path,
    counts blobs; for a single file path, returns 1 if exists else 0."""
    try:
        # Strip gs:// and split bucket/prefix
        path_no_scheme = path[5:]
        bucket_name, _, prefix = path_no_scheme.partition('/')
        bucket = gcs.bucket(bucket_name)
        if path.endswith('/'):
            # Directory — count non-zero-byte objects under the prefix
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=100))
            present = sum(1 for b in blobs if (b.size or 0) > 0)
            return (present, None)
        # Single file — exists + non-zero size
        blob = bucket.blob(prefix)
        if not blob.exists():
            return (0, None)
        blob.reload()
        return (1 if (blob.size or 0) > 0 else 0, None)
    except Exception as e:
        return (None, str(e)[:200])


# ---------------------------------------------------------------------------
# Halt + schedule context (decides EMPTY_OK vs DEGRADED for zero-row outputs)
# ---------------------------------------------------------------------------


def _halt_dates(bq: bigquery.Client, dates: List[date]) -> Dict[Tuple[str, date], bool]:
    """Returns {(sport, date): halt_active} for the dates we're reconciling."""
    if not dates:
        return {}
    rows = bq.query(
        f"""
        SELECT effective_date, sport, halt_active
        FROM `{HALT_STATE_TABLE}`
        WHERE effective_date IN UNNEST(@dates)
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter('dates', 'DATE', dates)]
        ),
    ).result(timeout=30)
    return {(r.sport, r.effective_date): bool(r.halt_active) for r in rows}


def _games_scheduled(bq: bigquery.Client, dates: List[date]) -> Dict[Tuple[str, date], int]:
    """Returns {(sport, date): num_games}. Heuristic: EMPTY_OK is fine when 0."""
    if not dates:
        return {}
    out: Dict[Tuple[str, date], int] = {}
    # NBA
    try:
        rows = bq.query(
            f"""
            SELECT game_date, COUNT(*) AS n
            FROM `{PROJECT_ID}.nba_reference.nba_schedule`
            WHERE game_date IN UNNEST(@dates)
            GROUP BY game_date
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ArrayQueryParameter('dates', 'DATE', dates)]
            ),
        ).result(timeout=30)
        for r in rows:
            out[('nba', r.game_date)] = int(r.n)
    except Exception as e:
        logger.warning(f"nba_schedule lookup failed (non-fatal): {e}")
    # MLB
    try:
        rows = bq.query(
            f"""
            SELECT game_date, COUNT(*) AS n
            FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
            WHERE game_date IN UNNEST(@dates)
            GROUP BY game_date
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ArrayQueryParameter('dates', 'DATE', dates)]
            ),
        ).result(timeout=30)
        for r in rows:
            out[('mlb', r.game_date)] = int(r.n)
    except Exception as e:
        logger.warning(f"mlb_schedule lookup failed (non-fatal): {e}")

    # Default to 0 for missing entries
    for d in dates:
        out.setdefault(('nba', d), 0)
        out.setdefault(('mlb', d), 0)
    return out


# ---------------------------------------------------------------------------
# Decision: row_count + halt + games → new_status
# ---------------------------------------------------------------------------


def decide_status(
    row_count: Optional[int],
    error: Optional[str],
    attempts: int,
    halt_active: bool,
    has_games: bool,
) -> Tuple[str, int]:
    """Return (new_status, attempts_increment). Pure function.

    Reconciler is the OBSERVER. It does not bump attempts; the subscriber
    is the canonical writer of attempts. Returned attempts_increment is
    always 0; signature kept for backward-compat with the batch updater.
    """
    if error is not None:
        # Couldn't even read the actual — leave as-is.
        return ('EXPECTED', 0)
    if row_count is None or row_count <= 0:
        # No actuals.
        if halt_active or not has_games:
            return ('EMPTY_OK', 0)
        # Games scheduled but no data — keep status unchanged; let the
        # gap_detector → subscriber loop drive attempts.
        if attempts >= DEGRADED_ATTEMPT_THRESHOLD:
            return ('DEGRADED', 0)
        return ('EXPECTED', 0)
    return ('COMPLETE', 0)


# ---------------------------------------------------------------------------
# Reconcile a batch
# ---------------------------------------------------------------------------


def reconcile_batch(bq: bigquery.Client, gcs: storage.Client, batch_size: int) -> Dict[str, int]:
    """Reconcile up to batch_size EXPECTED + DEGRADED rows whose expected_by
    has passed.

    Strategy:
      1. Pull EXPECTED *and* DEGRADED rows ordered by expected_by ASC.
         Including DEGRADED ensures that a row whose subscriber-driven
         backfill later succeeds gets flipped to COMPLETE rather than stuck
         (pre-fix, reconciler only read EXPECTED and DEGRADED rows could
         never recover).
      2. Lookup halt + schedule for the unique (sport, date) pairs.
      3. For each row, query actual partition.
      4. UPDATE each row's status, row_count, last_run_at. Reconciler does
         NOT bump attempts — the subscriber is the canonical writer of
         attempts (one increment per real backfill attempt).

    Returns counts of resulting statuses for telemetry.
    """
    select_query = f"""
        SELECT season, game_date, sport, phase, output_type,
               expected_partition, attempts
        FROM `{EXPECTED_OUTPUTS_TABLE}`
        WHERE status IN ('EXPECTED', 'DEGRADED')
          AND expected_by < CURRENT_TIMESTAMP()
        ORDER BY expected_by ASC
        LIMIT @batch_size
    """
    select_job = bq.query(
        select_query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter('batch_size', 'INT64', batch_size)]
        ),
    )
    rows = list(select_job.result(timeout=60))
    if not rows:
        return {'reconciled': 0}

    unique_dates = sorted({r.game_date for r in rows})
    halt_lookup = _halt_dates(bq, unique_dates)
    games_lookup = _games_scheduled(bq, unique_dates)

    counts: Dict[str, int] = defaultdict(int)
    updates: List[Dict[str, Any]] = []

    # Try to import the metrics emitter; non-fatal if missing.
    try:
        from shared.observability.metrics import emit_phase_completion
    except Exception:
        emit_phase_completion = None  # type: ignore

    for r in rows:
        loc = _parse_partition(r.expected_partition)
        if loc['kind'] == 'bq':
            row_count, err = check_bq_partition(bq, loc['table'], loc['predicate'])
        elif loc['kind'] == 'gcs':
            row_count, err = check_gcs_path(gcs, loc['path'])
        else:
            row_count, err = (None, f"unknown_partition_kind: {loc.get('raw')}")

        halt_active = halt_lookup.get((r.sport, r.game_date), False)
        has_games = games_lookup.get((r.sport, r.game_date), 0) > 0
        new_status, attempt_inc = decide_status(
            row_count=row_count,
            error=err,
            attempts=int(r.attempts or 0),
            halt_active=halt_active,
            has_games=has_games,
        )
        counts[new_status] += 1

        updates.append({
            'season': r.season,
            'game_date': r.game_date.isoformat(),
            'sport': r.sport,
            'phase': r.phase,
            'output_type': r.output_type,
            'new_status': new_status,
            'row_count': row_count,
            'attempt_inc': attempt_inc,
            'last_error': err,
        })

        if emit_phase_completion is not None:
            try:
                emit_phase_completion(
                    phase=r.phase, output_type=r.output_type,
                    status=new_status, sport=r.sport, row_count=row_count,
                )
            except Exception as e:
                logger.warning(f"emit_phase_completion failed (non-fatal): {e}")

    # Batch UPDATE via MERGE on a values-table.
    # Build a values-clause string. updates fan-in is limited by batch_size.
    if not updates:
        return dict(counts)

    values_clauses = []
    params = []
    for i, u in enumerate(updates):
        values_clauses.append(
            f"(@gd_{i}, @sp_{i}, @ph_{i}, @ot_{i}, @ns_{i}, @rc_{i}, @ai_{i}, @le_{i})"
        )
        params.extend([
            bigquery.ScalarQueryParameter(f'gd_{i}', 'DATE', u['game_date']),
            bigquery.ScalarQueryParameter(f'sp_{i}', 'STRING', u['sport']),
            bigquery.ScalarQueryParameter(f'ph_{i}', 'STRING', u['phase']),
            bigquery.ScalarQueryParameter(f'ot_{i}', 'STRING', u['output_type']),
            bigquery.ScalarQueryParameter(f'ns_{i}', 'STRING', u['new_status']),
            bigquery.ScalarQueryParameter(f'rc_{i}', 'INT64', u['row_count']),
            bigquery.ScalarQueryParameter(f'ai_{i}', 'INT64', u['attempt_inc']),
            bigquery.ScalarQueryParameter(f'le_{i}', 'STRING', u['last_error']),
        ])

    update_sql = f"""
        MERGE `{EXPECTED_OUTPUTS_TABLE}` T
        USING (
          SELECT * FROM UNNEST([
            STRUCT<
              game_date DATE,
              sport STRING,
              phase STRING,
              output_type STRING,
              new_status STRING,
              row_count INT64,
              attempt_inc INT64,
              last_error STRING
            >
            {', '.join(values_clauses)}
          ]) AS s
        ) S
        ON T.game_date = S.game_date
           AND T.sport = S.sport
           AND T.phase = S.phase
           AND T.output_type = S.output_type
        WHEN MATCHED THEN UPDATE SET
          status = S.new_status,
          row_count = S.row_count,
          attempts = T.attempts + S.attempt_inc,
          last_run_at = CURRENT_TIMESTAMP(),
          last_error = S.last_error,
          updated_at = CURRENT_TIMESTAMP(),
          source = 'reconciler'
    """
    bq.query(update_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()

    counts['reconciled'] = len(updates)
    return dict(counts)


# ---------------------------------------------------------------------------
# HTTP entry point
# ---------------------------------------------------------------------------


@functions_framework.http
def phase_completion_reconciler(request: Request):
    """Reconcile a batch of EXPECTED rows.

    Query params:
      batch_size — max rows per invocation (default 500)
    """
    args = request.args or {}
    batch_size = int(args.get('batch_size', str(DEFAULT_BATCH_SIZE)))

    bq = _get_bq()
    gcs = _get_gcs()

    counts = reconcile_batch(bq, gcs, batch_size)
    counts['written_at'] = datetime.now(timezone.utc).isoformat()
    logger.info(f"reconciler: {counts}")
    return counts, 200


main = phase_completion_reconciler
