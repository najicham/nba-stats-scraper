# predictions/coordinator/tests/test_progress_tracker.py

"""
Test suite for ProgressTracker class

Tests progress tracking logic, thread safety, completion detection,
and summary statistics generation.
"""

import pytest
import threading
import time
from datetime import datetime, timedelta
import sys
import os

# Add predictions to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
predictions_path = os.path.join(project_root, 'predictions')
if predictions_path not in sys.path:
    sys.path.insert(0, predictions_path)

from coordinator.progress_tracker import ProgressTracker


class TestProgressTracker:
    """Test suite for ProgressTracker"""
    
    def test_init(self):
        """Test ProgressTracker initialization"""
        tracker = ProgressTracker(expected_players=100)
        
        assert tracker.expected_players == 100
        assert len(tracker.completed_players) == 0
        assert len(tracker.failed_players) == 0
        assert tracker.total_predictions == 0
        assert tracker.is_complete is False
        assert tracker.start_time is not None
        assert tracker.completion_time is None
    
    def test_process_completion_event_single(self):
        """Test processing single completion event"""
        tracker = ProgressTracker(expected_players=2)
        
        event = {
            'player_lookup': 'lebron-james',
            'game_date': '2025-11-08',
            'predictions_generated': 5
        }
        
        complete = tracker.process_completion_event(event)
        
        assert complete is False  # Not done yet (1/2)
        assert len(tracker.completed_players) == 1
        assert tracker.total_predictions == 5
        assert 'lebron-james' in tracker.completed_players
        assert tracker.is_complete is False
    
    def test_process_completion_event_batch_complete(self):
        """Test batch marked complete when all players done"""
        tracker = ProgressTracker(expected_players=2)
        
        # First player
        tracker.process_completion_event({
            'player_lookup': 'lebron-james',
            'predictions_generated': 5
        })
        
        assert tracker.is_complete is False
        
        # Second player (should complete batch)
        complete = tracker.process_completion_event({
            'player_lookup': 'stephen-curry',
            'predictions_generated': 5
        })
        
        assert complete is True
        assert tracker.is_complete is True
        assert tracker.completion_time is not None
        assert len(tracker.completed_players) == 2
    
    def test_process_completion_event_duplicate_player(self):
        """Test duplicate completion events are handled (idempotency)"""
        tracker = ProgressTracker(expected_players=2)
        
        event = {
            'player_lookup': 'lebron-james',
            'predictions_generated': 5
        }
        
        # First event
        tracker.process_completion_event(event)
        assert len(tracker.completed_players) == 1
        assert tracker.total_predictions == 5
        
        # Duplicate event (should be ignored)
        complete = tracker.process_completion_event(event)
        assert complete is False
        assert len(tracker.completed_players) == 1  # Still 1
        assert tracker.total_predictions == 5  # Still 5 (not 10)
    
    def test_process_completion_event_no_player_lookup(self):
        """Test handling event without player_lookup"""
        tracker = ProgressTracker(expected_players=10)
        
        event = {
            'game_date': '2025-11-08',
            'predictions_generated': 5
        }
        
        complete = tracker.process_completion_event(event)
        
        assert complete is False
        assert len(tracker.completed_players) == 0
    
    def test_mark_player_failed(self):
        """Test marking player as failed"""
        tracker = ProgressTracker(expected_players=10)
        
        tracker.mark_player_failed('injured-player', 'Player inactive')
        
        assert len(tracker.failed_players) == 1
        assert 'injured-player' in tracker.failed_players
        assert len(tracker.completed_players) == 0
    
    def test_mark_player_failed_duplicate(self):
        """Test marking same player as failed twice"""
        tracker = ProgressTracker(expected_players=10)
        
        tracker.mark_player_failed('injured-player', 'Error 1')
        tracker.mark_player_failed('injured-player', 'Error 2')
        
        assert len(tracker.failed_players) == 1  # Only counted once
    
    def test_get_progress_initial(self):
        """Test get_progress returns correct initial state"""
        tracker = ProgressTracker(expected_players=10)
        
        progress = tracker.get_progress()
        
        assert progress['expected'] == 10
        assert progress['completed'] == 0
        assert progress['remaining'] == 10
        assert progress['failed'] == 0
        assert progress['total_predictions'] == 0
        assert progress['progress_percentage'] == 0.0
        assert progress['is_complete'] is False
    
    def test_get_progress_partial(self):
        """Test get_progress with partial completion"""
        tracker = ProgressTracker(expected_players=10)
        
        # Add some completions
        for i in range(5):
            tracker.process_completion_event({
                'player_lookup': f'player-{i}',
                'predictions_generated': 5
            })
        
        progress = tracker.get_progress()
        
        assert progress['expected'] == 10
        assert progress['completed'] == 5
        assert progress['remaining'] == 5
        assert progress['total_predictions'] == 25
        assert progress['progress_percentage'] == 50.0
        assert progress['is_complete'] is False
    
    def test_get_progress_complete(self):
        """Test get_progress when batch complete"""
        tracker = ProgressTracker(expected_players=3)
        
        for i in range(3):
            tracker.process_completion_event({
                'player_lookup': f'player-{i}',
                'predictions_generated': 5
            })
        
        progress = tracker.get_progress()
        
        assert progress['completed'] == 3
        assert progress['remaining'] == 0
        assert progress['progress_percentage'] == 100.0
        assert progress['is_complete'] is True
    
    def test_get_progress_with_failures(self):
        """Test get_progress accounts for failed players"""
        tracker = ProgressTracker(expected_players=10)
        
        # 5 completed
        for i in range(5):
            tracker.process_completion_event({
                'player_lookup': f'player-{i}',
                'predictions_generated': 5
            })
        
        # 2 failed
        tracker.mark_player_failed('player-fail-1', 'Error')
        tracker.mark_player_failed('player-fail-2', 'Error')
        
        progress = tracker.get_progress()
        
        assert progress['completed'] == 5
        assert progress['failed'] == 2
        assert progress['remaining'] == 3  # 10 - 5 - 2
    
    def test_get_summary(self):
        """Test get_summary returns final statistics"""
        tracker = ProgressTracker(expected_players=10)
        
        # Complete all players
        for i in range(10):
            tracker.process_completion_event({
                'player_lookup': f'player-{i}',
                'predictions_generated': 5
            })
        
        summary = tracker.get_summary()
        
        assert summary['expected_players'] == 10
        assert summary['completed_players'] == 10
        assert summary['failed_players'] == 0
        assert summary['total_predictions'] == 50
        assert summary['avg_predictions_per_player'] == 5.0
        assert summary['success_rate'] == 100.0
        assert 'start_time' in summary
        assert 'completion_time' in summary
        assert 'duration_seconds' in summary
    
    def test_get_summary_with_failures(self):
        """Test get_summary includes failed players"""
        tracker = ProgressTracker(expected_players=10)
        
        # 8 completed
        for i in range(8):
            tracker.process_completion_event({
                'player_lookup': f'player-{i}',
                'predictions_generated': 5
            })
        
        # 2 failed
        tracker.mark_player_failed('player-fail-1', 'Error')
        tracker.mark_player_failed('player-fail-2', 'Error')
        
        # Mark as complete (all players accounted for)
        tracker.process_completion_event({
            'player_lookup': 'player-8',
            'predictions_generated': 5
        })
        tracker.process_completion_event({
            'player_lookup': 'player-9',
            'predictions_generated': 5
        })
        
        summary = tracker.get_summary()
        
        assert summary['completed_players'] == 10
        assert summary['failed_players'] == 2
        assert summary['success_rate'] == 100.0  # Based on completed vs expected
    
    def test_is_stalled_no_completions(self):
        """Test is_stalled when no completions yet"""
        tracker = ProgressTracker(expected_players=10)
        
        # Should not be stalled immediately
        assert tracker.is_stalled(stall_threshold_seconds=60) is False
    
    def test_is_stalled_recent_activity(self):
        """Test is_stalled returns False with recent activity"""
        tracker = ProgressTracker(expected_players=10)
        
        # Add a completion
        tracker.process_completion_event({
            'player_lookup': 'player-1',
            'predictions_generated': 5
        })
        
        # Should not be stalled (just completed)
        assert tracker.is_stalled(stall_threshold_seconds=60) is False
    
    def test_is_stalled_when_complete(self):
        """Test is_stalled returns False when batch complete"""
        tracker = ProgressTracker(expected_players=2)
        
        # Complete batch
        tracker.process_completion_event({'player_lookup': 'p1', 'predictions_generated': 5})
        tracker.process_completion_event({'player_lookup': 'p2', 'predictions_generated': 5})
        
        # Should not be stalled (complete)
        assert tracker.is_stalled(stall_threshold_seconds=1) is False
    
    def test_get_missing_players(self):
        """Test get_missing_players returns correct list"""
        tracker = ProgressTracker(expected_players=5)
        
        # Complete 2
        tracker.process_completion_event({'player_lookup': 'player-1', 'predictions_generated': 5})
        tracker.process_completion_event({'player_lookup': 'player-2', 'predictions_generated': 5})
        
        # Fail 1
        tracker.mark_player_failed('player-3', 'Error')
        
        # Check missing
        all_players = ['player-1', 'player-2', 'player-3', 'player-4', 'player-5']
        missing = tracker.get_missing_players(all_players)
        
        assert len(missing) == 2
        assert 'player-4' in missing
        assert 'player-5' in missing
        assert 'player-1' not in missing
        assert 'player-3' not in missing
    
    def test_reset(self):
        """Test reset clears all state"""
        tracker = ProgressTracker(expected_players=10)
        
        # Add some state
        tracker.process_completion_event({'player_lookup': 'p1', 'predictions_generated': 5})
        tracker.mark_player_failed('p2', 'Error')
        
        assert len(tracker.completed_players) == 1
        assert tracker.total_predictions == 5
        
        # Reset
        tracker.reset()
        
        assert len(tracker.completed_players) == 0
        assert len(tracker.failed_players) == 0
        assert tracker.total_predictions == 0
        assert tracker.is_complete is False
        assert tracker.completion_time is None
    
    def test_repr(self):
        """Test string representation"""
        tracker = ProgressTracker(expected_players=10)
        tracker.process_completion_event({'player_lookup': 'p1', 'predictions_generated': 5})
        
        repr_str = repr(tracker)
        
        assert 'ProgressTracker' in repr_str
        assert '1/10' in repr_str
        assert 'predictions=5' in repr_str


