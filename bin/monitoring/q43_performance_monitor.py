#!/usr/bin/env python3
"""
Q43 Performance Monitor — Daily Shadow Model Comparison

Compares the QUANT_43 shadow model (catboost_v9_q43_train1102_0131) against the
production champion (catboost_v9) to determine when Q43 is ready for promotion.

Session 186 Discovery: Quantile alpha=0.43 creates edge through systematic prediction
bias built into the loss function (staleness-independent). This monitor tracks whether
that theoretical advantage translates to sustained production performance.

Usage:
    # Standard daily check (last 7 days)
    PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py

    # Custom date range
    PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --days 14

    # Send Slack alert
    PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --slack

    # JSON output for automation
    PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --json

    # Include Q45 comparison
    PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --include-q45

Created: 2026-02-11
Part of: Quantile Model Monitoring (Session 186+)
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Model identifiers
Q43_SYSTEM_ID = "catboost_v9_q43_train1102_0131"
Q45_SYSTEM_ID = "catboost_v9_q45_train1102_0131"
CHAMPION_SYSTEM_ID = "catboost_v9"

# Thresholds for recommendations
PROMOTE_HR_THRESHOLD = 60.0        # Q43 edge 3+ HR must be >= 60%
PROMOTE_ADVANTAGE_THRESHOLD = 5.0  # Q43 must beat champion by >= 5pp
INVESTIGATE_HR_THRESHOLD = 45.0    # Below this, investigate
MIN_SAMPLE_SIZE = 20               # Minimum graded picks for confidence
MIN_DAILY_ACTIONABLE = 3           # Minimum daily picks to be useful
BREAKEVEN_THRESHOLD = 52.4         # Breakeven hit rate for -110 bets


def query_daily_comparison(
    client: bigquery.Client,
    days: int,
    system_ids: List[str],
) -> List[Dict[str, Any]]:
    """Query daily hit rate comparison between models."""
    id_list = ", ".join(f"'{sid}'" for sid in system_ids)

    query = f"""
    WITH daily_graded AS (
        SELECT
            system_id,
            game_date,
            COUNT(*) as total_graded,
            COUNTIF(is_actionable = TRUE) as actionable,
            COUNTIF(prediction_correct) as correct,
            COUNTIF(prediction_correct AND ABS(predicted_margin) >= 3) as correct_edge3,
            COUNTIF(ABS(predicted_margin) >= 3) as total_edge3,
            COUNTIF(prediction_correct AND ABS(predicted_margin) >= 5) as correct_edge5,
            COUNTIF(ABS(predicted_margin) >= 5) as total_edge5,
            ROUND(AVG(predicted_points - line_value), 2) as vegas_bias,
            COUNTIF(recommendation = 'UNDER') as under_count,
            COUNTIF(recommendation = 'OVER') as over_count,
            COUNTIF(prediction_correct AND recommendation = 'UNDER') as under_correct,
            COUNTIF(prediction_correct AND recommendation = 'OVER') as over_correct,
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE system_id IN ({id_list})
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND prediction_correct IS NOT NULL
          AND line_value IS NOT NULL
          AND recommendation IN ('OVER', 'UNDER')
          AND (is_voided IS NULL OR is_voided = FALSE)
        GROUP BY system_id, game_date
    )
    SELECT
        system_id,
        game_date,
        total_graded,
        actionable,
        correct,
        ROUND(100.0 * correct / NULLIF(total_graded, 0), 1) as hit_rate,
        total_edge3,
        correct_edge3,
        ROUND(100.0 * correct_edge3 / NULLIF(total_edge3, 0), 1) as hit_rate_edge3,
        total_edge5,
        correct_edge5,
        ROUND(100.0 * correct_edge5 / NULLIF(total_edge5, 0), 1) as hit_rate_edge5,
        vegas_bias,
        under_count,
        over_count,
        under_correct,
        over_correct,
        ROUND(100.0 * under_correct / NULLIF(under_count, 0), 1) as under_hr,
        ROUND(100.0 * over_correct / NULLIF(over_count, 0), 1) as over_hr,
    FROM daily_graded
    ORDER BY game_date DESC, system_id
    """

    rows = list(client.query(query).result())
    return [dict(row) for row in rows]


def query_aggregate_performance(
    client: bigquery.Client,
    days: int,
    system_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Query aggregate performance over the full period."""
    id_list = ", ".join(f"'{sid}'" for sid in system_ids)

    query = f"""
    WITH graded AS (
        SELECT
            system_id,
            game_date,
            predicted_points,
            actual_points,
            line_value,
            prediction_correct,
            recommendation,
            predicted_margin
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE system_id IN ({id_list})
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND prediction_correct IS NOT NULL
          AND line_value IS NOT NULL
          AND recommendation IN ('OVER', 'UNDER')
          AND (is_voided IS NULL OR is_voided = FALSE)
    )
    SELECT
        system_id,
        MIN(game_date) as first_date,
        MAX(game_date) as last_date,
        COUNT(DISTINCT game_date) as game_days,
        COUNT(*) as total_graded,
        ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate_all,
        ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,

        -- Edge 3+
        COUNTIF(ABS(predicted_margin) >= 3) as n_edge_3plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_margin) >= 3)
            / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hit_rate_edge_3plus,

        -- Edge 5+
        COUNTIF(ABS(predicted_margin) >= 5) as n_edge_5plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_margin) >= 5)
            / NULLIF(COUNTIF(ABS(predicted_margin) >= 5), 0), 1) as hit_rate_edge_5plus,

        -- Vegas bias
        ROUND(AVG(predicted_points - line_value), 2) as vegas_bias,

        -- Direction breakdown
        COUNTIF(recommendation = 'UNDER') as under_total,
        COUNTIF(prediction_correct AND recommendation = 'UNDER') as under_correct,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER')
            / NULLIF(COUNTIF(recommendation = 'UNDER'), 0), 1) as under_hr,
        COUNTIF(recommendation = 'OVER') as over_total,
        COUNTIF(prediction_correct AND recommendation = 'OVER') as over_correct,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER')
            / NULLIF(COUNTIF(recommendation = 'OVER'), 0), 1) as over_hr,

        -- Edge 3+ direction breakdown
        COUNTIF(recommendation = 'UNDER' AND ABS(predicted_margin) >= 3) as under_edge3_total,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER' AND ABS(predicted_margin) >= 3)
            / NULLIF(COUNTIF(recommendation = 'UNDER' AND ABS(predicted_margin) >= 3), 0), 1) as under_edge3_hr,
        COUNTIF(recommendation = 'OVER' AND ABS(predicted_margin) >= 3) as over_edge3_total,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER' AND ABS(predicted_margin) >= 3)
            / NULLIF(COUNTIF(recommendation = 'OVER' AND ABS(predicted_margin) >= 3), 0), 1) as over_edge3_hr,

    FROM graded
    GROUP BY system_id
    """

    results = {}
    for row in client.query(query).result():
        results[row.system_id] = dict(row)

    return results


