# tests/predictions/test_similarity.py

"""
Unit tests for Similarity Balanced V1 Prediction System

Tests cover:
- Similarity scoring components
- Historical game matching
- Weighted baseline calculation
- Confidence scoring
- Edge cases and error handling
- Integration with mock data

Run with: pytest tests/predictions/test_similarity.py -v
"""

import pytest
from datetime import date, timedelta
import numpy as np
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from predictions.worker.prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
from predictions.shared.mock_data_generator import MockDataGenerator


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def similarity_system():
    """Create Similarity system instance"""
    return SimilarityBalancedV1()


@pytest.fixture
def mock_generator():
    """Create mock data generator with fixed seed"""
    return MockDataGenerator(seed=42)


@pytest.fixture
def sample_features():
    """Sample current game features"""
    return {
        'points_avg_last_5': 26.5,
        'points_avg_last_10': 25.8,
        'points_avg_season': 25.0,
        'points_std_last_10': 4.8,
        'minutes_avg_last_10': 35.2,
        'fatigue_score': 78.0,
        'shot_zone_mismatch_score': 4.5,
        'pace_score': 0.8,
        'usage_spike_score': 0.0,
        'opponent_def_rating_last_15': 112.5,
        'opponent_pace_last_15': 102.0,
        'is_home': 0.0,  # Away game
        'days_rest': 1.0,
        'back_to_back': 0.0,
        'paint_rate_last_10': 42.0,
        'mid_range_rate_last_10': 18.0,
        'three_pt_rate_last_10': 28.0,
        'assisted_rate_last_10': 68.0,
        'team_pace_last_10': 100.8,
        'team_off_rating_last_10': 117.2,
        'usage_rate_last_10': 27.5
    }


@pytest.fixture
def sample_historical_games():
    """Sample historical games for testing"""
    base_game = {
        'player_lookup': 'test-player',
        'game_date': date(2024, 12, 15),
        'game_id': 'BOS-20241215',
        'opponent_team_abbr': 'BOS',
        'opponent_tier': 'tier_2_average',
        'opponent_def_rating': 112.0,
        'days_rest': 1,
        'back_to_back': 0,
        'is_home': False,
        'recent_form': 'normal',
        'points': 27.5,
        'minutes_played': 35.0
    }
    
    # Generate 20 games with variations
    games = []
    for i in range(20):
        game = base_game.copy()
        game['game_date'] = date(2024, 12, 15) - timedelta(days=i*7)
        game['game_id'] = f"TEAM-{game['game_date'].strftime('%Y%m%d')}"
        
        # Vary points slightly
        game['points'] = 27.5 + np.random.normal(0, 3)
        
        # Vary some context
        if i % 3 == 0:
            game['days_rest'] = 0
            game['back_to_back'] = 1
        if i % 4 == 0:
            game['is_home'] = True
        if i % 5 == 0:
            game['opponent_tier'] = 'tier_1_elite'
            game['opponent_def_rating'] = 108.0
        
        games.append(game)
    
    return games


# ============================================================================
# TEST CLASS 1: Context Extraction
# ============================================================================

