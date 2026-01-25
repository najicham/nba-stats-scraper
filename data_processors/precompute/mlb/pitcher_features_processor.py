#!/usr/bin/env python3
"""
MLB Pitcher Features Processor - Phase 4 Precompute
Computes 25-feature vector for pitcher strikeout predictions.

Key Feature: Bottom-up model - Sum of individual batter K rates.

Dependencies:
- mlb_analytics.pitcher_game_summary (rolling K averages)
- mlb_analytics.batter_game_summary (rolling K rates)
- mlb_raw.mlb_schedule (probable pitchers)
- mlb_raw.mlb_lineup_batters (batting order)
- mlb_raw.oddsa_pitcher_props (betting lines)

Output: mlb_precompute.pitcher_ml_features
"""

import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Any
from google.cloud import bigquery
import hashlib

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

logger = logging.getLogger(__name__)

FEATURE_VERSION = "v2_35features"


class MlbPitcherFeaturesProcessor(PrecomputeProcessorBase):
    """Computes pitcher ML features for strikeout prediction."""

    def __init__(self):
        super().__init__()
        self.processor_name = "mlb_pitcher_features"
        self.target_table = "mlb_precompute.pitcher_ml_features"
        self.feature_version = FEATURE_VERSION

    def get_dependencies(self) -> dict:
        """Define upstream data dependencies for this processor."""
        return {
            'mlb_analytics.pitcher_game_summary': {
                'description': 'Pitcher rolling stats',
                'date_field': 'game_date',
                'check_type': 'lookback',
                'lookback_games': 5,
                'expected_count_min': 1,
                'max_age_hours': 48,
                'critical': False  # We can still run with partial data
            },
            'mlb_analytics.batter_game_summary': {
                'description': 'Batter K rates',
                'date_field': 'game_date',
                'check_type': 'lookback',
                'lookback_games': 5,
                'expected_count_min': 1,
                'max_age_hours': 48,
                'critical': False
            }
        }

    def process_date(self, game_date: date) -> Dict[str, Any]:
        """Process features for all pitchers on a given date."""
        logger.info(f"Processing pitcher features for {game_date}")

        # 1. Get scheduled games with probable pitchers
        schedule = self._get_schedule(game_date)
        if not schedule:
            logger.info(f"No games scheduled for {game_date}")
            return {"status": "no_games", "processed": 0}

        # 2. Get lineup data (which batters face each pitcher)
        lineups = self._get_lineups(game_date)

        # 3. Get pitcher analytics (rolling K averages)
        pitcher_stats = self._get_pitcher_analytics(game_date)

        # 4. Get batter analytics (rolling K rates)
        batter_stats = self._get_batter_analytics(game_date)

        # 5. Get betting lines
        betting_lines = self._get_betting_lines(game_date)

        # 6. Get pitcher splits (home/away, day/night)
        pitcher_splits = self._get_pitcher_splits(game_date)

        # 7. Get game lines (totals, moneylines)
        game_lines = self._get_game_lines(game_date)

        # 8. Get ballpark factors
        ballpark_factors = self._get_ballpark_factors()

        # 9. Get pitcher vs team history
        pitcher_vs_team = self._get_pitcher_vs_team(game_date)

        # 10. Get lineup K analysis (V1 features)
        lineup_analysis = self._get_lineup_analysis(game_date)

        # 11. Get umpire data (V1 features)
        umpire_data = self._get_umpire_data(game_date)

        # 12. Get innings projections (V1 features)
        innings_projections = self._get_innings_projections(game_date)

        # 13. Get pitcher arsenal data (V2 features)
        arsenal_data = self._get_arsenal_data(game_date)

        # 14. Get batter K profiles (V2 features)
        batter_profiles = self._get_batter_profiles(game_date)

        # 15. Get batter splits for platoon (V1/V2 features)
        batter_splits = self._get_batter_splits(game_date)

        # 16. Get pitcher handedness
        pitcher_hands = self._get_pitcher_handedness()

        # 17. Compute features for each pitcher
        features_list = []
        for game in schedule:
            for side in ['home', 'away']:
                pitcher_lookup = game.get(f'{side}_pitcher_lookup')
                if not pitcher_lookup:
                    continue

                features = self._compute_pitcher_features(
                    pitcher_lookup=pitcher_lookup,
                    game=game,
                    side=side,
                    lineups=lineups,
                    pitcher_stats=pitcher_stats,
                    batter_stats=batter_stats,
                    betting_lines=betting_lines,
                    pitcher_splits=pitcher_splits,
                    game_lines=game_lines,
                    ballpark_factors=ballpark_factors,
                    pitcher_vs_team=pitcher_vs_team,
                    lineup_analysis=lineup_analysis,
                    umpire_data=umpire_data,
                    innings_projections=innings_projections,
                    arsenal_data=arsenal_data,
                    batter_profiles=batter_profiles,
                    batter_splits=batter_splits,
                    pitcher_hands=pitcher_hands,
                    game_date=game_date
                )
                if features:
                    features_list.append(features)

        # 18. Write to BigQuery
        if features_list:
            rows_written = self._write_features(features_list, game_date)
            logger.info(f"Wrote {rows_written} pitcher features for {game_date}")
            return {"status": "success", "processed": rows_written}

        return {"status": "no_features", "processed": 0}

    def _get_schedule(self, game_date: date) -> List[Dict]:
        """Get scheduled games with probable pitchers."""
        query = f"""
        SELECT
            game_pk,
            game_date,
            home_team_abbr,
            away_team_abbr,
            home_pitcher_id,
            home_pitcher_name,
            home_pitcher_lookup,
            away_pitcher_id,
            away_pitcher_name,
            away_pitcher_lookup,
            venue_name,
            game_datetime,
            is_day_game
        FROM `{self.project_id}.mlb_raw.mlb_schedule`
        WHERE game_date = '{game_date}'
          AND status IN ('Scheduled', 'Pre-Game', 'In Progress')
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return df.to_dict('records')
        except Exception as e:
            logger.warning(f"Schedule query failed: {e}")
            return []

    def _get_lineups(self, game_date: date) -> Dict[str, List[Dict]]:
        """Get lineups by game_pk."""
        query = f"""
        SELECT
            game_pk,
            team_abbr,
            player_lookup,
            batting_order,
            position
        FROM `{self.project_id}.mlb_raw.mlb_lineup_batters`
        WHERE game_date = '{game_date}'
        ORDER BY game_pk, batting_order
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            # Group by game_pk
            lineups = {}
            for _, row in df.iterrows():
                key = str(row['game_pk'])
                if key not in lineups:
                    lineups[key] = {'home': [], 'away': []}
                # Determine side based on team in the game
                lineups[key].setdefault(row['team_abbr'], []).append(row.to_dict())
            return lineups
        except Exception as e:
            logger.warning(f"Lineups query failed: {e}")
            return {}

    def _get_pitcher_analytics(self, game_date: date) -> Dict[str, Dict]:
        """Get pitcher rolling stats."""
        query = f"""
        SELECT
            player_lookup,
            game_date,
            k_avg_last_3,
            k_avg_last_5,
            k_avg_last_10,
            k_std_last_10,
            k_per_9_rolling_10,
            ip_avg_last_5,
            season_k_per_9,
            season_era,
            season_whip,
            season_games,
            season_k_total,
            days_rest,
            games_last_30_days
        FROM `{self.project_id}.mlb_analytics.pitcher_game_summary`
        WHERE player_lookup IN (
            SELECT DISTINCT home_pitcher_lookup FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date = '{game_date}'
            UNION DISTINCT
            SELECT DISTINCT away_pitcher_lookup FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date = '{game_date}'
        )
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['player_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Pitcher analytics query failed: {e}")
            return {}

    def _get_batter_analytics(self, game_date: date) -> Dict[str, Dict]:
        """Get batter rolling K rates."""
        query = f"""
        SELECT
            player_lookup,
            k_rate_last_5,
            k_rate_last_10,
            k_avg_last_5,
            k_avg_last_10,
            season_k_rate,
            ab_avg_last_10
        FROM `{self.project_id}.mlb_analytics.batter_game_summary`
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['player_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Batter analytics query failed: {e}")
            return {}

    def _get_betting_lines(self, game_date: date) -> Dict[str, Dict]:
        """Get pitcher strikeout betting lines."""
        query = f"""
        SELECT
            player_lookup,
            line_point,
            over_price,
            under_price
        FROM `{self.project_id}.mlb_raw.oddsa_pitcher_props`
        WHERE game_date = '{game_date}'
          AND market_key = 'pitcher_strikeouts'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY scraped_at DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['player_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Betting lines query failed: {e}")
            return {}

    def _get_pitcher_splits(self, game_date: date) -> Dict[str, Dict]:
        """Get pitcher home/away and day/night splits."""
        query = f"""
        SELECT
            player_lookup,
            split_category,
            k_per_9,
            era,
            games
        FROM `{self.project_id}.mlb_raw.bdl_pitcher_splits`
        WHERE snapshot_date <= '{game_date}'
          AND split_category IN ('home', 'away', 'day', 'night')
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup, split_category ORDER BY snapshot_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            # Organize by player_lookup with all splits
            splits = {}
            for _, row in df.iterrows():
                player = row['player_lookup']
                if player not in splits:
                    splits[player] = {}
                splits[player][row['split_category']] = row.to_dict()
            return splits
        except Exception as e:
            logger.warning(f"Pitcher splits query failed: {e}")
            return {}

    def _get_game_lines(self, game_date: date) -> Dict[str, Dict]:
        """Get game totals and moneylines."""
        query = f"""
        SELECT
            home_team_abbr,
            away_team_abbr,
            total_over_under,
            home_moneyline,
            away_moneyline
        FROM `{self.project_id}.mlb_raw.oddsa_game_lines`
        WHERE game_date = '{game_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY home_team_abbr, away_team_abbr ORDER BY scraped_at DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            # Key by team matchup
            lines = {}
            for _, row in df.iterrows():
                key = f"{row['away_team_abbr']}@{row['home_team_abbr']}"
                lines[key] = row.to_dict()
            return lines
        except Exception as e:
            logger.warning(f"Game lines query failed: {e}")
            return {}

    def _get_ballpark_factors(self) -> Dict[str, Dict]:
        """Get ballpark K factors."""
        query = f"""
        SELECT
            team_abbr,
            venue_name,
            strikeouts_factor,
            runs_factor
        FROM `{self.project_id}.mlb_reference.ballpark_factors`
        WHERE season_year = EXTRACT(YEAR FROM CURRENT_DATE())
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['team_abbr']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Ballpark factors query failed: {e}")
            return {}

    def _get_pitcher_vs_team(self, game_date: date) -> Dict[str, Dict]:
        """Get pitcher historical stats vs specific teams."""
        query = f"""
        SELECT
            pitcher_lookup,
            opponent_lookup as opponent_team,
            at_bats,
            strikeouts,
            k_rate
        FROM `{self.project_id}.mlb_raw.bdl_player_versus`
        WHERE opponent_type = 'team'
          AND snapshot_date <= '{game_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY pitcher_lookup, opponent_lookup ORDER BY snapshot_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            # Key by pitcher_team combo
            vs_data = {}
            for _, row in df.iterrows():
                key = f"{row['pitcher_lookup']}_{row['opponent_team']}"
                vs_data[key] = row.to_dict()
            return vs_data
        except Exception as e:
            logger.warning(f"Pitcher vs team query failed: {e}")
            return {}

    def _get_lineup_analysis(self, game_date: date) -> Dict[str, Dict]:
        """Get pre-computed lineup K analysis (V1 feature)."""
        query = f"""
        SELECT
            pitcher_lookup,
            game_id,
            bottom_up_expected_k,
            bottom_up_k_std,
            lineup_avg_k_rate,
            lineup_k_rate_vs_hand,
            lineup_quality_tier,
            weak_spot_count,
            data_completeness_pct
        FROM `{self.project_id}.mlb_precompute.lineup_k_analysis`
        WHERE game_date = '{game_date}'
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['pitcher_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Lineup analysis query failed: {e}")
            return {}

    def _get_umpire_data(self, game_date: date) -> Dict[str, Dict]:
        """Get umpire K tendencies (V1 feature)."""
        query = f"""
        SELECT
            game_id,
            umpire_name,
            career_k_adjustment,
            zone_size,
            k_adjustment_last_10
        FROM `{self.project_id}.mlb_raw.umpire_game_assignment`
        WHERE game_date = '{game_date}'
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['game_id']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Umpire data query failed: {e}")
            return {}

    def _get_innings_projections(self, game_date: date) -> Dict[str, Dict]:
        """Get pitcher innings projections (V1 feature)."""
        query = f"""
        SELECT
            pitcher_lookup,
            projected_innings,
            projected_batters_faced,
            recent_avg_ip,
            season_avg_ip,
            expected_k_opportunities
        FROM `{self.project_id}.mlb_precompute.pitcher_innings_projection`
        WHERE game_date = '{game_date}'
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['pitcher_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Innings projections query failed: {e}")
            return {}

    def _get_arsenal_data(self, game_date: date) -> Dict[str, Dict]:
        """Get pitcher arsenal data (V2 features)."""
        query = f"""
        SELECT
            pitcher_lookup,
            avg_fastball_velocity,
            velocity_trend,
            overall_whiff_rate,
            chase_rate,
            put_away_rate,
            first_pitch_strike_rate,
            best_strikeout_pitch
        FROM `{self.project_id}.mlb_precompute.pitcher_arsenal_summary`
        WHERE analysis_date <= '{game_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY pitcher_lookup ORDER BY analysis_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['pitcher_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Arsenal data query failed: {e}")
            return {}

    def _get_batter_profiles(self, game_date: date) -> Dict[str, Dict]:
        """Get batter K profiles (V2 features)."""
        query = f"""
        SELECT
            batter_lookup,
            season_k_rate,
            k_rate_last_10,
            k_rate_vs_rhp,
            k_rate_vs_lhp,
            platoon_k_diff,
            whiff_rate,
            chase_rate
        FROM `{self.project_id}.mlb_precompute.batter_k_profile`
        WHERE analysis_date <= '{game_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY batter_lookup ORDER BY analysis_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['batter_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Batter profiles query failed: {e}")
            return {}

    def _get_batter_splits(self, game_date: date) -> Dict[str, Dict]:
        """Get batter splits vs LHP/RHP (V1/V2 features)."""
        query = f"""
        SELECT
            player_lookup,
            split_category,
            at_bats,
            strikeouts,
            k_rate
        FROM `{self.project_id}.mlb_raw.bdl_batter_splits`
        WHERE snapshot_date <= '{game_date}'
          AND split_category IN ('vs_lhp', 'vs_rhp')
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup, split_category ORDER BY snapshot_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            splits = {}
            for _, row in df.iterrows():
                player = row['player_lookup']
                if player not in splits:
                    splits[player] = {}
                splits[player][row['split_category']] = row.to_dict()
            return splits
        except Exception as e:
            logger.warning(f"Batter splits query failed: {e}")
            return {}

    def _get_pitcher_handedness(self) -> Dict[str, str]:
        """Get pitcher throwing hand (L/R)."""
        query = f"""
        SELECT DISTINCT
            player_lookup,
            throws
        FROM `{self.project_id}.mlb_raw.bdl_pitchers`
        WHERE throws IS NOT NULL
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['player_lookup']: row['throws'] for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Pitcher handedness query failed: {e}")
            return {}

    def _compute_pitcher_features(
        self,
        pitcher_lookup: str,
        game: Dict,
        side: str,
        lineups: Dict,
        pitcher_stats: Dict,
        batter_stats: Dict,
        betting_lines: Dict,
        pitcher_splits: Dict,
        game_lines: Dict,
        ballpark_factors: Dict,
        pitcher_vs_team: Dict,
        lineup_analysis: Dict,
        umpire_data: Dict,
        innings_projections: Dict,
        arsenal_data: Dict,
        batter_profiles: Dict,
        batter_splits: Dict,
        pitcher_hands: Dict,
        game_date: date
    ) -> Optional[Dict]:
        """Compute 35-feature vector for a pitcher (V2)."""

        # Get pitcher's rolling stats
        p_stats = pitcher_stats.get(pitcher_lookup, {})

        # Get opponent team and own team
        opponent_team = game['away_team_abbr'] if side == 'home' else game['home_team_abbr']
        own_team = game['home_team_abbr'] if side == 'home' else game['away_team_abbr']

        # Get batting lineup for opponent
        game_pk = str(game['game_pk'])
        opponent_batters = []
        if game_pk in lineups:
            for team_data in lineups[game_pk].values():
                for batter in team_data:
                    if batter.get('team_abbr') == opponent_team:
                        opponent_batters.append(batter)

        # Calculate bottom-up K expectation (legacy, for when lineup_analysis not available)
        bottom_up_k = self._calculate_bottom_up_k(opponent_batters, batter_stats)

        # Get betting line
        line_data = betting_lines.get(pitcher_lookup, {})
        k_line = line_data.get('line_point')

        # Get pitcher splits
        p_splits = pitcher_splits.get(pitcher_lookup, {})
        home_k_per_9 = self._safe_float(p_splits.get('home', {}).get('k_per_9'))
        away_k_per_9 = self._safe_float(p_splits.get('away', {}).get('k_per_9'))
        day_k_per_9 = self._safe_float(p_splits.get('day', {}).get('k_per_9'))
        night_k_per_9 = self._safe_float(p_splits.get('night', {}).get('k_per_9'))

        # Calculate split differences
        home_away_k_diff = 0.0
        if home_k_per_9 and away_k_per_9:
            home_away_k_diff = home_k_per_9 - away_k_per_9

        day_night_k_diff = 0.0
        if day_k_per_9 and night_k_per_9:
            day_night_k_diff = day_k_per_9 - night_k_per_9

        # Get pitcher vs opponent history
        vs_key = f"{pitcher_lookup}_{opponent_team.lower()}"
        vs_data = pitcher_vs_team.get(vs_key, {})
        vs_opponent_k_rate = self._safe_float(vs_data.get('k_rate')) or 0.0

        # Get game lines
        game_key = f"{game['away_team_abbr']}@{game['home_team_abbr']}"
        game_line_data = game_lines.get(game_key, {})
        game_total_line = self._safe_float(game_line_data.get('total_over_under')) or 0.0

        # Calculate team implied runs from moneyline
        team_implied_runs = 0.0
        if game_total_line > 0:
            moneyline = game_line_data.get('home_moneyline' if side == 'home' else 'away_moneyline')
            if moneyline:
                implied_prob = self._moneyline_to_probability(moneyline)
                team_implied_runs = game_total_line * implied_prob

        # Get ballpark factor
        venue_team = game['home_team_abbr']  # Venue is always home team's park
        park_data = ballpark_factors.get(venue_team, {})
        ballpark_k_factor = (self._safe_float(park_data.get('strikeouts_factor')) or 100) / 100.0

        # Calculate opponent OBP from batter stats
        opponent_obp = self._calculate_team_obp(opponent_batters, batter_stats)

        # =====================================================================
        # V1 FEATURES (f25-f29): MLB-Specific Bottom-Up Model
        # =====================================================================

        # Get lineup analysis (pre-computed)
        lineup_data = lineup_analysis.get(pitcher_lookup, {})

        # f25: bottom_up_k_expected (THE KEY FEATURE)
        f25_bottom_up_k = lineup_data.get('bottom_up_expected_k') or bottom_up_k

        # f26: lineup_k_vs_hand (lineup K rate vs pitcher's handedness)
        f26_lineup_k_vs_hand = lineup_data.get('lineup_k_rate_vs_hand') or 0.0

        # f27: platoon_advantage (LHP vs RHH lineup = advantage)
        pitcher_hand = pitcher_hands.get(pitcher_lookup, 'R')
        f27_platoon_advantage = self._calculate_platoon_advantage(
            pitcher_hand, opponent_batters, batter_splits
        )

        # f28: umpire_k_factor
        ump_data = umpire_data.get(game_pk, {})
        f28_umpire_k_factor = self._safe_float(ump_data.get('career_k_adjustment')) or 0.0

        # f29: projected_innings
        ip_data = innings_projections.get(pitcher_lookup, {})
        f29_projected_innings = self._safe_float(ip_data.get('projected_innings')) or \
                                self._safe_float(p_stats.get('ip_avg_last_5')) or 5.5

        # =====================================================================
        # V2 FEATURES (f30-f34): Advanced Pitcher/Batter Metrics
        # =====================================================================

        # Get arsenal data
        p_arsenal = arsenal_data.get(pitcher_lookup, {})

        # f30: velocity_trend
        f30_velocity_trend = self._safe_float(p_arsenal.get('velocity_trend')) or 0.0

        # f31: whiff_rate
        f31_whiff_rate = self._safe_float(p_arsenal.get('overall_whiff_rate')) or 0.0

        # f32: put_away_rate (K rate with 2 strikes)
        f32_put_away_rate = self._safe_float(p_arsenal.get('put_away_rate')) or 0.0

        # f33: lineup_weak_spots (count of high-K batters)
        f33_lineup_weak_spots = int(lineup_data.get('weak_spot_count') or 0)
        if f33_lineup_weak_spots == 0:
            # Calculate from batter profiles if not in lineup_analysis
            f33_lineup_weak_spots = self._count_weak_spots(opponent_batters, batter_profiles)

        # f34: matchup_edge (composite advantage score)
        f34_matchup_edge = self._calculate_matchup_edge(
            pitcher_lookup=pitcher_lookup,
            opponent_batters=opponent_batters,
            batter_profiles=batter_profiles,
            pitcher_hand=pitcher_hand,
            p_arsenal=p_arsenal
        )

        # Build 35-feature vector
        features = {
            # Identifiers
            'player_lookup': pitcher_lookup,
            'game_date': game_date,
            'game_id': str(game['game_pk']),
            'opponent_team_abbr': opponent_team,
            'season_year': game_date.year,

            # Recent Performance (0-4)
            'f00_k_avg_last_3': self._safe_float(p_stats.get('k_avg_last_3')),
            'f01_k_avg_last_5': self._safe_float(p_stats.get('k_avg_last_5')),
            'f02_k_avg_last_10': self._safe_float(p_stats.get('k_avg_last_10')),
            'f03_k_std_last_10': self._safe_float(p_stats.get('k_std_last_10')),
            'f04_ip_avg_last_5': self._safe_float(p_stats.get('ip_avg_last_5')),

            # Season Baseline (5-9)
            'f05_season_k_per_9': self._safe_float(p_stats.get('season_k_per_9')),
            'f06_season_era': self._safe_float(p_stats.get('season_era')),
            'f07_season_whip': self._safe_float(p_stats.get('season_whip')),
            'f08_season_games': p_stats.get('season_games') or 0,
            'f09_season_k_total': p_stats.get('season_k_total') or 0,

            # Split Adjustments (10-14)
            'f10_is_home': 1.0 if side == 'home' else 0.0,
            'f11_home_away_k_diff': home_away_k_diff,
            'f12_is_day_game': 1.0 if game.get('is_day_game') else 0.0,
            'f13_day_night_k_diff': day_night_k_diff,
            'f14_vs_opponent_k_rate': vs_opponent_k_rate,

            # Matchup Context (15-19) - BOTTOM-UP MODEL
            'f15_opponent_team_k_rate': self._calculate_team_k_rate(opponent_batters, batter_stats),
            'f16_opponent_obp': opponent_obp,
            'f17_ballpark_k_factor': ballpark_k_factor,
            'f18_game_total_line': game_total_line,
            'f19_team_implied_runs': team_implied_runs,

            # Workload/Fatigue (20-24)
            'f20_days_rest': p_stats.get('days_rest') or 5,
            'f21_games_last_30_days': p_stats.get('games_last_30_days') or 0,
            'f22_pitch_count_avg': self._safe_float(p_stats.get('pitch_count_avg_last_5')) or 0.0,
            'f23_season_ip_total': self._safe_float(p_stats.get('season_innings')) or 0.0,
            'f24_is_postseason': 1.0 if game.get('game_type') == 'P' else 0.0,

            # V1 Features: MLB-Specific (25-29)
            'f25_bottom_up_k_expected': f25_bottom_up_k,
            'f26_lineup_k_vs_hand': f26_lineup_k_vs_hand,
            'f27_platoon_advantage': f27_platoon_advantage,
            'f28_umpire_k_factor': f28_umpire_k_factor,
            'f29_projected_innings': f29_projected_innings,

            # V2 Features: Advanced Metrics (30-34)
            'f30_velocity_trend': f30_velocity_trend,
            'f31_whiff_rate': f31_whiff_rate,
            'f32_put_away_rate': f32_put_away_rate,
            'f33_lineup_weak_spots': float(f33_lineup_weak_spots),
            'f34_matchup_edge': f34_matchup_edge,

            # Target & Line
            'actual_strikeouts': None,  # Filled after game
            'strikeouts_line': k_line,

            # Bottom-up calculation (legacy field)
            'bottom_up_k_expected': f25_bottom_up_k,

            # Grading support (V1)
            'actual_innings': None,  # Filled after game
            'actual_k_per_9': None,  # Filled after game

            # Metadata
            'feature_version': self.feature_version,
            'created_at': datetime.now(timezone.utc),
            'processed_at': datetime.now(timezone.utc)
        }

        # Build 35-element feature vector
        feature_vector = [
            # Original 25 features (f00-f24)
            features['f00_k_avg_last_3'] or 0.0,
            features['f01_k_avg_last_5'] or 0.0,
            features['f02_k_avg_last_10'] or 0.0,
            features['f03_k_std_last_10'] or 0.0,
            features['f04_ip_avg_last_5'] or 0.0,
            features['f05_season_k_per_9'] or 0.0,
            features['f06_season_era'] or 0.0,
            features['f07_season_whip'] or 0.0,
            float(features['f08_season_games']),
            float(features['f09_season_k_total']),
            features['f10_is_home'],
            features['f11_home_away_k_diff'],
            features['f12_is_day_game'],
            features['f13_day_night_k_diff'],
            features['f14_vs_opponent_k_rate'],
            features['f15_opponent_team_k_rate'] or 0.0,
            features['f16_opponent_obp'],
            features['f17_ballpark_k_factor'],
            features['f18_game_total_line'],
            features['f19_team_implied_runs'],
            float(features['f20_days_rest']),
            float(features['f21_games_last_30_days']),
            features['f22_pitch_count_avg'],
            features['f23_season_ip_total'],
            features['f24_is_postseason'],
            # V1 features (f25-f29)
            features['f25_bottom_up_k_expected'] or 0.0,
            features['f26_lineup_k_vs_hand'] or 0.0,
            features['f27_platoon_advantage'] or 0.0,
            features['f28_umpire_k_factor'] or 0.0,
            features['f29_projected_innings'] or 0.0,
            # V2 features (f30-f34)
            features['f30_velocity_trend'] or 0.0,
            features['f31_whiff_rate'] or 0.0,
            features['f32_put_away_rate'] or 0.0,
            features['f33_lineup_weak_spots'] or 0.0,
            features['f34_matchup_edge'] or 0.0,
        ]
        features['feature_vector'] = feature_vector

        # Compute data hash
        hash_str = f"{pitcher_lookup}_{game_date}_{game['game_pk']}"
        features['data_hash'] = hashlib.md5(hash_str.encode()).hexdigest()[:16]

        return features

    def _calculate_platoon_advantage(
        self,
        pitcher_hand: str,
        opponent_batters: List[Dict],
        batter_splits: Dict
    ) -> float:
        """
        Calculate platoon advantage.
        LHP vs RHH = advantage (positive)
        RHP vs LHH = advantage (positive)
        Same hand = disadvantage (negative)
        """
        if not opponent_batters:
            return 0.0

        split_key = 'vs_lhp' if pitcher_hand == 'L' else 'vs_rhp'
        opposite_key = 'vs_rhp' if pitcher_hand == 'L' else 'vs_lhp'

        platoon_diffs = []
        for batter in opponent_batters:
            player_lookup = batter.get('player_lookup')
            if not player_lookup or player_lookup not in batter_splits:
                continue

            splits = batter_splits[player_lookup]
            k_vs_this = splits.get(split_key, {}).get('k_rate')
            k_vs_opposite = splits.get(opposite_key, {}).get('k_rate')

            if k_vs_this and k_vs_opposite:
                # Positive = easier to K vs this pitcher's hand
                platoon_diffs.append(k_vs_this - k_vs_opposite)

        return sum(platoon_diffs) / len(platoon_diffs) if platoon_diffs else 0.0

    def _count_weak_spots(
        self,
        opponent_batters: List[Dict],
        batter_profiles: Dict
    ) -> int:
        """Count batters with high K rate (>0.28)."""
        weak_spots = 0
        for batter in opponent_batters:
            player_lookup = batter.get('player_lookup')
            if not player_lookup:
                continue
            profile = batter_profiles.get(player_lookup, {})
            k_rate = profile.get('season_k_rate') or profile.get('k_rate_last_10')
            if k_rate and k_rate > 0.28:
                weak_spots += 1
        return weak_spots

    def _calculate_matchup_edge(
        self,
        pitcher_lookup: str,
        opponent_batters: List[Dict],
        batter_profiles: Dict,
        pitcher_hand: str,
        p_arsenal: Dict
    ) -> float:
        """
        Calculate composite matchup advantage score.
        Combines pitcher arsenal strength vs batter weaknesses.
        Range: -3 to +3 (positive = pitcher advantage)
        """
        edge = 0.0

        # Factor 1: Pitcher whiff rate (0.15-0.35 range)
        whiff = p_arsenal.get('overall_whiff_rate') or 0.25
        edge += (whiff - 0.25) * 10  # Normalized around 0.25 baseline

        # Factor 2: Lineup K vulnerability
        k_rates = []
        for batter in opponent_batters:
            player_lookup = batter.get('player_lookup')
            if player_lookup and player_lookup in batter_profiles:
                k_rate = batter_profiles[player_lookup].get('season_k_rate')
                if k_rate:
                    k_rates.append(k_rate)

        if k_rates:
            avg_k_rate = sum(k_rates) / len(k_rates)
            edge += (avg_k_rate - 0.22) * 10  # Normalized around 0.22 league avg

        # Factor 3: Put-away rate
        put_away = p_arsenal.get('put_away_rate') or 0.30
        edge += (put_away - 0.30) * 5  # Normalized around 0.30 baseline

        # Clamp to -3 to +3 range
        return max(-3.0, min(3.0, round(edge, 2)))

    def _calculate_bottom_up_k(
        self,
        opponent_batters: List[Dict],
        batter_stats: Dict
    ) -> float:
        """
        Calculate expected pitcher Ks using bottom-up model.

        Sum of (batter K rate × expected ABs) for all batters in lineup.

        This is the KEY INSIGHT of the model:
        Pitcher Ks ≈ Σ (individual batter K probabilities × ABs)
        """
        if not opponent_batters:
            return 0.0

        total_expected_k = 0.0
        for batter in opponent_batters:
            player_lookup = batter.get('player_lookup')
            if not player_lookup:
                continue

            b_stats = batter_stats.get(player_lookup, {})
            k_rate = b_stats.get('k_rate_last_10') or b_stats.get('season_k_rate') or 0.20

            # Estimate ABs based on batting order (1-9)
            batting_order = batter.get('batting_order', 5)
            expected_abs = self._estimate_abs_by_order(batting_order)

            total_expected_k += k_rate * expected_abs

        return round(total_expected_k, 2)

    def _estimate_abs_by_order(self, batting_order: int) -> float:
        """Estimate at-bats based on batting order position."""
        # Leadoff gets more ABs, 9th hitter gets fewer
        ab_by_order = {
            1: 4.5, 2: 4.3, 3: 4.2, 4: 4.0, 5: 3.9,
            6: 3.8, 7: 3.7, 8: 3.6, 9: 3.5
        }
        return ab_by_order.get(batting_order, 3.8)

    def _calculate_team_k_rate(
        self,
        opponent_batters: List[Dict],
        batter_stats: Dict
    ) -> Optional[float]:
        """Calculate average K rate for opponent's lineup."""
        if not opponent_batters:
            return None

        k_rates = []
        for batter in opponent_batters:
            player_lookup = batter.get('player_lookup')
            if not player_lookup:
                continue
            b_stats = batter_stats.get(player_lookup, {})
            k_rate = b_stats.get('k_rate_last_10') or b_stats.get('season_k_rate')
            if k_rate:
                k_rates.append(k_rate)

        return sum(k_rates) / len(k_rates) if k_rates else None

    def _safe_float(self, value) -> Optional[float]:
        """Safely convert to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _moneyline_to_probability(self, moneyline: int) -> float:
        """Convert American moneyline odds to implied probability."""
        if moneyline is None:
            return 0.5  # Default to 50/50
        try:
            ml = float(moneyline)
            if ml > 0:
                # Underdog: +150 means 100/(150+100) = 0.40
                return 100 / (ml + 100)
            else:
                # Favorite: -150 means 150/(150+100) = 0.60
                return abs(ml) / (abs(ml) + 100)
        except (ValueError, TypeError):
            return 0.5

    def _calculate_team_obp(
        self,
        opponent_batters: List[Dict],
        batter_stats: Dict
    ) -> float:
        """Calculate average OBP for opponent's lineup."""
        if not opponent_batters:
            return 0.320  # League average fallback

        obp_values = []
        for batter in opponent_batters:
            player_lookup = batter.get('player_lookup')
            if not player_lookup:
                continue
            b_stats = batter_stats.get(player_lookup, {})
            # Try to get OBP from batter stats
            obp = b_stats.get('season_obp') or b_stats.get('obp')
            if obp:
                obp_values.append(float(obp))

        return sum(obp_values) / len(obp_values) if obp_values else 0.320

    def _write_features(self, features_list: List[Dict], game_date: date) -> int:
        """Write features to BigQuery using atomic MERGE operation.

        CRITICAL FIX (Jan 25, 2026):
        - Changed from f-string to parameterized query (prevents SQL injection)
        - Changed from DELETE/INSERT to MERGE (prevents race condition where
          readers see empty/partial data between delete and insert)

        Note: BigQuery MERGE with UNNEST and complex structs can be tricky.
        We use a temp table approach for reliability.
        """
        if not features_list:
            return 0

        # Strategy: Load to temp table, then MERGE from temp table
        # This is more reliable than UNNEST(@features) with complex structs
        import uuid
        temp_table_id = f"temp_pitcher_features_{uuid.uuid4().hex[:8]}"
        temp_table_ref = f"{self.project_id}.mlb_precompute.{temp_table_id}"

        try:
            # Step 1: Load data to temporary table
            temp_table = self.bq_client.dataset('mlb_precompute').table(temp_table_id)
            errors = self.bq_client.insert_rows_json(temp_table, features_list)

            if errors:
                logger.warning(f"Temp table insert had errors: {errors}")
                # Fallback to legacy method
                return self._write_features_legacy(features_list, game_date)

            # Step 2: MERGE from temp table (atomic operation)
            merge_query = """
            MERGE `{target}` T
            USING `{temp}` S
            ON T.game_date = S.game_date
               AND T.player_lookup = S.player_lookup
               AND T.game_id = S.game_id
            WHEN MATCHED THEN
                UPDATE SET
                    opponent_team_abbr = S.opponent_team_abbr,
                    season_year = S.season_year,
                    f00_k_avg_last_3 = S.f00_k_avg_last_3,
                    f01_k_avg_last_5 = S.f01_k_avg_last_5,
                    f02_k_avg_last_10 = S.f02_k_avg_last_10,
                    f03_k_std_last_10 = S.f03_k_std_last_10,
                    f04_ip_avg_last_5 = S.f04_ip_avg_last_5,
                    f05_season_k_per_9 = S.f05_season_k_per_9,
                    f06_season_era = S.f06_season_era,
                    f07_season_whip = S.f07_season_whip,
                    f08_season_games = S.f08_season_games,
                    f09_season_k_total = S.f09_season_k_total,
                    f10_is_home = S.f10_is_home,
                    f11_home_away_k_diff = S.f11_home_away_k_diff,
                    f12_is_day_game = S.f12_is_day_game,
                    f13_day_night_k_diff = S.f13_day_night_k_diff,
                    f14_vs_opponent_k_rate = S.f14_vs_opponent_k_rate,
                    f15_opponent_team_k_rate = S.f15_opponent_team_k_rate,
                    f16_opponent_obp = S.f16_opponent_obp,
                    f17_ballpark_k_factor = S.f17_ballpark_k_factor,
                    f18_game_total_line = S.f18_game_total_line,
                    f19_team_implied_runs = S.f19_team_implied_runs,
                    f20_days_rest = S.f20_days_rest,
                    f21_games_last_30_days = S.f21_games_last_30_days,
                    f22_pitch_count_avg = S.f22_pitch_count_avg,
                    f23_season_ip_total = S.f23_season_ip_total,
                    f24_is_postseason = S.f24_is_postseason,
                    f25_bottom_up_k_expected = S.f25_bottom_up_k_expected,
                    f26_lineup_k_vs_hand = S.f26_lineup_k_vs_hand,
                    f27_platoon_advantage = S.f27_platoon_advantage,
                    f28_umpire_k_factor = S.f28_umpire_k_factor,
                    f29_projected_innings = S.f29_projected_innings,
                    f30_velocity_trend = S.f30_velocity_trend,
                    f31_whiff_rate = S.f31_whiff_rate,
                    f32_put_away_rate = S.f32_put_away_rate,
                    f33_lineup_weak_spots = S.f33_lineup_weak_spots,
                    f34_matchup_edge = S.f34_matchup_edge,
                    feature_vector = S.feature_vector,
                    actual_strikeouts = S.actual_strikeouts,
                    strikeouts_line = S.strikeouts_line,
                    bottom_up_k_expected = S.bottom_up_k_expected,
                    actual_innings = S.actual_innings,
                    actual_k_per_9 = S.actual_k_per_9,
                    feature_version = S.feature_version,
                    data_hash = S.data_hash,
                    processed_at = S.processed_at
            WHEN NOT MATCHED THEN
                INSERT (
                    player_lookup, game_date, game_id, opponent_team_abbr, season_year,
                    f00_k_avg_last_3, f01_k_avg_last_5, f02_k_avg_last_10, f03_k_std_last_10, f04_ip_avg_last_5,
                    f05_season_k_per_9, f06_season_era, f07_season_whip, f08_season_games, f09_season_k_total,
                    f10_is_home, f11_home_away_k_diff, f12_is_day_game, f13_day_night_k_diff, f14_vs_opponent_k_rate,
                    f15_opponent_team_k_rate, f16_opponent_obp, f17_ballpark_k_factor, f18_game_total_line, f19_team_implied_runs,
                    f20_days_rest, f21_games_last_30_days, f22_pitch_count_avg, f23_season_ip_total, f24_is_postseason,
                    f25_bottom_up_k_expected, f26_lineup_k_vs_hand, f27_platoon_advantage, f28_umpire_k_factor, f29_projected_innings,
                    f30_velocity_trend, f31_whiff_rate, f32_put_away_rate, f33_lineup_weak_spots, f34_matchup_edge,
                    feature_vector, actual_strikeouts, strikeouts_line, bottom_up_k_expected,
                    actual_innings, actual_k_per_9, feature_version, data_hash, created_at, processed_at
                )
                VALUES (
                    S.player_lookup, S.game_date, S.game_id, S.opponent_team_abbr, S.season_year,
                    S.f00_k_avg_last_3, S.f01_k_avg_last_5, S.f02_k_avg_last_10, S.f03_k_std_last_10, S.f04_ip_avg_last_5,
                    S.f05_season_k_per_9, S.f06_season_era, S.f07_season_whip, S.f08_season_games, S.f09_season_k_total,
                    S.f10_is_home, S.f11_home_away_k_diff, S.f12_is_day_game, S.f13_day_night_k_diff, S.f14_vs_opponent_k_rate,
                    S.f15_opponent_team_k_rate, S.f16_opponent_obp, S.f17_ballpark_k_factor, S.f18_game_total_line, S.f19_team_implied_runs,
                    S.f20_days_rest, S.f21_games_last_30_days, S.f22_pitch_count_avg, S.f23_season_ip_total, S.f24_is_postseason,
                    S.f25_bottom_up_k_expected, S.f26_lineup_k_vs_hand, S.f27_platoon_advantage, S.f28_umpire_k_factor, S.f29_projected_innings,
                    S.f30_velocity_trend, S.f31_whiff_rate, S.f32_put_away_rate, S.f33_lineup_weak_spots, S.f34_matchup_edge,
                    S.feature_vector, S.actual_strikeouts, S.strikeouts_line, S.bottom_up_k_expected,
                    S.actual_innings, S.actual_k_per_9, S.feature_version, S.data_hash, CURRENT_TIMESTAMP(), S.processed_at
                )
            """.format(target=f"{self.project_id}.{self.target_table}", temp=temp_table_ref)

            # Execute MERGE (no parameters needed - table names in query)
            job = self.bq_client.query(merge_query)
            job.result(timeout=120)  # 2 minute timeout

            # Step 3: Cleanup temp table
            self.bq_client.delete_table(temp_table_ref, not_found_ok=True)

            logger.info(f"Successfully merged {len(features_list)} pitcher features for {game_date}")
            return len(features_list)

        except Exception as e:
            logger.error(f"MERGE failed for pitcher features on {game_date}: {e}")
            # Cleanup temp table if it exists
            try:
                self.bq_client.delete_table(temp_table_ref, not_found_ok=True)
            except Exception:
                pass  # Ignore cleanup errors, fallback to legacy method
            # Fallback to legacy DELETE/INSERT with parameterized query
            return self._write_features_legacy(features_list, game_date)

    def _write_features_legacy(self, features_list: List[Dict], game_date: date) -> int:
        """Legacy write using DELETE/INSERT with parameterized queries.

        Used as fallback when MERGE fails. Still has race condition window
        but uses parameterized queries to prevent SQL injection.

        Args:
            features_list: List of feature dictionaries to write
            game_date: Date for the features

        Returns:
            Number of features written, or 0 on failure
        """
        # Use parameterized DELETE query (fixes SQL injection)
        delete_query = """
        DELETE FROM `{project}.{table}`
        WHERE game_date = @game_date
        """.format(project=self.project_id, table=self.target_table)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        try:
            job = self.bq_client.query(delete_query, job_config=job_config)
            job.result(timeout=60)  # 1 minute timeout for delete
        except Exception as e:
            logger.warning(f"Delete failed (table may not exist): {e}")

        # Insert new records
        table_ref = self.bq_client.dataset('mlb_precompute').table('pitcher_ml_features')
        errors = self.bq_client.insert_rows_json(table_ref, features_list)

        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
            return 0

        logger.info(f"Legacy write: inserted {len(features_list)} features for {game_date}")
        return len(features_list)


# CLI entrypoint
if __name__ == "__main__":
    import sys
    from datetime import datetime

    processor = MlbPitcherFeaturesProcessor()

    if len(sys.argv) > 1:
        target_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        target_date = date.today()

    result = processor.process_date(target_date)
    print(f"Result: {result}")
