"""
NBA.com Gamebook PDF scraper                            v1.0 – 2025‑08‑04
---------------------------------------------------------------------------
* Downloads and parses NBA gamebook PDFs 
* AUTO-DERIVES date and teams from game_code (single source of truth!)
* Extracts box scores AND DNP reasons (critical for prop betting)

Usage examples
--------------
  # Via capture tool (recommended):
  python tools/fixtures/capture.py nbac_gamebook_pdf \
      --game_code "20240410/MEMCLE" --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_gamebook_pdf.py --game_code "20240410/MEMCLE" --debug
"""

import logging
import os
import sys
import re
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import pdfplumber

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_gamebook_pdf
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException, InvalidRegionDecodeException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_gamebook_pdf.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException, InvalidRegionDecodeException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger("scraper_base")


class GetNbaComGamebookPdf(ScraperBase, ScraperFlaskMixin):
    """Downloads and parses NBA gamebook PDF - AUTO-DERIVES everything from game_code."""

    # Flask Mixin Configuration
    scraper_name = "nbac_gamebook_pdf"
    required_params = ["game_code"]  # Just 1 required! Everything else auto-derived
    optional_params = {
        "version": "short",     # "short" (.pdf) or "full" (_book.pdf)
        "date": None,           # Auto-derived from game_code (can override)
        "away_team": None,      # Auto-derived from game_code (can override)
        "home_team": None,      # Auto-derived from game_code (can override)
    }

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    required_opts = ["game_code"]  # Just 1! Everything else auto-derived
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.BINARY
    proxy_enabled: bool = True
    timeout_http = 60
    
    # ------------------------------------------------------------------ #
    # Exporters - Save BOTH PDF and parsed data
    # ------------------------------------------------------------------ #
    exporters = [
        # Save original PDF to GCS
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path("nba_com_gamebooks_pdf_raw"),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],  # Added "s3" group like working scrapers
        },
        # Save parsed data to GCS
        {
            "type": "gcs", 
            "key": GCSPathBuilder.get_path("nba_com_gamebooks_pdf_data"),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "s3", "gcs"],  # Added "s3" group like working scrapers
        },
        # Development exports
        {
            "type": "file",
            "filename": "/tmp/nba_gamebook_%(clean_game_code)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Capture group exports
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.pdf",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # AUTO-DERIVE everything from game_code
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        # Parse game_code BEFORE calling super() to extract the correct date
        game_code = self.opts["game_code"]
        if "/" not in game_code:
            raise DownloadDataException("game_code must be in format YYYYMMDD/TEAMTEAM")
        
        date_part, teams_part = game_code.split("/")
        
        # FORCE the game date (override parent class default)
        year = date_part[:4]    # "2024"
        month = date_part[4:6]  # "04" 
        day = date_part[6:8]    # "10"
        self.opts["date"] = f"{year}-{month}-{day}"  # "2024-04-10" - GAME DATE
        
        # Now call super() - it won't override our date since it's already set
        super().set_additional_opts()
        
        # AUTO-DERIVE TEAMS from game_code (unless overridden)
        if len(teams_part) != 6:
            raise DownloadDataException("Teams part must be 6 characters (3+3)")
        
        if not self.opts.get("away_team"):
            self.opts["away_team"] = teams_part[:3]  # "MEM"
        if not self.opts.get("home_team"):
            self.opts["home_team"] = teams_part[3:]  # "CLE"
        
        # Set derived values
        self.opts["date_part"] = date_part
        self.opts["teams_part"] = teams_part
        self.opts["matchup"] = f"{self.opts['away_team']}@{self.opts['home_team']}"
        self.opts["clean_game_code"] = game_code.replace("/", "_")  # For filenames
        self.opts["clean_game_code_dashes"] = game_code.replace("/", "-")  # "20211003-BKNLAL"
        
        # Set defaults
        self.opts["version"] = self.opts.get("version", "short")
        
        # Log to verify correct date is being used
        logger.info("Using game date: %s (derived from game_code: %s)", 
                   self.opts["date"], game_code)

    # ------------------------------------------------------------------ #
    # URL construction
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        """Construct PDF URL from game_code."""
        date_part = self.opts["date_part"]
        teams_part = self.opts["teams_part"]
        version = self.opts["version"]
        
        # CORRECTED URL format
        if version == "short":
            # Short version - basic box score (NO _book suffix)
            self.url = f"https://statsdmz.nba.com/pdfs/{date_part}/{date_part}_{teams_part}.pdf"
        elif version == "full":
            # Full version - detailed game book (HAS _book suffix)
            self.url = f"https://statsdmz.nba.com/pdfs/{date_part}/{date_part}_{teams_part}_book.pdf"
        else:
            raise DownloadDataException("version must be 'short' or 'full'")
        
        logger.info("NBA Gamebook PDF URL (%s): %s", version, self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_opts(self) -> None:
        super().validate_opts()
        
        # Validate game_code format
        game_code = self.opts["game_code"]
        if not re.match(r'^\d{8}/[A-Z]{6}$', game_code):
            raise DownloadDataException("game_code must be in format YYYYMMDD/TEAMTEAM")

    # ------------------------------------------------------------------ #
    # PDF Parsing
    # ------------------------------------------------------------------ #
    def decode_download_content(self) -> None:
        """Parse PDF content using pdfplumber."""
        content = self.raw_response.content

        # Basic PDF validation
        if b"not accessible in this region" in content.lower():
            raise InvalidRegionDecodeException("PDF blocked in this region.")
        if b"%PDF" not in content[:1024]:
            raise InvalidRegionDecodeException("Response is not a PDF.")

        logger.info("PDF Content size: %d bytes", len(content))

        # Initialize data structures with corrected categories
        active_players = []
        dnp_players = []  # Did Not Play (NWT/DNP) - game-specific
        inactive_players = []  # Truly inactive (longer-term unavailable)
        
        game_info = {
            "game_code": self.opts["game_code"],
            "date": self.opts["date"],
            "matchup": self.opts["matchup"],
            "away_team": self.opts["away_team"],
            "home_team": self.opts["home_team"],
            "pdf_version": self.opts["version"],
            "pdf_url": self.url,
        }

        # Extract text using pdfplumber
        logger.info("Extracting text with pdfplumber")
        
        # Save content to temp file for pdfplumber
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Extract text using pdfplumber
            with pdfplumber.open(temp_file_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
            
            logger.debug("pdfplumber extracted %d characters", len(full_text))
            logger.debug("Text sample (first 500 chars):\n%s", full_text[:500])
            
        finally:
            # Clean up temp file
            os.unlink(temp_file_path)
        
        if not full_text:
            raise DownloadDataException("pdfplumber failed to extract any text from PDF")

        # Save debug text
        debug_file = f"/tmp/debug_pdfplumber_text_{self.run_id}.txt"
        try:
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(full_text)
            logger.debug("Debug text saved to: %s", debug_file)
        except Exception as e:
            logger.warning("Failed to save debug text: %s", e)

        # Parse the clean text with corrected categories
        self._parse_clean_text(full_text, active_players, dnp_players, inactive_players, game_info)

        # Set final data structure with proper categories
        self.data = {
            **game_info,  # This now includes arena, officials, attendance, etc.
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_players": active_players,
            "dnp_players": dnp_players,  # Did Not Play this game
            "inactive_players": inactive_players,  # Truly inactive/unavailable
            "total_players": len(active_players) + len(dnp_players) + len(inactive_players),
            "active_count": len(active_players),
            "dnp_count": len(dnp_players),
            "inactive_count": len(inactive_players),
            "source": "nba_gamebook_pdf",
            "debug_info": {
                "text_length": len(full_text),
                "parser_used": "pdfplumber",
                "debug_file": debug_file,
            }
        }
        
        self.decoded_data = self.data
        
        logger.info("Parsed PDF: %d active, %d DNP, %d inactive players", 
                   len(active_players), len(dnp_players), len(inactive_players))

    def _parse_clean_text(self, text: str, active_players: List[Dict], 
                         dnp_players: List[Dict], inactive_players: List[Dict], game_info: Dict) -> None:
        """Parse clean extracted text from pdfplumber."""
        
        logger.info("Parsing clean text (%d chars)", len(text))
        
        # Extract game metadata from the top of the PDF
        self._extract_game_metadata(text, game_info)
        
        lines = text.split('\n')
        current_team = None
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            logger.debug("Line %d: %s", i, line[:100])  # DEBUG level
            
            # Detect team sections  
            if 'VISITOR:' in line:
                team_match = re.search(r'VISITOR:\s*(.+?)\s*\(', line)
                if team_match:
                    current_team = team_match.group(1)
                    logger.debug("Found visitor team: %s", current_team)  # DEBUG level
                continue
            elif 'HOME:' in line:
                team_match = re.search(r'HOME:\s*(.+?)\s*\(', line)
                if team_match:
                    current_team = team_match.group(1)
                    logger.debug("Found home team: %s", current_team)  # DEBUG level
                continue
            
            # Look for NWT players (did not play - game specific)
            if ' NWT - ' in line:
                player = self._extract_nwt_from_clean_line(line, current_team)
                if player:
                    dnp_players.append(player)
                    logger.debug("Found NWT player: %s - %s", player['name'], player['dnp_reason'])  # DEBUG level
            
            # Look for DNP players (did not play - game specific)  
            elif ' DNP - ' in line:
                player = self._extract_dnp_from_clean_line(line, current_team)
                if player:
                    dnp_players.append(player)
                    logger.debug("Found DNP player: %s - %s", player['name'], player['dnp_reason'])  # DEBUG level
            
            # Look for active players (lines with minutes like "35:42")
            elif re.search(r'\d{1,2}:\d{2}', line) and current_team:
                player = self._extract_active_from_clean_line(line, current_team)
                if player:
                    active_players.append(player)
                    logger.debug("Found active player: %s (%s pts, %s min)",  # DEBUG level
                               player['name'], player.get('stats', {}).get('points', 0), 
                               player.get('stats', {}).get('minutes', '0:00'))
            
            # Look for inactive player sections (truly inactive)
            elif line.startswith('Inactive:'):
                inactive_list = self._extract_inactive_players_from_line(line, lines, i)
                inactive_players.extend(inactive_list)
                for player in inactive_list:
                    logger.debug("Found inactive player: %s - %s (%s)",  # DEBUG level
                               player['name'], player['reason'], player['team'])

        # Single summary INFO log instead of individual player logs
        logger.info("Parsed game %s: %d active, %d DNP, %d inactive players (total: %d)", 
                   game_info.get('game_code', 'unknown'),
                   len(active_players), len(dnp_players), len(inactive_players),
                   len(active_players) + len(dnp_players) + len(inactive_players))

    def _extract_game_metadata(self, text: str, game_info: Dict) -> None:
        """Extract additional game metadata from PDF header."""
        
        lines = text.split('\n')[:20]  # Look at first 20 lines for metadata
        
        for line in lines:
            line = line.strip()
            
            # Extract arena and location
            # Pattern: "Wednesday, April 10, 2024 Rocket Mortgage FieldHouse, Cleveland, OH"
            arena_match = re.search(r'\d{4}\s+(.+?),\s+([A-Za-z\s]+),\s+([A-Z]{2})', line)
            if arena_match:
                arena = arena_match.group(1).strip()
                city = arena_match.group(2).strip()
                state = arena_match.group(3).strip()
                
                game_info["arena"] = arena
                game_info["city"] = city
                game_info["state"] = state
                game_info["location"] = f"{city}, {state}"
                
                logger.debug("Found game location: %s at %s", game_info["location"], arena)  # DEBUG level
            
            # Extract officials
            # Pattern: "Officials: #24 Kevin Scott, #36 Brent Barnaky, #41 Nate Green"
            elif line.startswith('Officials:'):
                officials = self._parse_officials(line)
                if officials:
                    game_info["officials"] = officials
                    logger.debug("Found officials: %s", [f["name"] for f in officials])  # DEBUG level
            
            # Extract game duration
            # Pattern: "Game Duration: 2:10"
            elif line.startswith('Game Duration:'):
                duration_match = re.search(r'Game Duration:\s*(\d+:\d+)', line)
                if duration_match:
                    game_info["game_duration"] = duration_match.group(1)
                    logger.debug("Found game duration: %s", game_info["game_duration"])  # DEBUG level
            
            # Extract attendance
            # Pattern: "Attendance: 19432 (Sellout)" or "Attendance: 19432"
            elif line.startswith('Attendance:'):
                attendance_match = re.search(r'Attendance:\s*(\d+)(?:\s*\(([^)]+)\))?', line)
                if attendance_match:
                    game_info["attendance"] = int(attendance_match.group(1))
                    if attendance_match.group(2):
                        game_info["attendance_note"] = attendance_match.group(2)
                    logger.debug("Found attendance: %s", game_info["attendance"])  # DEBUG level

    def _parse_officials(self, officials_line: str) -> List[Dict[str, Any]]:
        """Parse officials from line like 'Officials: #24 Kevin Scott, #36 Brent Barnaky, #41 Nate Green'"""
        officials = []
        
        try:
            # Remove "Officials:" prefix
            officials_text = officials_line.replace('Officials:', '').strip()
            
            # Split by commas
            official_parts = [part.strip() for part in officials_text.split(',')]
            
            for part in official_parts:
                # Extract number and name
                # Pattern: "#24 Kevin Scott"
                match = re.match(r'#(\d+)\s+(.+)', part)
                if match:
                    number = int(match.group(1))
                    name = match.group(2).strip()
                    
                    officials.append({
                        "number": number,
                        "name": name
                    })
                else:
                    logger.debug("Could not parse official: '%s'", part)
        
        except Exception as e:
            logger.warning("Error parsing officials from '%s': %s", officials_line, e)
        
        return officials

    def _extract_inactive_players_from_line(self, line: str, all_lines: List[str], line_idx: int) -> List[Dict]:
        """Extract truly inactive players from 'Inactive:' sections."""
        inactive_list = []
        
        try:
            logger.debug("Processing inactive line: %s", line)
            
            # Generic team extraction from "Inactive: [TEAM] - [PLAYERS]" format
            team_match = re.search(r'Inactive:\s*([^-]+?)\s*-', line)
            if not team_match:
                logger.warning("Could not extract team from inactive line: %s", line)
                return inactive_list
                
            team_name = team_match.group(1).strip()
            
            # Map team abbreviations/names to full names if needed
            team = self._normalize_team_name(team_name)
            
            if not team:
                logger.warning("Could not determine team from inactive line: %s", line)
                return inactive_list
            
            # Remove "Inactive: Grizzlies - " or similar prefix
            content = re.sub(r'^Inactive:\s+\w+\s+-\s+', '', line)
            
            # Check if inactive list continues on next lines (common in PDFs)
            full_content = content
            next_line_idx = line_idx + 1
            while next_line_idx < len(all_lines):
                next_line = all_lines[next_line_idx].strip()
                # If next line looks like a continuation (doesn't start with known patterns)
                if (next_line and 
                    not next_line.startswith(('Points in the Paint', 'SCORE BY', 'Technical fouls', 'MEMO', 'Copyright')) and
                    not re.match(r'^\d+\s+[A-Za-z]', next_line)):  # Not a new player stat line
                    full_content += " " + next_line
                    next_line_idx += 1
                else:
                    break
            
            logger.debug("Full inactive content for %s: %s", team, full_content)
            
            # Split by commas to get individual players
            player_parts = [part.strip() for part in full_content.split(',') if part.strip()]
            
            for part in player_parts:
                player = self._parse_individual_inactive_player(part, team)
                if player:
                    inactive_list.append(player)
            
        except Exception as e:
            logger.warning("Error extracting inactive players from line '%s': %s", line, e)
        
        return inactive_list

    def _parse_individual_inactive_player(self, player_text: str, team: str) -> Optional[Dict]:
        """Parse individual inactive player like 'Bane (Injury/Illness - Lumbar; Disc Bulge)'"""
        try:
            logger.debug("Parsing inactive player text: '%s'", player_text)
            
            # Pattern: "PlayerName (Reason)" 
            match = re.match(r'^([A-Za-z\s\.\'Jr]+?)\s*\((.+?)\)\s*$', player_text)
            if match:
                name = match.group(1).strip()
                reason = match.group(2).strip()
                
                # Clean up name
                name = re.sub(r'\s+', ' ', name)  # Multiple spaces to single
                
                if name and len(name) > 1:
                    return {
                        "name": name,
                        "team": team,
                        "status": "inactive",
                        "reason": reason,
                        "category": "inactive"
                    }
            else:
                logger.debug("Could not parse inactive player text: '%s'", player_text)
                
        except Exception as e:
            logger.debug("Error parsing inactive player '%s': %s", player_text, e)
        
        return None

    # Keep existing methods but update for new structure
    def _extract_nwt_from_clean_line(self, line: str, team: str) -> Optional[Dict]:
        """Extract NWT player from clean line like '7 Santi Aldama NWT - Injury/Illness - Right Foot; Strain'"""
        try:
            parts = line.split(' NWT - ', 1)
            if len(parts) != 2:
                return None
            
            name_part = parts[0].strip()
            reason_part = parts[1].strip()
            
            # Remove jersey number from start
            name = re.sub(r'^\d+\s+', '', name_part).strip()
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "team": team,
                    "status": "did_not_play",
                    "dnp_reason": f"NWT - {reason_part}",
                    "category": "NWT"
                }
        except Exception as e:
            logger.debug("Error extracting NWT from line '%s': %s", line, e)
        
        return None

    def _extract_dnp_from_clean_line(self, line: str, team: str) -> Optional[Dict]:
        """Extract DNP player from clean line like '24 Marcus Morris Sr. DNP - Coach's Decision'"""
        try:
            parts = line.split(' DNP - ', 1)
            if len(parts) != 2:
                return None
            
            name_part = parts[0].strip()
            reason_part = parts[1].strip()
            
            # Remove jersey number from start
            name = re.sub(r'^\d+\s+', '', name_part).strip()
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "team": team,
                    "status": "did_not_play",
                    "dnp_reason": f"DNP - {reason_part}",
                    "category": "DNP"
                }
        except Exception as e:
            logger.debug("Error extracting DNP from line '%s': %s", line, e)
        
        return None

    def _extract_active_from_clean_line(self, line: str, team: str) -> Optional[Dict]:
        """Extract active player with full stats from line like '45 GG Jackson F 35:42 7 21 2 10 6 6 0 2 2 2 2 2 1 1 -13 22'"""
        try:
            # Find minutes pattern
            minutes_match = re.search(r'(\d{1,2}:\d{2})', line)
            if not minutes_match:
                return None
            minutes = minutes_match.group(1)
            
            # Split on minutes to get parts before and after
            before_minutes = line.split(minutes)[0].strip()
            after_minutes = line.split(minutes)[1].strip() if minutes in line else ""
            
            # Extract name from before minutes
            # Typical pattern: "45 GG Jackson F" -> want "GG Jackson"
            name_match = re.search(r'^\d+\s+([A-Za-z\s\.\'Jr]+?)\s+[FGC]?\s*$', before_minutes)
            if not name_match:
                # Try simpler pattern without position
                name_match = re.search(r'^\d+\s+([A-Za-z\s\.\'Jr]+)', before_minutes)
            
            if not name_match:
                return None
            
            name = name_match.group(1).strip()
            
            # Parse full stat line from after minutes
            # Expected order: FG FGA 3P 3PA FT FTA OR DR TOT A PF ST TO BS +/- PTS
            stats = self._parse_stat_line(after_minutes)
            
            # Add minutes to stats
            stats["minutes"] = minutes
            
            # Sanity check
            if name and len(name) > 2 and not name.isdigit():
                return {
                    "name": name,
                    "team": team,
                    "status": "active",
                    "stats": stats
                }
                
        except Exception as e:
            logger.debug("Error extracting active player from line '%s': %s", line, e)
        
        return None

    def _parse_stat_line(self, stat_text: str) -> Dict[str, Any]:
        """Parse NBA stat line into structured data."""
        # Split stats by spaces and clean
        stat_parts = [s.strip() for s in stat_text.split() if s.strip()]
        
        # Initialize with defaults
        stats = {
            "minutes": "0:00",
            "field_goals_made": 0,
            "field_goals_attempted": 0,
            "three_pointers_made": 0,
            "three_pointers_attempted": 0,
            "free_throws_made": 0,
            "free_throws_attempted": 0,
            "offensive_rebounds": 0,
            "defensive_rebounds": 0,
            "total_rebounds": 0,
            "assists": 0,
            "personal_fouls": 0,
            "steals": 0,
            "turnovers": 0,
            "blocks": 0,
            "plus_minus": 0,
            "points": 0,
            # Calculated fields
            "field_goal_percentage": 0.0,
            "three_point_percentage": 0.0,
            "free_throw_percentage": 0.0,
        }
        
        try:
            # Expected order after minutes: FG FGA 3P 3PA FT FTA OR DR TOT A PF ST TO BS +/- PTS
            if len(stat_parts) >= 16:  # Minimum expected for full stat line
                stats["field_goals_made"] = self._safe_int(stat_parts[0])
                stats["field_goals_attempted"] = self._safe_int(stat_parts[1])
                stats["three_pointers_made"] = self._safe_int(stat_parts[2])
                stats["three_pointers_attempted"] = self._safe_int(stat_parts[3])
                stats["free_throws_made"] = self._safe_int(stat_parts[4])
                stats["free_throws_attempted"] = self._safe_int(stat_parts[5])
                stats["offensive_rebounds"] = self._safe_int(stat_parts[6])
                stats["defensive_rebounds"] = self._safe_int(stat_parts[7])
                stats["total_rebounds"] = self._safe_int(stat_parts[8])
                stats["assists"] = self._safe_int(stat_parts[9])
                stats["personal_fouls"] = self._safe_int(stat_parts[10])
                stats["steals"] = self._safe_int(stat_parts[11])
                stats["turnovers"] = self._safe_int(stat_parts[12])
                stats["blocks"] = self._safe_int(stat_parts[13])
                
                # Plus/minus can be negative, handle carefully
                plus_minus_str = stat_parts[14]
                if plus_minus_str.startswith('-'):
                    stats["plus_minus"] = -self._safe_int(plus_minus_str[1:])
                else:
                    stats["plus_minus"] = self._safe_int(plus_minus_str)
                
                # Points is typically the last number
                stats["points"] = self._safe_int(stat_parts[15])
                
                # Calculate percentages
                stats["field_goal_percentage"] = self._safe_percentage(
                    stats["field_goals_made"], stats["field_goals_attempted"]
                )
                stats["three_point_percentage"] = self._safe_percentage(
                    stats["three_pointers_made"], stats["three_pointers_attempted"]
                )
                stats["free_throw_percentage"] = self._safe_percentage(
                    stats["free_throws_made"], stats["free_throws_attempted"]
                )
                
            else:
                # Fallback: try to at least get points (last number)
                if stat_parts:
                    # Look for points at the end
                    for part in reversed(stat_parts):
                        if part.isdigit():
                            stats["points"] = int(part)
                            break
                            
                logger.debug("Stat line too short (%d parts), using fallback: %s", len(stat_parts), stat_parts)
        
        except Exception as e:
            logger.debug("Error parsing stat line '%s': %s", stat_text, e)
        
        return stats

    def _safe_int(self, value: str) -> int:
        """Safely convert string to int, return 0 if invalid."""
        try:
            return int(value) if value.isdigit() else 0
        except (ValueError, AttributeError):
            return 0

    def _safe_percentage(self, made: int, attempted: int) -> float:
        """Safely calculate percentage, return 0.0 if attempted is 0."""
        try:
            return round(made / attempted, 3) if attempted > 0 else 0.0
        except (ZeroDivisionError, TypeError):
            return 0.0
    
    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics for SCRAPER_STATS log (summary only, not full data)."""
        return {
            "game_code": self.opts["game_code"],
            "matchup": self.opts["matchup"],
            "pdf_version": self.opts["version"],
            "arena": self.data.get("arena", "unknown"),
            "attendance": self.data.get("attendance", 0),
            "total_players": self.data.get("total_players", 0),
            "active_count": self.data.get("active_count", 0),
            "dnp_count": self.data.get("dnp_count", 0),
            "inactive_count": self.data.get("inactive_count", 0),
            "officials_count": len(self.data.get("officials", [])),
            "text_length": self.data.get("debug_info", {}).get("text_length", 0),
            "parser_used": self.data.get("debug_info", {}).get("parser_used", "unknown"),
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #
create_app = convert_existing_flask_scraper(GetNbaComGamebookPdf)

if __name__ == "__main__":
    main = GetNbaComGamebookPdf.create_cli_and_flask_main()
    main()