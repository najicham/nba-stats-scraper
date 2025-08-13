"""
GCS Path Builder Utility

Centralized utility for generating consistent GCS paths for NBA scrapers.
Integrates with existing exporter system by providing path templates that work
with the current string formatting approach (gcs_path % opts).

Usage:
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

    # In scraper class:
    exporters = [
        {
            "type": "gcs", 
            "key": GCSPathBuilder.get_path("odds_api_events"),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        }
    ]
"""

from datetime import datetime
from typing import Dict, Optional


class GCSPathBuilder:
    """
    Centralized path builder for GCS storage following operational reference standards.
    
    All paths follow the pattern: /{source}/{type}/{date}/{subdir}/{timestamp}.{ext}
    where subdir and other components vary by scraper type.
    """
    
    # Path templates using Python string formatting (compatible with existing exporter system)
    PATH_TEMPLATES = {
        # Ball Don't Lie API Scrapers
        "bdl_games": "ball-dont-lie/games/%(date)s/%(timestamp)s.json",
        "bdl_player_box_scores_by_date": "ball-dont-lie/player-box-scores/%(date)s/%(timestamp)s.json", 
        "bdl_player_box_scores_by_game": "ball-dont-lie/player-box-scores/%(date)s/game_%(game_id)s/%(timestamp)s.json",
        "bdl_box_scores": "ball-dont-lie/boxscores/%(date)s/%(timestamp)s.json",
        "bdl_active_players": "ball-dont-lie/active-players/%(date)s/%(timestamp)s.json",
        "bdl_injuries": "ball-dont-lie/injuries/%(date)s/%(timestamp)s.json",
        
        # Odds API Scrapers
        "odds_api_events": "odds-api/events/%(date)s/%(timestamp)s.json",
        "odds_api_player_props": "odds-api/player-props/%(date)s/%(event_id)s-%(teams)s/%(timestamp)s-snap-%(snap)s.json",
        "odds_api_events_history": "odds-api/events-history/%(date)s/%(timestamp)s.json", 
        "odds_api_player_props_history": "odds-api/player-props-history/%(date)s/%(event_id)s-%(teams)s/%(timestamp)s-snap-%(snap)s.json",
        "odds_api_team_players": "odds-api/players/%(date)s/%(timestamp)s.json",
        
        # ESPN Scrapers
        "espn_team_roster": "espn/rosters/%(date)s/team_%(team_abbr)s/%(timestamp)s.json",
        "espn_scoreboard": "espn/scoreboard/%(date)s/%(timestamp)s.json", 
        "espn_boxscore": "espn/boxscores/%(date)s/game-%(game_id)s/%(timestamp)s.json",
        
        # NBA.com Scrapers
        "nba_com_player_list": "nba-com/player-list/%(date)s/%(timestamp)s.json",
        "nba_com_schedule": "nba-com/schedule/%(actual_season_nba_format)s/%(timestamp)s.json",
        "nba_com_schedule_cdn": "nba-com/schedule-cdn/%(actual_season_nba_format)s/%(timestamp)s.json",
        "nba_com_scoreboard_v2": "nba-com/scoreboard-v2/%(date)s/%(timestamp)s.json",
        "nba_com_injury_report": "nba-com/injury-report/%(date)s/%(hour)s%(period)s/%(timestamp)s.json",
        "nba_com_play_by_play": "nba-com/play-by-play/%(date)s/game-%(game_id)s/%(timestamp)s.json",
        "nba_com_player_boxscore": "nba-com/player-boxscores/%(date)s/%(timestamp)s.json",
        "nba_com_team_roster": "nba-com/rosters/%(date)s/team_%(team_abbr)s/%(timestamp)s.json", 
        "nba_com_player_movement": "nba-com/player-movement/%(date)s/%(timestamp)s.json",
        
        "nba_com_schedule": "nba-com/schedule/%(actual_season_nba_format)s/%(timestamp)s.json",
        "nba_com_schedule_metadata": "nba-com/schedule-metadata/%(actual_season_nba_format)s/%(timestamp)s.json",
        "nba_com_schedule_cdn": "nba-com/schedule-cdn/%(actual_season_nba_format)s/%(timestamp)s.json",
        
        # NBA.com Gamebooks (Phase 2)
        "nba_com_gamebooks_pdf_raw": "nba-com/gamebooks-pdf/%(date)s/%(clean_game_code_dashes)s/%(timestamp)s.pdf",
        "nba_com_gamebooks_pdf_data": "nba-com/gamebooks-data/%(date)s/%(clean_game_code_dashes)s/%(timestamp)s.json",

        # Basketball Reference
        "br_season_roster": "basketball-ref/season-rosters/%(season)s/%(teamAbbr)s.json",
        
        # BettingPros Scrapers
        "bettingpros_events": "bettingpros/events/%(date)s/%(timestamp)s.json",
        "bettingpros_player_props": "bettingpros/player-props/%(market_type)s/%(date)s/%(timestamp)s.json",

        # Big Data Ball
        # "big_data_ball_play_by_play": "big-data-ball/play-by-play/%(date)s/game_%(game_id)s/%(timestamp)s.csv",
        "bigdataball_pbp": "big-data-ball/%(nba_season)s/%(date)s/game_%(game_id)s/%(filename)s.csv",
    }
    
    
    @classmethod
    def get_path(cls, template_key: str, **kwargs) -> str:
        """
        Get a GCS path template for the given template key.
        
        Args:
            template_key: Key from PATH_TEMPLATES 
            **kwargs: Additional path customizations
            
        Returns:
            Path template string compatible with current exporter system
            
        Example:
            path = GCSPathBuilder.get_path("odds_api_events")
            # Returns: "odds-api/events/%(date)s/%(timestamp)s.json"
        """
        if template_key not in cls.PATH_TEMPLATES:
            raise ValueError(f"Unknown path template key: {template_key}")
            
        return cls.PATH_TEMPLATES[template_key]
    
    @classmethod
    def add_timestamp_if_missing(cls, opts: Dict) -> Dict:
        """
        Add timestamp if not present (for unique filenames).
        
        Args:
            opts: Existing options dictionary
            
        Returns:
            Updated options dictionary with timestamp if missing
        """
        updated_opts = opts.copy()
        
        # Add timestamp if not present (you already have run_id, but timestamp is more readable)
        if "timestamp" not in updated_opts:
            updated_opts["timestamp"] = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            
        return updated_opts
    
    @classmethod
    def validate_path_opts(cls, template_key: str, opts: Dict) -> None:
        """
        Validate that all required variables for a path template are present in opts.
        
        Args:
            template_key: Key from PATH_TEMPLATES
            opts: Options dictionary with variables for formatting
            
        Raises:
            ValueError: If required variables are missing
        """
        if template_key not in cls.PATH_TEMPLATES:
            raise ValueError(f"Unknown path template key: {template_key}")
            
        template = cls.PATH_TEMPLATES[template_key]
        
        # Extract variable names from template (e.g., %(date)s -> date)
        import re
        variables = re.findall(r'%\((\w+)\)s', template)
        
        missing_vars = [var for var in variables if var not in opts]
        if missing_vars:
            raise ValueError(f"Missing required variables for {template_key}: {missing_vars}")
    
    @classmethod 
    def preview_path(cls, template_key: str, **sample_opts) -> str:
        """
        Preview what a path will look like with sample options.
        
        Args:
            template_key: Key from PATH_TEMPLATES
            **sample_opts: Sample values for path variables
            
        Returns:
            Formatted path with sample values
            
        Example:
            path = GCSPathBuilder.preview_path(
                "odds_api_events", 
                date="2025-07-21", 
                timestamp="20250721_140000"
            )
            # Returns: "odds-api/events/2025-07-21/20250721_140000.json"
        """
        template = cls.get_path(template_key)
        
        # Add standard defaults if missing
        defaults = {
            "date": "2025-07-21",
            "timestamp": "20250721_140000", 
            "game_id": "12345",
            "event_id": "67890",
            "team_abbr": "LAL",
            "hour": "5",
            "period": "PM"
        }
        
        # Merge sample_opts with defaults
        merged_opts = {**defaults, **sample_opts}
        
        try:
            return template % merged_opts
        except KeyError as e:
            raise ValueError(f"Missing required variable for preview: {e}")


