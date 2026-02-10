# predictions/coordinator/quality_alerts.py
"""
Quality Alerts for Prediction System (Session 95, updated Session 152)

Sends alerts when prediction quality issues are detected:
- LOW_QUALITY_FEATURES: >20% of players have quality < 85%
- PHASE4_DATA_MISSING: Feature store has 0 rows for today
- FORCED_PREDICTIONS: >10 players forced at LAST_CALL
- LOW_COVERAGE: <80% of expected players have predictions
- VEGAS_COVERAGE_DEGRADED: >50% of players have no vegas line source
- LINE_CHECK_COMPLETED: Hourly line check results (Session 152)
- MORNING_SUMMARY: Daily morning prediction/line coverage summary (Session 152)
- RECOMMENDATION_SKEW: >85% of recs are same direction (Session 171)
- VEGAS_SOURCE_RECOVERY_HIGH: >30% of predictions used recovery_median (Session 171)
- RECOMMENDATION_DIRECTION_MISMATCH: pred > line but rec = UNDER or vice versa (Session 176)
"""

import logging
from datetime import date
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QualityAlert:
    """Quality alert details."""
    alert_type: str
    severity: str  # INFO, WARNING, CRITICAL
    message: str
    details: Dict


def check_and_send_quality_alerts(
    game_date: date,
    mode: str,
    total_players: int,
    players_to_predict: int,
    players_skipped_existing: int,
    players_skipped_low_quality: int,
    players_forced: int,
    avg_quality_score: float,
    quality_distribution: Dict[str, int]
) -> list:
    """
    Check for quality issues and send alerts.

    Args:
        game_date: Date predictions are for
        mode: Prediction mode (FIRST, RETRY, etc.)
        total_players: Total players in batch
        players_to_predict: Players that will get predictions
        players_skipped_existing: Players skipped (already have prediction)
        players_skipped_low_quality: Players skipped due to low quality
        players_forced: Players forced despite low quality
        avg_quality_score: Average feature quality score
        quality_distribution: Dict with high/medium/low counts

    Returns:
        List of QualityAlert objects that were triggered
    """
    alerts = []

    # Calculate percentages
    new_players = total_players - players_skipped_existing
    if new_players > 0:
        low_quality_pct = (players_skipped_low_quality / new_players) * 100
        forced_pct = (players_forced / new_players) * 100
    else:
        low_quality_pct = 0
        forced_pct = 0

    # Alert 1: LOW_QUALITY_FEATURES - >20% of players have quality < 85%
    high_quality_count = quality_distribution.get('high_85plus', 0)
    total_with_quality = sum(quality_distribution.values())
    if total_with_quality > 0:
        high_quality_pct = (high_quality_count / total_with_quality) * 100
        if high_quality_pct < 80:  # Less than 80% high quality = >20% low quality
            alert = QualityAlert(
                alert_type="LOW_QUALITY_FEATURES",
                severity="WARNING",
                message=f"Only {high_quality_pct:.1f}% of players have high-quality features (85%+)",
                details={
                    'game_date': str(game_date),
                    'mode': mode,
                    'high_quality_pct': high_quality_pct,
                    'avg_quality': avg_quality_score,
                    'distribution': quality_distribution,
                }
            )
            alerts.append(alert)
            _send_slack_alert(alert)

    # Alert 2: PHASE4_DATA_MISSING - No feature data available
    if total_with_quality == 0 and total_players > 0:
        alert = QualityAlert(
            alert_type="PHASE4_DATA_MISSING",
            severity="CRITICAL",
            message=f"No feature data available for {game_date}. Phase 4 may not have run.",
            details={
                'game_date': str(game_date),
                'mode': mode,
                'total_players': total_players,
            }
        )
        alerts.append(alert)
        _send_slack_alert(alert)

    # Alert 3: FORCED_PREDICTIONS - >10 players forced at LAST_CALL
    if players_forced > 10:
        alert = QualityAlert(
            alert_type="FORCED_PREDICTIONS",
            severity="WARNING",
            message=f"{players_forced} players forced with low-quality features at {mode}",
            details={
                'game_date': str(game_date),
                'mode': mode,
                'players_forced': players_forced,
                'forced_pct': forced_pct,
            }
        )
        alerts.append(alert)
        _send_slack_alert(alert)

    # Alert 4: LOW_COVERAGE - <80% coverage after FINAL_RETRY
    if mode in ('FINAL_RETRY', 'LAST_CALL'):
        coverage_pct = (players_to_predict + players_skipped_existing) / total_players * 100 if total_players > 0 else 0
        if coverage_pct < 80 and mode == 'FINAL_RETRY':
            alert = QualityAlert(
                alert_type="LOW_COVERAGE",
                severity="WARNING",
                message=f"Only {coverage_pct:.1f}% prediction coverage at {mode}",
                details={
                    'game_date': str(game_date),
                    'mode': mode,
                    'coverage_pct': coverage_pct,
                    'players_with_predictions': players_to_predict + players_skipped_existing,
                    'total_players': total_players,
                }
            )
            alerts.append(alert)
            _send_slack_alert(alert)

    # Log all alerts (structured logging)
    for alert in alerts:
        log_level = logging.WARNING if alert.severity == 'WARNING' else logging.ERROR
        logger.log(
            log_level,
            f"QUALITY_ALERT: {alert.alert_type} - {alert.message}",
            extra={
                'alert_type': alert.alert_type,
                'severity': alert.severity,
                'details': alert.details,
            }
        )

    return alerts


