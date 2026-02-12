"""
Best Bets Exporter for Phase 6 Publishing

Exports top prediction picks using tiered selection based on data-driven analysis.

CRITICAL: Updated 2026-01-14 based on CRITICAL-DATA-AUDIT-2026-01-14.md
Previous analysis used fake line_value=20 data. These are VALIDATED findings:

Tier Strategy (validated with real sportsbook lines, catboost_v8 only):
- Premium: catboost_v8, 5+ edge, any recommendation (target 83-88% hit rate)
- Strong: catboost_v8, 3-5 edge (target 74-79% hit rate)
- Value: catboost_v8, <3 edge (target 63-69% hit rate)

Key Findings (VALIDATED with real lines):
- catboost_v8 + UNDER + 5+ edge = 88.3% hit rate
- catboost_v8 + OVER + 5+ edge = 83.9% hit rate
- catboost_v8 + 3-5 edge = 74-79% hit rate
- catboost_v8 + <3 edge = 63-69% hit rate
- Other systems (ensemble, zone_matchup, etc.) = 21-26% hit rate - DO NOT USE
- 88-90% confidence tier excluded (broken)

See: docs/08-projects/current/ml-model-v8-deployment/CRITICAL-DATA-AUDIT-2026-01-14.md
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float

logger = logging.getLogger(__name__)


# Tier configuration VALIDATED with real sportsbook lines (catboost_v8 only)
# See: docs/08-projects/current/ml-model-v8-deployment/CRITICAL-DATA-AUDIT-2026-01-14.md
# IMPORTANT: Only use catboost_v8 system - other systems hit 21-26%
TIER_CONFIG = {
    'premium': {
        'system_id': 'catboost_v9',
        'min_edge': 5.0,
        'max_picks': 5,
        'target_hit_rate': '83-88%',  # VALIDATED: UNDER 88.3%, OVER 83.9%
    },
    'strong': {
        'system_id': 'catboost_v9',
        'min_edge': 3.0,
        'max_edge': 5.0,
        'max_picks': 10,
        'target_hit_rate': '74-79%',  # VALIDATED: UNDER 79.3%, OVER 74.6%
    },
    'value': {
        'system_id': 'catboost_v9',
        'min_edge': 0.0,
        'max_edge': 3.0,
        'max_picks': 10,
        'target_hit_rate': '63-69%',  # VALIDATED: UNDER 69.3%, OVER 63.3%
    },
}

# Criteria that should ALWAYS exclude a pick from best bets
# Based on VALIDATED analysis with real sportsbook lines
AVOID_CRITERIA = {
    'non_catboost_systems': True,     # Other systems hit 21-26% - NEVER USE
    'min_edge_threshold': 0.0,        # No minimum, but tiers prioritize by edge
    'max_predicted_points': 25,       # Star players less predictable
    'exclude_confidence_range': (0.88, 0.90),  # This tier hits poorly
    # NOTE: OVER is now ALLOWED - catboost_v8 + OVER + 5+ edge = 83.9%
}


class BestBetsExporter(BaseExporter):
    """
    Export best bets (top picks) to JSON using tiered selection.

    Output files:
    - best-bets/{date}.json - Best bets for a specific date
    - best-bets/latest.json - Most recent best bets

    Tiered Selection Methodology (based on 10K+ prediction analysis):
    1. Apply AVOID criteria to exclude low-quality picks:
       - Exclude OVER recommendations (53% hit rate vs 95% for UNDER)
       - Exclude edge < 2 points (17-24% hit rate)
       - Exclude star players (25+ predicted points, 43% hit rate)
       - Exclude 88-90% confidence tier (42% hit rate - broken)
    2. Classify remaining picks into tiers:
       - Premium: 90%+ conf, 5+ edge, <18 pts (target 92%+ hit rate)
       - Strong: 90%+ conf, 4+ edge, <20 pts (target 80%+ hit rate)
       - Value: 80%+ conf, 5+ edge, <22 pts (target 70%+ hit rate)
    3. Select picks by tier priority, respecting max_picks per tier
    4. Rank within tier by composite score

    JSON structure:
    {
        "game_date": "2021-11-10",
        "generated_at": "2025-12-10T...",
        "methodology": "...",
        "tier_summary": {"premium": 3, "strong": 5, "value": 7},
        "picks": [
            {
                "rank": 1,
                "tier": "premium",
                "player_lookup": "player_name",
                "recommendation": "UNDER",
                "line": 12.5,
                "predicted": 7.2,
                "edge": 5.3,
                "confidence": 0.92,
                "composite_score": 0.91,
                ...
            }
        ]
    }
    """

    DEFAULT_TOP_N = 25  # Increased to accommodate tiered selection

    def generate_json(self, target_date: str, top_n: int = None) -> Dict[str, Any]:
        """
        Generate best bets JSON for a specific date using tiered selection.

        Args:
            target_date: Date string in YYYY-MM-DD format
            top_n: Number of top picks to include (default 25)

        Returns:
            Dictionary ready for JSON serialization
        """
        if top_n is None:
            top_n = self.DEFAULT_TOP_N

        # Query predictions with tiered ranking data
        picks = self._query_ranked_predictions(target_date, top_n)

        if not picks:
            logger.warning(f"No best bets found for {target_date}")
            return self._empty_response(target_date)

        # Format picks with tier information
        formatted_picks = self._format_picks(picks)

        # Calculate tier summary
        tier_summary = {'premium': 0, 'strong': 0, 'value': 0, 'standard': 0}
        for pick in formatted_picks:
            tier = pick.get('tier', 'standard')
            if tier in tier_summary:
                tier_summary[tier] += 1

        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'methodology': 'Tiered selection: UNDER only, edge/confidence thresholds, excludes stars and broken 88-90% tier',
            'total_picks': len(formatted_picks),
            'tier_summary': tier_summary,
            'picks': formatted_picks
        }

    def _query_ranked_predictions(self, target_date: str, top_n: int) -> List[Dict]:
        """
        Query predictions using tiered selection based on VALIDATED analysis.

        CRITICAL: Updated 2026-01-14 per CRITICAL-DATA-AUDIT-2026-01-14.md
        CRITICAL: Updated 2026-02-11 for Sprint 2C - Date-based table selection

        Table Selection:
        - Current/Future dates (>= today): Use player_prop_predictions table
        - Historical dates (< today): Use prediction_accuracy table

        Filtering:
        - catboost_v8 ONLY (other systems hit 21-26%)
        - Both UNDER and OVER allowed (UNDER 88.3%, OVER 83.9% with 5+ edge)
        - Predicted points < 25 (stars less predictable)
        - Exclude 88-90% confidence tier (broken)

        Tier classification (by edge):
        - Premium: 5+ edge (83-88% hit rate)
        - Strong: 3-5 edge (74-79% hit rate)
        - Value: <3 edge (63-69% hit rate)
        """
        from datetime import datetime
        target = datetime.strptime(target_date, '%Y-%m-%d').date()
        today = datetime.now().date()

        # Explicit boolean flag for table selection (Opus: not string matching)
        use_predictions_table = target >= today

        # Build query based on table selection
        if use_predictions_table:
            # Current/Future: Use active predictions
            query = """
            WITH player_history AS (
                -- Pre-compute player historical accuracy (UNDER only for consistency)
                SELECT
                    player_lookup,
                    COUNT(*) as sample_size,
                    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END), 3) as historical_accuracy
                FROM `nba-props-platform.nba_predictions.prediction_accuracy`
                WHERE system_id = 'catboost_v9'
                  AND game_date < @target_date
                  AND recommendation = 'UNDER'
                GROUP BY player_lookup
            ),
            player_names AS (
                -- Get player full names from registry
                SELECT player_lookup, player_name
                FROM `nba-props-platform.nba_reference.nba_players_registry`
                QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
            ),
            fatigue_data AS (
                -- Get fatigue scores for the date
                SELECT
                    player_lookup,
                    fatigue_score
                FROM `nba-props-platform.nba_precompute.player_composite_factors`
                WHERE game_date = @target_date
            ),
            game_context AS (
                -- Get team context for current/future dates
                SELECT
                    player_lookup,
                    game_id,
                    team_abbr,
                    opponent_team_abbr
                FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
                WHERE game_date = @target_date
            ),
            predictions AS (
                SELECT
                    p.player_lookup,
                    COALESCE(pn.player_name, p.player_lookup) as player_full_name,
                    p.game_id,
                    gc.team_abbr,
                    gc.opponent_team_abbr,
                    p.predicted_points,
                    NULL as actual_points,  -- Not graded yet
                    p.current_points_line as line_value,
                    p.recommendation,
                    NULL as prediction_correct,  -- Not graded yet
                    p.confidence_score,
                    NULL as absolute_error,  -- Not graded yet
                    NULL as signed_error,  -- Not graded yet
                    ABS(p.predicted_points - p.current_points_line) as edge,
                    h.historical_accuracy as player_historical_accuracy,
                    h.sample_size as player_sample_size,
                    f.fatigue_score
                FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
                LEFT JOIN player_history h ON p.player_lookup = h.player_lookup
                LEFT JOIN player_names pn ON p.player_lookup = pn.player_lookup
                LEFT JOIN fatigue_data f ON p.player_lookup = f.player_lookup
                LEFT JOIN game_context gc ON p.player_lookup = gc.player_lookup AND p.game_id = gc.game_id
                WHERE p.game_date = @target_date
                  AND p.system_id = 'catboost_v9'  -- CRITICAL: Only catboost_v9
                  AND p.is_active = TRUE  -- Only active predictions
                  -- VALIDATED FILTERS per CRITICAL-DATA-AUDIT-2026-01-14.md:
                  AND p.recommendation IN ('UNDER', 'OVER')  -- Both allowed: UNDER 88%, OVER 84% with 5+ edge
                  AND p.predicted_points < 25     -- Stars less predictable
                  AND NOT (p.confidence_score >= 0.88 AND p.confidence_score < 0.90)  -- Exclude broken tier
                  AND p.current_points_line IS NOT NULL    -- Must have real betting line
                  -- Session 209: Quality filter (12.1% vs 50.3% hit rate)
                  AND p.quality_alert_level = 'green'
            ),"""
        else:
            # Historical: Use graded predictions
            query = """
            WITH player_history AS (
                -- Pre-compute player historical accuracy (UNDER only for consistency)
                SELECT
                    player_lookup,
                    COUNT(*) as sample_size,
                    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END), 3) as historical_accuracy
                FROM `nba-props-platform.nba_predictions.prediction_accuracy`
                WHERE system_id = 'catboost_v9'
                  AND game_date < @target_date
                  AND recommendation = 'UNDER'
                GROUP BY player_lookup
            ),
            player_names AS (
                -- Get player full names from registry
                SELECT player_lookup, player_name
                FROM `nba-props-platform.nba_reference.nba_players_registry`
                QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
            ),
            fatigue_data AS (
                -- Get fatigue scores for the date
                SELECT
                    player_lookup,
                    fatigue_score
                FROM `nba-props-platform.nba_precompute.player_composite_factors`
                WHERE game_date = @target_date
            ),
            quality_data AS (
                -- Session 209: Get quality data for historical predictions
                SELECT
                    player_lookup,
                    game_date,
                    quality_alert_level
                FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
                WHERE game_date = @target_date
            ),
            predictions AS (
                SELECT
                    p.player_lookup,
                    COALESCE(pn.player_name, p.player_lookup) as player_full_name,
                    p.game_id,
                    p.team_abbr,
                    p.opponent_team_abbr,
                    p.predicted_points,
                    p.actual_points,
                    p.line_value,
                    p.recommendation,
                    p.prediction_correct,
                    p.confidence_score,
                    p.absolute_error,
                    p.signed_error,
                    ABS(p.predicted_points - p.line_value) as edge,
                    h.historical_accuracy as player_historical_accuracy,
                    h.sample_size as player_sample_size,
                    f.fatigue_score,
                    q.quality_alert_level  -- Session 209: Quality filter
                FROM `nba-props-platform.nba_predictions.prediction_accuracy` p
                LEFT JOIN player_history h ON p.player_lookup = h.player_lookup
                LEFT JOIN player_names pn ON p.player_lookup = pn.player_lookup
                LEFT JOIN fatigue_data f ON p.player_lookup = f.player_lookup
                LEFT JOIN quality_data q ON p.player_lookup = q.player_lookup AND p.game_date = q.game_date
                WHERE p.game_date = @target_date
                  AND p.system_id = 'catboost_v9'  -- CRITICAL: Only catboost_v9
                  -- VALIDATED FILTERS per CRITICAL-DATA-AUDIT-2026-01-14.md:
                  AND p.recommendation IN ('UNDER', 'OVER')  -- Both allowed: UNDER 88%, OVER 84% with 5+ edge
                  AND p.predicted_points < 25     -- Stars less predictable
                  AND NOT (p.confidence_score >= 0.88 AND p.confidence_score < 0.90)  -- Exclude broken tier
                  AND p.line_value IS NOT NULL    -- Must have real betting line
                  AND p.line_value != 20          -- Exclude fake line=20 data from pre-v3.2 worker
                  -- Session 209: Quality filter (12.1% vs 50.3% hit rate)
                  AND COALESCE(q.quality_alert_level, 'unknown') = 'green'
            ),"""

        # Append shared scoring/ranking CTEs (same for both branches)
        query += """
        scored AS (
            SELECT
                *,
                -- Edge factor: 1 + edge/10, capped at 1.5
                LEAST(1.5, 1.0 + edge / 10.0) as edge_factor,
                -- Historical factor: only use player accuracy if sample_size >= 5
                -- This prevents inflated scores from 1-4 game samples (e.g., 100% on 1 game)
                CASE
                    WHEN player_sample_size >= 5 THEN player_historical_accuracy
                    ELSE 0.85  -- Default for unknown/low-sample players
                END as hist_factor,
                -- Composite score
                confidence_score
                    * LEAST(1.5, 1.0 + edge / 10.0)
                    * CASE
                        WHEN player_sample_size >= 5 THEN player_historical_accuracy
                        ELSE 0.85
                      END as composite_score,
                -- Tier classification based on VALIDATED edge performance
                -- See CRITICAL-DATA-AUDIT-2026-01-14.md for validation
                CASE
                    WHEN edge >= 5.0 THEN 'premium'   -- 83-88% hit rate
                    WHEN edge >= 3.0 THEN 'strong'    -- 74-79% hit rate
                    ELSE 'value'                       -- 63-69% hit rate
                END as tier,
                -- Tier sort order: edge is the primary driver of hit rate
                CASE
                    WHEN edge >= 5.0 THEN 1  -- Premium: 83-88%
                    WHEN edge >= 3.0 THEN 2  -- Strong: 74-79%
                    ELSE 3                    -- Value: 63-69%
                END as tier_order
            FROM predictions
        ),
        ranked AS (
            -- Rank picks within each tier by composite score
            -- This enables per-tier limits: 5 premium, 10 strong, 10 value
            SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY tier ORDER BY composite_score DESC) as tier_rank
            FROM scored
        ),
        filtered AS (
            -- Apply per-tier limits based on TIER_CONFIG max_picks
            -- Premium (5+ edge): 5 picks, Strong (3-5 edge): 10 picks, Value (<3 edge): 10 picks
            SELECT *
            FROM ranked
            WHERE (tier = 'premium' AND tier_rank <= 5)
               OR (tier = 'strong' AND tier_rank <= 10)
               OR (tier = 'value' AND tier_rank <= 10)
        )
        SELECT *
        FROM filtered
        ORDER BY tier_order ASC, composite_score DESC
        LIMIT @top_n
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('top_n', 'INT64', top_n)
        ]

        return self.query_to_list(query, params)

    def _format_picks(self, picks: List[Dict]) -> List[Dict[str, Any]]:
        """Format picks for JSON output."""
        formatted = []

        for rank, pick in enumerate(picks, 1):
            # Determine result if we have actual data
            if pick['actual_points'] is not None:
                if pick['prediction_correct'] is True:
                    result = 'WIN'
                elif pick['prediction_correct'] is False:
                    result = 'LOSS'
                else:
                    result = 'PUSH'
            else:
                result = 'PENDING'

            # Build rationale
            rationale = self._build_rationale(pick)

            # Compute fatigue level from score
            fatigue_score = pick.get('fatigue_score')
            if fatigue_score is not None:
                if fatigue_score >= 95:
                    fatigue_level = 'fresh'
                elif fatigue_score >= 75:
                    fatigue_level = 'normal'
                else:
                    fatigue_level = 'tired'
            else:
                fatigue_level = None

            formatted.append({
                'rank': rank,
                'tier': pick.get('tier', 'standard'),
                'player_lookup': pick['player_lookup'],
                'player_full_name': pick.get('player_full_name', pick['player_lookup']),
                'game_id': pick['game_id'],
                'team': pick['team_abbr'],
                'opponent': pick['opponent_team_abbr'],
                'recommendation': pick['recommendation'],
                'line': safe_float(pick['line_value']),
                'predicted': safe_float(pick['predicted_points']),
                'edge': safe_float(pick['edge']),
                'confidence': safe_float(pick['confidence_score']),
                'composite_score': round(safe_float(pick['composite_score']) or 0, 3),
                'player_historical_accuracy': safe_float(pick['player_historical_accuracy']),
                'player_sample_size': pick['player_sample_size'],
                'fatigue_score': safe_float(fatigue_score),
                'fatigue_level': fatigue_level,
                'rationale': rationale,
                'result': result,
                'actual': pick['actual_points'],
                'error': safe_float(pick['absolute_error'])
            })

        return formatted

    def _build_rationale(self, pick: Dict) -> List[str]:
        """Build human-readable rationale for the pick."""
        rationale = []

        # Tier-specific lead rationale
        tier = pick.get('tier', 'standard')
        if tier == 'premium':
            rationale.append("Premium pick: highest confidence tier (target 92%+ hit rate)")
        elif tier == 'strong':
            rationale.append("Strong pick: high confidence tier (target 80%+ hit rate)")
        elif tier == 'value':
            rationale.append("Value pick: solid confidence with strong edge (target 70%+ hit rate)")

        # Confidence
        conf = pick.get('confidence_score')
        if conf and conf >= 0.90:
            rationale.append(f"High confidence ({conf:.0%})")
        elif conf and conf >= 0.80:
            rationale.append(f"Good confidence ({conf:.0%})")

        # Edge
        edge = pick.get('edge')
        if edge and edge >= 5.0:
            rationale.append(f"Strong edge ({edge:.1f} points)")
        elif edge and edge >= 4.0:
            rationale.append(f"Solid edge ({edge:.1f} points)")
        elif edge and edge >= 2.0:
            rationale.append(f"Moderate edge ({edge:.1f} points)")

        # Player tier (predicted points indicates role)
        predicted = pick.get('predicted_points')
        if predicted and predicted < 12:
            rationale.append("Bench player (model excels here: 89% hit rate)")
        elif predicted and predicted < 18:
            rationale.append("Rotation player (model performs well: 73%+ hit rate)")

        # Historical accuracy
        hist = pick.get('player_historical_accuracy')
        sample = pick.get('player_sample_size', 0)
        if hist and sample >= 5:
            if hist >= 0.80:
                rationale.append(f"Strong track record ({hist:.0%} accuracy, {sample} games)")
            elif hist >= 0.70:
                rationale.append(f"Good track record ({hist:.0%} accuracy, {sample} games)")

        # Fatigue factor
        fatigue = pick.get('fatigue_score')
        if fatigue is not None:
            if fatigue >= 95:
                rationale.append(f"Well-rested (fatigue: {fatigue:.0f})")
            elif fatigue < 75:
                rationale.append(f"Elevated fatigue (fatigue: {fatigue:.0f})")

        # If no rationale beyond tier, add generic
        if len(rationale) <= 1:
            rationale.append("Meets selection criteria")

        return rationale

    def _empty_response(self, target_date: str) -> Dict[str, Any]:
        """Return empty response when no data available."""
        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'methodology': 'Tiered selection: UNDER only, edge/confidence thresholds, excludes stars and broken 88-90% tier',
            'total_picks': 0,
            'tier_summary': {'premium': 0, 'strong': 0, 'value': 0, 'standard': 0},
            'picks': []
        }

    def export(self, target_date: str, top_n: int = None, update_latest: bool = True) -> str:
        """
        Generate and upload best bets JSON.

        Args:
            target_date: Date string in YYYY-MM-DD format
            top_n: Number of top picks (default 15)
            update_latest: Whether to also update latest.json

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting best bets for {target_date}")

        json_data = self.generate_json(target_date, top_n)

        # Upload date-specific file
        path = f'best-bets/{target_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=86400')

        # Optionally update latest.json
        if update_latest:
            self.upload_to_gcs(json_data, 'best-bets/latest.json', 'public, max-age=300')
            logger.info("Updated best-bets/latest.json")

        return gcs_path
