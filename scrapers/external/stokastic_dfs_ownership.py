# File: scrapers/external/stokastic_dfs_ownership.py
"""
Stokastic DFS Ownership Scraper                                  v1.0 - 2026-06-29
----------------------------------------------------------------------------------
Collects projected DFS ownership percentages from Stokastic.com for NBA
DraftKings main-slate contests.

API Discovery (2026-06-29):
  The Stokastic tools site (tools.stokastic.com) uses a backend API at
  https://app-api-dfs-prod-main.azurewebsites.net

  Two-step flow:
    1. GET /api/contests/getPreContestSlateInfo?app=DATAHUB&sport=NBA
       → Returns list of active slates with {slateId, site, name, startTime, matchupInfo}
    2. GET /api/slatedata/projections?SlateId={id}
       → Returns list of player projections including ownership (0.0–1.0 decimal),
         salary, position, stdDev, etc.

  Both endpoints are unauthenticated (no API key required, CORS open).
  API server is Microsoft Azure ASP.NET, Cloudflare-fronted on the www site.

Projection data field notes:
  - ownership: decimal 0.0–1.0 (e.g. 0.344 = 34.4%). Stored as-is, converted to
    pct in BQ (projected_ownership_pct = ownership * 100).
  - site codes: "DK" = DraftKings, "FD" = FanDuel
  - injuryStatus: "Unknown", "Questionable", "Out", etc. from Stokastic's data feed
  - startTime / gameTime: UTC ISO strings

Signal Hypothesis:
  High DFS ownership (top-10% of slate, typically 30%+) → public/recreational
  attention → sportsbooks shade prop lines upward to balance action → UNDER value.
  This is FORWARD COLLECTION infrastructure. Backtest in early 2027 once a season
  of data accumulates.

Timing:
  - Stokastic posts projections + ownership by ~1 PM ET on game days
  - Recommend scraping at 2 PM ET (after early lineup news settles)
  - Scrape again at ~5 PM ET for updated ownership after confirmed lineups

Usage:
  python scrapers/external/stokastic_dfs_ownership.py --date 2026-10-22 --debug
  python scrapers/external/stokastic_dfs_ownership.py --date 2026-10-22 --group prod
  python scrapers/external/stokastic_dfs_ownership.py --date 2026-10-22 --site FD
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

# Stokastic DFS API — no auth required, Azure backend
STOKASTIC_API_BASE = "https://app-api-dfs-prod-main.azurewebsites.net"
SLATES_URL = f"{STOKASTIC_API_BASE}/api/contests/getPreContestSlateInfo?app=DATAHUB&sport=NBA"
PROJECTIONS_URL = f"{STOKASTIC_API_BASE}/api/slatedata/projections?SlateId={{slate_id}}"

# Only DraftKings main slate by default — this is what the signal hypothesis targets
DEFAULT_SITE = "DK"
MAIN_SLATE_NAME = "Main"

GCS_PATH_KEY = "stokastic_dfs_ownership"


class StokasticDFSOwnershipScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape NBA DFS projected ownership from Stokastic.com for DraftKings slates.

    Two-phase scraper:
      Phase 1 (set_url): Fetch slate list to find today's NBA DK Main slate ID.
      Phase 2 (transform_data): Fetch player projections for that slate.

    Uses the ScraperBase JSON download for phase 1. Phase 2 is a manual fetch
    via self._fetch_json() in transform_data.
    """

    scraper_name = "stokastic_dfs_ownership"
    required_params = ["date"]
    optional_params = {"site": DEFAULT_SITE}

    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = None   # Standard browser UA
    proxy_enabled: bool = False         # Azure API works from Cloud IPs

    CRAWL_DELAY_SECONDS = 1.0

    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/stokastic_dfs_ownership_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_stokastic_dfs_ownership_%(date)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """Phase 1 URL: fetch the slate list for NBA."""
        self.url = SLATES_URL
        logger.info("Stokastic DFS: fetching NBA slate list from %s", self.url)

    def validate_download_data(self) -> None:
        """Verify phase 1 response is a list of slates."""
        if not isinstance(self.decoded_data, list):
            raise ValueError(
                f"Expected JSON list from Stokastic slates API, got "
                f"{type(self.decoded_data).__name__}"
            )

    def transform_data(self) -> None:
        """Phase 2: find the target slate, fetch projections, extract ownership.

        Logic:
          1. Find DK Main slate (or site override) from phase 1 slate list.
          2. Fetch /api/slatedata/projections?SlateId={id}.
          3. Extract per-player ownership + projection data.
          4. Convert ownership 0-1 decimal → pct (0-100).
        """
        game_date = self.opts["date"]
        target_site = self.opts.get("site", DEFAULT_SITE).upper()
        scraped_at = datetime.now(timezone.utc).isoformat()

        slates: List[Dict] = self.decoded_data or []
        target_slate = self._find_target_slate(slates, target_site, game_date)

        if target_slate is None:
            logger.warning(
                "Stokastic DFS: no %s %s slate found for %s (off-season or no games today)",
                target_site,
                MAIN_SLATE_NAME,
                game_date,
            )
            self.data = self._empty_result(game_date, target_site, scraped_at)
            try:
                notify_warning(
                    title="Stokastic DFS: No Slate Found",
                    message=f"No {target_site} {MAIN_SLATE_NAME} NBA slate for {game_date}",
                    details={"date": game_date, "site": target_site,
                             "slates_available": len(slates)},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass
            return

        slate_id = target_slate["slateId"]
        slate_start = target_slate.get("startTime", "")
        logger.info(
            "Stokastic DFS: found %s %s slate id=%d start=%s for %s",
            target_site,
            MAIN_SLATE_NAME,
            slate_id,
            slate_start,
            game_date,
        )

        # Phase 2: fetch player projections
        proj_url = PROJECTIONS_URL.format(slate_id=slate_id)
        raw_projections = self._fetch_json(proj_url)

        if not raw_projections:
            logger.warning("Stokastic DFS: empty projections response for slateId=%d", slate_id)
            self.data = self._empty_result(game_date, target_site, scraped_at, slate_id)
            return

        players = []
        for raw in raw_projections:
            player = self._parse_player(raw, game_date, scraped_at, target_site, slate_id)
            if player:
                players.append(player)

        # Sort by ownership descending for readability
        players.sort(key=lambda p: p["projected_ownership_pct"] or 0.0, reverse=True)

        self.data = {
            "source": "stokastic",
            "date": game_date,
            "timestamp": scraped_at,
            "site": target_site,
            "slate_id": slate_id,
            "slate_name": MAIN_SLATE_NAME,
            "slate_start_time": slate_start,
            "player_count": len(players),
            "players": players,
        }

        high_own = sum(1 for p in players if (p["projected_ownership_pct"] or 0) >= 30.0)
        logger.info(
            "Stokastic DFS: %d players for %s %s, %d with ownership >= 30%%",
            len(players),
            game_date,
            target_site,
            high_own,
        )

        if players:
            try:
                notify_info(
                    title="Stokastic DFS Ownership Scraped",
                    message=(
                        f"Scraped {len(players)} players for {game_date} "
                        f"({high_own} with ownership >= 30%)"
                    ),
                    details={
                        "date": game_date,
                        "site": target_site,
                        "player_count": len(players),
                        "high_ownership_count": high_own,
                        "slate_id": slate_id,
                    },
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="Stokastic DFS: No Players",
                    message=f"0 players parsed from projections for slateId={slate_id}",
                    details={"date": game_date, "slate_id": slate_id},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass

    def _find_target_slate(
        self,
        slates: List[Dict],
        target_site: str,
        game_date: str,
    ) -> Optional[Dict]:
        """Find the Main slate for the target site on game_date.

        The slate list contains all upcoming slates across all sports and sites.
        Filter to: sport=NBA, site=target_site, name=Main, startTime on game_date.
        """
        candidates = []
        for slate in slates:
            if slate.get("sport", "").upper() != "NBA":
                continue
            if slate.get("site", "").upper() != target_site:
                continue
            if slate.get("name", "").strip().upper() != MAIN_SLATE_NAME.upper():
                continue
            # startTime is a UTC ISO string like "2026-10-22T23:05:00"
            start_time = slate.get("startTime", "")
            if start_time[:10] == game_date:
                candidates.append(slate)

        if not candidates:
            return None
        # Prefer the one with the most games (largest main slate)
        return max(candidates, key=lambda s: len(s.get("matchupInfo", [])))

    def _parse_player(
        self,
        raw: Dict,
        game_date: str,
        scraped_at: str,
        site: str,
        slate_id: int,
    ) -> Optional[Dict]:
        """Extract per-player ownership + projection fields from raw API record.

        API field notes:
          name        - "LeBron James" (full name)
          team        - "LAL" (team abbreviation)
          salary      - integer (e.g. 10600)
          position    - "PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "SF/PF"
          ownership   - float 0.0–1.0 (projected ownership fraction)
          projection  - float (projected DK points)
          stdDev      - float (std dev of projection)
          variance    - float (Stokastic's variance multiplier, usually 1.0)
          value       - float (projection / salary * 1000)
          hrPercent   - float (home run %, baseball-specific → 0.0 for NBA)
          injuryStatus - "Unknown", "Questionable", "Out", etc.
          gameTime    - UTC ISO string for game start
          confirmedLineup - bool (true = confirmed starting)
          id          - Stokastic internal player ID
          nameAndId   - "LeBron James (12345)" (DK player ID embedded)
        """
        try:
            raw_name = raw.get("name", "").strip()
            if not raw_name:
                return None

            ownership_raw = raw.get("ownership")
            ownership_pct = None
            if ownership_raw is not None:
                try:
                    ownership_pct = round(float(ownership_raw) * 100.0, 2)
                except (TypeError, ValueError):
                    ownership_pct = None

            salary = raw.get("salary")
            if salary is not None:
                try:
                    salary = int(salary)
                except (TypeError, ValueError):
                    salary = None

            projection = raw.get("projection")
            if projection is not None:
                try:
                    projection = round(float(projection), 4)
                except (TypeError, ValueError):
                    projection = None

            std_dev = raw.get("stdDev")
            if std_dev is not None:
                try:
                    std_dev = round(float(std_dev), 4)
                except (TypeError, ValueError):
                    std_dev = None

            dk_value = raw.get("value")
            if dk_value is not None:
                try:
                    dk_value = round(float(dk_value), 4)
                except (TypeError, ValueError):
                    dk_value = None

            game_time = raw.get("gameTime", "") or ""

            # Extract DK player ID from nameAndId: "LeBron James (12345)"
            dk_player_id = None
            name_and_id = raw.get("nameAndId", "") or ""
            if "(" in name_and_id and name_and_id.endswith(")"):
                try:
                    dk_player_id = int(name_and_id.split("(")[-1].rstrip(")"))
                except (ValueError, IndexError):
                    dk_player_id = None

            return {
                "player_name": raw_name,
                "player_team": raw.get("team", ""),
                "opponent": raw.get("opponent", ""),
                "position": raw.get("position", ""),
                "game_date": game_date,
                "game_time": game_time[:19] if game_time else None,  # ISO truncated
                "contest_type": site,
                "slate_id": slate_id,
                "projected_ownership_pct": ownership_pct,
                "projected_salary": salary,
                "projected_points": projection,
                "projection_std_dev": std_dev,
                "dk_value": dk_value,
                "injury_status": raw.get("injuryStatus", "Unknown"),
                "confirmed_lineup": bool(raw.get("confirmedLineup", False)),
                "dk_player_id": dk_player_id,
                "stokastic_player_id": raw.get("id"),
                "scraped_at": scraped_at,
            }

        except Exception as e:
            logger.debug("Stokastic DFS: error parsing player row: %s", e)
            return None

    def _fetch_json(self, url: str) -> Optional[List]:
        """Manually fetch a JSON endpoint and return parsed data.

        Used for phase 2 (projections) since ScraperBase handles phase 1
        (slate list) via the standard download mechanism.
        """
        import json
        import urllib.request

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://tools.stokastic.com",
            "Referer": "https://tools.stokastic.com/",
        }

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                raw_bytes = response.read()
                return json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            logger.error("Stokastic DFS: failed to fetch projections from %s: %s", url, e)
            return None

    def _empty_result(
        self,
        game_date: str,
        site: str = DEFAULT_SITE,
        scraped_at: Optional[str] = None,
        slate_id: Optional[int] = None,
    ) -> Dict:
        return {
            "source": "stokastic",
            "date": game_date,
            "timestamp": scraped_at or datetime.now(timezone.utc).isoformat(),
            "site": site,
            "slate_id": slate_id,
            "slate_name": MAIN_SLATE_NAME,
            "slate_start_time": None,
            "player_count": 0,
            "players": [],
        }


# Flask integration
app = convert_existing_flask_scraper(StokasticDFSOwnershipScraper)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stokastic DFS Ownership Scraper")
    parser.add_argument("--date", required=True, help="Game date (YYYY-MM-DD)")
    parser.add_argument(
        "--site",
        default=DEFAULT_SITE,
        choices=["DK", "FD"],
        help="DFS site: DK=DraftKings (default), FD=FanDuel",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--local", action="store_true", help="Run locally with file export only")
    parser.add_argument("--serve", action="store_true", help="Start Flask server")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.serve:
        app.run(host="0.0.0.0", port=8080, debug=True)
    else:
        scraper = StokasticDFSOwnershipScraper()
        groups = ["dev", "test"] if args.local else ["prod", "gcs"]
        scraper.run(
            opts={"date": args.date, "site": args.site},
            groups=groups,
        )
