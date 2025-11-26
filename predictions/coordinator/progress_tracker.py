# predictions/coordinator/progress_tracker.py

"""
Progress Tracker for Phase 5 Coordinator

Tracks prediction completion events from workers and maintains
progress state for the daily prediction batch.

THREADING MODEL:
---------------
This class MUST be thread-safe because:

1. Cloud Run processes multiple concurrent HTTP requests (up to 8 threads per instance)
2. Multiple workers complete predictions simultaneously
3. Each completion event triggers a POST to /complete endpoint
4. Multiple /complete requests hit the same ProgressTracker instance concurrently

Without thread safety:
- Race condition: Two threads check "player not in completed_players" simultaneously
- Both threads add the same player → player counted twice
- Progress calculation becomes incorrect (450/450 never reached, or 451/450!)

Solution: Use threading.Lock to synchronize access to shared state
- Only one thread can hold the lock at a time
- Other threads wait (block) until lock is released
- Ensures atomic read-modify-write operations

Performance Impact:
- Lock contention is minimal (each operation takes ~1ms)
- 450 completions over 2-3 minutes = ~3 completions/second
- Lock held for microseconds, released immediately
- No noticeable performance degradation

Responsibilities:
- Listen for prediction-ready events from Pub/Sub
- Track completion status (450/450)
- Detect failures and stalled predictions
- Calculate batch statistics
- Publish summary when complete

Version: 1.1 (Thread-safe with explicit locking)
"""

from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from threading import Lock
import logging
import json

logger = logging.getLogger(__name__)


