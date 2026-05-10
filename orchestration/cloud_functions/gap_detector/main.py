"""gap_detector — escalate stale EXPECTED + DEGRADED rows to backfill triggers.

Reads `nba_orchestration.expected_outputs`, finds rows that are overdue
(expected_by < NOW() and status in EXPECTED/DEGRADED), and publishes them
to the `nba-backfill-trigger` Pub/Sub topic. The scraper-gap-backfiller
service subscribes and re-runs the appropriate scraper.

Status transitions written by this CF:
  EXPECTED + attempts < cap        → no change (reconciler still owns this row)
  DEGRADED + attempts < cap        → publishes Pub/Sub message, attempts += 1
  EXPECTED/DEGRADED + attempts cap → FAILED (gap_detector gives up; alert fires)

The cap protects against runaway retries on permanently-unrecoverable data
(e.g. paid Odds API historical that we don't have access to).

Triggered by Cloud Scheduler `gap-detector-30min` every 30 min, offset 15 min
from reconciler so the two run in alternation.

Created: 2026-05-09 (pipeline-state-redesign Phase E).
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import functions_framework
from flask import Request
from google.cloud import bigquery, pubsub_v1


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
EXPECTED_OUTPUTS_TABLE = f'{PROJECT_ID}.nba_orchestration.expected_outputs'
BACKFILL_TOPIC = os.environ.get('BACKFILL_TOPIC', 'nba-backfill-trigger')

# Past this attempt count, gap_detector marks the row FAILED and gives up.
MAX_BACKFILL_ATTEMPTS = int(os.environ.get('MAX_BACKFILL_ATTEMPTS', '3'))

# Per-invocation cap to avoid runaway publishes if a season's worth of rows
# all become eligible at once.
MAX_PUBLISHES_PER_RUN = int(os.environ.get('MAX_PUBLISHES_PER_RUN', '50'))

_bq_client = None
_publisher = None


def _get_bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        try:
            from shared.clients.bigquery_pool import get_bigquery_client
            _bq_client = get_bigquery_client(project_id=PROJECT_ID)
        except Exception:
            _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def select_overdue_rows(bq: bigquery.Client, limit: int) -> List[Any]:
    query = f"""
        SELECT season, game_date, sport, phase, output_type,
               expected_partition, attempts, status
        FROM `{EXPECTED_OUTPUTS_TABLE}`
        WHERE status IN ('EXPECTED', 'DEGRADED')
          AND expected_by < CURRENT_TIMESTAMP()
        ORDER BY expected_by ASC
        LIMIT @limit
    """
    job = bq.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter('limit', 'INT64', limit)]
        ),
    )
    return list(job.result(timeout=60))


def publish_backfill_message(
    publisher: pubsub_v1.PublisherClient,
    project_id: str,
    topic: str,
    payload: Dict[str, Any],
) -> str:
    topic_path = publisher.topic_path(project_id, topic)
    data = json.dumps(payload, default=str).encode('utf-8')
    future = publisher.publish(topic_path, data=data)
    return future.result(timeout=10)


def update_status(
    bq: bigquery.Client,
    rows: List[Dict[str, Any]],
    new_status: str,
    bump_attempts: bool,
) -> int:
    if not rows:
        return 0

    values_clauses = []
    params = []
    for i, r in enumerate(rows):
        values_clauses.append(f"(@gd_{i}, @sp_{i}, @ph_{i}, @ot_{i})")
        params.extend([
            bigquery.ScalarQueryParameter(f'gd_{i}', 'DATE', r['game_date']),
            bigquery.ScalarQueryParameter(f'sp_{i}', 'STRING', r['sport']),
            bigquery.ScalarQueryParameter(f'ph_{i}', 'STRING', r['phase']),
            bigquery.ScalarQueryParameter(f'ot_{i}', 'STRING', r['output_type']),
        ])
    params.append(bigquery.ScalarQueryParameter('new_status', 'STRING', new_status))
    params.append(bigquery.ScalarQueryParameter('bump', 'INT64', 1 if bump_attempts else 0))

    update_sql = f"""
        UPDATE `{EXPECTED_OUTPUTS_TABLE}` T
        SET status = @new_status,
            attempts = T.attempts + @bump,
            last_run_at = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP(),
            source = 'gap_detector'
        WHERE (T.game_date, T.sport, T.phase, T.output_type) IN UNNEST([
          STRUCT<game_date DATE, sport STRING, phase STRING, output_type STRING>
          {', '.join(values_clauses)}
        ])
    """
    job = bq.query(update_sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    job.result(timeout=60)
    return len(rows)


@functions_framework.http
def gap_detector(request: Request):
    args = request.args or {}
    limit = int(args.get('limit', str(MAX_PUBLISHES_PER_RUN)))
    dry_run = (args.get('dry_run', 'false') or 'false').lower() in ('true', '1', 'yes')

    bq = _get_bq()
    rows = select_overdue_rows(bq, limit=limit)

    summary: Dict[str, Any] = {
        'eligible_rows': len(rows),
        'published': 0,
        'failed_marked': 0,
        'skipped_at_cap': 0,
        'errors': [],
        'dry_run': dry_run,
    }

    publisher = _get_publisher() if not dry_run else None

    publishable: List[Dict[str, Any]] = []
    failable: List[Dict[str, Any]] = []

    for r in rows:
        attempts = int(r.attempts or 0)
        d = {
            'season': r.season,
            'game_date': r.game_date,
            'sport': r.sport,
            'phase': r.phase,
            'output_type': r.output_type,
            'expected_partition': r.expected_partition,
            'attempts': attempts,
            'status': r.status,
        }
        if attempts >= MAX_BACKFILL_ATTEMPTS:
            failable.append(d)
        else:
            publishable.append(d)

    if not dry_run and publishable:
        for d in publishable:
            payload = {
                'sport': d['sport'],
                'game_date': d['game_date'].isoformat(),
                'phase': d['phase'],
                'output_type': d['output_type'],
                'expected_partition': d['expected_partition'],
                'attempt': d['attempts'] + 1,
                'requested_at': datetime.now(timezone.utc).isoformat(),
            }
            try:
                publish_backfill_message(publisher, PROJECT_ID, BACKFILL_TOPIC, payload)
                summary['published'] += 1
            except Exception as e:
                msg = f"publish failed for {d['sport']}/{d['game_date']}/{d['output_type']}: {e}"
                logger.warning(msg)
                summary['errors'].append(msg)

    if not dry_run:
        try:
            summary['failed_marked'] = update_status(bq, failable, 'FAILED', bump_attempts=False)
        except Exception as e:
            summary['errors'].append(f"update_status FAILED: {e}")
        # gap_detector does NOT bump attempts on publish. The subscriber is
        # the canonical writer of attempts (one increment per real backfill
        # attempt). Pre-fix this loop bumped attempts here AND in the
        # subscriber AND in the reconciler — a single round trip burned
        # the cap of 3 in one cycle, marking rows FAILED before the scraper
        # had a real chance. We still mark publishable rows DEGRADED so the
        # state machine reflects "in retry."
        try:
            update_status(bq, publishable, 'DEGRADED', bump_attempts=False)
        except Exception as e:
            summary['errors'].append(f"update_status publishable: {e}")

    summary['skipped_at_cap'] = len(failable)
    summary['written_at'] = datetime.now(timezone.utc).isoformat()
    logger.info(f"gap_detector: {summary}")

    # Emit overdue_count metric for the expected-output-overdue alert policy.
    # Fail-open: telemetry failure never crashes the CF.
    try:
        from shared.observability.metrics import emit_metric, MetricKind
        emit_metric(
            metric_name='overdue_count',
            value=float(len(rows)),
            labels={'project': 'pipeline-state-redesign'},
            kind=MetricKind.GAUGE,
        )
    except Exception as e:
        logger.warning(f"emit overdue_count failed (non-fatal): {e}")

    return summary, 200


main = gap_detector
