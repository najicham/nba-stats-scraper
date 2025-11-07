# File: data_processors/precompute/ml_feature_store/quality_scorer.py
"""
Quality Scorer - Calculate Feature Quality Score

Calculates 0-100 quality score based on data sources:
- Phase 4: 100 points (preferred)
- Phase 3: 75 points (fallback)
- Default: 40 points (no data, using defaults)
- Calculated: 100 points (always available)
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class QualityScorer:
    """Calculate feature quality score (0-100)."""
    
    # Source weights
    SOURCE_WEIGHTS = {
        'phase4': 100,
        'phase3': 75,
        'default': 40,
        'calculated': 100  # Calculated features always high quality
    }
    
    def __init__(self):
        """Initialize quality scorer."""
        pass
    
    def calculate_quality_score(self, feature_sources: Dict[int, str]) -> float:
        """
        Calculate overall feature quality score.
        
        Quality = weighted average of source quality across all 25 features.
        
        Args:
            feature_sources: Dict mapping feature index (0-24) to source
                           ('phase4', 'phase3', 'default', 'calculated')
            
        Returns:
            float: Quality score [0.0, 100.0]
        """
        if not feature_sources:
            logger.warning("No feature sources provided, returning 0")
            return 0.0
        
        # Calculate weighted sum
        total_weight = 0.0
        for feature_idx in range(25):
            source = feature_sources.get(feature_idx, 'default')
            weight = self.SOURCE_WEIGHTS.get(source, 40)
            total_weight += weight
        
        # Average
        quality_score = total_weight / 25.0
        
        logger.debug(f"Quality score: {quality_score:.1f} (sources: {self._summarize_sources(feature_sources)})")
        
        return round(quality_score, 2)
    
    def determine_primary_source(self, feature_sources: Dict[int, str]) -> str:
        """
        Determine primary data source used.
        
        Rules:
        - If >90% Phase 4: 'phase4'
        - If >50% Phase 4: 'phase4_partial'
        - If >50% Phase 3: 'phase3'
        - Otherwise: 'mixed'
        
        Args:
            feature_sources: Dict mapping feature index to source
            
        Returns:
            str: Primary source identifier
        """
        phase4_count = sum(1 for s in feature_sources.values() if s == 'phase4')
        phase3_count = sum(1 for s in feature_sources.values() if s == 'phase3')
        calculated_count = sum(1 for s in feature_sources.values() if s == 'calculated')
        default_count = sum(1 for s in feature_sources.values() if s == 'default')
        
        total = len(feature_sources)
        
        if total == 0:
            return 'unknown'
        
        phase4_pct = phase4_count / total
        phase3_pct = phase3_count / total
        
        if phase4_pct >= 0.90:
            return 'phase4'
        elif phase4_pct >= 0.50:
            return 'phase4_partial'
        elif phase3_pct >= 0.50:
            return 'phase3'
        else:
            return 'mixed'
    
    def identify_data_tier(self, quality_score: float) -> str:
        """
        Classify quality score into tier.
        
        Args:
            quality_score: Quality score [0, 100]
            
        Returns:
            str: 'high', 'medium', or 'low'
        """
        if quality_score >= 95:
            return 'high'
        elif quality_score >= 70:
            return 'medium'
        else:
            return 'low'
    
    def _summarize_sources(self, feature_sources: Dict[int, str]) -> str:
        """Generate human-readable summary of sources."""
        phase4 = sum(1 for s in feature_sources.values() if s == 'phase4')
        phase3 = sum(1 for s in feature_sources.values() if s == 'phase3')
        calculated = sum(1 for s in feature_sources.values() if s == 'calculated')
        default = sum(1 for s in feature_sources.values() if s == 'default')
        
        return f"phase4={phase4}, phase3={phase3}, calc={calculated}, default={default}"
