# predictions/worker/prediction_systems/similarity_balanced_v1.py

"""
Similarity Balanced V1 Prediction System

Finds similar historical games and uses their outcomes to predict performance.
Uses bucketing approach for fast, robust similarity matching.

Algorithm:
1. Bucket current game context (opponent tier, rest, venue, form)
2. Find historical games with similar contexts
3. Score similarity (0-100 points)
4. Weight by similarity score
5. Apply minor adjustments

Version: 1.0
"""

from datetime import date
from typing import Dict, List, Optional
import numpy as np


class SimilarityBalancedV1:
    """
    Similarity-based prediction system using historical game matching
    
    Scoring breakdown:
    - Opponent strength: 40 points (3 tiers)
    - Rest situation: 30 points (4 buckets)
    - Venue: 15 points (home/away)
    - Recent form: 15 points (hot/normal/cold)
    
    Total: 100 points possible
    """
    
    def __init__(self):
        """Initialize Similarity Balanced V1 system"""
        self.system_id = 'similarity_balanced_v1'
        self.model_version = 'v1'
        self.min_similarity_threshold = 70  # Minimum similarity score
        self.max_matches = 20  # Maximum similar games to use
        self.min_matches_required = 5  # Need at least 5 similar games
    
    def predict(
        self,
        player_lookup: str,
        features: Dict,
        historical_games: List[Dict],
        betting_line: Optional[float] = None
    ) -> Dict:
        """
        Generate prediction using similar historical games
        
        Args:
            player_lookup: Player identifier
            features: Current game features (25 features)
            historical_games: List of historical games with context and outcomes
            betting_line: Current over/under line (optional)
        
        Returns:
            dict: Prediction with metadata
        """
        # Step 1: Extract current game context
        current_context = self._extract_game_context(features)
        
        # Step 2: Find similar games
        similar_games = self._find_similar_games(
            current_context,
            historical_games
        )
        
        # Step 3: Check if we have enough similar games
        if len(similar_games) < self.min_matches_required:
            return {
                'system_id': self.system_id,
                'model_version': self.model_version,
                'predicted_points': None,
                'confidence_score': 0.0,
                'recommendation': 'PASS',
                'error': f'Insufficient similar games (found {len(similar_games)}, need {self.min_matches_required})',
                'similar_games_count': len(similar_games)
            }
        
        # Step 4: Calculate weighted baseline from similar games
        baseline = self._calculate_weighted_baseline(similar_games)
        
        # Step 5: Apply minor adjustments (similarity already captures context)
        adjustments = self._calculate_adjustments(features)
        predicted_points = baseline + adjustments['total']
        
        # Clamp to reasonable range
        predicted_points = max(0, min(60, predicted_points))
        
        # Step 6: Calculate confidence
        confidence = self._calculate_confidence(similar_games, features)
        
        # Step 7: Generate recommendation
        recommendation = self._generate_recommendation(
            predicted_points,
            betting_line,
            confidence
        )
        
        return {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'predicted_points': round(predicted_points, 2),
            'confidence_score': round(confidence, 2),
            'recommendation': recommendation,
            'similar_games_count': len(similar_games),
            'avg_similarity_score': round(np.mean([g['similarity_score'] for g in similar_games]), 2),
            'baseline_from_similar': round(baseline, 2),
            'adjustments': adjustments
        }
    
    # ========================================================================
    # SIMILARITY MATCHING ALGORITHM
    # ========================================================================
    
    def _extract_game_context(self, features: Dict) -> Dict:
        """
        Extract relevant context from features for similarity matching
        
        Returns:
            dict: Game context (opponent tier, rest, venue, form)
        """
        # Determine opponent tier based on defensive rating
        opponent_def_rating = features.get('opponent_def_rating_last_15', 112)
        opponent_tier = self._get_opponent_tier(opponent_def_rating)
        
        # Get rest situation
        days_rest = int(features.get('days_rest', 1))
        rest_bucket = self._get_rest_bucket(days_rest)
        
        # Get venue
        is_home = bool(features.get('is_home', 0))
        
        # Determine recent form
        last_5 = features.get('points_avg_last_5', 0)
        season = features.get('points_avg_season', 0)
        form = self._get_form_bucket(last_5, season)
        
        return {
            'opponent_tier': opponent_tier,
            'opponent_def_rating': opponent_def_rating,
            'rest_bucket': rest_bucket,
            'days_rest': days_rest,
            'is_home': is_home,
            'form': form,
            'points_avg_last_5': last_5,
            'points_avg_season': season
        }
    
    def _get_opponent_tier(self, def_rating: float) -> str:
        """
        Categorize opponent into defensive strength tiers
        
        Args:
            def_rating: Opponent's defensive rating
        
        Returns:
            str: 'tier_1_elite', 'tier_2_average', or 'tier_3_weak'
        """
        if def_rating < 110:
            return 'tier_1_elite'
        elif def_rating < 115:
            return 'tier_2_average'
        else:
            return 'tier_3_weak'
    
    def _get_rest_bucket(self, days_rest: int) -> str:
        """
        Categorize rest days into buckets
        
        Args:
            days_rest: Days since last game (0-7+)
        
        Returns:
            str: Rest category
        """
        if days_rest == 0:
            return 'back_to_back'
        elif days_rest == 1:
            return 'one_day_rest'
        elif days_rest == 2:
            return 'two_days_rest'
        else:
            return 'well_rested'
    
    def _get_form_bucket(self, last_5_avg: float, season_avg: float) -> str:
        """
        Categorize player's recent form
        
        Args:
            last_5_avg: Points per game last 5 games
            season_avg: Points per game season average
        
        Returns:
            str: 'hot', 'normal', or 'cold'
        """
        diff = last_5_avg - season_avg
        
        if diff >= 3:
            return 'hot'
        elif diff <= -3:
            return 'cold'
        else:
            return 'normal'
    
    def _find_similar_games(
        self,
        current_context: Dict,
        historical_games: List[Dict]
    ) -> List[Dict]:
        """
        Find similar historical games using bucketing algorithm
        
        Args:
            current_context: Current game context
            historical_games: All available historical games
        
        Returns:
            list: Similar games with similarity scores, sorted by similarity
        """
        similar_games = []
        
        for game in historical_games:
            # Calculate similarity score
            similarity_score = self._calculate_similarity_score(
                current_context,
                game
            )
            
            # Only include if meets threshold
            if similarity_score >= self.min_similarity_threshold:
                similar_games.append({
                    **game,
                    'similarity_score': similarity_score
                })
        
        # Sort by similarity (highest first)
        similar_games.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        # Take top N matches
        return similar_games[:self.max_matches]
    
    def _calculate_similarity_score(
        self,
        current: Dict,
        historical: Dict
    ) -> float:
        """
        Calculate similarity score between current and historical game
        
        Scoring:
        - Opponent strength: 40 points
        - Rest situation: 30 points
        - Venue: 15 points
        - Recent form: 15 points
        
        Total: 100 points possible
        
        Args:
            current: Current game context
            historical: Historical game context
        
        Returns:
            float: Similarity score (0-100)
        """
        score = 0.0
        
        # Component 1: Opponent strength (40 points)
        score += self._opponent_similarity(current, historical)
        
        # Component 2: Rest situation (30 points)
        score += self._rest_similarity(current, historical)
        
        # Component 3: Venue (15 points)
        score += self._venue_similarity(current, historical)
        
        # Component 4: Recent form (15 points)
        score += self._form_similarity(current, historical)
        
        return score
    
    def _opponent_similarity(self, current: Dict, historical: Dict) -> float:
        """
        Score opponent strength similarity (0-40 points)
        
        Scoring:
        - Same tier: 40 points
        - Adjacent tier: 20 points
        - Opposite tiers: 0 points
        """
        current_tier = current['opponent_tier']
        historical_tier = historical.get('opponent_tier', 'tier_2_average')
        
        if current_tier == historical_tier:
            return 40.0
        
        # Check if adjacent
        tier_order = ['tier_1_elite', 'tier_2_average', 'tier_3_weak']
        try:
            current_idx = tier_order.index(current_tier)
            historical_idx = tier_order.index(historical_tier)
            
            if abs(current_idx - historical_idx) == 1:
                return 20.0
        except ValueError:
            pass
        
        return 0.0
    
    def _rest_similarity(self, current: Dict, historical: Dict) -> float:
        """
        Score rest similarity (0-30 points)
        
        Scoring:
        - Same rest bucket: 30 points
        - Adjacent bucket: 15 points
        - Non-adjacent: 0 points
        """
        current_rest = current['rest_bucket']
        historical_rest = self._get_rest_bucket(historical.get('days_rest', 1))
        
        if current_rest == historical_rest:
            return 30.0
        
        # Check if adjacent
        rest_order = ['back_to_back', 'one_day_rest', 'two_days_rest', 'well_rested']
        try:
            current_idx = rest_order.index(current_rest)
            historical_idx = rest_order.index(historical_rest)
            
            if abs(current_idx - historical_idx) == 1:
                return 15.0
        except ValueError:
            pass
        
        return 0.0
    
    def _venue_similarity(self, current: Dict, historical: Dict) -> float:
        """
        Score venue similarity (0-15 points)
        
        Scoring:
        - Same venue (both home or both away): 15 points
        - Different venue: 0 points
        """
        current_home = current['is_home']
        historical_home = historical.get('is_home', False)
        
        if current_home == historical_home:
            return 15.0
        else:
            return 0.0
    
    def _form_similarity(self, current: Dict, historical: Dict) -> float:
        """
        Score recent form similarity (0-15 points)
        
        Scoring:
        - Same form: 15 points
        - Different form: 5 points (still include, but lower weight)
        """
        current_form = current['form']
        historical_form = historical.get('recent_form', 'normal')
        
        if current_form == historical_form:
            return 15.0
        else:
            return 5.0  # Different form still has some value
    
    # ========================================================================
    # PREDICTION CALCULATION
    # ========================================================================
    
    def _calculate_weighted_baseline(self, similar_games: List[Dict]) -> float:
        """
        Calculate weighted average of similar games' points
        
        Uses similarity scores as weights (higher similarity = more weight)
        
        Args:
            similar_games: List of similar games with similarity scores
        
        Returns:
            float: Weighted baseline prediction
        """
        total_weight = 0.0
        weighted_sum = 0.0
        
        for game in similar_games:
            weight = game['similarity_score'] / 100.0  # Convert to 0-1 range
            points = game.get('points', 0)
            
            weighted_sum += points * weight
            total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        return weighted_sum / total_weight
    
    def _calculate_adjustments(self, features: Dict) -> Dict:
        """
        Apply minor adjustments to baseline
        
        Note: Adjustments are reduced compared to other systems because
        similarity matching already captures most context
        
        Args:
            features: Current game features
        
        Returns:
            dict: Adjustment breakdown
        """
        # Fatigue adjustment (reduced)
        fatigue_score = features.get('fatigue_score', 70)
        fatigue_adj = (fatigue_score - 70) * 0.015  # Reduced from 0.02
        
        # Zone matchup adjustment (reduced)
        zone_score = features.get('shot_zone_mismatch_score', 0)
        zone_adj = zone_score * 0.4  # Reduced from 0.5
        
        # Pace adjustment (reduced)
        pace_score = features.get('pace_score', 0)
        pace_adj = pace_score * 0.8  # Reduced from 1.0
        
        # Usage adjustment (reduced)
        usage_score = features.get('usage_spike_score', 0)
        usage_adj = usage_score * 0.8  # Reduced from 1.0
        
        # Venue adjustment (reduced)
        is_home = features.get('is_home', 0)
        venue_adj = 0.8 if is_home else -0.5  # Reduced from 1.2/-0.8
        
        total = fatigue_adj + zone_adj + pace_adj + usage_adj + venue_adj
        
        return {
            'fatigue': round(fatigue_adj, 2),
            'zone_matchup': round(zone_adj, 2),
            'pace': round(pace_adj, 2),
            'usage': round(usage_adj, 2),
            'venue': round(venue_adj, 2),
            'total': round(total, 2)
        }
    
    def _calculate_confidence(
        self,
        similar_games: List[Dict],
        features: Dict
    ) -> float:
        """
        Calculate confidence score
        
        Factors:
        - Number of similar games found (±20 points)
        - Average similarity score (±20 points)
        - Outcome consistency in similar games (±10 points)
        
        Args:
            similar_games: List of similar games
            features: Current game features
        
        Returns:
            float: Confidence score (0-100)
        """
        confidence = 50.0  # Base confidence
        
        # Sample size bonus (±20 points with stronger penalties for low counts)
        count = len(similar_games)
        if count >= 15:
            confidence += 20
        elif count >= 10:
            confidence += 15
        elif count >= 7:
            confidence += 10
        elif count >= 5:
            confidence -= 15  # Minimum required, apply strong penalty for low count
        else:
            confidence -= 20  # Below minimum, shouldn't happen
        
        # Similarity quality bonus (±20 points)
        avg_similarity = np.mean([g['similarity_score'] for g in similar_games])
        if avg_similarity >= 85:
            confidence += 20
        elif avg_similarity >= 75:
            confidence += 15
        elif avg_similarity >= 70:
            confidence += 10
        else:
            confidence += 5
        
        # Outcome consistency bonus (±15 points with stronger penalties)
        points = [g.get('points', 0) for g in similar_games]
        std_dev = np.std(points)
        if std_dev < 4:
            confidence += 15  # Very consistent
        elif std_dev < 6:
            confidence += 8   # Moderately consistent
        elif std_dev < 8:
            confidence += 3   # Some variance
        else:
            confidence -= 5   # High variance - penalty!
        
        return max(0, min(100, confidence))
    
    def _generate_recommendation(
        self,
        predicted_points: float,
        betting_line: Optional[float],
        confidence: float
    ) -> str:
        """
        Generate betting recommendation
        
        Args:
            predicted_points: System's prediction
            betting_line: Current betting line
            confidence: Confidence score
        
        Returns:
            str: 'OVER', 'UNDER', or 'PASS'
        """
        # Need betting line to make recommendation
        if betting_line is None:
            return 'PASS'
        
        # Minimum confidence threshold
        if confidence < 65:  # Similarity requires higher confidence
            return 'PASS'
        
        # Calculate edge
        edge = predicted_points - betting_line
        min_edge = 2.0
        
        if edge >= min_edge:
            return 'OVER'
        elif edge <= -min_edge:
            return 'UNDER'
        else:
            return 'PASS'