def _send_slack_alert(alert: QualityAlert):
    """
    Send alert to Slack.

    Args:
        alert: QualityAlert to send
    """
    try:
        from shared.utils.slack_alerts import send_slack_alert

        # Format message for Slack
        emoji = ":warning:" if alert.severity == "WARNING" else ":rotating_light:"
        channel = "#nba-alerts"

        # Build details string
        details_lines = []
        for key, value in alert.details.items():
            if isinstance(value, dict):
                details_lines.append(f"  {key}: {value}")
            else:
                details_lines.append(f"  {key}: {value}")
        details_str = "\n".join(details_lines)

        message = f"""
{emoji} *{alert.alert_type}* ({alert.severity})

{alert.message}

*Details:*
```
{details_str}
```
"""

        send_slack_alert(
            message=message,
            channel=channel,
            alert_type=alert.alert_type,
        )
        logger.info(f"Sent Slack alert: {alert.alert_type}")

    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")


def send_predictions_skipped_alert(
    game_date: date,
    mode: str,
    blocked_results: list,
    missing_processors: list,
    heal_attempted: bool = False,
    heal_success: bool = False,
):
    """
    Send clear PREDICTIONS_SKIPPED alert with full details (Session 139).

    Called when players are hard-blocked by the quality gate. Provides
    actionable information: which players, why, and what to do next.

    Args:
        game_date: Date predictions are for
        mode: Prediction mode (FIRST, RETRY, etc.)
        blocked_results: List of QualityGateResult for blocked players
        missing_processors: List of diagnosed missing processors
        heal_attempted: Whether self-healing was attempted
        heal_success: Whether self-healing succeeded
    """
    if not blocked_results:
        return

    # Build player details
    player_lines = []
    for r in blocked_results[:20]:  # Cap at 20 for readability
        score_str = f"{r.feature_quality_score:.0f}%" if r.feature_quality_score is not None else "N/A"
        player_lines.append(
            f"  {r.player_lookup}: quality={score_str}, reason={r.reason}"
            + (f", missing={r.missing_processor}" if r.missing_processor else "")
        )

    remaining = len(blocked_results) - 20
    if remaining > 0:
        player_lines.append(f"  ... and {remaining} more")

    players_str = "\n".join(player_lines)

    # Heal status
    if heal_attempted:
        heal_str = "ATTEMPTED - " + ("SUCCESS" if heal_success else "FAILED")
    else:
        heal_str = "NOT ATTEMPTED"

    # Root cause
    if missing_processors:
        root_cause = ", ".join(missing_processors) + " didn't run"
    else:
        root_cause = "Unknown - check Phase 4 processor logs"

    message = f""":no_entry: *PREDICTIONS SKIPPED - ACTION REQUIRED*

*{len(blocked_results)} players* skipped for {game_date} ({mode})
Root cause: {root_cause}
Self-heal: {heal_str}

*Skipped players:*
```
{players_str}
```

*Next steps:*
1. Investigate why processor failed
2. Backfill tomorrow: `POST /start {{"game_date":"{game_date}","prediction_run_mode":"BACKFILL"}}`
"""

    alert = QualityAlert(
        alert_type="PREDICTIONS_SKIPPED",
        severity="CRITICAL",
        message=f"{len(blocked_results)} players skipped for {game_date} ({mode})",
        details={
            'game_date': str(game_date),
            'mode': mode,
            'players_blocked': len(blocked_results),
            'missing_processors': missing_processors,
            'heal_attempted': heal_attempted,
            'heal_success': heal_success,
        }
    )

    # Log the alert
    logger.error(
        f"QUALITY_ALERT: PREDICTIONS_SKIPPED - {len(blocked_results)} players for {game_date}",
        extra={
            'alert_type': 'PREDICTIONS_SKIPPED',
            'severity': 'CRITICAL',
            'details': alert.details,
        }
    )

    # Send to Slack
    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="PREDICTIONS_SKIPPED",
        )
        logger.info("Sent PREDICTIONS_SKIPPED Slack alert")
    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send PREDICTIONS_SKIPPED Slack alert: {e}")


