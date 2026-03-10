"""
MLB Pitcher Watchlist Evaluator — Weekly Cloud Function

Evaluates blacklisted pitchers for removal and active pitchers for addition
based on rolling BB HR and shadow pick performance.

Schedule: Weekly Monday 10 AM ET during MLB season (April-October)
Trigger: HTTP (Cloud Scheduler)

Thresholds:
  - Add to blacklist: active pitcher, BB HR < 45%, N >= 8
  - Remove from blacklist: shadow HR >= 60%, N >= 8
  - Watch for add: BB HR < 50%, N >= 5
  - Watch for remove: Shadow HR >= 55%, N >= 5
"""

import json
import logging
import os
from datetime import datetime, timezone

import functions_framework
from google.cloud import bigquery
import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PROJECT_ID = "nba-props-platform"
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL_ALERTS')

# Thresholds
ADD_HR_THRESHOLD = 45.0       # BB HR below this → recommend blacklist
ADD_MIN_N = 8                 # Minimum picks for add recommendation
REMOVE_HR_THRESHOLD = 60.0    # Shadow HR above this → recommend removal
REMOVE_MIN_N = 8              # Minimum shadow picks for removal
WATCH_ADD_HR = 50.0           # Approaching add threshold
WATCH_ADD_MIN_N = 5
WATCH_REMOVE_HR = 55.0        # Approaching remove threshold
WATCH_REMOVE_MIN_N = 5

# Current blacklist (must match signals.py — single source of truth)
BLACKLIST = frozenset([
    'tanner_bibee', 'mitchell_parker', 'casey_mize', 'mitch_keller',
    'logan_webb', 'jose_berrios', 'logan_gilbert', 'logan_allen',
    'jake_irvin', 'george_kirby', 'mackenzie_gore', 'bailey_ober',
    'zach_eflin', 'ryne_nelson', 'jameson_taillon', 'ryan_feltner',
    'luis_severino', 'randy_vasquez',
    'adrian_houser', 'stephen_kolek', 'dean_kremer',
    'michael_mcgreevy', 'tyler_mahle',
    'ranger_suárez', 'cade_horton', 'blake_snell',
    'luis_castillo', 'paul_skenes',
])


