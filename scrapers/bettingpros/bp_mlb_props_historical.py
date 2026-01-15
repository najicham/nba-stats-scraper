# scrapers/bettingpros/bp_mlb_props_historical.py
"""
BettingPros MLB Historical Props Scraper                    v1 - 2026-01-14
---------------------------------------------------------------------------
Fetches historical MLB player prop betting data with ACTUAL OUTCOMES from
the BettingPros API. Supports all 11 MLB prop markets (2 pitcher, 9 batter).

Key Features:
- Historical date queries (2022+ available)
- Actual outcomes included (scoring.actual)
- Performance trends included (last_5, last_10, season, etc.)
- BettingPros projections included
- Pagination handling for high-volume batter props

API Endpoint: https://api.bettingpros.com/v3/props?sport=MLB&market_id=XXX&date=YYYY-MM-DD

Market IDs:
  Pitcher: 285 (strikeouts), 290 (ERA allowed)
  Batter: 287 (hits), 288 (runs), 289 (RBIs), 291 (doubles), 292 (triples),
          293 (total bases), 294 (stolen bases), 295 (singles), 299 (home runs)

Usage Examples:
  # Single market/date (pitcher strikeouts)
  python scrapers/bettingpros/bp_mlb_props_historical.py \\
      --market_id 285 --date 2024-06-15 --group dev

  # Using market name
  python scrapers/bettingpros/bp_mlb_props_historical.py \\
      --market_type pitcher-strikeouts --date 2024-06-15 --group dev

  # Batter props (high volume, pagination)
  python scrapers/bettingpros/bp_mlb_props_historical.py \\
      --market_type batter-hits --date 2024-06-15 --group gcs

  # Production GCS export
  python scrapers/bettingpros/bp_mlb_props_historical.py \\
      --market_id 285 --date 2024-06-15 --group gcs

  # Flask service mode
  python scrapers/bettingpros/bp_mlb_props_historical.py --serve --debug
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

# Support both module execution and direct execution
try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_error, notify_warning, notify_info

logger = logging.getLogger("scraper_base")

# =============================================================================
# MLB Market Definitions
# =============================================================================

MLB_MARKETS = {
    # Pitcher Props (2)
    285: 'pitcher-strikeouts',
    290: 'pitcher-earned-runs-allowed',
    # Batter Props (9)
    287: 'batter-hits',
    288: 'batter-runs',
    289: 'batter-rbis',
    291: 'batter-doubles',
    292: 'batter-triples',
    293: 'batter-total-bases',
    294: 'batter-stolen-bases',
    295: 'batter-singles',
    299: 'batter-home-runs',
}

MLB_MARKET_BY_NAME = {name: id for id, name in MLB_MARKETS.items()}

# Aliases for convenience
MLB_MARKET_ALIASES = {
    'strikeouts': 285,
    'pitcher_strikeouts': 285,
    'era': 290,
    'pitcher_era': 290,
    'earned_runs': 290,
    'hits': 287,
    'batter_hits': 287,
    'runs': 288,
    'batter_runs': 288,
    'rbis': 289,
    'batter_rbis': 289,
    'doubles': 291,
    'batter_doubles': 291,
    'triples': 292,
    'batter_triples': 292,
    'total_bases': 293,
    'batter_total_bases': 293,
    'stolen_bases': 294,
    'batter_stolen_bases': 294,
    'steals': 294,
    'singles': 295,
    'batter_singles': 295,
    'home_runs': 299,
    'homeruns': 299,
    'batter_home_runs': 299,
}

# Merge all lookups
MLB_MARKET_LOOKUP = {**MLB_MARKET_BY_NAME, **MLB_MARKET_ALIASES}

# Market categories
PITCHER_MARKETS = [285, 290]
BATTER_MARKETS = [287, 288, 289, 291, 292, 293, 294, 295, 299]

# Sportsbook mappings
BOOKS = {
    0: "BettingPros Consensus",
    10: "FanDuel",
    12: "DraftKings",
    13: "Caesars",
    14: "PointsBet",
    15: "SugarHouse",
    18: "BetRivers",
    19: "BetMGM",
    24: "bet365",
    27: "PartyCasino",
    33: "Hard Rock",
    36: "Betfred",
    37: "Borgata",
    38: "Unibet",
    39: "WynnBET",
    45: "BetParx",
    49: "ESPN BET",
    60: "Fliff",
    63: "Underdog",
    68: "PrizePicks",
    73: "Sleeper",
}


class BettingProsMLBHistoricalProps(ScraperBase, ScraperFlaskMixin):
    """
    BettingPros MLB Historical Props Scraper.

    Fetches historical player prop data with actual outcomes for any market/date.
    Handles pagination automatically to get all props for a day.

    Required opts:
        date: Date in YYYY-MM-DD format

    Required (one of):
        market_id: Numeric market ID (e.g., 285)
        market_type: Market name (e.g., 'pitcher-strikeouts')

    Optional opts:
        limit: Results per page (default: 50, max: 50)
        include_events: Include event details (default: True)
    """

    scraper_name = "bp_mlb_props_historical"

    required_params = ["date"]
    optional_params = {
        "market_id": None,
        "market_type": None,
        "limit": 50,
        "include_events": True,
        "page": None,  # For manual pagination control
    }

    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled = False  # API is direct, no proxy needed
    browser_enabled = False

    # Timeout settings
    timeout_http = 60  # 60 seconds for potentially slow responses

    # Rate limiting
    RATE_LIMIT_DELAY = 0.3  # 300ms between requests

    # Retry settings
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 5  # seconds: 5, 10, 20

    # API Configuration
    BASE_URL = "https://api.bettingpros.com/v3/props"

    # Required headers for FantasyPros/BettingPros API
    FANTASYPROS_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Origin': 'https://www.fantasypros.com',
        'Referer': 'https://www.fantasypros.com/',
    }

    # GCS path configuration
    GCS_PATH_KEY = "bettingpros_mlb_historical_props"

    exporters = [
        # ========== PRODUCTION GCS ==========
        {
            "type": "gcs",
            "key": "bettingpros-mlb/historical/%(market_name)s/%(date)s/props.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # ========== DEVELOPMENT FILES ==========
        {
            "type": "file",
            "filename": "/tmp/bp_mlb_props_%(market_id)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/bp_mlb_props_%(market_id)s_%(date)s_raw.json",
            "export_mode": ExportMode.RAW,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # ========== CAPTURE GROUP ==========
        {
            "type": "file",
            "filename": "/tmp/bp_mlb_hist_raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/bp_mlb_hist_data_%(run_id)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    def validate_opts(self) -> None:
        """Validate that we have either market_id or market_type."""
        super().validate_opts()

        has_market_id = self.opts.get("market_id") is not None
        has_market_type = self.opts.get("market_type") is not None

        if not has_market_id and not has_market_type:
            raise DownloadDataException(
                "Either 'market_id' or 'market_type' is required. "
                f"Valid market_types: {list(MLB_MARKET_LOOKUP.keys())}"
            )

    def set_additional_opts(self) -> None:
        """Resolve market_id from market_type if needed."""
        super().set_additional_opts()

        # Resolve market_id
        if self.opts.get("market_type") and not self.opts.get("market_id"):
            market_type = self.opts["market_type"].lower().replace("-", "_")
            if market_type in MLB_MARKET_LOOKUP:
                self.opts["market_id"] = MLB_MARKET_LOOKUP[market_type]
            else:
                raise DownloadDataException(
                    f"Unknown market_type: {self.opts['market_type']}. "
                    f"Valid options: {list(MLB_MARKET_LOOKUP.keys())}"
                )

        # Get market name (convert to int if string from CLI)
        market_id = self.opts["market_id"]
        if isinstance(market_id, str):
            market_id = int(market_id)
            self.opts["market_id"] = market_id
        if market_id not in MLB_MARKETS:
            raise DownloadDataException(
                f"Unknown market_id: {market_id}. "
                f"Valid options: {list(MLB_MARKETS.keys())}"
            )

        self.opts["market_name"] = MLB_MARKETS[market_id]
        self.opts["is_pitcher_market"] = market_id in PITCHER_MARKETS

        logger.info(
            "BettingPros MLB Historical Props: market=%s (%d), date=%s",
            self.opts["market_name"],
            market_id,
            self.opts["date"]
        )

    def set_url(self) -> None:
        """Build the API URL for the first page."""
        params = {
            "sport": "MLB",
            "market_id": str(self.opts["market_id"]),
            "date": self.opts["date"],
            "limit": str(self.opts.get("limit", 50)),
            "page": "1",
        }

        if self.opts.get("include_events"):
            params["include_events"] = "true"

        self.url = f"{self.BASE_URL}?{urlencode(params)}"
        logger.debug("API URL (page 1): %s", self.url)

    def set_headers(self) -> None:
        """Set FantasyPros headers required for the API."""
        super().set_headers()
        self.headers.update(self.FANTASYPROS_HEADERS)

    def _build_url_for_page(self, page: int) -> str:
        """Build URL for a specific page."""
        params = {
            "sport": "MLB",
            "market_id": str(self.opts["market_id"]),
            "date": self.opts["date"],
            "limit": str(self.opts.get("limit", 50)),
            "page": str(page),
        }

        if self.opts.get("include_events"):
            params["include_events"] = "true"

        return f"{self.BASE_URL}?{urlencode(params)}"

    def download_and_decode(self) -> None:
        """Override to handle pagination and fetch all pages."""
        logger.info("Starting paginated download for %s on %s",
                    self.opts["market_name"], self.opts["date"])

        all_props = []
        page = 1
        total_pages = None
        total_items = None

        while True:
            # Update URL for current page
            self.url = self._build_url_for_page(page)
            logger.debug("Fetching page %d: %s", page, self.url)

            # Rate limiting (skip first page)
            if page > 1:
                time.sleep(self.RATE_LIMIT_DELAY)

            # Download with retry
            success = False
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    super().download_and_decode()
                    success = True
                    break
                except DownloadDataException as e:
                    if attempt < self.MAX_RETRIES:
                        backoff = self.RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                        logger.warning(
                            "Page %d attempt %d failed: %s. Retrying in %ds...",
                            page, attempt, e, backoff
                        )
                        time.sleep(backoff)
                    else:
                        if page == 1:
                            raise  # First page failure is fatal
                        logger.error("Page %d failed after %d attempts, stopping",
                                     page, self.MAX_RETRIES)
                        break

            if not success:
                break

            # Validate response structure
            if not isinstance(self.decoded_data, dict):
                logger.warning("Invalid response on page %d, stopping", page)
                break

            # Extract pagination info
            pagination = self.decoded_data.get("_pagination", {})
            total_pages = pagination.get("total_pages", 1)
            total_items = pagination.get("total_items", 0)
            props = self.decoded_data.get("props", [])

            logger.info("Page %d/%d: %d props (total: %d)",
                        page, total_pages, len(props), total_items)

            all_props.extend(props)

            # Check if done
            if page >= total_pages or not props:
                break

            page += 1

            # Safety limit
            if page > 100:
                logger.warning("Reached page limit (100), stopping")
                break

        # Store combined results
        self.decoded_data["all_props"] = all_props
        self.decoded_data["total_props"] = len(all_props)
        self.decoded_data["pages_fetched"] = page
        self.decoded_data["api_total_items"] = total_items

        logger.info("Pagination complete: %d props from %d pages",
                    len(all_props), page)

    def validate_download_data(self) -> None:
        """Validate the combined response."""
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Response is not a JSON object")

        all_props = self.decoded_data.get("all_props", [])
        if not isinstance(all_props, list):
            raise DownloadDataException("'all_props' is not a list")

        # Log validation result
        logger.info("Validation passed: %d props collected", len(all_props))

        if len(all_props) == 0:
            logger.warning("No props found for %s on %s",
                           self.opts["market_name"], self.opts["date"])

    def transform_data(self) -> None:
        """Transform API response to standardized output format."""
        all_props = self.decoded_data.get("all_props", [])

        processed_props = []
        scored_count = 0
        push_count = 0

        for prop in all_props:
            processed = self._process_prop(prop)
            if processed:
                processed_props.append(processed)
                if processed.get("is_scored"):
                    scored_count += 1
                if processed.get("is_push"):
                    push_count += 1

        # Build output
        self.data = {
            "meta": {
                "sport": "MLB",
                "market_id": self.opts["market_id"],
                "market_name": self.opts["market_name"],
                "is_pitcher_market": self.opts.get("is_pitcher_market", False),
                "date": self.opts["date"],
                "total_props": len(processed_props),
                "scored_props": scored_count,
                "push_props": push_count,
                "pages_fetched": self.decoded_data.get("pages_fetched", 1),
                "api_total_items": self.decoded_data.get("api_total_items"),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            },
            "props": processed_props,
        }

        # Log summary
        logger.info(
            "Transformed %d props: %d scored, %d push",
            len(processed_props), scored_count, push_count
        )

        # Send notification
        try:
            if len(processed_props) > 0:
                notify_info(
                    title="MLB Historical Props Scraped",
                    message=f"Retrieved {len(processed_props)} {self.opts['market_name']} props",
                    details={
                        'scraper': self.scraper_name,
                        'market': self.opts['market_name'],
                        'date': self.opts['date'],
                        'total_props': len(processed_props),
                        'scored': scored_count,
                        'pages': self.decoded_data.get('pages_fetched', 1),
                    }
                )
            else:
                notify_warning(
                    title="No MLB Props Found",
                    message=f"No {self.opts['market_name']} props for {self.opts['date']}",
                    details={
                        'scraper': self.scraper_name,
                        'market': self.opts['market_name'],
                        'date': self.opts['date'],
                    }
                )
        except Exception as e:
            logger.warning("Failed to send notification: %s", e)

    def _process_prop(self, prop: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single prop into standardized format."""
        try:
            # Extract participant info
            participant = prop.get("participant", {})
            player = participant.get("player", {})

            # Extract over/under
            over = prop.get("over", {})
            under = prop.get("under", {})

            # Extract projection
            projection = prop.get("projection", {})

            # Extract scoring (actual outcome!)
            scoring = prop.get("scoring", {})

            # Extract performance trends
            performance = prop.get("performance", {})

            # Extract extra context
            extra = prop.get("extra", {})

            processed = {
                # Identifiers
                "event_id": prop.get("event_id"),
                "player_id": participant.get("id"),
                "player_name": participant.get("name"),
                "team": player.get("team"),
                "position": player.get("position"),
                "jersey_number": player.get("jersey_number"),

                # Over line
                "over_line": over.get("line"),
                "over_odds": over.get("odds"),
                "over_book_id": over.get("book"),
                "over_consensus_line": over.get("consensus_line"),
                "over_consensus_odds": over.get("consensus_odds"),
                "over_probability": over.get("probability"),
                "over_ev": over.get("expected_value"),
                "over_rating": over.get("bet_rating"),

                # Under line
                "under_line": under.get("line"),
                "under_odds": under.get("odds"),
                "under_book_id": under.get("book"),
                "under_consensus_line": under.get("consensus_line"),
                "under_consensus_odds": under.get("consensus_odds"),
                "under_probability": under.get("probability"),
                "under_ev": under.get("expected_value"),
                "under_rating": under.get("bet_rating"),

                # Projection
                "projection_value": projection.get("value"),
                "projection_side": projection.get("recommended_side"),
                "projection_ev": projection.get("expected_value"),
                "projection_rating": projection.get("bet_rating"),
                "projection_diff": projection.get("diff"),

                # ACTUAL OUTCOME (key!)
                "actual_value": scoring.get("actual"),
                "is_scored": scoring.get("is_scored", False),
                "is_push": scoring.get("is_push", False),
                "push_reason": scoring.get("push_reason"),

                # Performance trends
                "perf_last_1_over": self._safe_get_perf(performance, "last_1", "over"),
                "perf_last_1_under": self._safe_get_perf(performance, "last_1", "under"),
                "perf_last_5_over": self._safe_get_perf(performance, "last_5", "over"),
                "perf_last_5_under": self._safe_get_perf(performance, "last_5", "under"),
                "perf_last_10_over": self._safe_get_perf(performance, "last_10", "over"),
                "perf_last_10_under": self._safe_get_perf(performance, "last_10", "under"),
                "perf_last_15_over": self._safe_get_perf(performance, "last_15", "over"),
                "perf_last_15_under": self._safe_get_perf(performance, "last_15", "under"),
                "perf_last_20_over": self._safe_get_perf(performance, "last_20", "over"),
                "perf_last_20_under": self._safe_get_perf(performance, "last_20", "under"),
                "perf_season_over": self._safe_get_perf(performance, "season", "over"),
                "perf_season_under": self._safe_get_perf(performance, "season", "under"),
                "perf_prior_season_over": self._safe_get_perf(performance, "prior_season", "over"),
                "perf_prior_season_under": self._safe_get_perf(performance, "prior_season", "under"),
                "perf_h2h_over": self._safe_get_perf(performance, "h2h", "over"),
                "perf_h2h_under": self._safe_get_perf(performance, "h2h", "under"),

                # Context
                "opposing_pitcher": extra.get("opposing_pitcher"),
                "lineup_set": extra.get("lineup_set"),
                "in_lineup": extra.get("in_lineup"),
                "opposition_rank": extra.get("opposition_rank", {}).get("rank"),
                "opposition_value": extra.get("opposition_rank", {}).get("value"),
            }

            return processed

        except Exception as e:
            logger.warning("Error processing prop: %s", e)
            return None

    def _safe_get_perf(self, performance: Dict, period: str, side: str) -> Optional[int]:
        """Safely extract performance value."""
        try:
            return performance.get(period, {}).get(side)
        except (TypeError, AttributeError):
            return None

    def should_save_data(self) -> bool:
        """Return True if we have props to save (even if empty, save for tracking)."""
        # Always save so we know we processed this date/market
        return True

    def get_scraper_stats(self) -> Dict[str, Any]:
        """Return scraper statistics for logging."""
        return {
            "market_id": self.opts.get("market_id"),
            "market_name": self.opts.get("market_name"),
            "date": self.opts.get("date"),
            "total_props": self.data.get("meta", {}).get("total_props", 0) if hasattr(self, 'data') else 0,
            "scored_props": self.data.get("meta", {}).get("scored_props", 0) if hasattr(self, 'data') else 0,
            "pages_fetched": self.data.get("meta", {}).get("pages_fetched", 0) if hasattr(self, 'data') else 0,
        }


# =============================================================================
# Flask and CLI entry points
# =============================================================================

create_app = convert_existing_flask_scraper(BettingProsMLBHistoricalProps)

if __name__ == "__main__":
    main = BettingProsMLBHistoricalProps.create_cli_and_flask_main()
    main()
