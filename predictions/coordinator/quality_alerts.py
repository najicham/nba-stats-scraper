# predictions/coordinator/quality_alerts.py
"""
Quality Alerts for Prediction System (Session 95)

Sends alerts when prediction quality issues are detected:
- LOW_QUALITY_FEATURES: >20% of players have quality < 85%
- PHASE4_DATA_MISSING: Feature store has 0 rows for today
- FORCED_PREDICTIONS: >10 players forced at LAST_CALL
- LOW_COVERAGE: <80% of expected players have predictions
"""

import logging
from datetime import date
from typing import Dict, Optional
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