def compute_recommendation(
    q43_perf: Optional[Dict],
    champion_perf: Optional[Dict],
) -> Dict[str, str]:
    """Determine recommendation based on Q43 vs champion performance."""
    if not q43_perf:
        return {
            "recommendation": "NO_DATA",
            "action": "No Q43 graded data available. Verify model is deployed and producing predictions.",
            "severity": "WARNING",
        }

    q43_n = q43_perf.get("n_edge_3plus", 0) or 0
    q43_hr = q43_perf.get("hit_rate_edge_3plus")
    champ_hr = champion_perf.get("hit_rate_edge_3plus") if champion_perf else None

    # Insufficient sample size
    if q43_n < MIN_SAMPLE_SIZE:
        return {
            "recommendation": "INSUFFICIENT_DATA",
            "action": f"Only {q43_n} edge 3+ picks graded (need {MIN_SAMPLE_SIZE}+). Continue monitoring.",
            "severity": "INFO",
        }

    if q43_hr is None:
        return {
            "recommendation": "NO_EDGE_DATA",
            "action": "No edge 3+ picks to evaluate. Check model predictions.",
            "severity": "WARNING",
        }

    q43_hr_f = float(q43_hr)

    # Below investigation threshold
    if q43_hr_f < INVESTIGATE_HR_THRESHOLD:
        return {
            "recommendation": "INVESTIGATE",
            "action": f"Q43 edge 3+ HR at {q43_hr_f:.1f}% (below {INVESTIGATE_HR_THRESHOLD}%). "
                      f"Check for systematic issues.",
            "severity": "CRITICAL",
        }

    # Below breakeven
    if q43_hr_f < BREAKEVEN_THRESHOLD:
        return {
            "recommendation": "MONITOR",
            "action": f"Q43 edge 3+ HR at {q43_hr_f:.1f}% (below breakeven {BREAKEVEN_THRESHOLD}%). "
                      f"Not yet profitable.",
            "severity": "WARNING",
        }

    # Above breakeven but below promotion threshold
    if q43_hr_f < PROMOTE_HR_THRESHOLD:
        return {
            "recommendation": "MONITOR",
            "action": f"Q43 edge 3+ HR at {q43_hr_f:.1f}% (profitable but below {PROMOTE_HR_THRESHOLD}% target). "
                      f"Continue monitoring.",
            "severity": "INFO",
        }

    # Check advantage over champion
    if champ_hr is not None:
        advantage = q43_hr_f - float(champ_hr)
        if advantage >= PROMOTE_ADVANTAGE_THRESHOLD:
            return {
                "recommendation": "PROMOTE",
                "action": f"Q43 outperforming champion by {advantage:+.1f}pp "
                          f"({q43_hr_f:.1f}% vs {float(champ_hr):.1f}%). "
                          f"Consider promotion.\n"
                          f"Action: Run ./bin/model-registry.sh promote catboost_v9_q43_train1102_0131",
                "severity": "SUCCESS",
            }
        elif advantage > 0:
            return {
                "recommendation": "MONITOR",
                "action": f"Q43 slightly ahead (+{advantage:.1f}pp). "
                          f"Need {PROMOTE_ADVANTAGE_THRESHOLD}+pp advantage for promotion.",
                "severity": "INFO",
            }
        else:
            return {
                "recommendation": "MONITOR",
                "action": f"Q43 behind champion by {advantage:.1f}pp despite good absolute HR. "
                          f"Continue monitoring.",
                "severity": "WARNING",
            }

    # No champion data for comparison but Q43 looks good
    return {
        "recommendation": "MONITOR",
        "action": f"Q43 edge 3+ HR at {q43_hr_f:.1f}% (above target). "
                  f"No champion data for comparison. Continue monitoring.",
        "severity": "INFO",
    }