class TestContextExtraction:
    """Test extracting game context from features"""
    
    def test_extract_basic_context(self, similarity_system, sample_features):
        """Test extracting game context"""
        context = similarity_system._extract_game_context(sample_features)
        
        assert context['opponent_tier'] == 'tier_2_average'
        assert context['rest_bucket'] == 'one_day_rest'
        assert context['is_home'] is False
        assert context['form'] == 'normal'
    
    def test_opponent_tier_elite(self, similarity_system):
        """Test elite opponent classification"""
        features = {'opponent_def_rating_last_15': 108.0}
        
        tier = similarity_system._get_opponent_tier(108.0)
        assert tier == 'tier_1_elite'
    
    def test_opponent_tier_weak(self, similarity_system):
        """Test weak opponent classification"""
        tier = similarity_system._get_opponent_tier(118.0)
        assert tier == 'tier_3_weak'
    
    def test_rest_buckets(self, similarity_system):
        """Test rest categorization"""
        assert similarity_system._get_rest_bucket(0) == 'back_to_back'
        assert similarity_system._get_rest_bucket(1) == 'one_day_rest'
        assert similarity_system._get_rest_bucket(2) == 'two_days_rest'
        assert similarity_system._get_rest_bucket(5) == 'well_rested'
    
    def test_form_hot(self, similarity_system):
        """Test hot form detection"""
        form = similarity_system._get_form_bucket(28.5, 25.0)  # +3.5 diff
        assert form == 'hot'
    
    def test_form_cold(self, similarity_system):
        """Test cold form detection"""
        form = similarity_system._get_form_bucket(21.5, 25.0)  # -3.5 diff
        assert form == 'cold'
    
    def test_form_normal(self, similarity_system):
        """Test normal form detection"""
        form = similarity_system._get_form_bucket(26.5, 25.0)  # +1.5 diff
        assert form == 'normal'


# ============================================================================
# TEST CLASS 2: Similarity Scoring Components
# ============================================================================

class TestSimilarityScoring:
    """Test individual similarity scoring components"""
    
    def test_opponent_same_tier(self, similarity_system):
        """Test perfect opponent tier match"""
        current = {'opponent_tier': 'tier_2_average'}
        historical = {'opponent_tier': 'tier_2_average'}
        
        score = similarity_system._opponent_similarity(current, historical)
        assert score == 40.0
    
    def test_opponent_adjacent_tier(self, similarity_system):
        """Test adjacent opponent tier"""
        current = {'opponent_tier': 'tier_2_average'}
        historical = {'opponent_tier': 'tier_1_elite'}
        
        score = similarity_system._opponent_similarity(current, historical)
        assert score == 20.0
    
    def test_opponent_opposite_tiers(self, similarity_system):
        """Test opposite opponent tiers"""
        current = {'opponent_tier': 'tier_1_elite'}
        historical = {'opponent_tier': 'tier_3_weak'}
        
        score = similarity_system._opponent_similarity(current, historical)
        assert score == 0.0
    
    def test_rest_same_bucket(self, similarity_system):
        """Test perfect rest match"""
        current = {'rest_bucket': 'one_day_rest'}
        historical = {'days_rest': 1}
        
        score = similarity_system._rest_similarity(current, historical)
        assert score == 30.0
    
    def test_rest_adjacent_bucket(self, similarity_system):
        """Test adjacent rest buckets"""
        current = {'rest_bucket': 'one_day_rest'}
        historical = {'days_rest': 2}  # two_days_rest
        
        score = similarity_system._rest_similarity(current, historical)
        assert score == 15.0
    
    def test_rest_non_adjacent(self, similarity_system):
        """Test non-adjacent rest buckets"""
        current = {'rest_bucket': 'back_to_back'}
        historical = {'days_rest': 5}  # well_rested
        
        score = similarity_system._rest_similarity(current, historical)
        assert score == 0.0
    
    def test_venue_same(self, similarity_system):
        """Test same venue"""
        current = {'is_home': False}
        historical = {'is_home': False}
        
        score = similarity_system._venue_similarity(current, historical)
        assert score == 15.0
    
    def test_venue_different(self, similarity_system):
        """Test different venue"""
        current = {'is_home': True}
        historical = {'is_home': False}
        
        score = similarity_system._venue_similarity(current, historical)
        assert score == 0.0
    
    def test_form_same(self, similarity_system):
        """Test same form"""
        current = {'form': 'hot'}
        historical = {'recent_form': 'hot'}
        
        score = similarity_system._form_similarity(current, historical)
        assert score == 15.0
    
    def test_form_different(self, similarity_system):
        """Test different form (still some value)"""
        current = {'form': 'hot'}
        historical = {'recent_form': 'cold'}
        
        score = similarity_system._form_similarity(current, historical)
        assert score == 5.0


