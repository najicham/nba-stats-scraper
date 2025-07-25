"""
ESPN - Game Boxscore scraper                                v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Scraper to extract NBA boxscore from ESPN game page.

1) Attempts to parse embedded JSON data ("bxscr").
   - If found (and not skipJson=1), we return that structure.
2) Otherwise, parse the HTML table in a way that pairs:
   - Left table (names) with Right table (stats).
   - Produces the same 14-stat arrays ESPN typically shows in the boxscore.

If ESPN includes multiple "Boxscore flex flex-column" blocks for the same 
team (responsive duplicates), we skip the duplicates based on matching 
player IDs.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py espn_game_boxscore \
      --game_id 401766123 \
      --debug

  # Direct CLI execution:
  python scrapers/espn/espn_game_boxscore.py --game_id 401766123 --debug

  # Flask web service:
  python scrapers/espn/espn_game_boxscore.py --serve --debug
"""

import logging
import json
import re
import os
import sys
from datetime import datetime, timezone

# import pytz
from bs4 import BeautifulSoup

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.espn.espn_game_boxscore
    from ..scraper_base import ScraperBase, DownloadType, ExportMode
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/espn/espn_game_boxscore.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, DownloadType, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# ---------------------------------------------------------------------------
#  Assume we have a config file with a dictionary:
#    TEAM_ABBR_MAP = {
#      "Indiana Pacers": "IND",
#      "Oklahoma City Thunder": "OKC",
#      ...
#    }
#  So that alt="Indiana Pacers" => "IND" 
# ---------------------------------------------------------------------------
try:
    from shared.config.espn_nba_team_abbr import TEAM_ABBR_MAP
except ImportError:
    # Fallback if config not available
    TEAM_ABBR_MAP = {}

