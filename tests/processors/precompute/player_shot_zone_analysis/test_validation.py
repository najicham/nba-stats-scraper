"""
Path: tests/processors/precompute/player_shot_zone_analysis/test_validation.py

Validation Tests for Player Shot Zone Analysis Processor

Tests against REAL BigQuery data to validate:
- Output schema correctness
- Data quality in production
- Calculation accuracy
- Completeness checks
- Edge case handling

These tests require:
- BigQuery credentials configured
- Processor has run successfully
- Data exists in nba_precompute.player_shot_zone_analysis

Run with: pytest test_validation.py -v
Duration: ~30-60 seconds (queries real BigQuery)

⚠️ NOTE: These tests query production data and may incur costs.
Run after processor completes nightly.

Created: October 30, 2025
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from google.cloud import bigquery
import os

# Skip tests if not in validation environment
SKIP_VALIDATION = os.environ.get('SKIP_VALIDATION_TESTS', 'false').lower() == 'true'
SKIP_REASON = "Validation tests disabled (set SKIP_VALIDATION_TESTS=false to enable)"


@pytest.fixture(scope='module')
def bq_client():
    """Create BigQuery client for validation queries."""
    if SKIP_VALIDATION:
        pytest.skip(SKIP_REASON)
    return bigquery.Client()


@pytest.fixture(scope='module')
def project_id(bq_client):
    """Get project ID."""
    return bq_client.project


@pytest.fixture(scope='module')
def latest_analysis_date(bq_client, project_id):
    """Get the most recent analysis_date in the table."""
    query = f"""
    SELECT MAX(analysis_date) as latest_date
    FROM `{project_id}.nba_precompute.player_shot_zone_analysis`
    """
    result = list(bq_client.query(query).result())
    if not result or result[0].latest_date is None:
        pytest.skip("No data in player_shot_zone_analysis table")
    return result[0].latest_date


@pytest.fixture(scope='module')
def sample_data(bq_client, project_id, latest_analysis_date):
    """Load sample data from the latest run."""
    query = f"""
    SELECT *
    FROM `{project_id}.nba_precompute.player_shot_zone_analysis`
    WHERE analysis_date = '{latest_analysis_date}'
    LIMIT 1000
    """
    return bq_client.query(query).to_dataframe()


# ============================================================================
# SCHEMA VALIDATION TESTS
# ============================================================================

class TestSchemaValidation:
    """Validate output schema matches specification."""
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_required_fields_present(self, sample_data):
        """Test all required fields are present in output."""
        required_fields = [
            # Identifiers
            'player_lookup',
            'universal_player_id',
            'analysis_date',
            
            # Shot distribution (10 games)
            'paint_rate_last_10',
            'mid_range_rate_last_10',
            'three_pt_rate_last_10',
            'total_shots_last_10',
            'games_in_sample_10',
            'sample_quality_10',
            
            # Efficiency (10 games)
            'paint_pct_last_10',
            'mid_range_pct_last_10',
            'three_pt_pct_last_10',
            
            # Volume
            'paint_attempts_per_game',
            'mid_range_attempts_per_game',
            'three_pt_attempts_per_game',
            
            # Trends (20 games)
            'paint_rate_last_20',
            'paint_pct_last_20',
            'games_in_sample_20',
            'sample_quality_20',
            
            # Shot creation
            'assisted_rate_last_10',
            'unassisted_rate_last_10',
            
            # Player info
            'player_position',
            'primary_scoring_zone',
            
            # Quality
            'data_quality_tier',
            'calculation_notes',
            
            # v4.0 Source tracking
            'source_player_game_last_updated',
            'source_player_game_rows_found',
            'source_player_game_completeness_pct',
            
            # Early season
            'early_season_flag',
            'insufficient_data_reason',
            
            # Metadata
            'created_at',
            'processed_at'
        ]
        
        missing_fields = [f for f in required_fields if f not in sample_data.columns]
        assert len(missing_fields) == 0, f"Missing required fields: {missing_fields}"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_field_types_correct(self, sample_data):
        """Test field data types are correct."""
        # Get non-null sample for type checking
        non_null_sample = sample_data[sample_data['games_in_sample_10'] >= 10].iloc[0] if len(sample_data) > 0 else None
        
        if non_null_sample is None:
            pytest.skip("No records with 10+ games for type validation")
        
        # Check numeric fields
        assert pd.api.types.is_float_dtype(sample_data['paint_rate_last_10'].dtype) or \
               sample_data['paint_rate_last_10'].dtype == 'object', "paint_rate should be float or allow NULL"
        
        assert pd.api.types.is_integer_dtype(sample_data['games_in_sample_10'].dtype), \
               "games_in_sample should be integer"
        
        # Check string fields
        assert sample_data['player_lookup'].dtype == 'object', "player_lookup should be string"
        assert sample_data['sample_quality_10'].dtype == 'object', "sample_quality should be string"


# ============================================================================
# DATA QUALITY TESTS
# ============================================================================

class TestDataQuality:
    """Validate data quality in production."""
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_no_duplicate_players(self, bq_client, project_id, latest_analysis_date):
        """Test no duplicate player records for same analysis_date."""
        query = f"""
        SELECT player_lookup, COUNT(*) as count
        FROM `{project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{latest_analysis_date}'
        GROUP BY player_lookup
        HAVING COUNT(*) > 1
        """
        duplicates = bq_client.query(query).to_dataframe()
        assert len(duplicates) == 0, f"Found {len(duplicates)} duplicate players"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_rates_sum_to_100_percent(self, sample_data):
        """Test paint + mid-range + three-point rates sum to ~100%."""
        # Filter to records with data
        valid_records = sample_data[
            (sample_data['paint_rate_last_10'].notna()) &
            (sample_data['mid_range_rate_last_10'].notna()) &
            (sample_data['three_pt_rate_last_10'].notna())
        ]
        
        if len(valid_records) == 0:
            pytest.skip("No records with complete rate data")
        
        # Calculate sum
        valid_records['rate_sum'] = (
            valid_records['paint_rate_last_10'] +
            valid_records['mid_range_rate_last_10'] +
            valid_records['three_pt_rate_last_10']
        )
        
        # Check each record
        for _, row in valid_records.iterrows():
            assert 99.0 <= row['rate_sum'] <= 101.0, \
                f"Player {row['player_lookup']}: rates sum to {row['rate_sum']}%, expected ~100%"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_shooting_percentages_valid_range(self, sample_data):
        """Test all shooting percentages are between 0 and 1."""
        pct_fields = [
            'paint_pct_last_10',
            'mid_range_pct_last_10',
            'three_pt_pct_last_10',
            'paint_pct_last_20'
        ]
        
        for field in pct_fields:
            valid_values = sample_data[sample_data[field].notna()][field]
            if len(valid_values) > 0:
                assert valid_values.min() >= 0.0, f"{field} has negative values"
                assert valid_values.max() <= 1.0, f"{field} has values > 1.0"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_games_in_sample_reasonable(self, sample_data):
        """Test games_in_sample values are reasonable."""
        # 10-game sample should be 0-10
        assert sample_data['games_in_sample_10'].min() >= 0
        assert sample_data['games_in_sample_10'].max() <= 15  # Allow some buffer
        
        # 20-game sample should be 0-20
        assert sample_data['games_in_sample_20'].min() >= 0
        assert sample_data['games_in_sample_20'].max() <= 25  # Allow some buffer
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_primary_zone_valid_values(self, sample_data):
        """Test primary_scoring_zone contains only valid values."""
        valid_zones = {'paint', 'mid_range', 'perimeter', 'balanced', None}
        actual_zones = set(sample_data['primary_scoring_zone'].unique())
        
        invalid_zones = actual_zones - valid_zones
        assert len(invalid_zones) == 0, f"Invalid primary zones found: {invalid_zones}"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_sample_quality_valid_values(self, sample_data):
        """Test sample_quality fields contain only valid values."""
        valid_qualities = {'excellent', 'good', 'limited', 'insufficient'}
        
        actual_10 = set(sample_data['sample_quality_10'].unique())
        invalid_10 = actual_10 - valid_qualities
        assert len(invalid_10) == 0, f"Invalid sample_quality_10 values: {invalid_10}"
        
        actual_20 = set(sample_data['sample_quality_20'].unique())
        invalid_20 = actual_20 - valid_qualities
        assert len(invalid_20) == 0, f"Invalid sample_quality_20 values: {invalid_20}"


# ============================================================================
# COMPLETENESS TESTS
# ============================================================================

class TestCompleteness:
    """Validate data completeness."""
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_minimum_player_count(self, bq_client, project_id, latest_analysis_date):
        """Test at least 400 active players processed."""
        query = f"""
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `{project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{latest_analysis_date}'
        """
        result = list(bq_client.query(query).result())[0]
        assert result.player_count >= 400, \
            f"Expected at least 400 players, found {result.player_count}"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_high_quality_data_majority(self, sample_data):
        """Test majority of players have high-quality data (10+ games)."""
        high_quality = len(sample_data[sample_data['data_quality_tier'] == 'high'])
        total = len(sample_data)
        
        if total > 0:
            pct_high_quality = (high_quality / total) * 100
            assert pct_high_quality >= 70, \
                f"Only {pct_high_quality:.1f}% high-quality data, expected ≥70%"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_source_tracking_populated(self, sample_data):
        """Test v4.0 source tracking fields are populated."""
        # Check non-null counts
        non_null_last_updated = sample_data['source_player_game_last_updated'].notna().sum()
        non_null_rows_found = sample_data['source_player_game_rows_found'].notna().sum()
        
        total = len(sample_data)
        if total > 0:
            assert non_null_last_updated / total >= 0.95, \
                "Most records should have source_player_game_last_updated"
            assert non_null_rows_found / total >= 0.95, \
                "Most records should have source_player_game_rows_found"


# ============================================================================
# CALCULATION ACCURACY TESTS
# ============================================================================

class TestCalculationAccuracy:
    """Spot-check calculations with real data."""
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_paint_dominant_players_identified(self, sample_data):
        """Test paint-dominant players are correctly identified."""
        paint_dominant = sample_data[
            (sample_data['primary_scoring_zone'] == 'paint') &
            (sample_data['paint_rate_last_10'].notna())
        ]
        
        if len(paint_dominant) > 0:
            # All paint-dominant players should have paint_rate >= 40%
            min_paint_rate = paint_dominant['paint_rate_last_10'].min()
            assert min_paint_rate >= 38.0, \
                f"Paint-dominant player has only {min_paint_rate}% paint rate"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_perimeter_players_identified(self, sample_data):
        """Test perimeter players are correctly identified."""
        perimeter = sample_data[
            (sample_data['primary_scoring_zone'] == 'perimeter') &
            (sample_data['three_pt_rate_last_10'].notna())
        ]
        
        if len(perimeter) > 0:
            # All perimeter players should have three_pt_rate >= 40%
            min_three_rate = perimeter['three_pt_rate_last_10'].min()
            assert min_three_rate >= 38.0, \
                f"Perimeter player has only {min_three_rate}% three-point rate"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_assisted_unassisted_sum_to_100(self, sample_data):
        """Test assisted + unassisted rates sum to ~100%."""
        valid_records = sample_data[
            (sample_data['assisted_rate_last_10'].notna()) &
            (sample_data['unassisted_rate_last_10'].notna())
        ]
        
        if len(valid_records) > 0:
            valid_records['creation_sum'] = (
                valid_records['assisted_rate_last_10'] +
                valid_records['unassisted_rate_last_10']
            )
            
            # Check sum is close to 100%
            for _, row in valid_records.head(10).iterrows():  # Check first 10
                assert 99.0 <= row['creation_sum'] <= 101.0, \
                    f"Player {row['player_lookup']}: assisted+unassisted = {row['creation_sum']}%"


# ============================================================================
# FRESHNESS TESTS
# ============================================================================

class TestFreshness:
    """Validate data freshness."""
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_data_is_recent(self, latest_analysis_date):
        """Test latest data is within last 7 days."""
        days_old = (date.today() - latest_analysis_date).days
        assert days_old <= 7, \
            f"Latest data is {days_old} days old, expected ≤7 days"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_processed_at_recent(self, sample_data):
        """Test processed_at timestamps are recent."""
        if len(sample_data) == 0:
            pytest.skip("No data to validate")
        
        # Parse timestamps
        sample_data['processed_dt'] = pd.to_datetime(sample_data['processed_at'])
        most_recent = sample_data['processed_dt'].max()
        
        hours_old = (datetime.now() - most_recent.to_pydatetime()).total_seconds() / 3600
        assert hours_old <= 48, \
            f"Most recent processing was {hours_old:.1f} hours ago, expected ≤48 hours"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestEdgeCases:
    """Validate edge case handling in production."""
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_early_season_players_handled(self, bq_client, project_id, latest_analysis_date):
        """Test early season players are properly flagged."""
        query = f"""
        SELECT 
            COUNT(*) as early_season_count,
            COUNT(CASE WHEN games_in_sample_10 < 10 THEN 1 END) as insufficient_games
        FROM `{project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{latest_analysis_date}'
          AND early_season_flag = TRUE
        """
        result = list(bq_client.query(query).result())[0]
        
        # If there are early season flags, they should have <10 games
        if result.early_season_count > 0:
            assert result.insufficient_games == result.early_season_count, \
                "All early_season_flag=TRUE records should have <10 games"
    
    @pytest.mark.skipif(SKIP_VALIDATION, reason=SKIP_REASON)
    def test_zero_shot_zones_handled(self, sample_data):
        """Test players with 0 attempts in a zone are handled correctly."""
        # Find players with 0 mid-range attempts
        zero_mid_range = sample_data[
            sample_data['mid_range_attempts_per_game'] == 0
        ]
        
        if len(zero_mid_range) > 0:
            # mid_range_pct should be NULL for these players
            assert zero_mid_range['mid_range_pct_last_10'].isna().all(), \
                "Players with 0 mid-range attempts should have NULL mid_range_pct"


# ============================================================================
# TEST RUNNER
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])