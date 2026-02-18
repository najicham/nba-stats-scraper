#!/usr/bin/env python3
"""
Backfill NBA.com injury reports from historical PDFs directly to BigQuery.

Downloads PDFs from ak-static.cms.nba.com, parses with pdfplumber + InjuryReportParser,
transforms with Phase 2 processor logic, and loads directly to BigQuery.

Usage:
    # Dry run — show what would be downloaded
    PYTHONPATH=. python bin/backfill_injury_reports.py --start-date 2025-11-01 --end-date 2025-12-31 --dry-run

    # Full backfill for Nov-Dec
    PYTHONPATH=. python bin/backfill_injury_reports.py --start-date 2025-11-01 --end-date 2025-12-31

    # Single date
    PYTHONPATH=. python bin/backfill_injury_reports.py --start-date 2025-11-20 --end-date 2025-11-20

    # Custom hour (default: 05PM — latest before evening games)
    PYTHONPATH=. python bin/backfill_injury_reports.py --start-date 2025-11-01 --end-date 2025-12-31 --hour 03PM
"""

import argparse
import io
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import requests
import pdfplumber
from google.cloud import bigquery

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scrapers.nbacom.injury_parser import InjuryReportParser

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# URL patterns
OLD_FORMAT_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{hour}.pdf"
NEW_FORMAT_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{hour}_{minute}.pdf"
FORMAT_CUTOFF = date(2025, 12, 23)

PROJECT_ID = 'nba-props-platform'
TABLE_ID = 'nba_raw.nbac_injury_report'


def build_url(game_date: date, hour_str: str) -> str:
    """Build the correct URL based on date format cutoff."""
    formatted_date = game_date.strftime('%Y-%m-%d')
    if game_date >= FORMAT_CUTOFF:
        # New format includes minutes: e.g., 05_00PM
        hour_num = hour_str[:2]
        period = hour_str[2:]
        return NEW_FORMAT_URL.format(date=formatted_date, hour=hour_num, minute=f"00{period}")
    else:
        # Old format: e.g., 05PM
        return OLD_FORMAT_URL.format(date=formatted_date, hour=hour_str)


def download_pdf(url: str) -> Optional[bytes]:
    """Download PDF from NBA.com CDN."""
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200 and b"%PDF" in resp.content[:1024]:
            return resp.content
        elif resp.status_code == 404:
            return None
        else:
            logger.warning(f"Unexpected response {resp.status_code} for {url}")
            return None
    except requests.RequestException as e:
        logger.error(f"Download error for {url}: {e}")
        return None


def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Extract text from PDF using pdfplumber."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=True) as tmp:
        tmp.write(pdf_content)
        tmp.flush()

        with pdfplumber.open(tmp.name) as pdf:
            text_parts = []
            for page in pdf.pages:
                text = page.extract_text(
                    x_tolerance=2, y_tolerance=2,
                    x_density=7.25, y_density=13
                )
                if text:
                    text_parts.append(text)
            return '\n'.join(text_parts)


def normalize_player_name(player_name: str) -> tuple:
    """Parse 'Last, First' format and create normalized lookup."""
    if not player_name:
        return ("", "")
    parts = player_name.split(',')
    if len(parts) == 2:
        last_name = parts[0].strip()
        first_name = parts[1].strip()
        full_name = f"{first_name} {last_name}"
    else:
        full_name = player_name.strip()
    player_lookup = full_name.lower()
    for char in [' ', "'", '.', '-', ',', 'jr', 'sr', 'ii', 'iii', 'iv']:
        player_lookup = player_lookup.replace(char, '')
    return (full_name, player_lookup)


def parse_matchup(matchup: str, game_date_str: str) -> Dict:
    """Parse matchup string like 'MIA@DET'."""
    try:
        parts = matchup.split('@')
        if len(parts) != 2:
            return {'away_team': '', 'home_team': '', 'game_id': ''}
        away_team = parts[0].strip()
        home_team = parts[1].strip()
        date_obj = datetime.strptime(game_date_str, '%m/%d/%Y')
        date_str = date_obj.strftime('%Y%m%d')
        game_id = f"{date_str}_{away_team}_{home_team}"
        return {'away_team': away_team, 'home_team': home_team, 'game_id': game_id}
    except Exception as e:
        logger.error(f"Error parsing matchup '{matchup}': {e}")
        return {'away_team': '', 'home_team': '', 'game_id': ''}