def log_quality_metrics(
    game_date: date,
    mode: str,
    summary_dict: Dict
):
    """
    Log quality metrics in structured format for monitoring dashboards.

    Args:
        game_date: Date predictions are for
        mode: Prediction mode
        summary_dict: Summary dictionary from QualityGateSummary
    """
    logger.info(
        "PREDICTION_QUALITY_METRICS",
        extra={
            'metric_type': 'prediction_quality',
            'game_date': str(game_date),
            'mode': mode,
            'total_players': summary_dict.get('total_players', 0),
            'players_to_predict': summary_dict.get('players_to_predict', 0),
            'players_skipped_existing': summary_dict.get('players_skipped_existing', 0),
            'players_skipped_low_quality': summary_dict.get('players_skipped_low_quality', 0),
            'players_forced': summary_dict.get('players_forced', 0),
            'avg_quality_score': summary_dict.get('avg_quality_score', 0),
            'high_quality_count': summary_dict.get('quality_distribution', {}).get('high_85plus', 0),
            'medium_quality_count': summary_dict.get('quality_distribution', {}).get('medium_80_85', 0),
            'low_quality_count': summary_dict.get('quality_distribution', {}).get('low_below_80', 0),
        }
    )


def send_vegas_coverage_alert(
    game_date: date,
    run_mode: str,
    coverage: Dict
):
    """
    Session 152: Alert when vegas line coverage is degraded at prediction time.

    Fires when >50% of players in the feature store have no vegas line source,
    indicating a scraper failure rather than normal bench player gaps.

    Args:
        game_date: Date predictions are for
        run_mode: Prediction run mode (EARLY, OVERNIGHT, etc.)
        coverage: Dict with odds_api_only, bettingpros_only, both_sources, no_source, total, coverage_pct
    """
    total = coverage.get('total', 0)
    no_source = coverage.get('no_source', 0)
    odds_api_only = coverage.get('odds_api_only', 0)
    bettingpros_only = coverage.get('bettingpros_only', 0)
    both_sources = coverage.get('both_sources', 0)
    coverage_pct = coverage.get('coverage_pct', 0)

    message = f""":warning: *VEGAS LINE COVERAGE DEGRADED*

*{game_date}* ({run_mode}) — {coverage_pct:.0f}% coverage

*Source breakdown:*
```
Both sources:      {both_sources} players
Odds API only:     {odds_api_only} players
BettingPros only:  {bettingpros_only} players
No source:         {no_source} players ({100 * no_source / total:.0f}% of {total})
```

*Impact:* Players without lines use default vegas features (25-28).
*Next steps:* Check scraper health. Lines may arrive later and trigger re-prediction.
"""

    alert = QualityAlert(
        alert_type="VEGAS_COVERAGE_DEGRADED",
        severity="WARNING",
        message=f"Vegas coverage {coverage_pct:.0f}% for {game_date} ({run_mode})",
        details=coverage
    )

    logger.warning(
        f"QUALITY_ALERT: VEGAS_COVERAGE_DEGRADED - {coverage_pct:.0f}% for {game_date}",
        extra={
            'alert_type': 'VEGAS_COVERAGE_DEGRADED',
            'severity': 'WARNING',
            'details': alert.details,
        }
    )

    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="VEGAS_COVERAGE_DEGRADED",
        )
        logger.info("Sent VEGAS_COVERAGE_DEGRADED Slack alert")
    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send VEGAS_COVERAGE_DEGRADED Slack alert: {e}")


