"""
main_scraper_service.py

Single Cloud Run service that routes to all scrapers based on the 'scraper' parameter.
FIXED: Import paths for sophisticated base image deployment.

Usage:
  # Start service
  python scrapers/main_scraper_service.py

  # Call any scraper
  curl -X POST https://nba-scrapers.a.run.app/scrape \
    -H "Content-Type: application/json" \
    -d '{
      "scraper": "oddsa_events_his",
      "sport": "basketball_nba", 
      "date": "2025-07-10T00:00:00Z"
    }'
"""

import os
import sys
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Import all scraper classes - FIXED for root deployment
SCRAPER_REGISTRY = {
    # Odds API scrapers
    "oddsa_events_his": ("scrapers.oddsapi.oddsa_events_his", "GetOddsApiHistoricalEvents"),  # ✅ Correct
    "oddsa_events": ("scrapers.oddsapi.oddsa_events", "GetOddsApiEvents"),  # ✅ Correct
    "oddsa_player_props": ("scrapers.oddsapi.oddsa_player_props", "GetOddsApiCurrentEventOdds"),  # ⚠️ Check this
    "oddsa_player_props_his": ("scrapers.oddsapi.oddsa_player_props_his", "GetOddsApiHistoricalEventOdds"),  # ➕ Add this
    
    # Ball Don't Lie scrapers  
    "bdl_games": ("scrapers.balldontlie.bdl_games", "BdlGamesScraper"),  # 🔧 Fixed
    "bdl_box_scores": ("scrapers.balldontlie.bdl_box_scores", "BdlBoxScoresScraper"),  # 🔧 Fixed
    "bdl_player_box_scores": ("scrapers.balldontlie.bdl_player_box_scores", "BdlPlayerBoxScoresScraper"),  # ➕ Add this
    "bdl_injuries": ("scrapers.balldontlie.bdl_injuries", "BdlInjuriesScraper"),  # ➕ Add this
    
    # ESPN scrapers
    "espn_roster": ("scrapers.espn.espn_roster_api", "GetEspnTeamRosterAPI"),  # 🔧 Fixed
    "espn_scoreboard": ("scrapers.espn.espn_scoreboard_api", "GetEspnScoreboard"),  # 🔧 Fixed
    "espn_boxscore": ("scrapers.espn.espn_game_boxscore", "GetEspnBoxscore"),  # ➕ Add this
    
    # NBA.com scrapers
    "nbac_roster": ("scrapers.nbacom.nbac_roster", "GetNbaTeamRoster"),  # 🔧 Fixed
    "nbac_schedule": ("scrapers.nbacom.nbac_current_schedule_v2_1", "GetDataNbaSeasonSchedule"),  # 🔧 Fixed
    "nbac_injury_report": ("scrapers.nbacom.nbac_injury_report", "GetNbaComInjuryReport"),  # ➕ Add this
    "nbac_play_by_play": ("scrapers.nbacom.nbac_play_by_play", "GetNbaPlayByPlayRawBackup"),  # ➕ Add this
    "nbac_player_boxscore": ("scrapers.nbacom.nbac_player_boxscore", "GetNbaComPlayerBoxscore"),  # ➕ Add this
    "nbac_player_list": ("scrapers.nbacom.nbac_player_list", "GetNbaComPlayerList"),  # ➕ Add this
}

def create_app():
    """Create the main scraper routing service."""
    app = Flask(__name__)
    load_dotenv()
    
    # Configure logging for Cloud Run
    if not app.debug:
        logging.basicConfig(level=logging.INFO)
    
    @app.route('/', methods=['GET'])
    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "healthy",
            "service": "nba-scrapers",
            "version": "1.0.0",
            "deployment": "sophisticated-base-image",
            "available_scrapers": list(SCRAPER_REGISTRY.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    
    @app.route('/scrapers', methods=['GET'])
    def list_scrapers():
        """List all available scrapers."""
        scrapers = []
        for scraper_name, (module_path, class_name) in SCRAPER_REGISTRY.items():
            scrapers.append({
                "name": scraper_name,
                "module": module_path,
                "class": class_name
            })
        
        return jsonify({
            "scrapers": scrapers,
            "count": len(scrapers)
        }), 200
    
    @app.route('/scrape', methods=['POST'])
    def route_scraper():
        """Route to the appropriate scraper based on 'scraper' parameter."""
        try:
            # Get parameters from JSON body or query params
            if request.is_json:
                params = request.get_json()
            else:
                params = request.args.to_dict()
            
            # Get scraper name
            scraper_name = params.get("scraper")
            if not scraper_name:
                return jsonify({
                    "error": "Missing required parameter: scraper",
                    "available_scrapers": list(SCRAPER_REGISTRY.keys())
                }), 400
            
            # Look up scraper in registry
            if scraper_name not in SCRAPER_REGISTRY:
                return jsonify({
                    "error": f"Unknown scraper: {scraper_name}",
                    "available_scrapers": list(SCRAPER_REGISTRY.keys())
                }), 400
            
            module_path, class_name = SCRAPER_REGISTRY[scraper_name]
            
            # Dynamic import of the scraper class - FIXED import path
            try:
                app.logger.info(f"Loading scraper: {scraper_name} from {module_path}")
                module = __import__(module_path, fromlist=[class_name])
                scraper_class = getattr(module, class_name)
                app.logger.info(f"Successfully loaded {class_name}")
            except (ImportError, AttributeError) as e:
                app.logger.error(f"Failed to import scraper {scraper_name}: {e}")
                # Add debugging info for import errors
                app.logger.error(f"Module path: {module_path}")
                app.logger.error(f"Python path: {sys.path}")
                app.logger.error(f"Working directory: {os.getcwd()}")
                return jsonify({
                    "error": f"Failed to load scraper: {scraper_name}",
                    "details": str(e),
                    "module_path": module_path,
                    "debug_info": {
                        "python_path": sys.path,
                        "working_dir": os.getcwd()
                    }
                }), 500
            
            # Remove 'scraper' from params before passing to scraper
            scraper_params = {k: v for k, v in params.items() if k != "scraper"}
            
            # Add default values
            scraper_params.setdefault("group", "prod")
            scraper_params.setdefault("debug", False)
            
            # Set debug logging if requested
            if scraper_params.get("debug"):
                logging.getLogger().setLevel(logging.DEBUG)
            
            # Run the scraper
            app.logger.info(f"Running scraper {scraper_name} with params: {scraper_params}")
            scraper = scraper_class()
            result = scraper.run(scraper_params)
            
            if result:
                return jsonify({
                    "status": "success",
                    "message": f"{scraper_name} completed successfully",
                    "scraper": scraper_name,
                    "run_id": scraper.run_id,
                    "data_summary": scraper.get_scraper_stats()
                }), 200
            else:
                return jsonify({
                    "status": "error",
                    "message": f"{scraper_name} failed",
                    "scraper": scraper_name,
                    "run_id": scraper.run_id
                }), 500
                
        except Exception as e:
            app.logger.error(f"Scraper routing error: {str(e)}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "scraper": params.get("scraper", "unknown")
            }), 500
    
    return app

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Scrapers Service")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8080)))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    
    args = parser.parse_args()
    
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
    