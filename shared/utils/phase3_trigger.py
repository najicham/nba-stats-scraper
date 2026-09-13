"""Trigger a Phase 3 analytics re-run for a game date.

Why this exists (2026-09-08)
----------------------------
Phase 2 → Phase 3 is wired as a direct Pub/Sub push: subscription
`nba-phase3-analytics-sub` on topic `nba-phase2-raw-complete` posts to
`nba-phase3-analytics-processors/process`. The older `nba-phase3-trigger` topic
survived that migration but **has no subscriptions**, so publishing to it is a
silent no-op — `publisher.publish()` still returns a message id, and the caller
logs "✅ Triggered Phase 3 re-run".

`orchestration/cloud_functions/bdb_retry_processor` was fixed to POST the
Phase-2 envelope over HTTP instead. Three operator tools
(`bin/monitoring/bdb_{retry_processor,pending_monitor,critical_monitor}.py`) and
`auto_backfill_orchestrator` were not, and kept reporting success while doing
nothing. This module is the shared version of the working path.

Note Phase 3 returns HTTP 200 even on PARTIAL failure (e.g.
PlayerGameSummaryProcessor blocked by the team-stats threshold), so a 200 means
"the request was accepted", not "the data is now correct". Callers that need the
stronger guarantee must verify the output table themselves.
"""

import base64
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PHASE3_SERVICE_URL = os.environ.get(
    'PHASE3_SERVICE_URL',
    'https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app',
)


def trigger_phase3_rerun(
    game_date: str,
    source: str,
    trigger_reason: str = 'manual',
    source_table: str = 'nbac_gamebook_player_stats',
    output_table: str = 'nba_raw.nbac_gamebook_player_stats',
    backfill_mode: bool = True,
    service_url: Optional[str] = None,
    timeout: int = 300,
) -> bool:
    """POST a Phase-2-completion envelope to Phase 3's /process endpoint.

    Args:
        game_date: 'YYYY-MM-DD'. Phase 3 reprocesses the whole date, not one game.
        source: Who is asking (goes into the message for tracing).
        trigger_reason: Free-text reason, e.g. 'bdb_data_available'.
        source_table: Routes to a processor group via ANALYTICS_TRIGGER_GROUPS.
        output_table: Phase 2 output table the envelope claims completed.
        backfill_mode: Ask Phase 3 to bypass completeness/freshness checks.
        service_url: Override the Phase 3 base URL.
        timeout: HTTP timeout in seconds.

    Returns:
        True on HTTP 200. See the module docstring: 200 does NOT prove the
        downstream table was actually enriched.
    """
    url = service_url or DEFAULT_PHASE3_SERVICE_URL

    try:
        import requests
        import google.auth.transport.requests
        import google.oauth2.id_token
    except ImportError as e:
        logger.error(f"Phase 3 trigger unavailable (missing dependency): {e}")
        return False

    inner_message = {
        'source_table': source_table,
        'output_table': output_table,
        'game_date': game_date,
        'status': 'success',
        'backfill_mode': backfill_mode,
        'trigger_reason': trigger_reason,
        'source': source,
    }
    envelope = {
        'message': {
            'data': base64.b64encode(
                json.dumps(inner_message).encode('utf-8')
            ).decode('utf-8')
        }
    }

    try:
        auth_req = google.auth.transport.requests.Request()
        id_token = google.oauth2.id_token.fetch_id_token(auth_req, url)
        response = requests.post(
            f"{url}/process",
            json=envelope,
            headers={
                'Authorization': f'Bearer {id_token}',
                'Content-Type': 'application/json',
            },
            timeout=timeout,
        )
    except Exception as e:
        logger.error(f"Failed to HTTP-trigger Phase 3 for {game_date}: {e}", exc_info=True)
        return False

    if response.status_code == 200:
        logger.info(
            f"Phase 3 /process returned 200 for {game_date} "
            f"(source={source}): {response.text[:120]}"
        )
        return True

    logger.error(
        f"Phase 3 returned {response.status_code} for {game_date} "
        f"(source={source}): {response.text[:200]}"
    )
    return False