def categorize_reason(reason: str) -> str:
    """Categorize the reason for absence."""
    if not reason:
        return 'unknown'
    reason_lower = reason.lower()
    if 'injury/illness' in reason_lower:
        return 'injury'
    elif 'g league' in reason_lower:
        return 'g_league'
    elif 'suspension' in reason_lower:
        return 'suspension'
    elif 'health and safety' in reason_lower or 'protocol' in reason_lower:
        return 'health_safety_protocol'
    elif 'rest' in reason_lower:
        return 'rest'
    elif 'personal' in reason_lower:
        return 'personal'
    return 'other'


def get_nba_season(d: date) -> str:
    """Determine NBA season from date."""
    if d.month >= 10:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    return f"{d.year - 1}-{str(d.year)[2:]}"


def transform_records(records: List[Dict], report_date: date, hour_str: str) -> List[Dict]:
    """Transform parsed injury records to BigQuery rows."""
    rows = []
    hour_24 = int(hour_str[:2])
    if 'PM' in hour_str and hour_24 != 12:
        hour_24 += 12
    elif 'AM' in hour_str and hour_24 == 12:
        hour_24 = 0

    season = get_nba_season(report_date)

    for record in records:
        try:
            player_full_name, player_lookup = normalize_player_name(record['player'])
            matchup_info = parse_matchup(record['matchup'], record['date'])

            game_time_raw = record.get('gametime', '')
            game_time = game_time_raw.replace('(ET)', '').replace('(EST)', '').strip() if game_time_raw else None

            reason_category = categorize_reason(record.get('reason', ''))

            try:
                game_date_iso = datetime.strptime(record['date'], '%m/%d/%Y').date().isoformat()
            except (ValueError, KeyError):
                game_date_iso = report_date.isoformat()

            row = {
                'report_date': report_date.isoformat(),
                'report_hour': hour_24,
                'season': season,
                'game_date': game_date_iso,
                'game_time': game_time,
                'game_id': matchup_info['game_id'],
                'matchup': record.get('matchup', ''),
                'away_team': matchup_info['away_team'],
                'home_team': matchup_info['home_team'],
                'team': record.get('team', ''),
                'player_name_original': record.get('player', ''),
                'player_full_name': player_full_name,
                'player_lookup': player_lookup,
                'injury_status': record.get('status', '').lower(),
                'reason': record.get('reason', ''),
                'reason_category': reason_category,
                'confidence_score': record.get('confidence', 1.0),
                'overall_report_confidence': 0.95,
                'scrape_time': f"backfill_{datetime.utcnow().strftime('%H-%M-%S')}",
                'run_id': f"backfill_{report_date.isoformat()}_{hour_str}",
                'source_file_path': f"backfill/injury-report/{report_date.isoformat()}/{hour_str}",
                'processed_at': datetime.utcnow().isoformat()
            }
            rows.append(row)
        except Exception as e:
            logger.error(f"Error transforming record: {e} — record: {record}")
    return rows


def load_to_bigquery(rows: List[Dict], client: bigquery.Client) -> int:
    """Load rows to BigQuery."""
    if not rows:
        return 0

    table_ref = client.get_table(TABLE_ID)
    job_config = bigquery.LoadJobConfig(
        schema=table_ref.schema,
        autodetect=False,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ignore_unknown_values=True
    )

    load_job = client.load_table_from_json(rows, TABLE_ID, job_config=job_config)
    load_job.result(timeout=60)

    if load_job.errors:
        logger.error(f"BigQuery load errors: {load_job.errors[:3]}")
        return 0
    return len(rows)


