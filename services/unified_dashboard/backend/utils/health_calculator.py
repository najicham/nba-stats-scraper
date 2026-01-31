"""
Health Score Calculator

Computes overall system health score (0-100) based on multiple dimensions:
- Pipeline execution success (30%)
- Data quality (25%)
- Prediction accuracy (25%)
- Service uptime (15%)
- Cost efficiency (5%)
"""
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


class HealthScoreCalculator:
    """Calculate system health scores"""

    # Weights for different health dimensions
    WEIGHTS = {
        'pipeline': 0.30,      # 30%: Pipeline execution success
        'data_quality': 0.25,  # 25%: Data completeness and correctness
        'ml_performance': 0.25,  # 25%: Model accuracy
        'services': 0.15,      # 15%: Infrastructure uptime
        'cost': 0.05           #  5%: Cost efficiency
    }

    # Thresholds for scoring
    THRESHOLDS = {
        'pipeline_success_excellent': 0.95,  # >95% = 100 points
        'pipeline_success_good': 0.90,       # >90% = 80 points
        'pipeline_success_fair': 0.80,       # >80% = 60 points
        'accuracy_excellent': 0.60,          # >60% = 100 points
        'accuracy_good': 0.56,               # >56% = 80 points
        'accuracy_fair': 0.52,               # >52% = 60 points
        'coverage_excellent': 0.95,          # >95% = 100 points
        'coverage_good': 0.90,               # >90% = 80 points
        'coverage_fair': 0.80,               # >80% = 60 points
    }

    @classmethod
    def calculate_overall_health(
        cls,
        pipeline_data: Dict[str, Any],
        processor_data: Dict[str, Any],
        summary_data: Dict[str, Any],
        shot_zone_quality: Dict[str, Any],
        heartbeats: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate overall system health score

        Args:
            pipeline_data: Phase completion data
            processor_data: Processor run statistics
            summary_data: Today's summary metrics
            shot_zone_quality: Shot zone quality metrics
            heartbeats: Processor heartbeat data

        Returns:
            Dict with overall score and breakdown by dimension
        """
        # Calculate dimension scores
        pipeline_score = cls._calculate_pipeline_score(processor_data, heartbeats)
        data_quality_score = cls._calculate_data_quality_score(
            summary_data, shot_zone_quality
        )
        ml_performance_score = cls._calculate_ml_performance_score(summary_data)
        services_score = cls._calculate_services_score(heartbeats)
        cost_score = 100  # TODO: Implement cost scoring

        # Weighted overall score
        overall_score = (
            pipeline_score * cls.WEIGHTS['pipeline'] +
            data_quality_score * cls.WEIGHTS['data_quality'] +
            ml_performance_score * cls.WEIGHTS['ml_performance'] +
            services_score * cls.WEIGHTS['services'] +
            cost_score * cls.WEIGHTS['cost']
        )

        # Determine status
        status = cls._determine_status(overall_score)

        return {
            'overall_score': round(overall_score, 0),
            'status': status,
            'breakdown': {
                'pipeline': {
                    'score': round(pipeline_score, 0),
                    'weight': cls.WEIGHTS['pipeline'],
                    'status': cls._determine_status(pipeline_score)
                },
                'data_quality': {
                    'score': round(data_quality_score, 0),
                    'weight': cls.WEIGHTS['data_quality'],
                    'status': cls._determine_status(data_quality_score)
                },
                'ml_performance': {
                    'score': round(ml_performance_score, 0),
                    'weight': cls.WEIGHTS['ml_performance'],
                    'status': cls._determine_status(ml_performance_score)
                },
                'services': {
                    'score': round(services_score, 0),
                    'weight': cls.WEIGHTS['services'],
                    'status': cls._determine_status(services_score)
                },
                'cost': {
                    'score': round(cost_score, 0),
                    'weight': cls.WEIGHTS['cost'],
                    'status': cls._determine_status(cost_score)
                }
            },
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

    @classmethod
    def _calculate_pipeline_score(
        cls,
        processor_data: Dict[str, Any],
        heartbeats: List[Dict[str, Any]]
    ) -> float:
        """
        Calculate pipeline health score based on success rates

        Args:
            processor_data: Processor run statistics
            heartbeats: Processor heartbeat data

        Returns:
            Score 0-100
        """
        if not processor_data.get('processors'):
            return 50  # Neutral score if no data

        # Calculate average success rate across all processors
        success_rates = [
            p['success_rate_pct'] / 100.0
            for p in processor_data['processors']
            if p.get('success_rate_pct') is not None
        ]

        if not success_rates:
            return 50

        avg_success_rate = sum(success_rates) / len(success_rates)

        # Check for stale heartbeats (reduce score if processors are stalled)
        stale_count = sum(1 for hb in heartbeats if hb.get('is_stale', False))
        total_heartbeats = len(heartbeats)
        stale_penalty = (stale_count / max(total_heartbeats, 1)) * 20  # Up to 20 point penalty

        # Score based on success rate
        if avg_success_rate >= cls.THRESHOLDS['pipeline_success_excellent']:
            score = 100
        elif avg_success_rate >= cls.THRESHOLDS['pipeline_success_good']:
            score = 80
        elif avg_success_rate >= cls.THRESHOLDS['pipeline_success_fair']:
            score = 60
        else:
            score = max(0, avg_success_rate * 100)

        return max(0, score - stale_penalty)

    @classmethod
    def _calculate_data_quality_score(
        cls,
        summary_data: Dict[str, Any],
        shot_zone_quality: Dict[str, Any]
    ) -> float:
        """
        Calculate data quality score based on coverage and completeness

        Args:
            summary_data: Today's summary metrics
            shot_zone_quality: Shot zone quality metrics

        Returns:
            Score 0-100
        """
        coverage_pct = summary_data.get('coverage_pct', 0) / 100.0
        shot_zone_completeness = shot_zone_quality.get('completeness_pct', 0) / 100.0

        # Score coverage
        if coverage_pct >= cls.THRESHOLDS['coverage_excellent']:
            coverage_score = 100
        elif coverage_pct >= cls.THRESHOLDS['coverage_good']:
            coverage_score = 80
        elif coverage_pct >= cls.THRESHOLDS['coverage_fair']:
            coverage_score = 60
        else:
            coverage_score = max(0, coverage_pct * 100)

        # Score shot zone quality (optional, doesn't fail system if missing)
        if shot_zone_completeness >= 0.80:
            shot_zone_score = 100
        elif shot_zone_completeness >= 0.60:
            shot_zone_score = 80
        else:
            shot_zone_score = max(0, shot_zone_completeness * 100)

        # Weight coverage more heavily (70%) vs shot zones (30%)
        return coverage_score * 0.7 + shot_zone_score * 0.3

    @classmethod
    def _calculate_ml_performance_score(cls, summary_data: Dict[str, Any]) -> float:
        """
        Calculate ML performance score based on prediction accuracy

        Args:
            summary_data: Today's summary metrics

        Returns:
            Score 0-100
        """
        accuracy_pct = summary_data.get('accuracy_pct', 0) / 100.0

        if accuracy_pct >= cls.THRESHOLDS['accuracy_excellent']:
            return 100
        elif accuracy_pct >= cls.THRESHOLDS['accuracy_good']:
            return 80
        elif accuracy_pct >= cls.THRESHOLDS['accuracy_fair']:
            return 60
        else:
            # Below breakeven (52.4%), score drops quickly
            return max(0, (accuracy_pct / 0.524) * 60)

    @classmethod
    def _calculate_services_score(cls, heartbeats: List[Dict[str, Any]]) -> float:
        """
        Calculate services health score based on heartbeats

        Args:
            heartbeats: Processor heartbeat data

        Returns:
            Score 0-100
        """
        if not heartbeats:
            return 100  # No heartbeats = assume healthy

        active_count = sum(1 for hb in heartbeats if not hb.get('is_stale', False))
        total_count = len(heartbeats)

        uptime_pct = active_count / total_count
        return uptime_pct * 100

    @staticmethod
    def _determine_status(score: float) -> str:
        """
        Determine status label from score

        Args:
            score: Health score (0-100)

        Returns:
            Status string: 'healthy', 'warning', 'critical'
        """
        if score >= 85:
            return 'healthy'
        elif score >= 65:
            return 'warning'
        else:
            return 'critical'
