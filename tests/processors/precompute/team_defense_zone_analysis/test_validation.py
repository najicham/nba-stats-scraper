"""
Path: tests/processors/precompute/team_defense_zone_analysis/test_validation.py

Data Validation Tests for Team Defense Zone Analysis

Tests run against actual BigQuery data to validate output quality.
Can be run nightly after processor completes.

Run with: pytest tests/precompute/test_team_defense_validation.py -v --bigquery
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from google.cloud import bigquery
from typing import Dict, List

# These tests require actual BigQuery access
# Skip if --bigquery flag not provided
bigquery_available = pytest.mark.skipif(
    not pytest.config.getoption("--bigquery", default=False),
    reason="Requires --bigquery flag and GCP credentials"
)


@bigquery_available
class TestOutputDataQuality:
    """Validate quality of processed data in BigQuery."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        """Create BigQuery client."""
        return bigquery.Client(project='nba-props-platform')
    
    @pytest.fixture(scope='class')
    def latest_data(self, bq_client):
        """Fetch latest processed data."""
        query = """
        SELECT *
        FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date = CURRENT_DATE()
        ORDER BY team_abbr
        """
        return bq_client.query(query).to_dataframe()
    
    def test_all_30_teams_processed(self, latest_data):
        """Verify all 30 NBA teams were processed."""
        assert len(latest_data) == 30, f"Expected 30 teams, got {len(latest_data)}"
        
        # Check no duplicates
        duplicate_count = latest_data['team_abbr'].duplicated().sum()
        assert duplicate_count == 0, f"Found {duplicate_count} duplicate teams"
    
    def test_no_missing_critical_fields(self, latest_data):
        """Verify all critical fields are populated (excluding early season)."""
        # Filter out early season placeholders
        real_data = latest_data[
            (latest_data['early_season_flag'].isna()) | 
            (latest_data['early_season_flag'] == False)
        ]
        
        if len(real_data) == 0:
            pytest.skip("All data is early season placeholders")
        
        critical_fields = [
            'team_abbr',
            'analysis_date',
            'paint_pct_allowed_last_15',
            'mid_range_pct_allowed_last_15',
            'three_pt_pct_allowed_last_15',
            'games_in_sample',
            'processed_at'
        ]
        
        for field in critical_fields:
            null_count = real_data[field].isna().sum()
            assert null_count == 0, f"Field '{field}' has {null_count} NULL values"
    
    def test_field_value_ranges(self, latest_data):
        """Verify all metric values are within valid ranges."""
        # Filter out early season
        real_data = latest_data[
            (latest_data['early_season_flag'].isna()) | 
            (latest_data['early_season_flag'] == False)
        ]
        
        if len(real_data) == 0:
            pytest.skip("All data is early season placeholders")
        
        # FG% allowed should be reasonable
        assert real_data['paint_pct_allowed_last_15'].min() >= 0.40, \
            "Paint FG% too low"
        assert real_data['paint_pct_allowed_last_15'].max() <= 0.75, \
            "Paint FG% too high"
        
        assert real_data['mid_range_pct_allowed_last_15'].min() >= 0.25, \
            "Mid-range FG% too low"
        assert real_data['mid_range_pct_allowed_last_15'].max() <= 0.60, \
            "Mid-range FG% too high"
        
        assert real_data['three_pt_pct_allowed_last_15'].min() >= 0.25, \
            "Three-point FG% too low"
        assert real_data['three_pt_pct_allowed_last_15'].max() <= 0.45, \
            "Three-point FG% too high"
        
        # Volume metrics
        assert real_data['paint_attempts_allowed_per_game'].min() >= 20.0, \
            "Paint attempts too low"
        assert real_data['paint_attempts_allowed_per_game'].max() <= 55.0, \
            "Paint attempts too high"
        
        assert real_data['three_pt_attempts_allowed_per_game'].min() >= 25.0, \
            "Three-point attempts too low"
        assert real_data['three_pt_attempts_allowed_per_game'].max() <= 45.0, \
            "Three-point attempts too high"
        
        # vs League average should be reasonable
        assert real_data['paint_defense_vs_league_avg'].min() >= -15.0, \
            "Paint vs league too negative"
        assert real_data['paint_defense_vs_league_avg'].max() <= 15.0, \
            "Paint vs league too positive"
        
        # Games in sample
        assert real_data['games_in_sample'].min() >= 15, \
            "Insufficient games in sample"
        assert real_data['games_in_sample'].max() <= 15, \
            "Too many games in sample"
    
    def test_strengths_weaknesses_identified(self, latest_data):
        """Verify strengths and weaknesses are identified."""
        real_data = latest_data[
            (latest_data['early_season_flag'].isna()) | 
            (latest_data['early_season_flag'] == False)
        ]
        
        if len(real_data) == 0:
            pytest.skip("All data is early season placeholders")
        
        # All teams should have strongest/weakest identified
        assert real_data['strongest_zone'].notna().all(), \
            "Some teams missing strongest_zone"
        assert real_data['weakest_zone'].notna().all(), \
            "Some teams missing weakest_zone"
        
        # Values should be valid
        valid_zones = ['paint', 'mid_range', 'perimeter']
        assert real_data['strongest_zone'].isin(valid_zones).all(), \
            "Invalid strongest_zone values"
        assert real_data['weakest_zone'].isin(valid_zones).all(), \
            "Invalid weakest_zone values"
        
        # Strongest and weakest should be different (unless all zones equal)
        same_count = (real_data['strongest_zone'] == real_data['weakest_zone']).sum()
        assert same_count == 0, \
            f"{same_count} teams have same strongest/weakest zone"
    
    def test_data_quality_tier_assignment(self, latest_data):
        """Verify data quality tiers are properly assigned."""
        # Check all have quality tier
        assert latest_data['data_quality_tier'].notna().all(), \
            "Some teams missing data_quality_tier"
        
        # Check values are valid
        valid_tiers = ['high', 'medium', 'low']
        assert latest_data['data_quality_tier'].isin(valid_tiers).all(), \
            "Invalid data_quality_tier values"
        
        # High quality should have 15 games
        high_quality = latest_data[latest_data['data_quality_tier'] == 'high']
        if len(high_quality) > 0:
            assert (high_quality['games_in_sample'] >= 15).all(), \
                "High quality teams should have 15+ games"
        
        # Low quality should have <10 games
        low_quality = latest_data[latest_data['data_quality_tier'] == 'low']
        if len(low_quality) > 0:
            assert (low_quality['games_in_sample'] < 10).all(), \
                "Low quality teams should have <10 games"


@bigquery_available
class TestSourceTrackingFields:
    """Validate v4.0 source tracking fields."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        return bigquery.Client(project='nba-props-platform')
    
    @pytest.fixture(scope='class')
    def latest_data(self, bq_client):
        query = """
        SELECT *
        FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date = CURRENT_DATE()
        """
        return bq_client.query(query).to_dataframe()
    
    def test_source_tracking_populated(self, latest_data):
        """Verify all source tracking fields are populated."""
        # Should have 3 fields per source
        source_fields = [
            'source_team_defense_last_updated',
            'source_team_defense_rows_found',
            'source_team_defense_completeness_pct'
        ]
        
        for field in source_fields:
            null_count = latest_data[field].isna().sum()
            assert null_count == 0, \
                f"Source tracking field '{field}' has {null_count} NULL values"
    
    def test_source_completeness_is_100(self, latest_data):
        """Verify source completeness is 100% (or near 100%)."""
        completeness = latest_data['source_team_defense_completeness_pct']
        
        # All should be >= 95%
        assert (completeness >= 95.0).all(), \
            f"Low completeness detected: min={completeness.min():.2f}%"
        
        # Most should be 100%
        perfect_count = (completeness == 100.0).sum()
        assert perfect_count >= len(latest_data) * 0.8, \
            f"Only {perfect_count}/{len(latest_data)} teams have 100% completeness"
    
    def test_source_data_is_fresh(self, latest_data):
        """Verify source data is recent (processed within 24 hours)."""
        now = datetime.utcnow()
        
        for idx, row in latest_data.iterrows():
            last_updated = pd.to_datetime(row['source_team_defense_last_updated'])
            age_hours = (now - last_updated).total_seconds() / 3600
            
            assert age_hours <= 24.0, \
                f"Team {row['team_abbr']} has stale data: {age_hours:.1f} hours old"
    
    def test_source_rows_found_reasonable(self, latest_data):
        """Verify rows_found is reasonable (450 expected for 30 teams x 15 games)."""
        rows_found = latest_data['source_team_defense_rows_found'].iloc[0]
        
        # Should be around 450 (30 teams x 15 games)
        # Allow some variance for teams with different game counts
        assert 400 <= rows_found <= 500, \
            f"Unexpected rows_found: {rows_found} (expected ~450)"