def format_val(val, suffix='', na='N/A'):
    """Format a value with suffix, handling None/NaN."""
    if val is None:
        return na
    if isinstance(val, float) and val != val:  # NaN check
        return na
    v = float(val) if hasattr(val, 'as_tuple') else val
    if isinstance(v, float):
        return f"{v:.1f}{suffix}"
    return f"{v}{suffix}"


def print_daily_table(
    daily_data: List[Dict],
    system_ids: List[str],
    days: int,
) -> str:
    """Print daily comparison table. Returns the table as a string."""
    lines = []

    # Pivot daily data by date
    dates_seen = sorted(set(r['game_date'] for r in daily_data), reverse=True)

    if not dates_seen:
        msg = f"No graded data found in the last {days} days."
        lines.append(msg)
        return "\n".join(lines)

    # Header
    header = f"| {'Date':<6s} |"
    separator = f"|{'-' * 8}|"

    for sid in system_ids:
        short_name = sid.replace("catboost_v9_", "").replace("catboost_v9", "Champion")
        header += f" {short_name + ' HR':>12s} | {short_name + ' N':>6s} | {short_name + ' 3+ HR':>9s} | {short_name + ' 3+ N':>6s} |"
        separator += f"{'-' * 14}|{'-' * 8}|{'-' * 11}|{'-' * 8}|"

    header += f" {'Winner':>10s} |"
    separator += f"{'-' * 12}|"

    lines.append(header)
    lines.append(separator)

    for game_date in dates_seen:
        date_str = game_date.strftime("%-m/%-d") if hasattr(game_date, 'strftime') else str(game_date)
        row = f"| {date_str:<6s} |"

        # Collect HR values for winner comparison
        hr_by_model = {}

        for sid in system_ids:
            day_data = next((r for r in daily_data if r['game_date'] == game_date and r['system_id'] == sid), None)
            if day_data:
                hr_all = format_val(day_data.get('hit_rate'), '%')
                n_all = str(day_data.get('total_graded', 0))
                hr_3 = format_val(day_data.get('hit_rate_edge3'), '%')
                n_3 = str(day_data.get('total_edge3', 0))
                hr_by_model[sid] = day_data.get('hit_rate_edge3')
            else:
                hr_all = "---"
                n_all = "0"
                hr_3 = "---"
                n_3 = "0"

            row += f" {hr_all:>12s} | {n_all:>6s} | {hr_3:>9s} | {n_3:>6s} |"

        # Determine winner (by edge 3+ HR)
        valid_hrs = {k: v for k, v in hr_by_model.items() if v is not None}
        if len(valid_hrs) >= 2:
            best = max(valid_hrs, key=valid_hrs.get)
            winner = best.replace("catboost_v9_", "").replace("catboost_v9", "Champ")
            if len(winner) > 10:
                winner = winner[:10]
        elif len(valid_hrs) == 1:
            winner = "only 1"
        else:
            winner = "---"

        row += f" {winner:>10s} |"
        lines.append(row)

    return "\n".join(lines)


