# File: scrapers/basketball_ref/br_season_roster.py
"""
Basketball Reference Season Roster scraper               v1.1 - 2025-08-06
------------------------------------------------------------------------
Scrapes NBA team season rosters from Basketball Reference for historical name mapping.

FIXED in v1.1:
- Added proper Unicode normalization for international player names
- Fixed character encoding issues for players like "Dāvis Bertāns"
- Enhanced name processing with ASCII conversion for reliable matching

URL Pattern: https://www.basketball-reference.com/teams/{TEAM_ABBREV}/{YEAR}.html
Example: https://www.basketball-reference.com/teams/MEM/2024.html (2023-24 season)

Rate Limiting: Basketball Reference allows max 20 requests/minute with 3-second crawl-delay.
This scraper respects their robots.txt with 3.5-second delays between requests.

Usage examples:
  # Single team/season:
  python scrapers/basketball_ref/br_season_roster.py --teamAbbr MEM --year 2024 --debug

  # Via capture tool:
  python tools/fixtures/capture.py br_season_roster \
      --teamAbbr MEM --year 2024 --debug

  # Backfill script would call this for all teams/seasons
"""

from __future__ import annotations

import logging
import re
import os
import sys
import time
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List

import sentry_sdk
from bs4 import BeautifulSoup

# Support both module execution and direct execution
try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Import shared NBA team abbreviations
try:
    # Module execution
    from ...shared.config.nba_teams import BASKETBALL_REF_TEAMS
except ImportError:
    # Direct execution
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from shared.config.nba_teams import BASKETBALL_REF_TEAMS

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger("scraper_base")

# Team name mapping (abbreviation -> full name) - specific to this scraper
TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BRK": "Brooklyn Nets",
    "CHO": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHO": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards"
}

