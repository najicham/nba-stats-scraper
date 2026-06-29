# File: scrapers/external/rotowire_nba_news.py
"""
RotoWire NBA News RSS Scraper                                    v1.0 - 2026-06-29
----------------------------------------------------------------------------------
Fetches NBA news blurbs from RotoWire's public RSS feed for forward collection.
This is infrastructure for future narrative signals — collect now, build signals
once a season of data accumulates.

RSS Feed URL: https://www.rotowire.com/rss/news.php?sport=NBA
              Returns standard RSS 2.0 XML, no auth required.

RSS Structure (verified 2026-06-29):
  <?xml version="1.0" encoding="UTF-8"?>
  <rss version="2.0">
    <channel>
      <title>RotoWire.com Latest NBA News</title>
      <item>
          <guid>nba531201</guid>
          <title>Andrew Wiggins: To sign three-year extension</title>
          <link>https://www.rotowire.com//basketball/player/andrew-wiggins-3571</link>
          <description>Wiggins intends to sign a three-year, $64 million contract ...</description>
          <pubDate>Mon, 29 Jun 2026 9:45:00 AM PDT</pubDate>
      </item>
      ...
    </channel>
  </rss>

Key observations about the feed:
  - Feed typically contains 5-20 most recent items (rotating window, not paginated).
    Run daily (or more frequently) to capture all items before they rotate off.
  - <guid> format: "nba" + numeric ID (e.g. "nba531201"). Numeric portion is the dedup key.
  - <title> format: "Player Name: Short action headline" — colon is a reliable separator.
    Player name is everything before the first colon. No team abbreviation is embedded in the title.
  - <link> format: ".../basketball/player/{slug}-{rotowire_player_id}" — player ID extractable
    from the last hyphen-separated segment of the URL path.
  - <description> is plain text (no HTML tags observed). Ends with a call-to-action sentence
    "Visit RotoWire.com for more analysis on this update." stripped before storage.
  - <pubDate> format: RFC 2822 with named timezone (e.g. "Mon, 29 Jun 2026 9:45:00 AM PDT").
    Python's email.utils.parsedate_to_datetime handles this correctly.

Fields extracted per item:
  - article_id        STRING  — numeric portion of <guid> (e.g. "531201"), dedup key
  - headline          STRING  — full <title> text (e.g. "Andrew Wiggins: To sign three-year extension")
  - player_name       STRING  — extracted from title before first colon (e.g. "Andrew Wiggins")
  - action_text       STRING  — extracted from title after first colon (e.g. "To sign three-year extension")
  - description       STRING  — <description> body, boilerplate footer stripped
  - published_at      TIMESTAMP — parsed from <pubDate>, normalized to UTC ISO
  - article_url       STRING  — <link> value (may have double slash, preserved as-is)
  - rotowire_player_id STRING — numeric player ID from URL (e.g. "3571"), NULL if not parseable
  - game_date         DATE    — date the scraper ran (partition key)
  - scraped_at        TIMESTAMP — UTC timestamp when collected

Usage:
  python scrapers/external/rotowire_nba_news.py --date 2026-06-29 --debug
  python scrapers/external/rotowire_nba_news.py --date 2026-06-29 --group prod
"""

from __future__ import annotations

import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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

# RotoWire NBA news RSS feed — public, no auth required
ROTOWIRE_NEWS_URL = "https://www.rotowire.com/rss/news.php?sport=NBA"

# Boilerplate footer appended by RotoWire to every description — strip it
_ROTOWIRE_FOOTER = "Visit RotoWire.com for more analysis on this update."

GCS_PATH_KEY = "rotowire_nba_news"

# Regex to extract the numeric player ID from RotoWire player URLs:
# e.g. "https://www.rotowire.com//basketball/player/andrew-wiggins-3571" → "3571"
_PLAYER_ID_RE = re.compile(r'-(\d+)\s*$')


