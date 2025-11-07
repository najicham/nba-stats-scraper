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
        self.seed = seed
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
            # Store random state for reproducibility
            self._random_state = random.getstate()
            self._np_random_state = np.random.get_state()
    
    # ========================================================================
    # CURRENT GAME FEATURES (25 features for today's prediction)
    # ========================================================================
    
    def generate_all_features(
        self,
        player_lookup: str,
        game_date: date,
        tier: str = None,
        position: str = None
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
        # For reproducibility: create deterministic seed from player + date + base seed
        if self.seed is not None:
            player_seed = hash((player_lookup, game_date, self.seed)) % (2**31)
            random.seed(player_seed)
            np.random.seed(player_seed)
        
        # Infer tier and position from player name if not provided
        if tier is None:
            tier = self._infer_tier(player_lookup)
        if position is None:
            position = self._infer_position(player_lookup)
        
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
        team = self._generate_team_context(tier)
        
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
            features_dict['games_played_last_7_days'],  # Index 4 - was minutes
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
        # Feature names in order matching features_array
        feature_names = [
            'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
            'points_std_last_10', 'games_played_last_7_days', 'fatigue_score',
            'shot_zone_mismatch_score', 'pace_score', 'usage_spike_score',
            'referee_favorability_score', 'look_ahead_pressure_score',
            'matchup_history_score', 'momentum_score', 'opponent_def_rating_last_15',
            'opponent_pace_last_15', 'is_home', 'days_rest', 'back_to_back',
            'paint_rate_last_10', 'mid_range_rate_last_10', 'three_pt_rate_last_10',
            'assisted_rate_last_10', 'team_pace_last_10', 'team_off_rating_last_10',
            'usage_rate_last_10'
        ]

        return {
            'player_lookup': player_lookup,
            'game_date': game_date,
            'player_tier': tier,
            'player_position': position,
            'feature_count': 25,
            'feature_version': 'v1_baseline_25',
            'data_source': 'mock',
            'features_array': features_array,
            'features': features_array,  # Alias for test compatibility
            'feature_names': feature_names,  # Feature names list
            **features_dict,
            'feature_quality_score': 85.0  # Mock data is good quality
        }
    
    
    def _infer_tier(self, player_lookup: str) -> str:
        """Infer player tier from name"""
        player_lower = player_lookup.lower()
        
        # Superstars
        if any(name in player_lower for name in ['lebron', 'curry', 'durant', 'jokic', 'giannis', 'luka']):
            return 'superstar'
        
        # Stars
        if any(name in player_lower for name in ['jordan', 'embiid', 'tatum', 'booker', 'mitchell']):
            return 'star'
        
        # Bench
        if 'unknown' in player_lower or 'bench' in player_lower:
            return 'bench'
        
        # Default to starter
        return 'starter'
    
    def _infer_position(self, player_lookup: str) -> str:
        """Infer position from player name"""
        player_lower = player_lookup.lower()
        
        # Centers
        if any(name in player_lower for name in ['embiid', 'jokic', 'towns', 'ayton', 'gobert']):
            return 'C'
        
        # Point Guards
        if any(name in player_lower for name in ['curry', 'luka', 'young', 'morant', 'paul']):
            return 'PG'
        
        # Power Forwards
        if any(name in player_lower for name in ['giannis', 'davis', 'porzingis']):
            return 'PF'
        
        # Shooting Guards  
        if any(name in player_lower for name in ['booker', 'mitchell', 'lavine', 'jordan']):
            return 'SG'
        
        # Default to SF
        return 'SF'
    
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
        
        # Minutes by tier
        if tier in ['superstar', 'star']:
            minutes = round(random.uniform(30, 38), 1)
        elif tier == 'starter':
            minutes = round(random.uniform(25, 33), 1)
        else:
            minutes = round(random.uniform(15, 28), 1)
        
        return {
            'points_avg_last_5': round(last_5, 1),
            'points_avg_last_10': round(last_10, 1),
            'points_avg_season': round(season, 1),
            'points_std_last_10': round(variance, 1),
            'minutes_avg_last_10': minutes,
            'games_played_last_7_days': random.randint(2, 3)  # Missing field!
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
        
        # Assisted rate by position (centers catch and finish more)
        if position == 'C':
            assisted = random.uniform(60, 80)
        elif position == 'PF':
            assisted = random.uniform(55, 75)
        elif position in ['SF', 'SG']:
            assisted = random.uniform(50, 70)
        else:  # PG
            assisted = random.uniform(40, 60)
        
        return {
            'paint_rate_last_10': round(paint * 100, 1),
            'mid_range_rate_last_10': round(mid * 100, 1),
            'three_pt_rate_last_10': round(three * 100, 1),
            'assisted_rate_last_10': round(assisted, 1),
            # Aliases for zone matchup (fractions not percentages)
            'pct_paint': round(paint, 3),
            'pct_mid_range': round(mid, 3),
            'pct_three': round(three, 3),
            'pct_free_throw': round((1.0 - paint - mid - three), 3)  # Remaining shots
        }
    
    def _generate_team_context(self, tier: str) -> Dict:
        """Generate features 22-24: Team context"""
        # Usage rate by tier
        if tier == 'superstar':
            usage = random.uniform(28, 35)
        elif tier == 'star':
            usage = random.uniform(24, 30)
        elif tier == 'starter':
            usage = random.uniform(18, 25)
        elif tier == 'rotation':
            usage = random.uniform(12, 20)
        else:  # bench
            usage = random.uniform(8, 15)
        
        return {
            'team_pace_last_10': round(random.uniform(95, 105), 1),
            'team_off_rating_last_10': round(random.uniform(105, 120), 1),
            'usage_rate_last_10': round(usage, 1)
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
        attempts = 0
        max_attempts = num_games * 3  # Allow retries for offseason dates
        
        while len(dates) < num_games and attempts < max_attempts:
            attempts += 1
            
            # Random date within lookback period
            days_ago = random.randint(1, lookback_days)
            game_date = current_date - timedelta(days=days_ago)
            
            # Skip if in offseason (May-September)
            if game_date.month in [5, 6, 7, 8, 9]:
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
        players = 10,
        game_date: Optional[date] = None
    ) -> Dict:
        """
        Generate features for multiple players
        
        Args:
            players: Either list of player names or integer count (default: 10)
            game_date: Game date (default: today)
        
        Returns:
            dict: Dictionary mapping player_lookup to features (if list provided)
                  OR list of features (if integer provided)
        """
        if game_date is None:
            game_date = date.today()
        
        # Handle both list of players and integer count
        if isinstance(players, list):
            # Generate for specific players
            batch = {}
            for player_lookup in players:
                features = self.generate_all_features(
                    player_lookup,
                    game_date
                )
                batch[player_lookup] = features
            return batch
        else:
            # Generate for N random players
            num_players = players
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