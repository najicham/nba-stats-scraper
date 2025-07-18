# scrapers/nbacom/nbac_injury_report.py
"""
NBA.com Injury Report PDF scraper                       v2 - 2025-06-16
-----------------------------------------------------------------------
Downloads and parses the official Injury Report PDF.  Outputs a list of
records like:

    {
        "date": "03/16/2025",
        "gametime": "7:30 PM ET",
        "matchup": "LAL@BOS",
        "team": "LOS ANGELES LAKERS",
        "player": "James, LeBron",
        "status": "Questionable",
        "reason": "Left ankle soreness"
    }
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List
import json

from pdfreader import SimplePDFViewer
from pdfreader.viewer.pdfviewer import PageDoesNotExist

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException, InvalidRegionDecodeException

logger = logging.getLogger("scraper_base")


class GetNbaComInjuryReport(ScraperBase):
    """Scrapes and parses the daily NBA Injury Report PDF."""

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    required_opts = ["gamedate", "hour", "period"]  # hour: 1-12, period: AM/PM
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.BINARY
    proxy_enabled: bool = True
    # no_retry_status_codes = [403]

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/injury-report/%(season)s/%(gamedate)s/%(hour)s%(period)s/%(time)s.pdf",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nbacom_injury_report_%(gamedate)s_%(hour)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # ADD THESE CAPTURE EXPORTERS:
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
    # Additional opts helper
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        now = datetime.now(timezone.utc)
        self.opts["time"] = now.strftime("%H-%M-%S")
        year = int(self.opts["gamedate"][0:4])
        self.opts["season"] = f"{year}-{(year + 1) % 100:02d}"

    # ------------------------------------------------------------------ #
    # Option validation
    # ------------------------------------------------------------------ #
    def validate_opts(self) -> None:
        super().validate_opts()
        try:
            hour = int(self.opts["hour"])
            if not (1 <= hour <= 12):
                raise DownloadDataException("hour must be between 1 and 12")
        except ValueError:
            raise DownloadDataException("hour must be a valid number")
        
        if self.opts["period"].upper() not in {"AM", "PM"}:
            raise DownloadDataException("period must be AM or PM")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        gd = self.opts["gamedate"]
        # Convert YYYYMMDD to YYYY-MM-DD format
        if "-" not in gd:
            formatted_date = f"{gd[0:4]}-{gd[4:6]}-{gd[6:8]}"
        else:
            formatted_date = gd
        
        hour = self.opts["hour"].zfill(2)  # Pad single digits with 0
        period = self.opts["period"].upper()
        self.url = (
            f"https://ak-static.cms.nba.com/referee/injury/"
            f"Injury-Report_{formatted_date}_{hour}{period}.pdf"
        )
        logger.info("Injury Report URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Only save if we parsed at least 1 record
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        return isinstance(self.data, list) and len(self.data) > 0

    # ------------------------------------------------------------------ #
    # Decode PDF -> self.data
    # ------------------------------------------------------------------ #
    def decode_download_content(self) -> None:
        content = self.raw_response.content

        if b"not accessible in this region" in content.lower():
            raise InvalidRegionDecodeException("PDF blocked in this region.")
        if b"%PDF" not in content[:1024]:
            raise InvalidRegionDecodeException("Response is not a PDF.")

        records: List[dict] = []
        temp = {
            "date": "",
            "gametime": "",
            "matchup": "",
            "team": "",
            "player": "",
            "status": "",
            "next_state": "",
        }

        viewer = SimplePDFViewer(content)
        page_num = 0
        try:
            while True:
                viewer.render()
                self._parse_strings(viewer.canvas.strings, temp, records)
                viewer.next()
                page_num += 1
        except PageDoesNotExist:
            logger.info(
                "Finished PDF after %d pages, parsed %d records.", page_num, len(records)
            )

        if not records:
            raise DownloadDataException("Parsed 0 records from PDF.")
            
        # Set both for compatibility with base class validation and our own logic
        self.data = records
        self.decoded_data = records

        self.validate_injury_data()

    # ------------------------------------------------------------------ #
    # String parser with full state machine
    # ------------------------------------------------------------------ #
    def _parse_strings(self, strings: List[str], temp: dict, out_list: List[dict]) -> None:
        """
        Enhanced parser with bulletproof boundary detection and complete processing.
        FIXES: 
        - Allow 2-character tokens like "JT" to pass through (len(s) > 1 instead of len(s) > 2)
        - Enhanced team boundary detection to prevent text bleeding
        """
        
        def normalize_text(text):
            """Clean up text fragments"""
            # Handle G League variations with comprehensive patterns
            text = re.sub(r'\bG\s+League\s*Two-?\s*Way\b', 'G League - Two Way', text)
            text = re.sub(r'\bLeague\s*Two-?\s*Way\b', 'G League - Two Way', text)
            text = re.sub(r'\bG\s+League\s*Assignment\b', 'G League Assignment', text)
            text = re.sub(r'\bLeague\s*Assignment\b', 'G League Assignment', text)
            
            # Enhanced G League - On Assignment patterns
            text = re.sub(r'\bG\s+League\s*-?\s*On\s+Assignment\b', 'G League - On Assignment', text)
            text = re.sub(r'\bLeague\s*-?\s*On\s+Assignment\b', 'G League - On Assignment', text)
            text = re.sub(r'\bLeague\s+On\s+Assignment\b', 'G League - On Assignment', text)
            
            text = re.sub(r'Injury/Illness\s*-\s*', 'Injury/Illness - ', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()
        
        def is_likely_player_name(token):
            """Enhanced detection for player names"""
            # Common player name patterns
            if ',' in token:
                return True
            if token in ['Jr.,', 'Sr.,', 'II,', 'III,', 'IV,']:
                return True
            # Look for common last names that might appear without commas
            common_surnames = ['Brooks', 'Porter', 'McCullar', 'Thor', 'Smith', 'Johnson', 'Williams', 
                            'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez',
                            'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson', 'Thomas', 'Taylor',
                            'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson', 'White', 'Harris']
            return token in common_surnames
        
        def is_team_indicator(token):
            team_words = ['Lakers', 'Clippers', 'Warriors', 'Celtics', 'Heat', 'Bulls', 'Knicks', 
                        'Nets', 'Thunder', 'Jazz', 'Suns', 'Kings', 'Nuggets', 'Rockets',
                        'Spurs', 'Mavericks', 'Grizzlies', 'Pelicans', 'Magic', 'Hawks', 'Hornets',
                        'Pistons', 'Pacers', 'Cavaliers', '76ers', 'Raptors', 'Bucks', 'Timberwolves',
                        'Wizards', 'Blazers']
            return any(team in token for team in team_words)
        
        def is_team_city(token):
            """Enhanced team city detection to prevent text bleeding"""
            team_cities = [
                'Detroit', 'Houston', 'Golden', 'State', 'Los', 'Angeles', 'New', 'York', 
                'San', 'Antonio', 'Oklahoma', 'City', 'Miami', 'Chicago', 'Milwaukee',
                'Portland', 'Dallas', 'Phoenix', 'Denver', 'Utah', 'Sacramento', 'Memphis',
                'Orlando', 'Atlanta', 'Charlotte', 'Indiana', 'Cleveland', 'Philadelphia',
                'Toronto', 'Boston', 'Brooklyn', 'Washington', 'Minnesota'
            ]
            return token in team_cities
        
        def build_player_name(strings_list, start_idx):
            """Build complete player name and return (name, next_index)"""
            token = strings_list[start_idx]
            
            # Handle suffix patterns like "Jr.,"
            if token in ['Jr.,', 'Sr.,', 'II,', 'III,']:
                # Look backward for missing first part
                missing_part = ""
                for back_idx in range(max(0, start_idx-3), start_idx):
                    candidate = strings_list[back_idx]
                    if (candidate not in ['Out', 'Questionable', 'Doubtful', 'Probable', 'Available'] and
                        not is_team_indicator(candidate) and '@' not in candidate and
                        not re.match(r'\d{1,2}:\d{2}', candidate)):
                        missing_part = candidate
                
                last_name = f"{missing_part} {token}".strip() if missing_part else token
                first_name = strings_list[start_idx + 1] if start_idx + 1 < len(strings_list) else ""
                if last_name.endswith(','):
                    return f"{last_name} {first_name}".strip(), start_idx + 2
                else:
                    return f"{last_name}, {first_name}".strip(' ,'), start_idx + 2
            
            # Handle normal "LastName," pattern  
            elif ',' in token:
                last_name = token[:-1]
                first_name = strings_list[start_idx + 1] if start_idx + 1 < len(strings_list) else ""
                return f"{last_name}, {first_name}".strip(), start_idx + 2
            
            # Handle separated comma: "Thor , JT"
            elif (start_idx + 2 < len(strings_list) and 
                strings_list[start_idx + 1] == ',' and
                strings_list[start_idx + 2] not in ['Out', 'Questionable', 'Doubtful', 'Probable', 'Available']):
                last_name = token
                first_name = strings_list[start_idx + 2]
                return f"{last_name}, {first_name}", start_idx + 3
                
            return "", start_idx + 1
        
        # Initialize context
        current_team = temp.get("current_team", "")
        current_matchup = temp.get("current_matchup", "")
        current_gametime = temp.get("current_gametime", "")
        
        # Extract date
        for s in strings:
            if re.match(r'\d{2}/\d{2}/\d{4}', s) or re.match(r'\d{2}/\d{2}/\d{2}', s):
                temp["date"] = s
                break
        
        # Filter noise - FIXED: Allow 2-character tokens like "JT"
        skip_words = {'Injury', 'Report:', 'Page', 'of', 'Game', 'Date', 'Time', 'Matchup', 'Team', 
                    'Player', 'Name', 'Current', 'Status', 'Reason', 'AM', 'PM', 'NOT', 'YET', 'SUBMITTED'}
        
        # CRITICAL FIX: Changed len(s) > 2 to len(s) > 1 to allow "JT" through
        clean_strings = [s for s in strings if s not in skip_words and len(s) > 1 and not s.isdigit()]
        
        # Process all tokens - ENSURE WE REACH THE END
        i = 0
        while i < len(clean_strings):
            try:
                token = clean_strings[i]
                
                # ADD THIS DEBUG BLOCK - Look for Thor specifically
                if "Thor" in token or "JT" in token:
                    logger.info(f"🔍 FOUND THOR/JT at index {i}: '{token}' - Context: {clean_strings[max(0,i-3):i+4]}")
                
                # Look for the end of Martin, Jaylen to see what comes next
                if "Martin" in token:
                    logger.info(f"🔍 FOUND MARTIN at index {i}: '{token}' - Next 10 tokens: {clean_strings[i:i+10]}")
                
                # Extract game time
                if re.match(r'\d{1,2}:\d{2}', token):
                    current_gametime = token
                    if i+1 < len(clean_strings) and clean_strings[i+1] == '(ET)':
                        current_gametime += " (ET)"
                        i += 1
                    elif i+1 < len(clean_strings) and clean_strings[i+1] in ['AM', 'PM']:
                        time_suffix = clean_strings[i+1]
                        current_gametime += f" {time_suffix} ET"
                        i += 1
                    temp["current_gametime"] = current_gametime
                    i += 1
                    continue
                
                # Extract matchup
                if '@' in token and len(token) <= 10 and re.match(r'[A-Z]{3}@[A-Z]{3}', token):
                    current_matchup = token
                    temp["current_matchup"] = current_matchup
                    i += 1
                    continue
                
                # Extract team names
                if is_team_indicator(token):
                    team_parts = []
                    # Look backward for prefixes
                    if i > 0 and clean_strings[i-1] in ['Los', 'Golden', 'New', 'San', 'Oklahoma', 'Washington', 'Portland', 'Detroit', 'Chicago', 'Milwaukee']:
                        team_parts.append(clean_strings[i-1])
                    team_parts.append(token)
                    # Look forward for suffixes
                    if i < len(clean_strings)-1 and clean_strings[i+1] in ['Angeles', 'State', 'York', 'Antonio', 'City', 'Trail', 'Orleans']:
                        team_parts.append(clean_strings[i+1])
                        i += 1
                    current_team = " ".join(team_parts)
                    temp["current_team"] = current_team
                    i += 1
                    continue
                
                # Parse player records - ENHANCED DETECTION
                if (',' in token or 
                    token in ['Jr.,', 'Sr.,', 'II,', 'III,'] or
                    (i + 2 < len(clean_strings) and clean_strings[i + 1] == ',')):
                    
                    player_name, next_idx = build_player_name(clean_strings, i)
                    
                    if not player_name:
                        i += 1
                        continue
                    
                    # Find status - look ahead carefully
                    status = ""
                    j = next_idx
                    while j < len(clean_strings) and j < next_idx + 8:  # Don't look too far
                        if clean_strings[j] in ['Out', 'Questionable', 'Doubtful', 'Probable', 'Available']:
                            status = clean_strings[j]
                            j += 1
                            break
                        j += 1
                    
                    # Collect reason with ENHANCED boundary detection
                    reason_parts = []
                    while j < len(clean_strings):
                        reason_token = clean_strings[j]
                        
                        # ENHANCED stop conditions with team city detection
                        if (is_likely_player_name(reason_token) or  # Any likely player name
                            ',' in reason_token or                   # Comma indicates new player
                            reason_token in ['Out', 'Questionable', 'Doubtful', 'Probable', 'Available'] or
                            '@' in reason_token or                   # New matchup
                            is_team_indicator(reason_token) or       # Team name
                            is_team_city(reason_token) or            # ENHANCED: Team city detection
                            re.match(r'\d{1,2}:\d{2}', reason_token) or  # Time
                            reason_token in ['Jr.,', 'Sr.,', 'II,', 'III,']):
                            break
                        
                        if reason_token not in ['-', ';', '(ET)', ',']:
                            reason_parts.append(reason_token)
                        j += 1
                    
                    # Create record
                    if status and player_name.strip():
                        raw_reason = " ".join(reason_parts).strip()
                        clean_reason = normalize_text(raw_reason)
                        
                        record = {
                            "date": temp.get("date", ""),
                            "gametime": current_gametime,
                            "matchup": current_matchup,
                            "team": current_team,
                            "player": player_name,
                            "status": status,
                            "reason": clean_reason
                        }
                        out_list.append(record)
                        
                        # DEBUG: Log when we find players to track progress
                        logger.debug(f"Found player: {player_name}")
                    
                    # Continue from where reason parsing stopped
                    i = j
                else:
                    i += 1
                    
            except (IndexError, AttributeError) as e:
                logger.warning(f"Parser exception at index {i}: {e}")
                i += 1
        
        # At the end of _parse_strings method, before the temp assignment
        logger.info(f"🔍 FINAL DEBUG: Last 10 tokens processed: {clean_strings[-10:] if len(clean_strings) >= 10 else clean_strings}")
        logger.info(f"🔍 Total players found this page: {len([r for r in out_list if r.get('player')])} - Last player: {out_list[-1].get('player') if out_list else 'None'}")
        
        # Persist context
        temp["current_team"] = current_team
        temp["current_matchup"] = current_matchup  
        temp["current_gametime"] = current_gametime
        
        logger.info(f"Parser completed. Processed {len(clean_strings)} tokens, found {len(out_list)} players this page.")

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "gamedate": self.opts["gamedate"],
            "hour": self.opts["hour"],
            "records": len(self.data) if isinstance(self.data, list) else 0,
        }
    
    def validate_injury_data(self) -> None:
        """
        Comprehensive validation for injury report data to catch production issues early.
        Raises DownloadDataException if validation fails.
        """
        
        # 1. BASIC DATA STRUCTURE VALIDATION
        if not isinstance(self.data, list):
            raise DownloadDataException("Data should be a list of injury records")
        
        if len(self.data) == 0:
            raise DownloadDataException("No injury records found - PDF may be empty or parsing failed")
        
        # 2. RECORD COUNT SANITY CHECK
        # NBA typically has 15-30 games per day, ~3-8 injury records per team
        # Reasonable range: 20-600 total records
        record_count = len(self.data)
        if record_count < 5:
            raise DownloadDataException(f"Suspiciously low record count: {record_count} (expected 20-600)")
        elif record_count > 800:
            raise DownloadDataException(f"Suspiciously high record count: {record_count} (expected 20-600)")
        
        # 3. REQUIRED FIELDS VALIDATION
        required_fields = ['date', 'gametime', 'matchup', 'team', 'player', 'status', 'reason']
        for i, record in enumerate(self.data):
            for field in required_fields:
                if field not in record or not record[field]:
                    raise DownloadDataException(f"Record {i}: Missing or empty required field '{field}': {record}")
        
        # 4. NBA TEAM VALIDATION
        valid_teams = {
            'Hawks', 'Celtics', 'Nets', 'Hornets', 'Bulls', 'Cavaliers', 'Mavericks', 'Nuggets', 
            'Pistons', 'Warriors', 'Rockets', 'Pacers', 'Clippers', 'Lakers', 'Grizzlies', 
            'Heat', 'Bucks', 'Timberwolves', 'Pelicans', 'Knicks', 'Thunder', 'Magic', 
            '76ers', 'Suns', 'Blazers', 'Kings', 'Spurs', 'Raptors', 'Jazz', 'Wizards',
            # Full team names that appear in PDFs
            'Atlanta Hawks', 'Boston Celtics', 'Brooklyn Nets', 'Charlotte Hornets', 'Chicago Bulls',
            'Cleveland Cavaliers', 'Dallas Mavericks', 'Denver Nuggets', 'Detroit Pistons', 
            'Golden State Warriors', 'Houston Rockets', 'Indiana Pacers', 'Los Angeles Clippers',
            'Los Angeles Lakers', 'Memphis Grizzlies', 'Miami Heat', 'Milwaukee Bucks', 
            'Minnesota Timberwolves', 'New Orleans Pelicans', 'New York Knicks', 'Oklahoma City Thunder',
            'Orlando Magic', 'Philadelphia 76ers', 'Phoenix Suns', 'Portland Trail Blazers',
            'Sacramento Kings', 'San Antonio Spurs', 'Toronto Raptors', 'Utah Jazz', 'Washington Wizards'
        }
        
        invalid_teams = []
        for record in self.data:
            team = record['team']
            if not any(valid_team in team for valid_team in valid_teams):
                invalid_teams.append(team)
        
        if invalid_teams:
            unique_invalid = list(set(invalid_teams))
            raise DownloadDataException(f"Invalid team names found: {unique_invalid}")
        
        # 5. STATUS VALUE VALIDATION
        valid_statuses = {'Out', 'Questionable', 'Doubtful', 'Probable', 'Available'}
        invalid_statuses = []
        for record in self.data:
            status = record['status']
            if status not in valid_statuses:
                invalid_statuses.append(status)
        
        if invalid_statuses:
            unique_invalid = list(set(invalid_statuses))
            raise DownloadDataException(f"Invalid status values found: {unique_invalid} (valid: {valid_statuses})")
        
        # 6. DATE VALIDATION
        expected_date = self.opts.get('gamedate', '')
        if expected_date:
            # Convert YYYYMMDD to MM/DD/YY format for comparison
            if len(expected_date) == 8:
                exp_formatted = f"{expected_date[4:6]}/{expected_date[6:8]}/{expected_date[2:4]}"
                
                date_mismatches = []
                for record in self.data:
                    if record['date'] != exp_formatted:
                        date_mismatches.append(record['date'])
                
                if date_mismatches:
                    unique_dates = list(set(date_mismatches))
                    logger.warning(f"Date mismatch: expected {exp_formatted}, found {unique_dates}")
        
        # 7. PLAYER NAME VALIDATION
        suspicious_players = []
        for record in self.data:
            player = record['player']
            # Check for obviously broken names
            if len(player) < 3 or player.count(',') > 1 or player.startswith(',') or player.endswith(','):
                suspicious_players.append(player)
        
        if suspicious_players:
            raise DownloadDataException(f"Suspicious player names found: {suspicious_players}")
        
        # 8. MATCHUP FORMAT VALIDATION
        invalid_matchups = []
        for record in self.data:
            matchup = record['matchup']
            # Should be format like "LAL@BOS" or "OKC@DET"
            if '@' not in matchup or len(matchup) < 6 or len(matchup) > 10:
                invalid_matchups.append(matchup)
        
        if invalid_matchups:
            unique_invalid = list(set(invalid_matchups))
            raise DownloadDataException(f"Invalid matchup formats: {unique_invalid}")
        
        # 9. G LEAGUE CONSISTENCY CHECK
        g_league_variations = []
        for record in self.data:
            reason = record['reason']
            # Only flag if it contains "league" but not "G League" AND is actually G League related
            # Exclude legitimate non-G League uses like "League Suspension"
            if ('league' in reason.lower() and 
                'G League' not in reason and 
                'suspension' not in reason.lower() and
                ('two way' in reason.lower() or 'assignment' in reason.lower())):
                g_league_variations.append(reason)
        
        if g_league_variations:
            unique_variations = list(set(g_league_variations))
            logger.warning(f"Inconsistent G League formatting found: {unique_variations}")
        
        # 10. SUMMARY STATS FOR MONITORING
        stats = {
            'total_records': len(self.data),
            'unique_teams': len(set(r['team'] for r in self.data)),
            'unique_matchups': len(set(r['matchup'] for r in self.data)),
            'status_breakdown': {},
            'teams_with_most_injuries': {}
        }
        
        # Status breakdown
        for record in self.data:
            status = record['status']
            stats['status_breakdown'][status] = stats['status_breakdown'].get(status, 0) + 1
        
        # Team injury counts
        for record in self.data:
            team = record['team']
            stats['teams_with_most_injuries'][team] = stats['teams_with_most_injuries'].get(team, 0) + 1
        
        logger.info(f"VALIDATION_STATS {json.dumps(stats)}")
        logger.info("✅ All injury data validations passed")


    def get_scraper_stats(self) -> dict:
        """Enhanced stats with validation metrics"""
        base_stats = {
            "gamedate": self.opts["gamedate"],
            "hour": self.opts["hour"],
            "period": self.opts["period"],
            "records": len(self.data) if isinstance(self.data, list) else 0,
        }
        
        if isinstance(self.data, list) and len(self.data) > 0:
            # Add validation-related stats
            base_stats.update({
                "unique_teams": len(set(r.get('team', '') for r in self.data)),
                "unique_matchups": len(set(r.get('matchup', '') for r in self.data)),
                "status_counts": {
                    status: sum(1 for r in self.data if r.get('status') == status)
                    for status in ['Out', 'Questionable', 'Doubtful', 'Probable', 'Available']
                }
            })
        
        return base_stats


# ---------------------------------------------------------------------- #
# Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    gd = request.args.get("gamedate")
    hr = request.args.get("hour")
    period = request.args.get("period")
    if not gd or not hr or not period:
        return ("Missing 'gamedate', 'hour', or 'period'", 400)

    ok = GetNbaComInjuryReport().run(
        {"gamedate": gd, "hour": hr, "period": period, "group": request.args.get("group", "prod")}
    )
    return (("Injury PDF scrape failed", 500) if ok is False else ("Scrape ok", 200))

# ---------------------------------------------------------------------- #
# CLI helper
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    cli = argparse.ArgumentParser(description="NBA.com Injury Report Scraper")
    cli.add_argument("--gamedate", required=True, help="YYYYMMDD or YYYY-MM-DD")
    cli.add_argument("--hour", required=True, help="Hour (1-12)")
    cli.add_argument("--period", required=True, choices=["AM", "PM"], help="AM or PM")
    add_common_args(cli)  # This adds --group, --runId, --debug, etc.
    args = cli.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    GetNbaComInjuryReport().run(vars(args))