@bigquery_available  
class TestEarlySeasonHandling:
    """Validate early season placeholder behavior."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        return bigquery.Client(project='nba-props-platform')
    
    def test_early_season_placeholders(self, bq_client):
        """Test early season data (if exists)."""
        # Query first 2 weeks of season
        query = """
        SELECT *
        FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date BETWEEN '2024-10-22' AND '2024-11-05'
          AND early_season_flag = TRUE
        LIMIT 30
        """
        
        early_data = bq_client.query(query).to_dataframe()
        
        if len(early_data) == 0:
            pytest.skip("No early season data available")
        
        # Check placeholder structure
        assert (early_data['paint_pct_allowed_last_15'].isna()).all(), \
            "Early season should have NULL paint_pct"
        assert (early_data['mid_range_pct_allowed_last_15'].isna()).all(), \
            "Early season should have NULL mid_range_pct"
        assert (early_data['three_pt_pct_allowed_last_15'].isna()).all(), \
            "Early season should have NULL three_pt_pct"
        
        # Early season flag should be TRUE
        assert (early_data['early_season_flag'] == True).all(), \
            "early_season_flag should be TRUE"
        
        # Should have insufficient data reason
        assert early_data['insufficient_data_reason'].notna().all(), \
            "Early season should have insufficient_data_reason"
        
        # Source tracking should STILL be populated
        assert early_data['source_team_defense_last_updated'].notna().all(), \
            "Source tracking should be populated even for early season"


@bigquery_available
class TestHistoricalConsistency:
    """Validate consistency across dates."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        return bigquery.Client(project='nba-props-platform')
    
    def test_no_duplicate_dates_per_team(self, bq_client):
        """Verify no duplicate analysis_date per team."""
        query = """
        SELECT 
            team_abbr,
            analysis_date,
            COUNT(*) as row_count
        FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY team_abbr, analysis_date
        HAVING COUNT(*) > 1
        """
        
        duplicates = bq_client.query(query).to_dataframe()
        
        assert len(duplicates) == 0, \
            f"Found {len(duplicates)} duplicate date/team combinations"
    
    def test_processed_at_timestamps_sequential(self, bq_client):
        """Verify processed_at timestamps are sequential by date."""
        query = """
        SELECT 
            analysis_date,
            MIN(processed_at) as min_processed,
            MAX(processed_at) as max_processed
        FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY analysis_date
        ORDER BY analysis_date DESC
        """
        
        timestamps = bq_client.query(query).to_dataframe()
        
        if len(timestamps) < 2:
            pytest.skip("Need at least 2 dates of data")
        
        # Each day should be processed after the previous day
        for i in range(len(timestamps) - 1):
            current_day = timestamps.iloc[i]
            previous_day = timestamps.iloc[i + 1]
            
            # Current day processed after previous day (usually)
            # Allow same-day reprocessing
            assert current_day['max_processed'] >= previous_day['min_processed'], \
                f"Timestamps out of order for {current_day['analysis_date']}"
    
    def test_metrics_reasonable_variance_over_time(self, bq_client):
        """Verify metrics don't change drastically day-to-day."""
        query = """
        WITH team_metrics AS (
            SELECT 
                team_abbr,
                analysis_date,
                paint_pct_allowed_last_15,
                three_pt_pct_allowed_last_15,
                LAG(paint_pct_allowed_last_15) OVER (
                    PARTITION BY team_abbr 
                    ORDER BY analysis_date
                ) as prev_paint_pct,
                LAG(three_pt_pct_allowed_last_15) OVER (
                    PARTITION BY team_abbr 
                    ORDER BY analysis_date
                ) as prev_three_pt_pct
            FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
              AND early_season_flag IS NULL OR early_season_flag = FALSE
        )
        SELECT *
        FROM team_metrics
        WHERE prev_paint_pct IS NOT NULL
          AND ABS(paint_pct_allowed_last_15 - prev_paint_pct) > 0.10
        """
        
        large_changes = bq_client.query(query).to_dataframe()
        
        # Some variance is expected, but not too much
        assert len(large_changes) <= 5, \
            f"Found {len(large_changes)} teams with >10pp day-over-day changes"