def print_report(
    daily_data: List[Dict],
    aggregates: Dict[str, Dict],
    recommendation: Dict[str, str],
    system_ids: List[str],
    days: int,
) -> str:
    """Print the full monitoring report. Returns report as string."""
    lines = []
    today = date.today().strftime("%Y-%m-%d")

    lines.append(f"=== Q43 Performance Monitor ({today}) ===")
    lines.append("")

    # Daily comparison table
    lines.append(f"Last {days} Days Performance:")
    daily_table = print_daily_table(daily_data, system_ids, days)
    lines.append(daily_table)
    lines.append("")

    # Aggregate summary
    lines.append("Summary:")
    for sid in system_ids:
        perf = aggregates.get(sid)
        if not perf:
            short = sid.replace("catboost_v9_", "").replace("catboost_v9", "Champion")
            lines.append(f"- {short}: No graded data")
            continue

        short = sid.replace("catboost_v9_", "").replace("catboost_v9", "Champion")
        hr_all = format_val(perf.get('hit_rate_all'), '%')
        n_all = perf.get('total_graded', 0)
        hr_3 = format_val(perf.get('hit_rate_edge_3plus'), '%')
        n_3 = perf.get('n_edge_3plus', 0)
        vegas = format_val(perf.get('vegas_bias'))
        mae = format_val(perf.get('mae'))

        lines.append(f"- {short} weekly hit rate: {hr_all} (n={n_all})")
        lines.append(f"  Edge 3+ HR: {hr_3} (n={n_3}), MAE: {mae}, Vegas bias: {vegas}")

    # Q43 vs Champion comparison
    q43_perf = aggregates.get(Q43_SYSTEM_ID)
    champ_perf = aggregates.get(CHAMPION_SYSTEM_ID)
    if q43_perf and champ_perf:
        q43_hr = q43_perf.get('hit_rate_edge_3plus')
        champ_hr = champ_perf.get('hit_rate_edge_3plus')
        if q43_hr is not None and champ_hr is not None:
            advantage = float(q43_hr) - float(champ_hr)
            lines.append(f"- Q43 advantage: {advantage:+.1f} percentage points (edge 3+)")

    lines.append("")

    # High-edge breakdown
    lines.append("High-Edge (3+) Performance:")
    for sid in system_ids:
        perf = aggregates.get(sid)
        if not perf:
            continue
        short = sid.replace("catboost_v9_", "").replace("catboost_v9", "Champion")
        hr_3 = format_val(perf.get('hit_rate_edge_3plus'), '%')
        n_3 = perf.get('n_edge_3plus', 0) or 0
        under_3_hr = format_val(perf.get('under_edge3_hr'), '%')
        under_3_n = perf.get('under_edge3_total', 0) or 0
        over_3_hr = format_val(perf.get('over_edge3_hr'), '%')
        over_3_n = perf.get('over_edge3_total', 0) or 0
        lines.append(f"- {short}: {hr_3} (n={n_3})")
        lines.append(f"  UNDER 3+: {under_3_hr} (n={under_3_n}), OVER 3+: {over_3_hr} (n={over_3_n})")

    lines.append("")

    # Edge 5+ breakdown
    lines.append("High-Edge (5+) Performance:")
    for sid in system_ids:
        perf = aggregates.get(sid)
        if not perf:
            continue
        short = sid.replace("catboost_v9_", "").replace("catboost_v9", "Champion")
        hr_5 = format_val(perf.get('hit_rate_edge_5plus'), '%')
        n_5 = perf.get('n_edge_5plus', 0) or 0
        lines.append(f"- {short}: {hr_5} (n={n_5})")

    lines.append("")

    # Statistical confidence note
    q43_n3 = q43_perf.get('n_edge_3plus', 0) if q43_perf else 0
    q43_n3 = q43_n3 or 0
    if q43_n3 < MIN_SAMPLE_SIZE:
        lines.append(f"Statistical Confidence: LOW ({q43_n3}/{MIN_SAMPLE_SIZE} minimum edge 3+ picks)")
    elif q43_n3 < 50:
        lines.append(f"Statistical Confidence: MODERATE ({q43_n3} edge 3+ picks, want 50+)")
    else:
        lines.append(f"Statistical Confidence: HIGH ({q43_n3} edge 3+ picks)")

    lines.append("")

    # Recommendation
    severity_marker = {
        "SUCCESS": "[PROMOTE]",
        "INFO": "[OK]",
        "WARNING": "[WARNING]",
        "CRITICAL": "[CRITICAL]",
    }.get(recommendation['severity'], "[?]")

    lines.append(f"Recommendation: {recommendation['recommendation']} {severity_marker}")
    lines.append(f"  {recommendation['action']}")
    lines.append("")

    return "\n".join(lines)


