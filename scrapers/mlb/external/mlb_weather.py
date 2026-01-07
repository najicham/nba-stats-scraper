"""
File: scrapers/mlb/external/mlb_weather.py

MLB Game Weather                                                  v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Weather data for MLB stadiums using OpenWeatherMap API.

Data Source: OpenWeatherMap API (https://openweathermap.org/)
- Requires API key (free tier: 1000 calls/day)
- Current weather + forecast
- Temperature, wind, humidity, precipitation

Key Weather Factors for K Predictions:
- Temperature: Colder = denser air = harder to hit = more Ks
- Wind: Strong wind affects pitcher control
- Humidity: Higher humidity = ball carries less = more Ks
- Altitude: Already factored into ballpark data

Note: Dome/retractable roof stadiums have controlled environments.

Usage:
  python scrapers/mlb/external/mlb_weather.py --team_abbr NYY --debug
  python scrapers/mlb/external/mlb_weather.py --date 2025-06-15 --debug

Environment Variables:
  OPENWEATHERMAP_API_KEY: Your OpenWeatherMap API key
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper

logger = logging.getLogger(__name__)


# Stadium coordinates for weather lookups
STADIUM_COORDINATES = {
    # American League
    "BAL": {"lat": 39.2838, "lon": -76.6218, "name": "Camden Yards", "dome": False},
    "BOS": {"lat": 42.3467, "lon": -71.0972, "name": "Fenway Park", "dome": False},
    "NYY": {"lat": 40.8296, "lon": -73.9262, "name": "Yankee Stadium", "dome": False},
    "TB": {"lat": 27.7682, "lon": -82.6534, "name": "Tropicana Field", "dome": True},
    "TOR": {"lat": 43.6414, "lon": -79.3894, "name": "Rogers Centre", "dome": True},
    "CLE": {"lat": 41.4962, "lon": -81.6852, "name": "Progressive Field", "dome": False},
    "CWS": {"lat": 41.8299, "lon": -87.6338, "name": "Guaranteed Rate Field", "dome": False},
    "DET": {"lat": 42.3390, "lon": -83.0485, "name": "Comerica Park", "dome": False},
    "KC": {"lat": 39.0517, "lon": -94.4803, "name": "Kauffman Stadium", "dome": False},
    "MIN": {"lat": 44.9817, "lon": -93.2776, "name": "Target Field", "dome": False},
    "HOU": {"lat": 29.7573, "lon": -95.3555, "name": "Minute Maid Park", "dome": True},
    "LAA": {"lat": 33.8003, "lon": -117.8827, "name": "Angel Stadium", "dome": False},
    "OAK": {"lat": 37.7516, "lon": -122.2005, "name": "Oakland Coliseum", "dome": False},
    "SEA": {"lat": 47.5914, "lon": -122.3326, "name": "T-Mobile Park", "dome": True},
    "TEX": {"lat": 32.7512, "lon": -97.0832, "name": "Globe Life Field", "dome": True},
    # National League
    "ATL": {"lat": 33.8907, "lon": -84.4677, "name": "Truist Park", "dome": False},
    "MIA": {"lat": 25.7781, "lon": -80.2196, "name": "loanDepot park", "dome": True},
    "NYM": {"lat": 40.7571, "lon": -73.8458, "name": "Citi Field", "dome": False},
    "PHI": {"lat": 39.9061, "lon": -75.1665, "name": "Citizens Bank Park", "dome": False},
    "WSH": {"lat": 38.8730, "lon": -77.0074, "name": "Nationals Park", "dome": False},
    "CHC": {"lat": 41.9484, "lon": -87.6553, "name": "Wrigley Field", "dome": False},
    "CIN": {"lat": 39.0979, "lon": -84.5082, "name": "Great American Ball Park", "dome": False},
    "MIL": {"lat": 43.0280, "lon": -87.9712, "name": "American Family Field", "dome": True},
    "PIT": {"lat": 40.4469, "lon": -80.0057, "name": "PNC Park", "dome": False},
    "STL": {"lat": 38.6226, "lon": -90.1928, "name": "Busch Stadium", "dome": False},
    "AZ": {"lat": 33.4455, "lon": -112.0667, "name": "Chase Field", "dome": True},
    "COL": {"lat": 39.7559, "lon": -104.9942, "name": "Coors Field", "dome": False},
    "LAD": {"lat": 34.0739, "lon": -118.2400, "name": "Dodger Stadium", "dome": False},
    "SD": {"lat": 32.7076, "lon": -117.1570, "name": "Petco Park", "dome": False},
    "SF": {"lat": 37.7786, "lon": -122.3893, "name": "Oracle Park", "dome": False},
}


class MlbWeatherScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB stadium weather using OpenWeatherMap API.

    Provides weather data that can affect K rates:
    - Temperature: Colder = more Ks (denser air)
    - Wind speed/direction: Affects pitcher control
    - Precipitation: May affect grip

    Note: Returns controlled environment data for dome stadiums.
    """

    scraper_name = "mlb_weather"
    required_params = []
    optional_params = {
        "team_abbr": None,   # Single team's stadium
        "all_stadiums": "false",  # Get weather for all stadiums
        "api_key": None,     # OpenWeatherMap API key
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-external/weather/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_weather_%(date)s_%(timestamp)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Get API key from opts or environment
        if not self.opts.get("api_key"):
            self.opts["api_key"] = os.getenv("OPENWEATHERMAP_API_KEY")

    _API_ROOT = "https://api.openweathermap.org/data/2.5/weather"

    def set_url(self) -> None:
        # URL will be set dynamically per stadium
        self.url = self._API_ROOT

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "mlb-weather-scraper/1.0",
            "Accept": "application/json",
        }

    def download(self) -> None:
        """Override download to fetch weather for multiple stadiums."""
        api_key = self.opts.get("api_key")

        if not api_key:
            logger.warning("No OpenWeatherMap API key provided. Using mock data.")
            self.download_data = self._get_mock_weather_data()
            return

        stadiums_to_fetch = []

        if self.opts.get("all_stadiums") == "true":
            stadiums_to_fetch = list(STADIUM_COORDINATES.keys())
        elif self.opts.get("team_abbr"):
            team = self.opts["team_abbr"].upper()
            if team in STADIUM_COORDINATES:
                stadiums_to_fetch = [team]
            else:
                raise ValueError(f"Unknown team abbreviation: {team}")
        else:
            # Default to all stadiums
            stadiums_to_fetch = list(STADIUM_COORDINATES.keys())

        weather_data = []
        for team_abbr in stadiums_to_fetch:
            stadium = STADIUM_COORDINATES[team_abbr]

            # Skip dome stadiums - they have controlled environments
            if stadium.get("dome"):
                weather_data.append(self._get_dome_weather(team_abbr, stadium))
                continue

            try:
                weather = self._fetch_weather(stadium["lat"], stadium["lon"], api_key)
                weather["team_abbr"] = team_abbr
                weather["stadium_name"] = stadium["name"]
                weather["is_dome"] = False
                weather_data.append(weather)
            except Exception as e:
                logger.error("Error fetching weather for %s: %s", team_abbr, e)
                weather_data.append(self._get_error_weather(team_abbr, stadium, str(e)))

        self.download_data = weather_data

    def _fetch_weather(self, lat: float, lon: float, api_key: str) -> Dict[str, Any]:
        """Fetch weather from OpenWeatherMap API."""
        params = {
            "lat": lat,
            "lon": lon,
            "appid": api_key,
            "units": "imperial",  # Fahrenheit, mph
        }

        resp = self.http_downloader.get(
            self._API_ROOT,
            headers=self.headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        return {
            "temperature_f": data.get("main", {}).get("temp"),
            "feels_like_f": data.get("main", {}).get("feels_like"),
            "humidity_pct": data.get("main", {}).get("humidity"),
            "wind_speed_mph": data.get("wind", {}).get("speed"),
            "wind_direction_deg": data.get("wind", {}).get("deg"),
            "wind_gust_mph": data.get("wind", {}).get("gust"),
            "conditions": data.get("weather", [{}])[0].get("main"),
            "description": data.get("weather", [{}])[0].get("description"),
            "clouds_pct": data.get("clouds", {}).get("all"),
            "pressure_hpa": data.get("main", {}).get("pressure"),
            "visibility_m": data.get("visibility"),
        }

    def _get_dome_weather(self, team_abbr: str, stadium: Dict) -> Dict[str, Any]:
        """Return controlled environment data for dome stadiums."""
        return {
            "team_abbr": team_abbr,
            "stadium_name": stadium["name"],
            "is_dome": True,
            "temperature_f": 72,  # Standard dome temp
            "feels_like_f": 72,
            "humidity_pct": 50,
            "wind_speed_mph": 0,
            "wind_direction_deg": None,
            "wind_gust_mph": None,
            "conditions": "Dome",
            "description": "climate controlled",
            "clouds_pct": 0,
            "k_weather_factor": 1.0,  # Neutral
        }

    def _get_error_weather(self, team_abbr: str, stadium: Dict, error: str) -> Dict[str, Any]:
        """Return error placeholder for failed fetches."""
        return {
            "team_abbr": team_abbr,
            "stadium_name": stadium["name"],
            "is_dome": stadium.get("dome", False),
            "error": error,
            "temperature_f": None,
            "k_weather_factor": 1.0,  # Default neutral
        }

    def _get_mock_weather_data(self) -> List[Dict[str, Any]]:
        """Return mock weather data when API key is not available."""
        mock_data = []
        for team_abbr, stadium in STADIUM_COORDINATES.items():
            if stadium.get("dome"):
                mock_data.append(self._get_dome_weather(team_abbr, stadium))
            else:
                mock_data.append({
                    "team_abbr": team_abbr,
                    "stadium_name": stadium["name"],
                    "is_dome": False,
                    "temperature_f": 75,  # Default nice day
                    "feels_like_f": 75,
                    "humidity_pct": 50,
                    "wind_speed_mph": 5,
                    "wind_direction_deg": 180,
                    "conditions": "Clear",
                    "description": "mock data - no API key",
                    "k_weather_factor": 1.0,
                })
        return mock_data

    def validate_download_data(self) -> None:
        if not self.download_data:
            raise ValueError("No weather data retrieved")

    def transform_data(self) -> None:
        """Transform weather data and calculate K factors."""
        weather_list = self.download_data

        # Calculate K weather factors
        for w in weather_list:
            if not w.get("error") and not w.get("is_dome"):
                w["k_weather_factor"] = self._calculate_k_factor(w)

        # Sort by K factor (most favorable for Ks first)
        weather_sorted = sorted(
            weather_list,
            key=lambda x: x.get("k_weather_factor", 1.0),
            reverse=True
        )

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "OpenWeatherMap",
            "stadiumCount": len(weather_list),
            "weather": weather_sorted,
            "domeStadiums": [w for w in weather_list if w.get("is_dome")],
            "outdoorStadiums": [w for w in weather_list if not w.get("is_dome")],
            "favorableKWeather": [w for w in weather_sorted if w.get("k_weather_factor", 1) > 1.02],
        }

        logger.info("Processed weather for %d stadiums", len(weather_list))

    def _calculate_k_factor(self, weather: Dict[str, Any]) -> float:
        """
        Calculate K weather factor based on conditions.

        Returns multiplier where:
        - > 1.0 = more Ks expected
        - < 1.0 = fewer Ks expected
        - 1.0 = neutral

        Factors:
        - Cold weather (< 60°F): +2% Ks (denser air)
        - Hot weather (> 90°F): -1% Ks (tired pitchers)
        - High humidity (> 70%): +1% Ks (ball doesn't carry)
        - Strong wind (> 15 mph): -1% Ks (affects control)
        """
        factor = 1.0

        temp = weather.get("temperature_f", 75)
        humidity = weather.get("humidity_pct", 50)
        wind = weather.get("wind_speed_mph", 5)

        # Temperature adjustment
        if temp and temp < 60:
            factor += 0.02  # Cold = more Ks
        elif temp and temp > 90:
            factor -= 0.01  # Hot = tired pitchers

        # Humidity adjustment
        if humidity and humidity > 70:
            factor += 0.01  # High humidity = ball doesn't carry

        # Wind adjustment
        if wind and wind > 15:
            factor -= 0.01  # Strong wind = less control

        return round(factor, 3)

    def get_scraper_stats(self) -> dict:
        return {
            "stadiumCount": self.data.get("stadiumCount", 0),
            "domeCount": len(self.data.get("domeStadiums", [])),
        }


create_app = convert_existing_flask_scraper(MlbWeatherScraper)

if __name__ == "__main__":
    main = MlbWeatherScraper.create_cli_and_flask_main()
    main()