class RotoWireNBANewsScraper(ScraperBase, ScraperFlaskMixin):
    """Fetch NBA news blurbs from RotoWire's RSS feed for forward collection."""

    scraper_name = "rotowire_nba_news"
    required_params = ["date"]
    optional_params = {}

    required_opts: List[str] = ["date"]
    # RSS is XML served with text/xml content-type. Use HTML download type so
    # ScraperBase fetches and decodes the response as text (self.decoded_data = str).
    # We then parse that string with ElementTree.
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True   # Triggers validate_download_data + transform_data
    header_profile: str | None = None   # No special headers needed for RotoWire RSS
    proxy_enabled: bool = False         # Public RSS works from Cloud IPs

    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/rotowire_nba_news_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_rotowire_nba_news_%(date)s.xml",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """RotoWire RSS URL has no date param — always returns the latest N items."""
        self.url = ROTOWIRE_NEWS_URL
        logger.info("RotoWire NBA news URL: %s", self.url)

    def validate_download_data(self) -> None:
        """Verify we received non-empty content that looks like RSS XML.

        For DownloadType.HTML, ScraperBase sets self.decoded_data to the
        response text (a str). We validate it here before transform_data runs.
        """
        raw = self.decoded_data
        if not raw:
            raise ValueError("Empty response from RotoWire RSS feed")
        snippet = raw[:200] if isinstance(raw, str) else str(raw)[:200]
        if "<rss" not in snippet and "<?xml" not in snippet:
            raise ValueError(
                f"Response does not look like RSS XML. First 200 chars: {snippet!r}"
            )

    def transform_data(self) -> None:
        """Parse RSS XML and extract news items.

        self.decoded_data is a str (response text) set by ScraperBase for
        DownloadType.HTML. ElementTree.fromstring accepts a str directly.
        """
        game_date = self.opts["date"]
        scraped_at = datetime.now(timezone.utc).isoformat()

        xml_text = self.decoded_data
        if not isinstance(xml_text, str):
            # Shouldn't happen for HTML download type, but be defensive
            xml_text = xml_text.decode("utf-8", errors="replace") if isinstance(xml_text, bytes) else str(xml_text)

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse RotoWire RSS XML: {e}") from e

        # RSS: <rss><channel><item>...</item>...</channel></rss>
        channel = root.find("channel")
        if channel is None:
            raise ValueError("No <channel> element found in RSS XML")

        items = channel.findall("item")
        news_items = []
        for item in items:
            parsed = self._parse_item(item, game_date, scraped_at)
            if parsed:
                news_items.append(parsed)

        self.data = {
            "source": "rotowire",
            "date": game_date,
            "timestamp": scraped_at,
            "item_count": len(news_items),
            "news_items": news_items,
        }

        logger.info(
            "RotoWire NBA News: %d items for %s",
            len(news_items),
            game_date,
        )

        if news_items:
            try:
                notify_info(
                    title="RotoWire NBA News Scraped",
                    message=f"Scraped {len(news_items)} news items for {game_date}",
                    details={"item_count": len(news_items), "date": game_date},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="RotoWire NBA News: No Items",
                    message=f"0 news items returned for {game_date}",
                    details={"date": game_date, "url": self.url},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass

    def _parse_item(
        self, item: ET.Element, game_date: str, scraped_at: str
    ) -> Optional[Dict]:
        """Parse one RSS <item> element into a flat storage record."""
        try:
            guid_raw = (item.findtext("guid") or "").strip()
            if not guid_raw:
                return None

            # guid format: "nba531201" — strip the "nba" prefix to get numeric ID
            article_id = guid_raw.removeprefix("nba") if guid_raw.startswith("nba") else guid_raw

            headline = (item.findtext("title") or "").strip()
            article_url = (item.findtext("link") or "").strip()
            description_raw = (item.findtext("description") or "").strip()
            pub_date_str = (item.findtext("pubDate") or "").strip()

            # Extract player name and action text from title.
            # Title format: "Player Name: Short action headline"
            # The colon separator is consistent across all observed RotoWire items.
            player_name: Optional[str] = None
            action_text: Optional[str] = None
            if ":" in headline:
                parts = headline.split(":", 1)
                player_name = parts[0].strip() or None
                action_text = parts[1].strip() or None

            # Extract RotoWire numeric player ID from URL.
            # URL pattern: ".../basketball/player/first-last-3571"
            rotowire_player_id: Optional[str] = None
            if article_url:
                url_path = article_url.rstrip("/").split("?")[0]
                m = _PLAYER_ID_RE.search(url_path)
                if m:
                    rotowire_player_id = m.group(1)

            # Strip RotoWire boilerplate footer from description.
            description = description_raw
            if _ROTOWIRE_FOOTER in description:
                description = description[: description.index(_ROTOWIRE_FOOTER)].strip()

            # Parse pubDate (RFC 2822 with named timezone, e.g. "Mon, 29 Jun 2026 9:45:00 AM PDT").
            # email.utils.parsedate_to_datetime handles named US timezones (PST/PDT/EST/EDT/etc.)
            published_at: Optional[str] = None
            if pub_date_str:
                try:
                    dt = parsedate_to_datetime(pub_date_str)
                    # Normalise to UTC ISO string
                    published_at = dt.astimezone(timezone.utc).isoformat()
                except Exception as e:
                    logger.debug("Could not parse pubDate %r: %s", pub_date_str, e)

            return {
                "article_id": article_id,
                "game_date": game_date,
                "headline": headline,
                "player_name": player_name,
                "action_text": action_text,
                "description": description,
                "published_at": published_at,
                "article_url": article_url,
                "rotowire_player_id": rotowire_player_id,
                "scraped_at": scraped_at,
            }

        except Exception as e:
            logger.debug("Error parsing RotoWire RSS item guid=%r: %s", item.findtext("guid"), e)
            return None

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "item_count": self.data.get("item_count", 0),
            "rowCount": self.data.get("item_count", 0),
        }


# Flask integration
app = convert_existing_flask_scraper(RotoWireNBANewsScraper)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RotoWire NBA News RSS Scraper")
    parser.add_argument("--date", required=True, help="Game date (YYYY-MM-DD)")
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
        scraper = RotoWireNBANewsScraper()
        scraper.run(opts={
            "date": args.date,
            "group": args.group,
        })