def check_existing_data(client: bigquery.Client, game_date: date) -> int:
    """Check how many records already exist for a date."""
    query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.{TABLE_ID}`
    WHERE report_date = '{game_date.isoformat()}'
    """
    result = list(client.query(query).result())
    return result[0].cnt if result else 0


def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com injury reports to BigQuery')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--hour', default='05PM', help='Hour to scrape (e.g., 05PM, 03PM). Default: 05PM')
    parser.add_argument('--dry-run', action='store_true', help='Preview without downloading or loading')
    parser.add_argument('--skip-existing', action='store_true', default=True, help='Skip dates with existing BQ data')
    parser.add_argument('--force', action='store_true', help='Override skip-existing')
    parser.add_argument('--fallback-hours', nargs='*', default=['03PM', '04PM', '06PM', '01PM'],
                        help='Fallback hours if primary returns 0 records')
    args = parser.parse_args()

    start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    hour_str = args.hour

    logger.info(f"Backfill injury reports: {start} to {end}, hour={hour_str}")
    logger.info(f"Dry run: {args.dry_run}")

    if not args.dry_run:
        bq_client = bigquery.Client(project=PROJECT_ID)
    else:
        bq_client = None

    injury_parser = InjuryReportParser()

    total_dates = 0
    total_records = 0
    skipped_existing = 0
    skipped_no_data = 0
    failed_dates = []

    current = start
    while current <= end:
        total_dates += 1
        date_str = current.strftime('%Y-%m-%d')

        # Check existing data
        if not args.force and not args.dry_run:
            existing = check_existing_data(bq_client, current)
            if existing > 0:
                logger.info(f"  {date_str}: {existing} records already exist, skipping")
                skipped_existing += 1
                current += timedelta(days=1)
                continue

        # Build URL and download
        url = build_url(current, hour_str)

        if args.dry_run:
            logger.info(f"  {date_str}: Would download {url}")
            current += timedelta(days=1)
            continue

        logger.info(f"  {date_str}: Downloading {url}")
        pdf_content = download_pdf(url)

        if not pdf_content:
            logger.warning(f"  {date_str}: No PDF available at {hour_str}")
            failed_dates.append(date_str)
            current += timedelta(days=1)
            time.sleep(0.5)
            continue

        # Extract text
        text = extract_text_from_pdf(pdf_content)
        if not text or len(text) < 100:
            logger.warning(f"  {date_str}: PDF too short or empty ({len(text) if text else 0} chars)")
            skipped_no_data += 1
            current += timedelta(days=1)
            time.sleep(0.5)
            continue

        # Parse
        injury_parser_instance = InjuryReportParser()
        records = injury_parser_instance.parse_text_content(text)

        # Try fallback hours if primary returns 0 records
        if len(records) == 0 and args.fallback_hours:
            for fallback_hour in args.fallback_hours:
                if fallback_hour == hour_str:
                    continue
                fallback_url = build_url(current, fallback_hour)
                logger.info(f"  {date_str}: Trying fallback hour {fallback_hour}")
                fb_content = download_pdf(fallback_url)
                if fb_content:
                    fb_text = extract_text_from_pdf(fb_content)
                    if fb_text and len(fb_text) >= 100:
                        fb_parser = InjuryReportParser()
                        records = fb_parser.parse_text_content(fb_text)
                        if len(records) > 0:
                            hour_str_used = fallback_hour
                            logger.info(f"  {date_str}: Fallback {fallback_hour} found {len(records)} records")
                            break
                time.sleep(0.3)
            else:
                hour_str_used = hour_str
        else:
            hour_str_used = hour_str

        if len(records) == 0:
            logger.warning(f"  {date_str}: 0 records parsed from PDF")
            skipped_no_data += 1
            current += timedelta(days=1)
            time.sleep(0.5)
            continue

        # Transform
        rows = transform_records(records, current, hour_str_used)

        # Load to BigQuery
        loaded = load_to_bigquery(rows, bq_client)
        total_records += loaded
        logger.info(f"  {date_str}: {loaded} records loaded (parsed: {len(records)})")

        current += timedelta(days=1)
        time.sleep(0.5)  # Rate limit

    # Summary
    logger.info("=" * 60)
    logger.info("BACKFILL SUMMARY")
    logger.info(f"  Date range: {start} to {end} ({total_dates} dates)")
    logger.info(f"  Total records loaded: {total_records}")
    logger.info(f"  Skipped (existing): {skipped_existing}")
    logger.info(f"  Skipped (no data): {skipped_no_data}")
    logger.info(f"  Failed dates: {len(failed_dates)}")
    if failed_dates:
        logger.info(f"  Failed: {', '.join(failed_dates)}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