logger = logging.getLogger("scraper_base")


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetEspnBoxscore(ScraperBase, ScraperFlaskMixin):
    """
    Scraper to extract NBA boxscore from ESPN game page.

    1) Attempts to parse embedded JSON data ("bxscr").
       - If found (and not skipJson=1), we return that structure.
    2) Otherwise, parse the HTML table in a way that pairs:
       - Left table (names) with Right table (stats).
       - Produces the same 14-stat arrays ESPN typically shows in the boxscore.

    If ESPN includes multiple "Boxscore flex flex-column" blocks for the same 
    team (responsive duplicates), we skip the duplicates based on matching 
    player IDs.
    """

    # Flask Mixin Configuration
    scraper_name = "espn_game_boxscore"
    required_params = ["game_id"]  # game_id is required
    optional_params = {
        "skipJson": "0",  # Set to 1/true to skip embedded JSON and test HTML
    }

    # Original scraper config
    required_opts = ["game_id"]
    download_type = DownloadType.HTML
    decode_download_data = True

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "espn_boxscore"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/boxscore2_%(game_id)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"]
        },
        {
            # NEW: raw HTML dump for fixture collection
            "type": "file",
            "filename": "/tmp/raw_%(game_id)s.html",
            "export_mode": ExportMode.RAW,   # untouched bytes
            "groups": ["capture"],           # fires only when you say --group capture
        },
        {
            "type": "file",
            # leave it in /tmp – the helper will move/gzip it for you
            "filename": "/tmp/exp_%(game_id)s.json",
            "export_mode": ExportMode.DATA,      # the parsed result
            "pretty_print": True,                # easier to read
            "groups": ["golden", "capture"],                # fires only on --group golden
        },
    ]

    def __init__(self):
        super().__init__()
        self.data = {}
        self.skip_json = False  # Controlled by command-line arg --skipJson=1

    def set_url(self):
        self.url = f"https://www.espn.com/nba/boxscore?gameId={self.opts['game_id']}"
        logger.info(f"Resolved ESPN boxscore URL: {self.url}")

    def set_headers(self):
        self.headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

    def validate_download_data(self):
        if not self.decoded_data:
            raise DownloadDataException("No HTML returned from ESPN boxscore page.")

    def transform_data(self):
        self.step_info("transform", "Parsing ESPN boxscore HTML")
        html = self.decoded_data

        # Check if user wants to skip parsing embedded JSON
        self.skip_json = str(self.opts.get("skipJson", "0")).lower() in ("1", "true", "yes")

        # 1) Attempt embedded JSON first
        embedded_data = None
        if not self.skip_json:
            embedded_data = self.extract_embedded_json(html)

        if embedded_data:
            logger.info("[✔] Found embedded 'bxscr' JSON -> parse_boxscore_json()")
            self.data = self.parse_boxscore_json(embedded_data)
        else:
            logger.warning("No embedded JSON found (or skipJson=1). Falling back to HTML.")
            self.data = self.scrape_html_boxscore(html)

        # Add top-level fields
        self.data["game_id"] = self.opts["game_id"]
        self.data["timestamp"] = datetime.now(timezone.utc).isoformat() # datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()

    # -------------------------------------------------------------------------
    # 1) Attempt: embedded JSON
    # -------------------------------------------------------------------------
    def extract_embedded_json(self, html):
        """
        Look for a pattern like: "bxscr": [ {...} ], "config"
        Return list-of-dicts if found, else None.
        """
        try:
            pattern = r'"bxscr"\s*:\s*(\[\{.*?\}\])\s*,\s*"config"'
            match = re.search(pattern, html, flags=re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except Exception:
            logger.exception("Error extracting 'bxscr' embedded JSON.")
        return None

    def parse_boxscore_json(self, bxscr_list):
      """
      Build the same structure the HTML fallback creates.
      When ESPN marks a player as DNP the JSON contains an *empty* stats list
      plus a reason in one of several keys (dnpRsn, didNotPlayReason, reason).
      We normalise that into the single-item stats list already produced by
      the HTML parser: ["DNP: <REASON>"].
      """
      result = {}

      for team_obj in bxscr_list:
          abbr    = team_obj["tm"].get("abbrev", "UNK").upper()
          players = []

          for group in team_obj.get("stats", []):
              group_type = group.get("type", "unknown")

              for a in group.get("athlts", []):
                ath      = a.get("athlt", {})
                p_id     = ath.get("id", "0")
                p_name = ath.get("dspNm") or ath.get("shrtNm") or "Unknown"   # ← full name
                jersey = ath.get("jersey") or ""                     
                stats    = a.get("stats", [])

                # --- DNP handling -------------------------------------------------------
                dnp_reason = (
                    a.get("dnpRsn")               # current key (2024-)
                    or a.get("didNotPlayReason")  # older key
                    or a.get("reason")            # very old key
                )
                record = {
                    "playerId":   p_id,
                    "playerName": p_name,
                    "jersey":     jersey,
                    "stats":      stats,
                    "type":       group_type,
                }
                if dnp_reason:
                  # Remove any leading "DNP-" / "DNP:" prefix for consistency
                  clean = re.sub(r'^\s*DNP[\-:]\s*', '', dnp_reason, flags=re.I).upper()
                  record["stats"] = []
                  record["dnpReason"] = clean

                players.append(record)

          result[abbr] = players

      return result
    

    # -------------------------------------------------------------------------
    # 2) Fallback: HTML-based approach
    # -------------------------------------------------------------------------
    def scrape_html_boxscore(self, html):
        """
        For each "Boxscore flex flex-column" container (one per team):
        - Identify team abbreviation from <img src=...png> or alt=...
        - We look for EXACTLY two <table> elements in that container:
            1) The 'left' table with player names
            2) The 'right' table with the actual stats (14 columns).
        - Pair them in displayed order.
        - If we parse the same set of player IDs for the same team multiple times
          (responsive duplicates), we skip duplicates.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Each "Boxscore flex flex-column" is one team's boxscore chunk
        sections = soup.select(".Boxscore.flex.flex-column")

        # We'll store final output in a dict
        output = {}

        # We'll track sets of player IDs to detect duplicates.
        team_to_ids = {}

        for section in sections:
            # Attempt team abbreviation from <img> or alt text
            abbr = self._extract_team_abbr(section)
            if not abbr:
                abbr = self._fallback_team_name(section, output)

            all_tables = section.select("table.Table")
            if len(all_tables) < 2:
                logger.warning(f"Boxscore section for {abbr} has <2 tables. Found {len(all_tables)}. Skipping.")
                continue

            left_table = all_tables[0]   # The 'fixed/left' table (names)
            right_table = all_tables[1]  # The 'scroll/right' table (stats)

            left_rows = left_table.select("tbody tr")
            right_rows = right_table.select("tbody tr")

            left_info = self._parse_left_rows(left_rows)
            right_info = self._parse_right_rows(right_rows)

            team_players = []
            current_type = "unknown"
            iRight = 0

            for item in left_info:
                if item["is_header"]:
                    # e.g. "starters", "bench", or "team"
                    t = item["text"].lower()
                    if t in ("starters", "bench", "team"):
                        current_type = t
                    else:
                        current_type = t if t else "unknown"
                else:
                    # It's a player row
                    p_name = item["playerName"]
                    p_id = item["playerId"]

                    # get the next row of stats from right_info
                    stats_list = []
                    if iRight < len(right_info):
                        stats_list = right_info[iRight]
                        iRight += 1
                    else:
                        logger.warning(f"Ran out of right-side rows. {p_name} has no stats.")

                    if isinstance(stats_list, dict) and "dnp" in stats_list:
                      player_rec = {
                          "playerId":   p_id,
                          "playerName": p_name,
                          "jersey":     item.get("jersey", ""),
                          "stats":      [],
                          "type":       current_type,
                          "dnpReason":  stats_list["dnp"]
                      }
                    else:
                        player_rec = {
                            "playerId":   p_id,
                            "playerName": p_name,
                            "jersey":     item.get("jersey", ""),
                            "stats":      stats_list,
                            "type":       current_type
                        }
                    team_players.append(player_rec)

            parsed_ids = set(p["playerId"] for p in team_players)
            already_seen_team = None
            for existing_team, existing_ids in team_to_ids.items():
                if parsed_ids == existing_ids:
                    already_seen_team = existing_team
                    break

            if already_seen_team:
                logger.info(f"Skipping duplicate block for team={abbr}, same IDs as {already_seen_team}.")
                continue

            output[abbr] = team_players
            team_to_ids[abbr] = parsed_ids

        return output

    # -------------------------------------------------------------------------
    # parse left side
    # -------------------------------------------------------------------------
    def _parse_left_rows(self, rows):
        """
        Return a list of dicts, e.g.
          [
            {"is_header": True, "text": "starters"},
            {"is_header": False, "playerName": "P. Siakam", "playerId": "3149673"},
            ...
          ]
        """
        parsed = []
        for tr in rows:
            header_cell = tr.select_one("td.Table__customHeader")
            if header_cell:
                text = header_cell.get_text(strip=True)
                if text:
                    parsed.append({"is_header": True, "text": text})
                continue

            link = tr.select_one("a[data-player-uid]")
            if link:
                uid = link.get("data-player-uid", "")
                # e.g. "s:40~l:46~a:3149673" => we split on "~a:"
                if "~a:" in uid:
                    p_id = uid.split("~a:")[-1]
                else:
                    p_id = uid  # fallback

                short_elt = link.select_one(".Boxscore__AthleteName--short")
                long_elt  = link.select_one(".Boxscore__AthleteName--long")
                p_name = (long_elt.get_text(strip=True) if long_elt
                          else link.get_text(strip=True))
                
                jersey_span = tr.select_one("span.playerJersey")
                jersey = re.sub(r"[^\d]", "", jersey_span.get_text()) if jersey_span else ""

                parsed.append({
                    "is_header": False,
                    "playerName": p_name,
                    "playerId": p_id,
                    "jersey": jersey,
                })
        return parsed

    # -------------------------------------------------------------------------
    # parse right side
    # -------------------------------------------------------------------------
    def _parse_right_rows(self, rows):
        """
        Return a list-of-lists, each inner list is ~14 stats.
        We skip header rows. For DNP rows, we add a single ["DNP: reason"].
        """
        stats_rows = []
        for tr in rows:
            # Skip if it's a header row
            if tr.select_one("td.Table__customHeader"):
                continue

            # Check for a DNP cell with colspan
            dnp_cell = tr.select_one("td[colspan]")
            if dnp_cell and "DNP" in dnp_cell.get_text(strip=True).upper():
                raw = dnp_cell.get_text(strip=True)             # e.g.  DNP-RIGHT ANKLE SPRAIN
                # strip the leading "DNP-" / "DNP:"  (case-insensitive)
                reason = re.sub(r'^DNP[\-:]\s*', '', raw, flags=re.I).upper()
                stats_rows.append({"dnp": reason})              # special marker
                continue

            tds = tr.select("td:not(.Table__customHeader)")
            row_stats = [td.get_text(strip=True) for td in tds]
            stats_rows.append(row_stats)

        return stats_rows

    # -------------------------------------------------------------------------
    # team detection
    # -------------------------------------------------------------------------
    def _extract_team_abbr(self, section):
        """
        Attempt to parse a team abbreviation from:
          1) <img src=".../scoreboard/ind.png" />
          2) alt="Indiana Pacers"
        Then map alt text -> known code from TEAM_ABBR_MAP if possible.
        Otherwise fallback to alt text with underscores.
        """
        logo_img = section.select_one(".Boxscore__Title img")
        if not logo_img:
            logger.info("No logo image found in section.")
            return None

        src_url = logo_img.get("src", "")
        alt_txt = logo_img.get("alt", "").strip()

        logger.debug(f"Team logo src URL: {src_url}")
        logger.debug(f"Team logo alt text: {alt_txt}")

        # Attempt scoreboard pattern, e.g. ".../scoreboard/ind.png"
        match = re.search(r"/scoreboard/([^/]+)\.png", src_url, flags=re.IGNORECASE)
        if match:
            abbr = match.group(1).upper()
            logger.debug(f"Regex matched scoreboard abbr: {abbr}")
            return abbr
        else:
            logger.info("Regex did not match scoreboard pattern in src.")

        # If alt text is in config map, use that
        if alt_txt in TEAM_ABBR_MAP:
            mapped_abbr = TEAM_ABBR_MAP[alt_txt]
            logger.debug(f"TEAM_ABBR_MAP matched '{alt_txt}' => {mapped_abbr}")
            return mapped_abbr

        # Otherwise fallback: "Indiana Pacers" => "INDIANA_PACERS"
        if alt_txt:
            fallback = alt_txt.replace(" ", "_").upper()
            logger.debug(f"Falling back to alt text => {fallback}")
            return fallback

        logger.info("No alt text found; returning None.")
        return None

    def _fallback_team_name(self, section, current_output):
        """
        If we can't parse an abbreviation from the <img>,
        fallback to e.g. "TEAM_1" or from the .BoxscoreItem__TeamName => "INDIANA_PACERS".
        """
        t_name = f"TEAM_{len(current_output) + 1}"
        maybe_name = section.select_one(".BoxscoreItem__TeamName")
        if maybe_name:
            name_text = maybe_name.get_text(strip=True)
            if name_text:
                t_name = name_text.replace(" ", "_").upper()
        return t_name

    # -------------------------------------------------------------------------
    # Stats for final log line
    # -------------------------------------------------------------------------
    def get_scraper_stats(self):
        total_players = 0
        if isinstance(self.data, dict):
            for k, v in self.data.items():
                if isinstance(v, list):
                    total_players += len(v)
        return {
            "game_id": self.opts["game_id"],
            "playerCount": total_players,
            "skipJson": self.skip_json,
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEspnBoxscore)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEspnBoxscore.create_cli_and_flask_main()
    main()
    