def build_slack_message(
    aggregates: Dict[str, Dict],
    recommendation: Dict[str, str],
    days: int,
) -> str:
    """Build a Slack-formatted message."""
    lines = []
    today = date.today().strftime("%Y-%m-%d")

    severity_emoji = {
        "SUCCESS": ":white_check_mark:",
        "INFO": ":large_blue_circle:",
        "WARNING": ":warning:",
        "CRITICAL": ":red_circle:",
    }.get(recommendation['severity'], ":question:")

    lines.append(f"{severity_emoji} *Q43 Performance Monitor* ({today})")
    lines.append("")

    q43_perf = aggregates.get(Q43_SYSTEM_ID)
    champ_perf = aggregates.get(CHAMPION_SYSTEM_ID)

    if q43_perf:
        q43_hr3 = format_val(q43_perf.get('hit_rate_edge_3plus'), '%')
        q43_n3 = q43_perf.get('n_edge_3plus', 0) or 0
        lines.append(f"*Q43* ({days}d): Edge 3+ HR = *{q43_hr3}* (n={q43_n3})")
    else:
        lines.append("*Q43*: No graded data")

    if champ_perf:
        champ_hr3 = format_val(champ_perf.get('hit_rate_edge_3plus'), '%')
        champ_n3 = champ_perf.get('n_edge_3plus', 0) or 0
        lines.append(f"*Champion* ({days}d): Edge 3+ HR = *{champ_hr3}* (n={champ_n3})")
    else:
        lines.append("*Champion*: No graded data")

    if q43_perf and champ_perf:
        q43_hr = q43_perf.get('hit_rate_edge_3plus')
        champ_hr = champ_perf.get('hit_rate_edge_3plus')
        if q43_hr is not None and champ_hr is not None:
            advantage = float(q43_hr) - float(champ_hr)
            lines.append(f"Advantage: *{advantage:+.1f}pp*")

    lines.append("")
    lines.append(f"*Recommendation: {recommendation['recommendation']}*")
    lines.append(recommendation['action'])

    return "\n".join(lines)