def send_pvl_bias_alert(
    game_date: date,
    run_mode: str,
    avg_pvl: float,
    prediction_count: int,
):
    """
    Session 170: Alert when batch avg predicted-vs-line (PVL) is outside ±2.0.

    Would have caught the Session 169 UNDER bias crisis immediately (avg_pvl was -3.84).
    Fires after consolidation for any prediction run.

    Args:
        game_date: Date predictions are for
        run_mode: Prediction run mode (FIRST, BACKFILL, etc.)
        avg_pvl: Average (predicted_points - current_points_line) for the batch
        prediction_count: Number of predictions in the batch
    """
    severity = "CRITICAL" if abs(avg_pvl) > 3.0 else "WARNING"
    direction = "UNDER" if avg_pvl < 0 else "OVER"
    emoji = ":rotating_light:" if severity == "CRITICAL" else ":warning:"

    message = f"""{emoji} *PVL BIAS DETECTED* ({severity})

*{game_date}* ({run_mode}) — avg_pvl = *{avg_pvl:+.2f}*

Model is predicting {abs(avg_pvl):.1f} points *{direction}* Vegas on average.
Threshold: ±2.0 (WARNING), ±3.0 (CRITICAL)
Predictions in batch: {prediction_count}

*Impact:* Systematic {direction} bias causes lopsided recommendations.
*Next steps:* Check Vegas line coverage, feature store quality, model inputs.
"""

    alert = QualityAlert(
        alert_type="PVL_BIAS_DETECTED",
        severity=severity,
        message=f"avg_pvl={avg_pvl:+.2f} for {game_date} ({run_mode})",
        details={
            'game_date': str(game_date),
            'run_mode': run_mode,
            'avg_pvl': avg_pvl,
            'direction': direction,
            'prediction_count': prediction_count,
        }
    )

    log_level = logging.ERROR if severity == "CRITICAL" else logging.WARNING
    logger.log(
        log_level,
        f"QUALITY_ALERT: PVL_BIAS_DETECTED - avg_pvl={avg_pvl:+.2f} for {game_date}",
        extra={
            'alert_type': 'PVL_BIAS_DETECTED',
            'severity': severity,
            'details': alert.details,
        }
    )

    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="PVL_BIAS_DETECTED",
        )
        logger.info("Sent PVL_BIAS_DETECTED Slack alert")
    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send PVL_BIAS_DETECTED Slack alert: {e}")