# ============================================================================
# TEST CLASS 3: Complete Similarity Calculation
# ============================================================================

class TestCompleteSimilarityScore:
    """Test complete similarity score calculation"""
    
    def test_perfect_match(self, similarity_system):
        """Test perfect similarity (100 points)"""
        current = {
            'opponent_tier': 'tier_2_average',
            'rest_bucket': 'one_day_rest',
            'is_home': False,
            'form': 'hot'
        }
        
        historical = {
            'opponent_tier': 'tier_2_average',
            'days_rest': 1,
            'is_home': False,
            'recent_form': 'hot'
        }
        
        score = similarity_system._calculate_similarity_score(current, historical)
        assert score == 100.0
    
    def test_good_match(self, similarity_system):
        """Test good similarity (~70-80 points)"""
        current = {
            'opponent_tier': 'tier_2_average',
            'rest_bucket': 'one_day_rest',
            'is_home': False,
            'form': 'hot'
        }
        
        historical = {
            'opponent_tier': 'tier_1_elite',  # Adjacent (20 pts)
            'days_rest': 1,  # Same (30 pts)
            'is_home': False,  # Same (15 pts)
            'recent_form': 'normal'  # Different (5 pts)
        }
        
        score = similarity_system._calculate_similarity_score(current, historical)
        assert score == 70.0  # 20 + 30 + 15 + 5
    
    def test_poor_match(self, similarity_system):
        """Test poor similarity (<50 points)"""
        current = {
            'opponent_tier': 'tier_1_elite',
            'rest_bucket': 'back_to_back',
            'is_home': True,
            'form': 'hot'
        }
        
        historical = {
            'opponent_tier': 'tier_3_weak',  # Opposite (0 pts)
            'days_rest': 5,  # Well-rested vs B2B (0 pts)
            'is_home': False,  # Different (0 pts)
            'recent_form': 'cold'  # Different (5 pts)
        }
        
        score = similarity_system._calculate_similarity_score(current, historical)
        assert score == 5.0


# ============================================================================
# TEST CLASS 4: Finding Similar Games
# ============================================================================

class TestFindingSimilarGames:
    """Test finding and filtering similar games"""
    
    def test_find_similar_games_basic(self, similarity_system, sample_features, sample_historical_games):
        """Test finding similar games"""
        context = similarity_system._extract_game_context(sample_features)
        
        similar_games = similarity_system._find_similar_games(
            context,
            sample_historical_games
        )
        
        # Should find at least some similar games
        assert len(similar_games) > 0
        
        # All should meet threshold
        for game in similar_games:
            assert game['similarity_score'] >= similarity_system.min_similarity_threshold
        
        # Should be sorted by similarity (descending)
        scores = [g['similarity_score'] for g in similar_games]
        assert scores == sorted(scores, reverse=True)
    
    def test_find_similar_games_respects_max_matches(self, similarity_system):
        """Test max matches limit"""
        context = {
            'opponent_tier': 'tier_2_average',
            'rest_bucket': 'one_day_rest',
            'is_home': False,
            'form': 'normal'
        }
        
        # Create 30 perfect matches
        historical_games = []
        for i in range(30):
            game = {
                'opponent_tier': 'tier_2_average',
                'days_rest': 1,
                'is_home': False,
                'recent_form': 'normal',
                'points': 25.0 + i * 0.5
            }
            historical_games.append(game)
        
        similar_games = similarity_system._find_similar_games(
            context,
            historical_games
        )
        
        # Should return max_matches even though 30 qualify
        assert len(similar_games) == similarity_system.max_matches
    
    def test_find_similar_games_filters_low_scores(self, similarity_system):
        """Test that low similarity games are filtered out"""
        context = {
            'opponent_tier': 'tier_1_elite',
            'rest_bucket': 'back_to_back',
            'is_home': True,
            'form': 'hot'
        }
        
        # Create games with varying similarity
        historical_games = [
            # Perfect match (100 pts)
            {
                'opponent_tier': 'tier_1_elite',
                'days_rest': 0,
                'is_home': True,
                'recent_form': 'hot',
                'points': 28.0
            },
            # Poor match (5 pts)
            {
                'opponent_tier': 'tier_3_weak',
                'days_rest': 5,
                'is_home': False,
                'recent_form': 'cold',
                'points': 22.0
            }
        ]
        
        similar_games = similarity_system._find_similar_games(
            context,
            historical_games
        )
        
        # Only perfect match should be included (5 < threshold of 70)
        assert len(similar_games) == 1
        assert similar_games[0]['similarity_score'] == 100.0


