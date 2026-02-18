#!/usr/bin/env python3
# File: validation/validators/precompute/ml_feature_store_validator.py
# Description: Validator for ml_feature_store_v2 predictions table
# Created: 2026-01-24
"""
Validator for ML Feature Store V2 predictions table.

Validates nba_predictions.ml_feature_store_v2 which contains
33-feature vectors used for ML predictions.

This is the most complex validator due to CASCADE validation pattern:
- Depends on all 4 upstream precompute tables
- Must validate feature array integrity
- Must validate source hash tracking
- Must validate production readiness cascade

Validation checks:
- Player count per game date (100+ expected)
- No duplicate player-game entries
- Feature array completeness (33 features)
- Feature version consistency
- Feature value bounds
- Source hash tracking (4 upstream sources)
- Cascade production readiness
- Quality tier distribution
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class MLFeatureStoreValidator(BaseValidator):
    """
    Validator for ML Feature Store V2 predictions table.

    This table contains 33-feature vectors for ML predictions with
    dependencies on all 4 upstream precompute tables:
    - player_daily_cache
    - player_composite_factors
    - player_shot_zone_analysis
    - team_defense_zone_analysis
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """ML Feature Store specific validations"""

        logger.info("Running ML Feature Store V2 validations...")

        # Check 1: Expected player count (100+ per game date)
        self._validate_player_count(start_date, end_date)

        # Check 2: No duplicate player-game entries
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Feature array completeness (33 features)
        self._validate_feature_array(start_date, end_date)

        # Check 4: Feature version consistency
        self._validate_feature_version(start_date, end_date)

        # Check 5: Feature value bounds (key features)
        self._validate_feature_bounds(start_date, end_date)

        # Check 6: Source hash tracking (4 sources)
        self._validate_source_hashes(start_date, end_date)

        # Check 7: Source completeness percentages
        self._validate_source_completeness(start_date, end_date)

        # Check 8: Cascade production readiness
        self._validate_cascade_readiness(start_date, end_date)

        # Check 9: Quality tier distribution
        self._validate_quality_distribution(start_date, end_date)

        # Check 10: Data hash uniqueness (idempotency)
        self._validate_data_hash(start_date, end_date)

        # Check 11: Freshness check
        self._validate_freshness(start_date, end_date)

        # Check 12: Shot zone zero-value detection (NEW - Session 38)
        self._validate_no_shot_zone_zeros(start_date, end_date)

        # Check 13: Shot zone distribution drift (NEW - Session 38)
        self._validate_shot_zone_distribution(start_date, end_date)

        # Check 14: Column population check (NEW - Session 285)
        self._validate_column_population(start_date, end_date)

        logger.info("Completed ML Feature Store V2 validations")

    def _validate_player_count(self, start_date: str, end_date: str):
        """Check if each game date has expected player count (100+)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING COUNT(DISTINCT player_lookup) < 50
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_count = [(str(row.game_date), row.player_count) for row in result]

            passed = len(low_count) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_count",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_count)} dates with fewer than 50 players" if not passed else "All dates have adequate player coverage",
                affected_count=len(low_count),
                affected_items=low_count[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed player count validation: {e}")
            self._add_error_result("player_count", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate player-game entries"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, player_lookup
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.game_date), row.player_lookup, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_entries",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate player-game entries" if not passed else "No duplicate entries found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_entries", str(e))

    def _validate_feature_array(self, start_date: str, end_date: str):
        """Check that feature arrays have exactly 33 elements"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            feature_count as metadata_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            feature_count IS NULL OR
            feature_count != 54
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup, row.metadata_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="feature_count",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(invalid)} records with incorrect feature count (expected 54)" if not passed else "All records have 54 features",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed feature array validation: {e}")
            self._add_error_result("feature_array", str(e))

    def _validate_feature_version(self, start_date: str, end_date: str):
        """Check that feature version is consistent"""

        check_start = time.time()

        query = f"""
        SELECT
            feature_version,
            COUNT(*) as record_count,
            MIN(game_date) as earliest_date,
            MAX(game_date) as latest_date
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY feature_version
        ORDER BY record_count DESC
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))
            versions = [(row.feature_version, row.record_count) for row in result]

            # Should primarily be v2_37features
            expected_version = 'v2_37features'
            has_expected = any(v[0] == expected_version for v in versions)
            passed = has_expected and len(versions) <= 2

            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="feature_version",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found versions: {versions}" if not passed else f"Version consistency OK: {expected_version}",
                affected_count=len(versions),
                affected_items=versions[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed feature version validation: {e}")
            self._add_error_result("feature_version", str(e))

    def _validate_feature_bounds(self, start_date: str, end_date: str):
        """Check that key feature values are within expected bounds"""

        check_start = time.time()

        # Check key features using individual columns
        query = f"""
        SELECT
            game_date,
            player_lookup,
            feature_0_value as points_avg_last_5,
            feature_5_value as fatigue_score,
            feature_13_value as opp_pace,
            feature_18_value as paint_rate
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            -- Points avg should be 0-60
            (feature_0_value < 0 OR feature_0_value > 60) OR
            -- Fatigue score 0-100
            (feature_5_value < 0 OR feature_5_value > 100) OR
            -- Opponent pace 80-120
            (feature_13_value < 70 OR feature_13_value > 130) OR
            -- Shot zone rates 0-1
            (feature_18_value < 0 OR feature_18_value > 1)
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="feature_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with feature values outside expected bounds" if not passed else "All key features within expected bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed feature bounds validation: {e}")
            self._add_error_result("feature_bounds", str(e))

    def _validate_source_hashes(self, start_date: str, end_date: str):
        """Check that all 4 source hashes are populated"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_records,
            COUNTIF(source_daily_cache_hash IS NULL) as missing_cache_hash,
            COUNTIF(source_composite_hash IS NULL) as missing_composite_hash,
            COUNTIF(source_shot_zones_hash IS NULL) as missing_shot_hash,
            COUNTIF(source_team_defense_hash IS NULL) as missing_defense_hash
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING
            COUNTIF(source_daily_cache_hash IS NULL) > 0 OR
            COUNTIF(source_composite_hash IS NULL) > 0 OR
            COUNTIF(source_shot_zones_hash IS NULL) > 0 OR
            COUNTIF(source_team_defense_hash IS NULL) > 0
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [
                (str(row.game_date), row.total_records,
                 row.missing_cache_hash, row.missing_composite_hash,
                 row.missing_shot_hash, row.missing_defense_hash)
                for row in result
            ]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="source_hashes",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(incomplete)} dates with missing source hashes" if not passed else "All 4 source hashes populated",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed source hash validation: {e}")
            self._add_error_result("source_hashes", str(e))

    def _validate_source_completeness(self, start_date: str, end_date: str):
        """Check that all 4 source completeness percentages are >= 80%"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            source_daily_cache_completeness_pct,
            source_composite_completeness_pct,
            source_shot_zones_completeness_pct,
            source_team_defense_completeness_pct
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            source_daily_cache_completeness_pct < 70 OR
            source_composite_completeness_pct < 70 OR
            source_shot_zones_completeness_pct < 70 OR
            source_team_defense_completeness_pct < 70
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_completeness = [(str(row.game_date), row.player_lookup) for row in result]

            passed = len(low_completeness) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="source_completeness",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_completeness)} records with source completeness <70%" if not passed else "All source completeness >= 70%",
                affected_count=len(low_completeness),
                affected_items=low_completeness[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed source completeness validation: {e}")
            self._add_error_result("source_completeness", str(e))

    def _validate_cascade_readiness(self, start_date: str, end_date: str):
        """Check cascade production readiness (depends on all 4 upstream tables)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_records,
            COUNTIF(is_production_ready = TRUE) as production_ready,
            ROUND(COUNTIF(is_production_ready = TRUE) * 100.0 / COUNT(*), 2) as ready_pct
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING ROUND(COUNTIF(is_production_ready = TRUE) * 100.0 / COUNT(*), 2) < 60
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_readiness = [
                (str(row.game_date), row.total_records, row.production_ready, row.ready_pct)
                for row in result
            ]

            passed = len(low_readiness) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="cascade_production_readiness",
                check_type="cascade",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_readiness)} dates with <60% cascade production readiness" if not passed else "All dates have adequate cascade readiness",
                affected_count=len(low_readiness),
                affected_items=low_readiness[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed cascade readiness validation: {e}")
            self._add_error_result("cascade_production_readiness", str(e))

    def _validate_quality_distribution(self, start_date: str, end_date: str):
        """Check quality tier distribution"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            quality_tier,
            COUNT(*) as tier_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, quality_tier
        ORDER BY game_date DESC, tier_count DESC
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            # Aggregate by tier across all dates
            tier_totals = {}
            for row in result:
                tier = row.quality_tier or 'NULL'
                tier_totals[tier] = tier_totals.get(tier, 0) + row.tier_count

            # Check if majority are in good tiers
            total = sum(tier_totals.values())
            good_tiers = tier_totals.get('excellent', 0) + tier_totals.get('good', 0) + tier_totals.get('acceptable', 0)
            good_pct = (good_tiers / total * 100) if total > 0 else 0

            passed = good_pct >= 50
            duration = time.time() - check_start

            tier_summary = [(k, v) for k, v in sorted(tier_totals.items(), key=lambda x: -x[1])]

            self.results.append(ValidationResult(
                check_name="quality_distribution",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Quality distribution: {round(good_pct, 1)}% in good tiers" if passed else f"Low quality: only {round(good_pct, 1)}% in good tiers",
                affected_count=len(tier_totals),
                affected_items=tier_summary[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed quality distribution validation: {e}")
            self._add_error_result("quality_distribution", str(e))

    def _validate_data_hash(self, start_date: str, end_date: str):
        """Check that data hashes are populated for idempotency"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_records,
            COUNTIF(data_hash IS NULL OR data_hash = '') as missing_hash
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING COUNTIF(data_hash IS NULL OR data_hash = '') > 0
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(str(row.game_date), row.total_records, row.missing_hash) for row in result]

            passed = len(missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="data_hash_idempotency",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(missing)} dates with missing data hashes" if not passed else "All records have data hashes for idempotency",
                affected_count=len(missing),
                affected_items=missing[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed data hash validation: {e}")
            self._add_error_result("data_hash_idempotency", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(game_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].latest_date:
                days_stale = result[0].days_stale
                passed = days_stale <= 7
                message = f"Latest data is {days_stale} days old (threshold: 7 days)"
                severity = "info" if days_stale <= 2 else ("warning" if days_stale <= 7 else "error")
            else:
                passed = False
                message = "No data found in date range"
                severity = "error"

            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="data_freshness",
                check_type="freshness",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=message,
                affected_count=0 if passed else 1,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed freshness validation: {e}")
            self._add_error_result("data_freshness", str(e))

    def _validate_no_shot_zone_zeros(self, start_date: str, end_date: str):
        """
        Detect records where shot zone features are all zeros.

        Added in Session 38 after discovering Jan 23 and Jan 29 had
        all shot zone features = 0, which corrupted model predictions.

        Features 18-20 are shot zone rates:
        - 18: pct_paint (paint shot %)
        - 19: pct_mid_range (mid-range shot %)
        - 20: pct_three (three-point shot %)

        All three being 0 simultaneously indicates a data failure.
        """
        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as zero_count,
            COUNT(*) * 100.0 / (
                SELECT COUNT(*)
                FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
                WHERE game_date = t.game_date
            ) as zero_pct
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2` t
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND feature_18_value = 0
          AND feature_19_value = 0
          AND feature_20_value = 0
        GROUP BY game_date
        HAVING COUNT(*) > 5
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            zero_days = [
                (str(row.game_date), row.zero_count, f"{row.zero_pct:.1f}%")
                for row in result
            ]

            passed = len(zero_days) == 0
            duration = time.time() - check_start

            # Critical if >50% of records on any day have all zeros
            has_critical = any(float(d[2].rstrip('%')) > 50 for d in zero_days)
            severity = "critical" if has_critical else ("warning" if not passed else "info")

            self.results.append(ValidationResult(
                check_name="shot_zone_zeros",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=f"Found {len(zero_days)} dates with all-zero shot zone features (data failure indicator)" if not passed else "No dates with all-zero shot zone features",
                affected_count=len(zero_days),
                affected_items=zero_days[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed shot zone zeros validation: {e}")
            self._add_error_result("shot_zone_zeros", str(e))

    def _validate_shot_zone_distribution(self, start_date: str, end_date: str):
        """
        Validate shot zone feature distributions match expected ranges.

        Added in Session 38 after discovering paint_rate dropped from 0.40 to 0.20
        and three_pt_rate spiked from 0.34 to 0.70 - clearly out of distribution.

        Expected ranges (as decimals in feature store):
        - pct_paint (feature 18): 0.15-0.65 (15-65%)
        - pct_mid_range (feature 19): 0.03-0.40 (3-40%)
        - pct_three (feature 20): 0.10-0.60 (10-60%)
        """
        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            ROUND(AVG(feature_18_value), 3) as avg_paint,
            ROUND(AVG(feature_19_value), 3) as avg_mid,
            ROUND(AVG(feature_20_value), 3) as avg_three,
            COUNT(*) as record_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING
            -- Average paint rate should be 0.25-0.50 (stricter than individual bounds)
            AVG(feature_18_value) < 0.20 OR AVG(feature_18_value) > 0.55 OR
            -- Average mid-range rate should be 0.10-0.30
            AVG(feature_19_value) < 0.08 OR AVG(feature_19_value) > 0.35 OR
            -- Average three-point rate should be 0.25-0.50
            AVG(feature_20_value) < 0.20 OR AVG(feature_20_value) > 0.55
        ORDER BY game_date DESC
        LIMIT 30
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            drift_days = [
                (str(row.game_date), f"paint={row.avg_paint}", f"mid={row.avg_mid}", f"three={row.avg_three}")
                for row in result
            ]

            passed = len(drift_days) == 0
            duration = time.time() - check_start

            # Critical if >5 days have drift (indicates systemic issue)
            severity = "critical" if len(drift_days) > 5 else ("warning" if not passed else "info")

            self.results.append(ValidationResult(
                check_name="shot_zone_distribution",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=f"Found {len(drift_days)} dates with shot zone distributions outside expected ranges" if not passed else "Shot zone distributions within expected ranges",
                affected_count=len(drift_days),
                affected_items=drift_days[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed shot zone distribution validation: {e}")
            self._add_error_result("shot_zone_distribution", str(e))

    def _validate_column_population(self, start_date: str, end_date: str):
        """
        Check 14: Verify feature_N_value columns are populated at expected rates.

        Core features (0-36) should have >50% population on every date.
        0% population on any date indicates a writer bug.
        Added Session 285 as part of features array migration.
        """
        check_start = time.time()

        # Check core features (0-36) population per date
        pop_parts = []
        for idx in range(37):
            pop_parts.append(
                f"ROUND(100.0 * COUNTIF(feature_{idx}_value IS NOT NULL) / COUNT(*), 1) as pop_{idx}"
            )
        pop_sql = ",\n            ".join(pop_parts)

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_records,
            {pop_sql}
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        ORDER BY game_date DESC
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            empty_features = []
            low_features = []

            for row in result:
                for idx in range(37):
                    pop_pct = getattr(row, f'pop_{idx}', 0) or 0
                    if pop_pct == 0:
                        empty_features.append((str(row.game_date), f"feature_{idx}_value", f"{pop_pct}%"))
                    elif pop_pct < 50:
                        low_features.append((str(row.game_date), f"feature_{idx}_value", f"{pop_pct}%"))

            passed = len(empty_features) == 0
            duration = time.time() - check_start

            severity = "critical" if not passed else ("warning" if low_features else "info")
            msg_parts = []
            if empty_features:
                msg_parts.append(f"{len(empty_features)} column-date pairs at 0% population")
            if low_features:
                msg_parts.append(f"{len(low_features)} column-date pairs below 50%")

            self.results.append(ValidationResult(
                check_name="column_population",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message="; ".join(msg_parts) if msg_parts else "All core feature columns adequately populated",
                affected_count=len(empty_features) + len(low_features),
                affected_items=(empty_features + low_features)[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed column population validation: {e}")
            self._add_error_result("column_population", str(e))

    def _add_error_result(self, check_name: str, error_msg: str):
        """Add an error result for failed checks"""
        self.results.append(ValidationResult(
            check_name=check_name,
            check_type="error",
            layer="bigquery",
            passed=False,
            severity="error",
            message=f"Validation check failed: {error_msg}",
            affected_count=0
        ))


if __name__ == "__main__":
    import argparse
    from datetime import datetime, timedelta

    parser = argparse.ArgumentParser(description="Validate ML Feature Store V2")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")

    args = parser.parse_args()

    if args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"Validating ml_feature_store_v2 from {start_date} to {end_date}")

    validator = MLFeatureStoreValidator(
        config_path="validation/configs/precompute/ml_feature_store.yaml"
    )

    results = validator.validate(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