class ProgressTracker:
    """
    Tracks progress of prediction batch processing
    
    THREAD-SAFE: Uses threading.Lock to protect shared state from
    concurrent access by multiple HTTP request handler threads.
    """
    
    def __init__(self, expected_players: int):
        """
        Initialize progress tracker
        
        Args:
            expected_players: Number of players expected (typically 450)
        """
        self.expected_players = expected_players
        self.start_time = datetime.utcnow()
        
        # ==================================================================
        # SHARED STATE (protected by self._lock)
        # ==================================================================
        # These data structures are accessed by multiple threads:
        # - Flask request handlers processing /complete endpoint
        # - Each worker completion event triggers concurrent access
        # - Without locks, race conditions cause incorrect counts
        
        self.completed_players: Set[str] = set()
        self.failed_players: Set[str] = set()
        self.predictions_by_player: Dict[str, int] = {}
        self.completion_times: List[datetime] = []
        self.total_predictions = 0
        
        # State flags
        self.is_complete = False
        self.completion_time: Optional[datetime] = None
        
        # ==================================================================
        # THREAD SYNCHRONIZATION
        # ==================================================================
        # Lock protects all shared state above
        # - Acquired before reading/modifying state
        # - Released automatically by 'with' statement
        # - Prevents race conditions between concurrent threads
        self._lock = Lock()
        
        logger.info(f"Initialized ProgressTracker for {expected_players} players (thread-safe)")
    
    def process_completion_event(self, event: Dict) -> bool:
        """
        Process a prediction-ready event from worker
        
        THREAD-SAFE: Uses lock to prevent race conditions when multiple
        workers complete simultaneously.
        
        Common race condition without lock:
        1. Thread A checks: "lebron-james" not in completed_players → True
        2. Thread B checks: "lebron-james" not in completed_players → True
        3. Thread A adds "lebron-james" to set
        4. Thread B adds "lebron-james" to set again
        5. Both threads increment total_predictions
        6. Result: Same player counted twice!
        
        With lock:
        1. Thread A acquires lock
        2. Thread A checks and adds "lebron-james"
        3. Thread A releases lock
        4. Thread B acquires lock
        5. Thread B checks: "lebron-james" already in set → Skip
        6. Thread B releases lock
        7. Result: Player counted exactly once ✅
        
        Args:
            event: Event data from Pub/Sub
                {
                    'player_lookup': 'lebron-james',
                    'game_date': '2025-11-08',
                    'predictions_generated': 5,
                    'timestamp': '2025-11-08T10:30:00.123Z'
                }
        
        Returns:
            bool: True if batch is now complete, False otherwise
        """
        player_lookup = event.get('player_lookup')
        predictions_count = event.get('predictions_generated', 0)
        
        if not player_lookup:
            logger.warning("Received event without player_lookup")
            return False
        
        # =====================================================================
        # CRITICAL SECTION: Protected by lock
        # =====================================================================
        # Everything inside this 'with' block is synchronized:
        # - Only one thread can execute this code at a time
        # - Other threads wait (block) until lock is released
        # - Lock automatically released at end of 'with' block
        
        with self._lock:
            # Check if this player already completed (idempotency)
            if player_lookup in self.completed_players:
                logger.debug(f"Player {player_lookup} already completed (duplicate event)")
                return False
            
            # Mark player as completed
            self.completed_players.add(player_lookup)
            self.completion_times.append(datetime.utcnow())
            
            # Track predictions
            self.total_predictions += predictions_count
            self.predictions_by_player[player_lookup] = predictions_count
            
            logger.info(
                f"Player {player_lookup} completed ({len(self.completed_players)}/{self.expected_players}) "
                f"with {predictions_count} predictions"
            )
            
            # Check if batch complete
            batch_complete = False
            if not self.is_complete and len(self.completed_players) >= self.expected_players:
                self._mark_complete()  # Still inside lock - safe to call
                batch_complete = True
            
            return batch_complete
        
        # Lock automatically released here
    
    def mark_player_failed(self, player_lookup: str, error: str):
        """
        Mark a player as failed
        
        THREAD-SAFE: Protected by lock since failed_players is shared state
        
        Args:
            player_lookup: Player identifier
            error: Error message
        """
        # =====================================================================
        # CRITICAL SECTION: Protected by lock
        # =====================================================================
        # Failed players could be marked by multiple threads:
        # - Publishing thread detects Pub/Sub failure
        # - Timeout thread marks stalled players as failed
        # - Need lock to prevent duplicate entries
        
        with self._lock:
            if player_lookup not in self.failed_players:
                self.failed_players.add(player_lookup)
                logger.error(f"Player {player_lookup} failed: {error}")
    
    def _mark_complete(self):
        """
        Mark batch as complete
        
        INTERNAL: Called while lock is held, does not acquire lock itself
        
        This method modifies shared state but does NOT acquire the lock
        because it's always called from within a locked context
        (e.g., from process_completion_event while lock is held).
        """
        self.is_complete = True
        self.completion_time = datetime.utcnow()
        
        duration = (self.completion_time - self.start_time).total_seconds()
        
        logger.info(
            f"Batch complete! {len(self.completed_players)}/{self.expected_players} players "
            f"in {duration:.1f}s ({self.total_predictions} predictions)"
        )
    
    def get_progress(self) -> Dict:
        """
        Get current progress statistics
        
        THREAD-SAFE: Acquires lock to read consistent snapshot of state
        
        Why lock is needed for reads:
        - Without lock: Could read mid-update (e.g., player added to set but
          not yet added to predictions count) → inconsistent data
        - With lock: Guaranteed atomic snapshot of all related state
        
        Returns:
            Dict with progress info
        """
        now = datetime.utcnow()
        elapsed = (now - self.start_time).total_seconds()
        
        # =====================================================================
        # CRITICAL SECTION: Protected by lock
        # =====================================================================
        # Even though we're only reading, we need the lock to ensure
        # consistency across multiple related values:
        # - completed count, failed count, total_predictions must be consistent
        # - Without lock, another thread could modify state mid-read
        
        with self._lock:
            completed = len(self.completed_players)
            failed = len(self.failed_players)
            remaining = self.expected_players - completed - failed
            total_predictions = self.total_predictions
            is_complete = self.is_complete
        
        # Lock released - calculations below use local copies
        
        # Calculate rate (outside lock since we have local copies)
        if completed > 0 and elapsed > 0:
            rate = completed / elapsed  # players per second
            eta_seconds = remaining / rate if rate > 0 else 0
        else:
            rate = 0.0
            eta_seconds = 0
        
        return {
            'expected': self.expected_players,
            'completed': completed,
            'failed': failed,
            'remaining': remaining,
            'is_complete': is_complete,
            'total_predictions': total_predictions,
            'elapsed_seconds': elapsed,
            'completion_rate': rate,
            'eta_seconds': eta_seconds,
            'progress_percentage': (completed / self.expected_players * 100) if self.expected_players > 0 else 0
        }
    
    def get_summary(self) -> Dict:
        """
        Get final summary statistics
        
        THREAD-SAFE: Acquires lock to read final state
        
        Should be called after batch is complete
        
        Returns:
            Dict with summary stats
        """
        if not self.is_complete:
            logger.warning("Getting summary before batch is complete")
        
        # =====================================================================
        # CRITICAL SECTION: Protected by lock
        # =====================================================================
        # Read all state atomically to ensure consistency
        
        with self._lock:
            completed_count = len(self.completed_players)
            failed_count = len(self.failed_players)
            total_preds = self.total_predictions
            completion_time = self.completion_time
            
            # Make copies of lists to work with outside lock
            completion_times_copy = list(self.completion_times)
            failed_players_copy = list(self.failed_players)
        
        # Lock released - work with local copies below
        
        duration = (completion_time - self.start_time).total_seconds() if completion_time else 0
        
        # Calculate percentiles for completion times
        completion_times_sorted = sorted([
            (t - self.start_time).total_seconds() 
            for t in completion_times_copy
        ])
        
        def percentile(data: List[float], p: int) -> float:
            if not data:
                return 0.0
            k = (len(data) - 1) * (p / 100.0)
            f = int(k)
            c = f + 1 if f < len(data) - 1 else f
            return data[f] + (k - f) * (data[c] - data[f])
        
        p50 = percentile(completion_times_sorted, 50) if completion_times_sorted else 0
        p95 = percentile(completion_times_sorted, 95) if completion_times_sorted else 0
        p99 = percentile(completion_times_sorted, 99) if completion_times_sorted else 0
        
        return {
            'start_time': self.start_time.isoformat(),
            'completion_time': completion_time.isoformat() if completion_time else None,
            'duration_seconds': duration,
            'expected_players': self.expected_players,
            'completed_players': completed_count,
            'failed_players': failed_count,
            'total_predictions': total_preds,
            'avg_predictions_per_player': total_preds / completed_count if completed_count > 0 else 0,
            'success_rate': (completed_count / self.expected_players * 100) if self.expected_players > 0 else 0,
            'completion_times': {
                'p50_seconds': p50,
                'p95_seconds': p95,
                'p99_seconds': p99
            },
            'failed_player_list': failed_players_copy[:20] if len(failed_players_copy) < 20 else failed_players_copy[:20]
        }
    
    def is_stalled(self, stall_threshold_seconds: int = 600) -> bool:
        """
        Check if batch processing has stalled
        
        THREAD-SAFE: Acquires lock to read stall-related state
        
        Args:
            stall_threshold_seconds: Seconds without progress = stalled (default 10 min)
        
        Returns:
            bool: True if stalled, False otherwise
        """
        # =====================================================================
        # CRITICAL SECTION: Protected by lock
        # =====================================================================
        
        with self._lock:
            if self.is_complete:
                return False
            
            if not self.completion_times:
                # No completions yet - check if we've exceeded threshold since start
                elapsed = (datetime.utcnow() - self.start_time).total_seconds()
                return elapsed > stall_threshold_seconds
            
            # Check time since last completion
            last_completion = max(self.completion_times)
        
        # Lock released - work with local copy
        
        time_since_last = (datetime.utcnow() - last_completion).total_seconds()
        return time_since_last > stall_threshold_seconds
    
    def get_missing_players(self, all_players: List[str]) -> List[str]:
        """
        Get list of players that haven't completed
        
        THREAD-SAFE: Acquires lock to read player sets
        
        Args:
            all_players: List of all player_lookups expected
        
        Returns:
            List of missing player_lookups
        """
        all_players_set = set(all_players)
        
        # =====================================================================
        # CRITICAL SECTION: Protected by lock
        # =====================================================================
        
        with self._lock:
            # Make copies to work with outside lock
            completed_copy = set(self.completed_players)
            failed_copy = set(self.failed_players)
        
        # Lock released - work with local copies
        
        missing = all_players_set - completed_copy - failed_copy
        return sorted(missing)
    
    def reset(self):
        """
        Reset tracker for new batch
        
        THREAD-SAFE: Acquires lock to reset all state
        
        WARNING: Should only be called when no other threads are active
        (e.g., between batches when coordinator is idle)
        """
        # =====================================================================
        # CRITICAL SECTION: Protected by lock
        # =====================================================================
        
        with self._lock:
            self.start_time = datetime.utcnow()
            self.completed_players.clear()
            self.failed_players.clear()
            self.completion_times.clear()
            self.predictions_by_player.clear()
            self.total_predictions = 0
            self.is_complete = False
            self.completion_time = None
        
        logger.info("Progress tracker reset for new batch")
    
    def __repr__(self):
        """
        String representation of tracker
        
        THREAD-SAFE: Uses get_progress() which acquires lock
        """
        progress = self.get_progress()
        return (
            f"ProgressTracker("
            f"completed={progress['completed']}/{progress['expected']}, "
            f"predictions={progress['total_predictions']}, "
            f"complete={progress['is_complete']})"
        )


# ============================================================================
# THREADING NOTES FOR FUTURE OPTIMIZATION
# ============================================================================
"""
CURRENT IMPLEMENTATION: threading.Lock (suitable for single-instance coordinator)
- Simple and reliable
- Low overhead
- Works perfectly for max-instances=1 Cloud Run deployment

PRODUCTION SCALING: For multi-instance coordinator (max-instances > 1):
- Current solution won't work (each instance has separate memory)
- Need distributed state management:
  
  Option 1: Firestore (Recommended)
  - Store batch state in Firestore document
  - Use transactions for atomic updates
  - Scale to any number of instances
  - See action plan for implementation details
  
  Option 2: Redis
  - Store state in Redis with atomic operations
  - Faster than Firestore but requires Redis instance
  - Good for high-throughput scenarios
  
  Option 3: Cloud Memorystore
  - Managed Redis service
  - Same benefits as Redis with less ops overhead

For initial deployment:
- Dev/Staging: Use threading.Lock with max-instances=1 ✅
- Production: Migrate to Firestore for multi-instance support

See: /docs/phase5_production_readiness_action_plan.md
     Section: "2. Coordinator Global State Management"
"""