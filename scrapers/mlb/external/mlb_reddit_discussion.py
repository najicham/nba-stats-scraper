"""
File: scrapers/mlb/external/mlb_reddit_discussion.py

MLB Reddit Discussion Scraper                                    v1.0 - 2026-03-06
--------------------------------------------------------------------------------
Fetches daily discussion posts about MLB betting and pitcher analysis from
relevant subreddits using Reddit's public JSON API (no authentication needed).

Subreddits:
- r/sportsbook: MLB Daily threads, picks, betting discussion
- r/baseball: Pitching analysis, strikeout discussion
- r/fantasybaseball: Streaming pitchers, start/sit recommendations

Provides community intelligence signals:
- Which pitchers are being discussed
- Sentiment around over/under K props
- Sharp bettor commentary from r/sportsbook daily threads

API: Reddit public JSON endpoints (append .json to any Reddit URL)
Rate Limit: 2 second delay between subreddit requests
No authentication required, but User-Agent header is mandatory.

Usage:
  python scrapers/mlb/external/mlb_reddit_discussion.py --date 2025-06-15 --debug
  python scrapers/mlb/external/mlb_reddit_discussion.py --debug
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper

logger = logging.getLogger(__name__)


# Keywords that indicate a comment is relevant to pitcher props / K analysis
# Keywords that indicate a comment is relevant to pitcher props / K analysis
# Avoid overly common words like 'over'/'under' which produce false positives
K_KEYWORDS = [
    'strikeout', 'strikeouts', ' k ', ' ks ', 'prop', 'props',
    'pitcher', 'pitching', 'whiff', 'chase rate',
    'slider', 'fastball', 'changeup', 'curveball',
    'k line', 'k prop', 'k/9', 'swstr',
    'over .5', 'under .5',  # match "over 6.5" but not "over the weekend"
]

# Search configurations per subreddit
SUBREDDIT_SEARCHES = {
    "sportsbook": [
        {"query": "MLB Daily", "is_daily_thread": True},
        {"query": "MLB picks", "is_daily_thread": False},
    ],
    "baseball": [
        {"query": "strikeout", "is_daily_thread": False},
        {"query": "pitching", "is_daily_thread": False},
    ],
    "fantasybaseball": [
        {"query": "streaming", "is_daily_thread": False},
        {"query": "start sit", "is_daily_thread": False},
    ],
}

# Minimum comment score to include (filters noise)
MIN_COMMENT_SCORE = 3

# Max characters of selftext to store per post
SELFTEXT_PREVIEW_LENGTH = 500

# Max top comments to fetch per daily thread
MAX_COMMENTS_PER_THREAD = 50

# Delay between requests in seconds (Reddit rate limit)
REQUEST_DELAY_SECONDS = 2

# HTTP timeout per request
REQUEST_TIMEOUT_SECONDS = 10


class MlbRedditDiscussionScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB betting and pitcher discussion from Reddit.

    Uses Reddit's public JSON API to fetch posts and comments from:
    - r/sportsbook (MLB daily threads, picks)
    - r/baseball (pitching analysis, strikeout discussion)
    - r/fantasybaseball (streaming pitchers, start/sit)

    Extracts top comments from daily threads that mention pitchers
    or K-related terms.
    """

    scraper_name = "mlb_reddit_discussion"
    required_params = []
    optional_params = {
        "date": None,  # Target date (YYYY-MM-DD), defaults to today
    }

    required_opts: List[str] = ["date"]
    download_type = DownloadType.JSON
    decode_download_data = False  # Multiple API calls, we handle download ourselves
    proxy_enabled: bool = True

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-external/reddit-discussion/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_reddit_discussion_%(date)s_%(timestamp)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    _REDDIT_BASE = "https://www.reddit.com"

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        if not self.opts.get("date"):
            self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def set_url(self) -> None:
        # URL is set dynamically per request in download()
        self.url = f"{self._REDDIT_BASE}/r/sportsbook/search.json"

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "mlb-props-research/1.0",
            "Accept": "application/json",
        }

    def download_and_decode(self) -> None:
        """Override download_and_decode to make multiple Reddit API requests.

        Must override download_and_decode (not download) because the base
        lifecycle calls download_and_decode from the HTTP handler mixin.
        """
        all_posts = []
        all_top_comments = []
        subreddits_scraped = set()
        request_count = 0

        for subreddit, searches in SUBREDDIT_SEARCHES.items():
            for search_config in searches:
                query = search_config["query"]
                is_daily_thread = search_config["is_daily_thread"]

                # Rate limit between requests
                if request_count > 0:
                    time.sleep(REQUEST_DELAY_SECONDS)

                try:
                    posts = self._search_subreddit(subreddit, query)
                    request_count += 1

                    for post in posts:
                        post["search_query"] = query
                        post["is_daily_thread"] = is_daily_thread

                    all_posts.extend(posts)
                    subreddits_scraped.add(subreddit)

                    logger.info(
                        "Fetched %d posts from r/%s for query '%s'",
                        len(posts), subreddit, query,
                    )

                    # For daily threads, fetch top comments
                    if is_daily_thread:
                        for post in posts:
                            if request_count > 0:
                                time.sleep(REQUEST_DELAY_SECONDS)

                            try:
                                comments = self._fetch_post_comments(
                                    subreddit, post["post_id"]
                                )
                                request_count += 1
                                all_top_comments.extend(comments)
                                logger.info(
                                    "Fetched %d qualifying comments from post %s",
                                    len(comments), post["post_id"],
                                )
                            except Exception as e:
                                logger.warning(
                                    "Error fetching comments for post %s: %s",
                                    post["post_id"], e,
                                )

                except Exception as e:
                    logger.error(
                        "Error searching r/%s for '%s': %s", subreddit, query, e
                    )

        # Deduplicate posts by post_id (same post may appear in multiple searches)
        seen_ids = set()
        unique_posts = []
        for post in all_posts:
            if post["post_id"] not in seen_ids:
                seen_ids.add(post["post_id"])
                unique_posts.append(post)

        # Deduplicate comments by comment_id
        seen_comment_ids = set()
        unique_comments = []
        for comment in all_top_comments:
            if comment["comment_id"] not in seen_comment_ids:
                seen_comment_ids.add(comment["comment_id"])
                unique_comments.append(comment)

        self.download_data = {
            "posts": unique_posts,
            "top_comments": unique_comments,
            "subreddits_scraped": list(subreddits_scraped),
            "request_count": request_count,
        }

        logger.info(
            "Reddit scrape complete: %d unique posts, %d qualifying comments "
            "from %d subreddits (%d API requests)",
            len(unique_posts), len(unique_comments),
            len(subreddits_scraped), request_count,
        )

    def _search_subreddit(self, subreddit: str, query: str) -> List[Dict[str, Any]]:
        """Search a subreddit for posts matching query, sorted by new, within the last day."""
        params = {
            "q": query,
            "sort": "new",
            "restrict_sr": "1",
            "t": "day",
            "limit": "25",
        }
        url = f"{self._REDDIT_BASE}/r/{subreddit}/search.json?{urlencode(params)}"

        resp = self.http_downloader.get(
            url,
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()

        posts = []
        for child in data.get("data", {}).get("children", []):
            post_data = child.get("data", {})
            if not post_data:
                continue

            selftext = post_data.get("selftext", "") or ""
            posts.append({
                "subreddit": subreddit,
                "post_id": post_data.get("id", ""),
                "title": post_data.get("title", ""),
                "author": post_data.get("author", "[deleted]"),
                "score": post_data.get("score", 0),
                "num_comments": post_data.get("num_comments", 0),
                "created_utc": post_data.get("created_utc", 0),
                "url": f"https://reddit.com{post_data.get('permalink', '')}",
                "selftext_preview": selftext[:SELFTEXT_PREVIEW_LENGTH],
            })

        return posts

    def _fetch_post_comments(
        self, subreddit: str, post_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch top comments from a specific post. Filters by score and K relevance."""
        url = (
            f"{self._REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
            f"?sort=top&limit={MAX_COMMENTS_PER_THREAD}"
        )

        resp = self.http_downloader.get(
            url,
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()

        comments = []

        # Reddit returns [post_listing, comment_listing]
        if not isinstance(data, list) or len(data) < 2:
            return comments

        comment_listing = data[1].get("data", {}).get("children", [])
        for child in comment_listing:
            if child.get("kind") != "t1":
                continue

            comment_data = child.get("data", {})
            if not comment_data:
                continue

            score = comment_data.get("score", 0)
            if score < MIN_COMMENT_SCORE:
                continue

            body = comment_data.get("body", "") or ""
            body_lower = body.lower()

            # Check for pitcher/K relevance
            mentions_pitcher = self._mentions_pitcher_content(body_lower)

            comments.append({
                "subreddit": subreddit,
                "post_id": post_id,
                "comment_id": comment_data.get("id", ""),
                "author": comment_data.get("author", "[deleted]"),
                "body": body[:1000],  # Cap comment body length
                "score": score,
                "created_utc": comment_data.get("created_utc", 0),
                "mentions_pitcher": mentions_pitcher,
                "mentioned_names": self._extract_mentioned_names(body),
            })

        return comments

    def _mentions_pitcher_content(self, text_lower: str) -> bool:
        """Check if text mentions pitcher-related or K-related content."""
        for keyword in K_KEYWORDS:
            if keyword in text_lower:
                return True
        return False

    def _extract_mentioned_names(self, text: str) -> List[str]:
        """
        Extract potential player name mentions from text.

        Uses a simple heuristic: look for capitalized words that could be
        last names (2+ capital-letter-starting words in a row, or single
        capitalized words near K keywords).
        """
        names = []

        # Pattern: Capitalized word near K-related context
        # e.g., "Cole OVER 7.5 Ks", "Burnes K prop", "Skubal strikeouts"
        # Look for capitalized words (likely surnames) near keywords
        words = text.split()
        for i, word in enumerate(words):
            # Clean punctuation from word for matching
            clean = re.sub(r'[^a-zA-Z]', '', word)
            if not clean or len(clean) < 3:
                continue

            # Check if word is capitalized (likely a name) and not a common word
            if clean[0].isupper() and clean not in _COMMON_WORDS:
                # Check if nearby words (within 3 positions) contain K keywords
                context_start = max(0, i - 3)
                context_end = min(len(words), i + 4)
                context = ' '.join(words[context_start:context_end]).lower()

                for keyword in K_KEYWORDS:
                    if keyword in context:
                        names.append(clean)
                        break

        # Deduplicate while preserving order
        seen = set()
        unique_names = []
        for name in names:
            if name not in seen:
                seen.add(name)
                unique_names.append(name)

        return unique_names

    def validate_download_data(self) -> None:
        if not isinstance(self.download_data, dict):
            raise ValueError("Reddit discussion data is malformed")
        # It's valid to have 0 posts (e.g., off-season), but the structure must exist
        if "posts" not in self.download_data:
            raise ValueError("Reddit discussion data missing 'posts' key")

    def transform_data(self) -> None:
        posts = self.download_data.get("posts", [])
        top_comments = self.download_data.get("top_comments", [])
        subreddits_scraped = self.download_data.get("subreddits_scraped", [])

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "subreddits_scraped": len(subreddits_scraped),
            "total_posts": len(posts),
            "total_comments": len(top_comments),
            "posts": posts,
            "top_comments": top_comments,
        }

        logger.info(
            "Transformed Reddit data: %d posts, %d comments from %d subreddits",
            len(posts), len(top_comments), len(subreddits_scraped),
        )

    def get_scraper_stats(self) -> dict:
        return {
            "total_posts": self.data.get("total_posts", 0),
            "total_comments": self.data.get("total_comments", 0),
            "subreddits_scraped": self.data.get("subreddits_scraped", 0),
        }


# Common English words to exclude from name detection
# (words that are capitalized at start of sentences but aren't names)
_COMMON_WORDS = {
    "The", "This", "That", "These", "Those", "There", "Their", "They",
    "What", "When", "Where", "Which", "While", "Who", "Why", "How",
    "Have", "Has", "Had", "Will", "Would", "Could", "Should", "Can",
    "May", "Might", "Must", "Shall", "Does", "Did", "Are", "Were",
    "Was", "Been", "Being", "Not", "But", "And", "For", "Nor",
    "Yet", "Both", "Either", "Neither", "Each", "Every", "All",
    "Any", "Few", "More", "Most", "Other", "Some", "Such", "Than",
    "Too", "Very", "Just", "Also", "Now", "Then", "Here", "Only",
    "Even", "Still", "Already", "Always", "Never", "Often", "Once",
    "MLB", "MLB's", "OVER", "UNDER", "BOL", "IMO", "FWIW", "PSA",
    "Daily", "Thread", "Game", "Games", "Today", "Tonight", "Pick",
    "Picks", "Best", "Lock", "Locks", "Fade", "Lean", "Like",
    "Take", "Taking", "Going", "Think", "Thinking", "Looking",
    "Start", "Sit", "Stream", "Streaming", "Add", "Drop",
    "Over", "Under", "Line", "Lines", "Prop", "Props", "Bet", "Bets",
    "His", "Her", "Him", "She", "Its", "Our", "Your", "My",
    "With", "From", "Into", "About", "After", "Before",
    "First", "Last", "Next", "New", "Good", "Great", "Bad",
    "Right", "Left", "High", "Low", "Big", "Top", "Hot", "Cold",
}


create_app = convert_existing_flask_scraper(MlbRedditDiscussionScraper)

if __name__ == "__main__":
    main = MlbRedditDiscussionScraper.create_cli_and_flask_main()
    main()
