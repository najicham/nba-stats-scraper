#!/usr/bin/env python3
"""
Analysis Template Runner

Executes SQL analysis templates against BigQuery with parameterized date ranges.

Usage:
    python bin/analysis/run_analysis.py --template tier_direction_regime --start 2026-01-01 --end 2026-02-28
    python bin/analysis/run_analysis.py --template day_of_week --start 2025-10-22 --end 2026-02-28
    python bin/analysis/run_analysis.py --list
    python bin/analysis/run_analysis.py --template slate_size --start 2026-01-01 --end 2026-02-28 --csv results.csv
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

TEMPLATES_DIR = Path(__file__).parent / 'templates'


def list_templates():
    """List available SQL templates."""
    templates = sorted(TEMPLATES_DIR.glob('*.sql'))
    if not templates:
        print("No templates found in", TEMPLATES_DIR)
        return
    print(f"\nAvailable templates ({TEMPLATES_DIR}):")
    print(f"{'Name':<30} {'Description'}")
    print(f"{'-'*30} {'-'*50}")
    for t in templates:
        # Read first comment line as description
        with open(t) as f:
            first_line = f.readline().strip()
            desc = first_line.lstrip('- ') if first_line.startswith('--') else t.stem
        print(f"  {t.stem:<28} {desc}")
    print()


def run_template(template_name: str, start_date: str, end_date: str,
                 csv_path: str = None, limit: int = None):
    """Execute a SQL template and display results."""
    template_file = TEMPLATES_DIR / f'{template_name}.sql'
    if not template_file.exists():
        print(f"Template not found: {template_file}")
        print("Use --list to see available templates.")
        sys.exit(1)

    sql = template_file.read_text()
    sql = sql.replace('{start_date}', start_date)
    sql = sql.replace('{end_date}', end_date)

    if limit:
        sql += f"\nLIMIT {limit}"

    try:
        from google.cloud import bigquery
        client = bigquery.Client(project='nba-props-platform')
    except Exception as e:
        print(f"Could not connect to BigQuery: {e}")
        sys.exit(1)

    print(f"\nRunning: {template_name}")
    print(f"Period:  {start_date} → {end_date}")
    print(f"{'='*60}")

    try:
        query_job = client.query(sql)
        result_iter = query_job.result()
        rows = list(result_iter)
    except Exception as e:
        print(f"Query failed: {e}")
        print(f"\nSQL:\n{sql}")
        sys.exit(1)

    if not rows:
        print("  No results.")
        return

    # Get column names from first row's keys
    columns = list(rows[0].keys())

    # Display as table
    # Calculate column widths
    widths = {col: max(len(col), 6) for col in columns}
    for row in rows:
        for col in columns:
            val = row[col]
            widths[col] = max(widths[col], len(str(val)) if val is not None else 4)

    # Header
    header = '  '.join(f'{col:>{widths[col]}}' for col in columns)
    print(header)
    print('  '.join('-' * widths[col] for col in columns))

    # Rows
    for row in rows:
        vals = []
        for col in columns:
            val = row[col]
            if val is None:
                vals.append(f'{"":>{widths[col]}}')
            elif isinstance(val, float):
                vals.append(f'{val:>{widths[col]}.1f}')
            else:
                vals.append(f'{str(val):>{widths[col]}}')
        print('  '.join(vals))

    print(f"\n{len(rows)} rows returned.")

    # CSV export
    if csv_path:
        import csv
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([row[col] for col in columns])
        print(f"Exported to {csv_path}")


def main():
    parser = argparse.ArgumentParser(description='SQL Analysis Template Runner')
    parser.add_argument('--template', '-t', type=str, help='Template name (without .sql)')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--list', '-l', action='store_true', help='List available templates')
    parser.add_argument('--csv', type=str, help='Export results to CSV')
    parser.add_argument('--limit', type=int, help='Limit number of rows')
    args = parser.parse_args()

    if args.list:
        list_templates()
        return

    if not args.template:
        print("Specify --template or --list")
        sys.exit(1)

    if not args.start or not args.end:
        print("--start and --end are required")
        sys.exit(1)

    run_template(args.template, args.start, args.end, csv_path=args.csv, limit=args.limit)


if __name__ == '__main__':
    main()
