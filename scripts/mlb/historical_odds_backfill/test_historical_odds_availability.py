#!/usr/bin/env python3
"""
Test Historical Odds Availability

Tests if historical betting lines are available from The Odds API
for our MLB prediction dates.

This is Phase 2 of the hit rate analysis - determining if backfill is feasible.

Usage:
    python scripts/mlb/historical_odds_backfill/test_historical_odds_availability.py

Requirements:
    - ODDS_API_KEY environment variable
    - Sample dates from predictions table
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any
import requests

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from google.cloud import bigquery

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = 'nba-props-platform'
ODDS_API_KEY = os.environ.get('ODDS_API_KEY')
SPORT = 'baseball_mlb'

# Sample dates to test (spread across seasons)
TEST_DATES = [
    '2024-04-15',  # Early 2024 season
    '2024-06-20',  # Mid 2024 season
    '2025-07-20',  # Mid 2025 season
]


class HistoricalOddsAvailabilityTester:
    """Test if historical odds are available for our prediction dates."""

    def __init__(self):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.api_key = ODDS_API_KEY

        if not self.api_key:
            raise ValueError("ODDS_API_KEY environment variable not set")

    def get_games_for_date(self, game_date: str) -> List[Dict[str, Any]]:
        """Get games from our schedule for a specific date."""
        query = f"""
        SELECT
            game_pk,
            game_date,
            home_team_abbr,
            away_team_abbr
        FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
        WHERE game_date = '{game_date}'
        ORDER BY game_pk
        """

        results = self.bq_client.query(query).result()
        return [dict(row) for row in results]

    def get_predictions_for_date(self, game_date: str) -> List[Dict[str, Any]]:
        """Get our predictions for a specific date."""
        query = f"""
        SELECT
            pitcher_lookup,
            pitcher_name,
            team_abbr,
            opponent_team_abbr,
            predicted_strikeouts,
            confidence
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
        ORDER BY pitcher_lookup
        """

        results = self.bq_client.query(query).result()
        return [dict(row) for row in results]

    def test_historical_events_endpoint(self, game_date: str) -> Dict[str, Any]:
        """
        Test if we can get historical events (game IDs) for a date.

        Endpoint: GET /v4/historical/sports/{sport}/events
        """
        # The Odds API historical endpoint requires ISO timestamp
        # We want odds from ~2 hours before game time
        # For testing, use 6 PM UTC on game date (typically afternoon ET)
        date_obj = datetime.strptime(game_date, '%Y-%m-%d')
        snapshot_time = date_obj.replace(hour=18, minute=0, second=0, tzinfo=timezone.utc)
        snapshot_iso = snapshot_time.strftime('%Y-%m-%dT%H:%M:%SZ')

        url = f"https://api.the-odds-api.com/v4/historical/sports/{SPORT}/events"
        params = {
            'apiKey': self.api_key,
            'date': snapshot_iso,
        }

        logger.info(f"Testing historical events endpoint for {game_date}")
        logger.info(f"  URL: {url}")
        logger.info(f"  Snapshot: {snapshot_iso}")

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            events = data.get('data', [])

            logger.info(f"  ✅ Success: Found {len(events)} events")
            logger.info(f"  Requests remaining: {response.headers.get('x-requests-remaining', 'unknown')}")

            return {
                'success': True,
                'events_found': len(events),
                'events': events,
                'snapshot_time': snapshot_iso,
                'requests_remaining': response.headers.get('x-requests-remaining')
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"  ❌ HTTP Error: {e}")
            logger.error(f"  Response: {e.response.text if e.response else 'No response'}")
            return {
                'success': False,
                'error': str(e),
                'response_text': e.response.text if e.response else None
            }
        except Exception as e:
            logger.error(f"  ❌ Error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def test_historical_odds_endpoint(
        self,
        event_id: str,
        game_date: str
    ) -> Dict[str, Any]:
        """
        Test if we can get historical pitcher strikeout lines for an event.

        Endpoint: GET /v4/historical/sports/{sport}/events/{eventId}/odds
        """
        # Snapshot time: 2 hours before typical first pitch (7 PM ET)
        date_obj = datetime.strptime(game_date, '%Y-%m-%d')
        snapshot_time = date_obj.replace(hour=22, minute=0, second=0, tzinfo=timezone.utc)  # 5 PM ET
        snapshot_iso = snapshot_time.strftime('%Y-%m-%dT%H:%M:%SZ')

        url = f"https://api.the-odds-api.com/v4/historical/sports/{SPORT}/events/{event_id}/odds"
        params = {
            'apiKey': self.api_key,
            'date': snapshot_iso,
            'markets': 'pitcher_strikeouts',
            'regions': 'us',
            'bookmakers': 'draftkings,fanduel',
            'oddsFormat': 'american',
        }

        logger.info(f"Testing historical odds endpoint for event {event_id}")
        logger.info(f"  Snapshot: {snapshot_iso}")

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            bookmakers = data.get('data', {}).get('bookmakers', [])

            # Count pitcher strikeout markets
            pitcher_lines_found = 0
            for bookmaker in bookmakers:
                for market in bookmaker.get('markets', []):
                    if market.get('key') == 'pitcher_strikeouts':
                        pitcher_lines_found += len(market.get('outcomes', []))

            logger.info(f"  ✅ Success: Found {len(bookmakers)} bookmakers, {pitcher_lines_found} pitcher lines")

            return {
                'success': True,
                'event_id': event_id,
                'bookmakers_found': len(bookmakers),
                'pitcher_lines_found': pitcher_lines_found,
                'data': data,
                'requests_remaining': response.headers.get('x-requests-remaining')
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"  ❌ HTTP Error: {e}")
            return {
                'success': False,
                'error': str(e),
                'response_text': e.response.text if e.response else None
            }
        except Exception as e:
            logger.error(f"  ❌ Error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def run_test(self) -> Dict[str, Any]:
        """Run full availability test."""
        logger.info("=" * 80)
        logger.info("HISTORICAL ODDS AVAILABILITY TEST")
        logger.info("=" * 80)
        logger.info("")

        results = {
            'test_dates': TEST_DATES,
            'date_results': [],
            'summary': {
                'total_dates_tested': 0,
                'dates_with_events': 0,
                'dates_with_odds': 0,
                'total_predictions': 0,
                'total_events_found': 0,
                'total_pitcher_lines_found': 0,
                'api_requests_used': 0,
            }
        }

        for game_date in TEST_DATES:
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Testing Date: {game_date}")
            logger.info('=' * 80)

            # Get our data for this date
            games = self.get_games_for_date(game_date)
            predictions = self.get_predictions_for_date(game_date)

            logger.info(f"Our data for {game_date}:")
            logger.info(f"  Games scheduled: {len(games)}")
            logger.info(f"  Predictions made: {len(predictions)}")

            date_result = {
                'game_date': game_date,
                'games_scheduled': len(games),
                'predictions_made': len(predictions),
                'events_test': None,
                'sample_odds_test': None,
            }

            # Test 1: Can we get historical events?
            events_result = self.test_historical_events_endpoint(game_date)
            date_result['events_test'] = events_result
            results['summary']['api_requests_used'] += 1

            if events_result['success']:
                results['summary']['dates_with_events'] += 1
                results['summary']['total_events_found'] += events_result['events_found']

                # Test 2: Can we get odds for one sample event?
                if events_result['events']:
                    sample_event = events_result['events'][0]
                    event_id = sample_event.get('id')

                    logger.info(f"\nTesting sample event: {event_id}")
                    odds_result = self.test_historical_odds_endpoint(event_id, game_date)
                    date_result['sample_odds_test'] = odds_result
                    results['summary']['api_requests_used'] += 1

                    if odds_result['success']:
                        results['summary']['dates_with_odds'] += 1
                        results['summary']['total_pitcher_lines_found'] += odds_result['pitcher_lines_found']

            results['date_results'].append(date_result)
            results['summary']['total_dates_tested'] += 1
            results['summary']['total_predictions'] += len(predictions)

        # Final summary
        logger.info(f"\n{'=' * 80}")
        logger.info("TEST SUMMARY")
        logger.info('=' * 80)
        logger.info(f"Dates tested: {results['summary']['total_dates_tested']}")
        logger.info(f"Dates with events available: {results['summary']['dates_with_events']}")
        logger.info(f"Dates with pitcher odds available: {results['summary']['dates_with_odds']}")
        logger.info(f"Total predictions: {results['summary']['total_predictions']}")
        logger.info(f"Total events found: {results['summary']['total_events_found']}")
        logger.info(f"Total pitcher lines found (sample): {results['summary']['total_pitcher_lines_found']}")
        logger.info(f"API requests used: {results['summary']['api_requests_used']}")

        # Verdict
        logger.info(f"\n{'=' * 80}")
        logger.info("VERDICT")
        logger.info('=' * 80)

        if results['summary']['dates_with_odds'] == results['summary']['total_dates_tested']:
            logger.info("✅ EXCELLENT: Historical odds available for all test dates")
            logger.info("   Recommendation: Proceed with full backfill")
            verdict = "PROCEED_FULL_BACKFILL"
        elif results['summary']['dates_with_odds'] > 0:
            coverage_pct = results['summary']['dates_with_odds'] / results['summary']['total_dates_tested'] * 100
            logger.info(f"🟡 PARTIAL: Historical odds available for {coverage_pct:.0f}% of test dates")
            logger.info("   Recommendation: Proceed with partial backfill, note limitations")
            verdict = "PROCEED_PARTIAL_BACKFILL"
        else:
            logger.info("❌ UNAVAILABLE: No historical odds available")
            logger.info("   Recommendation: Skip historical backfill, go prospective only")
            verdict = "SKIP_BACKFILL"

        results['verdict'] = verdict

        # Save results
        output_file = 'docs/08-projects/current/mlb-pitcher-strikeouts/HISTORICAL-ODDS-TEST-RESULTS.json'
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {output_file}")

        return results


def main():
    """Main entry point."""
    try:
        tester = HistoricalOddsAvailabilityTester()
        results = tester.run_test()

        # Exit code based on verdict
        if results['verdict'] == 'PROCEED_FULL_BACKFILL':
            sys.exit(0)
        elif results['verdict'] == 'PROCEED_PARTIAL_BACKFILL':
            sys.exit(1)
        else:
            sys.exit(2)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(3)


if __name__ == '__main__':
    main()
