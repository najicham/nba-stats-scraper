#!/usr/bin/env python3
"""
MLB BettingPros Market ID Discovery Script
==========================================
Discovers the real market IDs for MLB player props from BettingPros API.

This script should be run when MLB season is active to discover the actual
market IDs for pitcher and batter props. The discovered IDs will be used
to update the placeholder values in bp_mlb_player_props.py.

Usage:
------
  # Discover market IDs for a specific date (must have MLB games)
  python scripts/mlb/setup/discover_mlb_market_ids.py --date 2025-06-15

  # Try a range of market IDs
  python scripts/mlb/setup/discover_mlb_market_ids.py --date 2025-06-15 --id-range 100-300

  # Verbose output
  python scripts/mlb/setup/discover_mlb_market_ids.py --date 2025-06-15 --verbose

Output:
-------
  Writes discovered market IDs to: scripts/mlb/setup/mlb_market_ids_discovered.json

Note:
-----
  This script requires:
  1. MLB season to be active (games scheduled for the date)
  2. BettingPros API to return data (may need proxy)
  3. Valid event IDs for MLB games on that date
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from scrapers.bettingpros.bp_events import BettingProsEvents
from scrapers.bettingpros.bp_player_props import BettingProsPlayerProps

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# NBA market IDs for reference (confirmed working)
NBA_MARKET_IDS = {
    156: 'points-by-player',
    157: 'rebounds-by-player',
    151: 'assists-by-player',
    162: 'threes-by-player',
    160: 'steals-by-player',
    152: 'blocks-by-player',
}

# Expected MLB market types to search for
MLB_EXPECTED_MARKETS = [
    'pitcher-strikeouts',
    'pitcher-outs',
    'pitcher-hits-allowed',
    'pitcher-earned-runs',
    'pitcher-walks',
    'batter-hits',
    'batter-home-runs',
    'batter-rbis',
    'batter-total-bases',
    'batter-runs-scored',
    'batter-stolen-bases',
    'batter-strikeouts',
]


def fetch_mlb_events(date: str) -> List[str]:
    """Fetch MLB event IDs for the given date."""
    logger.info(f"Fetching MLB events for {date}...")

    try:
        events_scraper = BettingProsEvents()
        events_opts = {
            "date": date,
            "sport": "MLB",
            "group": "capture",
            "run_id": f"discovery_{date}_{int(time.time())}"
        }

        result = events_scraper.run(events_opts)

        if result and hasattr(events_scraper, 'data') and 'events' in events_scraper.data:
            event_ids = list(events_scraper.data['events'].keys())
            logger.info(f"Found {len(event_ids)} MLB events for {date}")
            return event_ids
        else:
            logger.warning(f"No MLB events found for {date}")
            return []

    except Exception as e:
        logger.error(f"Error fetching MLB events: {e}")
        return []


def test_market_id(market_id: int, event_ids: List[str], date: str, verbose: bool = False) -> Optional[Dict]:
    """Test a single market ID to see if it returns data."""
    if not event_ids:
        return None

    # Use first 3 event IDs for testing
    test_events = event_ids[:3]

    try:
        # Build the URL manually to test
        import requests

        event_ids_str = ":".join(test_events)
        url = (
            f"https://api.bettingpros.com/v3/offers"
            f"?sport=MLB"
            f"&market_id={market_id}"
            f"&event_id={event_ids_str}"
            f"&book_id=null"
            f"&limit=10"
            f"&page=1"
        )

        if verbose:
            logger.debug(f"Testing market_id={market_id}: {url}")

        # Add headers similar to scraper
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Origin': 'https://www.bettingpros.com',
            'Referer': 'https://www.bettingpros.com/',
        }

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()

            offers = data.get('offers', [])
            markets = data.get('markets', [])

            if offers and len(offers) > 0:
                # Found data for this market ID!
                market_info = {
                    'market_id': market_id,
                    'offers_count': len(offers),
                    'markets_in_response': markets,
                    'sample_offer': offers[0] if offers else None,
                }

                # Try to determine market name from offers
                if offers:
                    first_offer = offers[0]
                    # Log the structure for analysis
                    if verbose:
                        logger.info(f"Market {market_id} response keys: {first_offer.keys()}")

                return market_info

        elif response.status_code == 400:
            if verbose:
                logger.debug(f"Market {market_id}: Invalid (400)")
        elif response.status_code == 404:
            if verbose:
                logger.debug(f"Market {market_id}: Not found (404)")
        else:
            if verbose:
                logger.warning(f"Market {market_id}: Unexpected status {response.status_code}")

    except Exception as e:
        if verbose:
            logger.error(f"Error testing market_id={market_id}: {e}")

    return None


def discover_market_ids(date: str, id_range: Tuple[int, int], verbose: bool = False) -> Dict:
    """
    Discover MLB market IDs by testing a range of IDs against the API.

    Args:
        date: Date to test (YYYY-MM-DD format)
        id_range: Tuple of (start, end) market IDs to test
        verbose: Enable verbose logging

    Returns:
        Dictionary of discovered market IDs with metadata
    """
    start_id, end_id = id_range

    # First, fetch MLB events for the date
    event_ids = fetch_mlb_events(date)

    if not event_ids:
        logger.error(f"No MLB events found for {date}. Cannot discover market IDs.")
        logger.info("Try a date when MLB games are scheduled.")
        return {}

    logger.info(f"Testing market IDs from {start_id} to {end_id}...")
    logger.info(f"Using event IDs: {event_ids[:3]}...")

    discovered = {}
    tested = 0

    for market_id in range(start_id, end_id + 1):
        tested += 1

        # Progress update every 20 IDs
        if tested % 20 == 0:
            logger.info(f"Progress: tested {tested}/{end_id - start_id + 1} IDs, found {len(discovered)} markets")

        result = test_market_id(market_id, event_ids, date, verbose)

        if result:
            logger.info(f"✓ Found active market: ID={market_id}, offers={result['offers_count']}")
            discovered[market_id] = result

        # Rate limiting - be respectful to the API
        time.sleep(0.5)

    return discovered


def save_results(discovered: Dict, date: str) -> str:
    """Save discovered market IDs to JSON file."""
    output_file = os.path.join(
        os.path.dirname(__file__),
        'mlb_market_ids_discovered.json'
    )

    output = {
        'discovery_date': date,
        'discovery_timestamp': datetime.now().isoformat(),
        'nba_reference': NBA_MARKET_IDS,
        'mlb_discovered': discovered,
        'total_found': len(discovered),
        'update_instructions': [
            "Update MLB_MARKETS in scrapers/bettingpros/bp_mlb_player_props.py",
            "Update MLB_MARKET_ID_BY_KEYWORD with the correct mappings",
            "Test each market type to confirm functionality",
        ]
    }

    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"Results saved to: {output_file}")
    return output_file


def print_summary(discovered: Dict) -> None:
    """Print a summary of discovered market IDs."""
    print("\n" + "=" * 60)
    print("MLB MARKET ID DISCOVERY SUMMARY")
    print("=" * 60)

    if not discovered:
        print("\nNo market IDs found. Possible reasons:")
        print("  - MLB season is not active")
        print("  - No games scheduled for the date")
        print("  - API may be blocking requests")
        print("  - Try with a proxy or different date")
        return

    print(f"\nFound {len(discovered)} active market IDs:\n")

    for market_id, info in sorted(discovered.items()):
        offers_count = info.get('offers_count', 0)
        markets = info.get('markets_in_response', [])
        print(f"  Market ID {market_id}:")
        print(f"    - Offers count: {offers_count}")
        print(f"    - Markets in response: {markets}")
        print()

    print("\nNext steps:")
    print("  1. Analyze the sample offers to identify market types")
    print("  2. Update MLB_MARKETS in bp_mlb_player_props.py")
    print("  3. Test each market with the MLB scraper")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Discover MLB market IDs from BettingPros API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --date 2025-06-15
  %(prog)s --date 2025-06-15 --id-range 100-300
  %(prog)s --date 2025-06-15 --verbose
        """
    )

    parser.add_argument(
        '--date',
        type=str,
        required=True,
        help='Date to test (YYYY-MM-DD format, must have MLB games)'
    )

    parser.add_argument(
        '--id-range',
        type=str,
        default='100-250',
        help='Range of market IDs to test (e.g., "100-300"). Default: 100-250'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    # Validate date format
    try:
        datetime.strptime(args.date, '%Y-%m-%d')
    except ValueError:
        logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
        sys.exit(1)

    # Parse ID range
    try:
        start, end = map(int, args.id_range.split('-'))
        if start >= end:
            raise ValueError("Start must be less than end")
    except ValueError as e:
        logger.error(f"Invalid id-range format: {args.id_range}. Use 'start-end' (e.g., '100-300')")
        sys.exit(1)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("\n" + "=" * 60)
    print("MLB BETTINGPROS MARKET ID DISCOVERY")
    print("=" * 60)
    print(f"Date: {args.date}")
    print(f"ID Range: {start} to {end}")
    print("=" * 60 + "\n")

    # Run discovery
    discovered = discover_market_ids(args.date, (start, end), args.verbose)

    # Save results
    if discovered:
        save_results(discovered, args.date)

    # Print summary
    print_summary(discovered)


if __name__ == '__main__':
    main()