@functions_framework.http
def evaluate_pitcher_watchlist(request):
    """Evaluate pitcher watchlist and send Slack digest."""
    try:
        client = bigquery.Client(project=PROJECT_ID)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        # 1. Get active pitcher BB performance (season-to-date)
        active_pitchers = _get_active_pitcher_stats(client)

        # 2. Get blacklisted pitcher shadow performance
        shadow_pitchers = _get_shadow_pitcher_stats(client)

        # 3. Get model-level HR for all pitchers
        model_stats = _get_model_level_stats(client)

        # 4. Evaluate each pitcher
        watchlist_rows = []
        add_candidates = []
        remove_candidates = []
        watch_add = []
        watch_remove = []

        # Evaluate active pitchers for blacklist addition
        for pitcher, stats in active_pitchers.items():
            if pitcher in BLACKLIST:
                continue  # Skip — evaluated via shadow picks below

            hr_pct = (stats['wins'] / stats['n'] * 100) if stats['n'] > 0 else 0
            model = model_stats.get(pitcher, {})

            row = {
                'evaluation_date': today,
                'pitcher_lookup': pitcher,
                'current_status': 'ACTIVE',
                'bb_hr_pct': round(hr_pct, 1),
                'bb_n': stats['n'],
                'bb_wins': stats['wins'],
                'shadow_hr_pct': None,
                'shadow_n': 0,
                'shadow_wins': 0,
                'model_hr_pct': round(model.get('hr', 0), 1) if model else None,
                'model_n': model.get('n', 0) if model else 0,
                'recommended_action': 'NONE',
                'action_reason': None,
                'last_updated': datetime.now(timezone.utc).isoformat(),
            }

            if stats['n'] >= ADD_MIN_N and hr_pct < ADD_HR_THRESHOLD:
                row['current_status'] = 'WATCH_FOR_ADD'
                row['recommended_action'] = 'ADD_TO_BLACKLIST'
                row['action_reason'] = (
                    f"BB HR {hr_pct:.1f}% < {ADD_HR_THRESHOLD}% at N={stats['n']}"
                )
                add_candidates.append(row)
            elif stats['n'] >= WATCH_ADD_MIN_N and hr_pct < WATCH_ADD_HR:
                row['current_status'] = 'WATCH_FOR_ADD'
                row['action_reason'] = (
                    f"BB HR {hr_pct:.1f}% approaching threshold (N={stats['n']})"
                )
                watch_add.append(row)

            watchlist_rows.append(row)

        # Evaluate blacklisted pitchers for removal
        for pitcher in BLACKLIST:
            stats = shadow_pitchers.get(pitcher, {'n': 0, 'wins': 0})
            hr_pct = (stats['wins'] / stats['n'] * 100) if stats['n'] > 0 else 0
            model = model_stats.get(pitcher, {})

            row = {
                'evaluation_date': today,
                'pitcher_lookup': pitcher,
                'current_status': 'BLACKLISTED',
                'bb_hr_pct': None,
                'bb_n': 0,
                'bb_wins': 0,
                'shadow_hr_pct': round(hr_pct, 1) if stats['n'] > 0 else None,
                'shadow_n': stats['n'],
                'shadow_wins': stats['wins'],
                'model_hr_pct': round(model.get('hr', 0), 1) if model else None,
                'model_n': model.get('n', 0) if model else 0,
                'recommended_action': 'NONE',
                'action_reason': None,
                'last_updated': datetime.now(timezone.utc).isoformat(),
            }

            if stats['n'] >= REMOVE_MIN_N and hr_pct >= REMOVE_HR_THRESHOLD:
                row['current_status'] = 'WATCH_FOR_REMOVE'
                row['recommended_action'] = 'REMOVE_FROM_BLACKLIST'
                row['action_reason'] = (
                    f"Shadow HR {hr_pct:.1f}% >= {REMOVE_HR_THRESHOLD}% at N={stats['n']}"
                )
                remove_candidates.append(row)
            elif stats['n'] >= WATCH_REMOVE_MIN_N and hr_pct >= WATCH_REMOVE_HR:
                row['current_status'] = 'WATCH_FOR_REMOVE'
                row['action_reason'] = (
                    f"Shadow HR {hr_pct:.1f}% approaching threshold (N={stats['n']})"
                )
                watch_remove.append(row)

            watchlist_rows.append(row)

        # 5. Write watchlist to BQ
        if watchlist_rows:
            _write_watchlist(client, watchlist_rows)

        # 6. Send Slack digest if there are recommendations
        has_recommendations = (add_candidates or remove_candidates
                               or watch_add or watch_remove)
        if has_recommendations:
            _send_slack_digest(
                add_candidates, remove_candidates,
                watch_add, watch_remove, today,
            )

        summary = {
            'evaluation_date': today,
            'active_pitchers_evaluated': len(active_pitchers),
            'blacklisted_pitchers_evaluated': len(BLACKLIST),
            'shadow_pitchers_with_data': len(shadow_pitchers),
            'add_candidates': len(add_candidates),
            'remove_candidates': len(remove_candidates),
            'watch_add': len(watch_add),
            'watch_remove': len(watch_remove),
        }
        logger.info(f"Watchlist evaluation complete: {json.dumps(summary)}")

        return json.dumps(summary), 200

    except Exception as e:
        logger.error(f"Watchlist evaluation failed: {e}", exc_info=True)
        return json.dumps({'error': str(e)}), 500


def _get_active_pitcher_stats(client: bigquery.Client) -> dict:
    """Get BB HR for active (non-blacklisted) pitchers this season."""
    query = """
    SELECT
        bb.pitcher_lookup,
        COUNT(*) as n,
        COUNTIF(bb.prediction_correct = TRUE) as wins
    FROM `mlb_predictions.signal_best_bets_picks` bb
    WHERE bb.game_date >= DATE_TRUNC(CURRENT_DATE(), YEAR)
      AND bb.prediction_correct IS NOT NULL
    GROUP BY 1
    """
    results = {}
    for row in client.query(query).result():
        results[row.pitcher_lookup] = {
            'n': row.n,
            'wins': row.wins,
        }
    return results


def _get_shadow_pitcher_stats(client: bigquery.Client) -> dict:
    """Get shadow pick HR for blacklisted pitchers."""
    query = """
    SELECT
        pitcher_lookup,
        COUNT(*) as n,
        COUNTIF(prediction_correct = TRUE) as wins
    FROM `mlb_predictions.blacklist_shadow_picks`
    WHERE game_date >= DATE_TRUNC(CURRENT_DATE(), YEAR)
      AND prediction_correct IS NOT NULL
    GROUP BY 1
    """
    results = {}
    for row in client.query(query).result():
        results[row.pitcher_lookup] = {
            'n': row.n,
            'wins': row.wins,
        }
    return results


