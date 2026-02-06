# predictions/coordinator/quality_healer.py
"""
Quality Healer for Prediction System (Session 139)

Self-healing module that re-triggers Phase 4 processors when the quality gate
detects missing/degraded data. Limits to 1 heal attempt per batch via Firestore.

Flow:
1. Quality gate diagnoses missing processors
2. QualityHealer POSTs to Phase 4 /process-date with specific processors
3. Waits for completion (5-min timeout)
4. Re-triggers MLFeatureStoreProcessor to rebuild features
5. Returns heal result for coordinator to re-run quality gate
"""

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

# Max 1 heal attempt per batch to avoid infinite loops
MAX_HEAL_ATTEMPTS_PER_BATCH = 1
HEAL_TIMEOUT_SECONDS = 300  # 5 minutes


@dataclass
class HealResult:
    """Result of a self-healing attempt."""
    attempted: bool
    success: bool
    processors_triggered: List[str]
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


class QualityHealer:
    """
    Self-healing for quality gate failures.

    Re-triggers Phase 4 processors when quality gate detects missing data.
    Tracks attempts in Firestore to prevent infinite heal loops.
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._firestore_client = None

    @property
    def firestore_client(self):
        if self._firestore_client is None:
            from shared.clients import get_firestore_client
            self._firestore_client = get_firestore_client()
        return self._firestore_client

    def attempt_heal(
        self,
        game_date: date,
        batch_id: str,
        missing_processors: List[str],
    ) -> HealResult:
        """
        Attempt to self-heal by re-triggering Phase 4 processors.

        Args:
            game_date: Date to heal features for
            batch_id: Current prediction batch ID (for dedup)
            missing_processors: List of processor names that likely failed

        Returns:
            HealResult with success/failure details
        """
        if not missing_processors:
            return HealResult(attempted=False, success=False, processors_triggered=[],
                              error="No missing processors to heal")

        # Check Firestore for existing heal attempt on this batch
        if self._already_healed(batch_id):
            logger.info(f"QUALITY_HEALER: Already healed for batch {batch_id}, skipping")
            return HealResult(attempted=False, success=False, processors_triggered=[],
                              error="Already healed for this batch")

        logger.info(
            f"QUALITY_HEALER: Attempting heal for {game_date}, "
            f"processors={missing_processors}, batch={batch_id}"
        )

        # Record attempt in Firestore
        self._record_heal_attempt(batch_id, game_date, missing_processors)

        start = time.time()
        try:
            # Trigger Phase 4 processors
            success = self._trigger_phase4_processors(
                game_date=game_date,
                processors=missing_processors,
            )

            if success:
                # Also re-trigger MLFeatureStoreProcessor to rebuild features
                if 'MLFeatureStoreProcessor' not in missing_processors:
                    self._trigger_phase4_processors(
                        game_date=game_date,
                        processors=['MLFeatureStoreProcessor'],
                    )

            elapsed = time.time() - start
            result = HealResult(
                attempted=True,
                success=success,
                processors_triggered=missing_processors,
                elapsed_seconds=elapsed,
            )

            # Update Firestore with result
            self._update_heal_result(batch_id, result)

            if success:
                logger.info(f"QUALITY_HEALER: Heal succeeded in {elapsed:.1f}s")
            else:
                logger.warning(f"QUALITY_HEALER: Heal failed after {elapsed:.1f}s")

            return result

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"QUALITY_HEALER: Heal error: {e}", exc_info=True)
            result = HealResult(
                attempted=True,
                success=False,
                processors_triggered=missing_processors,
                error=str(e),
                elapsed_seconds=elapsed,
            )
            self._update_heal_result(batch_id, result)
            return result

    def _trigger_phase4_processors(
        self,
        game_date: date,
        processors: List[str],
    ) -> bool:
        """
        POST to Phase 4 /process-date to re-run specific processors.

        Args:
            game_date: Date to process
            processors: List of processor names to run

        Returns:
            True if request succeeded
        """
        import requests as http_requests
        from shared.config.service_urls import get_service_url, Services

        phase4_url = get_service_url(Services.PHASE4_PRECOMPUTE)

        # Get auth token for service-to-service call
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token
            auth_request = google.auth.transport.requests.Request()
            token = google.oauth2.id_token.fetch_id_token(auth_request, phase4_url)
        except Exception as e:
            logger.warning(f"QUALITY_HEALER: Failed to get auth token: {e}")
            token = None

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "analysis_date": game_date.isoformat(),
            "processors": processors,
            "strict_mode": False,
            "skip_dependency_check": True,
            "source": "quality_healer",
        }

        try:
            response = http_requests.post(
                f"{phase4_url}/process-date",
                headers=headers,
                json=payload,
                timeout=HEAL_TIMEOUT_SECONDS,
            )
            logger.info(
                f"QUALITY_HEALER: Phase 4 response: {response.status_code} "
                f"for processors={processors}"
            )
            return response.status_code in (200, 202)
        except http_requests.Timeout:
            logger.warning(f"QUALITY_HEALER: Phase 4 request timed out after {HEAL_TIMEOUT_SECONDS}s")
            return False
        except Exception as e:
            logger.error(f"QUALITY_HEALER: Phase 4 request failed: {e}")
            return False

    def _already_healed(self, batch_id: str) -> bool:
        """Check if we already attempted healing for this batch."""
        try:
            doc = self.firestore_client.collection('quality_heal_attempts').document(batch_id).get()
            if doc.exists:
                data = doc.to_dict()
                return data.get('attempt_count', 0) >= MAX_HEAL_ATTEMPTS_PER_BATCH
            return False
        except Exception as e:
            logger.warning(f"QUALITY_HEALER: Firestore check failed: {e}")
            return False  # Allow heal attempt if check fails

    def _record_heal_attempt(self, batch_id: str, game_date: date, processors: List[str]):
        """Record heal attempt in Firestore."""
        try:
            doc_ref = self.firestore_client.collection('quality_heal_attempts').document(batch_id)
            doc_ref.set({
                'batch_id': batch_id,
                'game_date': game_date.isoformat(),
                'processors': processors,
                'attempt_count': 1,
                'attempted_at': datetime.utcnow().isoformat(),
                'status': 'in_progress',
            })
        except Exception as e:
            logger.warning(f"QUALITY_HEALER: Failed to record attempt: {e}")

    def _update_heal_result(self, batch_id: str, result: HealResult):
        """Update Firestore with heal result."""
        try:
            doc_ref = self.firestore_client.collection('quality_heal_attempts').document(batch_id)
            doc_ref.update({
                'status': 'success' if result.success else 'failed',
                'completed_at': datetime.utcnow().isoformat(),
                'elapsed_seconds': result.elapsed_seconds,
                'error': result.error,
            })
        except Exception as e:
            logger.warning(f"QUALITY_HEALER: Failed to update result: {e}")
