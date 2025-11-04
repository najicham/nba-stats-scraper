# predictions/shared/mock_data_generator.py

"""
Mock Data Generator for Phase 5 Predictions

Generates realistic NBA player features and historical games for testing
prediction systems without requiring Phase 4 to be complete.

Version: 2.0 (Added historical games support for Similarity system)
"""

import random
from datetime import date, timedelta
from typing import Dict, List, Optional
import numpy as np


class MockDataGenerator:
    """
    Generate realistic mock data for NBA predictions
    
    Capabilities:
    - Generate 25 features for current game
    - Generate historical games for similarity matching
    - Support different player tiers and positions
    - Maintain consistency across related features
    """
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize mock data generator
        
        Args:
            seed: Random seed for reproducibility (default: None)
        """
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        
        self.seed = seed
    
    # ========================================================================
    # CURRENT GAME FEATURES (25 features for today's prediction)
    # ========================================================================
    
    def generate_all_features(
        self,
        player_lookup: str,
        game_date: date,
        tier: str = 'starter',
        position: str = 'SF'
    ) -> Dict:
        """
        Generate all 25 features for a player's upcoming game
        
        Args:
            player_lookup: Player identifier (e.g., 'lebron-james')
            game_date: Date of upcoming game
            tier: Player tier ('superstar', 'star', 'starter', 'rotation', 'bench')
            position: Position ('PG', 'SG', 'SF', 'PF', 'C')
        
        Returns:
            dict: All 25 features + metadata
        """
        # Base scoring by tier
        base_ppg = self._get_base_ppg(tier)
        
        # Generate recent performance (features 0-4)
        recent_perf = self._generate_recent_performance(base_ppg, tier)
        
        # Generate composite factors (features 5-12)
        composite = self._generate_composite_factors()
        
        # Generate matchup context (features 13-17)
        matchup = self._generate_matchup_context(position)
        
        # Generate shot zones (features 18-21)
        zones = self._generate_shot_zones(position)
        
        # Generate team context (features 22-24)
        team = self._generate_team_context()
        
        # Combine all features
        features_dict = {
            **recent_perf,
            **composite,
            **matchup,
            **zones,
            **team
        }
        
        # Create features array
        features_array = [
            features_dict['points_avg_last_5'],
            features_dict['points_avg_last_10'],
            features_dict['points_avg_season'],
            features_dict['points_std_last_10'],
            features_dict['minutes_avg_last_10'],
            features_dict['fatigue_score'],
            features_dict['shot_zone_mismatch_score'],
            features_dict['pace_score'],
            features_dict['usage_spike_score'],
            features_dict['referee_favorability_score'],
            features_dict['look_ahead_pressure_score'],
            features_dict['matchup_history_score'],
            features_dict['momentum_score'],
            features_dict['opponent_def_rating_last_15'],
            features_dict['opponent_pace_last_15'],
            features_dict['is_home'],
            features_dict['days_rest'],
            features_dict['back_to_back'],
            features_dict['paint_rate_last_10'],
            features_dict['mid_range_rate_last_10'],
            features_dict['three_pt_rate_last_10'],
            features_dict['assisted_rate_last_10'],
            features_dict['team_pace_last_10'],
            features_dict['team_off_rating_last_10'],
            features_dict['usage_rate_last_10']
        ]
        
        return {
            'player_lookup': player_lookup,
            'game_date': game_date,
            'feature_count': 25,
            'feature_version': 'v1_baseline_25',
            'data_source': 'mock',
            'features_array': features_array,
            **features_dict,
            'feature_quality_score': 85.0  # Mock data is good quality
        }
    
    def _get_base_ppg(self, tier: str) -> float:
        """Get base PPG by player tier"""
        tier_ranges = {
            'superstar': (28, 32),
            'star': (22, 27),
            'starter': (14, 21),
            'rotation': (8, 13),
            'bench': (4, 7)
        }
        low, high = tier_ranges.get(tier, (14, 21))
        return random.uniform(low, high)
    
    def _generate_recent_performance(self, base_ppg: float, tier: str) -> Dict:
        """Generate features 0-4: Recent performance"""
        # Add variance for recent games
        variance = random.uniform(2, 5)
        
        last_5 = np.clip(base_ppg + random.uniform(-3, 3), 0, 60)
        last_10 = np.clip(base_ppg + random.uniform(-2, 2), 0, 60)
        season = base_ppg
        
        return {
            'points_avg_last_5': round(last_5, 1),
            'points_avg_last_10': round(last_10, 1),
            'points_avg_season': round(season, 1),
            'points_std_last_10': round(variance, 1),
            'minutes_avg_last_10': round(random.uniform(20, 38), 1)
        }
    
    def _generate_composite_factors(self) -> Dict:
        """Generate features 5-12: Composite factors"""
        return {
            'fatigue_score': round(random.uniform(40, 100), 1),
            'shot_zone_mismatch_score': round(random.uniform(-10, 10), 1),
            'pace_score': round(random.uniform(-3, 3), 1),
            'usage_spike_score': round(random.uniform(-3, 3), 1),
            'referee_favorability_score': 0.0,  # Deferred
            'look_ahead_pressure_score': 0.0,  # Deferred
            'matchup_history_score': 0.0,  # Deferred
            'momentum_score': 0.0  # Deferred
        }
    
    def _generate_matchup_context(self, position: str) -> Dict:
        """Generate features 13-17: Matchup context"""
        return {
            'opponent_def_rating_last_15': round(random.uniform(105, 120), 1),
            'opponent_pace_last_15': round(random.uniform(95, 105), 1),
            'is_home': float(random.choice([0, 1])),
            'days_rest': float(random.choice([0, 1, 2, 3, 4, 5])),
            'back_to_back': float(random.choice([0, 1]))
        }
    
    def _generate_shot_zones(self, position: str) -> Dict:
        """Generate features 18-21: Shot zones by position"""
        # Position-specific shot distributions
        if position == 'C':
            paint = random.uniform(0.50, 0.70)
            mid = random.uniform(0.10, 0.20)
            three = 1.0 - paint - mid
        elif position in ['PF']:
            paint = random.uniform(0.35, 0.50)
            mid = random.uniform(0.15, 0.25)
            three = 1.0 - paint - mid
        elif position in ['SF', 'SG']:
            paint = random.uniform(0.20, 0.35)
            mid = random.uniform(0.15, 0.25)
            three = 1.0 - paint - mid
        else:  # PG
            paint = random.uniform(0.15, 0.30)
            mid = random.uniform(0.10, 0.20)
            three = 1.0 - paint - mid
        
        # Normalize to ensure sum = 1.0
        total = paint + mid + three
        paint /= total
        mid /= total
        three /= total
        
        return {
            'paint_rate_last_10': round(paint * 100, 1),
            'mid_range_rate_last_10': round(mid * 100, 1),
            'three_pt_rate_last_10': round(three * 100, 1),
            'assisted_rate_last_10': round(random.uniform(40, 80), 1)
        }
    
    def _generate_team_context(self) -> Dict:
        """Generate features 22-24: Team context"""
        return {
            'team_pace_last_10': round(random.uniform(95, 105), 1),
            'team_off_rating_last_10': round(random.uniform(105, 120), 1),
            'usage_rate_last_10': round(random.uniform(18, 32), 1)
        }
    
    # ========================================================================
    # HISTORICAL GAMES (for Similarity system)
    # ========================================================================
    
    def generate_historical_games(
        self,
        player_lookup: str,
        current_date: date,
        num_games: int = 50,
        lookback_days: int = 730,  # 2 years
        tier: str = 'starter'
    ) -> List[Dict]:
        """
        Generate realistic historical games for similarity matching
        
        Args:
            player_lookup: Player identifier
            current_date: Current game date (games will be before this)
            num_games: Number of historical games to generate
            lookback_days: Days to look back (default: 730 = 2 years)
            tier: Player tier (affects scoring)
        
        Returns:
            list: Historical games with outcomes and context
        """
        games = []
        base_ppg = self._get_base_ppg(tier)
        
        # Generate games distributed across lookback period
        dates = self._generate_game_dates(current_date, num_games, lookback_days)
        
        for game_date in dates:
            game = self._generate_single_historical_game(
                player_lookup,
                game_date,
                base_ppg,
                tier
            )
            games.append(game)
        
        return games
    
    def _generate_game_dates(
        self,
        current_date: date,
        num_games: int,
        lookback_days: int
    ) -> List[date]:
        """
        Generate realistic game dates (NBA season schedule)
        
        Games are more frequent during season (Oct-Apr), sparse in summer
        """
        dates = []
        
        for _ in range(num_games):
            # Random date within lookback period
            days_ago = random.randint(1, lookback_days)
            game_date = current_date - timedelta(days=days_ago)
            
            # Skip if in offseason (May-September)
            if game_date.month in [5, 6, 7, 8, 9]:
                # Retry
                continue
            
            dates.append(game_date)
        
        # Sort chronologically (most recent first)
        dates.sort(reverse=True)
        
        return dates[:num_games]
    
    def _generate_single_historical_game(
        self,
        player_lookup: str,
        game_date: date,
        base_ppg: float,
        tier: str
    ) -> Dict:
        """
        Generate a single historical game with context and outcome
        
        Returns:
            dict: Game with context (opponent, rest, venue, form) and outcome (points)
        """
        # Generate opponent tier
        opponent_tier = random.choice(['tier_1_elite', 'tier_2_average', 'tier_3_weak'])
        
        # Generate rest situation
        days_rest = random.choice([0, 1, 2, 3, 4, 5, 6, 7])
        back_to_back = 1 if days_rest == 0 else 0
        
        # Generate venue
        is_home = random.choice([True, False])
        
        # Generate recent form
        form = random.choice(['hot', 'normal', 'cold'])
        
        # Generate points based on context
        points = self._generate_game_points(
            base_ppg,
            opponent_tier,
            days_rest,
            is_home,
            form
        )
        
        # Generate minutes played
        minutes = round(random.uniform(25, 38), 1)
        
        # Generate opponent details
        opponent_abbr = self._generate_opponent_abbr()
        opponent_def_rating = self._get_def_rating_for_tier(opponent_tier)
        
        return {
            'player_lookup': player_lookup,
            'game_date': game_date,
            'game_id': f"{opponent_abbr}-{game_date.strftime('%Y%m%d')}",
            'opponent_team_abbr': opponent_abbr,
            'opponent_tier': opponent_tier,
            'opponent_def_rating': opponent_def_rating,
            'days_rest': days_rest,
            'back_to_back': back_to_back,
            'is_home': is_home,
            'recent_form': form,
            'points': points,
            'minutes_played': minutes
        }
    
    def _generate_game_points(
        self,
        base_ppg: float,
        opponent_tier: str,
        days_rest: int,
        is_home: bool,
        form: str
    ) -> float:
        """
        Generate points scored based on game context
        
        Simulates realistic scoring patterns:
        - Tier 1 defense: -3 to -5 points
        - Tier 3 defense: +2 to +4 points
        - Back-to-back: -2 to -3 points
        - Home: +1 to +2 points
        - Hot form: +3 to +5 points
        - Cold form: -3 to -5 points
        """
        points = base_ppg
        
        # Opponent strength adjustment
        if opponent_tier == 'tier_1_elite':
            points += random.uniform(-5, -3)
        elif opponent_tier == 'tier_3_weak':
            points += random.uniform(2, 4)
        
        # Rest adjustment
        if days_rest == 0:  # Back-to-back
            points += random.uniform(-3, -2)
        elif days_rest >= 3:  # Well-rested
            points += random.uniform(0.5, 1.5)
        
        # Venue adjustment
        if is_home:
            points += random.uniform(1, 2)
        else:
            points += random.uniform(-1, -0.5)
        
        # Form adjustment
        if form == 'hot':
            points += random.uniform(3, 5)
        elif form == 'cold':
            points += random.uniform(-5, -3)
        
        # Add game variance
        points += random.uniform(-3, 3)
        
        return round(max(0, min(60, points)), 1)
    
    def _generate_opponent_abbr(self) -> str:
        """Generate random NBA team abbreviation"""
        teams = [
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN',
            'DET', 'GSW', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA',
            'MIL', 'MIN', 'NOP', 'NYK', 'OKC', 'ORL', 'PHI', 'PHX',
            'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        ]
        return random.choice(teams)
    
    def _get_def_rating_for_tier(self, tier: str) -> float:
        """Get defensive rating range for opponent tier"""
        if tier == 'tier_1_elite':
            return round(random.uniform(105, 110), 1)
        elif tier == 'tier_2_average':
            return round(random.uniform(110, 115), 1)
        else:  # tier_3_weak
            return round(random.uniform(115, 122), 1)
    
    # ========================================================================
    # BATCH GENERATION (for testing multiple players/scenarios)
    # ========================================================================
    
    def generate_batch(
        self,
        num_players: int = 10,
        game_date: Optional[date] = None
    ) -> List[Dict]:
        """
        Generate features for multiple players
        
        Args:
            num_players: Number of players to generate
            game_date: Game date (default: today)
        
        Returns:
            list: Features for each player
        """
        if game_date is None:
            game_date = date.today()
        
        tiers = ['superstar', 'star', 'starter', 'rotation', 'bench']
        positions = ['PG', 'SG', 'SF', 'PF', 'C']
        
        batch = []
        for i in range(num_players):
            tier = random.choice(tiers)
            position = random.choice(positions)
            player_lookup = f"player-{i}"
            
            features = self.generate_all_features(
                player_lookup,
                game_date,
                tier,
                position
            )
            batch.append(features)
        
        return batch


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_mock_features(player_lookup: str, game_date: date, seed: Optional[int] = None) -> Dict:
    """
    Convenience function to get mock features for a player
    
    Args:
        player_lookup: Player identifier
        game_date: Game date
        seed: Random seed for reproducibility
    
    Returns:
        dict: 25 features + metadata
    """
    generator = MockDataGenerator(seed=seed)
    return generator.generate_all_features(player_lookup, game_date)


def get_mock_historical_games(
    player_lookup: str,
    current_date: date,
    num_games: int = 50,
    seed: Optional[int] = None
) -> List[Dict]:
    """
    Convenience function to get mock historical games
    
    Args:
        player_lookup: Player identifier
        current_date: Current date
        num_games: Number of games to generate
        seed: Random seed for reproducibility
    
    Returns:
        list: Historical games with context and outcomes
    """
    generator = MockDataGenerator(seed=seed)
    return generator.generate_historical_games(
        player_lookup,
        current_date,
        num_games
    )
