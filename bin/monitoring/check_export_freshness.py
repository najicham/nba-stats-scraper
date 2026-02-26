#!/usr/bin/env python3
"""
GCS Export Freshness Monitor

Detects stale Phase 6 export files in the GCS API bucket.
Prevents the scenario from Session 343 where best-bets/latest.json went
stale for 4 days undetected because the legacy exporter was decommissioned.

Usage:
    python bin/monitoring/check_export_freshness.py
    python bin/monitoring/check_export_freshness.py --max-age-hours 6
    python bin/monitoring/check_export_freshness.py --json  # Machine-readable output

Created: 2026-02-25 (Session 343)
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta

from google.cloud import storage


PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-props-platform-api'

# Export files and their expected max staleness (hours)
# Files that should be updated at least daily
MONITORED_EXPORTS = {
    # Core prediction exports (updated multiple times daily)
    'v1/tonight/all-players.json': {'max_age_hours': 12, 'severity': 'CRITICAL'},
    'v1/status.json': {'max_age_hours': 24, 'severity': 'HIGH'},
    # Signal and model health (updated post-grading)
    'v1/systems/signal-health.json': {'max_age_hours': 24, 'severity': 'HIGH'},
    'v1/systems/model-health.json': {'max_age_hours': 24, 'severity': 'HIGH'},
    # Best bets (should be refreshed daily + post-grading)
    'v1/best-bets/all.json': {'max_age_hours': 24, 'severity': 'HIGH'},
    'v1/best-bets/today.json': {'max_age_hours': 24, 'severity': 'HIGH'},
    'v1/best-bets/latest.json': {'max_age_hours': 24, 'severity': 'HIGH'},
    'v1/best-bets/record.json': {'max_age_hours': 36, 'severity': 'MEDIUM'},
    'v1/best-bets/history.json': {'max_age_hours': 36, 'severity': 'MEDIUM'},
    # Signal best bets (primary best-bets system)
    'v1/signal-best-bets/latest.json': {'max_age_hours': 24, 'severity': 'CRITICAL'},
}


def check_freshness(max_age_override: int = None) -> dict:
    """Check freshness of all monitored export files.

    Returns:
        Dict with results per file and overall status.
    """
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    now = datetime.now(timezone.utc)

    results = []
    stale_count = 0
    missing_count = 0
    critical_issues = []

    for path, config in MONITORED_EXPORTS.items():
        max_hours = max_age_override or config['max_age_hours']
        severity = config['severity']

        blob = bucket.blob(path)
        if not blob.exists():
            missing_count += 1
            entry = {
                'path': path,
                'status': 'MISSING',
                'severity': severity,
                'updated': None,
                'age_hours': None,
            }
            results.append(entry)
            if severity in ('CRITICAL', 'HIGH'):
                critical_issues.append(f"MISSING: {path}")
            continue

        blob.reload()  # Fetch metadata (updated timestamp)
        updated = blob.updated
        age = now - updated
        age_hours = age.total_seconds() / 3600

        if age_hours > max_hours:
            stale_count += 1
            status = 'STALE'
            if severity in ('CRITICAL', 'HIGH'):
                critical_issues.append(
                    f"STALE ({age_hours:.1f}h): {path}"
                )
        else:
            status = 'FRESH'

        results.append({
            'path': path,
            'status': status,
            'severity': severity,
            'updated': updated.isoformat(),
            'age_hours': round(age_hours, 1),
            'max_age_hours': max_hours,
        })

    overall = 'PASS'
    if critical_issues:
        overall = 'FAIL'
    elif stale_count > 0 or missing_count > 0:
        overall = 'WARNING'

    return {
        'overall': overall,
        'checked_at': now.isoformat(),
        'total_files': len(MONITORED_EXPORTS),
        'fresh': len(results) - stale_count - missing_count,
        'stale': stale_count,
        'missing': missing_count,
        'critical_issues': critical_issues,
        'results': results,
    }


def main():
    parser = argparse.ArgumentParser(description='Check GCS export freshness')
    parser.add_argument('--max-age-hours', type=int, default=None,
                        help='Override max age for all files (hours)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    args = parser.parse_args()

    report = check_freshness(args.max_age_hours)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status_icon = {'PASS': '✅', 'WARNING': '⚠️', 'FAIL': '🔴'}
        print(f"\n=== GCS Export Freshness Check ===")
        print(f"Status: {status_icon.get(report['overall'], '?')} {report['overall']}")
        print(f"Files: {report['fresh']} fresh, {report['stale']} stale, {report['missing']} missing\n")

        for r in report['results']:
            icon = '✅' if r['status'] == 'FRESH' else '🔴' if r['status'] == 'MISSING' else '⚠️'
            age_str = f"{r['age_hours']}h" if r['age_hours'] is not None else 'N/A'
            print(f"  {icon} {r['path']}")
            if r['status'] != 'FRESH':
                print(f"      Status: {r['status']} | Age: {age_str} | Severity: {r['severity']}")

        if report['critical_issues']:
            print(f"\n🔴 Critical Issues:")
            for issue in report['critical_issues']:
                print(f"  - {issue}")

    sys.exit(0 if report['overall'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
