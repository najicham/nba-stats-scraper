#!/usr/bin/env python3
"""
MLB Lineup K Analysis Processor - Phase 4 Precompute
Computes bottom-up strikeout expectations from lineup data.

Key Feature: Sum of individual batter K probabilities = expected pitcher Ks

Dependencies:
- mlb_raw.mlb_lineup_batters (batting order)
- mlb_raw.mlb_schedule (probable pitchers)
- mlb_analytics.batter_game_summary (rolling K rates)
- mlb_raw.bdl_batter_splits (platoon splits vs LHP/RHP)

Output: mlb_precompute.lineup_k_analysis
"""

import json
import logging
import statistics
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Any
from google.cloud import bigquery

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

logger = logging.getLogger(__name__)


class MlbLineupKAnalysisProcessor(PrecomputeProcessorBase):
    """Computes lineup-based strikeout analysis for pitchers."""

    def __init__(self):
        super().__init__()
        self.processor_name = "mlb_lineup_k_analysis"
        self.target_table = "mlb_precompute.lineup_k_analysis"

    def process_date(self, game_date: date) -> Dict[str, Any]:
        """Process lineup analysis for all pitchers on a given date."""
        logger.info(f"Processing lineup K analysis for {game_date}")

        # 1. Get scheduled games with probable pitchers
        schedule = self._get_schedule(game_date)
        if not schedule:
            logger.info(f"No games scheduled for {game_date}")
            return {"status": "no_games", "processed": 0}

        # 2. Get lineup data
        lineups = self._get_lineups(game_date)

        # 3. Get batter analytics (rolling K rates)
        batter_stats = self._get_batter_analytics(game_date)

        # 4. Get batter platoon splits
        batter_splits = self._get_batter_splits(game_date)

        # 5. Get pitcher handedness
        pitcher_hands = self._get_pitcher_handedness()

        # 6. Compute lineup analysis for each pitcher
        analysis_list = []
        for game in schedule:
            for side in ['home', 'away']:
                pitcher_lookup = game.get(f'{side}_pitcher_lookup')
                if not pitcher_lookup:
                    continue

                analysis = self._compute_lineup_analysis(
                    pitcher_lookup=pitcher_lookup,
                    game=game,
                    side=side,
                    lineups=lineups,
                    batter_stats=batter_stats,
                    batter_splits=batter_splits,
                    pitcher_hands=pitcher_hands,
                    game_date=game_date
                )
                if analysis:
                    analysis_list.append(analysis)

        # 7. Write to BigQuery
        if analysis_list:
            rows_written = self._write_analysis(analysis_list, game_date)
            logger.info(f"Wrote {rows_written} lineup analyses for {game_date}")
            return {"status": "success", "processed": rows_written}

        return {"status": "no_analyses", "processed": 0}

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
            away_pitcher_lookup
        FROM `{self.project_id}.mlb_raw.mlb_schedule`
        WHERE game_date = '{game_date}'
          AND status IN ('Scheduled', 'Pre-Game', 'In Progress', 'Final')
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return df.to_dict('records')
        except Exception as e:
            logger.warning(f"Schedule query failed: {e}")
            return []

    def _get_lineups(self, game_date: date) -> Dict[str, Dict[str, List[Dict]]]:
        """Get lineups by game_pk and team."""
        query = f"""
        SELECT
            game_pk,
            team_abbr,
            player_lookup,
            player_name,
            batting_order,
            position
        FROM `{self.project_id}.mlb_raw.mlb_lineup_batters`
        WHERE game_date = '{game_date}'
        ORDER BY game_pk, batting_order
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            lineups = {}
            for _, row in df.iterrows():
                key = str(row['game_pk'])
                if key not in lineups:
                    lineups[key] = {}
                team = row['team_abbr']
                if team not in lineups[key]:
                    lineups[key][team] = []
                lineups[key][team].append(row.to_dict())
            return lineups
        except Exception as e:
            logger.warning(f"Lineups query failed: {e}")
            return {}

    def _get_batter_analytics(self, game_date: date) -> Dict[str, Dict]:
        """Get batter rolling K rates."""
        query = f"""
        SELECT
            player_lookup,
            k_rate_last_5,
            k_rate_last_10,
            k_rate_last_30,
            k_avg_last_5,
            k_avg_last_10,
            season_k_rate,
            ab_avg_last_10,
            season_ab
        FROM `{self.project_id}.mlb_analytics.batter_game_summary`
        WHERE game_date < '{game_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) = 1
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            return {row['player_lookup']: row.to_dict() for _, row in df.iterrows()}
        except Exception as e:
            logger.warning(f"Batter analytics query failed: {e}")
            return {}

    def _get_batter_splits(self, game_date: date) -> Dict[str, Dict]:
        """Get batter splits vs LHP/RHP."""
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

    def _compute_lineup_analysis(
        self,
        pitcher_lookup: str,
        game: Dict,
        side: str,
        lineups: Dict,
        batter_stats: Dict,
        batter_splits: Dict,
        pitcher_hands: Dict,
        game_date: date
    ) -> Optional[Dict]:
        """Compute lineup K analysis for a pitcher."""

        # Get opponent team
        opponent_team = game['away_team_abbr'] if side == 'home' else game['home_team_abbr']
        game_pk = str(game['game_pk'])

        # Get opponent batting lineup
        opponent_batters = []
        if game_pk in lineups and opponent_team in lineups[game_pk]:
            opponent_batters = lineups[game_pk][opponent_team]

        if not opponent_batters:
            logger.debug(f"No lineup for {opponent_team} in game {game_pk}")
            return None

        # Get pitcher handedness
        pitcher_hand = pitcher_hands.get(pitcher_lookup, 'R')
        split_key = 'vs_lhp' if pitcher_hand == 'L' else 'vs_rhp'

        # Calculate lineup-level metrics
        k_rates = []
        k_rates_vs_hand = []
        chase_rates = []
        whiff_rates = []
        contact_rates = []
        batter_details = []
        batters_with_data = 0

        for batter in opponent_batters:
            player_lookup = batter.get('player_lookup')
            if not player_lookup:
                continue

            b_stats = batter_stats.get(player_lookup, {})
            b_splits = batter_splits.get(player_lookup, {})

            # Get K rate (prefer recent, fall back to season)
            k_rate = b_stats.get('k_rate_last_10') or b_stats.get('season_k_rate') or 0.20
            k_rates.append(k_rate)

            # Get K rate vs pitcher handedness
            k_rate_vs_hand = None
            if split_key in b_splits:
                k_rate_vs_hand = b_splits[split_key].get('k_rate')
            if k_rate_vs_hand is None:
                k_rate_vs_hand = k_rate  # Fall back to overall
            k_rates_vs_hand.append(k_rate_vs_hand)

            # Estimate at-bats for this batter
            batting_order = batter.get('batting_order', 5)
            expected_abs = self._estimate_abs_by_order(batting_order)

            if b_stats:
                batters_with_data += 1

            # Build batter detail record
            batter_details.append({
                'batting_order': batting_order,
                'batter_lookup': player_lookup,
                'batter_name': batter.get('player_name', ''),
                'handedness': b_stats.get('bats', 'R'),
                'season_k_rate': round(k_rate, 3) if k_rate else None,
                'k_rate_vs_hand': round(k_rate_vs_hand, 3) if k_rate_vs_hand else None,
                'expected_pa': round(expected_abs, 2),
                'expected_k': round(k_rate_vs_hand * expected_abs, 3) if k_rate_vs_hand else None
            })

        # Calculate aggregates
        lineup_avg_k_rate = sum(k_rates) / len(k_rates) if k_rates else None
        lineup_k_rate_vs_hand = sum(k_rates_vs_hand) / len(k_rates_vs_hand) if k_rates_vs_hand else None

        # Bottom-up K calculation (THE KEY)
        bottom_up_expected_k = 0.0
        expected_ks = []
        for bd in batter_details:
            if bd.get('expected_k'):
                bottom_up_expected_k += bd['expected_k']
                expected_ks.append(bd['expected_k'])

        # Calculate variance/std for confidence intervals
        bottom_up_k_std = statistics.stdev(expected_ks) if len(expected_ks) > 1 else 0.0
        bottom_up_k_floor = bottom_up_expected_k - (1.645 * bottom_up_k_std)  # 10th percentile
        bottom_up_k_ceiling = bottom_up_expected_k + (1.645 * bottom_up_k_std)  # 90th percentile

        # Classify lineup quality
        if lineup_avg_k_rate:
            if lineup_avg_k_rate < 0.18:
                lineup_quality_tier = 'ELITE_K_RESISTANT'
            elif lineup_avg_k_rate < 0.22:
                lineup_quality_tier = 'ABOVE_AVERAGE'
            elif lineup_avg_k_rate < 0.26:
                lineup_quality_tier = 'AVERAGE'
            elif lineup_avg_k_rate < 0.30:
                lineup_quality_tier = 'BELOW_AVERAGE'
            else:
                lineup_quality_tier = 'HIGH_K_PRONE'
        else:
            lineup_quality_tier = 'UNKNOWN'

        # Count weak spots (batters with K rate > 0.28)
        weak_spot_count = sum(1 for bd in batter_details if bd.get('season_k_rate', 0) > 0.28)

        # Data completeness
        data_completeness_pct = (batters_with_data / len(opponent_batters) * 100) if opponent_batters else 0.0

        return {
            'game_id': str(game['game_pk']),
            'game_date': game_date,
            'pitcher_lookup': pitcher_lookup,
            'opponent_team_abbr': opponent_team,
            'lineup_avg_k_rate': round(lineup_avg_k_rate, 4) if lineup_avg_k_rate else None,
            'lineup_k_rate_vs_hand': round(lineup_k_rate_vs_hand, 4) if lineup_k_rate_vs_hand else None,
            'lineup_chase_rate': None,  # TODO: Add when chase rate data available
            'lineup_whiff_rate': None,  # TODO: Add when whiff rate data available
            'lineup_contact_rate': None,  # TODO: Add when contact rate data available
            'bottom_up_expected_k': round(bottom_up_expected_k, 2),
            'bottom_up_k_std': round(bottom_up_k_std, 3),
            'bottom_up_k_floor': round(max(0, bottom_up_k_floor), 2),
            'bottom_up_k_ceiling': round(bottom_up_k_ceiling, 2),
            'lineup_batters': json.dumps(batter_details),
            'lineup_quality_tier': lineup_quality_tier,
            'weak_spot_count': weak_spot_count,
            'batters_with_k_data': batters_with_data,
            'data_completeness_pct': round(data_completeness_pct, 1),
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }

    def _estimate_abs_by_order(self, batting_order: int) -> float:
        """Estimate at-bats based on batting order position."""
        ab_by_order = {
            1: 4.5, 2: 4.3, 3: 4.2, 4: 4.0, 5: 3.9,
            6: 3.8, 7: 3.7, 8: 3.6, 9: 3.5
        }
        return ab_by_order.get(batting_order, 3.8)

    def _write_analysis(self, analysis_list: List[Dict], game_date: date) -> int:
        """Write analysis to BigQuery."""
        if not analysis_list:
            return 0

        # Delete existing records for this date
        delete_query = f"""
        DELETE FROM `{self.project_id}.{self.target_table}`
        WHERE game_date = '{game_date}'
        """
        try:
            self.bq_client.query(delete_query).result()
        except Exception as e:
            logger.warning(f"Delete failed (table may not exist): {e}")

        # Insert new records
        table_ref = self.bq_client.dataset('mlb_precompute').table('lineup_k_analysis')
        errors = self.bq_client.insert_rows_json(table_ref, analysis_list)

        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
            return 0

        return len(analysis_list)


# CLI entrypoint
if __name__ == "__main__":
    import sys

    processor = MlbLineupKAnalysisProcessor()

    if len(sys.argv) > 1:
        target_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        target_date = date.today()

    result = processor.process_date(target_date)
    print(f"Result: {result}")