def send_line_check_alert(
    game_date: date,
    new_line_players: List[str],
    stale_line_players: List[str],
    batch_id: Optional[str],
    dry_run: bool = False,
):
    """
    Session 152: Send Slack alert after hourly line check completes.

    Args:
        game_date: Date checked
        new_line_players: Players with new lines available
        stale_line_players: Players with moved lines
        batch_id: Prediction batch ID (None if dry_run or no changes)
        dry_run: Whether this was a dry run
    """
    total = len(new_line_players) + len(stale_line_players)
    # Deduplicate for display
    all_players = sorted(set(new_line_players + stale_line_players))

    if dry_run:
        mode_str = " (DRY RUN)"
    else:
        mode_str = ""

    # Only show first 15 player names
    player_list = "\n".join(f"  {p}" for p in all_players[:15])
    if len(all_players) > 15:
        player_list += f"\n  ... and {len(all_players) - 15} more"

    message = f""":mag: *Line Check{mode_str} — {game_date}*

Re-predicted *{len(all_players)} players* ({len(new_line_players)} new lines, {len(stale_line_players)} line moves)
{f"Batch: `{batch_id}`" if batch_id else ""}

```
{player_list}
```
"""

    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="LINE_CHECK_COMPLETED",
        )
        logger.info(f"Sent LINE_CHECK_COMPLETED Slack alert ({len(all_players)} players)")
    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send LINE_CHECK_COMPLETED Slack alert: {e}")


def send_morning_line_summary(
    game_date: date,
    prediction_stats: Dict,
    line_source_stats: Dict,
    subset_stats: Dict,
    feature_stats: Dict,
):
    """
    Session 152: Send morning Slack summary with prediction and line coverage stats.

    Args:
        game_date: Date being summarized
        prediction_stats: Dict with total, with_lines, without_lines, actionable
        line_source_stats: Dict with odds_api, bettingpros, both, none counts
        subset_stats: Dict mapping subset_name to pick_count
        feature_stats: Dict with avg_quality, blocked_count
    """
    total = prediction_stats.get('total', 0)
    with_lines = prediction_stats.get('with_lines', 0)
    without_lines = prediction_stats.get('without_lines', 0)
    actionable = prediction_stats.get('actionable', 0)
    medium_edge = prediction_stats.get('medium_edge', 0)
    high_edge = prediction_stats.get('high_edge', 0)

    oa = line_source_stats.get('odds_api', 0)
    bp = line_source_stats.get('bettingpros', 0)
    both = line_source_stats.get('both', 0)
    none_src = line_source_stats.get('none', 0)

    avg_quality = feature_stats.get('avg_quality', 0)
    blocked = feature_stats.get('blocked_count', 0)

    # Build subset summary line
    subset_parts = []
    for name, count in sorted(subset_stats.items()):
        subset_parts.append(f"{name}={count}")
    subset_line = " | ".join(subset_parts) if subset_parts else "No subsets"

    message = f""":sunrise: *Morning Summary — {game_date}*

*Predictions:* {total} active ({with_lines} with lines, {without_lines} without)
*Edge:* {medium_edge} medium (3+) | {high_edge} high (5+) | {actionable} actionable
*Line Sources:* OA={oa} | BP={bp} | Both={both} | None={none_src}
*Subsets:* {subset_line}
*Feature Quality:* {avg_quality:.1f}% avg | {blocked} blocked

Next line check: 8 AM ET.
"""

    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="MORNING_SUMMARY",
        )
        logger.info(f"Sent MORNING_SUMMARY Slack alert for {game_date}")
    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send MORNING_SUMMARY Slack alert: {e}")