class TestProgressTrackerThreadSafety:
    """Test thread safety of ProgressTracker"""
    
    def test_thread_safety_concurrent_completions(self):
        """Test thread safety with concurrent completion events"""
        tracker = ProgressTracker(expected_players=100)
        
        def complete_player(player_id):
            """Simulate worker completion"""
            event = {
                'player_lookup': f'player-{player_id}',
                'predictions_generated': 5
            }
            tracker.process_completion_event(event)
        
        # Spawn 100 threads simultaneously
        threads = []
        for i in range(100):
            t = threading.Thread(target=complete_player, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Verify results
        progress = tracker.get_progress()
        assert progress['completed'] == 100, f"Expected 100, got {progress['completed']}"
        assert progress['total_predictions'] == 500, f"Expected 500, got {progress['total_predictions']}"
        assert tracker.is_complete is True
    
    def test_thread_safety_race_condition_prevention(self):
        """Test that lock prevents race conditions"""
        tracker = ProgressTracker(expected_players=1)
        
        results = []
        
        def try_complete_same_player():
            """Try to complete the same player (race condition test)"""
            event = {
                'player_lookup': 'duplicate-player',
                'predictions_generated': 5
            }
            complete = tracker.process_completion_event(event)
            results.append(complete)
        
        # Spawn 10 threads trying to complete same player
        threads = []
        for i in range(10):
            t = threading.Thread(target=try_complete_same_player)
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Only ONE thread should succeed (return True for completion)
        # Others should detect duplicate and return False
        progress = tracker.get_progress()
        assert progress['completed'] == 1, "Player should only be counted once"
        assert tracker.total_predictions == 5, "Predictions should only be counted once"
        assert sum(1 for r in results if r) == 1, "Only one thread should complete the batch"
    
    def test_thread_safety_concurrent_read_write(self):
        """Test concurrent reads and writes don't cause corruption"""
        tracker = ProgressTracker(expected_players=50)
        
        progress_snapshots = []
        
        def complete_players():
            """Complete players (write operations)"""
            for i in range(10):
                tracker.process_completion_event({
                    'player_lookup': f'writer-player-{i}-{threading.current_thread().name}',
                    'predictions_generated': 5
                })
                time.sleep(0.001)  # Small delay
        
        def read_progress():
            """Read progress (read operations)"""
            for _ in range(20):
                progress = tracker.get_progress()
                progress_snapshots.append(progress)
                time.sleep(0.001)  # Small delay
        
        # Spawn writer and reader threads
        writers = [threading.Thread(target=complete_players, name=f'writer-{i}') for i in range(5)]
        readers = [threading.Thread(target=read_progress, name=f'reader-{i}') for i in range(3)]
        
        all_threads = writers + readers
        
        for t in all_threads:
            t.start()
        
        for t in all_threads:
            t.join()
        
        # Verify final state is consistent
        final_progress = tracker.get_progress()
        assert final_progress['completed'] == 50
        
        # All progress snapshots should be consistent (no torn reads)
        for snapshot in progress_snapshots:
            assert snapshot['completed'] >= 0
            assert snapshot['completed'] <= 50
            assert snapshot['total_predictions'] == snapshot['completed'] * 5
    
    def test_thread_safety_failed_players(self):
        """Test thread safety when marking players as failed"""
        tracker = ProgressTracker(expected_players=50)
        
        def mark_failures():
            """Mark players as failed"""
            for i in range(10):
                player_id = f'failed-{i}-{threading.current_thread().name}'
                tracker.mark_player_failed(player_id, 'Test error')
                time.sleep(0.001)
        
        # Spawn multiple threads marking failures
        threads = [threading.Thread(target=mark_failures) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should have exactly 50 failed players (10 per thread * 5 threads)
        progress = tracker.get_progress()
        assert progress['failed'] == 50


class TestProgressTrackerEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_zero_expected_players(self):
        """Test tracker with zero expected players"""
        tracker = ProgressTracker(expected_players=0)
        
        progress = tracker.get_progress()
        assert progress['expected'] == 0
        assert progress['progress_percentage'] == 0.0
    
    def test_completion_beyond_expected(self):
        """Test handling more completions than expected"""
        tracker = ProgressTracker(expected_players=2)
        
        # Complete 3 players (1 more than expected)
        tracker.process_completion_event({'player_lookup': 'p1', 'predictions_generated': 5})
        tracker.process_completion_event({'player_lookup': 'p2', 'predictions_generated': 5})
        tracker.process_completion_event({'player_lookup': 'p3', 'predictions_generated': 5})
        
        progress = tracker.get_progress()
        
        # Should handle gracefully
        assert progress['completed'] == 3
        assert progress['is_complete'] is True
    
    def test_empty_event(self):
        """Test handling empty event dict"""
        tracker = ProgressTracker(expected_players=10)
        
        result = tracker.process_completion_event({})
        
        assert result is False
        assert len(tracker.completed_players) == 0
    
    def test_get_summary_percentiles(self):
        """Test summary includes completion time percentiles"""
        tracker = ProgressTracker(expected_players=10)
        
        # Add completions with small delays
        for i in range(10):
            time.sleep(0.01)  # 10ms delay between completions
            tracker.process_completion_event({
                'player_lookup': f'player-{i}',
                'predictions_generated': 5
            })
        
        summary = tracker.get_summary()
        
        # Check percentiles exist
        assert 'completion_times' in summary
        assert 'p50_seconds' in summary['completion_times']
        assert 'p95_seconds' in summary['completion_times']
        assert 'p99_seconds' in summary['completion_times']
        
        # Percentiles should be positive
        assert summary['completion_times']['p50_seconds'] > 0
        assert summary['completion_times']['p95_seconds'] >= summary['completion_times']['p50_seconds']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