# ============================================================================
# TEST CLASS 5: Weighted Baseline Calculation
# ============================================================================

class TestWeightedBaseline:
    """Test weighted average calculation from similar games"""
    
    def test_weighted_baseline_equal_weights(self, similarity_system):
        """Test with equal similarity scores"""
        similar_games = [
            {'similarity_score': 80, 'points': 25.0},
            {'similarity_score': 80, 'points': 27.0},
            {'similarity_score': 80, 'points': 26.0}
        ]
        
        baseline = similarity_system._calculate_weighted_baseline(similar_games)
        
        # Equal weights → simple average
        expected = (25.0 + 27.0 + 26.0) / 3
        assert abs(baseline - expected) < 0.1
    
    def test_weighted_baseline_different_weights(self, similarity_system):
        """Test with different similarity scores"""
        similar_games = [
            {'similarity_score': 100, 'points': 30.0},  # Weight: 1.0
            {'similarity_score': 80, 'points': 25.0},   # Weight: 0.8
            {'similarity_score': 70, 'points': 20.0}    # Weight: 0.7
        ]
        
        baseline = similarity_system._calculate_weighted_baseline(similar_games)
        
        # Weighted average: (30*1.0 + 25*0.8 + 20*0.7) / (1.0 + 0.8 + 0.7)
        expected = (30.0 + 20.0 + 14.0) / 2.5
        assert abs(baseline - expected) < 0.1
    
    def test_weighted_baseline_empty_list(self, similarity_system):
        """Test with empty list"""
        baseline = similarity_system._calculate_weighted_baseline([])
        assert baseline == 0.0


# ============================================================================
# TEST CLASS 6: Adjustments
# ============================================================================

class TestAdjustments:
    """Test minor adjustments applied to baseline"""
    
    def test_adjustments_calculation(self, similarity_system, sample_features):
        """Test adjustment calculation"""
        adjustments = similarity_system._calculate_adjustments(sample_features)
        
        # Should have all adjustment components
        assert 'fatigue' in adjustments
        assert 'zone_matchup' in adjustments
        assert 'pace' in adjustments
        assert 'usage' in adjustments
        assert 'venue' in adjustments
        assert 'total' in adjustments
        
        # Total should be sum of components
        expected_total = (
            adjustments['fatigue'] +
            adjustments['zone_matchup'] +
            adjustments['pace'] +
            adjustments['usage'] +
            adjustments['venue']
        )
        assert abs(adjustments['total'] - expected_total) < 0.01
    
    def test_adjustments_fatigue_high(self, similarity_system):
        """Test fatigue adjustment when well-rested"""
        features = {'fatigue_score': 90.0}  # Well-rested
        
        adjustments = similarity_system._calculate_adjustments(features)
        
        # (90 - 70) * 0.015 = 0.3
        assert abs(adjustments['fatigue'] - 0.30) < 0.01
    
    def test_adjustments_fatigue_low(self, similarity_system):
        """Test fatigue adjustment when fatigued"""
        features = {'fatigue_score': 50.0}  # Fatigued
        
        adjustments = similarity_system._calculate_adjustments(features)
        
        # (50 - 70) * 0.015 = -0.3
        assert abs(adjustments['fatigue'] - (-0.30)) < 0.01


# ============================================================================
# TEST CLASS 7: Confidence Calculation
# ============================================================================