def send_recommendation_skew_alert(
    game_date: date,
    run_mode: str,
    overs: int,
    unders: int,
    total: int,
):
    """
    Session 171: Alert when recommendation distribution is heavily skewed.

    Catches Session 169-style 89% UNDER distribution even if avg_pvl happens
    to be within ±2.0. Fires after consolidation.

    Args:
        game_date: Date predictions are for
        run_mode: Prediction run mode (FIRST, BACKFILL, etc.)
        overs: Number of OVER recommendations
        unders: Number of UNDER recommendations
        total: Total active predictions with lines
    """
    over_pct = (overs / total * 100) if total > 0 else 0
    under_pct = (unders / total * 100) if total > 0 else 0
    dominant = "UNDER" if under_pct > over_pct else "OVER"
    dominant_pct = max(over_pct, under_pct)

    severity = "CRITICAL" if dominant_pct > 85 else "WARNING"
    emoji = ":rotating_light:" if severity == "CRITICAL" else ":warning:"

    message = f"""{emoji} *RECOMMENDATION SKEW* ({severity})

*{game_date}* ({run_mode}) — {dominant_pct:.0f}% {dominant}

```
OVER:  {overs:>4} ({over_pct:.1f}%)
UNDER: {unders:>4} ({under_pct:.1f}%)
Total: {total:>4}
```

Threshold: alert if either direction < 15%.
*Impact:* Lopsided recommendations suggest systematic model bias.
*Next steps:* Check PVL bias, Vegas line coverage, feature store quality.
"""

    alert = QualityAlert(
        alert_type="RECOMMENDATION_SKEW",
        severity=severity,
        message=f"{dominant_pct:.0f}% {dominant} for {game_date} ({run_mode})",
        details={
            'game_date': str(game_date),
            'run_mode': run_mode,
            'overs': overs,
            'unders': unders,
            'total': total,
            'over_pct': round(over_pct, 1),
            'under_pct': round(under_pct, 1),
        }
    )

    log_level = logging.ERROR if severity == "CRITICAL" else logging.WARNING
    logger.log(
        log_level,
        f"QUALITY_ALERT: RECOMMENDATION_SKEW - {dominant_pct:.0f}% {dominant} for {game_date}",
        extra={
            'alert_type': 'RECOMMENDATION_SKEW',
            'severity': severity,
            'details': alert.details,
        }
    )

    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="RECOMMENDATION_SKEW",
        )
        logger.info("Sent RECOMMENDATION_SKEW Slack alert")
    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send RECOMMENDATION_SKEW Slack alert: {e}")


def send_vegas_source_alert(
    game_date: date,
    run_mode: str,
    source_counts: Dict,
    total: int,
):
    """
    Session 171: Alert when >30% of predictions used recovery_median Vegas source.

    High recovery_median usage means the coordinator's actual_prop_line was NULL
    for many players, and we fell back to median of line_values. This is a warning
    sign that Vegas line plumbing needs investigation.

    Args:
        game_date: Date predictions are for
        run_mode: Prediction run mode
        source_counts: Dict mapping vegas_source to count
        total: Total active predictions
    """
    recovery_count = source_counts.get('recovery_median', 0)
    recovery_pct = (recovery_count / total * 100) if total > 0 else 0

    # Build source breakdown
    source_lines = []
    for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        pct = count / total * 100 if total > 0 else 0
        source_lines.append(f"  {source}: {count} ({pct:.0f}%)")
    source_str = "\n".join(source_lines)

    severity = "CRITICAL" if recovery_pct > 50 else "WARNING"
    emoji = ":rotating_light:" if severity == "CRITICAL" else ":warning:"

    message = f"""{emoji} *HIGH RECOVERY_MEDIAN USAGE* ({severity})

*{game_date}* ({run_mode}) — {recovery_count}/{total} predictions ({recovery_pct:.0f}%) used recovery_median

*Vegas source breakdown:*
```
{source_str}
```

Threshold: alert if recovery_median > 30%.
*Impact:* Coordinator's actual_prop_line was NULL; fell back to median of line_values.
*Next steps:* Check Phase 3 current_points_line population, odds scraper timing.
"""

    alert = QualityAlert(
        alert_type="VEGAS_SOURCE_RECOVERY_HIGH",
        severity=severity,
        message=f"{recovery_pct:.0f}% recovery_median for {game_date} ({run_mode})",
        details={
            'game_date': str(game_date),
            'run_mode': run_mode,
            'source_counts': source_counts,
            'recovery_count': recovery_count,
            'recovery_pct': round(recovery_pct, 1),
            'total': total,
        }
    )

    log_level = logging.ERROR if severity == "CRITICAL" else logging.WARNING
    logger.log(
        log_level,
        f"QUALITY_ALERT: VEGAS_SOURCE_RECOVERY_HIGH - {recovery_pct:.0f}% for {game_date}",
        extra={
            'alert_type': 'VEGAS_SOURCE_RECOVERY_HIGH',
            'severity': severity,
            'details': alert.details,
        }
    )

    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="VEGAS_SOURCE_RECOVERY_HIGH",
        )
        logger.info("Sent VEGAS_SOURCE_RECOVERY_HIGH Slack alert")
    except ImportError:
        logger.warning("Slack alerting not available - alert logged only")
    except Exception as e:
        logger.error(f"Failed to send VEGAS_SOURCE_RECOVERY_HIGH Slack alert: {e}")