# Convenience functions for easy import
def get_gcs_path(template_key: str, **kwargs) -> str:
    """Convenience function - alias for GCSPathBuilder.get_path()"""
    return GCSPathBuilder.get_path(template_key, **kwargs)


# Example usage and testing
if __name__ == "__main__":
    # Test path generation
    print("=== GCS Path Builder Examples ===")
    
    # Test by template key
    print("\n1. By Template Key:")
    print(f"Odds Events: {GCSPathBuilder.get_path('odds_api_events')}")
    print(f"Player Props: {GCSPathBuilder.get_path('odds_api_player_props')}")
    print(f"NBA Player List: {GCSPathBuilder.get_path('nba_com_player_list')}")
    
    # Test path previews
    print("\n2. Path Previews:")
    print(f"Odds Events Preview: {GCSPathBuilder.preview_path('odds_api_events')}")
    print(f"Player Props Preview: {GCSPathBuilder.preview_path('odds_api_player_props', event_id='abc123')}")
    print(f"Team Roster Preview: {GCSPathBuilder.preview_path('espn_team_roster', team_abbr='GSW')}")
    
    # Test with custom opts
    print("\n3. With Custom Options:")
    sample_opts = {
        "date": "2025-07-21",
        "timestamp": "20250721_153000",
        "event_id": "nba_game_12345"
    }
    template = GCSPathBuilder.get_path("odds_api_player_props")
    formatted = template % sample_opts
    print(f"Formatted: {formatted}")
    
    print("\n=== All Available Templates ===")
    for key in sorted(GCSPathBuilder.PATH_TEMPLATES.keys()):
        print(f"{key}: {GCSPathBuilder.PATH_TEMPLATES[key]}")
        