def send_slack_alert(message: str) -> bool:
    """Send Slack alert using the shared utility."""
    try:
        from shared.utils.slack_alerts import send_slack_alert as _send
        return _send(
            message=message,
            channel="#nba-alerts",
            alert_type="Q43_PERFORMANCE_MONITOR",
        )
    except ImportError:
        logger.warning("Could not import shared.utils.slack_alerts. Slack alert not sent.")
        return False
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Q43 Performance Monitor - Compare quantile shadow model vs champion"
    )
    parser.add_argument(
        '--days', type=int, default=7,
        help='Number of days to analyze (default: 7)'
    )
    parser.add_argument(
        '--slack', action='store_true',
        help='Send alert to #nba-alerts Slack channel'
    )
    parser.add_argument(
        '--json', action='store_true',
        help='Output as JSON for automation'
    )
    parser.add_argument(
        '--include-q45', action='store_true',
        help='Include Q45 model in comparison'
    )
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    # Build system IDs list
    system_ids = [CHAMPION_SYSTEM_ID, Q43_SYSTEM_ID]
    if args.include_q45:
        system_ids.append(Q45_SYSTEM_ID)

    logger.info(f"Querying performance data for last {args.days} days...")

    # Fetch data
    daily_data = query_daily_comparison(client, args.days, system_ids)
    aggregates = query_aggregate_performance(client, args.days, system_ids)

    # Compute recommendation
    q43_perf = aggregates.get(Q43_SYSTEM_ID)
    champion_perf = aggregates.get(CHAMPION_SYSTEM_ID)
    recommendation = compute_recommendation(q43_perf, champion_perf)

    if args.json:
        output = {
            "generated_at": datetime.now().isoformat(),
            "days": args.days,
            "aggregates": {
                k: {kk: str(vv) if isinstance(vv, date) else vv for kk, vv in v.items()}
                for k, v in aggregates.items()
            },
            "recommendation": recommendation,
            "daily": [
                {k: str(v) if isinstance(v, date) else v for k, v in row.items()}
                for row in daily_data
            ],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        report = print_report(daily_data, aggregates, recommendation, system_ids, args.days)
        print(report)

    # Send Slack alert if requested
    if args.slack:
        slack_msg = build_slack_message(aggregates, recommendation, args.days)
        success = send_slack_alert(slack_msg)
        if success:
            logger.info("Slack alert sent successfully")
        else:
            logger.warning("Slack alert failed or not configured")

    # Exit code based on recommendation severity
    exit_codes = {
        "SUCCESS": 0,
        "INFO": 0,
        "WARNING": 1,
        "CRITICAL": 2,
    }
    sys.exit(exit_codes.get(recommendation['severity'], 0))


if __name__ == "__main__":
    main()