def send_direction_mismatch_alert(
    game_date: date,
    run_mode: str,
    above_but_under: int,
    below_but_over: int,
    total: int,
):
    """
    Session 176: Alert when predictions have recommendation direction mismatches.

    Catches cases where predicted > line but recommendation = UNDER (or vice versa).
    The worker's defense-in-depth should prevent these, so any occurrence indicates
    a bypass or regression.

    Args:
        game_date: Date predictions are for
        run_mode: Prediction run mode
        above_but_under: Count of pred > line marked UNDER
        below_but_over: Count of pred < line marked OVER
        total: Total active predictions with lines
    """
    mismatch_count = above_but_under + below_but_over
    mismatch_pct = (mismatch_count / total * 100) if total > 0 else 0

    severity = "CRITICAL" if mismatch_count > 0 else "INFO"
    emoji = ":rotating_light:" if severity == "CRITICAL" else ":white_check_mark:"

    message = f"""{emoji} *RECOMMENDATION DIRECTION CHECK* ({severity})

*{game_date}* ({run_mode}) — {mismatch_count} mismatches out of {total} predictions

```
Above line + UNDER: {above_but_under}
Below line + OVER:  {below_but_over}
Total with lines:   {total}
```

*Impact:* Direction mismatches mean recommendations contradict the model's own prediction.
*Next steps:* If non-zero, check worker.py direction validation and multi-line logic.
"""

    alert = QualityAlert(
        alert_type="RECOMMENDATION_DIRECTION_MISMATCH",
        severity=severity,
        message=f"{mismatch_count} direction mismatches for {game_date} ({run_mode})",
        details={
            'game_date': str(game_date),
            'run_mode': run_mode,
            'above_but_under': above_but_under,
            'below_but_over': below_but_over,
            'mismatch_count': mismatch_count,
            'total': total,
        }
    )

    log_level = logging.ERROR if severity == "CRITICAL" else logging.INFO
    logger.log(
        log_level,
        f"QUALITY_ALERT: RECOMMENDATION_DIRECTION - {mismatch_count} mismatches for {game_date}",
        extra={
            'alert_type': 'RECOMMENDATION_DIRECTION_MISMATCH',
            'severity': severity,
            'details': alert.details,
        }
    )

    # Only send Slack alert if there are actual mismatches
    if mismatch_count > 0:
        try:
            from shared.utils.slack_alerts import send_slack_alert
            send_slack_alert(
                message=message,
                channel="#nba-alerts",
                alert_type="RECOMMENDATION_DIRECTION_MISMATCH",
            )
            logger.info("Sent RECOMMENDATION_DIRECTION_MISMATCH Slack alert")
        except ImportError:
            logger.warning("Slack alerting not available - alert logged only")
        except Exception as e:
            logger.error(f"Failed to send RECOMMENDATION_DIRECTION_MISMATCH Slack alert: {e}")