class BasketballRefSeasonRoster(ScraperBase, ScraperFlaskMixin):
    """
    Scrape NBA team season rosters from Basketball Reference for historical name mapping.
    Respects Basketball Reference's 20 requests/minute rate limit with 3.5s delays.
    """

    # Flask Mixin Configuration
    scraper_name = "br_season_roster"
    required_params = ["teamAbbr", "year"]
    optional_params = {}

    # Scraper config
    required_opts: List[str] = ["teamAbbr", "year"]
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None  # Use default headers
    
    # Enable proxy support for Basketball Reference
    proxy_enabled: bool = True

    # Rate limiting for Basketball Reference (respect their 20 req/min + 3s crawl-delay)
    CRAWL_DELAY_SECONDS = 3.5

    # GCS export configuration
    GCS_PATH_KEY = "br_season_roster"
    exporters = [
        # GCS production export
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Local development export
        {
            "type": "file", 
            "filename": "/tmp/br_season_roster_%(teamAbbr)s_%(year)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Raw HTML for debugging/capture
        {
            "type": "file",
            "filename": "/tmp/raw_br_season_roster_%(teamAbbr)s_%(year)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # Expected parsed data for testing
        {
            "type": "file",
            "filename": "/tmp/exp_br_season_roster_%(teamAbbr)s_%(year)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    def set_additional_opts(self) -> None:
        """Add season string and validate team abbreviation."""
        super().set_additional_opts()
        
        # Validate team abbreviation against shared config
        team_abbr = self.opts["teamAbbr"].upper()
        if team_abbr not in BASKETBALL_REF_TEAMS:
            error_msg = f"Invalid team abbreviation: {team_abbr}. Must be one of: {BASKETBALL_REF_TEAMS}"
            
            # Send error notification
            try:
                notify_error(
                    title="Basketball Reference Invalid Team",
                    message=error_msg,
                    details={
                        'scraper': 'br_season_roster',
                        'invalid_team': team_abbr,
                        'valid_teams': list(BASKETBALL_REF_TEAMS),
                        'year': self.opts.get('year')
                    },
                    processor_name="Basketball Reference Season Roster"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(error_msg)
            
        self.opts["teamAbbr"] = team_abbr
        
        # Add full team name
        self.opts["teamName"] = TEAM_NAMES[team_abbr]
        
        # Create season string (year represents ending year)
        year = int(self.opts["year"])
        self.opts["season"] = f"{year-1}-{str(year)[2:]}"  # e.g., 2024 -> "2023-24"

    def set_url(self) -> None:
        """Build Basketball Reference team roster URL."""
        self.url = (
            f"https://www.basketball-reference.com/teams/"
            f"{self.opts['teamAbbr']}/{self.opts['year']}.html"
        )
        logger.info("Basketball Reference season roster URL: %s", self.url)

    def set_headers(self) -> None:
        """Set respectful headers for Basketball Reference."""
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; NBA-Stats-Scraper/1.0; Educational Use)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def download_data(self):
        """Override to add rate limiting delay before each request."""
        # Rate limiting: Basketball Reference allows max 20 req/min with 3s crawl-delay
        logger.info("Waiting %.1f seconds to respect Basketball Reference rate limits...", 
                   self.CRAWL_DELAY_SECONDS)
        time.sleep(self.CRAWL_DELAY_SECONDS)
        
        try:
            super().download_data()
        except Exception as e:
            logger.error(f"Failed to download roster data: {e}")
            
            # Send error notification
            try:
                notify_error(
                    title="Basketball Reference Download Failed",
                    message=f"Failed to download roster for {self.opts['teamAbbr']} {self.opts['season']}: {str(e)}",
                    details={
                        'scraper': 'br_season_roster',
                        'error_type': type(e).__name__,
                        'team': self.opts['teamAbbr'],
                        'season': self.opts['season'],
                        'url': self.url
                    },
                    processor_name="Basketball Reference Season Roster"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise

    def validate_download_data(self) -> None:
        """Validate that we received a proper Basketball Reference roster page."""
        try:
            if not isinstance(self.decoded_data, str):
                raise ValueError("Expected HTML string but got different data type")
            
            html_lower = self.decoded_data.lower()
            if "<html" not in html_lower:
                raise ValueError("Response doesn't appear to be HTML")
                
            # Check for Basketball Reference specific markers
            if "basketball-reference.com" not in html_lower:
                raise ValueError("Response doesn't appear to be from Basketball Reference") 
                
            # Check for roster table or team data
            if "roster" not in html_lower and self.opts["teamAbbr"].lower() not in html_lower:
                raise ValueError(f"Page doesn't appear to contain roster data for {self.opts['teamAbbr']}")
                
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            
            # Send error notification
            try:
                notify_error(
                    title="Basketball Reference Data Validation Failed",
                    message=f"Downloaded data validation failed: {str(e)}",
                    details={
                        'scraper': 'br_season_roster',
                        'error_type': type(e).__name__,
                        'team': self.opts['teamAbbr'],
                        'season': self.opts['season'],
                        'data_length': len(self.decoded_data) if self.decoded_data else 0
                    },
                    processor_name="Basketball Reference Season Roster"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise

    def safe_extract_text(self, element) -> str:
        """
        Safely extract text from HTML element while preserving UTF-8 encoding.
        Prevents character corruption issues like ā → Ä.
        """
        if not element:
            return ""
        
        try:
            # Get raw text and ensure proper UTF-8 handling
            text = element.get_text(strip=True)
            
            # If text is already a string, ensure it's properly decoded UTF-8
            if isinstance(text, str):
                # Try to detect and fix encoding issues
                try:
                    # Check if it looks like mis-decoded UTF-8
                    if 'Ä' in text or 'Ã' in text:
                        # Common pattern: UTF-8 interpreted as Latin-1
                        # Try to re-encode/decode properly
                        text_bytes = text.encode('latin-1')
                        text = text_bytes.decode('utf-8')
                        logger.debug("Fixed UTF-8 encoding for text: %s", text)
                except (UnicodeDecodeError, UnicodeEncodeError):
                    # If fix fails, keep original
                    pass
            
            return text
            
        except Exception as e:
            logger.warning("Error extracting text from element: %s", e)
            return ""

    def clean_unicode_text(self, text: str) -> str:
        """
        Clean and normalize Unicode text from HTML.
        Converts accented characters to ASCII equivalents for reliable matching.
        
        Examples:
        - "Dāvis Bertāns" → "Davis Bertans"
        - "Bogdan Bogdanović" → "Bogdan Bogdanovic"
        - "Nikola Jokić" → "Nikola Jokic"
        """
        if not text:
            return ""
        
        try:
            # Step 1: Normalize Unicode to decomposed form (separates base + accents)
            normalized = unicodedata.normalize('NFD', text)
            
            # Step 2: Remove combining characters (accents, diacritics)
            # Category 'Mn' = nonspacing marks (accents, tildes, etc.)
            ascii_text = ''.join(
                char for char in normalized 
                if unicodedata.category(char) != 'Mn'
            )
            
            # Step 3: Ensure it's valid ASCII (fallback for any remaining issues)
            ascii_text = ascii_text.encode('ascii', 'ignore').decode('ascii')
            
            # Step 4: Clean up extra spaces
            ascii_text = ' '.join(ascii_text.split())
            
            # Debug logging for international names
            if text != ascii_text:
                logger.debug("Unicode cleanup: '%s' → '%s'", text, ascii_text)
            
            return ascii_text
            
        except Exception as e:
            logger.warning("Error cleaning Unicode text '%s': %s", text, e)
            # Fallback: try simple ASCII conversion
            try:
                return text.encode('ascii', 'ignore').decode('ascii')
            except (UnicodeDecodeError, UnicodeEncodeError, AttributeError):
                # UnicodeDecodeError/UnicodeEncodeError: encoding fails; AttributeError: None.encode()
                return text  # Last resort: return original

    def normalize_name(self, name: str) -> str:
        """
        Normalize name for matching against gamebook data.
        NOW WITH UNICODE SUPPORT!
        
        Steps:
        1. Clean Unicode characters (accents → ASCII)
        2. Remove suffixes (Jr, Sr, II, etc.)
        3. Convert to lowercase
        4. Clean spaces and punctuation
        """
        if not name:
            return ""
        
        # Step 1: FIXED - Clean Unicode characters first
        clean_name = self.clean_unicode_text(name)
        
        # Step 2: Remove common suffixes
        suffixes = ["Jr.", "Sr.", "Jr", "Sr", "II", "III", "IV", "V"]
        for suffix in suffixes:
            clean_name = clean_name.replace(f" {suffix}", "")
        
        # Step 3: Normalize case and spacing
        normalized = clean_name.lower().strip()
        
        # Step 4: Remove extra spaces
        normalized = ' '.join(normalized.split())
        
        return normalized

    def transform_data(self) -> None:
        """Parse Basketball Reference roster page and extract player data."""
        # FIXED: Ensure proper UTF-8 handling for international characters
        soup = BeautifulSoup(self.decoded_data, "html.parser")
        
        # Find the roster table - Basketball Reference uses id="roster"
        roster_table = soup.find("table", {"id": "roster"})
        if not roster_table:
            # Fallback: look for any table with roster-like headers
            all_tables = soup.find_all("table")
            for table in all_tables:
                headers = table.find_all("th")
                header_text = " ".join([self.safe_extract_text(th).lower() for th in headers])
                if "player" in header_text and ("no" in header_text or "pos" in header_text):
                    roster_table = table
                    break
        
        if not roster_table:
            warning_msg = f"Could not find roster table for {self.opts['teamAbbr']} {self.opts['year']}"
            logger.warning(warning_msg)
            sentry_sdk.capture_message(
                f"No roster table found for {self.opts['teamAbbr']} {self.opts['year']}", 
                level="warning"
            )
            
            # Send warning notification
            try:
                notify_warning(
                    title="Basketball Reference No Roster Table",
                    message=warning_msg,
                    details={
                        'scraper': 'br_season_roster',
                        'team': self.opts['teamAbbr'],
                        'season': self.opts['season'],
                        'year': self.opts['year'],
                        'url': self.url
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            self.data = self._create_empty_roster()
            return

        # Parse roster table
        players = []
        tbody = roster_table.find("tbody")
        if tbody:
            rows = tbody.find_all("tr")
        else:
            # Some tables don't have tbody
            rows = roster_table.find_all("tr")[1:]  # Skip header row

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
                
            # Skip totals/summary rows
            row_text = " ".join([self.safe_extract_text(cell).lower() for cell in cells])
            if any(skip in row_text for skip in ["team totals", "totals"]):
                continue

            player_data = self._extract_player_from_row(cells)
            if player_data and player_data.get("full_name"):
                players.append(player_data)
        
        # Create final data structure with enhanced fields
        self.data = {
            "team": self.opts["teamName"],
            "team_abbrev": self.opts["teamAbbr"],
            "season": self.opts["season"],
            "year": int(self.opts["year"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
            "source_url": self.url,
            # Add metadata for debugging name matching
            "name_processing": {
                "enhanced": True,
                "suffix_handling": True,
                "normalization": True,
                "unicode_handling": True,
                "version": "2.1"
            }
        }
        
        logger.info("Parsed %d players for %s %s", 
                len(players), self.opts["teamAbbr"], self.opts["season"])
        
        # Log sample for verification
        if players:
            sample = players[0]
            logger.debug("Sample player: %s -> last_name='%s', normalized='%s', suffix='%s'",
                        sample.get("full_name", ""), 
                        sample.get("last_name", ""),
                        sample.get("normalized", ""),
                        sample.get("suffix", ""))
            
            # Send success notification
            try:
                notify_info(
                    title="Basketball Reference Roster Scraped Successfully",
                    message=f"Successfully scraped roster for {self.opts['teamAbbr']} {self.opts['season']}",
                    details={
                        'scraper': 'br_season_roster',
                        'team': self.opts['teamAbbr'],
                        'team_name': self.opts['teamName'],
                        'season': self.opts['season'],
                        'player_count': len(players),
                        'sample_player': sample.get('full_name')
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        else:
            # Send warning if no players found
            try:
                notify_warning(
                    title="Basketball Reference No Players Found",
                    message=f"Roster table found but no players extracted for {self.opts['teamAbbr']} {self.opts['season']}",
                    details={
                        'scraper': 'br_season_roster',
                        'team': self.opts['teamAbbr'],
                        'season': self.opts['season'],
                        'rows_found': len(rows),
                        'url': self.url
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

    def _extract_player_from_row(self, cells) -> Dict[str, str]:
        """Extract player data from a single table row - FIXED FOR MULTIPLE JERSEY NUMBERS."""
        try:
            # Simplified, cleaner data structure
            player_data = {
                "jersey_number": "",
                "full_name": "",        # Complete name as shown on Basketball Reference
                "full_name_ascii": "",  # ASCII-only version for reliable matching
                "last_name": "",        # Actual surname (no suffixes)
                "normalized": "",       # Normalized for matching (now with Unicode support)
                "suffix": "",           # Jr, Sr, II, etc. (if present)
                "position": "",
                "height": "",
                "weight": ""
            }

            def is_jersey_number_cell(text: str) -> bool:
                """Detect if cell contains jersey number(s) - HANDLES MULTIPLE NUMBERS."""
                if not text:
                    return False
                
                # Pattern 1: Single number (4, 23, etc.)
                if re.match(r'^\d{1,2}$', text):
                    return True
                
                # Pattern 2: Multiple numbers with comma/space (4, 44 or 4,44 or 4 44)
                if re.match(r'^\d{1,2}[\s,]+\d{1,2}$', text):
                    return True
                    
                # Pattern 3: Multiple numbers with slash (4/44)
                # Note: Dashes excluded - they're used for heights (6-8)
                if re.match(r'^\d{1,2}/\d{1,2}$', text):
                    return True
                    
                return False

            def is_likely_name(text: str) -> bool:
                """Enhanced name detection - EXCLUDES JERSEY NUMBERS."""
                if not text or len(text.strip()) < 2:
                    return False
                    
                # FIXED: Exclude jersey number patterns first
                if is_jersey_number_cell(text):
                    return False
                    
                # Must have at least 2 words for first/last name
                words = text.split()
                if len(words) < 2:
                    return False
                    
                # Exclude obvious non-names (numbers, measurements, etc.)
                if re.match(r'^[\d\-\.\s,/]+$', text):
                    return False
                    
                # Exclude measurements/stats
                if "'" in text or '"' in text:  # Heights like 6'8"
                    return False
                    
                if re.match(r'^\d+\s*(lbs?|kg)$', text.lower()):  # Weights
                    return False
                    
                # Exclude positions
                if re.match(r'^[A-Z]{1,3}(-[A-Z]{1,3})?$', text):
                    return False
                    
                return True

            # Find player name - prioritize links, then use enhanced detection
            raw_full_name = ""
            
            # Step 1: Look for player links (most reliable)
            for cell in cells:
                player_link = cell.find("a", href=re.compile(r"/players/"))
                if player_link:
                    raw_full_name = self.safe_extract_text(player_link)
                    break

            # Step 2: Enhanced fallback with proper jersey number exclusion
            if not raw_full_name:
                for cell in cells:
                    text = self.safe_extract_text(cell)
                    if is_likely_name(text):
                        raw_full_name = text
                        break

            if not raw_full_name:
                logger.debug("No valid player name found in row cells: %s", 
                            [self.safe_extract_text(cell) for cell in cells[:5]])
                return {}

            # Store original and ASCII versions
            player_data["full_name"] = raw_full_name
            player_data["full_name_ascii"] = self.clean_unicode_text(raw_full_name)

            # Extract last name and suffix from ASCII version
            ascii_name = player_data["full_name_ascii"]
            name_parts = ascii_name.split()
            if name_parts:
                suffixes = ["Jr.", "Sr.", "Jr", "Sr", "II", "III", "IV", "V"]
                last_part = name_parts[-1]
                
                if last_part in suffixes and len(name_parts) > 1:
                    player_data["last_name"] = name_parts[-2]
                    player_data["suffix"] = last_part
                else:
                    player_data["last_name"] = last_part
                    player_data["suffix"] = ""
            
            # Add normalized name
            player_data["normalized"] = self.normalize_name(raw_full_name)

            # FIXED: Enhanced jersey number extraction (excludes height measurements)
            jersey_numbers = []
            for cell in cells[:4]:  # Check first few cells
                text = self.safe_extract_text(cell)
                if is_jersey_number_cell(text):
                    if re.match(r'^\d{1,2}$', text):
                        # Single jersey number
                        jersey_numbers.append(text)
                    elif re.match(r'^\d{1,2}[\s,]+\d{1,2}$', text):
                        # Multiple jersey numbers with comma/space
                        numbers = re.findall(r'\d{1,2}', text)
                        jersey_numbers.extend(numbers)
                    elif re.match(r'^\d{1,2}/\d{1,2}$', text):
                        # Multiple jersey numbers with slash
                        numbers = re.findall(r'\d{1,2}', text)
                        jersey_numbers.extend(numbers)
                    
            if jersey_numbers:
                # Use the first number as primary
                player_data["jersey_number"] = jersey_numbers[0]
                
                # Store all numbers if multiple (for debugging/reference)
                if len(jersey_numbers) > 1:
                    player_data["all_jersey_numbers"] = jersey_numbers
                    logger.debug("Player %s has multiple jersey numbers: %s", 
                            raw_full_name, jersey_numbers)

            # Extract other fields by position
            cell_texts = [self.safe_extract_text(cell) for cell in cells]
            
            # Position (PG, SG, PF-C, etc.)
            for text in cell_texts:
                if re.match(r'^[A-Z]{1,3}(-[A-Z]{1,3})?$', text):
                    player_data["position"] = text
                    break

            # Height (6-8 or 6'8")
            for text in cell_texts:
                if re.match(r'\d+-\d+|\d+\'\d+', text):
                    player_data["height"] = text
                    break

            # Weight (180-350 range for NBA)
            for text in cell_texts:
                if re.match(r'^\d{3}$', text):
                    weight_num = int(text)
                    if 150 <= weight_num <= 350:
                        player_data["weight"] = text
                        break

            return player_data

        except Exception as e:
            logger.warning("Error parsing player row: %s", e)
            logger.debug("Row cells: %s", [self.safe_extract_text(cell) for cell in cells])
            return {}

    def _create_empty_roster(self) -> Dict:
        """Create empty roster structure when no data found."""
        return {
            "team": self.opts["teamName"],
            "team_abbrev": self.opts["teamAbbr"], 
            "season": self.opts["season"],
            "year": int(self.opts["year"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": 0,
            "players": [],
            "source_url": self.url,
            "error": "No roster data found"
        }

    def get_scraper_stats(self) -> dict:
        """Return stats for logging."""
        return {
            "teamAbbr": self.opts["teamAbbr"],
            "season": self.opts["season"],
            "playerCount": self.data.get("playerCount", 0),
        }


# Flask and CLI entry points using mixin
create_app = convert_existing_flask_scraper(BasketballRefSeasonRoster)

if __name__ == "__main__":
    main = BasketballRefSeasonRoster.create_cli_and_flask_main()
    main()