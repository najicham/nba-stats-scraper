"""Kalshi NBA Player Props Scraper.

Fetches NBA player prop markets from Kalshi's prediction market API.
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from scrapers.scraper_base import ScraperBase, ExportMode
from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
from scrapers.utils.gcs_path_builder import GCSPathBuilder

from .kalshi_auth import KalshiAuthenticator

logger = logging.getLogger(__name__)


class KalshiPlayerProps(ScraperBase, ScraperFlaskMixin):
    """Scraper for Kalshi NBA player props.

    Kalshi is a CFTC-regulated prediction market that offers NBA player props
    as binary contracts (Yes/No). Unlike traditional sportsbooks, Kalshi
    profits from transaction fees and doesn't limit winning bettors.

    Contract Pricing:
    - Prices are in cents (0-100)
    - yes_ask of 55 = 55% implied probability
    - Conversion to American odds: 55¢ = -122, 45¢ = +122
    """

    name = "kalshi_player_props"

    # API Configuration - Note: Despite "elections" in URL, this serves ALL markets including sports
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    # Series tickers for NBA player props
    PROP_SERIES = {
        "KXNBAPTS": "points",
        "KXNBAREB": "rebounds",
        "KXNBAAST": "assists",
        "KXNBA3PT": "threes",
        "KXNBABLK": "blocks",
        "KXNBASTL": "steals",
    }

    # Rate limiting - Kalshi allows 10 req/sec, we use 5 to be safe
    REQUEST_DELAY = 0.2  # 200ms between requests

    # Legacy prop type mapping (for ticker parsing)
    PROP_TYPE_MAP = {
        "PTS": "points",
        "REB": "rebounds",
        "AST": "assists",
        "3PM": "threes",
        "3PT": "threes",
        "BLK": "blocks",
        "STL": "steals",
    }

    # Exporters configuration
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path("kalshi_player_props"),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/kalshi_player_props_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    def __init__(self):
        super().__init__()
        self.auth = None
        self._session = None

    def _get_session(self) -> requests.Session:
        """Get or create requests session."""
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _make_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        max_retries: int = 3
    ) -> Dict:
        """Make authenticated request to Kalshi API.

        Args:
            method: HTTP method
            path: API path (e.g., /events)
            params: Query parameters
            max_retries: Number of retries on failure

        Returns:
            JSON response as dictionary
        """
        full_path = f"/trade-api/v2{path}"
        url = f"{self.BASE_URL}{path}"

        headers = self.auth.get_auth_headers(method, full_path)
        session = self._get_session()

        for attempt in range(max_retries):
            try:
                response = session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=30
                )

                if response.status_code == 429:
                    # Rate limited - back off
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Request failed: {e}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise

        return {}

    def validate_opts(self) -> None:
        """Validate scraper options."""
        if "date" not in self.opts:
            raise ValueError("date is required")

        # Ensure date is in YYYY-MM-DD format
        date_str = self.opts["date"]
        if date_str.upper() == "TODAY":
            self.opts["date"] = datetime.now().strftime("%Y-%m-%d")
        else:
            # Validate format
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Invalid date format: {date_str}, expected YYYY-MM-DD")

    def set_additional_opts(self) -> None:
        """Initialize authentication and any additional setup."""
        self.auth = KalshiAuthenticator()

        # Add timestamp for export path
        self.opts["timestamp"] = datetime.now().strftime("%Y%m%d_%H%M%S")

    def set_url(self) -> None:
        """Set the base URL - not used directly since we make multiple API calls."""
        self.url = self.BASE_URL

    def _fetch_nba_events(self) -> List[Dict]:
        """Fetch all NBA player prop events for the target date.

        Events are organized by prop type series (KXNBAPTS, KXNBAREB, etc.)
        Event ticker format: KXNBAPTS-26FEB02PHILAC

        Returns:
            List of event dictionaries with prop_type added
        """
        all_events = []
        target_date = self.opts["date"]

        # Parse target date for matching
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            # Format for Kalshi ticker: 26FEB02 (YY + MON + DD)
            target_ticker_date = target_dt.strftime("%y%b%d").upper()
        except ValueError:
            logger.error(f"Invalid date format: {target_date}")
            return []

        logger.info(f"Fetching NBA events for {target_date} (ticker date: {target_ticker_date})")

        # Fetch events from each prop type series
        for series_ticker, prop_type in self.PROP_SERIES.items():
            cursor = None
            page_count = 0
            max_pages = 10

            while page_count < max_pages:
                params = {
                    "series_ticker": series_ticker,
                    "status": "open",
                    "limit": 100,
                }
                if cursor:
                    params["cursor"] = cursor

                try:
                    response = self._make_request("GET", "/events", params=params)
                except Exception as e:
                    logger.warning(f"Failed to fetch events for {series_ticker}: {e}")
                    break

                events = response.get("events", [])

                # Filter events for target date
                for event in events:
                    event_ticker = event.get("event_ticker", "")

                    # Check if event ticker contains the target date
                    # Format: KXNBAPTS-26FEB02PHILAC
                    if target_ticker_date in event_ticker:
                        event["prop_type"] = prop_type
                        event["series_ticker"] = series_ticker
                        all_events.append(event)

                cursor = response.get("cursor")
                if not cursor:
                    break

                page_count += 1
                time.sleep(self.REQUEST_DELAY)

            logger.info(f"Found {len([e for e in all_events if e.get('prop_type') == prop_type])} {prop_type} events")

        logger.info(f"Total: {len(all_events)} NBA prop events for {target_date}")
        return all_events

    def _fetch_markets_for_event(self, event_ticker: str) -> List[Dict]:
        """Fetch all markets (player props) for an event.

        Args:
            event_ticker: Kalshi event ticker

        Returns:
            List of market dictionaries
        """
        all_markets = []
        cursor = None
        page_count = 0
        max_pages = 10

        while page_count < max_pages:
            params = {
                "event_ticker": event_ticker,
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor

            response = self._make_request("GET", "/markets", params=params)
            markets = response.get("markets", [])
            all_markets.extend(markets)

            cursor = response.get("cursor")
            if not cursor:
                break

            page_count += 1
            time.sleep(self.REQUEST_DELAY)

        return all_markets

    def _parse_market_ticker(self, ticker: str) -> Optional[Dict]:
        """Parse player prop information from market ticker.

        New ticker format: KXNBAPTS-26FEB02PHILAC-LACIZUBAC40-20
        - Series: KXNBAPTS
        - Date/Game: 26FEB02PHILAC
        - Player code: LACIZUBAC40
        - Line: 20 (means 20+, so line is 19.5)

        Returns:
            Dictionary with parsed info or None if not parseable
        """
        # Pattern: KXNBA{PROP}-{DATE}{GAME}-{TEAMPLAYER}-{LINE}
        parts = ticker.split("-")
        if len(parts) < 4:
            return None

        series = parts[0]  # KXNBAPTS
        line_str = parts[-1]  # 20

        try:
            # Kalshi uses 20 to mean "20+ points", so line is 19.5
            line = float(line_str) - 0.5
        except ValueError:
            return None

        # Determine prop type from series
        prop_type = self.PROP_SERIES.get(series)
        if not prop_type:
            # Try legacy parsing
            for key, ptype in self.PROP_TYPE_MAP.items():
                if key in series:
                    prop_type = ptype
                    break

        return {
            "series": series,
            "prop_type": prop_type or "unknown",
            "line_value": line,
        }

    def _extract_player_name(self, market: Dict) -> str:
        """Extract player name from market title.

        Title format: "Ivica Zubac: 20+ points"

        Args:
            market: Market dictionary from API

        Returns:
            Player name string
        """
        title = market.get("title", "")

        # Pattern: "{Player Name}: {X}+ {stat}"
        # e.g., "Ivica Zubac: 20+ points"
        name_pattern = r"^([A-Za-z\s\.\-']+):\s*\d+"
        match = re.match(name_pattern, title)

        if match:
            return match.group(1).strip()

        # Try yes_sub_title: "Ivica Zubac: 25+"
        yes_sub = market.get("yes_sub_title", "")
        match = re.match(name_pattern, yes_sub)
        if match:
            return match.group(1).strip()

        # Try rules_primary which contains full name
        rules = market.get("rules_primary", "")
        # Pattern: "If {Player Name} records..."
        rules_match = re.search(r"If\s+([A-Za-z\s\.\-']+)\s+records", rules)
        if rules_match:
            return rules_match.group(1).strip()

        return "Unknown"

    def _normalize_player_name(self, name: str) -> str:
        """Normalize player name to player_lookup format.

        Args:
            name: Raw player name

        Returns:
            Normalized player_lookup string
        """
        # Remove special characters except letters
        normalized = re.sub(r"[^a-zA-Z]", "", name.lower())
        return normalized

    def _calculate_liquidity_score(self, market: Dict) -> str:
        """Calculate liquidity score based on orderbook depth.

        Args:
            market: Market dictionary

        Returns:
            "HIGH", "MEDIUM", or "LOW"
        """
        volume = market.get("volume", 0)
        open_interest = market.get("open_interest", 0)

        total = volume + open_interest

        if total >= 1000:
            return "HIGH"
        elif total >= 100:
            return "MEDIUM"
        else:
            return "LOW"

    def _calculate_liquidity_score_from_value(self, liquidity: int) -> str:
        """Calculate liquidity score from Kalshi's liquidity value.

        Kalshi provides liquidity in cents (e.g., 358441 = $3,584.41)

        Args:
            liquidity: Liquidity value in cents

        Returns:
            "HIGH", "MEDIUM", or "LOW"
        """
        if liquidity is None:
            return "LOW"

        # Convert cents to dollars
        liquidity_dollars = liquidity / 100

        if liquidity_dollars >= 5000:
            return "HIGH"
        elif liquidity_dollars >= 500:
            return "MEDIUM"
        else:
            return "LOW"

    def _cents_to_american_odds(self, cents: int) -> int:
        """Convert Kalshi cents (0-100) to American odds.

        Args:
            cents: Contract price in cents

        Returns:
            American odds (e.g., -150, +150)
        """
        if cents is None or cents <= 0 or cents >= 100:
            return 0

        if cents >= 50:
            return int(-100 * cents / (100 - cents))
        else:
            return int(100 * (100 - cents) / cents)

    def _transform_market(self, market: Dict, event: Dict) -> Optional[Dict]:
        """Transform a Kalshi market into our schema.

        Args:
            market: Raw market from API
            event: Parent event dictionary

        Returns:
            Transformed prop dictionary or None if invalid
        """
        ticker = market.get("ticker", "")

        # Get line value from floor_strike (more reliable than parsing ticker)
        line_value = market.get("floor_strike")
        if line_value is None:
            parsed = self._parse_market_ticker(ticker)
            if parsed:
                line_value = parsed.get("line_value")
            else:
                return None

        player_name = self._extract_player_name(market)
        if player_name == "Unknown":
            logger.debug(f"Could not extract player name from market: {ticker}")
            return None

        # Get prop type from event (more reliable)
        prop_type = event.get("prop_type", "unknown")

        # Extract team codes from event ticker
        # Format: KXNBAPTS-26FEB02PHILAC (PHI at LAC)
        event_ticker = event.get("event_ticker", "")
        # Last 6 chars are usually team codes: PHILAC -> PHI, LAC
        teams_str = event_ticker[-6:] if len(event_ticker) >= 6 else ""
        away_team = teams_str[:3] if len(teams_str) == 6 else None
        home_team = teams_str[3:] if len(teams_str) == 6 else None

        # Get series ticker from event
        series_ticker = event.get("series_ticker", "")

        # Get pricing
        yes_bid = market.get("yes_bid")
        yes_ask = market.get("yes_ask")
        no_bid = market.get("no_bid")
        no_ask = market.get("no_ask")

        # Get liquidity (Kalshi provides this directly now)
        liquidity = market.get("liquidity", 0)

        return {
            "game_date": self.opts["date"],
            "series_ticker": series_ticker,
            "event_ticker": event_ticker,
            "market_ticker": ticker,
            "prop_type": prop_type,
            "kalshi_player_name": player_name,
            "player_lookup": self._normalize_player_name(player_name),
            "player_team": None,  # Not always available from Kalshi
            "home_team": home_team,
            "away_team": away_team,
            "game_id": None,  # Would need to match with NBA schedule
            "line_value": float(line_value),
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "implied_over_prob": yes_ask / 100.0 if yes_ask else None,
            "implied_under_prob": no_ask / 100.0 if no_ask else None,
            "equivalent_over_odds": self._cents_to_american_odds(yes_ask),
            "equivalent_under_odds": self._cents_to_american_odds(no_ask),
            "yes_bid_size": None,  # Would need orderbook call
            "yes_ask_size": None,
            "no_bid_size": None,
            "no_ask_size": None,
            "total_volume": market.get("volume"),
            "open_interest": market.get("open_interest"),
            "liquidity_score": self._calculate_liquidity_score_from_value(liquidity),
            "market_status": market.get("status", "unknown"),
            "can_close_early": market.get("can_close_early"),
            "close_time": market.get("close_time"),
            "has_team_issues": True,  # Default, will be validated later
            "validated_team": None,
            "validation_confidence": None,
            "validation_method": None,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def download_and_decode(self) -> Dict:
        """Fetch all NBA player props for target date.

        Returns:
            Dictionary with props list and metadata
        """
        all_props = []
        events_processed = 0
        markets_found = 0

        try:
            # Fetch all events for the date
            events = self._fetch_nba_events()

            for event in events:
                event_ticker = event.get("event_ticker", "")
                logger.info(f"Processing event: {event_ticker}")

                # Fetch markets for this event
                markets = self._fetch_markets_for_event(event_ticker)
                markets_found += len(markets)

                # Transform each market
                for market in markets:
                    prop = self._transform_market(market, event)
                    if prop:
                        all_props.append(prop)

                events_processed += 1
                time.sleep(self.REQUEST_DELAY)

            logger.info(
                f"Completed: {events_processed} events, "
                f"{markets_found} markets, {len(all_props)} player props"
            )

        except Exception as e:
            logger.error(f"Error fetching Kalshi props: {e}")
            raise

        self.download_data = {
            "date": self.opts["date"],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "events_processed": events_processed,
            "markets_found": markets_found,
            "props_count": len(all_props),
            "props": all_props,
        }

        return self.download_data

    def validate_download_data(self) -> None:
        """Validate the downloaded data."""
        if not self.download_data:
            raise ValueError("No data downloaded")

        props = self.download_data.get("props", [])

        # Log if no props found (might be normal for some dates)
        if len(props) == 0:
            logger.warning(f"No player props found for {self.opts['date']}")
            # Don't raise - might be legitimate (no games, early in day, etc.)

        # Validate prop structure
        required_fields = ["game_date", "market_ticker", "player_lookup", "line_value"]
        for prop in props[:10]:  # Spot check first 10
            for field in required_fields:
                if field not in prop:
                    raise ValueError(f"Missing required field: {field}")

    def transform_data(self) -> Dict:
        """Transform data - already done in download_and_decode."""
        self.data = self.download_data
        return self.data

    def get_scraper_stats(self) -> Dict[str, Any]:
        """Return scraper statistics."""
        data = self.download_data or {}
        props = data.get("props", [])

        # Count by prop type
        prop_types = {}
        for prop in props:
            pt = prop.get("prop_type", "unknown")
            prop_types[pt] = prop_types.get(pt, 0) + 1

        # Count by liquidity
        liquidity = {}
        for prop in props:
            liq = prop.get("liquidity_score", "unknown")
            liquidity[liq] = liquidity.get(liq, 0) + 1

        return {
            "date": self.opts.get("date"),
            "events_processed": data.get("events_processed", 0),
            "markets_found": data.get("markets_found", 0),
            "props_count": len(props),
            "prop_types": prop_types,
            "liquidity_distribution": liquidity,
        }


# Flask app for Cloud Run
create_app = convert_existing_flask_scraper(KalshiPlayerProps)

if __name__ == "__main__":
    # CLI mode
    main = KalshiPlayerProps.create_cli_and_flask_main()
    main()
