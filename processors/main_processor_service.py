"""
Main processor service for Cloud Run
Handles Pub/Sub messages when scrapers complete
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone
import base64
import re

# Import processors
from processors.basketball_ref.br_roster_processor import BasketballRefRosterProcessor
from processors.oddsapi.odds_api_props_processor import OddsApiPropsProcessor
from processors.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
from processors.nbacom.nbac_player_list_processor import NbacPlayerListProcessor
from processors.balldontlie.bdl_standings_processor import BdlStandingsProcessor
from processors.balldontlie.bdl_injuries_processor import BdlInjuriesProcessor
from processors.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor
from processors.balldontlie.bdl_active_players_processor import BdlActivePlayersProcessor
from processors.nbacom.nbac_player_movement_processor import NbacPlayerMovementProcessor
from processors.nbacom.nbac_scoreboard_v2_processor import NbacScoreboardV2Processor
from processors.nbacom.nbac_player_boxscore_processor import NbacPlayerBoxscoreProcessor
from processors.nbacom.nbac_play_by_play_processor import NbacPlayByPlayProcessor

from processors.espn.espn_boxscore_processor import EspnBoxscoreProcessor
from processors.espn.espn_team_roster_processor import EspnTeamRosterProcessor
from processors.espn.espn_scoreboard_processor import EspnScoreboardProcessor
from processors.bettingpros.bettingpros_player_props_processor import BettingPropsProcessor
from processors.bigdataball.bigdataball_pbp_processor import BigDataBallPbpProcessor
from processors.nbacom.nbac_referee_processor import NbacRefereeProcessor
from processors.oddsapi.odds_game_lines_processor import OddsGameLinesProcessor


# from balldontlie.bdl_boxscore_processor import BdlBoxscoreProcessor
# from nbacom.nbac_schedule_processor import NbacScheduleProcessor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Processor registry
PROCESSOR_REGISTRY = {
    'basketball-ref/season-rosters': BasketballRefRosterProcessor,
    
    'odds-api/player-props': OddsApiPropsProcessor,
    'odds-api/game-lines-history': OddsGameLinesProcessor,
    
    'nba-com/gamebooks-data': NbacGamebookProcessor,
    'nba-com/player-list': NbacPlayerListProcessor,
    
    'ball-dont-lie/standings': BdlStandingsProcessor,
    'ball-dont-lie/injuries': BdlInjuriesProcessor,
    'ball-dont-lie/boxscores': BdlBoxscoresProcessor,
    'ball-dont-lie/active-players': BdlActivePlayersProcessor,
    
    'nba-com/player-movement': NbacPlayerMovementProcessor,
    'nba-com/scoreboard-v2': NbacScoreboardV2Processor,
    'nba-com/player-boxscores': NbacPlayerBoxscoreProcessor,
    'nba-com/play-by-play': NbacPlayByPlayProcessor,
    'nba-com/referee-assignments': NbacRefereeProcessor,

    'espn/boxscores': EspnBoxscoreProcessor,
    'espn/rosters': EspnTeamRosterProcessor,
    'espn/scoreboard': EspnScoreboardProcessor,

    'bettingpros/player-props': BettingPropsProcessor,

    'big-data-ball': BigDataBallPbpProcessor,
}


@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "processors",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route('/process', methods=['POST'])
def process_pubsub():
    """
    Handle Pub/Sub messages for file processing.
    Expected message format:
    {
        "bucket": "nba-scraped-data",
        "name": "basketball_reference/season_rosters/2023-24/LAL.json",
        "timeCreated": "2024-01-15T10:30:00Z"
    }
    """
    envelope = request.get_json()
    
    if not envelope:
        return jsonify({"error": "No Pub/Sub message received"}), 400
    
    # Decode Pub/Sub message
    if 'message' not in envelope:
        return jsonify({"error": "Invalid Pub/Sub message format"}), 400
    
    try:
        # Decode the message
        pubsub_message = envelope['message']
        
        if 'data' in pubsub_message:
            data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            message = json.loads(data)
        else:
            return jsonify({"error": "No data in Pub/Sub message"}), 400
        
        # Extract file info
        bucket = message.get('bucket', 'nba-scraped-data')
        file_path = message['name']
        
        logger.info(f"Processing file: gs://{bucket}/{file_path}")
        
        # Determine processor based on file path
        processor_class = None
        for path_prefix, proc_class in PROCESSOR_REGISTRY.items():
            if path_prefix in file_path:
                processor_class = proc_class
                break
        
        if not processor_class:
            logger.warning(f"No processor found for file: {file_path}")
            return jsonify({"status": "skipped", "reason": "No processor for file type"}), 200
        
        # Extract metadata from file path
        opts = extract_opts_from_path(file_path)
        opts['bucket'] = bucket
        opts['file_path'] = file_path
        opts['project_id'] = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        
        # Process the file
        processor = processor_class()
        success = processor.run(opts)
        
        if success:
            stats = processor.get_processor_stats()
            logger.info(f"Successfully processed {file_path}: {stats}")
            return jsonify({
                "status": "success",
                "file": file_path,
                "stats": stats
            }), 200
        else:
            logger.error(f"Failed to process {file_path}")
            return jsonify({
                "status": "error",
                "file": file_path
            }), 500
            
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def extract_opts_from_path(file_path: str) -> dict:
    """
    Extract processing options from file path.
    Examples:
    - basketball_reference/season_rosters/2023-24/LAL.json
    - ball-dont-lie/standings/2024-25/2025-01-15/timestamp.json
    - ball-dont-lie/injuries/2025-01-15/timestamp.json
    - ball-dont-lie/boxscores/2021-12-04/timestamp.json
    - ball-dont-lie/active-players/2025-01-15/timestamp.json  # NEW
    """
    opts = {}
    
    if 'basketball-ref/season-rosters' in file_path:
        # Extract season and team
        parts = file_path.split('/')
        season_str = parts[-2]  # "2023-24"
        team_abbrev = parts[-1].replace('.json', '')  # "LAL"
        season_year = int(season_str.split('-')[0])  # 2023
        
        opts['season_year'] = season_year
        opts['team_abbrev'] = team_abbrev
        
    elif 'ball-dont-lie/standings' in file_path:
        # Extract date from path: ball-dont-lie/standings/2024-25/2025-01-15/timestamp.json
        parts = file_path.split('/')
        date_str = parts[-2]  # "2025-01-15"
        season_formatted = parts[-3]  # "2024-25"
        
        # Parse date
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            opts['date_recorded'] = date_obj
        except ValueError:
            logger.warning(f"Could not parse date from path: {date_str}")
        
        # Parse season year from formatted string
        try:
            season_year = int(season_formatted.split('-')[0])  # 2024
            opts['season_year'] = season_year
        except ValueError:
            logger.warning(f"Could not parse season from path: {season_formatted}")
    
    elif 'ball-dont-lie/injuries' in file_path:
        # Extract date from path: ball-dont-lie/injuries/2025-01-15/timestamp.json
        parts = file_path.split('/')
        date_str = parts[-2]  # "2025-01-15"
        
        # Parse scrape date
        try:
            from datetime import datetime
            scrape_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            opts['scrape_date'] = scrape_date
            
            # Calculate season year (Oct-Sept NBA season)
            season_year = scrape_date.year if scrape_date.month >= 10 else scrape_date.year - 1
            opts['season_year'] = season_year
            
        except ValueError:
            logger.warning(f"Could not parse date from injuries path: {date_str}")
    
    elif 'ball-dont-lie/boxscores' in file_path:
        # Extract date from path: ball-dont-lie/boxscores/2021-12-04/timestamp.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            date_str = parts[-2]  # "2021-12-04"
            
            # Parse game date
            try:
                from datetime import datetime
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                opts['game_date'] = game_date
                
                # Calculate season year (Oct-Sept NBA season)
                season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
                opts['season_year'] = season_year
                
            except ValueError:
                logger.warning(f"Could not parse date from boxscores path: {date_str}")
    
    # ADD THIS NEW CASE FOR ACTIVE PLAYERS
    elif 'ball-dont-lie/active-players' in file_path:
        # Extract date from path: ball-dont-lie/active-players/2025-01-15/timestamp.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            date_str = parts[-2]  # "2025-01-15"
            
            # Parse collection date
            try:
                from datetime import datetime
                collection_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                opts['collection_date'] = collection_date
                
                # Calculate season year (Oct-Sept NBA season)
                season_year = collection_date.year if collection_date.month >= 10 else collection_date.year - 1
                opts['season_year'] = season_year
                
            except ValueError:
                logger.warning(f"Could not parse date from active-players path: {date_str}")
    
    elif 'nba-com/scoreboard-v2' in file_path:
        # NBA.com Scoreboard V2 files have date in path
        # Format: /nba-com/scoreboard-v2/{date}/{timestamp}.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            try:
                date_str = parts[-2]  # Extract date from path
                opts['scoreDate'] = date_str
            except (IndexError, ValueError):
                pass

    elif 'espn/boxscores' in file_path:
            # Extract game info from ESPN boxscore path
            # Path format: /espn/boxscores/{date}/game_{id}/{timestamp}.json
            parts = file_path.split('/')
            for i, part in enumerate(parts):
                if part == 'boxscores' and i + 1 < len(parts):
                    opts['game_date'] = parts[i + 1]
                elif part.startswith('game_') and i + 1 < len(parts):
                    opts['espn_game_id'] = part.replace('game_', '')

    elif 'espn/rosters' in file_path:
        # Extract team and date from ESPN roster path
        # Path format: espn/rosters/{date}/team_{team_abbr}/{timestamp}.json
        parts = file_path.split('/')
        
        # Extract date
        for part in parts:
            if len(part) == 10 and part.count('-') == 2:  # YYYY-MM-DD format
                try:
                    opts['roster_date'] = part
                    break
                except:
                    pass
        
        # Extract team abbreviation from team_{abbr} folder
        for part in parts:
            if part.startswith('team_') and len(part) > 5:
                opts['team_abbr'] = part[5:]  # Remove 'team_' prefix
                break

    elif 'nba-com/player-boxscores' in file_path:  # ADD THIS BLOCK
        # Extract date from path like: /nba-com/player-boxscores/2024-01-15/timestamp.json
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file_path)
        if date_match:
            opts['date'] = date_match.group(1)

    elif 'nba-com/play-by-play' in file_path:
        # Extract game date and game ID from play-by-play path
        # Format: /nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json
        parts = file_path.split('/')
        
        # Find date part (YYYY-MM-DD format)
        for part in parts:
            if re.match(r'\d{4}-\d{2}-\d{2}', part):
                opts['game_date'] = part
                break
        
        # Find game ID from game_{gameId} directory
        for part in parts:
            if part.startswith('game_'):
                opts['nba_game_id'] = part.replace('game_', '')
                break
    
    elif 'bettingpros/player-props' in file_path:
        # Extract market type from BettingPros path
        # Pattern: /bettingpros/player-props/{market_type}/{date}/{timestamp}.json
        parts = file_path.split('/')
        try:
            if 'player-props' in parts:
                market_idx = parts.index('player-props')
                if market_idx + 1 < len(parts):
                    opts['market_type'] = parts[market_idx + 1]  # Extract 'points', 'rebounds', etc.
        except (ValueError, IndexError):
            pass

    elif 'espn/scoreboard' in file_path:
        # Extract game date from path: espn/scoreboard/{date}/{timestamp}.json
        parts = file_path.split('/')
        if len(parts) >= 3:
            opts['game_date'] = parts[-2]  # Extract date from path

    elif 'big-data-ball' in file_path or 'bigdataball' in file_path:
        # BigDataBall play-by-play files
        # Path formats: 
        # - /big-data-ball/{season}/{date}/game_{id}/{filename}.csv
        # - /bigdataball/{season}/{date}/game_{id}/{filename}.csv
        parts = file_path.split('/')
        
        # Find date part (YYYY-MM-DD format)
        for part in parts:
            if re.match(r'\d{4}-\d{2}-\d{2}', part):
                opts['game_date'] = part
                
                # Calculate season year from game date
                try:
                    from datetime import datetime
                    game_date_obj = datetime.strptime(part, '%Y-%m-%d').date()
                    season_year = game_date_obj.year if game_date_obj.month >= 10 else game_date_obj.year - 1
                    opts['season_year'] = season_year
                except ValueError:
                    logger.warning(f"Could not parse date from BigDataBall path: {part}")
                break
        
        # Find game ID from game_{gameId} directory  
        for part in parts:
            if part.startswith('game_'):
                opts['game_id'] = part.replace('game_', '')
                break

    elif 'nba-com/referee-assignments' in file_path:
        # Extract date from referee path: /nba-com/referee-assignments/{date}/{timestamp}.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            date_str = parts[-2]  # "2025-01-01"
            
            # Parse referee assignment date
            try:
                from datetime import datetime
                assignment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                opts['assignment_date'] = assignment_date
                
                # Calculate season year (Oct-Sept NBA season)
                season_year = assignment_date.year if assignment_date.month >= 10 else assignment_date.year - 1
                opts['season_year'] = season_year
                
            except ValueError:
                logger.warning(f"Could not parse date from referee path: {date_str}")

    elif 'odds-api/game-lines-history' in file_path:
        # Extract metadata from path: odds-api/game-lines-history/date/hash-teams/file.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            opts['game_date'] = parts[-3]
            opts['game_hash_teams'] = parts[-2]
            opts['filename'] = parts[-1]
            
            # Extract snapshot timestamp if available
            if 'snap-' in parts[-1]:
                snapshot_part = parts[-1].split('snap-')[-1].replace('.json', '')
                opts['snapshot_timestamp'] = snapshot_part
    
    return opts    


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)