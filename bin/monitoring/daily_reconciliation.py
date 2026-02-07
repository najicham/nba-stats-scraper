#!/usr/bin/env python3
"""
Daily Reconciliation Report - End-to-End Pipeline Health Check

Compares data at each phase boundary to detect gaps and data loss:
1. Schedule → Boxscores: Missing games
2. Boxscores → Analytics: Missing players
3. Analytics → Features: Missing player-date combinations
4. Features → Predictions: Missing predictions

Usage:
    python bin/monitoring/daily_reconciliation.py                    # Today
    python bin/monitoring/daily_reconciliation.py --date 2026-01-24  # Specific date
    python bin/monitoring/daily_reconciliation.py --alert            # Send Slack summary
    python bin/monitoring/daily_reconciliation.py --detailed         # Show per-game details

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery
import requests

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    """Result of a reconciliation check."""
    check_name: str
    source_name: str
    target_name: str
    source_count: int
    target_count: int
    missing_count: int
    missing_items: List[str] = field(default_factory=list)
    coverage_pct: float = 0.0
    status: str = "ok"  # ok, warning, error

    def __post_init__(self):
        if self.source_count > 0:
            self.coverage_pct = (self.target_count / self.source_count) * 100
        if self.missing_count > 0:
            if self.coverage_pct < 80:
                self.status = "error"
            elif self.coverage_pct < 95:
                self.status = "warning"


@dataclass
class DailyReport:
    """Full daily reconciliation report."""
    game_date: str
    generated_at: datetime
    checks: List[ReconciliationResult] = field(default_factory=list)
    overall_status: str = "ok"

    def add_check(self, check: ReconciliationResult):
        self.checks.append(check)
        if check.status == "error":
            self.overall_status = "error"
        elif check.status == "warning" and self.overall_status != "error":
            self.overall_status = "warning"


class DailyReconciliation:
    """Run daily reconciliation checks across the pipeline."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def run_all_checks(self, game_date: str, detailed: bool = False) -> DailyReport:
        """Run all reconciliation checks for a game date."""
        report = DailyReport(
            game_date=game_date,
            generated_at=datetime.now(ET)
        )

        print("\n" + "=" * 70)
        print(f"DAILY RECONCILIATION REPORT: {game_date}")
        print(f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S ET')}")
        print("=" * 70)

        # Check 1: Schedule → Boxscores (missing games)
        check1 = self._check_schedule_vs_boxscores(game_date, detailed)
        report.add_check(check1)

        # Check 2: Boxscores → Analytics (missing players)
        check2 = self._check_boxscores_vs_analytics(game_date, detailed)
        report.add_check(check2)

        # Check 3: Analytics → Features (missing feature rows)
        check3 = self._check_analytics_vs_features(game_date, detailed)
        report.add_check(check3)

        # Check 4: Features → Predictions (missing predictions)
        check4 = self._check_features_vs_predictions(game_date, detailed)
        report.add_check(check4)

        # Check 5: Phase execution timing
        check5 = self._check_phase_execution_timing(game_date)
        report.add_check(check5)

        # Check 6: Feature quality distribution by category
        check6 = self._check_quality_distribution(game_date)
        report.add_check(check6)

        # Check 7: Cache miss rate (Session 147)
        check7 = self._check_cache_miss_rate(game_date)
        report.add_check(check7)

        # Check 8: Post-game reconciliation - played vs cached vs predicted (Session 147)
        check8 = self._check_played_vs_cached(game_date)
        report.add_check(check8)

        # Summary
        self._print_summary(report)

        return report

    def _check_schedule_vs_boxscores(self, game_date: str, detailed: bool) -> ReconciliationResult:
        """Check that all scheduled games have boxscore data."""
        print("\n" + "-" * 50)
        print("CHECK 1: Schedule → Boxscores (Missing Games)")
        print("-" * 50)

        query = f"""
        WITH schedule AS (
            SELECT DISTINCT
                game_id,
                CONCAT(away_team_abbr, '@', home_team_abbr) as matchup,
                game_status
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date = '{game_date}'
        ),
        boxscores AS (
            SELECT DISTINCT game_id
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{game_date}'
        )
        SELECT
            s.game_id,
            s.matchup,
            s.game_status,
            CASE WHEN b.game_id IS NOT NULL THEN 1 ELSE 0 END as has_boxscore
        FROM schedule s
        LEFT JOIN boxscores b ON s.game_id = b.game_id
        ORDER BY s.game_id
        """

        try:
            results = list(self.bq_client.query(query).result())

            scheduled = len(results)
            with_boxscores = sum(1 for r in results if r.has_boxscore)
            missing = [r for r in results if not r.has_boxscore and r.game_status == 'Final']

            print(f"   Scheduled games: {scheduled}")
            print(f"   With boxscores: {with_boxscores}")
            print(f"   Final games missing boxscores: {len(missing)}")

            if detailed and missing:
                print("   Missing games:")
                for r in missing:
                    print(f"      - {r.matchup} ({r.game_id})")

            return ReconciliationResult(
                check_name="schedule_vs_boxscores",
                source_name="Scheduled Final Games",
                target_name="Boxscores",
                source_count=sum(1 for r in results if r.game_status == 'Final'),
                target_count=with_boxscores,
                missing_count=len(missing),
                missing_items=[r.matchup for r in missing]
            )

        except Exception as e:
            logger.error(f"Check 1 failed: {e}")
            return ReconciliationResult(
                check_name="schedule_vs_boxscores",
                source_name="Schedule",
                target_name="Boxscores",
                source_count=0,
                target_count=0,
                missing_count=0,
                status="error"
            )

    def _check_boxscores_vs_analytics(self, game_date: str, detailed: bool) -> ReconciliationResult:
        """Check that all boxscore players have analytics data."""
        print("\n" + "-" * 50)
        print("CHECK 2: Boxscores → Analytics (Missing Players)")
        print("-" * 50)

        query = f"""
        WITH boxscores AS (
            SELECT DISTINCT
                game_id,
                player_lookup,
                player_name
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{game_date}'
              AND min > 0  -- Only players who played
        ),
        analytics AS (
            SELECT DISTINCT
                game_id,
                player_lookup
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = '{game_date}'
        )
        SELECT
            b.game_id,
            b.player_lookup,
            b.player_name,
            CASE WHEN a.player_lookup IS NOT NULL THEN 1 ELSE 0 END as has_analytics
        FROM boxscores b
        LEFT JOIN analytics a ON b.game_id = a.game_id AND b.player_lookup = a.player_lookup
        """

        try:
            results = list(self.bq_client.query(query).result())

            boxscore_players = len(results)
            with_analytics = sum(1 for r in results if r.has_analytics)
            missing = [r for r in results if not r.has_analytics]

            print(f"   Boxscore players (with minutes): {boxscore_players}")
            print(f"   With analytics: {with_analytics}")
            print(f"   Missing analytics: {len(missing)}")

            if detailed and missing[:10]:
                print("   Missing players (first 10):")
                for r in missing[:10]:
                    print(f"      - {r.player_name} ({r.player_lookup})")

            return ReconciliationResult(
                check_name="boxscores_vs_analytics",
                source_name="Boxscore Players",
                target_name="Analytics",
                source_count=boxscore_players,
                target_count=with_analytics,
                missing_count=len(missing),
                missing_items=[r.player_name for r in missing[:20]]
            )

        except Exception as e:
            logger.error(f"Check 2 failed: {e}")
            return ReconciliationResult(
                check_name="boxscores_vs_analytics",
                source_name="Boxscores",
                target_name="Analytics",
                source_count=0,
                target_count=0,
                missing_count=0,
                status="error"
            )

    def _check_analytics_vs_features(self, game_date: str, detailed: bool) -> ReconciliationResult:
        """Check that analytics players have feature store data (quality-ready)."""
        print("\n" + "-" * 50)
        print("CHECK 3: Analytics → Features (Missing/Low-Quality Feature Rows)")
        print("-" * 50)

        query = f"""
        WITH analytics AS (
            SELECT DISTINCT
                player_lookup,
                game_id
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = '{game_date}'
        ),
        features AS (
            SELECT DISTINCT
                player_lookup,
                game_id,
                is_quality_ready,
                quality_alert_level
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = '{game_date}'
        )
        SELECT
            a.player_lookup,
            a.game_id,
            CASE WHEN f.player_lookup IS NOT NULL THEN 1 ELSE 0 END as has_features,
            IFNULL(f.is_quality_ready, FALSE) as is_quality_ready,
            f.quality_alert_level
        FROM analytics a
        LEFT JOIN features f ON a.game_id = f.game_id AND a.player_lookup = f.player_lookup
        """

        try:
            results = list(self.bq_client.query(query).result())

            analytics_players = len(results)
            with_features = sum(1 for r in results if r.has_features)
            quality_ready = sum(1 for r in results if r.is_quality_ready)
            missing = [r for r in results if not r.has_features]
            not_ready = [r for r in results if r.has_features and not r.is_quality_ready]

            print(f"   Analytics player-games: {analytics_players}")
            print(f"   With features: {with_features}")
            print(f"   Quality-ready (is_quality_ready=TRUE): {quality_ready}")
            print(f"   Missing features: {len(missing)}")
            if not_ready:
                print(f"   Features present but NOT quality-ready: {len(not_ready)}")

            return ReconciliationResult(
                check_name="analytics_vs_features",
                source_name="Analytics",
                target_name="Quality-Ready Features",
                source_count=analytics_players,
                target_count=quality_ready,
                missing_count=analytics_players - quality_ready,
                missing_items=[r.player_lookup for r in missing[:20]]
            )

        except Exception as e:
            logger.error(f"Check 3 failed: {e}")
            return ReconciliationResult(
                check_name="analytics_vs_features",
                source_name="Analytics",
                target_name="Quality-Ready Features",
                source_count=0,
                target_count=0,
                missing_count=0,
                status="error"
            )

    def _check_features_vs_predictions(self, game_date: str, detailed: bool) -> ReconciliationResult:
        """Check that feature store players have predictions, with quality breakdown for skipped."""
        print("\n" + "-" * 50)
        print("CHECK 4: Features → Predictions (Missing Predictions)")
        print("-" * 50)

        query = f"""
        WITH features AS (
            SELECT DISTINCT
                player_lookup,
                game_id,
                quality_alert_level
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = '{game_date}'
        ),
        predictions AS (
            SELECT DISTINCT
                player_lookup,
                game_id
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = '{game_date}'
              AND system_id = 'catboost_v8'
              AND is_active = TRUE
        )
        SELECT
            f.player_lookup,
            f.game_id,
            f.quality_alert_level,
            CASE WHEN p.player_lookup IS NOT NULL THEN 1 ELSE 0 END as has_predictions
        FROM features f
        LEFT JOIN predictions p ON f.game_id = p.game_id AND f.player_lookup = p.player_lookup
        """

        try:
            results = list(self.bq_client.query(query).result())

            feature_players = len(results)
            with_predictions = sum(1 for r in results if r.has_predictions)
            missing = [r for r in results if not r.has_predictions]

            # Break down skipped predictions by quality alert level
            missing_by_alert = {}
            for r in missing:
                level = r.quality_alert_level or 'unknown'
                missing_by_alert[level] = missing_by_alert.get(level, 0) + 1

            print(f"   Feature store player-games: {feature_players}")
            print(f"   With predictions: {with_predictions}")
            print(f"   Missing predictions: {len(missing)}")
            if missing_by_alert:
                print(f"   Skipped by quality_alert_level:")
                for level in ['red', 'yellow', 'green', 'unknown']:
                    count = missing_by_alert.get(level, 0)
                    if count > 0:
                        print(f"      {level}: {count}")

            return ReconciliationResult(
                check_name="features_vs_predictions",
                source_name="Features",
                target_name="Predictions",
                source_count=feature_players,
                target_count=with_predictions,
                missing_count=len(missing),
                missing_items=[r.player_lookup for r in missing[:20]]
            )

        except Exception as e:
            logger.error(f"Check 4 failed: {e}")
            return ReconciliationResult(
                check_name="features_vs_predictions",
                source_name="Features",
                target_name="Predictions",
                source_count=0,
                target_count=0,
                missing_count=0,
                status="error"
            )

    def _check_phase_execution_timing(self, game_date: str) -> ReconciliationResult:
        """Check phase execution timing for gaps."""
        print("\n" + "-" * 50)
        print("CHECK 5: Phase Execution Timing")
        print("-" * 50)

        query = f"""
        SELECT
            phase_name,
            MIN(execution_timestamp) as first_execution,
            MAX(execution_timestamp) as last_execution,
            COUNT(*) as execution_count,
            SUM(duration_seconds) as total_duration,
            COUNT(CASE WHEN status = 'complete' THEN 1 END) as successful
        FROM `{self.project_id}.nba_orchestration.phase_execution_log`
        WHERE game_date = '{game_date}'
        GROUP BY phase_name
        ORDER BY first_execution
        """

        try:
            results = list(self.bq_client.query(query).result())

            phases_executed = len(results)
            expected_phases = 4  # phase2_to_phase3, phase3_to_phase4, phase4_to_phase5, phase5_to_phase6

            for r in results:
                print(f"   {r.phase_name}: {r.successful}/{r.execution_count} successful, "
                      f"first={r.first_execution}, duration={r.total_duration:.1f}s")

            if phases_executed == 0:
                print("   ⚠️ No phase executions logged!")

            return ReconciliationResult(
                check_name="phase_execution_timing",
                source_name="Expected Phases",
                target_name="Executed Phases",
                source_count=expected_phases,
                target_count=phases_executed,
                missing_count=expected_phases - phases_executed,
                missing_items=[]
            )

        except Exception as e:
            logger.error(f"Check 5 failed: {e}")
            return ReconciliationResult(
                check_name="phase_execution_timing",
                source_name="Phases",
                target_name="Executions",
                source_count=4,
                target_count=0,
                missing_count=4,
                status="error"
            )

    def _check_quality_distribution(self, game_date: str) -> ReconciliationResult:
        """Check feature quality distribution by category for the day."""
        print("\n" + "-" * 50)
        print("CHECK 6: Feature Quality Distribution by Category")
        print("-" * 50)

        query = f"""
        SELECT
            COUNT(*) as total,
            ROUND(AVG(matchup_quality_pct), 1) as avg_matchup,
            ROUND(AVG(player_history_quality_pct), 1) as avg_player_history,
            ROUND(AVG(game_context_quality_pct), 1) as avg_game_context,
            COUNTIF(quality_alert_level = 'green') as green_count,
            COUNTIF(quality_alert_level = 'yellow') as yellow_count,
            COUNTIF(quality_alert_level = 'red') as red_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{game_date}'
        """

        try:
            results = list(self.bq_client.query(query).result())

            if not results or results[0].total == 0:
                print("   No feature store data for this date.")
                return ReconciliationResult(
                    check_name="quality_distribution",
                    source_name="Feature Store",
                    target_name="Quality Categories",
                    source_count=0,
                    target_count=0,
                    missing_count=0,
                    status="warning"
                )

            row = results[0]
            total = row.total
            avg_matchup = row.avg_matchup or 0.0
            avg_player_history = row.avg_player_history or 0.0
            avg_game_context = row.avg_game_context or 0.0
            green = row.green_count or 0
            yellow = row.yellow_count or 0
            red = row.red_count or 0

            print(f"   Total feature rows: {total}")
            print(f"   Category averages:")
            print(f"      Matchup Quality:        {avg_matchup:.1f}%")
            print(f"      Player History Quality: {avg_player_history:.1f}%")
            print(f"      Game Context Quality:   {avg_game_context:.1f}%")
            print(f"   Alert level distribution:")
            print(f"      Green:  {green} ({green/total*100:.1f}%)")
            print(f"      Yellow: {yellow} ({yellow/total*100:.1f}%)")
            print(f"      Red:    {red} ({red/total*100:.1f}%)")

            # Flag if matchup quality is low (Session 132 recurrence indicator)
            if avg_matchup < 50:
                print(f"   WARNING: Low matchup quality ({avg_matchup:.1f}%) - check PlayerCompositeFactorsProcessor")

            # Determine status based on red alerts and category quality
            if red > total * 0.1 or avg_matchup < 50:
                status = "error"
            elif red > 0 or avg_matchup < 70:
                status = "warning"
            else:
                status = "ok"

            return ReconciliationResult(
                check_name="quality_distribution",
                source_name="Feature Store",
                target_name="Green Quality",
                source_count=total,
                target_count=green,
                missing_count=red,
                status=status
            )

        except Exception as e:
            logger.error(f"Check 6 failed: {e}")
            return ReconciliationResult(
                check_name="quality_distribution",
                source_name="Feature Store",
                target_name="Quality Categories",
                source_count=0,
                target_count=0,
                missing_count=0,
                status="error"
            )

    def _check_cache_miss_rate(self, game_date: str) -> ReconciliationResult:
        """Check cache miss rate in the ML feature store (Session 147)."""
        print("\n" + "-" * 50)
        print("CHECK 7: Cache Miss Rate (Session 147)")
        print("-" * 50)

        query = f"""
        SELECT
            COUNTIF(cache_miss_fallback_used) as cache_misses,
            COUNT(*) as total,
            ROUND(COUNTIF(cache_miss_fallback_used) / NULLIF(COUNT(*), 0) * 100, 1) as miss_rate_pct
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{game_date}'
        """

        try:
            results = list(self.bq_client.query(query).result())

            if not results or results[0].total == 0:
                print("   No feature store data for this date.")
                return ReconciliationResult(
                    check_name="cache_miss_rate",
                    source_name="Feature Store",
                    target_name="Cache Hits",
                    source_count=0, target_count=0, missing_count=0,
                    status="warning"
                )

            row = results[0]
            total = row.total
            misses = row.cache_misses or 0
            hits = total - misses
            miss_rate = row.miss_rate_pct or 0.0

            print(f"   Total players: {total}")
            print(f"   Cache hits: {hits}")
            print(f"   Cache misses (fallback used): {misses}")
            print(f"   Miss rate: {miss_rate}%")

            # For daily predictions, >0% is a warning; >5% is an error
            if miss_rate > 5:
                status = "error"
                print(f"   ERROR: High cache miss rate - check PlayerDailyCacheProcessor")
            elif miss_rate > 0:
                status = "warning"
                print(f"   WARNING: Non-zero cache miss rate - investigate player list mismatch")
            else:
                status = "ok"

            return ReconciliationResult(
                check_name="cache_miss_rate",
                source_name="Feature Store Players",
                target_name="Cache Hits",
                source_count=total,
                target_count=hits,
                missing_count=misses,
                status=status
            )

        except Exception as e:
            logger.error(f"Check 7 failed: {e}")
            return ReconciliationResult(
                check_name="cache_miss_rate",
                source_name="Feature Store",
                target_name="Cache Hits",
                source_count=0, target_count=0, missing_count=0,
                status="error"
            )

    def _check_played_vs_cached(self, game_date: str) -> ReconciliationResult:
        """Post-game reconciliation: who played vs who was cached/predicted (Session 147)."""
        print("\n" + "-" * 50)
        print("CHECK 8: Post-Game Reconciliation - Played vs Cached/Predicted")
        print("-" * 50)

        query = f"""
        WITH played AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = '{game_date}' AND is_dnp = FALSE
        ),
        cached AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_precompute.player_daily_cache`
            WHERE cache_date = '{game_date}'
        ),
        predicted AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = '{game_date}' AND is_active = TRUE
        )
        SELECT
            (SELECT COUNT(*) FROM played) as players_played,
            (SELECT COUNT(*) FROM cached) as players_cached,
            (SELECT COUNT(*) FROM predicted) as players_predicted,
            (SELECT COUNT(*) FROM played p
             LEFT JOIN cached c ON p.player_lookup = c.player_lookup
             WHERE c.player_lookup IS NULL) as played_not_cached,
            (SELECT COUNT(*) FROM played p
             LEFT JOIN predicted pr ON p.player_lookup = pr.player_lookup
             WHERE pr.player_lookup IS NULL) as played_not_predicted
        """

        try:
            results = list(self.bq_client.query(query).result())

            if not results:
                return ReconciliationResult(
                    check_name="played_vs_cached",
                    source_name="Players Played",
                    target_name="Players Cached",
                    source_count=0, target_count=0, missing_count=0,
                    status="warning"
                )

            row = results[0]
            played = row.players_played or 0
            cached = row.players_cached or 0
            predicted = row.players_predicted or 0
            not_cached = row.played_not_cached or 0
            not_predicted = row.played_not_predicted or 0

            print(f"   Players who played: {played}")
            print(f"   Players cached: {cached}")
            print(f"   Players predicted: {predicted}")
            print(f"   Played but NOT cached: {not_cached}")
            print(f"   Played but NOT predicted: {not_predicted}")

            if played == 0:
                print("   No boxscores yet (games may not have finished)")
                return ReconciliationResult(
                    check_name="played_vs_cached",
                    source_name="Players Played",
                    target_name="Players Cached",
                    source_count=0, target_count=0, missing_count=0,
                    status="ok"
                )

            # Cache coverage: played but not cached indicates upcoming_player_game_context gaps
            cache_coverage_pct = ((played - not_cached) / played * 100) if played > 0 else 100
            print(f"   Cache coverage: {cache_coverage_pct:.1f}%")

            if not_cached > 10:
                status = "error"
            elif not_cached > 3:
                status = "warning"
            else:
                status = "ok"

            return ReconciliationResult(
                check_name="played_vs_cached",
                source_name="Players Played",
                target_name="Players Cached",
                source_count=played,
                target_count=played - not_cached,
                missing_count=not_cached,
                status=status
            )

        except Exception as e:
            logger.error(f"Check 8 failed: {e}")
            return ReconciliationResult(
                check_name="played_vs_cached",
                source_name="Players Played",
                target_name="Players Cached",
                source_count=0, target_count=0, missing_count=0,
                status="error"
            )

    def _print_summary(self, report: DailyReport):
        """Print summary of reconciliation report."""
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)

        status_icon = {
            "ok": "✅",
            "warning": "⚠️",
            "error": "❌"
        }

        for check in report.checks:
            icon = status_icon[check.status]
            print(f"   {icon} {check.check_name}: {check.target_count}/{check.source_count} "
                  f"({check.coverage_pct:.1f}%) - {check.missing_count} missing")

        print()
        print(f"   Overall Status: {status_icon[report.overall_status]} {report.overall_status.upper()}")

        if report.overall_status != "ok":
            print("\n   ⚠️ ACTION REQUIRED - Review missing items above")

    def send_slack_report(self, report: DailyReport) -> bool:
        """Send reconciliation report to Slack."""
        if not SLACK_WEBHOOK_URL:
            print("No SLACK_WEBHOOK_URL configured")
            return False

        status_emoji = {
            "ok": ":white_check_mark:",
            "warning": ":warning:",
            "error": ":x:"
        }

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📊 Daily Reconciliation: {report.game_date}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Overall Status:* {status_emoji[report.overall_status]} {report.overall_status.upper()}"
                }
            },
            {"type": "divider"}
        ]

        # Add check results
        for check in report.checks:
            emoji = status_emoji[check.status]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *{check.source_name} → {check.target_name}*\n"
                           f"{check.target_count}/{check.source_count} ({check.coverage_pct:.1f}%) | "
                           f"{check.missing_count} missing"
                }
            })

        # Add context
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M ET')}"
            }]
        })

        try:
            response = requests.post(
                SLACK_WEBHOOK_URL,
                json={"blocks": blocks},
                timeout=10
            )
            if response.status_code == 200:
                print("Slack report sent successfully")
                return True
            else:
                print(f"Slack report failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"Error sending Slack report: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Daily pipeline reconciliation report")
    parser.add_argument('--date', type=str, help='Game date (YYYY-MM-DD), defaults to today')
    parser.add_argument('--alert', action='store_true', help='Send Slack summary')
    parser.add_argument('--detailed', action='store_true', help='Show per-game details')
    args = parser.parse_args()

    # Default to today ET
    if args.date:
        game_date = args.date
    else:
        game_date = datetime.now(ET).strftime("%Y-%m-%d")

    reconciliation = DailyReconciliation()
    report = reconciliation.run_all_checks(game_date, detailed=args.detailed)

    if args.alert:
        reconciliation.send_slack_report(report)

    # Exit with appropriate code
    if report.overall_status == "error":
        sys.exit(2)
    elif report.overall_status == "warning":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