def _get_model_level_stats(client: bigquery.Client) -> dict:
    """Get overall model-level HR for all pitchers this season."""
    query = """
    SELECT
        pitcher_lookup,
        COUNT(*) as n,
        COUNTIF(prediction_correct = TRUE) as wins,
        SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100 as hr
    FROM `mlb_predictions.prediction_accuracy`
    WHERE game_date >= DATE_TRUNC(CURRENT_DATE(), YEAR)
      AND prediction_correct IS NOT NULL
      AND has_prop_line = TRUE
      AND recommendation = 'OVER'
    GROUP BY 1
    """
    results = {}
    for row in client.query(query).result():
        results[row.pitcher_lookup] = {
            'n': row.n,
            'wins': row.wins,
            'hr': float(row.hr) if row.hr else 0,
        }
    return results


def _write_watchlist(client: bigquery.Client, rows: list):
    """Write watchlist evaluation to BQ."""
    table_id = f"{PROJECT_ID}.mlb_predictions.pitcher_watchlist"
    try:
        errors = client.insert_rows_json(table_id, rows)
        if errors:
            logger.error(f"Watchlist insert errors: {errors[:3]}")
        else:
            logger.info(f"Wrote {len(rows)} watchlist rows")
    except Exception as e:
        logger.error(f"Failed to write watchlist: {e}")


def _send_slack_digest(add_candidates, remove_candidates,
                       watch_add, watch_remove, today):
    """Send weekly Slack digest with watchlist recommendations."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("No SLACK_WEBHOOK_URL_ALERTS configured, skipping alert")
        return

    sections = []

    if add_candidates:
        lines = []
        for c in sorted(add_candidates, key=lambda x: x['bb_hr_pct']):
            model_info = f", model {c['model_hr_pct']}%" if c['model_hr_pct'] else ""
            lines.append(
                f"  • `{c['pitcher_lookup']}`: BB HR {c['bb_hr_pct']}% "
                f"({c['bb_wins']}-{c['bb_n'] - c['bb_wins']}, N={c['bb_n']}{model_info})"
            )
        sections.append(f"*:rotating_light: ADD to blacklist:*\n" + "\n".join(lines))

    if remove_candidates:
        lines = []
        for c in sorted(remove_candidates, key=lambda x: -x['shadow_hr_pct']):
            model_info = f", model {c['model_hr_pct']}%" if c['model_hr_pct'] else ""
            lines.append(
                f"  • `{c['pitcher_lookup']}`: Shadow HR {c['shadow_hr_pct']}% "
                f"({c['shadow_wins']}-{c['shadow_n'] - c['shadow_wins']}, N={c['shadow_n']}{model_info})"
            )
        sections.append(f"*:white_check_mark: REMOVE from blacklist:*\n" + "\n".join(lines))

    if watch_add:
        lines = []
        for c in sorted(watch_add, key=lambda x: x['bb_hr_pct']):
            lines.append(
                f"  • `{c['pitcher_lookup']}`: BB HR {c['bb_hr_pct']}% (N={c['bb_n']})"
            )
        sections.append(f"*:eyes: Approaching blacklist:*\n" + "\n".join(lines))

    if watch_remove:
        lines = []
        for c in sorted(watch_remove, key=lambda x: -x['shadow_hr_pct']):
            lines.append(
                f"  • `{c['pitcher_lookup']}`: Shadow HR {c['shadow_hr_pct']}% (N={c['shadow_n']})"
            )
        sections.append(f"*:eyes: Approaching removal:*\n" + "\n".join(lines))

    body = "\n\n".join(sections)

    payload = {
        'attachments': [{
            'color': '#FF8C00' if add_candidates else '#36a64f',
            'blocks': [
                {
                    'type': 'header',
                    'text': {
                        'type': 'plain_text',
                        'text': f'⚾ MLB Pitcher Watchlist — {today}',
                    }
                },
                {
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': body,
                    }
                },
                {
                    'type': 'context',
                    'elements': [{
                        'type': 'mrkdwn',
                        'text': (
                            f"Add threshold: BB HR < {ADD_HR_THRESHOLD}% at N >= {ADD_MIN_N} | "
                            f"Remove threshold: Shadow HR >= {REMOVE_HR_THRESHOLD}% at N >= {REMOVE_MIN_N}"
                        ),
                    }]
                },
            ]
        }]
    }

    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Sent watchlist Slack digest")
    except Exception as e:
        logger.error(f"Failed to send Slack digest: {e}")


# Cloud Function entry point alias (Gen2 immutable entry point)
main = evaluate_pitcher_watchlist