class TestConfidence:
    """Test confidence score calculation"""
    
    def test_confidence_high_count_high_similarity(self, similarity_system):
        """Test high confidence with many high-quality matches"""
        similar_games = [
            {'similarity_score': 90, 'points': 26.0 + i * 0.2}
            for i in range(15)
        ]
        
        confidence = similarity_system._calculate_confidence(
            similar_games,
            {'points_std_last_10': 3.5}
        )
        
        # Should be high (15 games, 90 avg similarity, low variance)
        assert confidence > 80
    
    def test_confidence_low_count(self, similarity_system):
        """Test lower confidence with few matches"""
        similar_games = [
            {'similarity_score': 85, 'points': 26.0}
            for i in range(5)
        ]
        
        confidence = similarity_system._calculate_confidence(
            similar_games,
            {}
        )
        
        # Should be moderate (only 5 games)
        assert 60 < confidence < 75
    
    def test_confidence_high_variance(self, similarity_system):
        """Test lower confidence with high outcome variance"""
        similar_games = [
            {'similarity_score': 90, 'points': 20.0},
            {'similarity_score': 90, 'points': 35.0},
            {'similarity_score': 90, 'points': 15.0},
            {'similarity_score': 90, 'points': 30.0},
            {'similarity_score': 90, 'points': 25.0}
        ]
        
        confidence = similarity_system._calculate_confidence(
            similar_games,
            {}
        )
        
        # High variance in outcomes reduces confidence
        assert confidence < 80


# ============================================================================
# TEST CLASS 8: Full Prediction
# ============================================================================

class TestFullPrediction:
    """Test complete prediction workflow"""
    
    def test_predict_success(self, similarity_system, sample_features, sample_historical_games):
        """Test successful prediction"""
        result = similarity_system.predict(
            player_lookup='test-player',
            features=sample_features,
            historical_games=sample_historical_games,
            betting_line=25.5
        )
        
        # Should return valid prediction
        assert result['system_id'] == 'similarity_balanced_v1'
        assert result['predicted_points'] is not None
        assert result['predicted_points'] > 0
        assert result['predicted_points'] < 60
        assert 0 <= result['confidence_score'] <= 100
        assert result['recommendation'] in ['OVER', 'UNDER', 'PASS']
        assert result['similar_games_count'] > 0
    
    def test_predict_insufficient_games(self, similarity_system, sample_features):
        """Test prediction with insufficient similar games"""
        # Only 3 games, none similar enough
        historical_games = [
            {
                'opponent_tier': 'tier_3_weak',
                'days_rest': 5,
                'is_home': True,
                'recent_form': 'cold',
                'points': 20.0
            }
            for i in range(3)
        ]
        
        result = similarity_system.predict(
            player_lookup='test-player',
            features=sample_features,
            historical_games=historical_games,
            betting_line=25.5
        )
        
        # Should return None with error
        assert result['predicted_points'] is None
        assert result['confidence_score'] == 0
        assert result['recommendation'] == 'PASS'
        assert 'error' in result
        assert 'Insufficient' in result['error']
    
    def test_predict_strong_over(self, similarity_system, sample_features):
        """Test prediction with strong OVER signal"""
        # Create similar games that all scored high
        historical_games = []
        for i in range(10):
            game = {
                'opponent_tier': 'tier_2_average',
                'days_rest': 1,
                'is_home': False,
                'recent_form': 'normal',
                'points': 30.0 + i * 0.5  # All scored 30+
            }
            historical_games.append(game)
        
        result = similarity_system.predict(
            player_lookup='test-player',
            features=sample_features,
            historical_games=historical_games,
            betting_line=25.5
        )
        
        # Should recommend OVER
        assert result['predicted_points'] > 28
        assert result['recommendation'] == 'OVER'
    
    def test_predict_pass_low_confidence(self, similarity_system, sample_features):
        """Test prediction passes with low confidence"""
        # Few games with high variance
        historical_games = [
            {
                'opponent_tier': 'tier_2_average',
                'days_rest': 1,
                'is_home': False,
                'recent_form': 'normal',
                'points': 15.0
            },
            {
                'opponent_tier': 'tier_2_average',
                'days_rest': 1,
                'is_home': False,
                'recent_form': 'normal',
                'points': 35.0
            }
        ]
        
        # Duplicate to get above min threshold (5 games)
        historical_games = historical_games * 3
        
        result = similarity_system.predict(
            player_lookup='test-player',
            features=sample_features,
            historical_games=historical_games,
            betting_line=25.5
        )
        
        # Low confidence should lead to PASS
        assert result['confidence_score'] < 70


