# File: scrapers/external/espn_nba_news.py
"""
ESPN NBA News Scraper                                            v1.0 - 2026-06-29
----------------------------------------------------------------------------------
Fetches NBA news articles from ESPN's public JSON API for forward collection.
This is infrastructure for future narrative/news signals — collect now, build
signals once a season of data accumulates.

API: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=100
     Response is JSON (no auth required, public endpoint).

API Response Structure (verified 2026-06-29):
  {
    "header": "NBA News",
    "articles": [
      {
        "id": 49217727,
        "type": "HeadlineNews",
        "headline": "Ben Simmons training for comeback...",
        "description": "Blurb/lede text here...",
        "published": "2026-06-29T18:28:19Z",
        "lastModified": "2026-06-29T18:28:19Z",
        "byline": "Ohm Youngmisuk",
        "premium": false,
        "links": {"web": {"href": "https://www.espn.com/nba/story/_/id/..."}, ...},
        "categories": [
          {"type": "league",    "description": "NBA", "leagueId": 46, ...},
          {"type": "athlete",   "description": "Ben Simmons", "athleteId": 3907387, ...},
          {"type": "topic",     "description": "news", ...},
          {"type": "contributor", "description": "Ohm Youngmisuk", ...},
          {"type": "guid",      "guid": "...", ...}
        ]
      }, ...
    ]
  }

Key fields extracted per article:
  - article_id        ESPN numeric article ID (dedup key)
  - headline          News headline
  - description       Lede / blurb (1-2 sentence summary)
  - published_at      Publication UTC timestamp
  - article_type      ESPN content type (HeadlineNews, Story, etc.)
  - web_url           Full espn.com article URL
  - byline            Reporter name
  - is_premium        Whether article is ESPN+ paywalled
  - athlete_ids       Array of ESPN athlete IDs mentioned
  - athlete_names     Array of athlete display names
  - topic_tags        Array of topic labels (e.g. ["news", "injury", "trade"])
  - game_date         Date the scraper ran (partition key for BQ)
  - scraped_at        UTC timestamp when collected

Date param note: The ?dates=YYYYMMDD param filters articles to a calendar date
but ESPN's API returns [] for player-specific endpoints when passed an ID —
the /athletes/{id}/news endpoint works without params and returns that player's
recent news, but adds an extra API call per player. This scraper uses the single
bulk /news?limit=100 endpoint and extracts athlete associations from categories.

Usage:
  python scrapers/external/espn_nba_news.py --date 2026-06-29 --debug
  python scrapers/external/espn_nba_news.py --date 2026-06-29 --group prod
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_warning, notify_info

logger = logging.getLogger("scraper_base")

# ESPN NBA news endpoint — public JSON API, no auth required
ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news"

# Maximum articles to fetch per run. ESPN returns ~20-30 new articles/day.
DEFAULT_LIMIT = 100

GCS_PATH_KEY = "espn_nba_news"


class ESPNNBANewsScraper(ScraperBase, ScraperFlaskMixin):
    """Fetch NBA news blurbs from ESPN's public JSON API for forward collection."""

    scraper_name = "espn_nba_news"
    required_params = ["date"]
    optional_params = {"limit": DEFAULT_LIMIT}

    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"   # Injects ESPN User-Agent via ScraperBase
    proxy_enabled: bool = False            # ESPN public API works from Cloud IPs

    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_nba_news_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_espn_nba_news_%(date)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """Build ESPN news URL with date filter and limit."""
        date_str = self.opts["date"]
        # ESPN accepts ?dates=YYYYMMDD — convert from YYYY-MM-DD
        espn_date = date_str.replace("-", "")
        limit = self.opts.get("limit", DEFAULT_LIMIT)
        self.url = f"{ESPN_NEWS_URL}?limit={limit}&dates={espn_date}"
        logger.info("ESPN NBA news URL: %s", self.url)

    def validate_download_data(self) -> None:
        """Verify response is a dict with an 'articles' key."""
        if not isinstance(self.decoded_data, dict):
            raise ValueError(
                f"Expected JSON dict from ESPN news API, got {type(self.decoded_data).__name__}"
            )
        if "articles" not in self.decoded_data:
            raise ValueError(
                f"Missing 'articles' key in ESPN response. Keys: {list(self.decoded_data.keys())}"
            )

    def transform_data(self) -> None:
        """Extract relevant fields from each article."""
        raw_articles = self.decoded_data.get("articles", [])
        game_date = self.opts["date"]
        scraped_at = datetime.now(timezone.utc).isoformat()

        articles = []
        for raw in raw_articles:
            article = self._parse_article(raw, game_date, scraped_at)
            if article:
                articles.append(article)

        self.data = {
            "source": "espn",
            "date": game_date,
            "timestamp": scraped_at,
            "article_count": len(articles),
            "articles": articles,
        }

        logger.info(
            "ESPN NBA News: %d articles for %s (%d with athlete mentions)",
            len(articles),
            game_date,
            sum(1 for a in articles if a["athlete_ids"]),
        )

        if articles:
            try:
                notify_info(
                    title="ESPN NBA News Scraped",
                    message=f"Scraped {len(articles)} articles for {game_date}",
                    details={"article_count": len(articles), "date": game_date},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="ESPN NBA News: No Articles",
                    message=f"0 articles returned for {game_date}",
                    details={"date": game_date, "url": self.url},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass

    def _parse_article(
        self, raw: dict, game_date: str, scraped_at: str
    ) -> Optional[Dict]:
        """Parse one ESPN article dict into a flat storage record."""
        try:
            article_id = raw.get("id")
            if not article_id:
                return None

            # Extract athlete and topic info from the categories array.
            # ESPN categories can be: league / athlete / topic / contributor / guid
            athlete_ids: List[int] = []
            athlete_names: List[str] = []
            topic_tags: List[str] = []

            for cat in raw.get("categories", []):
                cat_type = cat.get("type", "")
                if cat_type == "athlete":
                    aid = cat.get("athleteId")
                    aname = cat.get("description", "")
                    if aid:
                        athlete_ids.append(int(aid))
                    if aname:
                        athlete_names.append(aname)
                elif cat_type == "topic":
                    tag = cat.get("description", "")
                    if tag:
                        topic_tags.append(tag)

            # Web URL lives at links.web.href
            web_url = None
            links = raw.get("links", {})
            if isinstance(links, dict):
                web_ref = links.get("web")
                if isinstance(web_ref, dict):
                    web_url = web_ref.get("href")

            return {
                "article_id": int(article_id),
                "game_date": game_date,
                "headline": raw.get("headline", ""),
                "description": raw.get("description", ""),
                "published_at": raw.get("published"),
                "last_modified": raw.get("lastModified"),
                "article_type": raw.get("type", ""),
                "web_url": web_url,
                "byline": raw.get("byline", ""),
                "is_premium": bool(raw.get("premium", False)),
                "athlete_ids": athlete_ids,
                "athlete_names": athlete_names,
                "topic_tags": topic_tags,
                "scraped_at": scraped_at,
            }

        except Exception as e:
            logger.debug("Error parsing ESPN article %s: %s", raw.get("id"), e)
            return None

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "article_count": self.data.get("article_count", 0),
            "rowCount": self.data.get("article_count", 0),
        }


# Flask integration
app = convert_existing_flask_scraper(ESPNNBANewsScraper)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ESPN NBA News Scraper")
    parser.add_argument("--date", required=True, help="Game date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Max articles to fetch (default: {DEFAULT_LIMIT})")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--group", default="dev",
                        help="Exporter group: dev|prod|capture (default: dev)")
    parser.add_argument("--serve", action="store_true", help="Start Flask server")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.serve:
        app.run(host="0.0.0.0", port=8080, debug=True)
    else:
        scraper = ESPNNBANewsScraper()
        scraper.run(opts={
            "date": args.date,
            "limit": args.limit,
            "group": args.group,
        })