@bigquery_available
class TestCrossTeamComparisons:
    """Validate data makes sense across teams."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        return bigquery.Client(project='nba-props-platform')
    
    @pytest.fixture(scope='class')
    def latest_data(self, bq_client):
        query = """
        SELECT *
        FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date = CURRENT_DATE()
          AND (early_season_flag IS NULL OR early_season_flag = FALSE)
        """
        return bq_client.query(query).to_dataframe()
    
    def test_league_average_is_centered(self, latest_data):
        """Verify vs_league_avg metrics are centered around 0."""
        if len(latest_data) == 0:
            pytest.skip("No real data available")
        
        # Average of all vs_league metrics should be near 0
        paint_avg = latest_data['paint_defense_vs_league_avg'].mean()
        mid_avg = latest_data['mid_range_defense_vs_league_avg'].mean()
        three_avg = latest_data['three_pt_defense_vs_league_avg'].mean()
        
        # Should be within +/- 1.0 pp of 0
        assert -1.0 <= paint_avg <= 1.0, \
            f"Paint vs league avg not centered: {paint_avg:.2f}"
        assert -1.0 <= mid_avg <= 1.0, \
            f"Mid-range vs league avg not centered: {mid_avg:.2f}"
        assert -1.0 <= three_avg <= 1.0, \
            f"Three-point vs league avg not centered: {three_avg:.2f}"
    
    def test_defensive_rating_distribution(self, latest_data):
        """Verify defensive ratings have reasonable distribution."""
        if len(latest_data) == 0:
            pytest.skip("No real data available")
        
        ratings = latest_data['defensive_rating_last_15']
        
        # Should have spread
        assert ratings.std() >= 3.0, \
            f"Defensive ratings too clustered: std={ratings.std():.2f}"
        
        # Range should be reasonable
        assert 100.0 <= ratings.min() <= 115.0, \
            f"Best defensive rating unexpected: {ratings.min():.1f}"
        assert 110.0 <= ratings.max() <= 125.0, \
            f"Worst defensive rating unexpected: {ratings.max():.1f}"
    
    def test_paint_defense_correlates_with_rating(self, latest_data):
        """Verify paint defense correlates with overall rating."""
        if len(latest_data) < 10:
            pytest.skip("Insufficient data for correlation test")
        
        # Teams allowing higher paint FG% should have worse ratings
        correlation = latest_data['paint_pct_allowed_last_15'].corr(
            latest_data['defensive_rating_last_15']
        )
        
        # Positive correlation expected (higher FG% = worse rating)
        assert correlation > 0.2, \
            f"Paint defense doesn't correlate with rating: {correlation:.3f}"


def pytest_addoption(parser):
    """Add --bigquery flag to pytest."""
    parser.addoption(
        "--bigquery",
        action="store_true",
        default=False,
        help="Run tests that require BigQuery access"
    )


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--bigquery', '--tb=short'])