# ============================================================================
# TEST CLASS 9: Integration with Mock Data
# ============================================================================

class TestMockDataIntegration:
    """Test integration with mock data generator"""
    
    def test_generate_and_predict(self, similarity_system, mock_generator):
        """Test full workflow with generated mock data"""
        player_lookup = 'lebron-james'
        game_date = date(2025, 1, 15)
        
        # Generate current features
        features = mock_generator.generate_all_features(
            player_lookup,
            game_date,
            tier='star',
            position='SF'
        )
        
        # Generate historical games
        historical_games = mock_generator.generate_historical_games(
            player_lookup,
            game_date,
            num_games=50,
            tier='star'
        )
        
        # Make prediction
        result = similarity_system.predict(
            player_lookup=player_lookup,
            features=features,
            historical_games=historical_games,
            betting_line=25.5
        )
        
        # Should work end-to-end
        assert result['predicted_points'] is not None
        assert result['similar_games_count'] >= 5
        assert result['confidence_score'] > 0
    
    def test_multiple_players(self, similarity_system, mock_generator):
        """Test predictions for multiple players"""
        game_date = date(2025, 1, 15)
        
        players = [
            ('player-1', 'superstar', 'PG'),
            ('player-2', 'starter', 'C'),
            ('player-3', 'rotation', 'SF')
        ]
        
        for player_lookup, tier, position in players:
            features = mock_generator.generate_all_features(
                player_lookup,
                game_date,
                tier=tier,
                position=position
            )
            
            historical_games = mock_generator.generate_historical_games(
                player_lookup,
                game_date,
                num_games=30,
                tier=tier
            )
            
            result = similarity_system.predict(
                player_lookup=player_lookup,
                features=features,
                historical_games=historical_games,
                betting_line=20.5
            )
            
            # All should work
            assert result is not None


# ============================================================================
# TEST CLASS 10: Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_empty_historical_games(self, similarity_system, sample_features):
        """Test with no historical games"""
        result = similarity_system.predict(
            player_lookup='rookie-player',
            features=sample_features,
            historical_games=[],
            betting_line=20.5
        )
        
        assert result['predicted_points'] is None
        assert result['recommendation'] == 'PASS'
        assert 'error' in result
    
    def test_no_betting_line(self, similarity_system, sample_features, sample_historical_games):
        """Test prediction without betting line"""
        result = similarity_system.predict(
            player_lookup='test-player',
            features=sample_features,
            historical_games=sample_historical_games,
            betting_line=None
        )
        
        # Should still predict, but PASS recommendation
        assert result['predicted_points'] is not None
        assert result['recommendation'] == 'PASS'
    
    def test_extreme_predictions_clamped(self, similarity_system, sample_features):
        """Test that extreme predictions are clamped to 0-60"""
        # Create games with extreme outcomes
        historical_games = [
            {
                'opponent_tier': 'tier_3_weak',
                'days_rest': 3,
                'is_home': True,
                'recent_form': 'hot',
                'points': 55.0  # Very high
            }
            for i in range(10)
        ]
        
        result = similarity_system.predict(
            player_lookup='test-player',
            features=sample_features,
            historical_games=historical_games,
            betting_line=25.5
        )
        
        # Should clamp to reasonable range
        assert 0 <= result['predicted_points'] <= 60


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
